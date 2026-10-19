"""M2 drafting-core modify-command tests (TP-CAT-01 P0 subset, contract §0).

MIRROR, OFFSET, ARRAYRECT, BREAK, JOIN, EXPLODE, STRETCH, MATCHPROP plus
MOVE/ROTATE/SCALE on the new M2 entity kinds — all driven by
``Registry.run_command`` with a ScriptedProvider (the exact interface the
modal operator and the acceptance battery use), asserting EXACT geometry on
the REAL bcdoc and the pinned locked-layer / noun-verb / undo-granularity
semantics (contracts §2.2/§4; one committed transaction per command).
"""

import math

import pytest

from bccmd import Cancelled, point_input, selection_input

from bcdoc.entities import Arc, Circle, Insert, Line, Polyline, Text

from bcdraft.geometry import arc_from_bulge, entity_bbox


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed(document, entities):
    """Add entities in one transaction; returns their ids in order."""
    with document.transaction("seed"):
        for entity in entities:
            document.add_entity(entity)
    return [entity.id for entity in entities]


def _ids(document, kind):
    return [e.id for e in document.entities() if e.kind == kind]


def _add_locked_layer(document, name="Locked"):
    with document.transaction("layer"):
        document.layers.add(name)
        document.layers.set_props(name, locked=True)
    return name


# ---------------------------------------------------------------------------
# MIRROR
# ---------------------------------------------------------------------------

def test_mirror_line_exact_reflection_keep_source(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 5, 0), (10, 5, 0))])
    result = run(ctx, "mirror", [selection_input(ids), "0,0", "10,0", "N"])
    assert result.status == "ok"
    assert "source kept" in result.summary
    assert result.created and result.created[0] != ids[0]
    assert result.modified == []
    assert document.count_by_kind() == {"line": 2}
    mirrored = document.get(result.created[0])
    # reflection across the X axis: (x, y) -> (x, -y)
    assert mirrored.p1 == (0.0, -5.0, 0.0)
    assert mirrored.p2 == (10.0, -5.0, 0.0)
    assert document.get(ids[0]).p1 == (0.0, 5.0, 0.0)  # source untouched


def test_mirror_line_erase_source_replaces_in_place(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((3, 0, 0), (3, 10, 0))])
    result = run(ctx, "mirror", [selection_input(ids), "0,0", "0,10", "Y"])
    assert "erased source" in result.summary
    assert result.modified == ids
    assert result.created == []
    assert document.count_by_kind() == {"line": 1}
    line = document.get(ids[0])
    assert line.p1 == (-3.0, 0.0, 0.0)
    assert line.p2 == (-3.0, 10.0, 0.0)


def test_mirror_across_diagonal_axis(run, make_context, document):
    # reflecting (x, y) across y = x gives (y, x)
    ids = _seed(document, [Line((0, 1, 0), (2, 1, 0))])
    result = run(make_context(), "mirror", [selection_input(ids), "0,0", "1,1", "Y"])
    line = document.get(ids[0])
    assert line.p1 == pytest.approx((1.0, 0.0, 0.0))
    assert line.p2 == pytest.approx((1.0, 2.0, 0.0))


def test_mirror_arc_swaps_sweep_angles(run, make_context, document):
    # arc 0->90 mirrored across the X axis runs 270->0 (the reflected point
    # set with the traversal reversed: start and end angles swap)
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    result = run(
        make_context(), "mirror", [selection_input(ids), "0,0", "10,0", "Y"]
    )
    arc = document.get(ids[0])
    assert arc.center == (0.0, 0.0, 0.0)
    assert arc.start_angle == pytest.approx(270.0)
    assert arc.end_angle == pytest.approx(0.0)
    # the mirrored arc passes through the reflected midpoint of the original
    # sweep: 45 deg maps to (5*sqrt(2)/2, -5*sqrt(2)/2)
    angle = math.radians(arc.start_angle + 45.0)
    point = (arc.center[0] + arc.radius * math.cos(angle),
             arc.center[1] + arc.radius * math.sin(angle))
    assert point == pytest.approx((3.535533905932738, -3.535533905932737))


def test_mirror_polyline_flips_bulge_signs(run, make_context, document):
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0)], bulges=[0.5, 0.0])])
    result = run(
        make_context(), "mirror", [selection_input(ids), "0,0", "10,0", "Y"]
    )
    pl = document.get(ids[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert pl.bulges[0] == pytest.approx(-0.5)


def test_mirror_erase_source_is_one_undo_step(run, make_context, document):
    ids = _seed(document, [Line((0, 1, 0), (1, 1, 0))])
    depth = document.undo_depth()
    run(make_context(), "mirror", [selection_input(ids), "0,0", "1,0", "Y"])
    assert document.undo_depth() == depth + 1
    document.undo()
    line = document.get(ids[0])
    assert line.p1 == (0.0, 1.0, 0.0) and line.p2 == (1.0, 1.0, 0.0)


def test_mirror_identical_axis_points_reask(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 1, 0), (1, 1, 0))])
    result = run(ctx, "mirror", [selection_input(ids), "0,0", "0,0", "1,0", "Y"])
    assert result.status == "ok"
    assert any("must differ" in m for m in ctx.feedback_messages)
    line = document.get(ids[0])
    assert line.p1 == (0.0, -1.0, 0.0)
    assert line.p2 == (1.0, -1.0, 0.0)


def test_mirror_text_reflects_rotation(run, make_context, document):
    ids = _seed(document, [Text((5, 5, 0), height=2.0, rotation=30.0, content="T")])
    run(make_context(), "mirror", [selection_input(ids), "0,0", "10,0", "Y"])
    text = document.get(ids[0])
    assert text.position == (5.0, -5.0, 0.0)
    assert text.rotation == pytest.approx(330.0)  # 2*0 - 30


