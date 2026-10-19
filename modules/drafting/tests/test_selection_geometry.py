"""M2 selection-geometry + drafting-geometry-extension tests (contract §0/§4).

The pinned selection helpers (``bcdraft.selection``: all_ids / window_ids /
crossing_ids / last_created_id — the exact names ``_common.select_ids``
imports), the SELECT command through the registry, and the pinned drafting
geometry extensions (``bcdraft.geometry``: entity_bbox / apply_insert_transform /
arc_from_bulge / polyline_points + the bulge helpers behind PLINE).

Selection semantics (binding, contracts §4): every helper filters to
``doc.current_space``, EXCLUDES frozen-layer entities and INCLUDES
locked-layer ones; ``window`` needs full bbox containment, ``crossing``
intersects; inserts contribute their TRANSFORMED member bboxes.
"""

import math

import pytest

from bccmd import selection_input

from bcdoc.entities import (
    Arc,
    Circle,
    Dim,
    Insert,
    Line,
    Mtext,
    Point as PointEntity,
    Polyline,
    Ray,
    Text,
    Viewport,
    Xline,
)

from bcdraft import geometry
from bcdraft import selection as sel


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed(document, entities):
    with document.transaction("seed"):
        for entity in entities:
            document.add_entity(entity)
    return [entity.id for entity in entities]


def _add_layers(document, specs):
    with document.transaction("layers"):
        for name, props in specs:
            document.layers.add(name, **props)


# ---------------------------------------------------------------------------
# all_ids / last_created_id — space + frozen/locked filters
# ---------------------------------------------------------------------------

def test_all_ids_filters_space_and_frozen_but_keeps_locked(document):
    _add_layers(document, [("Frozen", {"frozen": True}), ("Locked", {"locked": True})])
    ids = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),                       # MODEL, layer 0
        Line((0, 1, 0), (1, 1, 0), layer="Frozen"),       # frozen -> invisible
        Line((0, 2, 0), (1, 2, 0), layer="Locked"),       # locked but selectable
    ])
    assert sel.all_ids(document) == [ids[0], ids[2]]
    # switching space empties the pool
    with document.transaction("lay"):
        document.add_layout("Layout1")
    with document.transaction("space"):
        document.add_entity(Line((0, 3, 0), (1, 3, 0), space="Layout1"))
    document.set_current_space("Layout1")
    layout_line = [e.id for e in document.entities_in_space("Layout1")]
    assert sel.all_ids(document) == layout_line
    document.set_current_space("MODEL")
    assert sel.all_ids(document) == [ids[0], ids[2]]


def test_last_created_id_is_newest_in_current_space(document):
    _add_layers(document, [("Frozen", {"frozen": True})])
    ids = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),
        Line((0, 1, 0), (1, 1, 0), layer="Frozen"),
        Line((0, 2, 0), (1, 2, 0)),
    ])
    assert sel.last_created_id(document) == ids[2]
    # frozen-only document: nothing selectable
    with document.transaction("more"):
        document.add_entity(Line((0, 9, 0), (1, 9, 0), layer="Frozen"))
    assert sel.last_created_id(document) == ids[2]


def test_last_created_id_none_on_empty_document(document):
    assert sel.last_created_id(document) is None


def test_selectable_ids_drops_stale_and_frozen(document):
    _add_layers(document, [("Frozen", {"frozen": True})])
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    frozen_id = _seed(document, [Line((0, 1, 0), (1, 1, 0), layer="Frozen")])[0]
    result = sel.selectable_ids(document, ["deadbeef", ids[0], ids[0], frozen_id])
    assert result == [ids[0]]


# ---------------------------------------------------------------------------
# window_ids / crossing_ids — bbox geometry on a multi-kind document
# ---------------------------------------------------------------------------

