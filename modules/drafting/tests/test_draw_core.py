"""M2 drafting-core draw-command tests (TP-CAT-01 P0 subset, contract §0).

PLINE (+arc segments via tangent continuation, +per-vertex widths),
RECTANG, POLYGON (inscribed/circumscribed/edge), POINT, XLINE, RAY,
ELLIPSE (axis endpoints / Center / Rotation) and CIRCLE 2P/3P — all driven
by ``Registry.run_command`` with a ScriptedProvider (the exact interface the
modal viewport operator and the acceptance battery use), asserting EXACT
geometry on the REAL bcdoc.

Typed "2P"/"3P" arrive as keyword InputValues (the M1 text parser treats
digit-leading tokens as numeric); every other input is plain text parsed by
bccmd exactly as a shell user would type it.
"""

import math

import pytest

from bccmd import Cancelled, Point, keyword_input, point_input

from bcdraft.geometry import (
    arc_from_bulge,
    polyline_segments,
    tangent_at_end,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _kind(document, kind):
    return [e for e in document.entities() if e.kind == kind]


# ---------------------------------------------------------------------------
# PLINE
# ---------------------------------------------------------------------------

def test_pline_straight_segments_one_entity_one_tx_each(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "10,0", "10,10", ""])
    assert result.status == "ok"
    assert result.created and len(result.created) == 1
    pl = document.get(result.created[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0))
    assert not pl.closed
    assert list(pl.bulges) == [0.0, 0.0, 0.0]
    # one committed transaction per segment -> one undo step per segment
    assert document.undo_depth() == 2
    # the second vertex is the relative-input anchor
    assert ctx.last_point == Point(10.0, 10.0)


def test_pline_arc_option_tangent_continuation_bulge(run, make_context, document):
    """Arc after a straight segment: the arc's start tangent continues the
    segment direction, so the bulge is exactly 1.0 (semicircle) and the
    arc_from_bulge representation reproduces both endpoints."""
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "10,0", "Arc", "10,10", ""])
    assert result.status == "ok"
    pl = document.get(result.created[0])
    assert pl.vertices == (
        (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0),
    )
    # tan(180°/4) == 1.0 — the semicircle bulge (AutoCAD convention)
    assert pl.bulges[1] == pytest.approx(1.0)
    assert pl.bulges[0] == 0.0 and pl.bulges[2] == 0.0
    # the bulge arc: center at the chord midpoint, radius = chord/2
    center, radius, a_start, a_end = arc_from_bulge(
        pl.vertices[1], pl.vertices[2], pl.bulges[1])
    assert center == pytest.approx((10.0, 5.0, 0.0))
    assert radius == pytest.approx(5.0)
    # tangent continuity: the arc's start tangent is the segment direction
    segment_dir = tangent_at_end(
        pl.vertices[0], pl.vertices[1], pl.bulges[0])
    assert segment_dir == pytest.approx((1.0, 0.0))
    # walking the CCW representation from a_start reaches the endpoint
    assert a_start == pytest.approx(270.0)
    assert a_end == pytest.approx(90.0)


def test_pline_arc_option_first_segment_uses_plus_x_tangent(
    run, make_context, document
):
    # documented v0 approximation: no previous segment -> +X start tangent
    result = run(make_context(), "pline", ["0,0", "Arc", "0,10", ""])
    pl = document.get(result.created[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (0.0, 10.0, 0.0))
    assert pl.bulges[0] == pytest.approx(1.0)
    center, radius, _s, _e = arc_from_bulge(
        pl.vertices[0], pl.vertices[1], pl.bulges[0])
    # the arc bulges toward +X (the assumed tangent direction)
    assert center == pytest.approx((0.0, 5.0, 0.0))
    assert radius == pytest.approx(5.0)


def test_pline_arc_angle_option_sets_included_angle_bulge(
    run, make_context, document
):
    ctx = make_context()
    result = run(
        ctx, "pline", ["0,0", "Arc", "Angle", "0", "45", "10,0", "Line", "10,-5", ""]
    )
    assert result.status == "ok"
    pl = document.get(result.created[0])
    # bulge = tan(included/4); 0 and 360 are rejected with feedback
    assert any("must differ from 0" in m for m in ctx.feedback_messages)
    assert pl.bulges[0] == pytest.approx(math.tan(math.radians(45.0) / 4.0))
    assert pl.vertices[2] == (10.0, -5.0, 0.0)
    # [Line] returns to straight segments
    assert pl.bulges[1] == 0.0


def test_pline_width_option_per_vertex_widths(run, make_context, document):
    result = run(
        make_context(), "pline", ["0,0", "Width", "2", "1", "10,0", "20,0", ""]
    )
    pl = document.get(result.created[0])
    # widths[i] = [start, end] of the segment LEAVING vertex i: the typed
    # width applies to the next segment drawn; the following segments start
    # at the previous end width (AutoCAD current-width carry-over)
    assert pl.widths == ((2.0, 1.0), (1.0, 1.0), (1.0, 1.0))


def test_pline_halfwidth_option_doubles_into_full_widths(
    run, make_context, document
):
    result = run(
        make_context(), "pline", ["0,0", "Halfwidth", "1", "0.5", "10,0", ""]
    )
    pl = document.get(result.created[0])
    assert pl.widths == ((2.0, 1.0), (1.0, 1.0))


def test_pline_negative_width_reprompts(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "Width", "-1", "3", "3", "10,0", ""])
    assert result.status == "ok"
    assert any("zero or positive" in m for m in ctx.feedback_messages)
    pl = document.get(result.created[0])
    assert pl.widths[0] == (3.0, 3.0)


