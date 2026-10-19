"""Draw commands: LINE (chained, Close/Undo), CIRCLE (Radius/Diameter/2P/3P),
ARC (3-point + Start-Center-End), PLINE (+arc segments via tangent
continuation, +per-vertex widths), RECTANG, POLYGON, POINT, XLINE, RAY,
ELLIPSE — contract §0 drafting core, M1 + M2 scope.

Every command is a steps-generator driven either by the blocking prompt
loop (bccmd.run_steps) or step-by-step by the modal viewport operator
(bccmd.StepDriver) — one implementation, one state machine. All document
mutations happen inside transactions (contract §4.2 binding rule). LINE
and PLINE commit ONE transaction per segment (each committed segment = one
undo step — the familiar AutoCAD granularity, ux-spec §3.10); PLINE mutates
its single committed Polyline per segment through the journaled
``update_entity`` path.

New entities are created on the CURRENT layer (CLAYER) and in the CURRENT
space (``doc.current_space``), so the M2 LAYER/Layout commands route them.
Typed "2P"/"3P" at the CIRCLE center prompt arrive as keyword InputValues
from the shell/agents; the M1 text parser classifies digit-leading tokens
as numeric (W-A integration note — see worklog).
"""

from __future__ import annotations

import math
from typing import List, Optional

from bccmd import CommandResult, CommandSpec, Point, Request
from bcdoc.entities import Arc, Circle, Line, Point as PointEntity, Polyline, Ellipse, Xline, Ray
from . import geometry
from ._common import add_entity, ask_point, ask_positive_distance, dde_input, require_point