# ---------------------------------------------------------------------------
# OFFSET
# ---------------------------------------------------------------------------

def test_offset_line_parallel_on_picked_side(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    result = run(
        make_context(), "offset", ["2", selection_input(ids), "5,3", ""]
    )
    assert result.status == "ok"
    assert "2 object(s) offset" not in result.summary
    assert len(result.created) == 1
    off = document.get(result.created[0])
    assert off.p1 == (0.0, 2.0, 0.0)
    assert off.p2 == (10.0, 2.0, 0.0)
    assert off.layer == "0"


def test_offset_line_other_side(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    result = run(
        make_context(), "offset", ["2", selection_input(ids), "5,-3", ""]
    )
    off = document.get(result.created[0])
    assert off.p1 == (0.0, -2.0, 0.0)
    assert off.p2 == (10.0, -2.0, 0.0)


def test_offset_circle_radius_grows_and_shrinks(run, make_context, document):
    ids = _seed(document, [Circle((0, 0, 0), 5)])
    # pick outside -> radius + distance
    result = run(
        make_context(), "offset", ["2", selection_input(ids), "10,0", ""]
    )
    assert document.get(result.created[0]).radius == pytest.approx(7.0)
    # pick inside -> radius - distance
    result = run(
        make_context(), "offset", ["2", selection_input(ids), "1,0", ""]
    )
    inside = document.get(result.created[0])
    assert inside.center == (0.0, 0.0, 0.0)
    assert inside.radius == pytest.approx(3.0)


def test_offset_arc_radius_sides_keep_angles(run, make_context, document):
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    result = run(
        make_context(), "offset", ["1", selection_input(ids), "10,10", ""]
    )
    off = document.get(result.created[0])
    assert off.center == (0.0, 0.0, 0.0)
    assert off.radius == pytest.approx(6.0)
    assert off.start_angle == 0.0 and off.end_angle == 90.0
    # inside pick
    result = run(
        make_context(), "offset", ["1", selection_input(ids), "1,1", ""]
    )
    off = document.get(result.created[0])
    assert off.radius == pytest.approx(4.0)


def test_offset_arc_collapse_skipped_with_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 2, 0, 90)])
    result = run(ctx, "offset", ["5", selection_input(ids), "1,1", ""])
    assert result.status == "ok"
    assert result.created == []
    assert any("collapse" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"arc": 1}


def test_offset_through_point_on_line_and_circle(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Circle((0, 5, 0), 3)])
    result = run(
        make_context(),
        "offset", ["Through",
                   selection_input([ids[0]]), "5,7",      # 7 above the line
                   selection_input([ids[1]]), "0,10",     # 2 outside the circle
                   ""],
    )
    assert result.status == "ok"
    assert "through points" in result.summary
    line_off = document.get(result.created[0])
    assert line_off.p1 == (0.0, 7.0, 0.0)
    assert line_off.p2 == (10.0, 7.0, 0.0)
    circle_off = document.get(result.created[1])
    assert circle_off.center == (0.0, 5.0, 0.0)
    # the through point IS the side: |pick - center| - radius = 5 - 3
    assert circle_off.radius == pytest.approx(5.0)


def test_offset_through_point_not_supported_on_polyline(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])])
    result = run(
        ctx, "offset", ["Through", selection_input(ids), "5,5", ""]
    )
    assert result.status == "ok"
    assert result.created == []
    assert any("not supported on polylines" in m for m in ctx.feedback_messages)


def test_offset_polyline_per_segment_with_jog(run, make_context, document):
    """L-shaped open polyline offset inwards: each segment offsets parallel;
    the non-parallel join gets a straight jog connector (documented M2
    no-corner-heal limit) and the feedback says so."""
    ctx = make_context()
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])])
    result = run(
        ctx, "offset", ["1", selection_input(ids), "5,5", ""]
    )
    assert result.status == "ok"
    assert any("join(s) not healed" in m for m in ctx.feedback_messages)
    off = document.get(result.created[0])
    assert not off.closed
    # segment 1 (y=0 leg) moved up by 1; segment 2 (x=10 leg) moved left by 1;
    # jog from (10, 1) to (9, 0)
    assert off.vertices == (
        (0.0, 1.0, 0.0), (10.0, 1.0, 0.0), (9.0, 0.0, 0.0), (9.0, 10.0, 0.0),
    )


def test_offset_negative_and_zero_distance_rejected(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    result = run(
        ctx, "offset", ["-1", "0", "2", selection_input(ids), "5,3", ""]
    )
    assert result.status == "ok"
    assert sum(1 for m in ctx.feedback_messages if "positive distance" in m) == 2
    off = document.get(result.created[0])
    assert off.p1 == (0.0, 2.0, 0.0)


def test_offset_undo_option_pops_last_offset(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    result = run(
        ctx, "offset",
        ["1", selection_input(ids), "5,3",       # offset 1 (up)
         selection_input(ids), "5,-3",             # offset 2 (down)
         "U",                                     # undo offset 2
         selection_input(ids), "5,5",             # offset 3 (up)
         ""],
    )
    assert result.status == "ok"
    assert len(result.created) == 2
    assert any("last offset undone" in m for m in ctx.feedback_messages)
    ys = sorted(
        document.get(eid).p1[1]
        for eid in result.created
    )
    assert ys == [1.0, 1.0]


def test_offset_one_transaction_per_offset_object(
    run, make_context, document
):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Circle((0, 5, 0), 3)])
    depth = document.undo_depth()
    run(
        make_context(),
        "offset", ["2",
                   selection_input([ids[0]]), "5,3",
                   selection_input([ids[1]]), "0,20",
                   ""],
    )
    assert document.undo_depth() == depth + 2
    document.undo()
    assert document.count_by_kind() == {"line": 2, "circle": 1}


