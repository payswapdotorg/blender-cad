"""Modify commands: ERASE, MOVE, COPY, ROTATE, SCALE (M1) + MIRROR, OFFSET,
ARRAYRECT, BREAK, JOIN, EXPLODE, STRETCH, MATCHPROP (M2 drafting core).

All transforms are analytic recomputations through ``bcdraft.geometry``
dispatch helpers — no kernel at M2 (ADR-0002). Every mutation goes through
the JOURNALED document API (``add_entity`` / ``remove`` / ``update_entity``)
inside transactions so UNDO restores geometry; direct attribute writes
would bypass the undo journal. MOVE/ERASE/ROTATE/SCALE/MIRROR/JOIN/EXPLODE/
STRETCH/MATCHPROP/ARRAYRECT commit ONE transaction per command invocation;
COPY one per placement; OFFSET one per offset object; PLINE-style
granularity is documented per command.

Locked-layer semantics (contract §2.2): ``select_ids`` returns locked-layer
entities (visible + selectable), and every MODIFY command here partitions
them out with the local ``_split_locked`` helper, sinking
"N entity(ies) on locked layer skipped" feedback — zero cross-worker
dependency on W-A's parallel _common.split_locked (same partition, TL may
unify at integration).

Documented v0 limits (feedback strings are the contract surface):
* OFFSET on polylines does per-segment offsets WITHOUT corner healing —
  non-parallel joins get straight jog connectors (known M2 limit, noted
  in the command feedback);
* BREAK on polylines supports both points on ONE STRAIGHT segment only;
* JOIN never merges across kinds (line+arc stays two objects; polyline
  sources absorb connecting lines/arcs only);
* STRETCH cannot move arc endpoints (skipped with feedback) and treats
  text/mtext/insert/ellipse/point/circle/dim/viewport as whole-object
  moves when their anchor point lies inside the crossing window;
* EXPLODE handles inserts (one level) and polylines; other kinds report
  "cannot explode".
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from bccmd import CommandResult, CommandSpec, Point, Request
from bcdoc.entities import Arc, Circle, Line, Polyline
from . import geometry
from .selection import crossing_ids
from ._common import ask_point, existing_ids, select_ids


# ---------------------------------------------------------------------------
# locked-layer partition (local twin of _common.split_locked — W-D scope)
# ---------------------------------------------------------------------------

def _split_locked(doc, ids):
    """Partition ``ids`` into (modifiable, locked-layer) ids.

    ``doc.layers.get`` returns the live record; a missing record (never
    happens through the auto-create path) counts as unlocked so a stale id
    can never crash a command.
    """
    modifiable: List[str] = []
    locked: List[str] = []
    for eid in ids:
        try:
            entity = doc.get(eid)
        except Exception:
            continue
        record = doc.layers.get(entity.layer)
        if record is not None and record.locked:
            locked.append(eid)
        else:
            modifiable.append(eid)
    return modifiable, locked


def _skip_locked(ctx, command: str, locked) -> None:
    if locked:
        ctx.feedback(
            f"{command}: {len(locked)} entity(ies) on locked layer skipped")


def _replace_entity(doc, eid: str, new_entity):
    """Journaled same-identity replacement: remove ``eid`` and add
    ``new_entity`` (same id + handle) in the OPEN transaction — one undo
    step, stable id/handle. Used when a kind change or a polyline GROWTH
    cannot be expressed as update_entity field changes (bcdoc v2's per-field
    length validation rejects length-changing polyline updates in any
    field order — see commands_draw._pline_commit)."""
    old = doc.remove(eid)
    new_entity.id = old.id
    doc.add_entity(new_entity, handle=old.handle)
    return new_entity


# ---------------------------------------------------------------------------
# ERASE
# ---------------------------------------------------------------------------

def erase_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "ERASE")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "ERASE", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="ERASE: no objects selected")
    removed: List[str] = []
    with doc.transaction("ERASE"):
        for eid in modifiable:
            doc.remove(eid)  # ids are pre-validated by select_ids
            removed.append(eid)
    # Dropped entities must not linger in the document selection (selection
    # changes never bump doc_version — bcdoc §3.4).
    doc.selection.remove(removed)
    return CommandResult(
        status="ok",
        summary=f"ERASE: removed {len(removed)} object(s)",
        removed=removed,
    )


# ---------------------------------------------------------------------------
# MOVE (base→second point, in place; [Displacement] for direct delta entry)
# ---------------------------------------------------------------------------

def move_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "MOVE")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "MOVE", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="MOVE: no objects selected")
    value = yield Request(
        "point", "MOVE Specify base point or [Displacement]:",
        options=["Displacement"],
    )
    if value.kind == "keyword" and value.value == "Displacement":
        displacement_value = yield Request("point", "MOVE Specify displacement <x,y,z>:")
        while displacement_value.kind != "point":
            ctx.feedback("MOVE: displacement vector required")
            displacement_value = yield Request("point", "MOVE Specify displacement <x,y,z>:")
        delta = displacement_value.value
    else:
        while value.kind != "point":
            ctx.feedback("MOVE: base point or [Displacement] required")
            value = yield Request(
                "point", "MOVE Specify base point or [Displacement]:",
                options=["Displacement"],
            )
        base = value.value
        ctx.set_last_point(base)
        second = yield Request(
            "point", "MOVE Specify second point or <use first point as displacement>:"
        )
        while second.kind != "point":
            ctx.feedback("MOVE: second point required")
            second = yield Request(
                "point", "MOVE Specify second point or <use first point as displacement>:"
            )
        delta = second.value - base
        ctx.set_last_point(second.value)
    with doc.transaction("MOVE"):
        for eid in modifiable:
            entity = doc.get(eid)
            doc.update_entity(eid, **geometry.move_changes(entity, delta.to_tuple()))
    return CommandResult(
        status="ok",
        summary=(
            f"MOVE: {len(modifiable)} object(s) by "
            f"({delta.x:g}, {delta.y:g}, {delta.z:g})"
        ),
        modified=modifiable,
    )


# ---------------------------------------------------------------------------
# COPY (multiple placements, [Exit/Undo])
# ---------------------------------------------------------------------------

def copy_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "COPY")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "COPY", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="COPY: no objects selected")
    base_value = yield Request("point", "COPY Specify base point:")
    while base_value.kind != "point":
        ctx.feedback("COPY: base point required")
        base_value = yield Request("point", "COPY Specify base point:")
    base = base_value.value
    ctx.set_last_point(base)

    created: List[str] = []
    placements = 0
    while True:
        value = yield Request(
            "point", "COPY Specify second point or [Exit/Undo] <Exit>:",
            options=["Exit", "Undo"], default="Exit",
        )
        if value.kind == "keyword":
            if value.value in ("Exit", "Enter"):
                break
            if value.value == "Undo":
                if placements == 0:
                    ctx.feedback("COPY: nothing to undo")
                    continue
                if doc.undo():  # one committed placement = one undo step
                    del created[-len(modifiable):]
                    placements -= 1
                    ctx.feedback("COPY: last placement undone")
                continue
            ctx.feedback("COPY: point or [Exit/Undo]")
            continue
        if value.kind != "point":
            ctx.feedback("COPY: point or [Exit/Undo]")
            continue
        delta = value.value - base
        ctx.set_last_point(value.value)
        with doc.transaction("COPY"):
            for eid in modifiable:
                entity = doc.get(eid)
                created.append(doc.add_entity(
                    geometry.clone_moved(entity, delta.to_tuple())
                ).id)
        placements += 1
    if not created:
        return CommandResult(status="ok", summary="COPY: no placements made")
    return CommandResult(
        status="ok",
        summary=f"COPY: {len(created)} new object(s) in {placements} placement(s)",
        created=created,
    )


# ---------------------------------------------------------------------------
# ROTATE (base point + angle; CCW positive about +Z)
# ---------------------------------------------------------------------------

def rotate_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "ROTATE")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "ROTATE", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="ROTATE: no objects selected")
    base_value = yield Request("point", "ROTATE Specify base point:")
    while base_value.kind != "point":
        ctx.feedback("ROTATE: base point required")
        base_value = yield Request("point", "ROTATE Specify base point:")
    base = base_value.value
    ctx.set_last_point(base)
    while True:
        value = yield Request("angle", "ROTATE Specify rotation angle (CCW positive):")
        if value.kind == "angle":
            angle = float(value.value)
            break
        if value.kind == "point":
            # mouse entry: angle from base point to the picked point
            angle = geometry.angle_of(
                (value.value.x - base.x, value.value.y - base.y)
            )
            break
        ctx.feedback("ROTATE: angle (typed or point) required")
    with doc.transaction("ROTATE"):
        for eid in modifiable:
            entity = doc.get(eid)
            doc.update_entity(
                eid, **geometry.rotate_changes(entity, base.to_tuple(), float(angle))
            )
    return CommandResult(
        status="ok",
        summary=f"ROTATE: {len(modifiable)} object(s) {angle:g}° CCW about base point",
        modified=modifiable,
    )


# ---------------------------------------------------------------------------
# SCALE (base point + factor; [Reference] length ratio)
# ---------------------------------------------------------------------------

def scale_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "SCALE")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "SCALE", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="SCALE: no objects selected")
    base_value = yield Request("point", "SCALE Specify base point:")
    while base_value.kind != "point":
        ctx.feedback("SCALE: base point required")
        base_value = yield Request("point", "SCALE Specify base point:")
    base = base_value.value
    ctx.set_last_point(base)
    while True:
        value = yield Request(
            "distance", "SCALE Specify scale factor or [Reference]:",
            options=["Reference"],
        )
        if value.kind == "keyword" and value.value == "Reference":
            ref_length = yield from _ask_scale_length(
                ctx, base, "SCALE Specify reference length <1>:", default=1.0
            )
            new_length = yield from _ask_scale_length(
                ctx, base, "SCALE Specify new length:"
            )
            factor = new_length / ref_length
            break
        if value.kind == "distance" and float(value.value) != 0.0:
            factor = float(value.value)
            break
        if value.kind == "point":
            factor = geometry.dist_2d(
                (base.x, base.y), (value.value.x, value.value.y)
            )
            if factor > 0.0:
                break
            ctx.feedback("SCALE: scale factor must be non-zero")
            continue
        ctx.feedback("SCALE: non-zero scale factor or [Reference]")
    with doc.transaction("SCALE"):
        for eid in modifiable:
            entity = doc.get(eid)
            doc.update_entity(
                eid, **geometry.scale_changes(entity, base.to_tuple(), factor)
            )
    return CommandResult(
        status="ok",
        summary=f"SCALE: {len(modifiable)} object(s) × {factor:g} about base point",
        modified=modifiable,
    )


def _ask_scale_length(ctx, base: Point, prompt: str, default=None):
    """Reference/new length prompt: typed number, point (distance from base)
    or Enter accepting the default when one is shown."""
    while True:
        value = yield Request("distance", prompt, default=default)
        if value.kind in ("distance", "angle") and float(value.value) > 0.0:
            return float(value.value)
        if value.kind == "keyword" and value.value == "Enter" and default:
            return float(default)
        if value.kind == "point":
            length = geometry.dist_2d(
                (base.x, base.y), (value.value.x, value.value.y)
            )
            if length > 0.0:
                return length
        ctx.feedback("SCALE: positive length required")


# ---------------------------------------------------------------------------
# MIRROR — reflect across a two-point axis; [Yes/No] erase-source prompt
# ---------------------------------------------------------------------------

def _mirror_erase_source(ctx) -> bool:
    while True:
        value = yield Request(
            "string", "MIRROR Erase source objects? [Yes/No] <No>:",
            options=["Yes", "No"], default="No",
        )
        if value.kind == "keyword":
            if value.value == "Yes":
                return True
            if value.value == "No":
                return False
        elif value.kind == "string":
            token = str(value.value).strip().lower()
            if token in ("y", "yes"):
                return True
            if token in ("n", "no"):
                return False
        ctx.feedback("MIRROR: Yes or No required")


def mirror_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "MIRROR")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "MIRROR", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="MIRROR: no objects selected")
    p1 = yield from ask_point(
        ctx, Request("point", "MIRROR Specify first point of mirror line:"))
    ctx.set_last_point(p1)
    while True:
        p2 = yield from ask_point(
            ctx, Request("point", "MIRROR Specify second point of mirror line:"))
        if geometry.dist_2d(
                (p1.x, p1.y), (p2.x, p2.y)) > geometry.TOL:
            break
        ctx.feedback("MIRROR: mirror line points must differ")
    ctx.set_last_point(p2)
    erase = yield from _mirror_erase_source(ctx)
    a, b = p1.to_tuple(), p2.to_tuple()
    created: List[str] = []
    with doc.transaction("MIRROR"):
        for eid in modifiable:
            entity = doc.get(eid)
            if erase:
                # mirror in place (arc sweeps reverse, bulge signs flip,
                # rotations reflect — geometry.mirror_changes)
                doc.update_entity(eid, **geometry.mirror_changes(entity, a, b))
            else:
                # keep-source: COPY semantics — a mirrored duplicate keeps
                # the original untouched
                created.append(doc.add_entity(
                    geometry.apply_mirror(entity, a, b)).id)
    noun = "erased source" if erase else "source kept"
    summary = f"MIRROR: {len(modifiable)} object(s) mirrored ({noun})"
    return CommandResult(
        status="ok", summary=summary,
        modified=(modifiable if erase else []),
        created=created,
    )


# ---------------------------------------------------------------------------
# OFFSET — distance or [Through]; one object + side point per iteration
# ---------------------------------------------------------------------------

def _offset_props(entity) -> dict:
    return {
        "layer": entity.layer, "color": entity.color,
        "linetype": entity.linetype, "lineweight": entity.lineweight,
        "space": entity.space,
    }


def _offset_line(entity: Line, distance: float, pick) -> Line:
    dx, dy = entity.p2[0] - entity.p1[0], entity.p2[1] - entity.p1[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    side = 1.0 if (ux * (pick[1] - entity.p1[1])
                   - uy * (pick[0] - entity.p1[0])) >= 0.0 else -1.0
    delta = (side * distance * -uy, side * distance * ux, 0.0)
    return Line(
        geometry.move_pt(entity.p1, delta), geometry.move_pt(entity.p2, delta),
        **_offset_props(entity))


def _offset_radius(entity, distance: float, pick) -> Optional[float]:
    """Signed radius change for circle/arc/bulge segments: +distance when
    the side point lies OUTSIDE the circle, −distance when inside."""
    to_pick = geometry.dist_2d(pick, entity.center)
    side = 1.0 if to_pick > entity.radius else -1.0
    new_radius = entity.radius + side * distance
    if new_radius <= geometry.TOL:
        return None
    return new_radius


def _offset_polyline(entity: Polyline, distance: float, pick):
    """Per-segment offset WITHOUT corner healing (documented M2 limit):
    each segment is offset to the side the pick point lies on; joins whose
    offset endpoints do not coincide get a straight jog connector. Returns
    (polyline, jog_count) or (None, reason)."""
    segments = geometry.polyline_segments(entity)
    if not segments:
        return None, "polyline has fewer than two vertices"
    pieces: List[Tuple[tuple, tuple, float]] = []
    for start, end, bulge in segments:
        if abs(bulge) <= geometry.TOL:
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            if length <= geometry.TOL:
                continue
            ux, uy = dx / length, dy / length
            side = 1.0 if (ux * (pick[1] - start[1])
                           - uy * (pick[0] - start[0])) >= 0.0 else -1.0
            delta = (side * distance * -uy, side * distance * ux, 0.0)
            pieces.append((
                geometry.move_pt(start, delta), geometry.move_pt(end, delta), 0.0))
        else:
            center, radius, s_angle, e_angle = geometry.arc_from_bulge(
                start, end, bulge)
            to_pick = geometry.dist_2d(pick, center)
            side = 1.0 if to_pick > radius else -1.0
            new_radius = radius + side * distance
            if new_radius <= geometry.TOL:
                return None, "offset would collapse an arc segment"
            new_start = (
                center[0] + new_radius * math.cos(math.radians(s_angle)),
                center[1] + new_radius * math.sin(math.radians(s_angle)),
                start[2])
            new_end = (
                center[0] + new_radius * math.cos(math.radians(e_angle)),
                center[1] + new_radius * math.sin(math.radians(e_angle)),
                end[2])
            pieces.append((new_start, new_end, bulge))
    if not pieces:
        return None, "polyline has no offsettable segments"
    vertices: List[tuple] = []
    bulges: List[float] = []
    jogs = 0
    for index, (start, end, bulge) in enumerate(pieces):
        if index == 0:
            vertices.append(start)
            bulges.append(bulge)
            continue
        prev_end = pieces[index - 1][1]
        if geometry.dist_2d(prev_end, start) > 1e-6:
            # no corner healing at non-parallel joins — a straight jog
            # connector keeps the result a single polyline (M2 limit)
            vertices.append(prev_end)
            bulges.append(0.0)
            jogs += 1
        vertices.append(start)
        bulges.append(bulge)
    vertices.append(pieces[-1][1])
    bulges.append(0.0)
    if len(vertices) < 2:
        return None, "offset collapsed the polyline"
    result = Polyline(
        list(vertices), bulges=list(bulges), closed=entity.closed,
        **_offset_props(entity))
    return result, jogs


def _offset_through_distance(entity, pick) -> Optional[float]:
    """[Through] mode: the through point IS the side — its distance to the
    entity fixes the offset distance."""
    kind = entity.kind
    if kind == "line":
        point, _t = geometry.project_on_segment(pick, entity.p1, entity.p2)
        return geometry.dist_2d(pick, point)
    if kind in ("circle", "arc"):
        return abs(geometry.dist_2d(pick, entity.center) - entity.radius)
    return None


def offset_steps(ctx):
    doc = ctx.document
    through_mode = False
    distance = 0.0
    while True:
        value = yield Request(
            "distance", "OFFSET Specify offset distance or [Through] <1>:",
            options=["Through"], default=1.0,
        )
        if value.kind == "keyword" and value.value == "Through":
            through_mode = True
            break
        if value.kind in ("distance", "angle") and float(value.value) > 0.0:
            distance = float(value.value)
            break
        ctx.feedback("OFFSET: positive distance or [Through]")
    created: List[str] = []
    while True:
        value = yield Request(
            "selection", "OFFSET Select object to offset or [Exit/Undo] <Exit>:",
            options=["Exit", "Undo"], default="Exit",
        )
        if value.kind == "keyword":
            if value.value in ("Exit", "Enter"):
                break
            if value.value == "Undo":
                if created and doc.undo():
                    created.pop()
                    ctx.feedback("OFFSET: last offset undone")
                continue
            ctx.feedback("OFFSET: select an object or [Exit/Undo]")
            continue
        if value.kind != "selection" or not value.value:
            break  # empty selection ends the loop (AutoCAD Enter)
        ids = existing_ids(doc, value.value)
        if len(ids) > 1:
            ctx.feedback("OFFSET: one object at a time — using the first")
        ids, locked = _split_locked(doc, ids)
        _skip_locked(ctx, "OFFSET", locked)
        if not ids:
            continue
        eid = ids[0]
        entity = doc.get(eid)
        if through_mode:
            prompt = "OFFSET Specify through point:"
        else:
            prompt = "OFFSET Specify point on side to offset:"
        pick_point = yield from ask_point(ctx, Request("point", prompt))
        ctx.set_last_point(pick_point)
        pick = pick_point.to_tuple()
        new_entity = None
        if through_mode:
            if entity.kind == "polyline":
                ctx.feedback(
                    "OFFSET: Through is not supported on polylines (v0)")
                continue
            distance = _offset_through_distance(entity, pick)
            if distance is None or distance <= geometry.TOL:
                ctx.feedback("OFFSET: through point does not resolve a side")
                continue
        if entity.kind == "line":
            new_entity = _offset_line(entity, distance, pick)
        elif entity.kind == "circle":
            radius = _offset_radius(entity, distance, pick)
            if radius is None:
                ctx.feedback("OFFSET: offset would collapse the circle — skipped")
                continue
            new_entity = Circle(entity.center, radius, **_offset_props(entity))
        elif entity.kind == "arc":
            radius = _offset_radius(entity, distance, pick)
            if radius is None:
                ctx.feedback("OFFSET: offset would collapse the arc — skipped")
                continue
            new_entity = Arc(
                entity.center, radius, entity.start_angle, entity.end_angle,
                **_offset_props(entity))
        elif entity.kind == "polyline":
            new_entity, info = _offset_polyline(entity, distance, pick)
            if new_entity is None:
                ctx.feedback(f"OFFSET: {info}")
                continue
            if entity.widths:
                ctx.feedback("OFFSET: segment widths are dropped (v0)")
            if isinstance(info, int) and info > 0:
                ctx.feedback(
                    f"OFFSET: {info} join(s) not healed — straight jogs "
                    "inserted (known M2 limit)")
        else:
            ctx.feedback(f"OFFSET: cannot offset a {entity.kind} (v0)")
            continue
        with doc.transaction("OFFSET"):
            created.append(doc.add_entity(new_entity).id)
        ctx.feedback("OFFSET: 1 object offset")
    summary = f"OFFSET: {len(created)} object(s) offset"
    if through_mode:
        summary += " (through points)"
    return CommandResult(status="ok", summary=summary, created=created)


# ---------------------------------------------------------------------------
# ARRAYRECT — rows × columns grid of copies; originals occupy cell (1,1)
# ---------------------------------------------------------------------------

def _ask_count(ctx, prompt: str, default: int = 1) -> int:
    while True:
        value = yield Request("distance", prompt, default=default)
        if value.kind in ("distance", "angle"):
            number = float(value.value)
            if number == int(number) and number >= 1.0:
                return int(number)
        if value.kind == "keyword" and value.value == "Enter":
            return default
        ctx.feedback("ARRAYRECT: a whole number >= 1 is required")


def _ask_signed_distance(ctx, prompt: str, default: float = 1.0) -> float:
    """Spacing prompt: any value allowed (negative = down / left; zero
    stacks the copies — AutoCAD permits it)."""
    while True:
        value = yield Request("distance", prompt, default=default)
        if value.kind in ("distance", "angle"):
            return float(value.value)
        if value.kind == "keyword" and value.value == "Enter":
            return float(default)
        ctx.feedback("ARRAYRECT: a spacing value is required")


def arrayrect_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "ARRAYRECT")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "ARRAYRECT", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="ARRAYRECT: no objects selected")
    rows = yield from _ask_count(ctx, "ARRAYRECT Enter number of rows <1>:")
    columns = yield from _ask_count(ctx, "ARRAYRECT Enter number of columns <1>:")
    row_spacing = yield from _ask_signed_distance(
        ctx, "ARRAYRECT Specify distance between rows (negative = down) <1>:")
    column_spacing = yield from _ask_signed_distance(
        ctx, "ARRAYRECT Specify distance between columns (negative = left) <1>:")
    created: List[str] = []
    with doc.transaction("ARRAYRECT"):
        for row in range(rows):
            for column in range(columns):
                if row == 0 and column == 0:
                    continue  # the originals occupy the first array cell
                delta = (column * column_spacing, row * row_spacing, 0.0)
                for eid in modifiable:
                    created.append(doc.add_entity(
                        geometry.clone_moved(doc.get(eid), delta)).id)
    total = rows * columns
    summary = (
        f"ARRAYRECT: {rows}×{columns} grid, "
        f"{len(created)} new object(s) (originals stay at cell 1,1)"
    )
    ctx.feedback(summary)
    return CommandResult(status="ok", summary=summary, created=created)


# ---------------------------------------------------------------------------
# BREAK — remove the part between two points on ONE object
# ---------------------------------------------------------------------------

def _line_break_pieces(entity: Line, first, second):
    """Break a line: clamped removed interval; returns the surviving pieces
    (0, 1 or 2 Line entities) — exact geometry."""
    dx, dy = entity.p2[0] - entity.p1[0], entity.p2[1] - entity.p1[1]
    denom = dx * dx + dy * dy
    if denom <= geometry.TOL * geometry.TOL:
        return []  # zero-length line: everything removed
    t1 = ((first[0] - entity.p1[0]) * dx + (first[1] - entity.p1[1]) * dy) / denom
    t2 = ((second[0] - entity.p1[0]) * dx + (second[1] - entity.p1[1]) * dy) / denom
    low = max(0.0, min(min(t1, t2), 1.0))
    high = min(1.0, max(max(t1, t2), 0.0))
    pieces = []
    if low > geometry.TOL:
        pieces.append(_line_piece(entity, 0.0, low))
    if high < 1.0 - geometry.TOL:
        pieces.append(_line_piece(entity, high, 1.0))
    return pieces


def _line_piece(entity: Line, t_from: float, t_to: float) -> Line:
    def at(t):
        return (
            entity.p1[0] + t * (entity.p2[0] - entity.p1[0]),
            entity.p1[1] + t * (entity.p2[1] - entity.p1[1]),
            entity.p1[2] + t * (entity.p2[2] - entity.p1[2]),
        )
    return Line(at(t_from), at(t_to), **_offset_props(entity))


def _pick_sweep(a_from: float, a_to: float) -> float:
    """CCW sweep in [0, 360) from ``a_from`` to ``a_to`` where EQUAL angles
    mean ZERO sweep — the picked-angle measure BREAK needs.

    Unlike ``geometry._ccw_from`` (the entity-level "full circle when the
    angles coincide" convention, correct for arc sweeps stored on entities),
    this returns 0.0 for a_from == a_to: a break pick landing exactly on the
    arc's start/end angle is ON the arc and bounds a zero removed portion,
    never a 360° one.
    """
    return geometry.normalize_deg(a_to - a_from)


def _arc_break_pieces(entity: Arc, first, second):
    """Break an arc: remove the CCW portion first→second; survivors are the
    [s→a1] and [a2→e] sub-arcs (0, 1 or 2). Returns (None, reason) on
    invalid picks."""
    sweep = geometry._ccw_from(entity.start_angle, entity.end_angle)
    a1 = geometry.angle_of((first[0] - entity.center[0],
                            first[1] - entity.center[1]))
    a2 = geometry.angle_of((second[0] - entity.center[0],
                            second[1] - entity.center[1]))
    if _pick_sweep(entity.start_angle, a1) > sweep + geometry.TOL:
        return None, "first point is not on the arc"
    if _pick_sweep(entity.start_angle, a2) > sweep + geometry.TOL:
        return None, "second point is not on the arc"
    if _pick_sweep(a1, a2) <= geometry.TOL:
        return None, "break points coincide"
    pieces = []
    first_sweep = _pick_sweep(entity.start_angle, a1)
    second_sweep = _pick_sweep(a2, entity.end_angle)
    if first_sweep > geometry.TOL:
        pieces.append(Arc(entity.center, entity.radius, entity.start_angle,
                          geometry.normalize_deg(entity.start_angle + first_sweep),
                          **_offset_props(entity)))
    if second_sweep > geometry.TOL:
        pieces.append(Arc(entity.center, entity.radius,
                          geometry.normalize_deg(a2), entity.end_angle,
                          **_offset_props(entity)))
    return pieces, None


def _locate_polyline_segment(entity: Polyline, point):
    """Nearest segment to a point (straight: exact; bulged: sampled) →
    (index, t, distance). t is the position along the segment (0..1 for
    straight segments)."""
    best = None
    segments = geometry.polyline_segments(entity)
    for index, (start, end, bulge) in enumerate(segments):
        if abs(bulge) <= geometry.TOL:
            nearest, t = geometry.project_on_segment(point, start, end)
            distance = geometry.dist_2d(point, nearest)
        else:
            center, radius, s_angle, e_angle = geometry.arc_from_bulge(
                start, end, bulge)
            samples = geometry.arc_points(
                center, radius, s_angle, e_angle, max(2, 32))
            nearest = min(
                samples, key=lambda sample: geometry.dist_2d(point, sample))
            distance = geometry.dist_2d(point, nearest)
            t = geometry._ccw_from(s_angle, geometry.angle_of(
                (nearest[0] - center[0], nearest[1] - center[1]))) / max(
                geometry._ccw_from(s_angle, e_angle), geometry.TOL)
        if best is None or distance < best[2] - geometry.TOL:
            best = (index, t, distance)
    return best


def _polyline_break_pieces(entity: Polyline, first, second):
    """Polyline break: only when both points fall on ONE STRAIGHT segment
    (documented v0 limit). Returns (pieces, None) or (None, reason)."""
    located1 = _locate_polyline_segment(entity, first)
    located2 = _locate_polyline_segment(entity, second)
    if located1 is None or located2 is None:
        return None, "polyline has no segments"
    index1, _t1, _d1 = located1
    index2, _t2, _d2 = located2
    bulges = list(entity.bulges) if entity.bulges else [0.0] * len(entity.vertices)
    if abs(bulges[index1]) > geometry.TOL or abs(bulges[index2]) > geometry.TOL:
        return None, "BREAK: not supported on this segment type (v0)"
    if index1 != index2:
        return None, "BREAK: both points must lie on one segment (v0)"
    index = index1
    start, end, _bulge = geometry.polyline_segments(entity)[index]
    dx, dy = end[0] - start[0], end[1] - start[1]
    denom = dx * dx + dy * dy
    if denom <= geometry.TOL * geometry.TOL:
        return None, "segment is degenerate"
    t1 = ((first[0] - start[0]) * dx + (first[1] - start[1]) * dy) / denom
    t2 = ((second[0] - start[0]) * dx + (second[1] - start[1]) * dy) / denom
    low = max(0.0, min(min(t1, t2), 1.0))
    high = min(1.0, max(max(t1, t2), 0.0))
    if high - low <= geometry.TOL:
        return None, "break points coincide"
    at_low = (start[0] + low * dx, start[1] + low * dy, start[2])
    at_high = (start[0] + high * dx, start[1] + high * dy, start[2])

    def stub_width():
        if entity.widths:
            return tuple(entity.widths[index])
        return None

    vertices = list(entity.vertices)
    count = len(vertices)
    if entity.closed:
        # removing one segment opens the loop: walk CCW from the high
        # break point around to the low one
        new_vertices = [at_high]
        new_bulges = [0.0]
        for step in range(1, count + 1):
            vertex_index = (index + step) % count
            new_vertices.append(vertices[vertex_index])
            new_bulges.append(bulges[vertex_index])
        new_vertices.append(at_low)
        new_bulges.append(0.0)
        return [Polyline(new_vertices, bulges=new_bulges, closed=False,
                         widths=([stub_width()] * len(new_vertices)
                                 if entity.widths else None),
                         **_offset_props(entity))], None
    pieces = []
    if index > 0 or low > geometry.TOL:
        head = vertices[:index + 1]
        head_bulges = bulges[:index + 1]
        head_widths = ([tuple(w) for w in entity.widths[:index + 1]]
                       if entity.widths else None)
        if low > geometry.TOL:
            head = head + [at_low]
            head_bulges = head_bulges + [0.0]
            if head_widths is not None:
                head_widths = head_widths + [stub_width()]
        if len(head) >= 2:
            pieces.append(Polyline(head, bulges=head_bulges, closed=False,
                                   widths=head_widths,
                                   **_offset_props(entity)))
    if index < count - 2 or high < 1.0 - geometry.TOL:
        tail = [at_high] + vertices[index + 1:]
        tail_bulges = [0.0] + bulges[index + 1:]
        tail_widths = None
        if entity.widths:
            tail_widths = [stub_width()] + [
                tuple(w) for w in entity.widths[index + 1:]]
        if len(tail) >= 2:
            pieces.append(Polyline(tail, bulges=tail_bulges, closed=False,
                                   widths=tail_widths,
                                   **_offset_props(entity)))
    return pieces, None


def break_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "BREAK")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "BREAK", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="BREAK: no objects selected")
    if len(modifiable) > 1:
        ctx.feedback("BREAK: one object at a time — using the first")
    eid = modifiable[0]
    entity = doc.get(eid)
    if entity.kind not in ("line", "circle", "arc", "polyline"):
        ctx.feedback(f"BREAK: cannot break a {entity.kind} (v0)")
        return CommandResult(status="ok", summary=f"BREAK: cannot break a {entity.kind}")
    first = yield from ask_point(
        ctx, Request("point", "BREAK Specify first break point:"))
    ctx.set_last_point(first)
    while True:
        value = yield Request(
            "point", "BREAK Specify second break point or [First]:",
            options=["First"],
        )
        if value.kind == "keyword" and value.value == "First":
            first = yield from ask_point(
                ctx, Request("point", "BREAK Specify first break point:"))
            ctx.set_last_point(first)
            continue
        if value.kind == "keyword":
            ctx.feedback("BREAK: second point or [First] required")
            continue
        second = value.value
        ctx.set_last_point(second)
        message, created, removed = _break_apply(
            doc, eid, entity, first.to_tuple(), second.to_tuple())
        if message is not None:
            ctx.feedback(f"BREAK: {message}")
            continue  # degenerate pick: re-ask the second point
        summary = "BREAK: 1 object broken"
        if created:
            summary += f" into {len(created)} piece(s)"
        return CommandResult(
            status="ok", summary=summary, created=created,
            removed=[removed] if removed else [],
        )


def _break_apply(doc, eid, entity, first, second):
    """Apply one break inside ONE transaction.

    Returns ``(message, created_ids, removed_id)`` — the message is None on
    success (the ids report the committed change to the CommandResult), or a
    diagnostic string when the picks are degenerate (the command re-asks the
    second point; nothing was committed).
    """
    kind = entity.kind
    if kind == "line":
        pieces = _line_break_pieces(entity, first, second)
        created: List[str] = []
        with doc.transaction("BREAK"):
            doc.remove(eid)
            for piece in pieces:
                created.append(doc.add_entity(piece).id)
        return None, created, eid
    if kind == "circle":
        a1 = geometry.angle_of((first[0] - entity.center[0],
                                first[1] - entity.center[1]))
        a2 = geometry.angle_of((second[0] - entity.center[0],
                                second[1] - entity.center[1]))
        if _pick_sweep(a1, a2) <= geometry.TOL:
            return "break points coincide", [], None
        # remove the CCW arc first→second; the survivor runs CCW from the
        # second point back to the first
        with doc.transaction("BREAK"):
            doc.remove(eid)
            created = [doc.add_entity(Arc(
                entity.center, entity.radius,
                geometry.normalize_deg(a2), geometry.normalize_deg(a1),
                **_offset_props(entity))).id]
        return None, created, eid
    if kind == "arc":
        pieces, reason = _arc_break_pieces(entity, first, second)
        if reason is not None:
            return reason, [], None
        created = []
        with doc.transaction("BREAK"):
            doc.remove(eid)
            for piece in pieces:
                created.append(doc.add_entity(piece).id)
        return None, created, eid
    # polyline
    pieces, reason = _polyline_break_pieces(entity, first, second)
    if reason is not None:
        return reason, [], None
    created = []
    with doc.transaction("BREAK"):
        doc.remove(eid)
        for piece in pieces:
            created.append(doc.add_entity(piece).id)
    return None, created, eid


# ---------------------------------------------------------------------------
# JOIN — merge collinear lines / concentric arcs; grow polylines
# ---------------------------------------------------------------------------

def _join_lines(source: Line, joiner: Line):
    """Collinear merge: parallel directions AND the joiner's endpoints on
    the source's infinite line (tolerance 1e-9). Returns the merged
    (p1, p2) — the two endpoints farthest apart."""
    d1 = (source.p2[0] - source.p1[0], source.p2[1] - source.p1[1])
    d2 = (joiner.p2[0] - joiner.p1[0], joiner.p2[1] - joiner.p1[1])
    len1 = math.hypot(*d1)
    len2 = math.hypot(*d2)
    if len1 <= geometry.TOL or len2 <= geometry.TOL:
        return None
    cross = abs(d1[0] * d2[1] - d1[1] * d2[0]) / (len1 * len2)
    if cross > 1e-9:
        return None  # not parallel
    ux, uy = d1[0] / len1, d1[1] / len1
    for point in (joiner.p1, joiner.p2):
        offset = abs(ux * (point[1] - source.p1[1])
                     - uy * (point[0] - source.p1[0]))
        if offset > 1e-9:
            return None  # not on the source line
    endpoints = [source.p1, source.p2, joiner.p1, joiner.p2]
    best = None
    best_distance = -1.0
    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            distance = geometry.dist_2d(endpoints[i], endpoints[j])
            if distance > best_distance:
                best_distance = distance
                best = (endpoints[i], endpoints[j])
    return best


def _join_arcs(source: Arc, joiner: Arc):
    """Concentric same-radius sweep merge. Returns
    ("update", start, end) | ("circle", None, None) | ("skip", reason)."""
    if geometry.dist_2d(source.center, joiner.center) > 1e-9:
        return "skip", "arcs are not concentric"
    if abs(source.radius - joiner.radius) > 1e-9:
        return "skip", "arc radii differ"
    w_source = geometry._ccw_from(source.start_angle, source.end_angle)
    w_joiner = geometry._ccw_from(joiner.start_angle, joiner.end_angle)
    start = source.start_angle
    b1 = geometry.normalize_deg(joiner.start_angle - start)
    b2 = b1 + w_joiner
    if b1 <= w_source + geometry.TOL:
        sweep = min(360.0, max(w_source, b2))
        merged_start = start
    elif b2 >= 360.0 - geometry.TOL:
        sweep = min(360.0, 360.0 + w_source - b1)
        merged_start = geometry.normalize_deg(start + b1)
    else:
        return "skip", "arcs are not contiguous"
    if sweep >= 360.0 - geometry.TOL:
        return "circle", None, None
    return "update", merged_start, geometry.normalize_deg(
        merged_start + sweep)


def _polyline_grow(doc, entity, append_vertices, append_bulges, prepend=None):
    """Grow an OPEN polyline by appending (or prepending) vertices.

    The appended ``append_bulges`` value is the CONNECTOR segment's bulge
    (it leaves the current last vertex — AutoCAD bulge convention). A
    prepend bulge is the leaving segment of the NEW first vertex.
    Length-changing update_entity is not expressible under bcdoc v2's
    per-field validation, so the growth commits as a same-identity
    remove+re-add (one undo step; see _replace_entity)."""
    vertices = list(entity.vertices)
    bulges = list(entity.bulges) if entity.bulges else [0.0] * len(vertices)
    widths = list(entity.widths) if entity.widths else None
    if prepend is not None:
        point, bulge = prepend
        vertices.insert(0, point)
        bulges.insert(0, bulge)
        if widths is not None:
            widths.insert(0, (0.0, 0.0))
    for point, bulge in zip(append_vertices, append_bulges):
        bulges[-1] = bulge  # the connector leaves the current last vertex
        vertices.append(point)
        bulges.append(0.0)
        if widths is not None:
            widths.append((0.0, 0.0))
    replacement = Polyline(vertices, bulges=bulges, widths=widths,
                           closed=entity.closed, **_offset_props(entity))
    _replace_entity(doc, entity.id, replacement)
    return replacement


def _join_into_polyline(doc, entity: Polyline, joiner) -> Optional[str]:
    """Absorb a connecting line/arc into an OPEN polyline. Returns None on
    success or the skip reason."""
    if entity.closed:
        return "source polyline is closed (no open end)"
    first, last = entity.vertices[0], entity.vertices[-1]
    if joiner.kind == "line":
        if geometry.dist_2d(last, joiner.p2) <= 1e-9:
            far = joiner.p1  # joiner ENDS at the polyline tail: append its p1
        elif geometry.dist_2d(last, joiner.p1) <= 1e-9:
            far = joiner.p2
        else:
            far = None
        if far is not None:
            if geometry.dist_2d(last, far) <= geometry.TOL:
                return "line is degenerate"
            _polyline_grow(doc, entity, [far], [0.0])
            return None
        if geometry.dist_2d(first, joiner.p2) <= 1e-9:
            _polyline_grow(doc, entity, [], [], prepend=(joiner.p1, 0.0))
            return None
        if geometry.dist_2d(first, joiner.p1) <= 1e-9:
            _polyline_grow(doc, entity, [], [], prepend=(joiner.p2, 0.0))
            return None
        return "line does not touch either end"
    if joiner.kind == "arc":
        sweep = geometry._ccw_from(joiner.start_angle, joiner.end_angle)
        arc_start = (
            joiner.center[0] + joiner.radius * math.cos(
                math.radians(joiner.start_angle)),
            joiner.center[1] + joiner.radius * math.sin(
                math.radians(joiner.start_angle)),
            joiner.center[2])
        arc_end = (
            joiner.center[0] + joiner.radius * math.cos(
                math.radians(joiner.end_angle)),
            joiner.center[1] + joiner.radius * math.sin(
                math.radians(joiner.end_angle)),
            joiner.center[2])
        base_bulge = geometry.bulge_from_arc(arc_start, arc_end, joiner.center)
        if geometry.dist_2d(last, arc_start) <= 1e-9:
            # leave the tail through the arc's START: CCW traversal
            _polyline_grow(doc, entity, [arc_end], [base_bulge])
            return None
        if geometry.dist_2d(last, arc_end) <= 1e-9:
            # enter through the arc's END: reversed (CW) traversal
            _polyline_grow(doc, entity, [arc_start], [-base_bulge])
            return None
        if geometry.dist_2d(first, arc_start) <= 1e-9:
            # the path arrives at the head through the arc's start: the new
            # first segment runs arc_end→arc_start (CW traversal)
            _polyline_grow(doc, entity, [], [], prepend=(arc_end, -base_bulge))
            return None
        if geometry.dist_2d(first, arc_end) <= 1e-9:
            _polyline_grow(doc, entity, [], [], prepend=(arc_start, base_bulge))
            return None
        return "arc does not touch either end"
    return f"cannot join a {joiner.kind} into a polyline (v0)"


def join_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "JOIN")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "JOIN", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="JOIN: no objects selected")
    if len(modifiable) > 1:
        ctx.feedback("JOIN: one source object at a time — using the first")
    source_id = modifiable[0]
    source = doc.get(source_id)
    if source.kind not in ("line", "arc", "polyline"):
        ctx.feedback(f"JOIN: source must be a line, arc or polyline (got {source.kind})")
        return CommandResult(status="ok", summary="JOIN: unsupported source")
    value = yield Request("selection", "JOIN Select objects to join:")
    joiners = []
    while True:
        if value.kind == "selection":
            joiners.extend(value.value or [])
            break
        if value.kind == "keyword" and value.value == "Enter":
            break
        ctx.feedback("JOIN: select objects to join, or press Enter")
        value = yield Request("selection", "JOIN Select objects to join:")
    joiners = existing_ids(doc, joiners)
    joiners, locked = _split_locked(doc, joiners)
    _skip_locked(ctx, "JOIN", locked)
    joiners = [jid for jid in joiners if jid != source_id]
    if not joiners:
        return CommandResult(status="ok", summary="JOIN: nothing to join")
    joined = 0
    reasons: List[str] = []
    removed: List[str] = []
    with doc.transaction("JOIN"):
        for jid in joiners:
            joiner = doc.get(jid)
            source = doc.get(source_id)  # re-read: growth replaced the object
            reason = None
            if source.kind == "line":
                if joiner.kind != "line":
                    reason = (f"cannot join a {joiner.kind} into a line "
                              "(v0 — cross-kind merges are not modeled)")
                else:
                    merged = _join_lines(source, joiner)
                    if merged is None:
                        reason = "lines are not collinear"
                    else:
                        doc.update_entity(source_id, p1=merged[0], p2=merged[1])
            elif source.kind == "arc":
                if joiner.kind != "arc":
                    reason = (f"cannot join a {joiner.kind} into an arc (v0)")
                else:
                    outcome = _join_arcs(source, joiner)
                    if outcome[0] == "skip":
                        reason = outcome[1]
                    elif outcome[0] == "circle":
                        circle = Circle(source.center, source.radius,
                                        **_offset_props(source))
                        _replace_entity(doc, source_id, circle)
                    else:
                        doc.update_entity(
                            source_id, start_angle=outcome[1],
                            end_angle=outcome[2])
            else:  # polyline source
                reason = _join_into_polyline(doc, source, joiner)
            if reason is None:
                joined += 1
                # AutoCAD semantics: a successfully absorbed joiner is
                # DELETED (its geometry now lives in the merged source)
                doc.remove(jid)
                removed.append(jid)
            else:
                reasons.append(f"{joiner.kind}: {reason}")
                ctx.feedback(f"JOIN: skipped — {reasons[-1]}")
    summary = f"JOIN: {joined} object(s) merged"
    if reasons:
        summary += f", {len(reasons)} skipped"
    return CommandResult(
        status="ok", summary=summary,
        modified=[source_id] if joined else [],
        removed=removed,
    )


# ---------------------------------------------------------------------------
# EXPLODE — inserts → transformed members; polylines → line/arc segments
# ---------------------------------------------------------------------------

def explode_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "EXPLODE")
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "EXPLODE", locked)
    if not modifiable:
        return CommandResult(status="ok", summary="EXPLODE: no objects selected")
    created: List[str] = []
    removed: List[str] = []
    with doc.transaction("EXPLODE"):
        for eid in modifiable:
            entity = doc.get(eid)
            if entity.kind == "insert":
                try:
                    definition = doc.block(entity.name)
                except Exception:
                    ctx.feedback(
                        f"EXPLODE: block '{entity.name}' not found — skipped")
                    continue
                for member in definition.entities:
                    exploded = geometry.apply_insert_transform(
                        member, definition.base_point, entity.position,
                        entity.scale, entity.rotation)
                    exploded.space = entity.space
                    if exploded.layer == "0":
                        # layer-0 members adopt the INSERT's layer
                        exploded.layer = entity.layer
                    if exploded.color == 0:
                        # ByBlock resolves to the INSERT's color (None =
                        # ByLayer of the member's own — possibly adopted — layer)
                        exploded.color = entity.color
                    created.append(doc.add_entity(exploded).id)
                doc.remove(eid)
                removed.append(eid)
            elif entity.kind == "polyline":
                if entity.widths:
                    ctx.feedback("EXPLODE: polyline widths dropped (v0)")
                for start, end, bulge in geometry.polyline_segments(entity):
                    if abs(bulge) <= geometry.TOL:
                        created.append(doc.add_entity(Line(
                            start, end, **_offset_props(entity))).id)
                    else:
                        center, radius, s_angle, e_angle = (
                            geometry.arc_from_bulge(start, end, bulge))
                        created.append(doc.add_entity(Arc(
                            center, radius, s_angle, e_angle,
                            **_offset_props(entity))).id)
                doc.remove(eid)
                removed.append(eid)
            else:
                ctx.feedback(f"EXPLODE: cannot explode a {entity.kind} (v0)")
    summary = f"EXPLODE: {len(removed)} object(s) exploded into {len(created)}"
    return CommandResult(
        status="ok", summary=summary, created=created, removed=removed)


# ---------------------------------------------------------------------------
# STRETCH — crossing window moves only the vertices inside it
# ---------------------------------------------------------------------------

def _stretch_entity_changes(entity, rect, delta):
    """Per-kind stretch field changes; None when nothing moves. Arcs return
    "skip" (endpoint moves are unsupported at v0)."""
    kind = entity.kind
    if kind in ("line", "xline", "ray"):
        changes = {}
        p1_inside = geometry.point_in_rect(entity.p1, rect)
        p2_inside = geometry.point_in_rect(entity.p2, rect)
        if p1_inside:
            changes["p1"] = geometry.move_pt(entity.p1, delta)
        if p2_inside:
            changes["p2"] = geometry.move_pt(entity.p2, delta)
        return changes or None
    if kind == "polyline":
        moved = False
        vertices = []
        for vertex in entity.vertices:
            if geometry.point_in_rect(vertex, rect):
                vertices.append(geometry.move_pt(vertex, delta))
                moved = True
            else:
                vertices.append(vertex)
        return {"vertices": vertices} if moved else None
    if kind == "circle":
        return ({"center": geometry.move_pt(entity.center, delta)}
                if geometry.point_in_rect(entity.center, rect) else None)
    if kind == "point":
        return ({"position": geometry.move_pt(entity.position, delta)}
                if geometry.point_in_rect(entity.position, rect) else None)
    if kind == "ellipse":
        return ({"center": geometry.move_pt(entity.center, delta)}
                if geometry.point_in_rect(entity.center, rect) else None)
    if kind in ("text", "mtext"):
        return ({"position": geometry.move_pt(entity.position, delta)}
                if geometry.point_in_rect(entity.position, rect) else None)
    if kind == "insert":
        return ({"position": geometry.move_pt(entity.position, delta)}
                if geometry.point_in_rect(entity.position, rect) else None)
    if kind == "dim":
        return (geometry.move_changes(entity, delta)
                if geometry.point_in_rect(entity.p1, rect) else None)
    if kind == "viewport":
        anchor = ((entity.p1[0] + entity.p2[0]) / 2.0,
                  (entity.p1[1] + entity.p2[1]) / 2.0, entity.p1[2])
        return (geometry.move_changes(entity, delta)
                if geometry.point_in_rect(anchor, rect) else None)
    if kind == "arc":
        return "skip"  # endpoint move unsupported at v0 (documented)
    return None


def stretch_steps(ctx):
    doc = ctx.document
    first = yield from ask_point(
        ctx, Request("point", "STRETCH Specify first corner of the crossing window:"))
    ctx.set_last_point(first)
    second = yield from ask_point(
        ctx, Request("point", "STRETCH Specify opposite corner:"))
    ctx.set_last_point(second)
    rect = geometry.rect_of(first.to_tuple(), second.to_tuple())
    ids = crossing_ids(doc, first.to_tuple(), second.to_tuple())
    modifiable, locked = _split_locked(doc, ids)
    _skip_locked(ctx, "STRETCH", locked)
    if not modifiable:
        return CommandResult(
            status="ok", summary="STRETCH: no objects in the crossing window")
    base = yield from ask_point(ctx, Request("point", "STRETCH Specify base point:"))
    ctx.set_last_point(base)
    value = yield Request(
        "point", "STRETCH Specify second point or <use first as displacement>:")
    while value.kind != "point":
        ctx.feedback("STRETCH: second point required")
        value = yield Request(
            "point", "STRETCH Specify second point or <use first as displacement>:")
    delta = value.value - base
    ctx.set_last_point(value.value)
    stretched: List[str] = []
    with doc.transaction("STRETCH"):
        for eid in modifiable:
            entity = doc.get(eid)
            changes = _stretch_entity_changes(entity, rect, delta.to_tuple())
            if changes == "skip":
                ctx.feedback(
                    "STRETCH: arc endpoint move not supported (v0) — skipped")
                continue
            if not changes:
                continue  # selected by crossing, no vertex inside the window
            doc.update_entity(eid, **changes)
            stretched.append(eid)
    summary = f"STRETCH: {len(stretched)} object(s) stretched"
    return CommandResult(status="ok", summary=summary, modified=stretched)


# ---------------------------------------------------------------------------
# MATCHPROP — copy layer/color/linetype/lineweight to targets
# ---------------------------------------------------------------------------

def matchprop_steps(ctx):
    doc = ctx.document
    source_ids = yield from select_ids(ctx, "MATCHPROP")
    modifiable, locked = _split_locked(doc, source_ids)
    _skip_locked(ctx, "MATCHPROP", locked)
    if not modifiable:
        return CommandResult(
            status="ok", summary="MATCHPROP: no source object selected")
    if len(modifiable) > 1:
        ctx.feedback("MATCHPROP: one source object — using the first")
    source = doc.get(modifiable[0])
    target_ids = yield from select_ids(ctx, "MATCHPROP")
    targets, locked = _split_locked(doc, target_ids)
    _skip_locked(ctx, "MATCHPROP", locked)
    if not targets:
        return CommandResult(
            status="ok", summary="MATCHPROP: no target objects selected")
    with doc.transaction("MATCHPROP"):
        for eid in targets:
            # update_entity auto-creates a missing source layer inside this
            # same transaction (journaled, so undo reverts both atomically)
            doc.update_entity(
                eid,
                layer=source.layer,
                color=source.color,
                linetype=source.linetype,
                lineweight=source.lineweight,
            )
    summary = f"MATCHPROP: {len(targets)} object(s) updated from layer {source.layer!r}"
    return CommandResult(status="ok", summary=summary, modified=targets)


# ---------------------------------------------------------------------------
# Command specs
# ---------------------------------------------------------------------------

ERASE = CommandSpec(
    name="ERASE", aliases=["E"], steps=erase_steps,
    help="Remove selected objects",
)
MOVE = CommandSpec(
    name="MOVE", aliases=["M"], steps=move_steps,
    help="Displace objects by base point and second point",
)
COPY = CommandSpec(
    name="COPY", aliases=["CO"], steps=copy_steps,
    help="Duplicate objects to one or more placements",
)
ROTATE = CommandSpec(
    name="ROTATE", aliases=["RO"], steps=rotate_steps,
    help="Rotate objects CCW about a base point",
)
SCALE = CommandSpec(
    name="SCALE", aliases=["SC"], steps=scale_steps,
    help="Scale objects uniformly about a base point",
)
MIRROR = CommandSpec(
    name="MIRROR", aliases=["MI"], steps=mirror_steps,
    help="Reflect objects across a two-point axis ([Yes/No] erase source)",
)
OFFSET = CommandSpec(
    name="OFFSET", aliases=["O"], steps=offset_steps,
    help="Parallel copies at a distance or through a point (one object at a time)",
)
ARRAYRECT = CommandSpec(
    name="ARRAYRECT", aliases=["AR"], steps=arrayrect_steps,
    help="Rectangular rows × columns array of copies",
)
BREAK = CommandSpec(
    name="BREAK", aliases=["BR"], steps=break_steps,
    help="Remove the part of one object between two picked points",
)
JOIN = CommandSpec(
    name="JOIN", aliases=["J"], steps=join_steps,
    help="Merge collinear lines and concentric arcs; grow open polylines",
)
EXPLODE = CommandSpec(
    name="EXPLODE", aliases=["X"], steps=explode_steps,
    help="Inserts → transformed members; polylines → line/arc segments",
)
STRETCH = CommandSpec(
    name="STRETCH", aliases=["S"], steps=stretch_steps,
    help="Move the vertices inside a crossing window (crossing implied)",
)
MATCHPROP = CommandSpec(
    name="MATCHPROP", aliases=["MA"], steps=matchprop_steps,
    help="Copy layer/color/linetype/lineweight from a source to targets",
)

COMMANDS = (
    ERASE, MOVE, COPY, ROTATE, SCALE, MIRROR, OFFSET, ARRAYRECT, BREAK,
    JOIN, EXPLODE, STRETCH, MATCHPROP,
)