def _entity_kwargs(doc) -> dict:
    """Current-layer / current-space routing for every entity a draw
    command creates (M2: entities follow CLAYER + the active space)."""
    return {"layer": doc.current_layer, "space": doc.current_space}


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
            if value.kind == "keyword" and not (
                isinstance(value.value, str) and value.value.startswith("osnap:")
            ):
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
                            ctx, _line(doc, points[-1], points[0]), "LINE Close"
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
            # M2 precision legs for the chained prompt (contracts §3/§4):
            # osnap one-shot keywords arm the override; typed distances are
            # direct-distance entry; mouse points resolve (grid/ortho/osnap).
            converted = dde_input(ctx, value)
            if converted is None:
                continue
            value = converted
            if value.kind != "point":
                ctx.feedback("LINE: point or option required")
                continue
            entity = add_entity(
                ctx, _line(doc, points[-1], value.value), "LINE segment"
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


def _line(doc, p1: Point, p2: Point) -> Line:
    return Line(p1.to_tuple(), p2.to_tuple(), **_entity_kwargs(doc))


# ---------------------------------------------------------------------------
# CIRCLE — center+radius / center+diameter / 2P / 3P
# ---------------------------------------------------------------------------

def circle_steps(ctx):
    doc = ctx.document
    value = yield Request(
        "point", "CIRCLE Specify center point for circle or [2P/3P]:",
        options=["2P", "3P"],
    )
    if value.kind == "keyword" and value.value == "2P":
        return (yield from _circle_two_point(ctx))
    if value.kind == "keyword" and value.value == "3P":
        return (yield from _circle_three_point(ctx))
    try:
        center = require_point(value)
    except ValueError as exc:
        ctx.feedback(str(exc))
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
    entity = add_entity(ctx, _circle(doc, center, radius), "CIRCLE")
    return CommandResult(
        status="ok",
        summary=f"CIRCLE: radius {radius:g} at ({center.x:g}, {center.y:g})",
        created=[entity.id],
    )


def _circle_two_point(ctx):
    doc = ctx.document
    first = yield from ask_point(
        ctx, Request("point", "CIRCLE Specify first endpoint of circle's diameter:"))
    ctx.set_last_point(first)
    while True:
        second = yield from ask_point(
            ctx, Request("point", "CIRCLE Specify second endpoint of circle's diameter:"))
        if geometry.dist_2d(
                (first.x, first.y), (second.x, second.y)) <= geometry.TOL:
            ctx.feedback("CIRCLE: endpoints must differ")
            continue
        break
    p1, p2 = first.to_tuple(), second.to_tuple()
    center = geometry.move_pt(
        p1, ((p2[0] - p1[0]) / 2.0, (p2[1] - p1[1]) / 2.0, (p2[2] - p1[2]) / 2.0)
    )
    radius = geometry.dist_2d(p1, p2) / 2.0
    ctx.set_last_point(second)
    entity = add_entity(ctx, _circle(doc, second, radius, center), "CIRCLE 2P")
    return CommandResult(
        status="ok",
        summary=f"CIRCLE: 2P diameter, radius {radius:g} at ({center[0]:g}, {center[1]:g})",
        created=[entity.id],
    )


def _circle_three_point(ctx):
    doc = ctx.document
    first = yield from ask_point(
        ctx, Request("point", "CIRCLE Specify first point on circle:"))
    ctx.set_last_point(first)
    while True:
        second = yield from ask_point(
            ctx, Request("point", "CIRCLE Specify second point on circle:"))
        if geometry.dist_2d(
                (first.x, first.y), (second.x, second.y)) <= geometry.TOL:
            ctx.feedback("CIRCLE: points must differ")
            continue
        break
    ctx.set_last_point(second)
    while True:
        third = yield from ask_point(
            ctx, Request("point", "CIRCLE Specify third point on circle:"))
        # perpendicular-bisector math (circumcenter); collinear or duplicate
        # points cannot define a circle → diagnostic + re-ask the third point
        circle = geometry.circumcenter(
            first.to_tuple(), second.to_tuple(), third.to_tuple()
        )
        if circle is None:
            ctx.feedback("CIRCLE: points are collinear — specify another point")
            continue
        center, radius = circle
        break
    ctx.set_last_point(third)
    entity = add_entity(
        ctx, _circle(doc, third, radius, center), "CIRCLE 3P")
    return CommandResult(
        status="ok",
        summary=(
            f"CIRCLE: 3P through ({first.x:g}, {first.y:g}), "
            f"({second.x:g}, {second.y:g}), ({third.x:g}, {third.y:g})"
        ),
        created=[entity.id],
    )


def _circle(doc, point_on: Point, radius: float, center=None) -> Circle:
    if center is None:
        center = point_on.to_tuple()
    return Circle(tuple(center), float(radius), **_entity_kwargs(doc))


# ---------------------------------------------------------------------------
# ARC — default 3-point; [Center] switches to Start-Center-End
# ---------------------------------------------------------------------------

def arc_steps(ctx):
    doc = ctx.document
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
        entity = add_entity(ctx, _arc(doc, center, radius, a_start, a_end), "ARC")
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
    doc = ctx.document
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
            ctx, _arc(doc, center.to_tuple(), radius, a_start, a_start + sweep), "ARC"
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


def _arc(doc, center, radius: float, start_angle: float, end_angle: float) -> Arc:
    return Arc(
        tuple(center), float(radius),
        geometry.normalize_deg(start_angle), geometry.normalize_deg(end_angle),
        **_entity_kwargs(doc),
    )


# ---------------------------------------------------------------------------
# PLINE — one Polyline entity, one transaction per segment
# ---------------------------------------------------------------------------

def _ask_width_value(ctx, prompt: str, default: Optional[float]) -> float:
    """Non-negative width/halfwidth prompt (negative → diagnostic + re-ask)."""
    while True:
        value = yield Request("distance", prompt, default=default)
        if value.kind in ("distance", "angle") and float(value.value) >= 0.0:
            return float(value.value)
        if value.kind == "keyword" and value.value == "Enter" and default is not None:
            return float(default)
        ctx.feedback("PLINE: width must be zero or positive")


def pline_steps(ctx):
    doc = ctx.document
    start = yield from ask_point(ctx, Request("point", "PLINE Specify start point:"))
    ctx.set_last_point(start)
    while True:  # restartable: Undo before the first segment re-asks the start
        pl_id = None
        verts = [start.to_tuple()]
        bulges: List[float] = [0.0]
        widths = None            # list of (start, end) once any width is set
        current_width = (0.0, 0.0)
        arc_mode = False
        finish = None
        while True:
            segments = len(verts) - 1
            options = ["Arc", "Halfwidth", "Undo", "Width"]
            if segments >= 1:
                options.insert(1, "Close")
            if arc_mode:
                prompt = "PLINE Specify endpoint of arc or [Angle/Line]:"
                options = ["Angle", "Line"]
                if segments >= 1:
                    options.append("Close")
            else:
                prompt = "PLINE Specify next point or [{}]:".format(
                    "/".join(o for o in ["Arc", "Close", "Halfwidth",
                                         "Undo", "Width"] if o in options)
                )
            value = yield Request("point", prompt, options=options)
            if value.kind == "keyword":
                keyword = value.value
                if keyword == "Enter":
                    finish = "end"
                    break
                if keyword == "Undo":
                    if segments == 0:
                        ctx.feedback("PLINE: start point discarded")
                        break  # restart at the start prompt
                    if doc.undo():  # one committed segment = one undo step
                        if segments == 1:
                            # the only segment WAS the add transaction: the
                            # polyline is gone — restart from the start point
                            pl_id = None
                            verts = [verts[0]]
                            bulges = [0.0]
                            if widths:
                                widths = [tuple(current_width)]
                        else:
                            entity = doc.get(pl_id)
                            verts = list(entity.vertices)
                            bulges = (list(entity.bulges)
                                      if entity.bulges else [0.0] * len(verts))
                            widths = list(entity.widths) if entity.widths else None
                            if widths:
                                current_width = tuple(widths[-1])
                        ctx.set_last_point(Point(*verts[-1]))
                        ctx.feedback("PLINE: last segment undone")
                    continue
                if keyword == "Close":
                    if segments >= 1:
                        with doc.transaction("PLINE Close"):
                            doc.update_entity(pl_id, closed=True)
                        finish = "closed"
                    break
                if keyword == "Arc" and not arc_mode:
                    arc_mode = True
                    continue
                if keyword == "Line" and arc_mode:
                    arc_mode = False
                    continue
                if keyword == "Angle" and arc_mode:
                    included = yield from _ask_included_angle(ctx)
                    while True:
                        end = yield from ask_point(
                            ctx, Request("point", "PLINE Specify endpoint of arc:"))
                        if geometry.dist_2d(verts[-1], end.to_tuple()) <= geometry.TOL:
                            ctx.feedback("PLINE: endpoint must differ from the last vertex")
                            continue
                        bulge = math.tan(math.radians(included) / 4.0)
                        pl_id, widths, current_width = _pline_commit(
                            doc, pl_id, verts, bulges, widths, current_width,
                            end.to_tuple(), bulge)
                        break
                    continue  # stay in arc mode (AutoCAD)
                if keyword == "Width" or keyword == "Halfwidth":
                    factor = 2.0 if keyword == "Halfwidth" else 1.0
                    label = "half-width" if factor == 2.0 else "width"
                    start_w = yield from _ask_width_value(
                        ctx,
                        f"PLINE Specify starting {label} <{current_width[0] / (2.0 if factor == 2.0 else 1.0):g}>:",
                        current_width[0] / (2.0 if factor == 2.0 else 1.0),
                    )
                    end_w = yield from _ask_width_value(
                        ctx,
                        f"PLINE Specify ending {label} <{start_w:g}>:",
                        start_w,
                    )
                    current_width = (start_w * factor, end_w * factor)
                    continue
                ctx.feedback("PLINE: point or [{}] required".format("/".join(options)))
                continue
            if value.kind != "point":
                ctx.feedback("PLINE: point or option required")
                continue
            point = value.value.to_tuple()
            if geometry.dist_2d(verts[-1], point) <= geometry.TOL:
                ctx.feedback("PLINE: vertex must differ from the previous one")
                continue
            if arc_mode:
                bulge = _continuation_bulge(verts, bulges, point)
                if abs(bulge) <= geometry.TOL:
                    # the endpoint lies on the outgoing tangent: straight
                    ctx.feedback("PLINE: arc endpoint is on the tangent — straight segment")
                    bulge = 0.0
            else:
                bulge = 0.0
            pl_id, widths, current_width = _pline_commit(
                doc, pl_id, verts, bulges, widths, current_width, point, bulge)
            ctx.set_last_point(value.value)
        if finish is not None:
            break
        # Undo discarded the start: re-ask it (AutoCAD restarts the PLINE)
        start = yield from ask_point(ctx, Request("point", "PLINE Specify start point:"))
        ctx.set_last_point(start)
    if pl_id is None:
        return CommandResult(status="ok", summary="PLINE: no segments drawn")
    closed = doc.get(pl_id).closed
    summary = f"PLINE: {len(doc.get(pl_id).vertices)} vertex polyline"
    if closed:
        summary += " [closed]"
    return CommandResult(status="ok", summary=summary, created=[pl_id])


def _continuation_bulge(verts, bulges, point) -> float:
    """Tangent-continuation bulge from the last segment to ``point``.

    The outgoing tangent of the last segment (straight: its direction;
    arc: its end tangent) defines the arc's start direction (AutoCAD PLINE
    Arc rule). With NO previous segment the +X direction is assumed
    (documented v0 approximation — AutoCAD tracks the last drawn entity,
    which a fresh steps-generator cannot see).
    """
    if len(verts) < 2:
        return geometry.bulge_from_tangent(verts[-1], point, (1.0, 0.0))
    prev_bulge = bulges[len(verts) - 2] if len(bulges) >= len(verts) - 1 else 0.0
    tangent = geometry.tangent_at_end(verts[-2], verts[-1], prev_bulge)
    return geometry.bulge_from_tangent(verts[-1], point, tangent)


def _pline_note_width(widths, verts, current_width):
    """Segment-append bookkeeping: apply ``current_width`` to the segment
    leaving the current last vertex; the NEXT segment starts at this end
    width (AutoCAD current-width behavior)."""
    if current_width == (0.0, 0.0) and widths is None:
        return widths, current_width
    if widths is None:
        widths = [(0.0, 0.0)] * len(verts)
    widths[-1] = tuple(current_width)
    widths.append((current_width[1], current_width[1]))
    return widths, widths[-1]


def _pline_commit(doc, pl_id, verts, bulges, widths, current_width, point, bulge):
    """Commit ONE segment: first segment adds the Polyline, later segments
    mutate it (one undo step each). Returns ``(pl_id, widths,
    current_width)`` — the width bookkeeping for the NEXT segment (AutoCAD
    current-width carry-over).

    Growth path note: bcdoc v2's per-field polyline length validation
    rejects length-changing ``update_entity`` calls in ANY field order (the
    intermediate state is invalid), so a later segment commits as
    remove + re-add INSIDE THE SAME transaction with the id and handle
    preserved — still one journaled undo step, the entity id stays stable,
    and undo restores the previous object bit-exactly (verified against
    undo/redo/serialize round-trips). Flagged for the TL: a batched
    vertices+bulges update in bcdoc would restore the plain mutation path.
    """
    widths, current_width = _pline_note_width(widths, verts, current_width)
    verts.append(point)
    bulges[len(verts) - 2] = bulge
    bulges.append(0.0)
    kwargs = _entity_kwargs(doc)
    if pl_id is not None:
        old = doc.get(pl_id)
        kwargs = {
            "layer": old.layer, "color": old.color, "linetype": old.linetype,
            "lineweight": old.lineweight, "space": old.space,
        }
    with doc.transaction("PLINE segment"):
        if pl_id is None:
            pl_id = doc.add_entity(
                Polyline(list(verts), bulges=list(bulges),
                         widths=(list(widths) if widths is not None else None),
                         **kwargs)
            ).id
        else:
            old = doc.remove(pl_id)
            replacement = Polyline(
                list(verts), bulges=list(bulges),
                widths=(list(widths) if widths is not None else None),
                closed=old.closed, **kwargs)
            replacement.id = old.id
            doc.add_entity(replacement, handle=old.handle)
    return pl_id, widths, current_width


def _ask_included_angle(ctx) -> float:
    """Included angle for the PLINE Arc [Angle] path (CCW positive; a
    zero/full turn is rejected). A point gives the angle from the last
    vertex to the pick."""
    while True:
        value = yield Request("angle", "PLINE Specify included angle of arc:")
        angle = None
        if value.kind == "angle":
            angle = float(value.value)
        elif value.kind == "point":
            reference = ctx.last_point
            if reference is None:
                ctx.feedback("PLINE: angle or point required")
                continue
            angle = geometry.angle_of(
                (value.value.x - reference.x, value.value.y - reference.y))
        if angle is None:
            ctx.feedback("PLINE: included angle required")
            continue
        if abs(angle) <= geometry.TOL or abs(abs(angle) - 360.0) <= geometry.TOL:
            ctx.feedback("PLINE: included angle must differ from 0°/360°")
            continue
        return angle


# ---------------------------------------------------------------------------
# RECTANG — two corners → closed 4-vertex polyline
# ---------------------------------------------------------------------------

def rectang_steps(ctx):
    doc = ctx.document
    first = yield from ask_point(
        ctx, Request("point", "RECTANG Specify first corner point:"))
    ctx.set_last_point(first)
    while True:
        second = yield from ask_point(
            ctx, Request("point", "RECTANG Specify other corner point:"))
        p1, p2 = first.to_tuple(), second.to_tuple()
        if abs(p1[0] - p2[0]) <= geometry.TOL or abs(p1[1] - p2[1]) <= geometry.TOL:
            # zero-width/height rectangles are degenerate in AutoCAD too
            if geometry.dist_2d(p1, p2) <= geometry.TOL:
                ctx.feedback("RECTANG: corners must differ")
                continue
        break
    z = p1[2]
    vertices = [
        (p1[0], p1[1], z), (p2[0], p1[1], z),
        (p2[0], p2[1], z), (p1[0], p2[1], z),
    ]
    ctx.set_last_point(second)
    entity = add_entity(
        ctx, Polyline(vertices, closed=True, **_entity_kwargs(doc)), "RECTANG")
    return CommandResult(
        status="ok",
        summary=(
            f"RECTANG: {abs(p2[0] - p1[0]):g} × {abs(p2[1] - p1[1]):g} rectangle"
        ),
        created=[entity.id],
    )


# ---------------------------------------------------------------------------
# POLYGON — inscribed/circumscribed about a circle, or by edge
# ---------------------------------------------------------------------------

def _polygon_sides(ctx) -> int:
    while True:
        value = yield Request(
            "distance", "POLYGON Enter number of sides <4>:", default=4)
        if value.kind in ("distance", "angle"):
            number = float(value.value)
            if number == int(number) and number > 2.0:
                return int(number)
        if value.kind == "keyword" and value.value == "Enter":
            return 4
        ctx.feedback("POLYGON: number of sides must be an integer > 2")


def polygon_steps(ctx):
    doc = ctx.document
    sides = yield from _polygon_sides(ctx)
    value = yield Request(
        "point", "POLYGON Specify center of polygon or [Edge]:",
        options=["Edge"],
    )
    if value.kind == "keyword" and value.value == "Edge":
        vertices = yield from _polygon_by_edge(ctx, sides)
        method = "edge"
    else:
        try:
            center = require_point(value)
        except ValueError as exc:
            ctx.feedback(str(exc))
            center = yield from ask_point(
                ctx, Request("point", "POLYGON Specify center of polygon:"))
        ctx.set_last_point(center)
        method_value = yield Request(
            "string",
            "POLYGON Enter polygon type [Inscribed/Circumscribed] <Inscribed>:",
            options=["Inscribed", "Circumscribed"],
            default="Inscribed",
        )
        inscribed = True
        if method_value.kind == "keyword":
            inscribed = method_value.value != "Circumscribed"
        elif method_value.kind == "string":
            inscribed = "circum" not in str(method_value.value).lower()
        vertices = yield from _polygon_by_center(
            ctx, sides, center, inscribed)
        method = "inscribed" if inscribed else "circumscribed"
    entity = add_entity(
        ctx, Polyline(vertices, closed=True, **_entity_kwargs(doc)), "POLYGON")
    return CommandResult(
        status="ok",
        summary=f"POLYGON: {sides} sides by {method}",
        created=[entity.id],
    )


def _polygon_by_center(ctx, sides: int, center: Point, inscribed: bool):
    """Vertices on the circumcircle, CCW. A typed radius puts the first
    vertex (inscribed) / first edge midpoint (circumscribed) at angle 0;
    a POINT pick sets that angle from the center."""
    while True:
        value = yield Request(
            "distance", "POLYGON Specify radius of circle:", default=None)
        phase = 0.0
        if value.kind == "point":
            point = value.value
            phase = geometry.angle_of((point.x - center.x, point.y - center.y))
            radius = geometry.dist_2d(
                (center.x, center.y), (point.x, point.y))
        elif value.kind in ("distance", "angle"):
            radius = float(value.value)
        else:
            ctx.feedback("POLYGON: radius (or a point on the circle) required")
            continue
        if radius <= geometry.TOL:
            ctx.feedback("POLYGON: radius must be positive")
            continue
        break
    step = 360.0 / sides
    if inscribed:
        circumradius = radius
        first_angle = phase
    else:
        # circumscribed: the picked circle is the INCIRCLE (edge midpoints)
        circumradius = radius / math.cos(math.radians(step / 2.0))
        first_angle = phase + step / 2.0
    cx, cy, cz = center.to_tuple()
    vertices = []
    for k in range(sides):
        angle = math.radians(first_angle + k * step)
        vertices.append((
            cx + circumradius * math.cos(angle),
            cy + circumradius * math.sin(angle),
            cz,
        ))
    ctx.set_last_point(Point(*vertices[0]))
    return vertices


def _polygon_by_edge(ctx, sides: int):
    first = yield from ask_point(
        ctx, Request("point", "POLYGON Specify first endpoint of edge:"))
    ctx.set_last_point(first)
    while True:
        second = yield from ask_point(
            ctx, Request("point", "POLYGON Specify second endpoint of edge:"))
        p1, p2 = first.to_tuple(), second.to_tuple()
        edge = geometry.dist_2d(p1, p2)
        if edge > geometry.TOL:
            break
        ctx.feedback("POLYGON: edge endpoints must differ")
    step_deg = 360.0 / sides
    ux = (p2[0] - p1[0]) / edge
    uy = (p2[1] - p1[1]) / edge
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0, p1[2])
    # CCW from p1 to p2: the interior (and the center) lies on the LEFT
    apothem = (edge / 2.0) / math.tan(math.radians(step_deg / 2.0))
    circumradius = (edge / 2.0) / math.sin(math.radians(step_deg / 2.0))
    center = (mid[0] - uy * apothem, mid[1] + ux * apothem, p1[2])
    first_angle = geometry.angle_of((p1[0] - center[0], p1[1] - center[1]))
    vertices = []
    for k in range(sides):
        angle = math.radians(first_angle + k * step_deg)
        vertices.append((
            center[0] + circumradius * math.cos(angle),
            center[1] + circumradius * math.sin(angle),
            p1[2],
        ))
    ctx.set_last_point(second)
    return vertices


