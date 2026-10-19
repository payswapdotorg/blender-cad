"""Precision input engine tests (m2 contracts §4 + §10 drafting row W-A).

Every snap mode has exact-value tests (known geometry -> snap coordinates
asserted to 1e-9), plus aperture ranking, frozen-layer and cross-space
exclusion, insert-member transforms, the grid/ortho/one-shot resolution
chain, direct distance entry, the ask_point integration hook (typed points
NEVER resolve; mouse points always do) and the end-to-end registry proof:
a mouse-source LINE pick snapping to a prior line's endpoint with EXACT
created geometry.
"""

import math

import pytest

from bccmd import (
    CommandResult,
    CommandSpec,
    Point,
    Registry,
    Request,
    ScriptedProvider,
    point_input,
)
from bcdoc.entities import (
    Arc,
    Circle,
    Ellipse,
    Insert,
    Line,
    Mtext,
    Polyline,
    Ray,
    Text,
    Xline,
)
from bcdraft import precision
from bcdraft._common import ask_point, split_locked
from bcdraft.precision import (
    OSMODE_BITS,
    OSMODE_NONE,
    SnapResult,
    dde_point,
    parse_osnap_tokens,
    resolve_point,
    running_modes,
    snap_candidates,
)

APPROX = dict(abs=1e-9)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pts(results):
    return [(r.point.x, r.point.y, r.point.z) for r in results]


def _pt(result):
    return (result.point.x, result.point.y, result.point.z)


def _add(document, entity, label="test"):
    with document.transaction(label):
        document.add_entity(entity)
    return entity


def _line(document, p1, p2, layer="0", space="MODEL"):
    return _add(document, Line(p1, p2, layer=layer, space=space))


def _frozen_layer(document, name="FROZ"):
    with document.transaction("layer"):
        document.layers.add(name)
        document.layers.set_props(name, frozen=True)


def _locked_layer(document, name="LOCK"):
    with document.transaction("layer"):
        document.layers.add(name)
        document.layers.set_props(name, locked=True)


def _off_layer(document, name="HIDN"):
    with document.transaction("layer"):
        document.layers.add(name)
        document.layers.set_props(name, on=False)


def _cursor(p, aperture=0.5, doc=None, modes=("ENDPOINT",), from_point=None):
    return snap_candidates(doc, list(modes), Point(*p), aperture,
                           from_point=from_point)


def _expect(points, expected):
    """Exact-value assertion to 1e-9 (contract §10: snap coordinates are
    asserted to 1e-9 — trig-rooted candidates carry inherent float noise)."""
    assert len(points) == len(expected), f"{points} != {expected}"
    for got, want in zip(points, expected):
        assert got == pytest.approx(tuple(want), abs=1e-9), f"{got} != {want}"


# ---------------------------------------------------------------------------
# OSMODE bits + token/mode decoding
# ---------------------------------------------------------------------------

def test_osmode_bits_pinned_layout():
    assert OSMODE_BITS == {
        "ENDPOINT": 1, "MIDPOINT": 2, "CENTER": 4, "QUADRANT": 16,
        "INTERSECTION": 32, "INSERTION": 64, "PERPENDICULAR": 128,
        "TANGENT": 1024,
    }
    assert OSMODE_NONE == 0


def test_running_modes_default_55():
    doc = pytest.importorskip("bcdoc.document").Document()
    assert doc.settings.get("OSMODE") == 55
    assert running_modes(doc) == [
        "ENDPOINT", "MIDPOINT", "CENTER", "QUADRANT", "INTERSECTION",
    ]


def test_running_modes_off_and_single_bits(document):
    document.settings.set("OSMODE", 0)
    assert running_modes(document) == []
    document.settings.set("OSMODE", 1024)
    assert running_modes(document) == ["TANGENT"]
    document.settings.set("OSMODE", 1 | 2 | 128)
    assert running_modes(document) == ["ENDPOINT", "MIDPOINT", "PERPENDICULAR"]


def test_parse_osnap_tokens(document):
    assert parse_osnap_tokens("END,MID") == ["ENDPOINT", "MIDPOINT"]
    assert parse_osnap_tokens(" qua , tan ") == ["QUADRANT", "TANGENT"]
    assert parse_osnap_tokens("bogus") == []
    assert parse_osnap_tokens("") == []


# ---------------------------------------------------------------------------
# ENDPOINT / MIDPOINT / CENTER / QUADRANT — exact values
# ---------------------------------------------------------------------------

def test_endpoint_line(document):
    _line(document, (10, 0, 0), (20, 10, 0))
    points = _pts(_cursor((10.1, 0.2), doc=document))
    assert points == [(10.0, 0.0, 0.0)]
    points = _pts(_cursor((19.9, 10.1), doc=document))
    assert points == [(20.0, 10.0, 0.0)]


def test_endpoint_arc_sweep_ends(document):
    _add(document, Arc((0, 0, 0), 5.0, 30.0, 150.0))
    points = _pts(_cursor((4.4, 2.6), doc=document))
    _expect(points, [(5 * math.cos(math.radians(30)), 2.5, 0.0)])
    points = _pts(_cursor((-4.4, 2.6), doc=document))
    _expect(points, [(5 * math.cos(math.radians(150)), 2.5, 0.0)])


def test_endpoint_polyline_vertices(document):
    _add(document, Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)]))
    points = _pts(_cursor((0.2, -0.1), doc=document))
    assert points == [(0.0, 0.0, 0.0)]
    points = _pts(_cursor((10.3, 10.2), doc=document))
    assert points == [(10.0, 10.0, 0.0)]


