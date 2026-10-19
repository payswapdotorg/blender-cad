"""Layout commands: LAYOUT, MSPACE, PSPACE, MVIEW (contracts §5.4;
inventory FP-LAY-001/002/004/007).

All names NEW (no collisions with bccmd/bcdraft); ``MVIEW`` additionally
carries the aliases ``MV`` and ``VIEWPORT`` (contract §5.4 pins
``VIEWPORT``; ``VIEWPORTS`` — plural, the AutoCAD alias — is NOT
registered, a documented choice).

Semantics (pinned by the W-C task letter):

- LAYOUT options ``[?List/New/Copy/Delete/Rename/Set/Move]``:
  * List prints one feedback line per layout (name + page size) and
    re-asks the option; Enter at the option prompt ends politely;
  * New prompts a unique name (``"MODEL"`` is refused — bcdoc permits a
    layout by that name but it would collide with the model-space routing
    constant; recorded for TL as a candidate bcdoc-side guard), then page
    width/height with 420x297 defaults;
  * Copy creates the record AND clones every entity of the source space
    into the new space (fresh ids + handles; viewports clone too — the
    honest AutoCAD-subset, documented); one transaction;
  * Delete refuses non-empty spaces with clear feedback (the bcdoc
    invariant guard), is allowed for the LAST layout, and fixes up session
    pointers (current_space -> "MODEL", active_layout -> None) when they
    referenced the deleted name;
  * Rename delegates to ``doc.rename_layout`` (entities re-route); a
    no-op rename to the same name is allowed;
  * Set activates: ``doc.set_current_space(name)`` (maintains TILEMODE 0)
    + ``doc.active_layout = name``;
  * Move reorders via ``doc.reorder_layout(name, index_of(before))``;
- MSPACE: already in MODEL -> feedback note; else
  ``set_current_space("MODEL")`` keeping the active layout as the VIEWING
  tab (TILEMODE 1);
- PSPACE: requires an active layout (clear feedback otherwise);
  ``set_current_space(active_layout)`` (TILEMODE 0);
- MVIEW: requires a PAPER current space (clear feedback + cancelled in
  model space); two paper-corner picks form the rect (normalized to
  lower-left/upper-right, both extents must be non-zero); then view
  center or [Fit] <Fit> — Fit sizes center/height from the MODEL-space
  entities bbox (empty model -> honest feedback note + center (0,0) and
  height 100 defaults); an explicit center asks a positive view height.

Documented M2 limits: viewport FIT matches the model bbox height only
(aspect-aware width fitting is GUI work); the bbox is conservative for
arcs (center +- radius, not the swept extent) and skips xline/ray
(infinite by definition), dims (derived geometry) and viewports (paper
concepts); no plot/publish (FP-LAY-008+ stays planned).
"""

from __future__ import annotations

import math
import uuid
from typing import Optional

from bccmd import CommandContext, CommandResult, CommandSpec, Point, Request
from bcdoc import errors as bcdoc_errors
from bcdoc.document import MODEL_SPACE
from bcdoc.entities import Viewport
from bcdraft import geometry as bgeo

#: Default view for MVIEW Fit with an empty model space (task letter).
_EMPTY_MODEL_CENTER = (0.0, 0.0, 0.0)
_EMPTY_MODEL_HEIGHT = 100.0

#: Degenerate-extent tolerance for rects / bboxes.
_TOL = 1e-12


# ---------------------------------------------------------------------------
# ask helpers (local: the file list is pinned by the task letter)
# ---------------------------------------------------------------------------

def _ask_layout_name(ctx: CommandContext, request: Request) -> str:
    while True:
        value = yield request
        if value.kind == "string":
            if isinstance(value.value, str):
                return value.value
            if value.raw:
                return value.raw.strip()
            return str(value.value)
        ctx.feedback("LAYOUT: layout name required")


def _ask_existing_layout(ctx: CommandContext, prompt: str) -> str:
    doc = ctx.document
    while True:
        name = yield from _ask_layout_name(ctx, Request("string", prompt))
        if name not in doc.layouts():
            ctx.feedback(f"LAYOUT: no layout named {name!r}")
            continue
        return name


