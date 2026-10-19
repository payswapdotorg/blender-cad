"""Draw-command tests through the registry (TP-CAT-01).

LINE (chained + Close/Undo), CIRCLE (radius/diameter/point), ARC (3-point
and start-center-end) — all driven by ``Registry.run_command`` with a
ScriptedProvider: the exact interface the modal viewport operator and the
acceptance battery use. Exact geometry is asserted on the REAL bcdoc.
"""

import math

import pytest

from bccmd import Point, point_input, selection_input


# ---------------------------------------------------------------------------
# LINE
# ---------------------------------------------------------------------------

def test_line_chained_segments_and_enter_ends(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "line", ["0,0", "10,0", "@0,10", ""])
    assert result.status == "ok"
    assert result.summary == "LINE: 2 segment(s)"
    assert len(result.created) == 2
    lines = [document.get(eid) for eid in result.created]
    assert lines[0].p1 == (0.0, 0.0, 0.0)
    assert lines[0].p2 == (10.0, 0.0, 0.0)
    assert lines[1].p1 == (10.0, 0.0, 0.0)
    assert lines[1].p2 == (10.0, 10.0, 0.0)
    # last_point tracks the newest vertex (relative input resolved from it)
    assert ctx.last_point == Point(10.0, 10.0)


def test_line_close_option_closes_the_polygon(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "line", ["0,0", "@10,0", "@0,10", "C"])
    assert result.status == "ok"
    assert "[closed]" in result.summary
    assert len(result.created) == 3
    closing = document.get(result.created[-1])
    assert closing.p1 == (10.0, 10.0, 0.0)
    assert closing.p2 == (0.0, 0.0, 0.0)


def test_line_one_committed_transaction_per_segment(run, make_context, document):
    """AutoCAD-familiar granularity: each committed segment is ONE undo step."""
    ctx = make_context()
    run(ctx, "line", ["0,0", "@10,0", "@10,0", "@0,10"])
    assert document.count_by_kind() == {"line": 3}
    assert document.undo_depth() == 3
    document.undo()
    assert document.count_by_kind() == {"line": 2}
    # the remaining segments are the FIRST two (the last was undone)
    remaining = document.entities()
    assert remaining[-1].p2 == (20.0, 0.0, 0.0)


def test_line_undo_option_removes_last_segment_of_this_run(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "line", ["0,0", "10,0", "U", "@10,0", ""])
    assert result.status == "ok"
    assert len(result.created) == 1
    assert document.count_by_kind() == {"line": 1}
    # the surviving segment is the re-drawn one
    line = document.get(result.created[0])
    assert line.p1 == (0.0, 0.0, 0.0)
    assert line.p2 == (10.0, 0.0, 0.0)
    assert document.undo_depth() == 1  # segment 1 was undone by the option


def test_line_undo_option_before_first_segment_reasks_first_point(
    run, make_context, document
):
    # "U" at the first NEXT-point prompt (no segment yet) discards the first
    # point and re-asks it (AutoCAD LINE behavior).
    ctx = make_context()
    result = run(ctx, "line", ["0,0", "U", "5,5", "@5,0", ""])
    assert result.status == "ok"
    assert len(result.created) == 1
    assert "first point discarded" in "\n".join(ctx.feedback_messages)
    line = document.get(result.created[0])
    assert line.p1 == (5.0, 5.0, 0.0)
    assert line.p2 == (10.0, 5.0, 0.0)


def test_line_keyword_prefix_match_c_for_close(run, make_context, document):
    # "c" is unambiguous against [Close/Undo] → Close (ux-spec §3.3)
    result = run(make_context(), "line", ["0,0", "@1,0", "c"])
    assert "[closed]" in result.summary