# ---------------------------------------------------------------------------
# POINT / XLINE / RAY
# ---------------------------------------------------------------------------

def point_steps(ctx):
    doc = ctx.document
    position = yield from ask_point(
        ctx, Request("point", "POINT Specify a point:"))
    ctx.set_last_point(position)
    entity = add_entity(
        ctx, PointEntity(position.to_tuple(), **_entity_kwargs(doc)), "POINT")
    return CommandResult(
        status="ok",
        summary=f"POINT: at ({position.x:g}, {position.y:g}, {position.z:g})",
        created=[entity.id],
    )


def _ask_through_point(ctx, name: str, base: Point) -> Point:
    while True:
        through = yield from ask_point(
            ctx, Request("point", f"{name} Specify through point:"))
        if geometry.dist_2d(
                (base.x, base.y), (through.x, through.y)) > geometry.TOL:
            return through
        ctx.feedback(f"{name}: through point must differ from the base point")


def xline_steps(ctx):
    doc = ctx.document
    base = yield from ask_point(ctx, Request("point", "XLINE Specify base point:"))
    ctx.set_last_point(base)
    through = yield from _ask_through_point(ctx, "XLINE", base)
    ctx.set_last_point(through)
    entity = add_entity(
        ctx, Xline(base.to_tuple(), through.to_tuple(), **_entity_kwargs(doc)),
        "XLINE")
    return CommandResult(
        status="ok",
        summary=(
            f"XLINE: through ({base.x:g}, {base.y:g}) and "
            f"({through.x:g}, {through.y:g})"
        ),
        created=[entity.id],
    )