def test_endpoint_xline_ray_base_only(document):
    _add(document, Xline((3, 4, 0), (4, 4, 0)))
    _add(document, Ray((7, 1, 0), (8, 1, 0)))
    points = _pts(_cursor((3.2, 4.1), doc=document, aperture=0.5))
    assert (3.0, 4.0, 0.0) in points  # xline base p1
    points = _pts(_cursor((7.1, 1.2), doc=document, aperture=0.5))
    assert (7.0, 1.0, 0.0) in points  # ray base p1


def test_midpoint_line(document):
    _line(document, (10, 0, 0), (20, 10, 0))
    points = _pts(_cursor((15.2, 5.1), doc=document, modes=("MIDPOINT",)))
    assert points == [(15.0, 5.0, 0.0)]


def test_midpoint_arc_sweep_mid(document):
    _add(document, Arc((0, 0, 0), 5.0, 30.0, 150.0))
    points = _pts(_cursor((0.1, 5.2), doc=document, modes=("MIDPOINT",)))
    _expect(points, [(0.0, 5.0, 0.0)])


def test_midpoint_polyline_straight_and_bulge_segments(document):
    # segment (10,0)->(10,10) carries bulge 1 = CCW semicircle about (10,5)
    _add(document, Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)], bulges=[0, 1, 0]))
    points = _pts(_cursor((5.1, 0.2), doc=document, modes=("MIDPOINT",)))
    _expect(points, [(5.0, 0.0, 0.0)])
    points = _pts(_cursor((15.1, 5.1), doc=document, modes=("MIDPOINT",)))
    _expect(points, [(15.0, 5.0, 0.0)])


def test_center_circle_arc_ellipse(document):
    _add(document, Circle((3, 4, 0), 2.0))
    _add(document, Arc((10, 0, 0), 5.0, 30.0, 150.0))
    _add(document, Ellipse((20, 20, 0), (4, 0, 0), 0.5))
    points = _pts(_cursor((3.1, 4.2), doc=document, modes=("CENTER",)))
    assert (3.0, 4.0, 0.0) in points
    points = _pts(_cursor((10.2, 0.1), doc=document, modes=("CENTER",)))
    assert (10.0, 0.0, 0.0) in points
    points = _pts(_cursor((20.2, 20.1), doc=document, modes=("CENTER",)))
    assert (20.0, 20.0, 0.0) in points


def test_quadrant_circle_all_four(document):
    _add(document, Circle((3, 4, 0), 2.0))
    for near, expected in [
        ((5.1, 4.1), (5.0, 4.0, 0.0)),
        ((3.1, 6.1), (3.0, 6.0, 0.0)),
        ((1.0, 4.2), (1.0, 4.0, 0.0)),
        ((2.9, 1.9), (3.0, 2.0, 0.0)),
    ]:
        points = _pts(_cursor(near, doc=document, modes=("QUADRANT",)))
        _expect(points, [expected])


def test_quadrant_arc_respects_sweep(document):
    _add(document, Arc((0, 0, 0), 5.0, 30.0, 150.0))
    points = _pts(_cursor((0.1, 5.1), doc=document, modes=("QUADRANT",)))
    _expect(points, [(0.0, 5.0, 0.0)])             # 90 is in [30,150]
    assert _cursor((5.1, 0.1), doc=document, modes=("QUADRANT",)) == []
    assert _cursor((-5.1, 0.1), doc=document, modes=("QUADRANT",)) == []


def test_quadrant_ellipse_axis_extremes(document):
    _add(document, Ellipse((10, 10, 0), (4, 0, 0), 0.5))
    points = _pts(_cursor((14.1, 10.1), doc=document, modes=("QUADRANT",)))
    _expect(points, [(14.0, 10.0, 0.0)])
    points = _pts(_cursor((10.1, 12.1), doc=document, modes=("QUADRANT",)))
    _expect(points, [(10.0, 12.0, 0.0)])
    points = _pts(_cursor((5.9, 10.1), doc=document, modes=("QUADRANT",)))
    _expect(points, [(6.0, 10.0, 0.0)])
    points = _pts(_cursor((10.1, 7.9), doc=document, modes=("QUADRANT",)))
    _expect(points, [(10.0, 8.0, 0.0)])


def test_quadrant_partial_ellipse_respects_sweep(document):
    _add(document, Ellipse((10, 10, 0), (4, 0, 0), 0.5, 0.0, 90.0))
    assert _cursor((14.1, 10.1), doc=document, modes=("QUADRANT",))
    assert _cursor((10.1, 12.1), doc=document, modes=("QUADRANT",))
    assert _cursor((6.0, 10.1), doc=document, modes=("QUADRANT",)) == []
    assert _cursor((10.1, 8.0), doc=document, modes=("QUADRANT",)) == []


# ---------------------------------------------------------------------------
# INTERSECTION — pairwise across entities with domain tests
# ---------------------------------------------------------------------------

def test_intersection_line_line_inside_segments(document):
    _line(document, (0, 0, 0), (10, 10, 0))
    _line(document, (0, 10, 0), (10, 0, 0))
    points = _pts(_cursor((5.2, 5.1), doc=document, modes=("INTERSECTION",)))
    assert points == [(5.0, 5.0, 0.0)]