def test_pline_width_enter_accepts_the_shown_default(run, make_context, document):
    # "" at the width prompts accepts the shown default (0 -> 0); zero
    # widths are not materialized (the entity keeps its no-widths form)
    result = run(make_context(), "pline", ["0,0", "Width", "", "", "10,0", ""])
    pl = document.get(result.created[0])
    assert pl.widths == ()


def test_pline_close_option_closes_the_loop(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "10,0", "10,10", "C"])
    assert result.status == "ok"
    assert "[closed]" in result.summary
    pl = document.get(result.created[0])
    assert pl.closed
    # the closing segment runs from the last vertex back to the first
    segments = polyline_segments(pl)
    assert segments[-1][0] == (10.0, 10.0, 0.0)
    assert segments[-1][1] == (0.0, 0.0, 0.0)
    # 2 segments + 1 close flag = 3 undo steps
    assert document.undo_depth() == 3


def test_pline_undo_pops_the_last_segment(run, make_context, document):
    ctx = make_context()
    result = run(
        ctx, "pline", ["0,0", "10,0", "10,10", "U", "10,5", ""]
    )
    assert result.status == "ok"
    assert any("last segment undone" in m for m in ctx.feedback_messages)
    pl = document.get(result.created[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 5.0, 0.0))
    # the undo option rolled back its transaction: net depth is 2 again
    assert document.undo_depth() == 2


def test_pline_undo_at_only_segment_keeps_start_point(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "10,0", "U", "5,5", "10,5", ""])
    assert result.status == "ok"
    assert any("last segment undone" in m for m in ctx.feedback_messages)
    pl = document.get(result.created[0])
    # AutoCAD PLINE Undo removes the last vertex; the start point STAYS and
    # the next input draws a new first segment from it
    assert pl.vertices == ((0.0, 0.0, 0.0), (5.0, 5.0, 0.0), (10.0, 5.0, 0.0))
    # add tx + its undo + two new segments = 2 net undo steps
    assert document.undo_depth() == 2


def test_pline_undo_before_first_segment_discards_start(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "U", "3,0", "9,0", ""])
    assert result.status == "ok"
    assert any("start point discarded" in m for m in ctx.feedback_messages)
    pl = document.get(result.created[0])
    assert pl.vertices == ((3.0, 0.0, 0.0), (9.0, 0.0, 0.0))


def test_pline_duplicate_vertex_rejected_with_feedback(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "0,0", "10,0", ""])
    assert result.status == "ok"
    assert any("must differ from the previous" in m for m in ctx.feedback_messages)
    pl = document.get(result.created[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))