def _ask_new_layout_name(ctx: CommandContext, prompt: str) -> str:
    doc = ctx.document
    while True:
        name = yield from _ask_layout_name(ctx, Request("string", prompt))
        if name == MODEL_SPACE:
            ctx.feedback(
                f"LAYOUT: {MODEL_SPACE!r} is reserved for model space — "
                "pick another name")
            continue
        if name in doc.layouts():
            ctx.feedback(f"LAYOUT: layout {name!r} already exists")
            continue
        return name


def _ask_positive(ctx: CommandContext, request: Request) -> float:
    while True:
        value = yield request
        if value.kind == "distance" and isinstance(value.value, (int, float)):
            if float(value.value) > 0.0:
                return float(value.value)
            ctx.feedback("LAYOUT: value must be positive")
            continue
        if value.kind == "point" and ctx.last_point is not None:
            number = bgeo.dist_2d(
                (ctx.last_point.x, ctx.last_point.y),
                (value.value.x, value.value.y),
            )
            if number > 0.0:
                return number
        ctx.feedback("LAYOUT: positive number required")


# ---------------------------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------------------------

def layout_steps(ctx: CommandContext):
    doc = ctx.document
    while True:
        value = yield Request(
            "keyword", "LAYOUT Enter layout option "
            "[?List/New/Copy/Delete/Rename/Set/Move]:",
            options=["?List", "New", "Copy", "Delete", "Rename", "Set", "Move"],
            default="Exit",
        )
        choice = value.value if (value.kind == "keyword"
                                 and isinstance(value.value, str)) else None
        if choice == "Exit":
            return CommandResult(status="ok", summary="LAYOUT: done")
        if choice == "?List":
            names = doc.layouts()
            if not names:
                ctx.feedback("LAYOUT: no layouts defined")
            for name in names:
                record = doc.layout(name)
                ctx.feedback(
                    f"Layout {record.name!r}: {record.page_width:g} x "
                    f"{record.page_height:g} {record.paper_units}")
            continue
        if choice == "New":
            return (yield from _layout_new(ctx))
        if choice == "Copy":
            return (yield from _layout_copy(ctx))
        if choice == "Delete":
            result = yield from _layout_delete(ctx)
            if result is not None:
                return result
            continue
        if choice == "Rename":
            return (yield from _layout_rename(ctx))
        if choice == "Set":
            return (yield from _layout_set(ctx))
        if choice == "Move":
            return (yield from _layout_move(ctx))
        ctx.feedback("LAYOUT: option ?List/New/Copy/Delete/Rename/Set/Move required")


def _layout_new(ctx: CommandContext) -> CommandResult:
    doc = ctx.document
    name = yield from _ask_new_layout_name(
        ctx, "LAYOUT Enter name for new layout:")
    page_width = yield from _ask_positive(
        ctx, Request("distance", "LAYOUT Specify page width <420>:", default=420.0))
    page_height = yield from _ask_positive(
        ctx, Request("distance", "LAYOUT Specify page height <297>:", default=297.0))
    with doc.transaction("LAYOUT New"):
        doc.add_layout(name, page_width=page_width, page_height=page_height)
    ctx.feedback(f"LAYOUT: layout {name!r} created ({page_width:g} x {page_height:g})")
    return CommandResult(status="ok", summary=f"LAYOUT: created {name!r}")


