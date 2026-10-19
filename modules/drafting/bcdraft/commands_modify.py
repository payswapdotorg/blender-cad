"""Modify commands: ERASE, MOVE, COPY, ROTATE, SCALE — contract §5, M1 scope.

All transforms are analytic recomputations (line endpoints, circle center,
arc center + angles) — no kernel at M1 (ADR-0002). Each mutation set runs
inside ONE document transaction per command (MOVE/ERASE/ROTATE/SCALE = one
committed undo step; COPY = one per placement), and every mutation goes
through the JOURNALED document API (``add_entity`` / ``remove`` /
``update_entity``) so UNDO restores geometry — direct attribute writes
would bypass the undo journal (see bcdraft.geometry docstring).

COPY keeps prompting for additional placements (AutoCAD multiple copy) with
[Exit/Undo] options; its Undo option pops the last placement of THIS run via
one document undo step.
"""

from __future__ import annotations

from typing import List

from bccmd import CommandResult, CommandSpec, Point, Request
from . import geometry
from ._common import existing_ids, select_ids


# ---------------------------------------------------------------------------
# ERASE
# ---------------------------------------------------------------------------

def erase_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "ERASE")
    if not ids:
        return CommandResult(status="ok", summary="ERASE: no objects selected")
    removed: List[str] = []
    with doc.transaction("ERASE"):
        for eid in ids:
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
    if not ids:
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
        for eid in ids:
            entity = doc.get(eid)
            doc.update_entity(eid, **geometry.move_changes(entity, delta.to_tuple()))
    return CommandResult(
        status="ok",
        summary=(
            f"MOVE: {len(ids)} object(s) by "
            f"({delta.x:g}, {delta.y:g}, {delta.z:g})"
        ),
        modified=ids,
    )


# ---------------------------------------------------------------------------
# COPY (multiple placements, [Exit/Undo])
# ---------------------------------------------------------------------------

def copy_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "COPY")
    if not ids:
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
                    del created[-len(ids):]
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
            for eid in ids:
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
    if not ids:
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
        for eid in ids:
            entity = doc.get(eid)
            doc.update_entity(
                eid, **geometry.rotate_changes(entity, base.to_tuple(), float(angle))
            )
    return CommandResult(
        status="ok",
        summary=f"ROTATE: {len(ids)} object(s) {angle:g}° CCW about base point",
        modified=ids,
    )


# ---------------------------------------------------------------------------
# SCALE (base point + factor; [Reference] length ratio)
# ---------------------------------------------------------------------------

def scale_steps(ctx):
    doc = ctx.document
    ids = yield from select_ids(ctx, "SCALE")
    if not ids:
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
        for eid in ids:
            entity = doc.get(eid)
            doc.update_entity(
                eid, **geometry.scale_changes(entity, base.to_tuple(), factor)
            )
    return CommandResult(
        status="ok",
        summary=f"SCALE: {len(ids)} object(s) × {factor:g} about base point",
        modified=ids,
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

COMMANDS = (ERASE, MOVE, COPY, ROTATE, SCALE)
