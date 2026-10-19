"""Shared prompt/selection helpers for bcdraft command implementations.

These are steps-generator utilities: ``ask_point`` etc. yield Requests and
return converted values, so both command drivers (blocking Runner via
``run_steps``, and the modal viewport operator via StepDriver) execute the
exact same logic (contract §4, m1-module-contracts.md).

M2 additions (m2-module-contracts.md §3/§4):

* ``ask_point`` is the single precision-resolution hook — mouse-source
  points run through ``precision.resolve_point`` (osnap/grid/ortho), plain
  numbers arriving as ``distance`` values (direct distance entry) convert
  via ``precision.dde_point``, and the ``osnap:`` one-shot keyword records
  ``ctx.pending_osnap`` and re-asks. Typed points pass through UNCHANGED
  (M1 determinism: scripted tests stay exact).
* ``select_ids`` accepts the selection-mode keywords All / Previous /
  Window / Crossing / Last (W-D's ``bcdraft.selection`` provides the
  geometry behind them — pinned signatures) and records every non-empty
  resolution on ``doc.last_selection_ids`` (the Previous pool).
* ``split_locked`` partitions a selection into (modifiable, locked-layer)
  ids — locked-layer entities are selectable but NOT modifiable; W-D's
  modify commands consume it with this exact name.
"""

from __future__ import annotations

from typing import List, Tuple

from bccmd import CommandContext, InputValue, Point, Request
from bcdoc.errors import EntityNotFound
from . import geometry, precision
from .precision import SnapResult  # re-export for consumers/tests


SELECTION_MODES = ["All", "Previous", "Window", "Crossing", "Last"]


def existing_ids(doc, ids) -> List[str]:
    """Filter ``ids`` to entities that exist, order-preserved, de-duplicated.

    ``Document.get`` raises :class:`EntityNotFound` for unknown ids (no None
    returns), so existence is probed with try/except — a stale id in a
    selection or a scripted test must never crash a command.
    """
    seen = set()
    out = []
    for eid in ids:
        if eid in seen:
            continue
        seen.add(eid)
        try:
            doc.get(eid)
        except EntityNotFound:
            continue
        out.append(eid)
    return out


def ask_point(ctx: CommandContext, request: Request) -> Point:
    """Yield ``request`` until a point arrives; keywords echo a diagnostic.

    M2 precision hook (contracts §3/§4) — for each ACCEPTED point input:

    * ``osnap:<modes>`` keyword (one-shot override typed at the prompt) —
      parsed, stored on ``ctx.pending_osnap``, feedback
      "Osnap override active: ...", re-ask;
    * ``distance`` kind with a last point — direct distance entry via
      ``precision.dde_point`` (direction last_point -> pointer);
    * ``point`` kind with ``source == "mouse"`` — resolved through
      ``precision.resolve_point`` (grid -> ortho -> osnap with the pending
      one-shot), the pending override consumed, the RESOLVED point returned;
    * ``point`` kind with any other source — returned UNCHANGED (typed
      input never snaps — M1 determinism).

    Everything else keeps the M1 diagnostics (require_point messages).
    """
    while True:
        value = yield request
        if (value.kind == "keyword" and isinstance(value.value, str)
                and value.value.startswith("osnap:")):
            modes = precision.parse_osnap_tokens(value.value[len("osnap:"):])
            if modes:
                ctx.pending_osnap = modes
                ctx.feedback("Osnap override active: " + ", ".join(modes))
            else:
                ctx.feedback(f"Unknown osnap mode(s): {value.value!r}")
            continue
        if value.kind == "distance" and isinstance(value.value, (int, float)):
            if ctx.last_point is None:
                ctx.feedback("Direct distance entry needs a previous point")
                continue
            return precision.dde_point(
                ctx.last_point, float(value.value), ctx.pointer, ctx.document
            )
        if value.kind == "point" and isinstance(value.value, Point):
            if getattr(value, "source", "typed") == "mouse":
                result = precision.resolve_point(
                    ctx.document, value.value, ctx.last_point,
                    ctx.pending_osnap, ctx.pointer,
                )
                ctx.pending_osnap = None  # one-shot consumed (single use)
                return result.point
            return value.value
        try:
            return require_point(value)
        except ValueError as exc:
            ctx.feedback(str(exc))


