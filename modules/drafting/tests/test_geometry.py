"""Analytic geometry tests for bcdraft.geometry (TP-CAT-01, geometry side).

Numerical correctness of the helpers the commands are built on: angles,
circles through three points, the CCW arc convention and the transform
change-computors (W2 co-owns drafting geometry-side tests per glossary §10).
"""

import math

import pytest

from bcdraft import geometry


# ---------------------------------------------------------------------------
# angle / normalization helpers
# ---------------------------------------------------------------------------

def test_normalize_deg_wraps_into_0_360():
    assert geometry.normalize_deg(0.0) == 0.0
    assert geometry.normalize_deg(90.0) == 90.0
    assert geometry.normalize_deg(-90.0) == 270.0
    assert geometry.normalize_deg(360.0) == 0.0
    assert geometry.normalize_deg(450.0) == 90.0
    assert geometry.normalize_deg(-720.5) == pytest.approx(359.5)


def test_angle_of_is_ccw_from_plus_x():
    assert geometry.angle_of((1.0, 0.0)) == 0.0
    assert geometry.angle_of((0.0, 1.0)) == 90.0
    assert geometry.angle_of((-1.0, 0.0)) == 180.0
    assert geometry.angle_of((0.0, -1.0)) == 270.0
    assert geometry.angle_of((1.0, 1.0)) == pytest.approx(45.0)


def test_dist_2d_and_3d():
    assert geometry.dist_2d((0, 0, 9), (3, 4, 9)) == pytest.approx(5.0)
    assert geometry.dist_3d((0, 0, 0), (3, 4, 12)) == pytest.approx(13.0)


# ---------------------------------------------------------------------------
# circle through 3 points / arc from 3 points
# ---------------------------------------------------------------------------

def test_circumcenter_circle_through_origin_axes():
    center, radius = geometry.circumcenter((-1, 0, 0), (0, 1, 0), (1, 0, 0))
    assert center == pytest.approx((0.0, 0.0, 0.0))
    assert radius == pytest.approx(1.0)


def test_circumcenter_collinear_returns_none():
    assert geometry.circumcenter((0, 0, 0), (1, 0, 0), (2, 0, 0)) is None


def test_arc_from_3p_ccw_sweep_passes_through_mid():
    # points on the circle c=(10,10) r=10: start 0°, mid 90°, end 180°
    center, radius, a0, a1 = geometry.arc_from_3p(
        (20, 10, 0), (10, 20, 0), (0, 10, 0)
    )
    assert center == pytest.approx((10.0, 10.0, 0.0))
    assert radius == pytest.approx(10.0)
    assert a0 == pytest.approx(0.0)
    assert a1 == pytest.approx(180.0)


def test_arc_from_3p_other_sweep_represented_ccw_from_end():
    # start 180°, mid 90°, end 0° — CCW start→end would miss mid, so the
    # arc is represented CCW from end to start (sweep through the top).
    center, radius, a0, a1 = geometry.arc_from_3p(
        (0, 10, 0), (10, 20, 0), (20, 10, 0)
    )
    assert a0 == pytest.approx(0.0)
    assert a1 == pytest.approx(180.0)
    # and the midpoint of the stored arc lies on the picked mid point
    points = geometry.arc_points(center, radius, a0, a1)
    assert any(
        math.hypot(p[0] - 10, p[1] - 20) < 0.1 for p in points
    )


def test_arc_points_endpoints_on_circle_and_cover_sweep():
    pts = geometry.arc_points((0, 0, 0), 2.0, 90.0, 180.0, segments=16)
    assert len(pts) == 17
    first, last = pts[0], pts[-1]
    assert first == pytest.approx((0.0, 2.0, 0.0))
    assert last == pytest.approx((-2.0, 0.0, 0.0))
    for p in pts:
        assert math.hypot(p[0], p[1]) == pytest.approx(2.0, abs=1e-9)


def test_circle_points_is_cyclic_ring():
    pts = geometry.circle_points((0, 0, 0), 1.0, segments=4)
    assert len(pts) == 4
    for p in pts:
        assert math.hypot(p[0], p[1]) == pytest.approx(1.0)
    # first point sits at angle 0, going CCW
    assert pts[0] == pytest.approx((1.0, 0.0, 0.0))
    assert pts[1] == pytest.approx((0.0, 1.0, 0.0))