def test_offset_multiple_selected_uses_first_with_feedback(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Line((0, 1, 0), (10, 1, 0))])
    result = run(
        ctx, "offset", ["1", selection_input(ids), "5,3", ""]
    )
    assert any("one object at a time" in m for m in ctx.feedback_messages)
    off = document.get(result.created[0])
    assert off.p1 == (0.0, 1.0, 0.0)  # ids[0] offset up by 1


def test_offset_locked_layer_skipped_with_feedback(
    run, make_context, document
):
    ctx = make_context()
    locked = _add_locked_layer(document)
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0), layer=locked)])
    result = run(ctx, "offset", ["1", selection_input(ids), "5,3", ""])
    assert result.status == "ok"
    assert result.created == []
    assert any("locked layer skipped" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"line": 1}


# ---------------------------------------------------------------------------
# ARRAYRECT
# ---------------------------------------------------------------------------

def test_arrayrect_grid_positions_exact(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    result = run(
        ctx, "arrayrect", [selection_input(ids), "2", "3", "5", "2", ""]
    )
    assert result.status == "ok"
    assert "2×3 grid" in result.summary
    # originals occupy cell (1,1); copies fill the remaining 5 cells
    assert len(result.created) == 5
    assert document.count_by_kind() == {"line": 6}
    positions = sorted((e.p1, e.p2) for e in document.entities())
    expected = sorted(
        (((x, y, 0.0), (x + 1, y, 0.0))
         for x in (0.0, 2.0, 4.0) for y in (0.0, 5.0)),
    )
    assert positions == expected
    assert document.undo_depth() == 2  # seed + ONE array transaction


def test_arrayrect_negative_spacing_left_down(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    # row spacing -2 (rows stack DOWN), column spacing -3 (columns go LEFT)
    run(
        make_context(), "arrayrect",
        [selection_input(ids), "2", "2", "-2", "-3", ""],
    )
    xs = sorted(e.p1 for e in document.entities())
    assert xs == [
        (-3.0, -2.0, 0.0), (-3.0, 0.0, 0.0), (0.0, -2.0, 0.0), (0.0, 0.0, 0.0),
    ]


def test_arrayrect_count_validation_reprompts(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    result = run(
        ctx, "arrayrect",
        [selection_input(ids), "0", "2.5", "2", "2", "1", "1", ""],
    )
    assert result.status == "ok"
    assert sum(
        1 for m in ctx.feedback_messages if "whole number >= 1" in m
    ) == 2
    assert len(result.created) == 3  # 2x2 grid minus the original cell


def test_arrayrect_undo_restores(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    run(
        make_context(), "arrayrect",
        [selection_input(ids), "2", "2", "5", "5", ""],
    )
    document.undo()
    assert document.count_by_kind() == {"line": 1}


# ---------------------------------------------------------------------------
# BREAK
# ---------------------------------------------------------------------------

def test_break_line_splits_into_two_exact_pieces(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    # the picks hover off the line: they project onto it (t parameters 0.3/0.7)
    result = run(ctx, "break", [selection_input(ids), "3,0.5", "7,-0.5"])
    assert result.status == "ok"
    assert result.removed == ids
    assert len(result.created) == 2
    assert document.count_by_kind() == {"line": 2}
    assert document.undo_depth() == 2  # seed + one BREAK transaction
    pieces = sorted(document.entities(), key=lambda e: e.p1[0])
    assert pieces[0].p1 == (0.0, 0.0, 0.0)
    assert pieces[0].p2 == (3.0, 0.0, 0.0)
    assert pieces[1].p1 == (7.0, 0.0, 0.0)
    assert pieces[1].p2 == (10.0, 0.0, 0.0)


def test_break_line_at_one_point_splits_in_two(run, make_context, document):
    # identical picks on a line split it into two touching pieces (the
    # AutoCAD "break at point" degenerate case)
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    result = run(
        make_context(), "break", [selection_input(ids), "3,0", "3,0"]
    )
    pieces = sorted(document.entities(), key=lambda e: e.p1[0])
    assert len(pieces) == 2
    assert pieces[0].p2 == (3.0, 0.0, 0.0)
    assert pieces[1].p1 == (3.0, 0.0, 0.0)


def test_break_circle_to_arc_sweep_exact(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Circle((0, 0, 0), 5)])
    result = run(ctx, "break", [selection_input(ids), "5,0", "0,5"])
    assert result.status == "ok"
    assert document.count_by_kind() == {"arc": 1}
    assert result.removed == ids
    arc = document.get(result.created[0])
    # the CCW portion 0->90 is removed: the survivor runs 90 -> 360
    assert arc.center == (0.0, 0.0, 0.0)
    assert arc.radius == pytest.approx(5.0)
    assert arc.start_angle == pytest.approx(90.0)
    assert arc.end_angle == pytest.approx(0.0)


def test_break_circle_same_point_feedback_reasks(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Circle((0, 0, 0), 5)])
    result = run(
        ctx, "break", [selection_input(ids), "5,0", "5,0", "0,5"]
    )
    assert result.status == "ok"
    assert any("coincide" in m for m in ctx.feedback_messages)
    # nothing was committed by the degenerate attempt; the accepted picks
    # broke the circle normally
    assert document.count_by_kind() == {"arc": 1}
    arc = document.get(result.created[0])
    assert arc.start_angle == pytest.approx(90.0)


def test_break_arc_into_two_arcs(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    # break between 45 and 60 degrees
    first = point_input(5 * math.cos(math.radians(45)), 5 * math.sin(math.radians(45)))
    second = point_input(5 * math.cos(math.radians(60)), 5 * math.sin(math.radians(60)))
    result = run(ctx, "break", [selection_input(ids), first, second])
    assert result.status == "ok"
    assert result.removed == ids
    assert len(result.created) == 2
    arcs = sorted(document.entities(), key=lambda e: e.start_angle)
    assert arcs[0].start_angle == pytest.approx(0.0)
    assert arcs[0].end_angle == pytest.approx(45.0)
    assert arcs[1].start_angle == pytest.approx(60.0)
    assert arcs[1].end_angle == pytest.approx(90.0)
    for arc in arcs:
        assert arc.radius == pytest.approx(5.0)


def test_break_arc_at_its_endpoints_removes_it_entirely(
    run, make_context, document
):
    # picks exactly at the start and end angles ARE on the arc (a pick at the
    # start angle must not be rejected as "not on the arc")
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    result = run(ctx, "break", [selection_input(ids), "5,0", "0,5"])
    assert result.status == "ok"
    assert result.created == []          # everything between was removed
    assert result.removed == ids
    assert document.count_by_kind() == {}


def test_break_arc_pick_outside_sweep_rejected(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    result = run(ctx, "break", [selection_input(ids), "0,-5", "0,5", Cancelled()])
    assert result.status == "cancelled"
    assert any("not on the arc" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"arc": 1}


def test_break_arc_same_point_feedback_reasks(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    result = run(
        ctx, "break",
        [selection_input(ids), "3.535,3.535", "3.535,3.535",
         "3.535,3.535", "0,5", Cancelled()],
    )
    assert any("coincide" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"arc": 1}


def test_break_first_option_reasks_first_point(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    result = run(
        ctx, "break",
        [selection_input(ids), "2,0", "First", "3,0", "7,0"],
    )
    assert result.status == "ok"
    pieces = sorted(document.entities(), key=lambda e: e.p1[0])
    assert pieces[0].p2 == (3.0, 0.0, 0.0)
    assert pieces[1].p1 == (7.0, 0.0, 0.0)


def test_break_one_object_at_a_time_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Line((20, 0, 0), (30, 0, 0))])
    result = run(
        ctx, "break", [selection_input(ids), "3,0", "7,0"]
    )
    assert any("one object at a time" in m for m in ctx.feedback_messages)
    assert len(result.created) == 2  # only ids[0] was broken


def test_break_unsupported_kind_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Circle((0, 0, 0), 1), Insert("none", (0, 0, 0))])
    result = run(ctx, "break", [selection_input([ids[1]])])
    assert result.status == "ok"
    assert any("cannot break" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"circle": 1, "insert": 1}


# ---------------------------------------------------------------------------
# JOIN
# ---------------------------------------------------------------------------

def test_join_collinear_lines_merge_far_endpoints(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Line((10, 0, 0), (20, 0, 0))])
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert result.status == "ok"
    assert "1 object(s) merged" in result.summary
    assert result.removed == [ids[1]]
    assert result.modified == [ids[0]]
    assert document.count_by_kind() == {"line": 1}
    merged = document.get(ids[0])
    assert merged.p1 == (0.0, 0.0, 0.0)
    assert merged.p2 == (20.0, 0.0, 0.0)


def test_join_collinear_lines_with_gap_bridge(run, make_context, document):
    # collinear but disjoint: AutoCAD JOIN bridges the gap into one line
    ids = _seed(document, [Line((0, 0, 0), (5, 0, 0)), Line((10, 0, 0), (15, 0, 0))])
    run(
        make_context(), "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    merged = document.get(ids[0])
    assert merged.p1 == (0.0, 0.0, 0.0)
    assert merged.p2 == (15.0, 0.0, 0.0)


def test_join_non_collinear_skipped_with_feedback(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Line((10, 0, 0), (10, 10, 0))])
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert "0 object(s) merged" in result.summary
    assert any("not collinear" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"line": 2}


def test_join_concentric_arcs_merge_sweep(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90), Arc((0, 0, 0), 5, 90, 180)])
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert result.status == "ok"
    assert result.removed == [ids[1]]
    arc = document.get(ids[0])
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(180.0)


