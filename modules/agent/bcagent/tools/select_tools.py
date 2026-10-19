"""``cad.select`` namespace — M1 subset: selection (session state, never doc_version).

Implemented (contract §6.2; m1-module-contracts §8):

- ``cad.select.get``    — current selection (— · read-only)
- ``cad.select.set``    — replace/add/remove (— · **propose**; non-transactional:
  selection bumps ``selection_epoch``, NEVER ``doc_version`` — contract §6.2)
- ``cad.select.count``  — selection size (— · read-only)
- ``cad.select.filter`` — query ids by predicate (— · read-only, paginated)

``cad.select.filter`` implements the contract's RESTRICTED query subset — a tiny
hand-written parser (NO ``eval``/``exec`` anywhere in bcagent; asserted by the
security-boundary tests):

- properties: ``type``, ``layer``, ``color``, ``linetype`` + geometric
  ``length``, ``radius``
- operators: ``==``, ``!=``, ``<``, ``>`` (the contract §6.2 comparison set)
- combination: ``&&`` only (no ``||`` at M1)
- string properties (type/layer/linetype) accept only quoted string values and only
  ``==``/``!=``; numeric properties accept numbers only
- a property that does not apply to an entity kind (e.g. ``radius`` on a line) or
  is unset (``color`` = ByLayer) evaluates to False for every operator — documented
  subset semantics (contract: "unavailable → omitted, never faked" applied to
  predicates)

Geometric property definitions (document units; angles degrees about +Z):

- ``length``: line = |p2−p1|; circle = circumference 2πr; arc = r·Δθ with
  Δθ = (end−start) mod 360° in radians; degenerate arc (start == end) → 0.
- ``radius``: circle/arc only.
"""

from __future__ import annotations

import math
import re

from ..contract import ValidationError
from .base import (
    ToolContext,
    ToolSpec,
    get_entity,
    id_list,
    paginate,
    selection_digest,
)

_QUERY_TOKEN = re.compile(
    r"""\s*(?:
        (?P<op>&&|==|!=|<=|>=|<|>)
      | "(?P<str>(?:[^"\\]|\\.)*)"
      | (?P<num>-?\d+(?:\.\d+)?)
      | (?P<prop>[A-Za-z_][A-Za-z0-9_]*)
    )\s*""",
    re.VERBOSE,
)

_STRING_PROPS = frozenset({"type", "layer", "linetype"})
_NUMBER_PROPS = frozenset({"color", "length", "radius"})
_ALL_PROPS = _STRING_PROPS | _NUMBER_PROPS
_SUPPORTED_OPS = frozenset({"==", "!=", "<", ">"})
_ARC_EPS = 1e-12


def _tokenize(query: str):
    tokens = []
    pos = 0
    while pos < len(query):
        match = _QUERY_TOKEN.match(query, pos)
        if match is None or match.end() == pos:
            raise ValidationError(
                "query cannot be parsed at this position",
                details={"query": query, "position": pos},
            )
        pos = match.end()
        if match.group("op") is not None:
            tokens.append(("op", match.group("op")))
        elif match.group("str") is not None:
            # unescape \" and \\ only
            value = re.sub(r"\\(.)", r"\1", match.group("str"))
            tokens.append(("str", value))
        elif match.group("num") is not None:
            tokens.append(("num", float(match.group("num"))))
        else:
            tokens.append(("prop", match.group("prop")))
    return tokens


def _parse_query(query: str):
    """Parse the restricted predicate language into [(prop, op, value), …]
    joined by && (all must hold). Raises CAD_E_VALIDATION on anything else."""
    if not isinstance(query, str):
        raise ValidationError("query must be a string", details={"query": query})
    tokens = _tokenize(query)
    predicates = []
    pos = 0
    # states: "prop" (expect property) -> "op" -> "value" -> "and" (expect && or end)
    expect = "prop"
    pending = None
    while pos < len(tokens):
        kind, value = tokens[pos]
        pos += 1
        if expect == "and":
            if kind == "op" and value == "&&":
                expect = "prop"
            else:
                raise ValidationError(
                    "predicates must be combined with && only",
                    details={"query": query, "near": value},
                )
        elif expect == "prop":
            if kind != "prop" or value not in _ALL_PROPS:
                raise ValidationError(
                    "expected a query property "
                    f"(one of {sorted(_ALL_PROPS)})",
                    details={"query": query, "near": value},
                )
            pending = [value]
            expect = "op"
        elif expect == "op":
            if kind != "op" or value == "&&":
                raise ValidationError(
                    "expected a comparison operator",
                    details={"query": query, "near": value},
                )
            if value not in _SUPPORTED_OPS:
                raise ValidationError(
                    f"operator {value} is not in the M1 subset "
                    f"(allowed: {sorted(_SUPPORTED_OPS)})",
                    details={"query": query},
                )
            if value in ("<", ">") and pending[0] in _STRING_PROPS:
                raise ValidationError(
                    f"ordering comparisons are not supported for the string "
                    f"property '{pending[0]}' at M1",
                    details={"query": query},
                )
            pending.append(value)
            expect = "value"
        else:  # expect == "value"
            if pending[0] in _STRING_PROPS and kind != "str":
                raise ValidationError(
                    f"property '{pending[0]}' compares against a quoted string",
                    details={"query": query},
                )
            if pending[0] in _NUMBER_PROPS and kind != "num":
                raise ValidationError(
                    f"property '{pending[0]}' compares against a number",
                    details={"query": query},
                )
            if kind not in ("str", "num"):
                raise ValidationError(
                    "expected a value",
                    details={"query": query, "near": value},
                )
            predicates.append(tuple(pending + [value]))
            pending = None
            expect = "and"
    if expect != "and" or not predicates:
        raise ValidationError(
            "query is empty or incomplete",
            details={"query": query},
        )
    return predicates


