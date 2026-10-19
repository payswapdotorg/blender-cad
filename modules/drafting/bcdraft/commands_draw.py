"""Draw commands: LINE (chained, Close/Undo), CIRCLE (Radius/Diameter),
ARC (3-point + Start-Center-End) — contract §5, M1 scope.

Every command is a steps-generator driven either by the blocking prompt
loop (bccmd.run_steps) or step-by-step by the modal viewport operator
(bccmd.StepDriver) — one implementation, one state machine. All document
mutations happen inside transactions (contract §4.2 binding rule). LINE
commits ONE transaction per segment (each committed segment = one undo
step — the familiar AutoCAD granularity, ux-spec §3.10).
"""

from __future__ import annotations

from typing import List

from bccmd import CommandResult, CommandSpec, Point, Request
from bcdoc.entities import Arc, Circle, Line  # document entities (declared dep)
from . import geometry
from ._common import add_entity, ask_point, ask_positive_distance, require_point


# ---------------------------------------------------------------------------
# LINE
# ---------------------------------------------------------------------------

def line_steps(ctx):
    doc = ctx.document
    created: List[str] = []
    closed = False
    while True:  # restartable: Undo before the first segment re-asks point 1
        first = yield from ask_point(ctx, Request("point", "LINE Specify first point:"))
        ctx.set_last_point(first)
        points = [first]
        finish = None
        while True:
            segments = len(points) - 1
            options = ["Undo"] if segments == 0 else ["Close", "Undo"]
            value = yield Request(
                "point",
                "LINE Specify next point or [{}]: ".format("/".join(options)),
                options=options,
            )
            if value.kind == "keyword":
                keyword = value.value
                if keyword == "Undo":
                    if segments == 0:
                        ctx.feedback("LINE: first point discarded")
                        break  # back to the first-point prompt
                    # Undo removes the last committed segment of THIS run
                    # (one transaction per segment = one undo step).
                    if doc.undo():
                        created.pop()
                        points.pop()
                        ctx.set_last_point(points[-1])
                        ctx.feedback("LINE: last segment undone")
                    continue
                if keyword == "Close":
                    if segments >= 1:
                        entity = add_entity(
                            ctx, _line(points[-1], points[0]), "LINE Close"
                        )
                        created.append(entity.id)
                        closed = True
                    finish = "closed"
                    break
                if keyword == "Enter":
                    finish = "end"
                    break
                ctx.feedback("LINE: point or [{}] required".format("/".join(options)))
                continue
            if value.kind != "point":
                ctx.feedback("LINE: point or option required")
                continue
            entity = add_entity(
                ctx, _line(points[-1], value.value), "LINE segment"
            )
            created.append(entity.id)
            points.append(value.value)
            ctx.set_last_point(value.value)
        if finish is not None:
            break
    summary = f"LINE: {len(created)} segment(s)"
    if closed:
        summary += " [closed]"
    return CommandResult(status="ok", summary=summary, created=created)


def _line(p1: Point, p2: Point) -> Line:
    return Line(p1.to_tuple(), p2.to_tuple())


# ---------------------------------------------------------------------------
# CIRCLE
# ---------------------------------------------------------------------------

def circle_steps(ctx):
    doc = ctx.document
    center = yield from ask_point(
        ctx, Request("point", "CIRCLE Specify center point for circle:")
    )
    ctx.set_last_point(center)
    while True:
        value = yield Request(
            "distance", "CIRCLE Specify radius of circle or [Diameter]:",
            options=["Diameter"],
        )
        if value.kind == "keyword" and value.value == "Diameter":
            diameter = yield from ask_positive_distance(
                ctx, Request("distance", "CIRCLE Specify diameter of circle:")
            )
            radius = diameter / 2.0
            break
        if value.kind == "distance" and float(value.value) > 0.0:
            radius = float(value.value)
            break
        if value.kind == "point":
            # point entry: radius = distance from the center (mouse distance)
            radius = geometry.dist_2d(
                (center.x, center.y), (value.value.x, value.value.y)
            )
            if radius > 0.0:
                break
            ctx.feedback("CIRCLE: radius must be positive")
            continue
        ctx.feedback("CIRCLE: positive radius, point or [Diameter]")
    entity = add_entity(ctx, _circle(center, radius), "CIRCLE")
    return CommandResult(
        status="ok",
        summary=f"CIRCLE: radius {radius:g} at ({center.x:g}, {center.y:g})",
        created=[entity.id],
    )