def test_join_arcs_to_full_circle(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 180), Arc((0, 0, 0), 5, 180, 0)])
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert result.status == "ok"
    assert document.count_by_kind() == {"circle": 1}
    circle = document.get(ids[0])
    assert circle.center == (0.0, 0.0, 0.0)
    assert circle.radius == pytest.approx(5.0)


def test_join_arcs_gap_skipped_with_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90), Arc((0, 0, 0), 5, 120, 180)])
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert any("not contiguous" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"arc": 2}


def test_join_line_into_polyline_appends(run, make_context, document):
    ctx = make_context()
    ids = _seed(
        document,
        [Polyline([(0, 0, 0), (5, 0, 0)]), Line((5, 0, 0), (10, 0, 0))],
    )
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert result.status == "ok"
    assert result.removed == [ids[1]]
    # the polyline keeps its identity (same id) and grows
    pl = document.get(ids[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert list(pl.bulges) == [0.0, 0.0, 0.0]
    assert document.count_by_kind() == {"polyline": 1}


def test_join_line_into_polyline_prepends(run, make_context, document):
    ids = _seed(
        document,
        [Polyline([(5, 0, 0), (10, 0, 0)]), Line((0, 0, 0), (5, 0, 0))],
    )
    run(
        make_context(), "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    pl = document.get(ids[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0))


def test_join_arc_into_polyline_sets_connector_bulge(
    run, make_context, document
):
    # an arc absorbing into the polyline tail becomes the connector segment:
    # bulge_from_arc of the CCW semicircle (5,0)->(10,0) about (7.5,0)
    ids = _seed(
        document,
        [Polyline([(0, 0, 0), (5, 0, 0)]), Arc((7.5, 0, 0), 2.5, 180, 0)],
    )
    result = run(
        make_context(), "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert result.status == "ok"
    pl = document.get(ids[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    # CCW traversal absorbed forward: positive semicircle bulge
    assert pl.bulges[1] == pytest.approx(1.0)
    assert document.count_by_kind() == {"polyline": 1}


def test_join_skips_cross_kind_with_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Circle((20, 0, 0), 1)])
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert any("cannot join a circle" in m for m in ctx.feedback_messages)
    assert "1 skipped" in result.summary
    assert document.count_by_kind() == {"line": 1, "circle": 1}


def test_join_one_undo_step(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Line((10, 0, 0), (20, 0, 0))])
    depth = document.undo_depth()
    run(
        make_context(), "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert document.undo_depth() == depth + 1
    document.undo()
    assert document.count_by_kind() == {"line": 2}
    assert document.get(ids[1]).p2 == (20.0, 0.0, 0.0)


def test_join_source_locked_skipped(run, make_context, document):
    ctx = make_context()
    locked = _add_locked_layer(document)
    ids = _seed(
        document,
        [Line((0, 0, 0), (10, 0, 0), layer=locked),
         Line((10, 0, 0), (20, 0, 0))],
    )
    result = run(
        ctx, "join", [selection_input([ids[0]]), selection_input([ids[1]])]
    )
    assert result.status == "ok"
    assert any("locked layer skipped" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"line": 2}


# ---------------------------------------------------------------------------
# EXPLODE
# ---------------------------------------------------------------------------

def _make_insert(document, name="B", position=(10, 10, 0), scale=(2, 2, 2),
                 rotation=30, layer="L1"):
    # members built OUTSIDE the document (add_block stores copies): the
    # drawing carries only the INSERT entity
    with document.transaction("block"):
        member = Line((0, 0, 0), (4, 0, 0), layer="0", color=0)
        circle = Circle((2, 2, 0), 1, layer="M")
        document.add_block(name, (0, 0, 0), [member, circle])
    with document.transaction("insert"):
        return document.add_entity(
            Insert(name, position, scale=scale, rotation=rotation, layer=layer)
        ).id


def test_explode_insert_transformed_members(run, make_context, document):
    ctx = make_context()
    insert_id = _make_insert(document)
    result = run(ctx, "explode", [selection_input([insert_id])])
    assert result.status == "ok"
    assert result.removed == [insert_id]
    assert len(result.created) == 2
    assert document.count_by_kind() == {"line": 1, "circle": 1}
    line, circle = (document.get(eid) for eid in result.created)
    # member line (0,0)-(4,0): -base (0,0,0), scale 2 -> (0,0)-(8,0),
    # rotate 30 CCW, translate to (10,10)
    assert line.p1 == (10.0, 10.0, 0.0)
    assert line.p2 == pytest.approx(
        (10.0 + 8.0 * math.cos(math.radians(30.0)),
         10.0 + 8.0 * math.sin(math.radians(30.0)), 0.0)
    )
    # member circle c=(2,2) r=1: center scaled 2 -> (4,4), rotated 30, moved
    assert circle.center == pytest.approx(
        (10.0 + 4.0 * math.cos(math.radians(30.0)) - 4.0 * math.sin(math.radians(30.0)),
         10.0 + 4.0 * math.sin(math.radians(30.0)) + 4.0 * math.cos(math.radians(30.0)),
         0.0)
    )
    assert circle.radius == pytest.approx(2.0)  # |sx| * r


def test_explode_insert_byblock_and_layer_zero_resolution(
    run, make_context, document
):
    ctx = make_context()
    insert_id = _make_insert(document)
    result = run(ctx, "explode", [selection_input([insert_id])])
    line, circle = (document.get(eid) for eid in result.created)
    # layer-0 members adopt the INSERT's layer; other layers stay
    assert line.layer == "L1"
    assert circle.layer == "M"
    # ByBlock color 0 resolves against the insert's color (None = ByLayer)
    assert line.color is None
    assert circle.color is None


def test_explode_insert_space_inheritance(run, make_context, document):
    ctx = make_context()
    with document.transaction("lay"):
        document.add_layout("Layout1")
    insert_id = _make_insert(document)
    with document.transaction("move-space"):
        document.update_entity(insert_id, space="Layout1")
    result = run(ctx, "explode", [selection_input([insert_id])])
    for eid in result.created:
        assert document.get(eid).space == "Layout1"


def test_explode_missing_block_skipped_with_feedback(
    run, make_context, document
):
    ctx = make_context()
    with document.transaction("orphan"):
        insert_id = document.add_entity(Insert("ghost", (0, 0, 0))).id
    result = run(ctx, "explode", [selection_input([insert_id])])
    assert result.status == "ok"
    assert any("not found" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"insert": 1}


def test_explode_polyline_to_lines_and_arcs(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)],
                                    bulges=[0.0, 1.0, 0.0])])
    result = run(ctx, "explode", [selection_input(ids)])
    assert result.status == "ok"
    assert result.removed == ids
    assert document.count_by_kind() == {"line": 1, "arc": 1}
    line = document.get(_ids(document, "line")[0])
    arc = document.get(_ids(document, "arc")[0])
    assert line.p1 == (0.0, 0.0, 0.0) and line.p2 == (10.0, 0.0, 0.0)
    # the semicircle segment becomes an arc with the SAME point set
    center, radius, _s, _e = arc_from_bulge((10, 0, 0), (10, 10, 0), 1.0)
    assert arc.center == pytest.approx(center)
    assert arc.radius == pytest.approx(radius)