# ---------------------------------------------------------------------------
# point transforms
# ---------------------------------------------------------------------------

def test_move_pt_translates_all_axes():
    assert geometry.move_pt((1, 2, 3), (10, 20, 30)) == (11, 22, 33)


def test_rotate_pt_90_ccw_about_origin():
    p = geometry.rotate_pt((10, 0, 5), (0, 0, 0), 90.0)
    assert p[0] == pytest.approx(0.0, abs=1e-9)
    assert p[1] == pytest.approx(10.0)
    assert p[2] == pytest.approx(5.0)  # z untouched (planar rotation)


def test_rotate_pt_about_offorigin_center():
    p = geometry.rotate_pt((12, 10, 0), (10, 10, 0), -90.0)
    assert p == pytest.approx((10.0, 8.0, 0.0))


def test_scale_pt_about_center():
    assert geometry.scale_pt((10, 10, 0), (0, 0, 0), 2.0) == (20, 20, 0)
    assert geometry.scale_pt((12, 10, 0), (10, 10, 0), 0.5) == (11, 10, 0)


# ---------------------------------------------------------------------------
# entity change-computors (the journaled-transform path commands use)
# ---------------------------------------------------------------------------

def test_move_changes_per_kind():
    from bcdoc.entities import Arc, Circle, Line

    line = Line((0, 0, 0), (1, 0, 0))
    changes = geometry.move_changes(line, (2, 3, 0))
    assert changes == {"p1": (2.0, 3.0, 0.0), "p2": (3.0, 3.0, 0.0)}

    circle = Circle((1, 1, 0), 5)
    assert geometry.move_changes(circle, (1, 0, 0)) == {"center": (2.0, 1.0, 0.0)}

    arc = Arc((0, 0, 0), 2, 10, 90)
    assert geometry.move_changes(arc, (0, 0, 1)) == {"center": (0.0, 0.0, 1.0)}
    # angles never change on a move
    assert arc.start_angle == 10 and arc.end_angle == 90


def test_rotate_changes_arc_shifts_angles_and_normalizes():
    from bcdoc.entities import Arc

    arc = Arc((1, 1, 0), 2, 350, 10)
    changes = geometry.rotate_changes(arc, (0, 0, 0), 30.0)
    assert changes["start_angle"] == pytest.approx(20.0)
    assert changes["end_angle"] == pytest.approx(40.0)
    # center (1,1) rotated 30° CCW about the origin: (cos30-sin30, sin30+cos30)
    assert changes["center"][0] == pytest.approx(0.3660254, abs=1e-6)
    assert changes["center"][1] == pytest.approx(1.3660254, abs=1e-6)


def test_scale_changes_circle_scales_radius_and_center():
    from bcdoc.entities import Circle

    circle = Circle((2, 0, 0), 1.5)
    changes = geometry.scale_changes(circle, (0, 0, 0), 3.0)
    assert changes["center"] == (6.0, 0.0, 0.0)
    assert changes["radius"] == pytest.approx(4.5)


def test_unsupported_kind_raises():
    class Fake:
        kind = "lwpolyline"

    with pytest.raises(ValueError):
        geometry.move_changes(Fake(), (0, 0, 0))
    with pytest.raises(ValueError):
        geometry.rotate_changes(Fake(), (0, 0, 0), 10.0)
    with pytest.raises(ValueError):
        geometry.scale_changes(Fake(), (0, 0, 0), 2.0)
    with pytest.raises(ValueError):
        geometry.clone_moved(Fake(), (0, 0, 0))


def test_clone_moved_keeps_properties_and_geometry():
    from bcdoc.entities import Line

    source = Line((0, 0, 0), (5, 0, 0), layer=" Walls ", color=3, linetype="DASHED")
    clone = geometry.clone_moved(source, (1, 1, 1))
    assert clone is not source
    assert clone.id != source.id  # fresh identity
    assert clone.handle == 0      # assigned by Document.add_entity
    assert clone.p1 == (1.0, 1.0, 1.0)
    assert clone.p2 == (6.0, 1.0, 1.0)
    assert clone.layer == " Walls " and clone.color == 3
    assert clone.linetype == "DASHED"