def dde_input(ctx: CommandContext, value: InputValue):
    """Chained-point-prompt resolution helper (M2 contracts §3/§4).

    Commands whose point prompts carry keyword options (LINE next point,
    PLINE, …) cannot route those prompts through :func:`ask_point` (it only
    returns points), so they hand each ACCEPTED non-keyword input here.
    Covers the same three precision legs ``ask_point`` does:

    * ``osnap:<modes>`` keyword — one-shot armed on ``ctx.pending_osnap``
      with feedback; returns ``None`` (caller re-asks);
    * ``distance`` input with a last point — direct distance entry via
      ``precision.dde_point``; ``None`` (re-ask) when no last point;
    * ``point`` input with ``source == "mouse"`` — resolved through
      ``precision.resolve_point`` (grid → ortho → osnap), pending one-shot
      consumed; typed points pass through UNCHANGED.

    Anything else returns ``value`` unchanged (keywords are the CALLER's
    business — this helper never sees them).
    """
    if value.kind == "keyword" and isinstance(value.value, str) \
            and value.value.startswith("osnap:"):
        modes = precision.parse_osnap_tokens(value.value[len("osnap:"):])
        if modes:
            ctx.pending_osnap = modes
            ctx.feedback("Osnap override active: " + ", ".join(modes))
        else:
            ctx.feedback(f"Unknown osnap mode(s): {value.value!r}")
        return None
    if value.kind != "distance" or not isinstance(value.value, (int, float)):
        if value.kind == "point" and isinstance(value.value, Point) \
                and getattr(value, "source", "typed") == "mouse":
            result = precision.resolve_point(
                ctx.document, value.value, ctx.last_point,
                ctx.pending_osnap, ctx.pointer,
            )
            ctx.pending_osnap = None  # one-shot consumed (single use)
            return InputValue(kind="point", value=result.point)
        return value
    if ctx.last_point is None:
        ctx.feedback("Direct distance entry needs a previous point")
        return None
    return InputValue(
        kind="point",
        value=precision.dde_point(
            ctx.last_point, float(value.value), ctx.pointer, ctx.document
        ),
    )


def require_point(value: InputValue) -> Point:
    if value.kind == "point" and isinstance(value.value, Point):
        return value.value
    if value.kind == "keyword" and value.value == "Enter":
        raise ValueError("Point required (Enter is not valid here)")
    raise ValueError(f"Point required, got {value.kind} input")


def ask_positive_distance(ctx: CommandContext, request: Request) -> float:
    while True:
        value = yield request
        try:
            number = require_positive_number(value)
        except ValueError as exc:
            ctx.feedback(str(exc))
            continue
        if value.kind == "point":
            # point entry at a distance prompt: distance from last point
            reference = ctx.last_point
            if reference is None:
                ctx.feedback("No reference point for distance")
                continue
            number = geometry.dist_2d(
                (reference.x, reference.y), (value.value.x, value.value.y)
            )
            if number <= 0.0:
                ctx.feedback("Distance must be positive")
                continue
        return number


def require_positive_number(value: InputValue) -> float:
    if value.kind in ("distance", "angle") and isinstance(value.value, (int, float)):
        number = float(value.value)
        if number <= 0.0:
            raise ValueError("Value must be positive")
        return number
    if value.kind == "point":
        return 0.0  # handled by caller (needs ctx.last_point)
    raise ValueError(f"Number required, got {value.kind!r} input")