def test_explode_polyline_widths_dropped_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0)],
                                    widths=[(2, 1), (1, 1)])])
    result = run(ctx, "explode", [selection_input(ids)])
    assert any("widths dropped" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"line": 1}


def test_explode_non_explodable_feedback(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Circle((0, 0, 0), 5), Line((0, 0, 0), (1, 0, 0))])
    result = run(ctx, "explode", [selection_input([ids[0]])])
    assert result.status == "ok"
    assert result.created == [] and result.removed == []
    assert any("cannot explode a circle" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"circle": 1, "line": 1}


def test_explode_one_undo_step_restores_insert(run, make_context, document):
    insert_id = _make_insert(document)
    depth = document.undo_depth()
    run(make_context(), "explode", [selection_input([insert_id])])
    assert document.undo_depth() == depth + 1
    document.undo()
    assert document.count_by_kind() == {"insert": 1}
    assert document.get(insert_id).name == "B"


# ---------------------------------------------------------------------------
# STRETCH
# ---------------------------------------------------------------------------

def test_stretch_moves_only_endpoints_inside_window(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0)), Line((0, 20, 0), (10, 20, 0))])
    # crossing window over x in [8,12], y in [-1,1]: only the first line's
    # SECOND endpoint is inside
    result = run(ctx, "stretch", ["8,-1", "12,1", "10,0", "12,0"])
    assert result.status == "ok"
    assert result.modified == [ids[0]]
    line = document.get(ids[0])
    assert line.p1 == (0.0, 0.0, 0.0)
    assert line.p2 == (12.0, 0.0, 0.0)
    other = document.get(ids[1])
    assert other.p1 == (0.0, 20.0, 0.0) and other.p2 == (10.0, 20.0, 0.0)