def _layout_copy(ctx: CommandContext) -> CommandResult:
    doc = ctx.document
    source = yield from _ask_existing_layout(
        ctx, "LAYOUT Enter name of layout to copy:")
    new = yield from _ask_new_layout_name(
        ctx, "LAYOUT Enter name for the copied layout:")
    record = doc.layout(source)
    with doc.transaction("LAYOUT Copy"):
        doc.add_layout(new, page_width=record.page_width,
                       page_height=record.page_height,
                       paper_units=record.paper_units)
        cloned = 0
        for entity in list(doc.entities_in_space(source)):
            clone = entity.copy()
            clone.id = uuid.uuid4().hex   # fresh identity (entity.copy keeps it)
            clone.handle = 0              # add_entity assigns a fresh handle
            clone.space = new
            doc.add_entity(clone)
            cloned += 1
    ctx.feedback(
        f"LAYOUT: layout {new!r} copied from {source!r} "
        f"({cloned} entity(ies) cloned)")
    return CommandResult(
        status="ok", summary=f"LAYOUT: copied {source!r} -> {new!r}")


def _layout_delete(ctx: CommandContext) -> Optional[CommandResult]:
    """Delete one layout; None = refused with feedback (back to options)."""
    doc = ctx.document
    name = yield from _ask_existing_layout(
        ctx, "LAYOUT Enter name of layout to delete:")
    try:
        with doc.transaction("LAYOUT Delete"):
            doc.remove_layout(name)
    except bcdoc_errors.LayoutNotEmpty as exc:
        ctx.feedback(f"LAYOUT: {exc}")
        return None
    # Session-state fixup (bcdoc only re-routes on rename): pointers that
    # named the removed layout must not dangle.
    if doc.current_space == name:
        doc.set_current_space(MODEL_SPACE)
    if doc.active_layout == name:
        doc.active_layout = None
    ctx.feedback(f"LAYOUT: layout {name!r} deleted")
    return CommandResult(status="ok", summary=f"LAYOUT: deleted {name!r}")


def _layout_rename(ctx: CommandContext) -> CommandResult:
    doc = ctx.document
    old = yield from _ask_existing_layout(
        ctx, "LAYOUT Enter name of layout to rename:")
    new = yield from _ask_new_layout_name(
        ctx, "LAYOUT Enter new name for the layout:")
    if new == old:
        ctx.feedback("LAYOUT: name unchanged (no-op rename)")
        return CommandResult(status="ok", summary=f"LAYOUT: rename skipped")
    with doc.transaction("LAYOUT Rename"):
        doc.rename_layout(old, new)
    ctx.feedback(f"LAYOUT: layout {old!r} renamed to {new!r}")
    return CommandResult(status="ok", summary=f"LAYOUT: renamed {old!r} -> {new!r}")


def _layout_set(ctx: CommandContext) -> CommandResult:
    doc = ctx.document
    name = yield from _ask_existing_layout(
        ctx, "LAYOUT Enter name of layout to make current:")
    doc.set_current_space(name)   # validates + maintains TILEMODE 0
    doc.active_layout = name
    ctx.feedback(
        f"LAYOUT: layout {name!r} is current (paper space, TILEMODE "
        f"{doc.settings.get('TILEMODE')})")
    return CommandResult(status="ok", summary=f"LAYOUT: set current {name!r}")


def _layout_move(ctx: CommandContext) -> CommandResult:
    doc = ctx.document
    name = yield from _ask_existing_layout(
        ctx, "LAYOUT Enter name of layout to move:")
    before = yield from _ask_existing_layout(
        ctx, "LAYOUT Enter name of layout before which to place it:")
    names = doc.layouts()
    index = names.index(before)
    if names.index(name) < index:
        # removing the moved item shifts the target one slot left; the
        # insert index must address the post-removal list ("before" target)
        index -= 1
    with doc.transaction("LAYOUT Move"):
        doc.reorder_layout(name, index)
    ctx.feedback(f"LAYOUT: {name!r} moved before {before!r} "
                 f"(now at position {doc.layouts().index(name) + 1})")
    return CommandResult(
        status="ok", summary=f"LAYOUT: moved {name!r} before {before!r}")


# ---------------------------------------------------------------------------
# MSPACE / PSPACE (prompt-free)
# ---------------------------------------------------------------------------