def test_pline_cancel_keeps_committed_segments(run, make_context, document):
    # AutoCAD-familiar: Esc keeps what was committed (one tx per segment)
    ctx = make_context()
    result = run(ctx, "pline", ["0,0", "5,0", "10,0", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {"polyline": 1}
    pl = _kind(document, "polyline")[0]
    assert pl.vertices == ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert document.doc_version == 2


# ---------------------------------------------------------------------------
# RECTANG
# ---------------------------------------------------------------------------

def test_rectang_two_corners_closed_four_vertices(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "rectang", ["0,0", "10,5"])
    assert result.status == "ok"
    assert "10 × 5" in result.summary
    pl = document.get(result.created[0])
    assert pl.vertices == (
        (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 5.0, 0.0), (0.0, 5.0, 0.0),
    )
    assert pl.closed
    assert document.undo_depth() == 1


def test_rectang_reversed_corners_normalized(run, make_context, document):
    # either corner order produces the same rectangle
    result = run(make_context(), "rectang", ["10,5", "0,0"])
    pl = document.get(result.created[0])
    assert pl.vertices == (
        (10.0, 5.0, 0.0), (0.0, 5.0, 0.0), (0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
    )


def test_rectang_identical_corners_feedback_and_reask(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "rectang", ["0,0", "0,0", "8,3"])
    assert result.status == "ok"
    assert any("corners must differ" in m for m in ctx.feedback_messages)
    pl = document.get(result.created[0])
    assert pl.vertices == (
        (0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 3.0, 0.0), (0.0, 3.0, 0.0),
    )


# ---------------------------------------------------------------------------
# POLYGON
# ---------------------------------------------------------------------------

def test_polygon_inscribed_vertices_on_the_circle(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "polygon", ["5", "0,0", "", "5"])  # Enter = Inscribed
    assert result.status == "ok"
    assert result.summary == "POLYGON: 5 sides by inscribed"
    pl = document.get(result.created[0])
    assert pl.closed and len(pl.vertices) == 5
    for vertex in pl.vertices:
        # every vertex sits exactly on the circumcircle (radius 5)
        assert math.hypot(vertex[0], vertex[1]) == pytest.approx(5.0)
    # typed radius puts the first vertex at angle 0
    assert pl.vertices[0] == pytest.approx((5.0, 0.0, 0.0))
    # CCW order: the second vertex is 72° up the circle
    second = pl.vertices[1]
    angle = math.degrees(math.atan2(second[1], second[0]))
    assert angle == pytest.approx(72.0)


def test_polygon_circumscribed_incircle_radius(run, make_context, document):
    result = run(make_context(), "polygon", ["4", "0,0", "C", "5"])
    pl = document.get(result.created[0])
    assert result.summary == "POLYGON: 4 sides by circumscribed"
    assert len(pl.vertices) == 4
    # the picked circle is the INCIRCLE: every edge midpoint is at radius 5
    segments = polyline_segments(pl)
    for start, end, _bulge in segments:
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        assert math.hypot(mid[0], mid[1]) == pytest.approx(5.0)
    # vertices sit on the circumcircle: R = r / cos(180/n) = 5/cos(45)
    circum = 5.0 / math.cos(math.radians(45.0))
    for vertex in pl.vertices:
        assert math.hypot(vertex[0], vertex[1]) == pytest.approx(circum)


def test_polygon_point_pick_sets_the_phase(run, make_context, document):
    result = run(make_context(), "polygon", ["3", "10,0", "", "20,10"])
    pl = document.get(result.created[0])
    # point pick: radius = |pick - center|, first vertex towards the pick
    radius = math.hypot(10.0, 10.0)
    assert pl.vertices[0] == pytest.approx((10.0 + radius, 0.0, 0.0))
    for vertex in pl.vertices:
        assert math.hypot(vertex[0] - 10.0, vertex[1]) == pytest.approx(radius)


def test_polygon_by_edge(run, make_context, document):
    result = run(make_context(), "polygon", ["6", "E", "0,0", "10,0"])
    assert result.status == "ok"
    assert result.summary == "POLYGON: 6 sides by edge"
    pl = document.get(result.created[0])
    assert pl.closed and len(pl.vertices) == 6
    # the edge endpoints are vertices of the polygon, in order
    assert pl.vertices[0] == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert pl.vertices[1] == pytest.approx((10.0, 0.0, 0.0), abs=1e-9)
    # interior on the LEFT of p1->p2: the center is above the edge at the
    # apothem distance (edge/2)/tan(half the central angle)
    center = (
        sum(v[0] for v in pl.vertices) / 6.0,
        sum(v[1] for v in pl.vertices) / 6.0,
    )
    assert center[1] == pytest.approx(
        (10.0 / 2.0) / math.tan(math.radians(30.0)), rel=1e-9
    )
    # every vertex is at the circumradius (edge/2)/sin(30)
    circum = 5.0 / math.sin(math.radians(30.0))
    for vertex in pl.vertices:
        assert math.hypot(vertex[0] - center[0], vertex[1] - center[1]) == (
            pytest.approx(circum, rel=1e-9)
        )


def test_polygon_sides_below_three_rejected_then_accepted(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "polygon", ["2", "3", "0,0", "", "4"])
    assert result.status == "ok"
    assert any(
        "sides must be an integer > 2" in m for m in ctx.feedback_messages
    )
    pl = document.get(result.created[0])
    assert len(pl.vertices) == 3
    assert result.summary == "POLYGON: 3 sides by inscribed"


def test_polygon_noninteger_sides_rejected(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "polygon", ["abc", "2.5", "4", "0,0", "", "5"])
    assert result.status == "ok"
    # a non-numeric token sinks a parse diagnostic and re-asks; a
    # fractional number reaches the command and gets its own feedback
    assert any("Invalid input" in m for m in ctx.feedback_messages)
    assert any("integer > 2" in m for m in ctx.feedback_messages)
    assert len(document.get(result.created[0]).vertices) == 4


def test_polygon_cancelled_no_entity_version_unchanged(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "polygon", ["5", "0,0", Cancelled()])
    assert result.status == "cancelled"
    assert document.doc_version == 0
    assert document.count_by_kind() == {}


# ---------------------------------------------------------------------------
# POINT / XLINE / RAY
# ---------------------------------------------------------------------------

def test_point_exact_position(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "point", ["7,-3"])
    assert result.status == "ok"
    point = document.get(result.created[0])
    assert point.position == (7.0, -3.0, 0.0)
    assert point.layer == "0"
    assert point.space == "MODEL"
    assert ctx.last_point == Point(7.0, -3.0)


def test_xline_stores_base_and_through(run, make_context, document):
    result = run(make_context(), "xline", ["1,1", "5,3"])
    xline = document.get(result.created[0])
    assert xline.p1 == (1.0, 1.0, 0.0)
    assert xline.p2 == (5.0, 3.0, 0.0)


def test_xline_through_point_must_differ(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "xline", ["1,1", "1,1", "5,1"])
    assert result.status == "ok"
    assert any("must differ from the base" in m for m in ctx.feedback_messages)
    xline = document.get(result.created[0])
    assert xline.p2 == (5.0, 1.0, 0.0)


def test_ray_stores_base_and_through(run, make_context, document):
    result = run(make_context(), "ray", ["2,2", "6,5"])
    ray = document.get(result.created[0])
    assert ray.p1 == (2.0, 2.0, 0.0)
    assert ray.p2 == (6.0, 5.0, 0.0)


def test_ray_cancelled_mid_command(run, make_context, document):
    result = run(make_context(), "ray", ["2,2", Cancelled()])
    assert result.status == "cancelled"
    assert document.doc_version == 0
    assert document.count_by_kind() == {}


# ---------------------------------------------------------------------------
# ELLIPSE
# ---------------------------------------------------------------------------

def test_ellipse_axis_endpoints_and_distance(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "ellipse", ["0,0", "10,0", "3"])
    assert result.status == "ok"
    e = document.get(result.created[0])
    # center-relative semi-major vector + ratio (DXF convention)
    assert e.center == (5.0, 0.0, 0.0)
    assert e.major_axis == (5.0, 0.0, 0.0)
    assert e.ratio == pytest.approx(3.0 / 5.0)
    # full ellipse by default
    assert e.start_angle == 0.0 and e.end_angle == 360.0
    assert "axis endpoints" in result.summary


def test_ellipse_second_axis_longer_swaps_the_major_axis(
    run, make_context, document
):
    # AutoCAD: when the "other axis" exceeds the first axis, the first axis
    # becomes the MINOR axis and the stored major vector follows the swap
    result = run(make_context(), "ellipse", ["0,0", "10,0", "20"])
    e = document.get(result.created[0])
    assert e.center == (5.0, 0.0, 0.0)
    assert e.major_axis == pytest.approx((0.0, 20.0, 0.0))
    assert e.ratio == pytest.approx(0.25)


def test_ellipse_rotation_option_projects_a_circle(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "ellipse", ["0,0", "10,0", "R", "60", ""])
    assert result.status == "ok"
    e = document.get(result.created[0])
    assert e.major_axis == pytest.approx((5.0, 0.0, 0.0))
    # the other semi-axis = major * |cos(rotation)|
    assert e.ratio == pytest.approx(abs(math.cos(math.radians(60.0))))


def test_ellipse_rotation_ninety_collapses_feedback_reasks(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "ellipse", ["0,0", "10,0", "R", "90", "45", ""])
    assert result.status == "ok"
    assert any("collapses the ellipse" in m for m in ctx.feedback_messages)
    e = document.get(result.created[0])
    assert e.ratio == pytest.approx(abs(math.cos(math.radians(45.0))))


def test_ellipse_center_option(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "ellipse", ["C", "5,5", "10,5", "2", ""])
    assert result.status == "ok"
    assert "by center" in result.summary
    e = document.get(result.created[0])
    assert e.center == (5.0, 5.0, 0.0)
    assert e.major_axis == (5.0, 0.0, 0.0)
    assert e.ratio == pytest.approx(0.4)


def test_ellipse_center_option_with_longer_other_axis(
    run, make_context, document
):
    result = run(make_context(), "ellipse", ["C", "0,0", "4,0", "8"])
    e = document.get(result.created[0])
    assert e.major_axis == pytest.approx((0.0, 8.0, 0.0))
    assert e.ratio == pytest.approx(0.5)


def test_ellipse_axis_endpoints_must_differ(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "ellipse", ["0,0", "0,0", "10,0", "3"])
    assert result.status == "ok"
    assert any("must differ" in m for m in ctx.feedback_messages)
    e = document.get(result.created[0])
    assert e.center == (5.0, 0.0, 0.0)
    assert e.ratio == pytest.approx(0.6)


def test_ellipse_invalid_input_recovers(run, make_context, document):
    ctx = make_context()
    # a bad token at the [Center]-option point prompt sinks a diagnostic
    # and re-asks; the command then completes normally
    result = run(ctx, "ellipse", ["oops", "0,0", "10,0", "3"])
    assert result.status == "ok"
    assert any("keyword" in m for m in ctx.feedback_messages)
    e = document.get(result.created[0])
    assert e.ratio == pytest.approx(0.6)


def test_ellipse_cancelled_mid_command(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "ellipse", ["0,0", "10,0", Cancelled()])
    assert result.status == "cancelled"
    assert document.doc_version == 0
    assert document.count_by_kind() == {}


# ---------------------------------------------------------------------------
# CIRCLE 2P / 3P
# ---------------------------------------------------------------------------

def test_circle_two_point_diameter(run, make_context, document):
    ctx = make_context()
    result = run(
        ctx, "circle", [keyword_input("2P"), "0,0", "10,0"]
    )
    assert result.status == "ok"
    assert "2P" in result.summary
    circle = document.get(result.created[0])
    assert circle.center == (5.0, 0.0, 0.0)
    assert circle.radius == pytest.approx(5.0)
    assert document.undo_depth() == 1


def test_circle_two_point_duplicate_endpoints_rejected(
    run, make_context, document
):
    ctx = make_context()
    result = run(
        ctx, "circle", [keyword_input("2P"), "5,5", "5,5", "5,15"]
    )
    assert result.status == "ok"
    assert any("endpoints must differ" in m for m in ctx.feedback_messages)
    circle = document.get(result.created[0])
    assert circle.center == (5.0, 10.0, 0.0)
    assert circle.radius == pytest.approx(5.0)


def test_circle_three_point(run, make_context, document):
    ctx = make_context()
    result = run(
        ctx, "circle", [keyword_input("3P"), "0,0", "10,0", "5,5"]
    )
    assert result.status == "ok"
    assert "3P" in result.summary
    circle = document.get(result.created[0])
    assert circle.center == pytest.approx((5.0, 0.0, 0.0))
    assert circle.radius == pytest.approx(5.0)
    for pt in ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0)):
        assert math.hypot(pt[0] - circle.center[0], pt[1] - circle.center[1]) == (
            pytest.approx(circle.radius)
        )


def test_circle_three_point_collinear_rejected_then_accepted(
    run, make_context, document
):
    ctx = make_context()
    result = run(
        ctx, "circle",
        [keyword_input("3P"), "0,0", "10,0", "20,0", "5,5"],
    )
    assert result.status == "ok"
    assert any("collinear" in m for m in ctx.feedback_messages)
    circle = document.get(result.created[0])
    assert circle.center == pytest.approx((5.0, 0.0, 0.0))
    assert circle.radius == pytest.approx(5.0)


def test_circle_three_point_duplicate_second_rejected(
    run, make_context, document
):
    ctx = make_context()
    result = run(
        ctx, "circle",
        [keyword_input("3P"), "0,0", "0,0", "10,0", "5,5"],
    )
    assert result.status == "ok"
    assert any("points must differ" in m for m in ctx.feedback_messages)
    circle = document.get(result.created[0])
    assert circle.radius == pytest.approx(5.0)


def test_circle_two_point_cancelled_no_entity(run, make_context, document):
    result = run(
        make_context(), "circle", [keyword_input("2P"), "0,0", Cancelled()]
    )
    assert result.status == "cancelled"
    assert document.doc_version == 0
    assert document.count_by_kind() == {}


def test_circle_three_point_cancelled_no_entity(run, make_context, document):
    result = run(
        make_context(),
        "circle", [keyword_input("3P"), "0,0", "10,0", Cancelled()],
    )
    assert result.status == "cancelled"
    assert document.doc_version == 0
    assert document.count_by_kind() == {}