def test_stretch_circle_moves_whole_when_center_inside(
    run, make_context, document
):
    ids = _seed(document, [Circle((10, 0, 0), 2), Circle((0, 0, 0), 2)])
    result = run(
        make_context(), "stretch", ["9,-3", "11,3", "10,0", "13,0"]
    )
    assert result.modified == [ids[0]]
    assert document.get(ids[0]).center == (13.0, 0.0, 0.0)
    assert document.get(ids[0]).radius == pytest.approx(2.0)
    assert document.get(ids[1]).center == (0.0, 0.0, 0.0)


def test_stretch_zero_length_line_kept_zero_length(
    run, make_context, document
):
    ids = _seed(document, [Line((10, 0, 0), (10, 0, 0))])
    result = run(
        make_context(), "stretch", ["9,-1", "11,1", "10,0", "12,0"]
    )
    assert result.modified == [ids[0]]
    line = document.get(ids[0])
    assert line.p1 == (12.0, 0.0, 0.0)
    assert line.p2 == (12.0, 0.0, 0.0)  # still degenerate


def test_stretch_polyline_moves_only_inside_vertices(
    run, make_context, document
):
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)])])
    # window around (10,10) only: that vertex moves; bulges are untouched
    result = run(
        make_context(), "stretch", ["9,9", "11,11", "10,10", "12,10"]
    )
    assert result.modified == [ids[0]]
    pl = document.get(ids[0])
    assert pl.vertices == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                           (12.0, 10.0, 0.0), (0.0, 10.0, 0.0))


def test_stretch_arc_endpoint_unsupported_skip_feedback(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Arc((0, 0, 0), 5, 0, 90)])
    result = run(ctx, "stretch", ["-1,-1", "6,6", "0,0", "2,2"])
    assert result.status == "ok"
    assert result.modified == []
    assert any("arc endpoint move not supported" in m for m in ctx.feedback_messages)
    arc = document.get(ids[0])
    assert arc.center == (0.0, 0.0, 0.0)