def mspace_run(ctx: CommandContext, runner) -> CommandResult:
    doc = ctx.document
    if doc.current_space == MODEL_SPACE:
        ctx.feedback("MSPACE: already in model space")
        return CommandResult(status="ok", summary="MSPACE: already in model space")
    doc.set_current_space(MODEL_SPACE)   # active_layout kept as the VIEWING tab
    ctx.feedback(
        f"MSPACE: model space active (TILEMODE "
        f"{doc.settings.get('TILEMODE')}; active layout "
        f"{doc.active_layout!r} kept)")
    return CommandResult(status="ok", summary="MSPACE: model space active")


def pspace_run(ctx: CommandContext, runner) -> CommandResult:
    doc = ctx.document
    if doc.active_layout is None:
        ctx.feedback(
            "PSPACE: no active layout — activate one first (LAYOUT Set)")
        return CommandResult(
            status="cancelled", summary="PSPACE: no active layout")
    doc.set_current_space(doc.active_layout)
    ctx.feedback(
        f"PSPACE: paper space of layout {doc.active_layout!r} active "
        f"(TILEMODE {doc.settings.get('TILEMODE')})")
    return CommandResult(
        status="ok", summary=f"PSPACE: active layout {doc.active_layout!r}")


# ---------------------------------------------------------------------------
# MVIEW (VIEWPORT)
# ---------------------------------------------------------------------------

def mview_steps(ctx: CommandContext):
    doc = ctx.document
    if doc.current_space == MODEL_SPACE:
        ctx.feedback(
            "MVIEW: viewports live in paper space — activate a layout first "
            "(LAYOUT Set)")
        return CommandResult(
            status="cancelled", summary="MVIEW: refused in model space")

    first_pt = yield from _ask_point(
        ctx, Request("point", "MVIEW Specify first corner of viewport:"))
    first = first_pt.to_tuple()
    ctx.set_last_point(first_pt)
    while True:
        second_pt = yield from _ask_point(
            ctx, Request("point", "MVIEW Specify opposite corner of viewport:"))
        second = second_pt.to_tuple()
        if (abs(second[0] - first[0]) <= _TOL
                or abs(second[1] - first[1]) <= _TOL):
            ctx.feedback(
                "MVIEW: corners must differ in both X and Y — try again")
            continue
        break
    rect_p1 = (min(first[0], second[0]), min(first[1], second[1]),
               min(first[2], second[2]))
    rect_p2 = (max(first[0], second[0]), max(first[1], second[1]),
               max(first[2], second[2]))

    value = yield Request(
        "point", "MVIEW Specify view center or [Fit] <Fit>:",
        options=["Fit"], default="Fit",
    )
    if value.kind == "point":
        center = value.value.to_tuple()
        ctx.set_last_point(value.value)
        height = yield from _ask_view_height(ctx)
    else:  # Fit (keyword option, or Enter through the default)
        center, height, empty = _model_fit(doc)
        if empty:
            ctx.feedback(
                "MVIEW: model space is empty — viewport will show nothing "
                f"(defaults: center (0,0), height {_EMPTY_MODEL_HEIGHT:g})")
        else:
            ctx.feedback(
                f"MVIEW: fit to model extents (center "
                f"({center[0]:g}, {center[1]:g}), height {height:g})")

    viewport = Viewport(
        center, view_height=height, p1=rect_p1, p2=rect_p2, locked=False,
        layer=doc.current_layer, space=doc.current_space,
    )
    with doc.transaction("MVIEW"):
        entity = doc.add_entity(viewport)
    ctx.feedback(
        f"MVIEW: viewport created in {doc.current_space!r} "
        f"(view height {height:g})")
    return CommandResult(
        status="ok", summary=f"MVIEW: viewport in {doc.current_space!r}",
        created=[entity.id])


def _ask_point(ctx: CommandContext, request: Request) -> Point:
    while True:
        value = yield request
        if value.kind == "point":
            return value.value
        ctx.feedback("MVIEW: point required")