def test_window_requires_full_containment_multi_kind(document):
    inside_line, inside_circle, through_line = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),     # fully inside
        Circle((0.5, 0.5, 0), 0.2),     # fully inside
        Line((0, 0, 0), (50, 0, 0)),    # passes through the window
    ])
    picked = sel.window_ids(document, (-1, -1, 0), (2, 2, 0))
    assert sorted(picked) == sorted([inside_line, inside_circle])


def test_crossing_catches_entities_merely_passing_through(document):
    inside_line, through_line = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),
        Line((0, 0, 0), (50, 0, 0)),
    ])
    window_picked = sel.window_ids(document, (2, -1, 0), (4, 1, 0))
    cross_picked = sel.crossing_ids(document, (2, -1, 0), (4, 1, 0))
    assert window_picked == []
    assert through_line in cross_picked
    assert inside_line not in cross_picked


def test_window_includes_locked_and_excludes_frozen(document):
    _add_layers(document, [("Frozen", {"frozen": True}), ("Locked", {"locked": True})])
    plain, frozen, locked = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),
        Line((0, 1, 0), (1, 1, 0), layer="Frozen"),
        Line((0, 2, 0), (1, 2, 0), layer="Locked"),
    ])
    picked = sel.window_ids(document, (-1, -1, 0), (2, 3, 0))
    assert sorted(picked) == sorted([plain, locked])
    cross = sel.crossing_ids(document, (-1, -1, 0), (2, 3, 0))
    assert frozen not in cross


def test_window_bbox_exactly_on_the_edge_is_inside(document):
    # the tolerance lets a rectangle drawn exactly on the entity's bbox select
    ids = _seed(document, [Line((0, 0, 0), (1, 1, 0))])
    assert sel.window_ids(document, (0, 0, 0), (1, 1, 0)) == ids
    assert sel.window_ids(document, (-2, -2, 0), (-1, -1, 0)) == []


def test_window_reversed_corners_normalized(document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    assert sel.window_ids(document, (2, 1, 0), (-1, -1, 0)) == ids


def test_window_polyline_with_bulge_needs_the_extrema(document):
    """A semicircular bulge segment's arc extrema extend the polyline bbox:
    a window covering only the chord does NOT select it; covering the
    arc extrema does."""
    # negative bulge from (0,0) to (4,0): the arc bows UP through (2, 2)
    ids = _seed(document, [Polyline([(0, 0, 0), (4, 0, 0)], bulges=[-1.0, 0.0])])
    assert geometry.entity_bbox(document.get(ids[0])) == pytest.approx(
        (0.0, 0.0, 4.0, 2.0)
    )
    # window over the chord only: the extrema stick out -> not selected
    assert sel.window_ids(document, (-1, -1, 0), (5, 1.5, 0)) == []
    # window including the arc extrema: selected
    assert sel.window_ids(document, (-1, -1, 0), (5, 2.5, 0)) == ids


def test_window_insert_uses_transformed_member_bboxes(document):
    with document.transaction("block"):
        document.add_block("BB", (0, 0, 0), [Line((0, 0, 0), (2, 0, 0))])
    with document.transaction("insert"):
        insert_id = document.add_entity(
            Insert("BB", (10, 10, 0), scale=(2, 2, 2), rotation=90)
        ).id
    # member (0,0)-(2,0) scaled 2 -> (0,0)-(4,0), rotated 90 -> (0,0)-(0,4),
    # moved to (10,10): bbox (10,10,10,14)
    assert geometry.entity_bbox(document.get(insert_id), document) == (
        10.0, 10.0, 10.0, 14.0,
    )
    assert sel.window_ids(document, (9, 9, 0), (11, 15, 0)) == [insert_id]
    assert sel.window_ids(document, (0, 0, 0), (5, 5, 0)) == []
    # and crossing catches it when only the member bbox clips the rectangle
    assert sel.crossing_ids(document, (10, 12, 0), (20, 20, 0)) == [insert_id]


def test_window_insert_without_doc_falls_back_to_position(document):
    with document.transaction("block"):
        document.add_block("BB", (0, 0, 0), [Line((0, 0, 0), (2, 0, 0))])
    with document.transaction("insert"):
        insert_id = document.add_entity(Insert("BB", (7, 7, 0))).id
    entity = document.get(insert_id)
    # documented fallback: without the doc the reference point alone bounds it
    assert geometry.entity_bbox(entity, None) == (7.0, 7.0, 7.0, 7.0)


# ---------------------------------------------------------------------------
# SELECT command through the registry
# ---------------------------------------------------------------------------

def test_select_all_sets_document_selection_with_feedback(
    run, make_context, document
):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0)), Line((2, 0, 0), (3, 0, 0))])
    ctx = make_context()
    result = run(ctx, "select", ["All", ""])
    assert result.status == "ok"
    assert result.summary == "SELECT: 2 object(s) selected"
    assert sorted(document.selection.ids) == sorted(ids)
    assert sorted(document.last_selection_ids) == sorted(ids)
    assert "SELECT: 2 object(s) selected" in ctx.feedback_messages