def ray_steps(ctx):
    doc = ctx.document
    base = yield from ask_point(ctx, Request("point", "RAY Specify start point:"))
    ctx.set_last_point(base)
    through = yield from _ask_through_point(ctx, "RAY", base)
    ctx.set_last_point(through)
    entity = add_entity(
        ctx, Ray(base.to_tuple(), through.to_tuple(), **_entity_kwargs(doc)),
        "RAY")
    return CommandResult(
        status="ok",
        summary=(
            f"RAY: from ({base.x:g}, {base.y:g}) through "
            f"({through.x:g}, {through.y:g})"
        ),
        created=[entity.id],
    )


# ---------------------------------------------------------------------------
# ELLIPSE — axis endpoints + distance/Rotation, or [Center]
# ---------------------------------------------------------------------------
#
# Convention (binding for interchange): ``major_axis`` is the CENTER-
# RELATIVE semi-major vector (DXF form); ``ratio`` = minor/major in (0, 1].
# When the "other axis" distance exceeds the first axis, the axes swap
# (AutoCAD behavior — the first axis becomes the minor axis).

def _ask_positive_distance_or_point(ctx, prompt: str, reference):
    """Positive distance; a POINT pick gives the distance from
    ``reference`` (and the caller can read the angle from ctx.last_point)."""
    while True:
        value = yield Request("distance", prompt)
        if value.kind in ("distance", "angle") and float(value.value) > 0.0:
            return float(value.value), None
        if value.kind == "point":
            distance = geometry.dist_2d(
                (reference[0], reference[1]),
                (value.value.x, value.value.y))
            if distance > 0.0:
                return distance, value.value
            ctx.feedback("ELLIPSE: distance must be positive")
            continue
        ctx.feedback("ELLIPSE: positive distance required")