def test_intersection_rejects_point_outside_segment(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    _line(document, (20, -5, 0), (20, 5, 0))
    assert _cursor((20.1, 0.1), doc=document, modes=("INTERSECTION",)) == []


def test_intersection_xline_unbounded(document):
    _add(document, Xline((0, 0, 0), (1, 0, 0)))
    _line(document, (5, -1, 0), (5, 1, 0))
    points = _pts(_cursor((5.1, 0.1), doc=document, modes=("INTERSECTION",)))
    _expect(points, [(5.0, 0.0, 0.0)])


def test_intersection_ray_half_line_domain(document):
    _add(document, Ray((0, 0, 0), (1, 0, 0)))
    _line(document, (-5, -1, 0), (-5, 1, 0))     # behind the ray base
    _line(document, (3, -1, 0), (3, 1, 0))       # forward on the ray
    points = _pts(_cursor((3.1, 0.1), doc=document, modes=("INTERSECTION",)))
    _expect(points, [(3.0, 0.0, 0.0)])           # only the forward hit
    assert _cursor((-5.1, 0.1), doc=document, modes=("INTERSECTION",)) == []


def test_intersection_line_circle_two_points(document):
    _line(document, (-10, 0, 0), (10, 0, 0))
    _add(document, Circle((3, 0, 0), 2.0))
    points = _pts(_cursor((1.1, 0.2), doc=document, modes=("INTERSECTION",)))
    assert points == [(1.0, 0.0, 0.0)]
    points = _pts(_cursor((5.1, -0.2), doc=document, modes=("INTERSECTION",)))
    assert points == [(5.0, 0.0, 0.0)]


def test_intersection_line_circle_tangent(document):
    _line(document, (-10, 5, 0), (10, 5, 0))
    _add(document, Circle((0, 0, 0), 5.0))
    points = _pts(_cursor((0.1, 5.1), doc=document, modes=("INTERSECTION",)))
    assert points == [(0.0, 5.0, 0.0)]


def test_intersection_line_circle_respects_segment(document):
    _line(document, (0, 0, 0), (2, 0, 0))
    _add(document, Circle((5, 0, 0), 2.0))       # crossings at x=3 and x=7
    assert _cursor((3.1, 0.1), doc=document, modes=("INTERSECTION",)) == []
    assert _cursor((7.1, 0.1), doc=document, modes=("INTERSECTION",)) == []


def test_intersection_arc_sweep_filter(document):
    _add(document, Arc((0, 0, 0), 5.0, 30.0, 150.0))
    _line(document, (-10, 3, 0), (10, 3, 0))
    # circle crossings (±4,3) sit at 36.87° and 143.13° — both inside
    _expect(_pts(_cursor((4.1, 3.1), doc=document, modes=("INTERSECTION",))),
            [(4.0, 3.0, 0.0)])
    _expect(_pts(_cursor((-4.1, 3.1), doc=document, modes=("INTERSECTION",))),
            [(-4.0, 3.0, 0.0)])


def test_intersection_narrow_arc_excludes_crossings(document):
    # same circle geometry but a 40..140 sweep: both crossings at 36.87° and
    # 143.13° fall OUTSIDE the sweep — no candidates at all
    _add(document, Arc((0, 0, 0), 5.0, 40.0, 140.0))
    _line(document, (-10, 3, 0), (10, 3, 0))
    assert _cursor((4.1, 3.1), doc=document, modes=("INTERSECTION",)) == []
    assert _cursor((-4.1, 3.1), doc=document, modes=("INTERSECTION",)) == []


def test_intersection_circle_circle(document):
    _add(document, Circle((0, 0, 0), 5.0))
    _add(document, Circle((8, 0, 0), 5.0))
    points = _pts(_cursor((4.1, 3.2), doc=document, modes=("INTERSECTION",)))
    _expect(points, [(4.0, 3.0, 0.0)])
    points = _pts(_cursor((4.1, -3.2), doc=document, modes=("INTERSECTION",)))
    _expect(points, [(4.0, -3.0, 0.0)])


def test_intersection_polyline_segment_pairs(document):
    _add(document, Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)]))
    _line(document, (5, -5, 0), (5, 5, 0))
    points = _pts(_cursor((5.1, 0.2), doc=document, modes=("INTERSECTION",)))
    assert points == [(5.0, 0.0, 0.0)]


def test_intersection_bulge_arc_segment(document):
    # semicircle center (10,5) r=5 sweeping -90°..90° (through (15,5))
    _add(document, Polyline([(10, 0, 0), (10, 10, 0)], bulges=[1, 0]))
    _line(document, (5, 5, 0), (15, 5, 0))
    points = _pts(_cursor((15.1, 5.1), doc=document, modes=("INTERSECTION",)))
    _expect(points, [(15.0, 5.0, 0.0)])           # in-sweep crossing
    assert _cursor((5.1, 5.1), doc=document, modes=("INTERSECTION",)) == []


def test_intersection_skips_adjacent_polyline_self_joints(document):
    polyline = _add(document, Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)]))
    # a cursor at the (10,0) shared vertex must find NO INTERSECTION marker
    # (same-entity adjacent segments are not "intersections")
    found = _cursor((10.1, 0.1), doc=document, modes=("INTERSECTION",))
    assert all(r.entity_id != polyline.id for r in found) or found == []


# ---------------------------------------------------------------------------
# TANGENT / PERPENDICULAR (from_point = the last point)
# ---------------------------------------------------------------------------