def test_select_window_asks_two_corners_then_selects(
    run, make_context, document
):
    inside, outside = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),
        Line((10, 0, 0), (11, 0, 0)),
    ])
    ctx = make_context()
    result = run(ctx, "select", ["Window", "-1,-1", "2,2", ""])
    assert result.status == "ok"
    assert sorted(document.selection.ids) == [inside]
    assert outside not in document.selection.ids


def test_select_crossing_mode(run, make_context, document):
    inside, through = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),
        Line((0, 0, 0), (50, 0, 0)),
    ])
    ctx = make_context()
    result = run(ctx, "select", ["Crossing", "20,-1", "30,1", ""])
    assert result.status == "ok"
    assert sorted(document.selection.ids) == [through]
    assert inside not in document.selection.ids


def test_select_last_mode(run, make_context, document):
    _seed(document, [Line((0, 0, 0), (1, 0, 0)), Line((2, 0, 0), (3, 0, 0))])
    ctx = make_context()
    result = run(ctx, "select", ["Last", ""])
    last = [e.id for e in document.entities()][-1]
    assert sorted(document.selection.ids) == [last]
    assert result.summary == "SELECT: 1 object(s) selected"


def test_select_raw_id_list_dedups_and_drops_stale(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    ctx = make_context()
    result = run(
        ctx, "select", [selection_input(["deadbeef", ids[0], ids[0]]), ""]
    )
    assert sorted(document.selection.ids) == ids


def test_select_previous_persists_across_commands(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0)), Line((2, 0, 0), (3, 0, 0))])
    ctx = make_context()
    run(ctx, "select", ["All", ""])
    # a fresh command resolves Previous from doc.last_selection_ids
    result = run(ctx, "erase", ["Previous", ""])
    assert result.status == "ok"
    assert sorted(result.removed) == sorted(ids)
    assert document.count_by_kind() == {}


def test_select_empty_result_feedback_and_pool_kept(
    run, make_context, document
):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    ctx = make_context()
    run(ctx, "select", ["All", ""])
    # an empty SELECT clears the selection but the Previous pool survives
    result = run(ctx, "select", [""])
    assert result.status == "ok"
    assert result.summary == "SELECT: 0 object(s) selected"
    assert document.selection.ids == frozenset()
    assert document.last_selection_ids == ids


def test_select_all_skips_frozen_and_other_spaces(run, make_context, document):
    _add_layers(document, [("Frozen", {"frozen": True})])
    ids = _seed(document, [
        Line((0, 0, 0), (1, 0, 0)),
        Line((0, 1, 0), (1, 1, 0), layer="Frozen"),
    ])
    with document.transaction("lay"):
        document.add_layout("Layout1")
    with document.transaction("space"):
        document.add_entity(Line((0, 3, 0), (1, 3, 0), space="Layout1"))
    ctx = make_context()
    run(ctx, "select", ["All", ""])
    assert sorted(document.selection.ids) == [ids[0]]