def test_line_cancel_mid_command_keeps_committed_segments(
    run, make_context, document
):
    # AutoCAD-familiar: already-committed segments stay; Esc only drops the
    # segment in progress (none here — Cancelled arrives at the next-point
    # prompt). One committed segment = one undo step.
    from bccmd import Cancelled

    ctx = make_context()
    result = run(ctx, "line", ["0,0", "@1,0", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {"line": 1}
    assert document.doc_version == 1
    assert document.undo_depth() == 1


# ---------------------------------------------------------------------------
# CIRCLE
# ---------------------------------------------------------------------------

def test_circle_center_and_radius(run, make_context, document):
    result = run(make_context(), "circle", ["30,30", "5"])
    assert result.status == "ok"
    circle = document.get(result.created[0])
    assert circle.center == (30.0, 30.0, 0.0)
    assert circle.radius == pytest.approx(5.0)


def test_circle_diameter_option(run, make_context, document):
    result = run(make_context(), "circle", ["0,0", "D", "10"])
    assert result.status == "ok"
    circle = document.get(result.created[0])
    assert circle.radius == pytest.approx(5.0)
    assert circle.center == (0.0, 0.0, 0.0)


def test_circle_point_entry_sets_radius_from_center(
    run, make_context, document
):
    result = run(make_context(), "circle", [point_input(1, 2), point_input(4, 6)])
    circle = document.get(result.created[0])
    assert circle.center == (1.0, 2.0, 0.0)
    assert circle.radius == pytest.approx(5.0)


def test_circle_negative_radius_reprompts(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "circle", ["0,0", "-3", "7"])
    assert result.status == "ok"
    circle = document.get(result.created[0])
    assert circle.radius == pytest.approx(7.0)
    assert any("positive" in m for m in ctx.feedback_messages)


# ---------------------------------------------------------------------------
# ARC — default 3-point method
# ---------------------------------------------------------------------------

def test_arc_three_point_ccw_through_mid(run, make_context, document):
    # start (20,10) 0°, mid (10,20) 90°, end (0,10) 180° on c=(10,10) r=10
    result = run(make_context(), "arc", ["20,10", "10,20", "0,10"])
    assert result.status == "ok"
    arc = document.get(result.created[0])
    assert arc.center == pytest.approx((10.0, 10.0, 0.0))
    assert arc.radius == pytest.approx(10.0)
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(180.0)


def test_arc_three_point_other_direction_represented_ccw_from_end(
    run, make_context, document
):
    result = run(make_context(), "arc", ["0,10", "10,20", "20,10"])
    arc = document.get(result.created[0])
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(180.0)


def test_arc_collinear_points_reprompt(run, make_context, document):
    # (0,0),(5,0),(10,0) are collinear → diagnostic + re-ask for the end
    # point; the accepted end (10,10) produces the real 3-point arc.
    ctx = make_context()
    result = run(ctx, "arc", ["0,0", "5,0", "10,0", "10,10"])
    assert result.status == "ok"
    assert any("collinear" in m for m in ctx.feedback_messages)
    arc = document.get(result.created[0])
    # the stored arc passes through all three picked points (fine-grained
    # polyline sampling: 256 segments keeps the chord error << 0.1 units)
    from bcdraft.geometry import arc_points

    pts = arc_points(
        arc.center, arc.radius, arc.start_angle, arc.end_angle, segments=256
    )
    for target in ((0.0, 0.0), (5.0, 0.0), (10.0, 10.0)):
        assert any(
            math.hypot(p[0] - target[0], p[1] - target[1]) < 0.1 for p in pts
        ), f"arc misses picked point {target}"


def test_arc_start_center_end_method_selected_by_keyword(
    run, make_context, document
):
    # [Center] switch → SCE: c=(10,10), start (20,10), end (0,10)
    result = run(make_context(), "arc", ["C", "10,10", "20,10", "0,10"])
    assert result.status == "ok"
    assert "start-center-end" in result.summary
    arc = document.get(result.created[0])
    assert arc.center == pytest.approx((10.0, 10.0, 0.0))
    assert arc.radius == pytest.approx(10.0)
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(180.0)


def test_arc_start_center_end_full_circle_when_end_equals_start(
    run, make_context, document
):
    # v0 convention: start_angle == end_angle represents the FULL circle
    # (the arc sampler's CCW sweep of 360°); the angles stay normalized to
    # [0, 360) so the DXF round-trip representation is stable.
    result = run(make_context(), "arc", ["C", "0,0", "5,0", "5,0"])
    arc = document.get(result.created[0])
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(0.0)
    assert arc.radius == pytest.approx(5.0)


def test_arc_keeps_layer_properties_from_document_defaults(run, make_context, document):
    result = run(make_context(), "arc", ["20,10", "10,20", "0,10"])
    arc = document.get(result.created[0])
    assert arc.layer == "0"
    assert arc.linetype == "ByLayer"
    assert arc.color is None