def _circle(center: Point, radius: float) -> Circle:
    return Circle(center.to_tuple(), float(radius))


# ---------------------------------------------------------------------------
# ARC — default 3-point; [Center] switches to Start-Center-End
# ---------------------------------------------------------------------------

def arc_steps(ctx):
    value = yield Request(
        "point", "ARC Specify start point of arc or [Center]:",
        options=["Center"],
    )
    if value.kind == "keyword" and value.value == "Center":
        return (yield from _arc_center_end(ctx))
    try:
        start = require_point(value)
    except ValueError as exc:
        ctx.feedback(str(exc))
        start = yield from ask_point(
            ctx, Request("point", "ARC Specify start point of arc:")
        )
    ctx.set_last_point(start)
    mid = yield from ask_point(
        ctx, Request("point", "ARC Specify second point of arc:")
    )
    while True:
        end = yield from ask_point(
            ctx, Request("point", "ARC Specify end point of arc:")
        )
        result = geometry.arc_from_3p(
            (start.x, start.y, start.z), (mid.x, mid.y, mid.z),
            (end.x, end.y, end.z),
        )
        if result is None:
            ctx.feedback("ARC: points are collinear — specify another end point")
            continue
        center, radius, a_start, a_end = result
        entity = add_entity(ctx, _arc(center, radius, a_start, a_end), "ARC")
        ctx.set_last_point(end)
        return CommandResult(
            status="ok",
            summary=(
                f"ARC: 3-point through ({start.x:g}, {start.y:g}), "
                f"({mid.x:g}, {mid.y:g}), ({end.x:g}, {end.y:g})"
            ),
            created=[entity.id],
        )


def _arc_center_end(ctx):
    center = yield from ask_point(ctx, Request("point", "ARC Specify center point:"))
    while True:
        start = yield from ask_point(
            ctx, Request("point", "ARC Specify start point of arc:")
        )
        radius = geometry.dist_2d((center.x, center.y), (start.x, start.y))
        if radius > 0.0:
            break
        ctx.feedback("ARC: start point must differ from the center")
    ctx.set_last_point(start)
    a_start = geometry.angle_of((start.x - center.x, start.y - center.y))
    while True:
        end = yield from ask_point(ctx, Request("point", "ARC Specify end point of arc:"))
        a_end = geometry.angle_of((end.x - center.x, end.y - center.y))
        # AutoCAD SCE: the arc runs CCW from start to end about the center.
        sweep = geometry.normalize_deg(a_end - a_start)
        if sweep <= geometry.TOL:
            sweep = 360.0
        entity = add_entity(
            ctx, _arc(center.to_tuple(), radius, a_start, a_start + sweep), "ARC"
        )
        ctx.set_last_point(end)
        return CommandResult(
            status="ok",
            summary=(
                f"ARC: start-center-end, radius {radius:g}, "
                f"CCW {sweep:g}° about ({center.x:g}, {center.y:g})"
            ),
            created=[entity.id],
        )


def _arc(center, radius: float, start_angle: float, end_angle: float) -> Arc:
    return Arc(
        tuple(center), float(radius),
        geometry.normalize_deg(start_angle), geometry.normalize_deg(end_angle),
    )


# ---------------------------------------------------------------------------
# Command specs (aliases follow ux-specification §3.1 shipped defaults)
# ---------------------------------------------------------------------------

LINE = CommandSpec(
    name="LINE", aliases=["L"], steps=line_steps,
    help="Straight line segments; chained with Close/Undo options",
)
CIRCLE = CommandSpec(
    name="CIRCLE", aliases=["C"], steps=circle_steps,
    help="Full circle by center and radius or diameter",
)
ARC = CommandSpec(
    name="ARC", aliases=["A"], steps=arc_steps,
    help="Arc by three points or start-center-end",
)

COMMANDS = (LINE, CIRCLE, ARC)