# ---------------------------------------------------------------------------
# entity_bbox — exact per-kind extents
# ---------------------------------------------------------------------------

def test_entity_bbox_line_circle_point(document):
    line = Line((1, 2, 0), (4, 6, 0))
    assert geometry.entity_bbox(line) == (1.0, 2.0, 4.0, 6.0)
    circle = Circle((5, 5, 0), 2)
    assert geometry.entity_bbox(circle) == (3.0, 3.0, 7.0, 7.0)
    point = PointEntity((2, 3, 0))
    assert geometry.entity_bbox(point) == (2.0, 3.0, 2.0, 3.0)


def test_entity_bbox_arc_axis_extremes_inside_sweep():
    # quarter arc 0->90: endpoints (5,0),(0,5) plus the extremes at 0 and 90
    arc = Arc((0, 0, 0), 5, 0, 90)
    assert geometry.entity_bbox(arc) == pytest.approx((0.0, 0.0, 5.0, 5.0))
    # 270-degree sweep 45->315: includes the 90/180/270 extremes but not 0
    big = Arc((0, 0, 0), 5, 45, 315)
    half = 5 * math.sqrt(2) / 2
    assert geometry.entity_bbox(big) == pytest.approx(
        (-5.0, -5.0, half, 5.0)
    )
    # full-circle convention (start == end): the whole circle
    full = Arc((1, 1, 0), 2, 30, 30)
    assert geometry.entity_bbox(full) == (-1.0, -1.0, 3.0, 3.0)


def test_entity_bbox_polyline_union_of_segments(document):
    pl = Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    assert geometry.entity_bbox(pl) == (0.0, 0.0, 10.0, 10.0)
    # the closing segment's bulge contributes its arc extrema to the box:
    # closing (10,0)->(0,0) with bulge -1 dips through (5,-5)
    closed = Polyline([(0, 0, 0), (10, 0, 0)], bulges=[0.0, -1.0], closed=True)
    assert geometry.entity_bbox(closed) == pytest.approx((0.0, -5.0, 10.0, 0.0))


def test_entity_bbox_ellipse_exact_formula():
    from bcdoc.entities import Ellipse

    e = Ellipse((1, 2, 0), (3, 0, 0), 0.5)
    # axis-aligned: half-extents are the semi-axes
    assert geometry.entity_bbox(e) == pytest.approx((-2.0, 0.5, 4.0, 3.5))
    rotated = Ellipse((1, 2, 0), (0, 3, 0), 0.5)  # major along +Y
    assert geometry.entity_bbox(rotated) == pytest.approx((-0.5, -1.0, 2.5, 5.0))
    at45 = Ellipse((0, 0, 0), (3 * math.cos(math.radians(45)),
                                3 * math.sin(math.radians(45)), 0), 0.5)
    cos45 = math.cos(math.radians(45.0))
    half_w = math.sqrt((3 * cos45) ** 2 + (1.5 * cos45) ** 2)
    assert geometry.entity_bbox(at45) == pytest.approx(
        (-half_w, -half_w, half_w, half_w)
    )


def test_entity_bbox_infinite_kinds_bounded_by_reach():
    xline = Xline((0, 0, 0), (1, 1, 0))
    reach = geometry.REACH * math.cos(math.radians(45.0))
    assert geometry.entity_bbox(xline) == pytest.approx(
        (-reach, -reach, reach, reach)
    )
    ray = Ray((0, 0, 0), (1, 1, 0))
    assert geometry.entity_bbox(ray) == pytest.approx((0.0, 0.0, reach, reach))


