"""Pure-helper tests for bcshell (TP-CAT-01) — no Blender needed.

Covers the headless-testable core of the shell package:

* ``pick.ray_plane_z0`` / ``pick.dynamic_readout`` — viewport-pick math;
* ``sync.entity_display_spec`` — the pure document→display description
  (contract §6.2 mapping: line → polyline, circle → cyclic 4-point curve,
  arc → sampled non-cyclic polyline);
* ``session`` feedback ring + status snapshot;
* the lazy-bpy import discipline (bpy never enters sys.modules here).
"""

import math

import pytest

import bcshell.pick as pick
import bcshell.session as session
import bcshell.sync as sync


# ---------------------------------------------------------------------------
# pick.ray_plane_z0 — ray ∩ z=0 (the CAD drawing plane)
# ---------------------------------------------------------------------------

def test_ray_hits_plane_straight_down():
    assert pick.ray_plane_z0((1.0, 2.0, 5.0), (0.0, 0.0, -1.0)) == (1.0, 2.0)


def test_ray_hits_plane_oblique():
    hit = pick.ray_plane_z0((0.0, 0.0, 1.0), (1.0, 1.0, -1.0))
    assert hit == pytest.approx((1.0, 1.0))


def test_parallel_ray_never_hits():
    assert pick.ray_plane_z0((3.0, 3.0, 7.0), (1.0, 0.0, 0.0)) is None
    assert pick.ray_plane_z0((3.0, 3.0, 7.0), (0.0, 1.0, 0.0)) is None


def test_intersection_behind_viewer_is_none():
    # the plane lies BEHIND the ray origin along its direction (t < 0)
    assert pick.ray_plane_z0((0.0, 0.0, 5.0), (0.0, 0.0, 1.0)) is None


def test_ray_from_below_hits():
    assert pick.ray_plane_z0((2.0, -1.0, -3.0), (0.0, 0.0, 1.0)) == (2.0, -1.0)


# ---------------------------------------------------------------------------
# pick.dynamic_readout — the "<distance> <angle>" live overlay
# ---------------------------------------------------------------------------

def test_dynamic_readout_distance_and_angle():
    text = pick.dynamic_readout((0.0, 0.0, 0.0), (3.0, 4.0, 0.0))
    assert text == "5.000 < 53.1\u00b0"


def test_dynamic_readout_angle_wraps_to_0_360():
    assert pick.dynamic_readout((0, 0, 0), (1.0, 0.0, 0.0)).endswith("< 0.0\u00b0")
    assert pick.dynamic_readout((0, 0, 0), (0.0, -1.0, 0.0)).endswith("< 270.0\u00b0")


def test_dynamic_readout_without_anchor_is_empty():
    assert pick.dynamic_readout(None, (1.0, 2.0, 0.0)) == ""
    assert pick.dynamic_readout((0, 0, 0), None) == ""


def test_dynamic_readout_coincident_points():
    assert pick.dynamic_readout((1.0, 1.0, 0.0), (1.0, 1.0, 0.0)) == "0.000 < 0\u00b0"


# ---------------------------------------------------------------------------
# sync.entity_display_spec — the pure document→display mapping (contract §6.2)
# ---------------------------------------------------------------------------

def _line():
    from bcdoc.entities import Line

    return Line((1.0, 2.0, 0.0), (5.0, 7.0, 0.0))


def _circle():
    from bcdoc.entities import Circle

    return Circle((10.0, 20.0, 0.0), 4.0)


def _arc():
    from bcdoc.entities import Arc

    return Arc((0.0, 0.0, 0.0), 2.0, 0.0, 90.0)


def test_display_spec_line_two_point_polyline():
    spec = sync.entity_display_spec(_line())
    assert spec["kind"] == "line"
    assert spec["points"] == [(1.0, 2.0, 0.0), (5.0, 7.0, 0.0)]
    assert spec["cyclic"] is False
    assert spec["bcdoc_id"] == spec["bcdoc_id"]
    assert "BC_Line_" in spec["name"]


def test_display_spec_circle_cyclic_four_points():
    spec = sync.entity_display_spec(_circle())
    assert spec["cyclic"] is True
    assert len(spec["points"]) == 4
    # the four cardinal samples sit ON the circle at 0/90/180/270°
    for point in spec["points"]:
        assert math.hypot(point[0] - 10.0, point[1] - 20.0) == pytest.approx(4.0)


def test_display_spec_arc_non_cyclic_sampled_sweep():
    spec = sync.entity_display_spec(_arc())
    assert spec["cyclic"] is False
    points = spec["points"]
    assert len(points) == sync.ARC_SEGMENTS + 1
    # CCW 0°→90° about the origin, radius 2: first/last samples exact
    assert points[0] == pytest.approx((2.0, 0.0, 0.0))
    assert points[-1] == pytest.approx((0.0, 2.0, 0.0))
    for point in points:
        assert math.hypot(point[0], point[1]) == pytest.approx(2.0)


def test_display_spec_carries_entity_id_and_handle_name():
    entity = _circle()
    spec = sync.entity_display_spec(entity)
    assert spec["bcdoc_id"] == entity.id
    assert str(entity.handle) in spec["name"]


def test_display_spec_unknown_kind_raises():
    class Fake:
        kind = "polyline"

    with pytest.raises(ValueError):
        sync.entity_display_spec(Fake())


def test_display_collection_constants_match_contract():
    assert sync.COLLECTION_NAME == "BlenderCAD"
    assert sync.ID_PROP == "bcdoc_id"


# ---------------------------------------------------------------------------
# session — feedback ring + status snapshot (bpy-free)
# ---------------------------------------------------------------------------

def test_feedback_ring_is_bounded(shell_session):
    for i in range(session.FEEDBACK_LIMIT + 25):
        session.feedback_sink(f"msg {i}")
    assert len(session.feedback_messages(1000)) == session.FEEDBACK_LIMIT
    tail = session.feedback_messages(2)
    assert tail[-1] == f"msg {session.FEEDBACK_LIMIT + 24}"


def test_status_without_document(shell_session):
    info = session.status()
    assert info["registered_document"] is False
    assert info["prompt"] == "Command:"
    assert "doc_version" not in info


def test_status_with_document(shell_session):
    doc = session.active_document()
    with doc.transaction("t"):
        from bcdoc.entities import Line

        doc.add_entity(Line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    info = session.status()
    assert info["registered_document"] is True
    assert info["doc_version"] == 1
    assert info["entities"] == 1
    assert info["counts"] == {"line": 1}
    assert info["undo_depth"] == 1
    assert info["redo_depth"] == 0