def _ellipse_axis_kwargs(ctx, center, semi_a_vec, other_distance) -> dict:
    """Normalize to semi-major + ratio, swapping axes when the second axis
    is the longer one (AutoCAD)."""
    semi_len = math.hypot(semi_a_vec[0], semi_a_vec[1])
    if other_distance <= semi_len:
        major = semi_a_vec
        ratio = other_distance / semi_len
    else:
        # the other axis is major: rotate the first axis by +90° and scale
        major = (-semi_a_vec[1] * (other_distance / semi_len),
                 semi_a_vec[0] * (other_distance / semi_len),
                 semi_a_vec[2])
        ratio = semi_len / other_distance
    return {"center": center, "major_axis": major, "ratio": ratio,
            "start_angle": 0.0, "end_angle": 360.0}


def ellipse_steps(ctx):
    doc = ctx.document
    value = yield Request(
        "point", "ELLIPSE Specify first endpoint of axis or [Center]:",
        options=["Center"],
    )
    if value.kind == "keyword" and value.value == "Center":
        center = yield from ask_point(
            ctx, Request("point", "ELLIPSE Specify center of ellipse:"))
        ctx.set_last_point(center)
        while True:
            axis_end = yield from ask_point(
                ctx, Request("point", "ELLIPSE Specify endpoint of axis:"))
            semi_a_vec = (
                axis_end.x - center.x, axis_end.y - center.y, axis_end.z - center.z)
            if math.hypot(semi_a_vec[0], semi_a_vec[1]) > geometry.TOL:
                break
            ctx.feedback("ELLIPSE: axis endpoint must differ from the center")
        ctx.set_last_point(axis_end)
        distance, _pick = yield from _ask_positive_distance_or_point(
            ctx, "ELLIPSE Specify length of other axis:",
            (center.x, center.y, center.z))
        kwargs = _ellipse_axis_kwargs(
            doc, center.to_tuple(), semi_a_vec, distance)
        method = "center"
    else:
        try:
            first = require_point(value)
        except ValueError as exc:
            ctx.feedback(str(exc))
            first = yield from ask_point(
                ctx, Request("point", "ELLIPSE Specify first endpoint of axis:"))
        ctx.set_last_point(first)
        while True:
            second = yield from ask_point(
                ctx, Request("point", "ELLIPSE Specify other endpoint of axis:"))
            if geometry.dist_2d(
                    (first.x, first.y), (second.x, second.y)) > geometry.TOL:
                break
            ctx.feedback("ELLIPSE: axis endpoints must differ")
        ctx.set_last_point(second)
        p1, p2 = first.to_tuple(), second.to_tuple()
        center = (
            (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0, (p1[2] + p2[2]) / 2.0)
        semi_a_vec = (
            (p2[0] - p1[0]) / 2.0, (p2[1] - p1[1]) / 2.0,
            (p2[2] - p1[2]) / 2.0)
        while True:
            value = yield Request(
                "distance", "ELLIPSE Specify distance to other axis or [Rotation]:",
                options=["Rotation"],
            )
            if value.kind == "keyword" and value.value == "Rotation":
                # projected circle: other semi-axis = |cos(rotation)| × major
                while True:
                    angle_value = yield Request(
                        "angle",
                        "ELLIPSE Specify rotation around major axis (deg):")
                    if angle_value.kind == "angle":
                        rotation = float(angle_value.value)
                    elif angle_value.kind == "point":
                        rotation = geometry.angle_of((
                            angle_value.value.x - center[0],
                            angle_value.value.y - center[1]))
                    else:
                        ctx.feedback("ELLIPSE: rotation angle required")
                        continue
                    projected = abs(math.cos(math.radians(rotation)))
                    if projected <= 1e-9:
                        ctx.feedback("ELLIPSE: 90° rotation collapses the ellipse")
                        continue
                    break
                distance = math.hypot(semi_a_vec[0], semi_a_vec[1]) * projected
                break
            if value.kind == "point":
                distance = geometry.dist_2d(center, value.value.to_tuple())
                if distance <= geometry.TOL:
                    ctx.feedback("ELLIPSE: distance must be positive")
                    continue
                break
            if value.kind in ("distance", "angle") and float(value.value) > 0.0:
                distance = float(value.value)
                break
            ctx.feedback("ELLIPSE: positive distance or [Rotation]")
        kwargs = _ellipse_axis_kwargs(doc, center, semi_a_vec, distance)
        method = "axis endpoints"
    entity = add_entity(ctx, Ellipse(**kwargs, **_entity_kwargs(doc)), "ELLIPSE")
    return CommandResult(
        status="ok",
        summary=(
            f"ELLIPSE: by {method}, center ({kwargs['center'][0]:g}, "
            f"{kwargs['center'][1]:g}), ratio {kwargs['ratio']:g}"
        ),
        created=[entity.id],
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
    help="Full circle by center and radius or diameter, or 2P/3P",
)
ARC = CommandSpec(
    name="ARC", aliases=["A"], steps=arc_steps,
    help="Arc by three points or start-center-end",
)
PLINE = CommandSpec(
    name="PLINE", aliases=["PL"], steps=pline_steps,
    help="Polyline with line/arc (tangent continuation) segments and widths",
)
RECTANG = CommandSpec(
    name="RECTANG", aliases=["REC"], steps=rectang_steps,
    help="Rectangle from two corners (closed polyline)",
)
POLYGON = CommandSpec(
    name="POLYGON", aliases=["POL"], steps=polygon_steps,
    help="Regular polygon inscribed/circumscribed or by edge",
)
POINT = CommandSpec(
    name="POINT", aliases=["PO"], steps=point_steps,
    help="Point entity at a picked position",
)
XLINE = CommandSpec(
    name="XLINE", aliases=["XL"], steps=xline_steps,
    help="Infinite construction line through two points",
)
RAY = CommandSpec(
    name="RAY", aliases=["RA"], steps=ray_steps,
    help="Semi-infinite ray from a base point through another",
)
ELLIPSE = CommandSpec(
    name="ELLIPSE", aliases=["EL"], steps=ellipse_steps,
    help="Full ellipse by axis endpoints (+distance/Rotation) or center",
)

COMMANDS = (
    LINE, CIRCLE, ARC, PLINE, RECTANG, POLYGON, POINT, XLINE, RAY, ELLIPSE,
)