def test_entity_bbox_text_mtext_dim_viewport_rough_or_exact():
    text = Text((2, 2, 0), height=3)
    # documented rough estimate: width ~ 2x height, one height of box
    assert geometry.entity_bbox(text) == (2.0, 2.0, 8.0, 5.0)
    mtext = Mtext((1, 1, 0), width=5)
    assert geometry.entity_bbox(mtext) == (1.0, 1.0, 6.0, 3.5)
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), offset_point=(5, 3, 0))
    assert geometry.entity_bbox(dim) == (0.0, 0.0, 10.0, 3.0)
    assert geometry.entity_bbox(
        Dim("linear", (0, 0, 0), (10, 0, 0), offset_point=(5, 3, 0),
            text_position=(5, 6, 0))
    ) == (0.0, 0.0, 10.0, 6.0)
    viewport = Viewport((0, 0, 0), 10, (0, 0, 0), (10, 10, 0))
    assert geometry.entity_bbox(viewport) == (0.0, 0.0, 10.0, 10.0)


def test_entity_bbox_unknown_kind_raises():
    class Fake:
        kind = "frob"
    with pytest.raises(ValueError):
        geometry.entity_bbox(Fake())


# ---------------------------------------------------------------------------
# arc_from_bulge + the bulge helpers (PLINE arc math)
# ---------------------------------------------------------------------------

def test_arc_from_bulge_quarter_ccw():
    # bulge tan(90/4) from (0,0) to (10,0): CCW quarter about (5,5)
    bulge = math.tan(math.radians(90.0) / 4.0)
    center, radius, a_start, a_end = geometry.arc_from_bulge(
        (0, 0, 0), (10, 0, 0), bulge)
    assert center == pytest.approx((5.0, 5.0, 0.0))
    assert radius == pytest.approx(10.0 / math.sqrt(2.0))
    assert a_start == pytest.approx(225.0)  # (0,0) seen from (5,5)
    assert a_end == pytest.approx(315.0)    # (10,0) seen from (5,5)
    assert geometry._ccw_from(a_start, a_end) == pytest.approx(90.0)


def test_arc_from_bulge_semicircle_and_major_arc():
    center, radius, a_start, a_end = geometry.arc_from_bulge(
        (0, 0, 0), (4, 0, 0), 1.0)
    assert center == pytest.approx((2.0, 0.0, 0.0))
    assert radius == pytest.approx(2.0)
    # |bulge| > 1 is a major arc: the sweep exceeds 180 degrees
    major = math.tan(math.radians(270.0) / 4.0)   # 270-degree included angle
    center, radius, a_start, a_end = geometry.arc_from_bulge(
        (0, 0, 0), (4, 0, 0), major)
    sweep = geometry._ccw_from(a_start, a_end)
    assert sweep == pytest.approx(270.0)
    assert center == pytest.approx((2.0, -2.0, 0.0))


def test_arc_from_bulge_negative_runs_the_other_direction():
    # negative bulge: the traversal (0,0)->(10,0) is CLOCKWISE (center on
    # the right of travel, at (5,-5)), so the CCW representation runs from
    # the old END angle back to the old START angle
    center, radius, a_start, a_end = geometry.arc_from_bulge(
        (0, 0, 0), (10, 0, 0), -math.tan(math.radians(90.0) / 4.0))
    assert center == pytest.approx((5.0, -5.0, 0.0))
    assert radius == pytest.approx(10.0 / math.sqrt(2.0))
    assert a_start == pytest.approx(45.0)    # the old END angle
    assert a_end == pytest.approx(135.0)     # the old START angle


def test_arc_from_bulge_rejects_degenerate_input():
    with pytest.raises(ValueError):
        geometry.arc_from_bulge((0, 0, 0), (10, 0, 0), 0.0)   # straight
    with pytest.raises(ValueError):
        geometry.arc_from_bulge((0, 0, 0), (0, 0, 0), 0.5)   # coincident


def test_bulge_from_arc_round_trip():
    bulge = math.tan(math.radians(60.0) / 4.0)
    center, radius, a_start, a_end = geometry.arc_from_bulge(
        (0, 0, 0), (10, 0, 0), bulge)
    # the arc's start/end points back through bulge_from_arc
    p1 = (center[0] + radius * math.cos(math.radians(a_start)),
          center[1] + radius * math.sin(math.radians(a_start)), 0.0)
    p2 = (center[0] + radius * math.cos(math.radians(a_end)),
          center[1] + radius * math.sin(math.radians(a_end)), 0.0)
    assert geometry.bulge_from_arc(p1, p2, center) == pytest.approx(bulge)