def select_ids(ctx: CommandContext, command_name: str) -> List[str]:
    """Selection prompt with PICKFIRST-style preselection (ux-spec §3.5)
    and the M2 selection-mode keywords All/Previous/Window/Crossing/Last
    (contracts §4; geometry from W-D's ``bcdraft.selection``).

    Preselected entities (``document.selection``) are passed straight to the
    command; otherwise the prompt accepts an id list or one of the keywords
    (prefix-matched as usual: "a" -> All, "p" -> Previous, "w" -> Window,
    "c" -> Crossing, "l" -> Last). Enter ends selection (empty). Every
    non-empty resolution becomes ``doc.last_selection_ids`` — the Previous
    pool (session state; contract §4).
    """
    doc = ctx.document
    pre = sorted(doc.selection.ids)
    if pre:
        ids = existing_ids(doc, pre)
        ctx.feedback(f"{command_name}: {len(ids)} object(s) preselected")
        _remember_selection(doc, ids)
        return ids
    request = Request(
        "selection",
        f"{command_name} Select objects or [All/Previous/Window/Crossing/Last]:",
        options=list(SELECTION_MODES),
    )
    while True:
        value = yield request
        if value.kind == "selection":
            ids = existing_ids(doc, value.value or [])
            _remember_selection(doc, ids)
            return ids
        if value.kind == "keyword":
            if value.value == "Enter":
                return []
            resolved = yield from _selection_mode(ctx, command_name, value.value)
            if resolved is None:
                continue  # the mode failed; its feedback was sunk — re-ask
            _remember_selection(doc, resolved)
            return resolved
        ctx.feedback(f"{command_name}: select objects, a mode keyword, or Enter")


def _remember_selection(doc, ids: List[str]) -> None:
    """Record the last non-empty selection used by a command (contract §4 —
    the Previous mode reads this; session state, never serialized)."""
    if ids:
        try:
            doc.last_selection_ids = list(ids)
        except Exception:  # pragma: no cover - host-state oddity guard
            pass


def _selection_mode(ctx: CommandContext, command_name: str, mode: str):
    """Resolve one selection-mode keyword -> id list, or None to re-ask
    (with feedback already sunk). Pinned geometry helpers come from W-D's
    ``bcdraft.selection``: all_ids/window_ids/crossing_ids/last_created_id —
    imported lazily so the package imports cleanly before that module lands
    at TL integration (plain import, no try/except fallback)."""
    doc = ctx.document
    from . import selection  # W-D's module (contracts §4 pinned signatures)

    if mode == "All":
        return existing_ids(doc, selection.all_ids(doc))
    if mode == "Previous":
        previous = list(getattr(doc, "last_selection_ids", None) or [])
        if not previous:
            ctx.feedback(f"{command_name}: no previous selection")
            return None
        return existing_ids(doc, previous)
    if mode in ("Window", "Crossing"):
        p1 = yield from ask_point(
            ctx, Request("point", f"{command_name} Specify first corner:")
        )
        p2 = yield from ask_point(
            ctx, Request("point", f"{command_name} Specify opposite corner:")
        )
        # corner tuples: the selection geometry helpers index coordinates
        if mode == "Window":
            return existing_ids(doc, selection.window_ids(doc, p1.to_tuple(), p2.to_tuple()))
        return existing_ids(doc, selection.crossing_ids(doc, p1.to_tuple(), p2.to_tuple()))
    if mode == "Last":
        last_id = selection.last_created_id(doc)
        if last_id is None:
            ctx.feedback(f"{command_name}: no previously created object")
            return None
        return existing_ids(doc, [last_id])
    ctx.feedback(f"{command_name}: unknown selection mode {mode!r}")
    return None


def split_locked(doc, ids) -> Tuple[List[str], List[str]]:
    """Partition ``ids`` into ``(kept, skipped)`` by their entities' layer
    LOCKED flag (kept = modifiable; skipped = on locked layers). Stale ids
    (entity no longer exists) drop out of both lists; a missing layer
    record counts as unlocked (lenient — bcdoc keeps entities off orphan
    layers by construction).

    Modify commands consume this with the exact name (contracts §2.2:
    LOCKED => visible/selectable, NOT modifiable — "N entity(ies) on locked
    layer — skipped" feedback belongs to the caller).
    """
    kept: List[str] = []
    skipped: List[str] = []
    table = getattr(doc, "layers", None)
    for eid in ids:
        try:
            entity = doc.get(eid)
        except EntityNotFound:
            continue
        locked = False
        if table is not None:
            try:
                record = table.get(entity.layer)
            except Exception:  # pragma: no cover - defensive
                record = None
            locked = bool(record.locked) if record is not None else False
        (skipped if locked else kept).append(eid)
    return kept, skipped


def add_entity(ctx: CommandContext, entity, label: str):
    """Add one entity inside a fresh committed transaction (one undo step)."""
    doc = ctx.document
    with doc.transaction(label):
        return doc.add_entity(entity)
