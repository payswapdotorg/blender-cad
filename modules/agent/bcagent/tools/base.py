"""Tool spec plumbing + shared argument/geometry helpers for the M1 tool subset.

Shared vocabulary for every ``bcagent.tools.*`` module:

- :class:`ToolSpec` — one ``cad.<ns>.<verb>`` tool: its id, transactional flag,
  minimum mode, required permission classes, and the run callable.
- :class:`ToolContext` — what a tool may touch: the session, the bcdoc Document and
  a back-reference to the adapter (used only by ``cad.system.capabilities``).
- Argument helpers that raise the contract's structured errors (never bare
  ``TypeError``/``KeyError`` leaking to the caller as ``CAD_E_INTERNAL``).

Wire conventions implemented here (contract §2):

- ``point3``/``vec3`` arguments arrive as ``[x, y, z]`` number arrays and are
  converted to tuples in document order.
- Entities are serialized to the wire shape of contract §6.3 (``id``, ``type``,
  ``from``/``to`` | ``center``/``radius`` | …, plus the common properties).
- Pagination (contract §2): ``limit`` default 100 max 1000, opaque ``cursor``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Callable

from ..contract import (
    EntityNotFoundError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# bcdoc missing-entity mapping
# ---------------------------------------------------------------------------

# m1-module-contracts §3.2 does not pin the exception type Document.get raises for
# an unknown id (a contract gap — recorded in the spike/worklog). The adapter
# therefore accepts both plain mapping exceptions and a typed bcdoc error if the
# document module defines one. The tuple is computed once at import.
_NOT_FOUND_EXCS: tuple = (KeyError, LookupError)
try:  # pragma: no cover - depends on worker 3-b's exact error surface
    from bcdoc import errors as _bcdoc_errors  # type: ignore

    for _name in ("EntityNotFound", "EntityNotFoundError", "NotFound"):
        _cls = getattr(_bcdoc_errors, _name, None)
        if isinstance(_cls, type) and issubclass(_cls, BaseException):
            _NOT_FOUND_EXCS = _NOT_FOUND_EXCS + (_cls,)
            break
except Exception:  # bcdoc absent at authoring time -> tuple stays (KeyError, LookupError)
    pass


def get_entity(doc, entity_id):
    """Fetch an entity or raise the structured ``CAD_E_ENTITY_NOT_FOUND``.

    Accepts any id type bcdoc uses (uuid hex strings at v0). Malformed ids are a
    validation error; well-formed-but-unknown ids are a not-found error.
    """
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValidationError(
            "entity id must be a non-empty string",
            details={"id": entity_id},
        )
    try:
        return doc.get(entity_id)
    except _NOT_FOUND_EXCS as exc:
        raise EntityNotFoundError(
            f"entity not found: {entity_id}",
            details={"id": entity_id},
        ) from exc


# ---------------------------------------------------------------------------
# Spec + context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool may touch. The Document is ONLY mutated through bcdoc
    transactions (the adapter opens them for transactional tools — binding rule,
    glossary §6 / contract §8)."""

    session: object      # bcagent.sessions.Session
    doc: object          # bcdoc.document.Document
    adapter: object      # bcagent.adapter.CadToolAdapter


@dataclass(frozen=True)
class ToolSpec:
    """One ``cad.*`` tool: requirements + implementation.

    ``run(ctx, args) -> dict`` returns the tool's ``result`` object (the adapter
    wraps it into the contract §2 envelope). Transactional tools never open their
    own transaction — the adapter does, exactly once (one undo step, contract §4).
    """

    tool_id: str
    run: Callable[[ToolContext, dict], dict]
    transactional: bool = False
    min_mode: str = "read-only"
    classes: tuple = ()
    #: contract registry version the tool appeared in (all M1 tools: v1.0 §6 tables)
    version_added: str = "1.0"
    #: For transactional tools: does the ADAPTER open the bcdoc transaction?
    #: Default True. False means the tool implementation manages its own single
    #: transaction (e.g. ``cad.io.import_dxf`` — bcio's import runs inside ONE
    #: transaction of its own and bcdoc v0 does not nest transactions). The
    #: adapter still enforces the base_doc_version precondition BEFORE the tool
    #: runs, so R1 holds either way; the one-undo-step guarantee comes from the
    #: single transaction whichever side opens it.
    adapter_managed_transaction: bool = True


# ---------------------------------------------------------------------------
# Argument helpers (raise structured errors, never bare builtins)
# ---------------------------------------------------------------------------


def require_args(args: dict, key: str):
    """Return ``args[key]`` or raise ``CAD_E_VALIDATION`` (missing request field)."""
    if key not in args:
        raise ValidationError(
            f"missing required argument: {key}",
            details={"field": key},
        )
    return args[key]


def optional(args: dict, key: str, default=None):
    """Return ``args[key]`` when present (not None) else ``default``."""
    value = args.get(key)
    return default if value is None else value


def require_str(args: dict, key: str) -> str:
    value = require_args(args, key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"argument {key} must be a non-empty string",
            details={"field": key, "got_type": type(value).__name__},
        )
    return value