def test_stretch_empty_window_polite_no_op(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    result = run(make_context(), "stretch", ["50,50", "60,60", "0,0", "1,1"])
    assert result.status == "ok"
    assert "no objects in the crossing window" in result.summary
    assert document.get(ids[0]).p2 == (1.0, 0.0, 0.0)


def test_stretch_one_undo_step(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    depth = document.undo_depth()
    run(make_context(), "stretch", ["8,-1", "12,1", "10,0", "12,0"])
    assert document.undo_depth() == depth + 1
    document.undo()
    assert document.get(ids[0]).p2 == (10.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# MATCHPROP
# ---------------------------------------------------------------------------

def test_matchprop_copies_all_display_properties(run, make_context, document):
    with document.transaction("layers"):
        document.layers.add("Src", color=3, linetype="DASHED", lineweight=0.5)
    source, target = _seed(
        document,
        [Line((0, 0, 0), (1, 0, 0), layer="Src", color=5, linetype="HIDDEN",
              lineweight=0.25),
         Line((0, 1, 0), (1, 1, 0))],
    )
    ctx = make_context()
    result = run(
        ctx, "matchprop", [selection_input([source]), selection_input([target])]
    )
    assert result.status == "ok"
    assert result.modified == [target]
    copied = document.get(target)
    assert copied.layer == "Src"
    assert copied.color == 5
    assert copied.linetype == "HIDDEN"
    assert copied.lineweight == 0.25
    # layers tx + seed tx + ONE matchprop tx
    assert document.undo_depth() == 3


def test_matchprop_missing_layer_auto_created_and_undoable(
    run, make_context, document
):
    # a source entity can live on a layer the table does not know (bcio
    # imports, direct construction): the target update auto-creates it
    source, target = _seed(
        document,
        [Line((0, 0, 0), (1, 0, 0), layer="Ghost", color=5),
         Line((0, 1, 0), (1, 1, 0))],
    )
    assert "Ghost" not in document.layers
    result = run(
        make_context(),
        "matchprop", [selection_input([source]), selection_input([target])],
    )
    assert "Ghost" in document.layers
    assert document.get(target).layer == "Ghost"
    # ONE undo step reverts the property copy AND the auto-created layer
    document.undo()
    assert "Ghost" not in document.layers
    assert document.get(target).layer == "0"


def test_matchprop_locked_target_skipped(run, make_context, document):
    ctx = make_context()
    locked = _add_locked_layer(document)
    source, target = _seed(
        document,
        [Line((0, 0, 0), (1, 0, 0), color=5),
         Line((0, 1, 0), (1, 1, 0), layer=locked)],
    )
    result = run(
        ctx, "matchprop", [selection_input([source]), selection_input([target])]
    )
    assert result.status == "ok"
    assert any("locked layer skipped" in m for m in ctx.feedback_messages)
    assert document.get(target).color is None


# ---------------------------------------------------------------------------
# locked-layer + noun-verb + undo granularity across commands
# ---------------------------------------------------------------------------

def test_move_skips_locked_entities_with_feedback(run, make_context, document):
    ctx = make_context()
    locked = _add_locked_layer(document)
    locked_line, free_line = _seed(
        document,
        [Line((0, 0, 0), (1, 0, 0), layer=locked), Line((0, 1, 0), (1, 1, 0))],
    )
    result = run(
        ctx, "move", [selection_input([locked_line, free_line]), "0,0", "5,5"]
    )
    assert result.status == "ok"
    assert any("locked layer skipped" in m for m in ctx.feedback_messages)
    assert document.get(locked_line).p1 == (0.0, 0.0, 0.0)
    assert document.get(free_line).p1 == (5.0, 6.0, 0.0)


def test_erase_all_locked_reports_no_objects(run, make_context, document):
    ctx = make_context()
    locked = _add_locked_layer(document)
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0), layer=locked)])
    result = run(ctx, "erase", [selection_input(ids)])
    assert "no objects selected" in result.summary
    assert any("locked layer skipped" in m for m in ctx.feedback_messages)
    assert document.count_by_kind() == {"line": 1}


def test_local_split_locked_partitions_like_common_helper(document):
    # the commands_modify twin partitions identically to _common.split_locked
    from bcdraft._common import split_locked
    from bcdraft.commands_modify import _split_locked

    locked = _add_locked_layer(document)
    ids = _seed(
        document,
        [Line((0, 0, 0), (1, 0, 0)),
         Line((0, 1, 0), (1, 1, 0), layer=locked),
         Line((0, 2, 0), (1, 2, 0))],
    )
    stale = ids + ["deadbeef"]
    assert _split_locked(document, stale) == split_locked(document, stale)
    kept, skipped = _split_locked(document, stale)
    assert kept == [ids[0], ids[2]]
    assert skipped == [ids[1]]


def test_noun_verb_preselection_runs_without_selection_prompt(
    run, make_context, document
):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    document.selection.set(ids)
    # no selection input scripted: the preselection feeds the command
    result = run(ctx, "move", ["0,0", "5,5"])
    assert result.status == "ok"
    assert result.modified == ids
    assert any("preselected" in m for m in ctx.feedback_messages)
    assert document.get(ids[0]).p1 == (5.0, 5.0, 0.0)
    assert document.last_selection_ids == ids


def test_noun_verb_preselection_mirror(run, make_context, document):
    ids = _seed(document, [Line((0, 1, 0), (1, 1, 0))])
    document.selection.set(ids)
    result = run(make_context(), "mirror", ["0,0", "1,0", "Y"])
    assert result.modified == ids
    assert document.get(ids[0]).p1 == (0.0, -1.0, 0.0)


