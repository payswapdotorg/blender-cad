"""Selection geometry + the SELECT command (W-D, drafting core).

PINNED API (m2-module-contracts §4 selection helpers): ``_common.select_ids``
imports these EXACT names, so every signature here is load-bearing for the
parallel W-A precision work:

* ``all_ids(doc) -> list[str]``           — current space, frozen excluded
* ``window_ids(doc, p1, p2) -> list[str]`` — fully inside the rectangle
* ``crossing_ids(doc, p1, p2) -> list[str]`` — bbox intersects the rectangle
* ``last_created_id(doc) -> str | None``   — newest entity in the current space

Shared semantics (binding): every helper filters to ``doc.current_space``
and EXCLUDES entities on frozen layers (contract §2.2: frozen = hidden AND
not selectable); LOCKED-layer entities are INCLUDED — modify commands skip
them with "N entity(ies) on locked layer skipped" feedback (commands_modify).
``window``/``crossing`` use ``geometry.entity_bbox`` with the doc argument so
insert references contribute their TRANSFORMED member bboxes.

The SELECT command is the operator-facing surface: a looping selection
prompt with [All/Window/Crossing/Previous/Last] options that resolves
through the same helpers, commits ``doc.selection.set(ids)`` and records
``doc.last_selection_ids`` (session state, never journaled).
"""

from __future__ import annotations

from typing import List, Optional

from bccmd import CommandResult, CommandSpec, Request
from bcdoc.errors import EntityNotFound
from . import geometry
from ._common import ask_point


# ---------------------------------------------------------------------------
# layer/space filters
# ---------------------------------------------------------------------------

def _layer_frozen(doc, name: str) -> bool:
    """A missing layer record can never be frozen (auto-created layers)."""
    record = doc.layers.get(name)
    return bool(record is not None and record.frozen)


def _selectable(entity, doc) -> bool:
    """Current-space + not-frozen (locked layers stay selectable)."""
    return entity.space == doc.current_space and not _layer_frozen(doc, entity.layer)


def selectable_ids(doc, ids) -> List[str]:
    """Filter ``ids`` to existing, selectable entities (order preserved,
    de-duplicated). Used by SELECT for raw id lists and Previous."""
    seen = set()
    out: List[str] = []
    for eid in ids:
        if eid in seen:
            continue
        seen.add(eid)
        try:
            entity = doc.get(eid)
        except EntityNotFound:
            continue
        if _selectable(entity, doc):
            out.append(eid)
    return out


# ---------------------------------------------------------------------------
# pinned helpers (m2-module-contracts §4)
# ---------------------------------------------------------------------------

def all_ids(doc) -> List[str]:
    """Every entity in the current space on a non-frozen layer (insertion
    order). Locked layers are included; commands skip locked targets."""
    return [entity.id for entity in doc.entities() if _selectable(entity, doc)]


def window_ids(doc, p1, p2) -> List[str]:
    """Ids fully inside the p1-p2 rectangle (bbox containment, tolerance
    1e-9 so a rectangle pick on the entity's edge still selects it)."""
    rect = geometry.rect_of(p1, p2)
    tol = geometry.TOL
    out: List[str] = []
    for entity in doc.entities():
        if not _selectable(entity, doc):
            continue
        min_x, min_y, max_x, max_y = geometry.entity_bbox(entity, doc)
        if (min_x >= rect[0] - tol and max_x <= rect[2] + tol
                and min_y >= rect[1] - tol and max_y <= rect[3] + tol):
            out.append(entity.id)
    return out


def crossing_ids(doc, p1, p2) -> List[str]:
    """Ids whose bbox INTERSECTS the p1-p2 rectangle (crossing selection:
    also catches entities merely passing through the window)."""
    rect = geometry.rect_of(p1, p2)
    tol = geometry.TOL
    out: List[str] = []
    for entity in doc.entities():
        if not _selectable(entity, doc):
            continue
        min_x, min_y, max_x, max_y = geometry.entity_bbox(entity, doc)
        if not (max_x < rect[0] - tol or min_x > rect[2] + tol
                or max_y < rect[1] - tol or min_y > rect[3] + tol):
            out.append(entity.id)
    return out


def last_created_id(doc) -> Optional[str]:
    """The most recently created entity in the current space (insertion
    order of ``doc.entities()``), frozen layers excluded; None when empty."""
    for entity in reversed(doc.entities()):
        if _selectable(entity, doc):
            return entity.id
    return None


# ---------------------------------------------------------------------------
# SELECT command
# ---------------------------------------------------------------------------

SELECT_OPTIONS = ["All", "Window", "Crossing", "Previous", "Last"]


def _two_corners(ctx, prompt: str):
    """Window/Crossing corner picks -> ((x1,y1,z1), (x2,y2,z2))."""
    first = yield from ask_point(ctx, Request("point", f"SELECT Specify first corner:"))
    second = yield from ask_point(
        ctx, Request("point", "SELECT Specify opposite corner:"))
    ctx.set_last_point(second)
    return first, second


def select_steps(ctx):
    doc = ctx.document
    picked: List[str] = []
    request = Request(
        "selection",
        "SELECT Select objects or [All/Window/Crossing/Previous/Last]:",
        options=list(SELECT_OPTIONS),
    )
    while True:
        value = yield request
        if value.kind == "keyword" and value.value == "Enter":
            break
        if value.kind == "keyword":
            option = value.value
            if option == "All":
                picked.extend(all_ids(doc))
            elif option == "Window":
                p1, p2 = yield from _two_corners(ctx, "Window")
                picked.extend(window_ids(doc, p1.to_tuple(), p2.to_tuple()))
            elif option == "Crossing":
                p1, p2 = yield from _two_corners(ctx, "Crossing")
                picked.extend(crossing_ids(doc, p1.to_tuple(), p2.to_tuple()))
            elif option == "Previous":
                picked.extend(doc.last_selection_ids)
            elif option == "Last":
                last = last_created_id(doc)
                if last is not None:
                    picked.append(last)
            else:
                ctx.feedback("SELECT: unknown option")
            continue
        if value.kind == "selection":
            picked.extend(value.value or [])
            continue
        ctx.feedback("SELECT: select objects or choose an option")
    ids = selectable_ids(doc, picked)
    doc.selection.set(ids)
    if ids:
        # The Previous pool holds the last NON-EMPTY selection (contract §4):
        # an empty SELECT clears doc.selection but never the pool.
        doc.last_selection_ids = list(ids)
    ctx.feedback(f"SELECT: {len(ids)} object(s) selected")
    return CommandResult(status="ok", summary=f"SELECT: {len(ids)} object(s) selected")


SELECT = CommandSpec(
    name="SELECT", aliases=[],
    steps=select_steps,
    help="Build a selection with All/Window/Crossing/Previous/Last options",
)

COMMANDS = (SELECT,)