def test_bulge_from_tangent_and_tangent_at_end():
    # tangent (1,0) at (0,0) curving to (10,10): the circle tangent to +X at
    # the origin through that point has radius 10 -> a 90-degree arc
    quarter = math.tan(math.radians(90.0) / 4.0)
    assert geometry.bulge_from_tangent(
        (0, 0, 0), (10, 10, 0), (1, 0)) == pytest.approx(quarter)
    # the classic PLINE continuation: straight (0,0)->(10,0) then an arc to
    # (10,10) has tangent (1,0) at the new arc's start -> semicircle bulge 1
    assert geometry.bulge_from_tangent(
        (10, 0, 0), (10, 10, 0), (1, 0)) == pytest.approx(1.0)
    # endpoint on the tangent line degenerates to a straight segment
    assert geometry.bulge_from_tangent(
        (0, 0, 0), (10, 0, 0), (1, 0)) == 0.0
    with pytest.raises(ValueError):
        geometry.bulge_from_tangent((0, 0, 0), (10, 0, 0), (0, 0))
    # tangent_at_end: straight segments keep their direction; the CCW
    # semicircle (10,0)->(10,10) arrives at its end heading -X
    assert geometry.tangent_at_end((0, 0, 0), (10, 0, 0), 0.0) == (1.0, 0.0)
    assert geometry.tangent_at_end((10, 0, 0), (10, 10, 0), 1.0) == \
        pytest.approx((-1.0, 0.0))


# ---------------------------------------------------------------------------
# polyline_points — ordered path sampling
# ---------------------------------------------------------------------------

def test_polyline_points_straight_closed_and_single_vertex():
    pl = Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    assert geometry.polyline_points(pl) == [
        (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0),
    ]
    closed = Polyline([(0, 0, 0), (10, 0, 0)], closed=True)
    assert geometry.polyline_points(closed) == [
        (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 0.0, 0.0),
    ]
    assert geometry.polyline_points(Polyline([(3, 4, 0)])) == [(3.0, 4.0, 0.0)]