def test_one_undo_step_per_command(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (10, 0, 0))])
    depth = document.undo_depth()
    ctx = make_context()
    run(ctx, "move", [selection_input(ids), "0,0", "1,0"])
    run(ctx, "rotate", [selection_input(ids), "0,0", "90"])
    run(ctx, "scale", [selection_input(ids), "0,0", "2"])
    run(ctx, "mirror", [selection_input(ids), "0,0", "10,0", "Y"])
    assert document.undo_depth() == depth + 4
    for _ in range(4):
        assert document.undo()
    line = document.get(ids[0])
    assert line.p1 == (0.0, 0.0, 0.0) and line.p2 == (10.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# transforms on the M2 kinds (MOVE / ROTATE / SCALE dispatch)
# ---------------------------------------------------------------------------

def test_move_rotate_scale_polyline_bulge_invariance(
    run, make_context, document
):
    ids = _seed(document, [Polyline([(0, 0, 0), (10, 0, 0)], bulges=[0.5, 0.0])])
    run(make_context(), "move", [selection_input(ids), "0,0", "3,4"])
    pl = document.get(ids[0])
    assert pl.vertices == ((3.0, 4.0, 0.0), (13.0, 4.0, 0.0))
    assert list(pl.bulges) == [0.5, 0.0]      # bulges are move-invariant
    run(make_context(), "rotate", [selection_input(ids), "0,0", "90"])
    pl = document.get(ids[0])
    assert pl.vertices[0] == pytest.approx((-4.0, 3.0, 0.0))
    assert list(pl.bulges) == [0.5, 0.0]     # ...and rotate-invariant
    run(make_context(), "scale", [selection_input(ids), "0,0", "2"])
    pl = document.get(ids[0])
    assert pl.vertices[0] == pytest.approx((-8.0, 6.0, 0.0))
    assert pl.vertices[1] == pytest.approx((-8.0, 26.0, 0.0))
    assert list(pl.bulges) == [0.5, 0.0]     # ...and uniform-scale-invariant


def test_move_rotate_scale_ellipse_center_and_major_axis(
    run, make_context, document
):
    from bcdoc.entities import Ellipse

    ids = _seed(document, [Ellipse((5, 5, 0), (3, 0, 0), 0.5)])
    run(make_context(), "move", [selection_input(ids), "0,0", "1,2"])
    e = document.get(ids[0])
    assert e.center == (6.0, 7.0, 0.0)
    assert e.major_axis == (3.0, 0.0, 0.0)   # free vector: move keeps it
    assert e.ratio == 0.5
    run(make_context(), "rotate", [selection_input(ids), "0,0", "90"])
    e = document.get(ids[0])
    assert e.center == pytest.approx((-7.0, 6.0, 0.0))
    assert e.major_axis == pytest.approx((0.0, 3.0, 0.0))  # rotates as a vector
    run(make_context(), "scale", [selection_input(ids), "0,0", "2"])
    e = document.get(ids[0])
    assert e.center == pytest.approx((-14.0, 12.0, 0.0))
    assert e.major_axis == pytest.approx((0.0, 6.0, 0.0))  # length scales
    assert e.ratio == 0.5                    # shape invariant


def test_move_rotate_scale_text_position_rotation_height(
    run, make_context, document
):
    ids = _seed(document, [Text((5, 5, 0), height=2.0, rotation=10.0, content="Hi")])
    run(make_context(), "move", [selection_input(ids), "0,0", "1,0"])
    t = document.get(ids[0])
    assert t.position == (6.0, 5.0, 0.0)
    assert t.rotation == 10.0 and t.height == 2.0
    run(make_context(), "rotate", [selection_input(ids), "0,0", "30"])
    t = document.get(ids[0])
    assert t.rotation == pytest.approx(40.0)
    run(make_context(), "scale", [selection_input(ids), "0,0", "2"])
    t = document.get(ids[0])
    assert t.height == pytest.approx(4.0)    # height scales with the factor
    assert t.rotation == pytest.approx(40.0)


def test_move_rotate_scale_insert(run, make_context, document):
    with document.transaction("b"):
        document.add_block("B", (0, 0, 0), [Line((0, 0, 0), (1, 0, 0))])
    with document.transaction("i"):
        iid = document.add_entity(
            Insert("B", (5, 5, 0), scale=(2, 2, 2), rotation=10.0)
        ).id
    run(make_context(), "move", [selection_input([iid]), "0,0", "1,0"])
    ins = document.get(iid)
    assert ins.position == (6.0, 5.0, 0.0)
    assert ins.scale == (2.0, 2.0, 2.0) and ins.rotation == 10.0
    run(make_context(), "rotate", [selection_input([iid]), "0,0", "20"])
    ins = document.get(iid)
    assert ins.rotation == pytest.approx(30.0)
    run(make_context(), "scale", [selection_input([iid]), "0,0", "3"])
    ins = document.get(iid)
    assert ins.scale == (6.0, 6.0, 6.0)      # scale factors multiply
    assert ins.rotation == pytest.approx(30.0)


def test_scale_negative_factor_point_reflection(run, make_context, document):
    """A negative uniform factor is a POINT REFLECTION (|f| scale + 180°
    rotation, orientation-preserving): radii stay positive, arc angles
    rotate by 180° and polyline bulges are invariant."""
    ids = _seed(document, [
        Circle((3, 0, 0), 2),
        Arc((3, 10, 0), 2, 0, 90),
        Line((1, 0, 0), (3, 0, 0)),
        Polyline([(1, -5, 0), (3, -5, 0)], bulges=[0.5, 0.0]),
    ])
    result = run(
        make_context(), "scale", [selection_input(ids), "0,0", "-1"]
    )
    assert result.status == "ok"
    circle, arc, line, pl = (document.get(eid) for eid in ids)
    # circle: center point-reflected, radius stays POSITIVE
    assert circle.center == (-3.0, 0.0, 0.0)
    assert circle.radius == 2.0
    # arc: center + 180°-rotated angles (0->90 becomes 180->270)
    assert arc.center == (-3.0, -10.0, 0.0)
    assert arc.radius == 2.0
    assert arc.start_angle == pytest.approx(180.0)
    assert arc.end_angle == pytest.approx(270.0)
    # line: endpoints through the signed factor
    assert line.p1 == (-1.0, 0.0, 0.0) and line.p2 == (-3.0, 0.0, 0.0)
    # polyline: bulges do NOT flip (rotation, not a mirror)
    assert pl.vertices == ((-1.0, 5.0, 0.0), (-3.0, 5.0, 0.0))
    assert list(pl.bulges) == [0.5, 0.0]


def test_scale_negative_factor_text_rotates_180(run, make_context, document):
    ids = _seed(document, [Text((4, 0, 0), height=2.0, rotation=10.0, content="T")])
    run(make_context(), "scale", [selection_input(ids), "0,0", "-1"])
    t = document.get(ids[0])
    assert t.position == (-4.0, 0.0, 0.0)
    assert t.rotation == pytest.approx(190.0)
    assert t.height == 2.0


def test_move_xline_and_ray(run, make_context, document):
    from bcdoc.entities import Ray, Xline

    ids = _seed(document, [Xline((0, 0, 0), (1, 1, 0)), Ray((0, 0, 0), (1, 1, 0))])
    run(make_context(), "move", [selection_input(ids), "0,0", "1,2"])
    xline, ray = (document.get(eid) for eid in ids)
    assert xline.p1 == (1.0, 2.0, 0.0) and xline.p2 == (2.0, 3.0, 0.0)
    assert ray.p1 == (1.0, 2.0, 0.0) and ray.p2 == (2.0, 3.0, 0.0)