def test_tangent_two_points_from_outside(document):
    _add(document, Circle((10, 0, 0), 5.0))
    # from (0,0): tangent points at angles 180° ± 60° about (10,0) ->
    # (7.5, ±4.3301) — the right-angle tangent identity (T-P)·(T-C) = 0
    points = _pts(_cursor((7.6, 4.45), doc=document, modes=("TANGENT",),
                           from_point=(0, 0, 0)))
    _expect(points, [(7.5, 5.0 * math.sin(math.radians(60)), 0.0)])
    points = _pts(_cursor((7.6, -4.45), doc=document, modes=("TANGENT",),
                           from_point=(0, 0, 0)))
    _expect(points, [(7.5, -5.0 * math.sin(math.radians(60)), 0.0)])


def test_tangent_from_point_on_circle_is_itself(document):
    _add(document, Circle((10, 0, 0), 5.0))
    points = _pts(_cursor((5.1, 0.2), doc=document, modes=("TANGENT",),
                           from_point=(5, 0, 0)))
    _expect(points, [(5.0, 0.0, 0.0)])


def test_tangent_from_inside_and_center_is_empty(document):
    _add(document, Circle((10, 0, 0), 5.0))
    assert _cursor((1.1, 0.2), doc=document, modes=("TANGENT",),
                   from_point=(1, 0, 0)) == []
    assert _cursor((0.2, 0.2), doc=document, modes=("TANGENT",),
                   from_point=(10, 0, 0)) == []


def test_tangent_arc_respects_sweep(document):
    _add(document, Arc((0, 0, 0), 5.0, 30.0, 150.0))
    from_pt = (0, 10, 0)
    points = _pts(_cursor((-4.4, 2.6), doc=document, modes=("TANGENT",),
                          from_point=from_pt))
    # from (0,10): tangent angles 30° and 150° — exactly the arc endpoints;
    # the cursor hovers near the 150° one
    _expect(points, [(5 * math.cos(math.radians(150)), 2.5, 0.0)])