def test_polyline_points_walks_bulges_in_traversal_direction():
    # positive bulge semicircle (0,0)->(4,0) bows DOWN through (2,-2): the
    # CCW representation runs 270->90, so the walk must reach the mid at
    # parameter 0 degrees (2, +2)... i.e. the sampling follows the actual
    # start->end direction regardless of the stored angle orientation.
    pl = Polyline([(0, 0, 0), (4, 0, 0)], bulges=[1.0, 0.0])
    points = geometry.polyline_points(pl, segments_per_arc=4)
    assert points[0] == (0.0, 0.0, 0.0)
    assert points[-1] == (4.0, 0.0, 0.0)
    mid_index = len(points) // 2
    midpoint = points[mid_index]
    # the positive bulge bows to the RIGHT of travel (+X): through (2, -2)
    assert midpoint[0] == pytest.approx(2.0)
    assert midpoint[1] == pytest.approx(-2.0)
    # negative bulge walks the mirrored path through (2, +2)
    pl2 = Polyline([(0, 0, 0), (4, 0, 0)], bulges=[-1.0, 0.0])
    points2 = geometry.polyline_points(pl2, segments_per_arc=4)
    assert points2[mid_index][1] == pytest.approx(2.0)
    assert points2[-1] == (4.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# apply_insert_transform — the EXPLODE/selection member placement math
# ---------------------------------------------------------------------------

def _transformed(entity, base=(0, 0, 0), position=(10, 10, 0),
                 scale=(1, 1, 1), rotation=0.0):
    return geometry.apply_insert_transform(
        entity, base, position, scale, rotation)


def test_apply_insert_transform_composes_translate_scale_rotate():
    # (1,0)-(3,0) with base (1,0,0), scale (2,1,1), rotation 90, at (10,10):
    # relative (0,0)-(2,0) -> scaled (0,0)-(4,0) -> rotated (0,0)-(0,4)
    # -> placed (10,10)-(10,14)
    line = Line((1, 0, 0), (3, 0, 0))
    moved = _transformed(line, base=(1, 0, 0), scale=(2, 1, 1), rotation=90.0)
    assert isinstance(moved, Line)
    assert moved.p1 == pytest.approx((10.0, 10.0, 0.0))
    assert moved.p2 == pytest.approx((10.0, 14.0, 0.0))


def test_apply_insert_transform_circle_arc_point_radius_and_angles():
    circle = Circle((0, 0, 0), 2)
    moved = _transformed(circle, position=(5, 5, 0), scale=(2, 2, 2), rotation=30)
    assert moved.center == (5.0, 5.0, 0.0)
    assert moved.radius == pytest.approx(4.0)     # |sx| * r
    arc = Arc((0, 0, 0), 2, 10, 80)
    moved = _transformed(arc, position=(5, 5, 0), scale=(1, 1, 1), rotation=30)
    assert moved.start_angle == pytest.approx(40.0)
    assert moved.end_angle == pytest.approx(110.0)
    point = PointEntity((1, 2, 0))
    moved = _transformed(point, position=(10, 10, 0))
    assert moved.position == (11.0, 12.0, 0.0)


def test_apply_insert_transform_polyline_keeps_bulges():
    pl = Polyline([(0, 0, 0), (4, 0, 0)], bulges=[0.5, 0.0])
    moved = _transformed(
        pl, base=(0, 0, 0), position=(10, 10, 0), scale=(2, 2, 2), rotation=90
    )
    assert moved.vertices[0] == pytest.approx((10.0, 10.0, 0.0))
    assert moved.vertices[1] == pytest.approx((10.0, 18.0, 0.0))
    assert list(moved.bulges) == [0.5, 0.0]      # invariant (documented)


def test_apply_insert_transform_ellipse_text_insert():
    from bcdoc.entities import Ellipse

    ellipse = Ellipse((0, 0, 0), (3, 0, 0), 0.5)
    moved = _transformed(
        ellipse, position=(10, 10, 0), scale=(2, 2, 2), rotation=90)
    assert moved.center == (10.0, 10.0, 0.0)
    assert moved.major_axis == pytest.approx((0.0, 6.0, 0.0))
    text = Text((1, 0, 0), height=2.0, rotation=10.0)
    moved = _transformed(text, position=(5, 5, 0), scale=(2, 1, 1), rotation=30)
    assert moved.position == pytest.approx(
        (5.0 + 2.0 * math.cos(math.radians(30)),
         5.0 + 2.0 * math.sin(math.radians(30)), 0.0))
    assert moved.height == pytest.approx(2.0)    # |sy|
    assert moved.rotation == pytest.approx(40.0)
    # nested inserts compose position/rotation and multiply scale per axis
    nested = Insert("inner", (1, 0, 0), scale=(1, 1, 1), rotation=10.0)
    moved = _transformed(nested, position=(5, 5, 0), scale=(2, 2, 2), rotation=30)
    assert moved.position == pytest.approx(
        (5.0 + 2.0 * math.cos(math.radians(30)),
         5.0 + 2.0 * math.sin(math.radians(30)), 0.0))
    assert moved.scale == (2.0, 2.0, 2.0)        # per-axis multiplication
    assert moved.rotation == pytest.approx(40.0)


def test_apply_insert_transform_unsupported_kind_raises():
    class Fake:
        kind = "frob"
    with pytest.raises(ValueError):
        geometry.apply_insert_transform(
            Fake(), (0, 0, 0), (0, 0, 0), (1, 1, 1), 0.0)