def _entity_length(entity) -> float | None:
    kind = entity.kind
    if kind == "line":
        (x1, y1, _), (x2, y2, _) = entity.p1, entity.p2
        return math.hypot(x2 - x1, y2 - y1)
    if kind == "circle":
        return 2.0 * math.pi * float(entity.radius)
    if kind == "arc":
        if abs(entity.end_angle - entity.start_angle) < _ARC_EPS:
            return 0.0
        sweep = math.radians((entity.end_angle - entity.start_angle) % 360.0)
        return float(entity.radius) * sweep
    return None


def _entity_radius(entity) -> float | None:
    if entity.kind in ("circle", "arc"):
        return float(entity.radius)
    return None


def _matches(entity, prop: str, op: str, value) -> bool:
    if prop == "type":
        left = entity.kind
    elif prop == "layer":
        left = entity.layer
    elif prop == "linetype":
        left = entity.linetype
    elif prop == "color":
        left = entity.color  # None = ByLayer -> no explicit ACI: predicate False
    elif prop == "length":
        left = _entity_length(entity)
    elif prop == "radius":
        left = _entity_radius(entity)
    else:  # pragma: no cover — parser already restricts the property set
        return False
    if left is None:
        return False  # property not applicable/unset — never faked
    if op == "==":
        return left == value
    if op == "!=":
        return left != value
    if op == "<":
        return left < value
    return left > value


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _select_get(ctx: ToolContext, args: dict) -> dict:
    state = ctx.doc.selection
    ids = sorted(state.ids)
    return {
        "entities": ids,
        "selection_epoch": state.epoch,
        "digest": selection_digest(ids),
    }


def _select_set(ctx: ToolContext, args: dict) -> dict:
    ids = id_list(args)
    mode = args.get("mode")
    if mode not in ("replace", "add", "remove"):
        raise ValidationError(
            "mode must be one of: replace, add, remove",
            details={"field": "mode", "got": mode},
        )
    # every referenced id must exist (unknown id -> CAD_E_ENTITY_NOT_FOUND)
    for entity_id in ids:
        get_entity(ctx.doc, entity_id)
    state = ctx.doc.selection
    if mode == "replace":
        state.set(ids)
    elif mode == "add":
        state.add(ids)
    else:
        state.remove(ids)
    new_ids = sorted(state.ids)
    return {
        "entities": new_ids,
        "selection_epoch": state.epoch,
        "digest": selection_digest(new_ids),
    }


def _select_count(ctx: ToolContext, args: dict) -> dict:
    state = ctx.doc.selection
    return {"count": len(state.ids), "selection_epoch": state.epoch}


def _select_filter(ctx: ToolContext, args: dict) -> dict:
    by_type = args.get("by_type")
    by_layer = args.get("by_layer")
    for field_name, field_value in (("by_type", by_type), ("by_layer", by_layer)):
        if field_value is not None and not isinstance(field_value, (list, tuple)):
            raise ValidationError(
                f"{field_name} must be an array",
                details={"field": field_name},
            )
    by_type = set(by_type) if by_type else None
    by_layer = set(by_layer) if by_layer else None
    # absent query -> match all; a PRESENT query (even empty string) must parse
    predicates = []
    if args.get("query") is not None:
        predicates = _parse_query(args["query"])
    matched = []
    for entity in ctx.doc.entities():  # insertion order — stable
        if by_type is not None and entity.kind not in by_type:
            continue
        if by_layer is not None and entity.layer not in by_layer:
            continue
        if all(_matches(entity, p, o, v) for p, o, v in predicates):
            matched.append(entity.id)
    page, next_cursor = paginate(args, sorted(matched))
    result = {"ids": page, "total": len(matched)}
    if next_cursor is not None:
        result["next_cursor"] = next_cursor
    return result


TOOL_SPECS = [
    ToolSpec(tool_id="cad.select.get", run=_select_get),
    ToolSpec(tool_id="cad.select.set", run=_select_set, min_mode="propose"),
    ToolSpec(tool_id="cad.select.count", run=_select_count),
    ToolSpec(tool_id="cad.select.filter", run=_select_filter),
]