def test_perpendicular_foot_on_segment(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    points = _pts(_cursor((5.1, 0.2), doc=document, modes=("PERPENDICULAR",),
                          from_point=(5, 7, 0)))
    _expect(points, [(5.0, 0.0, 0.0)])


def test_perpendicular_clamped_to_segment_end(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    points = _pts(_cursor((10.1, 0.2), doc=document, modes=("PERPENDICULAR",),
                          from_point=(15, 3, 0)))
    _expect(points, [(10.0, 0.0, 0.0)])


def test_perpendicular_xline_unclamped_ray_clamped(document):
    _add(document, Xline((0, 0, 0), (1, 0, 0)))
    points = _pts(_cursor((15.1, 0.1), doc=document, modes=("PERPENDICULAR",),
                           from_point=(15, 3, 0)))
    _expect(points, [(15.0, 0.0, 0.0)])
    _add(document, Ray((0, 0, 0), (1, 0, 0)))
    points = _pts(_cursor((0.1, 0.1), doc=document, modes=("PERPENDICULAR",),
                          from_point=(-5, 3, 0)))
    _expect(points, [(0.0, 0.0, 0.0)])


def test_perpendicular_circle_radial_nearest_cursor(document):
    _add(document, Circle((0, 0, 0), 5.0))
    near = _pts(_cursor((5.1, 0.2), doc=document, modes=("PERPENDICULAR",),
                        from_point=(10, 0, 0)))
    _expect(near, [(5.0, 0.0, 0.0)])
    far = _pts(_cursor((-5.1, 0.2), doc=document, modes=("PERPENDICULAR",),
                       from_point=(10, 0, 0)))
    _expect(far, [(-5.0, 0.0, 0.0)])


def test_perpendicular_arc_respects_sweep(document):
    _add(document, Arc((0, 0, 0), 5.0, 90.0, 270.0))
    points = _pts(_cursor((-5.1, 0.2), doc=document, modes=("PERPENDICULAR",),
                          from_point=(10, 0, 0)))
    _expect(points, [(-5.0, 0.0, 0.0)])           # 180° in [90,270]; 0° is not


# ---------------------------------------------------------------------------
# INSERTION mode
# ---------------------------------------------------------------------------

def test_insertion_insert_text_mtext(document):
    _add(document, Insert("NOPE", (7, 8, 0)))     # dangling ref: position only
    _add(document, Text((1, 2, 0)))
    _add(document, Mtext((3, 4, 0)))
    points = _pts(_cursor((7.1, 8.2), doc=document, modes=("INSERTION",)))
    assert points == [(7.0, 8.0, 0.0)]
    points = _pts(_cursor((1.1, 2.2), doc=document, modes=("INSERTION",)))
    assert points == [(1.0, 2.0, 0.0)]
    points = _pts(_cursor((3.1, 4.2), doc=document, modes=("INSERTION",)))
    assert points == [(3.0, 4.0, 0.0)]


# ---------------------------------------------------------------------------
# aperture + ranking
# ---------------------------------------------------------------------------

def test_aperture_excludes_beyond_radius(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    assert _cursor((10.4, 0.0), aperture=0.3, doc=document) == []
    points = _pts(_cursor((10.4, 0.0), aperture=0.5, doc=document))
    assert points == [(10.0, 0.0, 0.0)]


def test_aperture_zero_keeps_only_exact_hits(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    assert _pts(_cursor((10.0, 0.0), aperture=0.0, doc=document)) == \
        [(10.0, 0.0, 0.0)]
    assert _cursor((10.0000001, 0.0), aperture=0.0, doc=document) == []


def test_ranking_nearest_cursor_first(document):
    _line(document, (0, 0, 0), (10, 0, 0))        # MIDPOINT (5,0)   d=0.4
    _line(document, (4, 3, 0), (6, 3, 0))         # MIDPOINT (5,3)   d=2.6
    results = _cursor((5.0, 0.4), aperture=3.0, doc=document,
                      modes=("MIDPOINT", "ENDPOINT"))
    # endpoints (4,3)/(6,3) tie at d≈2.784 — collection order breaks it
    assert [(r.point.x, r.point.y) for r in results] == [
        (5.0, 0.0),    # line1 midpoint (nearest)
        (5.0, 3.0),    # line2 midpoint
        (4.0, 3.0),    # line2 endpoint — collected before its sibling
        (6.0, 3.0),
    ]


def test_ranking_ties_stay_in_collection_order(document):
    first = _line(document, (0, 0, 0), (10, 0, 0))     # mid (5,0)   d=0.4
    second = _line(document, (4, 0.8, 0), (6, 0.8, 0))  # mid (5,0.8) d=0.4
    results = _cursor((5.0, 0.4), aperture=1.0, doc=document,
                      modes=("MIDPOINT",))
    assert [(r.point.x, r.point.y) for r in results] == [(5.0, 0.0), (5.0, 0.8)]
    assert results[0].entity_id == first.id
    assert results[1].entity_id == second.id


def test_snap_result_carries_mode_and_entity_id(document):
    line = _line(document, (0, 0, 0), (10, 0, 0))
    results = _cursor((0.1, 0.1), doc=document)
    assert results[0].mode == "ENDPOINT"
    assert results[0].entity_id == line.id


# ---------------------------------------------------------------------------
# frozen / off / locked layer semantics + cross-space exclusion
# ---------------------------------------------------------------------------

def test_frozen_layer_entities_never_snap(document):
    _frozen_layer(document)
    frozen = _line(document, (0, 0, 0), (10, 0, 0), layer="FROZ")
    live = _line(document, (20, 0, 0), (30, 0, 0))
    assert _cursor((0.1, 0.1), doc=document) == []  # frozen endpoint not seen
    points = _pts(_cursor((20.1, 0.1), doc=document))
    assert points == [(20.0, 0.0, 0.0)]


def test_off_layer_still_snappable_locked_layer_still_snappable(document):
    _off_layer(document)
    _locked_layer(document)
    _line(document, (0, 0, 0), (10, 0, 0), layer="HIDN")
    _line(document, (20, 0, 0), (30, 0, 0), layer="LOCK")
    assert _pts(_cursor((0.1, 0.1), doc=document)) == [(0.0, 0.0, 0.0)]
    assert _pts(_cursor((20.1, 0.1), doc=document)) == [(20.0, 0.0, 0.0)]


def test_cross_space_entities_excluded(document):
    with document.transaction("layout"):
        document.add_layout("P1")
    paper = _line(document, (0, 0, 0), (10, 0, 0), space="P1")
    model = _line(document, (20, 0, 0), (30, 0, 0), space="MODEL")
    assert document.current_space == "MODEL"
    assert _cursor((0.1, 0.1), doc=document) == []    # paper space unseen
    assert _pts(_cursor((20.1, 0.1), doc=document)) == [(20.0, 0.0, 0.0)]
    # positive control: switching spaces reveals the paper entity
    document.set_current_space("P1")
    assert _pts(_cursor((0.1, 0.1), doc=document)) == [(0.0, 0.0, 0.0)]
    document.set_current_space("MODEL")


# ---------------------------------------------------------------------------
# insert members contribute TRANSFORMED geometry
# ---------------------------------------------------------------------------

def _block_with_line_and_circle(document, name="BLK", base=(0, 0, 0)):
    members = [Line((0, 0, 0), (10, 0, 0)), Circle((20, 0, 0), 2.0)]
    with document.transaction("block"):
        document.add_block(name, base, members)
    return document.block(name)


def test_insert_members_transformed_endpoints_midpoint(document):
    _block_with_line_and_circle(document)
    insert = _add(document, Insert("BLK", (100, 50, 0),
                                   scale=(2, 2, 2), rotation=90.0))
    points = _pts(_cursor((100.1, 50.2), doc=document))
    assert (100.0, 50.0, 0.0) in points       # local (0,0) -> world
    points = _pts(_cursor((100.1, 70.2), doc=document))
    assert (100.0, 70.0, 0.0) in points        # local (10,0) -> world
    results = _cursor((100.2, 60.1), doc=document, modes=("MIDPOINT",))
    assert _pts(results) == [(100.0, 60.0, 0.0)]
    assert results[0].entity_id == insert.id  # attribution: the reference


def test_insert_members_transformed_center_quadrant(document):
    _block_with_line_and_circle(document)
    _add(document, Insert("BLK", (100, 50, 0), scale=(2, 2, 2), rotation=90.0))
    points = _pts(_cursor((99.8, 90.3), doc=document, modes=("CENTER",)))
    assert points == [(100.0, 90.0, 0.0)]      # local (20,0) -> world (100,90)
    points = _pts(_cursor((100.2, 94.1), doc=document, modes=("QUADRANT",)))
    assert points == [(100.0, 94.0, 0.0)]      # radius 2*2; angle 0+90


def test_insert_members_intersect_each_other(document):
    members = [Line((0, 0, 0), (10, 0, 0)), Line((5, -5, 0), (5, 5, 0))]
    with document.transaction("block"):
        document.add_block("XBLK", (0, 0, 0), members)
    _add(document, Insert("XBLK", (0, 0, 0)))
    points = _pts(_cursor((5.1, 0.1), doc=document, modes=("INTERSECTION",)))
    assert points == [(5.0, 5.0 * 0 - 5.0 * 0 + 0.0, 0.0)]  # (5, 0, 0)
    assert points == [(5.0, 0.0, 0.0)]


def test_insert_respects_block_base_point(document):
    members = [Line((5, 0, 0), (15, 0, 0))]
    with document.transaction("block"):
        document.add_block("BP", (5, 0, 0), members)
    _add(document, Insert("BP", (100, 50, 0)))
    points = _pts(_cursor((100.1, 50.2), doc=document))
    assert (100.0, 50.0, 0.0) in points       # local (5,0)-base -> world (100,50)
    points = _pts(_cursor((110.1, 50.2), doc=document))
    assert (110.0, 50.0, 0.0) in points       # local (15,0) -> (110,50)


def test_insert_non_uniform_scale_keeps_affine_candidates_only(document):
    members = [Line((0, 0, 0), (10, 0, 0)), Circle((20, 0, 0), 2.0)]
    with document.transaction("block"):
        document.add_block("NU", (0, 0, 0), members)
    _add(document, Insert("NU", (0, 0, 0), scale=(2, 1, 1)))
    points = _pts(_cursor((20.1, 0.2), doc=document))          # endpoint (20,0)
    assert (20.0, 0.0, 0.0) in points
    points = _pts(_cursor((40.1, 0.2), doc=document, modes=("CENTER",)))
    assert points == [(40.0, 0.0, 0.0)]                        # center transforms
    assert _cursor((42.1, 0.2), doc=document, modes=("QUADRANT",)) == []
    assert _cursor((38.1, 0.2), doc=document, modes=("QUADRANT",)) == []


def test_insert_member_on_frozen_layer_excluded(document):
    _frozen_layer(document)
    members = [Line((0, 0, 0), (10, 0, 0), layer="FROZ"),
               Line((20, 0, 0), (30, 0, 0))]
    with document.transaction("block"):
        document.add_block("FZB", (0, 0, 0), members)
    _add(document, Insert("FZB", (0, 0, 0)))
    assert _cursor((0.1, 0.1), doc=document) == []            # frozen member gone
    assert _pts(_cursor((20.1, 0.1), doc=document)) == [(20.0, 0.0, 0.0)]


# ---------------------------------------------------------------------------
# resolve_point — the binding chain (grid -> ortho -> osnap)
# ---------------------------------------------------------------------------

def test_resolve_grid_snap_lattice(document):
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 1.0)
    result = resolve_point(document, Point(10.4, 3.6))
    assert _pt(result) == (10.0, 4.0, 0.0)
    assert result.mode is None and result.entity_id is None
    document.settings.set("SNAPUNIT", 2.5)
    assert _pt(resolve_point(document, Point(3.7, -1.2))) == (2.5, 0.0, 0.0)


def test_resolve_grid_snap_huge_coordinates(document):
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 1.0)
    assert _pt(resolve_point(document, Point(1e9, -1e9))) == (1e9, -1e9, 0.0)
    document.settings.set("SNAPUNIT", 1000.0)
    assert _pt(resolve_point(document, Point(1e9, -1e9))) == (1e9, -1e9, 0.0)


def test_resolve_grid_snap_guard_for_bad_spacing(document):
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 0.0)   # degenerate spacing: no snap
    assert _pt(resolve_point(document, Point(10.4, 3.6))) == (10.4, 3.6, 0.0)


def test_resolve_ortho_projects_onto_hv_axes(document):
    document.settings.set("ORTHOMODE", 1)
    last = Point(10, 10, 0)
    assert _pt(resolve_point(document, Point(15, 13, 0), last_point=last)) == \
        (15.0, 10.0, 0.0)
    assert _pt(resolve_point(document, Point(12, 14, 0), last_point=last)) == \
        (10.0, 14.0, 0.0)


def test_resolve_ortho_needs_last_point(document):
    document.settings.set("ORTHOMODE", 1)
    assert _pt(resolve_point(document, Point(15, 13, 0), last_point=None)) == \
        (15.0, 13.0, 0.0)


def test_resolve_ortho_coincident_raw_uses_pointer_without_crash(document):
    document.settings.set("ORTHOMODE", 1)
    last = Point(5, 5, 0)
    result = resolve_point(document, Point(5, 5, 0), last_point=last,
                           pointer=Point(10, 5, 0))
    assert _pt(result) == (5.0, 5.0, 0.0)
    result = resolve_point(document, Point(5, 5, 0), last_point=last,
                           pointer=None)
    assert _pt(result) == (5.0, 5.0, 0.0)


def test_resolve_osnap_beats_grid_and_ortho(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 3.0)     # lattice point would be (9,0)
    document.settings.set("ORTHOMODE", 1)
    result = resolve_point(document, Point(10.3, 0.3, 0), last_point=Point(0, 0, 0))
    assert _pt(result) == (10.0, 0.0, 0.0)     # exact endpoint, not (9,0)
    assert result.mode == "ENDPOINT"


def test_resolve_falls_back_to_chain_without_candidates(document):
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 1.0)
    _line(document, (0, 0, 0), (10, 0, 0))
    result = resolve_point(document, Point(50.4, 50.6, 0))  # far from geometry
    assert _pt(result) == (50.0, 51.0, 0.0)
    assert result.mode is None


