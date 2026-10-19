"""Modify-command tests through the registry (TP-CAT-01).

ERASE / MOVE / COPY / ROTATE / SCALE driven by ``Registry.run_command`` with
a ScriptedProvider (the exact interface the modal operator and the
acceptance battery use), asserting EXACT geometry on the REAL bcdoc — and
that UNDO restores the pre-command geometry (journaled update_entity path).
"""

import pytest

from bccmd import selection_input


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ids(document, kind=None):
    return [
        e.id for e in document.entities()
        if kind is None or e.kind == kind
    ]


def _draw_line_chain(run, ctx, document):
    """Two committed segments (0,0)-(10,0)-(10,10) for modify tests."""
    result = run(ctx, "line", ["0,0", "10,0", "10,10", ""])
    assert result.status == "ok"
    return _ids(document, "line")


# ---------------------------------------------------------------------------
# ERASE
# ---------------------------------------------------------------------------

def test_erase_removes_selected_ids(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    assert document.count_by_kind() == {"line": 2}

    result = run(ctx, "erase", [selection_input([ids[1]])])
    assert result.status == "ok"
    assert result.removed == [ids[1]]
    assert document.count_by_kind() == {"line": 1}
    assert document.get(ids[0]).p2 == (10.0, 0.0, 0.0)


def test_erase_is_one_undo_step(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    depth_before = document.undo_depth()
    run(ctx, "erase", [selection_input(ids)])
    assert document.undo_depth() == depth_before + 1
    document.undo()
    assert document.count_by_kind() == {"line": 2}


def test_erase_uses_document_preselection(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    document.selection.set([ids[0]])
    result = run(ctx, "erase", [])  # preselection: no selection prompt asked
    assert result.removed == [ids[0]]
    assert any("preselected" in m for m in ctx.feedback_messages)
    # erased ids are dropped from the document selection
    assert ids[0] not in document.selection.ids


def test_erase_enter_ends_selection_politely(run, make_context, document):
    ctx = make_context()
    _draw_line_chain(run, ctx, document)
    result = run(ctx, "erase", [""])
    assert result.status == "ok"
    assert "no objects selected" in result.summary
    assert document.count_by_kind() == {"line": 2}


def test_erase_ignores_stale_and_duplicate_ids(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    result = run(ctx, "erase", [selection_input(["deadbeef", ids[0], ids[0]])])
    assert result.removed == [ids[0]]
    assert document.count_by_kind() == {"line": 1}


# ---------------------------------------------------------------------------
# MOVE (base → second point, in place)
# ---------------------------------------------------------------------------

def test_move_line_by_base_and_second_point(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    result = run(ctx, "move", [selection_input([ids[0]]), "1,1", "4,3"])
    assert result.status == "ok"
    assert result.modified == [ids[0]]
    line = document.get(ids[0])
    assert line.p1 == (3.0, 2.0, 0.0)   # (0,0) + delta (3,2)
    assert line.p2 == (13.0, 2.0, 0.0)
    # the other entity is untouched
    other = document.get(ids[1])
    assert other.p1 == (10.0, 0.0, 0.0)


def test_move_displacement_option(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    run(ctx, "move", [selection_input(ids), "Displacement", "5,-2"])
    seg1, seg2 = (document.get(i) for i in ids)
    assert seg1.p1 == (5.0, -2.0, 0.0)
    assert seg2.p2 == (15.0, 8.0, 0.0)


def test_move_circle_and_arc_geometry(run, make_context, document):
    ctx = make_context()
    run(ctx, "circle", ["10,10", "3"])     # circle c=(10,10) r=3
    run(ctx, "arc", ["C", "20,10", "25,10", "20,15"])  # SCE arc
    circle_id = _ids(document, "circle")[0]
    arc_id = _ids(document, "arc")[0]

    run(ctx, "move", [selection_input([circle_id, arc_id]), "0,0", "1,2"])

    circle = document.get(circle_id)
    assert circle.center == (11.0, 12.0, 0.0)
    assert circle.radius == pytest.approx(3.0)  # move never rescales
    arc = document.get(arc_id)
    assert arc.center == (21.0, 12.0, 0.0)
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(90.0)


def test_move_is_journaled_and_undo_restores_geometry(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    before = document.get(ids[0]).p1
    run(ctx, "move", [selection_input(ids), "0,0", "7,7"])
    assert document.get(ids[0]).p1 == (7.0, 7.0, 0.0)
    document.undo()
    assert document.get(ids[0]).p1 == before


# ---------------------------------------------------------------------------
# COPY (multiple placements; duplicates with new ids/handles)
# ---------------------------------------------------------------------------

def test_copy_two_placements_new_ids_and_handles(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    result = run(ctx, "copy", [selection_input(ids), "0,0", "5,0", "10,0", ""])
    assert result.status == "ok"
    assert len(result.created) == 4  # 2 entities × 2 placements
    assert document.count_by_kind() == {"line": 6}
    # duplicates are real new entities: distinct ids, fresh monotonic handles
    all_lines = document.entities()
    handles = [e.handle for e in all_lines]
    assert len(set(handles)) == 6
    assert len(set(e.id for e in all_lines)) == 6
    # exact geometry of the +10 placement
    last_two = {document.get(eid).p1[0] for eid in result.created[2:]}
    assert last_two == {10.0, 20.0}


def test_copy_undo_option_pops_last_placement(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    result = run(ctx, "copy", [selection_input(ids), "0,0", "5,0", "U", "8,0", ""])
    assert result.status == "ok"
    assert len(result.created) == 2  # only the +8 placement survived
    assert document.count_by_kind() == {"line": 4}
    xs = sorted(document.get(eid).p1[0] for eid in result.created)
    assert xs == [8.0, 18.0]


def test_copy_exit_with_no_placements(run, make_context, document):
    ctx = make_context()
    _draw_line_chain(run, ctx, document)
    result = run(ctx, "copy", [selection_input(document.selection.ids or _ids(document)), "0,0", ""])
    assert result.status == "ok"
    assert "no placements" in result.summary


def test_copy_keeps_source_properties(run, make_context, document):
    from bcdoc.entities import Line

    ctx = make_context()
    with document.transaction("seed"):
        document.add_entity(Line((0, 0, 0), (1, 0, 0), layer="Walls", color=5))
    seed = _ids(document)[0]
    result = run(ctx, "copy", [selection_input([seed]), "0,0", "2,0", ""])
    clone = document.get(result.created[0])
    assert clone.layer == "Walls"
    assert clone.color == 5
    assert clone.linetype == "ByLayer"


# ---------------------------------------------------------------------------
# ROTATE (base point + angle, CCW about +Z)
# ---------------------------------------------------------------------------

def test_rotate_line_90_ccw_about_base(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)  # (0,0)-(10,0)-(10,10)
    result = run(ctx, "rotate", [selection_input(ids), "0,0", "90"])
    assert result.status == "ok"
    seg1, seg2 = (document.get(i) for i in ids)
    assert seg1.p1 == pytest.approx((0.0, 0.0, 0.0))
    assert seg1.p2 == pytest.approx((0.0, 10.0, 0.0))
    assert seg2.p1 == pytest.approx((0.0, 10.0, 0.0))
    assert seg2.p2 == pytest.approx((-10.0, 10.0, 0.0))


def test_rotate_about_offorigin_base_point(run, make_context, document):
    ctx = make_context()
    run(ctx, "circle", ["10,10", "1"])
    cid = _ids(document, "circle")[0]
    run(ctx, "rotate", [selection_input([cid]), "10,10", "180"])
    assert document.get(cid).center == pytest.approx((10.0, 10.0, 0.0))
    assert document.get(cid).radius == pytest.approx(1.0)


def test_rotate_arc_shifts_angles(run, make_context, document):
    ctx = make_context()
    run(ctx, "arc", ["C", "0,0", "5,0", "0,5"])  # arc 0°→90°
    aid = _ids(document, "arc")[0]
    run(ctx, "rotate", [selection_input([aid]), "0,0", "45"])
    arc = document.get(aid)
    assert arc.start_angle == pytest.approx(45.0)
    assert arc.end_angle == pytest.approx(135.0)


def test_rotate_undo_restores_geometry_and_angles(run, make_context, document):
    ctx = make_context()
    run(ctx, "arc", ["C", "0,0", "5,0", "0,5"])
    aid = _ids(document, "arc")[0]
    run(ctx, "rotate", [selection_input([aid]), "0,0", "30"])
    document.undo()
    arc = document.get(aid)
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# SCALE (base point + factor; [Reference] length ratio)
# ---------------------------------------------------------------------------

def test_scale_line_by_factor_about_base(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    result = run(ctx, "scale", [selection_input(ids), "0,0", "2"])
    assert result.status == "ok"
    seg1, seg2 = (document.get(i) for i in ids)
    assert seg1.p2 == (20.0, 0.0, 0.0)
    assert seg2.p2 == (20.0, 20.0, 0.0)


def test_scale_circle_scales_radius_and_moves_center(run, make_context, document):
    ctx = make_context()
    run(ctx, "circle", ["3,0", "1"])  # c=(3,0) r=1
    cid = _ids(document, "circle")[0]
    run(ctx, "scale", [selection_input([cid]), "0,0", "2"])
    circle = document.get(cid)
    assert circle.center == (6.0, 0.0, 0.0)
    assert circle.radius == pytest.approx(2.0)


def test_scale_reference_length_ratio(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    # reference length 2 → new length 6 ⇒ factor 3
    run(ctx, "scale", [selection_input(ids), "0,0", "R", "2", "6"])
    assert document.get(ids[0]).p2 == (30.0, 0.0, 0.0)


def test_scale_zero_factor_reprompts(run, make_context, document):
    ctx = make_context()
    ids = _draw_line_chain(run, ctx, document)
    run(ctx, "scale", [selection_input(ids), "0,0", "0", "0.5"])
    assert document.get(ids[0]).p2 == (5.0, 0.0, 0.0)
    assert any("non-zero" in m for m in ctx.feedback_messages)