def point3(value, name: str) -> tuple:
    """Validate a ``[x, y, z]`` point/vec argument -> tuple of 3 finite floats."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValidationError(
            f"{name} must be a [x, y, z] array of 3 numbers",
            details={"field": name, "got": value},
        )
    out = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise ValidationError(
                f"{name} components must be numbers",
                details={"field": name, "component": component},
            )
        component = float(component)
        if not math.isfinite(component):
            raise ValidationError(
                f"{name} components must be finite numbers",
                details={"field": name, "component": component},
            )
        out.append(component)
    return tuple(out)


def number(value, name: str, *, positive: bool = False, nonzero: bool = False) -> float:
    """Validate a numeric argument (finite; optionally > 0 / != 0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(
            f"{name} must be a number",
            details={"field": name, "got_type": type(value).__name__},
        )
    value = float(value)
    if not math.isfinite(value):
        raise ValidationError(
            f"{name} must be a finite number",
            details={"field": name, "got": value},
        )
    if positive and value <= 0:
        raise ValidationError(
            f"{name} must be > 0",
            details={"field": name, "got": value},
        )
    if nonzero and value == 0:
        raise ValidationError(
            f"{name} must be non-zero",
            details={"field": name, "got": value},
        )
    return value


def int_in(value, name: str, *, minimum: int | None = None,
           maximum: int | None = None) -> int:
    """Validate an integer argument (bools rejected)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            f"{name} must be an integer",
            details={"field": name, "got_type": type(value).__name__},
        )
    if minimum is not None and value < minimum:
        raise ValidationError(
            f"{name} must be >= {minimum}",
            details={"field": name, "got": value},
        )
    if maximum is not None and value > maximum:
        raise ValidationError(
            f"{name} must be <= {maximum}",
            details={"field": name, "got": value},
        )
    return value


def id_list(args: dict, key: str = "ids", *, required: bool = True) -> list:
    """Validate a list-of-entity-ids argument (strings, deduplicated, order kept)."""
    value = args.get(key) if not required else require_args(args, key)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError(
            f"{key} must be an array of entity ids",
            details={"field": key, "got_type": type(value).__name__},
        )
    seen = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(
                f"{key} entries must be non-empty strings",
                details={"field": key, "entry": item},
            )
        if item not in seen:
            seen.append(item)
    return seen


# ---------------------------------------------------------------------------
# Pagination (contract §2: limit default 100 max 1000, opaque cursor)
# ---------------------------------------------------------------------------


def clamp_limit(args: dict) -> int:
    limit = args.get("limit", 100)
    if limit is None:
        return 100
    return int_in(limit, "limit", minimum=1, maximum=1000)


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        offset = payload["o"]
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("bad offset")
        return offset
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValidationError(
            "invalid cursor", details={"cursor": cursor}
        ) from exc


def paginate(args: dict, items: list):
    """Slice ``items`` by ``limit``/``cursor``; returns ``(page, next_cursor|None)``.

    ``items`` must already be in the tool's canonical deterministic order (stable
    across calls) so cursors remain valid.
    """
    limit = clamp_limit(args)
    offset = 0
    cursor = args.get("cursor")
    if cursor is not None:
        if not isinstance(cursor, str):
            raise ValidationError(
                "cursor must be a string", details={"cursor": cursor}
            )
        offset = _decode_cursor(cursor)
    page = items[offset:offset + limit]
    next_cursor = None
    if offset + limit < len(items):
        next_cursor = _encode_cursor(offset + limit)
    return page, next_cursor


# ---------------------------------------------------------------------------
# Wire serialization of entities (contract §6.3 example shape)
# ---------------------------------------------------------------------------


def entity_dict(entity) -> dict:
    """bcdoc entity -> contract wire object.

    Common: ``id``, ``type``, ``handle``, ``layer``, ``color`` (None = ByLayer),
    ``linetype``. Geometry per kind (document units, WCS — contract §2):
    line ``from``/``to``; circle ``center``/``radius``; arc adds
    ``start_angle``/``end_angle`` (degrees CCW about +Z).
    """
    out = {
        "id": entity.id,
        "type": entity.kind,
        "handle": entity.handle,
        "layer": entity.layer,
        "color": entity.color,
        "linetype": entity.linetype,
    }
    kind = entity.kind
    if kind == "line":
        out["from"] = [float(v) for v in entity.p1]
        out["to"] = [float(v) for v in entity.p2]
    elif kind == "circle":
        out["center"] = [float(v) for v in entity.center]
        out["radius"] = float(entity.radius)
    elif kind == "arc":
        out["center"] = [float(v) for v in entity.center]
        out["radius"] = float(entity.radius)
        out["start_angle"] = float(entity.start_angle)
        out["end_angle"] = float(entity.end_angle)
    else:  # pragma: no cover — bcdoc v0 has only line/circle/arc (m1 contracts §3.1)
        raise ValidationError(
            f"entity kind not serializable at M1: {kind}",
            details={"kind": kind},
        )
    return out


def selection_digest(ids) -> str:
    """Stable digest of a selection id set (contract §6.2 ``digest: string``):
    ``sha256:<hex>`` over the newline-joined SORTED ids (empty selection is defined
    as the digest of the empty string)."""
    joined = "\n".join(sorted(ids)).encode()
    return "sha256:" + hashlib.sha256(joined).hexdigest()