def _ask_view_height(ctx: CommandContext) -> float:
    while True:
        value = yield Request(
            "distance", "MVIEW Specify view height of model view:")
        if value.kind == "distance" and isinstance(value.value, (int, float)):
            if float(value.value) > 0.0:
                return float(value.value)
            ctx.feedback("MVIEW: view height must be positive")
            continue
        if value.kind == "point" and ctx.last_point is not None:
            number = bgeo.dist_2d(
                (ctx.last_point.x, ctx.last_point.y),
                (value.value.x, value.value.y),
            )
            if number > 0.0:
                return number
        ctx.feedback("MVIEW: positive view height required")


def _model_fit(doc):
    """(center, height, empty) fitting the MODEL-space entities bbox.

    Conservative, documented bbox: lines/polyline vertices/points/text/
    mtext/insert use their coordinates; circles + arcs center +- radius
    (arcs: full-circle bound, not the swept extent); ellipses get the
    exact axis-aligned extent of the rotated axes; xline/ray are INFINITE
    (skipped), dims are derived (skipped), viewports are paper concepts
    (skipped). Degenerate (flat) bboxes fall back to the X extent, then
    to 1.0 so the view is never zero-height.
    """
    try:
        entities = doc.entities_in_space(MODEL_SPACE)
    except bcdoc_errors.InvalidSpace:  # pragma: no cover - MODEL always valid
        entities = []
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for entity in entities:
        kind = getattr(entity, "kind", "")
        spans = []
        if kind in ("line",):
            spans = [entity.p1, entity.p2]
        elif kind in ("circle", "arc"):
            c, r = entity.center, float(entity.radius)
            spans = [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
        elif kind == "point":
            spans = [entity.position]
        elif kind == "polyline":
            spans = list(entity.vertices)
        elif kind == "ellipse":
            a = math.hypot(entity.major_axis[0], entity.major_axis[1])
            b = a * float(entity.ratio)
            theta = math.atan2(entity.major_axis[1], entity.major_axis[0])
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            extent_x = math.sqrt((a * cos_t) ** 2 + (b * sin_t) ** 2)
            extent_y = math.sqrt((a * sin_t) ** 2 + (b * cos_t) ** 2)
            c = entity.center
            spans = [(c[0] - extent_x, c[1] - extent_y),
                     (c[0] + extent_x, c[1] + extent_y)]
        elif kind in ("text", "mtext"):
            spans = [entity.position]
        elif kind == "insert":
            spans = [entity.position]
        for sx, sy in ((p[0], p[1]) for p in spans):
            minx = min(minx, sx)
            maxx = max(maxx, sx)
            miny = min(miny, sy)
            maxy = max(maxy, sy)
    if minx is math.inf or miny is math.inf:
        return _EMPTY_MODEL_CENTER, _EMPTY_MODEL_HEIGHT, True
    center = ((minx + maxx) / 2.0, (miny + maxy) / 2.0, 0.0)
    height = maxy - miny
    if height <= _TOL:
        height = (maxx - minx) if (maxx - minx) > _TOL else 1.0
    return center, height, False


# ---------------------------------------------------------------------------
# command specs
# ---------------------------------------------------------------------------

LAYOUT = CommandSpec(
    name="LAYOUT", aliases=[],
    steps=layout_steps,
    help="Manage paper-space layouts: list/new/copy/delete/rename/set/move",
)
MSPACE = CommandSpec(
    name="MSPACE", aliases=[],
    run=mspace_run,
    help="Edit in model space while viewing a layout (TILEMODE 1)",
)
PSPACE = CommandSpec(
    name="PSPACE", aliases=[],
    run=pspace_run,
    help="Return to the active layout's paper space (TILEMODE 0)",
)
MVIEW = CommandSpec(
    name="MVIEW", aliases=["MV", "VIEWPORT"],
    steps=mview_steps,
    help="Create a paper-space viewport (rect; view center or [Fit])",
)

COMMANDS = (LAYOUT, MSPACE, PSPACE, MVIEW)


def register_all(registry):
    """Register every layout command spec into ``registry``."""
    for spec in COMMANDS:
        registry.register(spec)
    return registry


__all__ = ["COMMANDS", "register_all"]