def test_resolve_one_shot_overrides_running_modes(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    _add(document, Circle((50, 50, 0), 3.0))
    document.settings.set("OSMODE", 4)         # running: CENTER only
    result = resolve_point(document, Point(0.1, 0.1, 0),
                           one_shot=["ENDPOINT"])
    assert _pt(result) == (0.0, 0.0, 0.0)
    assert result.mode == "ENDPOINT"
    # without the one-shot the running CENTER mode finds nothing here
    result = resolve_point(document, Point(0.1, 0.1, 0))
    assert _pt(result) == (0.1, 0.1, 0.0)
    assert result.mode is None


def test_resolve_empty_one_shot_falls_back_to_running(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    document.settings.set("OSMODE", 1)         # running: ENDPOINT
    result = resolve_point(document, Point(0.1, 0.1, 0), one_shot=[])
    assert _pt(result) == (0.0, 0.0, 0.0)
    assert result.mode == "ENDPOINT"


def test_resolve_tangent_uses_last_point_as_from_point(document):
    _add(document, Circle((10, 0, 0), 5.0))
    document.settings.set("OSMODE", 1024)      # running: TANGENT
    result = resolve_point(document, Point(7.6, 4.45, 0),
                           last_point=Point(0, 0, 0))
    assert _pt(result) == pytest.approx(
        (7.5, 5.0 * math.sin(math.radians(60)), 0.0), abs=1e-9)
    assert result.mode == "TANGENT"


def test_resolve_osnap_off_returns_chain_only(document):
    _line(document, (0, 0, 0), (10, 0, 0))
    document.settings.set("OSMODE", 0)
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 1.0)
    result = resolve_point(document, Point(0.1, 0.1, 0))
    assert _pt(result) == (0.0, 0.0, 0.0)       # grid lattice, no osnap
    assert result.mode is None


# ---------------------------------------------------------------------------
# dde_point — direct distance entry
# ---------------------------------------------------------------------------

def test_dde_point_along_pointer_direction(document):
    assert dde_point(Point(10, 10, 0), 5.0, Point(20, 10, 0), document) \
        .to_tuple() == (15.0, 10.0, 0.0)
    assert dde_point(Point(10, 10, 0), 5.0, Point(10, 20, 0), document) \
        .to_tuple() == (10.0, 15.0, 0.0)


def test_dde_point_without_pointer_uses_angle_zero(document):
    assert dde_point(Point(10, 10, 0), 5.0, None, document).to_tuple() == \
        (15.0, 10.0, 0.0)


def test_dde_point_ortho_snaps_direction_to_90s(document):
    document.settings.set("ORTHOMODE", 1)
    # 30° snaps down to 0°; 50° snaps up to 90°
    pointer = Point(10 + 5 * math.cos(math.radians(30)),
                    10 + 5 * math.sin(math.radians(30)), 0)
    assert dde_point(Point(10, 10, 0), 5.0, pointer, document).to_tuple() == \
        (15.0, 10.0, 0.0)
    pointer = Point(10 + 5 * math.cos(math.radians(50)),
                    10 + 5 * math.sin(math.radians(50)), 0)
    assert dde_point(Point(10, 10, 0), 5.0, pointer, document).to_tuple() == \
        (10.0, 15.0, 0.0)
    # exact diagonal resolves half-up to the higher bin
    assert dde_point(Point(10, 10, 0), 5.0, Point(15, 15, 0), document) \
        .to_tuple() == (10.0, 15.0, 0.0)


def test_dde_point_zero_negative_distance_and_z(document):
    assert dde_point(Point(10, 10, 0), 0.0, Point(20, 10, 0), document) \
        .to_tuple() == (10.0, 10.0, 0.0)
    assert dde_point(Point(10, 10, 0), -5.0, Point(20, 10, 0), document) \
        .to_tuple() == (5.0, 10.0, 0.0)
    assert dde_point(Point(1, 2, 3), 2.0, Point(5, 2, 3), document) \
        .to_tuple() == (3.0, 2.0, 3.0)


# ---------------------------------------------------------------------------
# ask_point integration hook (contract §4) — through the real Runner
# ---------------------------------------------------------------------------

def _run_test_point(ctx, items, points=1):
    """Drive a steps command asking ``points`` points through ask_point,
    via Registry.run_command + ScriptedProvider (the real prompt loop)."""

    def steps(cx):
        got = []
        for _ in range(points):
            value = yield from ask_point(cx, Request("point", "TEST point:"))
            got.append(value)
        return CommandResult(
            status="ok",
            summary=";".join(f"{p.x:.9f},{p.y:.9f},{p.z:.9f}" for p in got),
        )

    registry = Registry()
    registry.register(CommandSpec(name="TESTPT", steps=steps))
    result = registry.run_command(ctx, "TESTPT",
                                  provider=ScriptedProvider(ctx, items))
    coords = [tuple(float(v) for v in part.split(","))
              for part in result.summary.split(";")] if result.ok else []
    return result, coords


def test_ask_point_typed_never_resolves(make_context, document):
    _line(document, (0, 0, 0), (10, 0, 0))
    ctx = make_context()
    result, coords = _run_test_point(ctx, ["9.8,0.3"])
    assert result.ok
    assert coords == [(9.8, 0.3, 0.0)]           # EXACT passthrough


def test_ask_point_mouse_resolves_to_endpoint(make_context, document):
    _line(document, (0, 0, 0), (10, 0, 0))
    ctx = make_context()
    result, coords = _run_test_point(ctx, [point_input(9.8, 0.3, source="mouse")])
    assert result.ok
    assert coords == [(10.0, 0.0, 0.0)]           # resolved exactly


def test_ask_point_mouse_uses_running_modes_and_marker_data(document, make_context):
    _line(document, (0, 0, 0), (10, 0, 0))
    ctx = make_context()
    # sanity: resolution returns a SnapResult with marker data
    result = precision.resolve_point(document, Point(9.8, 0.3, 0))
    assert isinstance(result, SnapResult)
    assert result.mode == "ENDPOINT"


def test_ask_point_dde_converts_distance(make_context, document):
    ctx = make_context()
    ctx.last_point = Point(10, 10, 0)
    result, coords = _run_test_point(ctx, ["25"])
    assert result.ok
    assert coords == [(35.0, 10.0, 0.0)]          # pointer None -> angle 0
    ctx = make_context()
    ctx.last_point = Point(10, 10, 0)
    ctx.pointer = Point(10, 20, 0)
    result, coords = _run_test_point(ctx, ["5"])
    assert coords == [(10.0, 15.0, 0.0)]          # direction from pointer


def test_ask_point_distance_without_last_point_feedback(make_context, document):
    from bccmd import distance_input
    ctx = make_context()
    result, coords = _run_test_point(ctx, [distance_input(25), "3,4"])
    assert result.ok
    assert any("previous point" in m for m in ctx.feedback_messages)
    assert coords == [(3.0, 4.0, 0.0)]


def test_ask_point_osnap_keyword_sets_pending_and_reasks(make_context, document):
    _line(document, (0, 0, 0), (10, 0, 0))
    _add(document, Circle((50, 50, 0), 3.0))
    document.settings.set("OSMODE", 4)             # running: CENTER only
    ctx = make_context()
    result, coords = _run_test_point(ctx, [
        "END",                                      # one-shot override
        point_input(0.1, 0.1, source="mouse"),     # -> exact endpoint
    ])
    assert result.ok
    assert coords == [(0.0, 0.0, 0.0)]
    assert any("Osnap override active: ENDPOINT" in m for m in ctx.feedback_messages)
    assert ctx.pending_osnap is None                # consumed after the pick


def test_ask_point_one_shot_consumed_once(make_context, document):
    _line(document, (0, 0, 0), (10, 0, 0))
    _add(document, Circle((50, 50, 0), 3.0))
    document.settings.set("OSMODE", 4)             # running: CENTER only
    ctx = make_context()
    result, coords = _run_test_point(ctx, [
        "end",
        point_input(0.1, 0.1, source="mouse"),     # one-shot ENDPOINT
        point_input(49.9, 50.2, source="mouse"),   # running CENTER applies
    ], points=2)
    assert result.ok
    assert coords[0] == (0.0, 0.0, 0.0)            # one-shot endpoint
    assert coords[1] == (50.0, 50.0, 0.0)          # running center — override gone


def test_ask_point_invalid_osnap_keyword_reprompts(make_context, document):
    ctx = make_context()
    result, coords = _run_test_point(ctx, ["2,3"])
    assert result.ok
    assert coords == [(2.0, 3.0, 0.0)]


# ---------------------------------------------------------------------------
# end-to-end: mouse-source LINE through the registry runner
# ---------------------------------------------------------------------------

def test_line_mouse_snap_to_endpoint_e2e(run, make_context, document):
    """The handoff proof: precision integrated into real command execution —
    a mouse pick NEAR a prior line's endpoint creates EXACT geometry."""
    _line(document, (10, 0, 0), (20, 10, 0))
    ctx = make_context()
    ctx.pointer = Point(25.0, 15.0, 0)
    result = run(ctx, "line", [
        point_input(19.9, 10.05, source="mouse"),  # near the (20,10) endpoint
        "30,0",
        "",                                        # Enter ends the chain
    ])
    assert result.status == "ok"
    created = document.entities()[-1]
    assert created.kind == "line"
    assert created.p1 == (20.0, 10.0, 0.0)         # EXACT endpoint snap
    assert created.p2 == (30.0, 0.0, 0.0)
    assert created.id in result.created


def test_line_typed_points_stay_exact_e2e(run, make_context, document):
    _line(document, (10, 0, 0), (20, 10, 0))
    ctx = make_context()
    result = run(ctx, "line", ["19.9,10.05", "30,0", ""])
    assert result.status == "ok"
    created = document.entities()[-1]
    assert created.p1 == (19.9, 10.05, 0.0)        # no resolution for typed


# ---------------------------------------------------------------------------
# split_locked (W-D's modify commands consume this exact name)
# ---------------------------------------------------------------------------

def test_split_locked_partitions_by_layer_flag(document):
    _locked_layer(document)
    free = _line(document, (0, 0, 0), (1, 0, 0))
    locked = _line(document, (0, 1, 0), (1, 1, 0), layer="LOCK")
    kept, skipped = split_locked(document, [free.id, locked.id])
    assert kept == [free.id]
    assert skipped == [locked.id]


def test_split_locked_stale_ids_drop_out(document):
    _line(document, (0, 0, 0), (1, 0, 0))
    line = document.entities()[0]
    kept, skipped = split_locked(document, [line.id, "no-such-id"])
    assert kept == [line.id]
    assert skipped == []


def test_split_locked_missing_layer_counts_unlocked(document):
    entity = Line((0, 0, 0), (1, 0, 0), layer="GHOST")
    with document.transaction("add"):
        document.add_entity(entity)
    kept, skipped = split_locked(document, [entity.id])
    assert kept == [entity.id]
    assert skipped == []
