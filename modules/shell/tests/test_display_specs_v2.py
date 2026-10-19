"""bcshell v2 display-spec tests (contract §7) — pure, no Blender.

Covers EVERY kind mapping of :func:`bcshell.sync.display_specs` (shape,
sampled points, roles, ids, routing keys), the layer-display policy
(:func:`layer_visible`, :func:`display_aci`), the local ACI palette
(:mod:`bcshell.colors`) and the space-collection name mapping.

Integration-gated mappings skip until the parallel packages land
(the skips auto-activate at TL integration):

* ``dim`` — needs ``bcdraw.dims.resolve_dimension`` (W-C);
* ``insert`` — needs ``bcdraft.geometry.apply_insert_transform`` (W-D).
"""

import math

import pytest

import bcshell.sync as sync
from bcshell.colors import ACI_TABLE, aci_to_rgb

from bcdoc.document import Document
from bcdoc.entities import (
    Arc,
    Circle,
    Dim,
    Ellipse,
    Insert,
    Line,
    Mtext,
    Point,
    Polyline,
    Ray,
    Text,
    Viewport,
    Xline,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def doc():
    document = Document(name="display-spec-tests")
    with document.transaction("seed layer"):
        document.layers.add("WALLS", color=1)
        document.layers.add("HIDDEN", color=5, on=False)
        document.layers.add("ICE", color=3, frozen=True)
    return document


def _added(document, entity):
    with document.transaction("add"):
        document.add_entity(entity)
    return entity


def _binding_keys(spec):
    """The binding spec keys every curve/font spec must carry."""
    expected = {"role", "kind", "name", "bcdoc_id"}
    if spec["kind"] == "curve":
        expected |= {"points", "cyclic"}
    else:
        expected |= {"body", "size", "rotation", "position"}
    return expected


def _assert_spec_shape(specs, entity, count=None, kind="curve", role="solid"):
    assert isinstance(specs, list)
    assert 1 <= len(specs)
    if count is not None:
        assert len(specs) == count
    for spec in specs:
        missing = _binding_keys(spec) - set(spec)
        assert not missing, f"spec missing binding keys: {missing}"
        assert spec["kind"] in ("curve", "font")
        assert spec["role"] in sync.ROLES
        assert spec["role"] == role
        assert spec["bcdoc_id"] == entity.id
        # additive routing keys (documented in the module docstring)
        assert isinstance(spec["aci"], int)
        assert isinstance(spec["hide"], bool)
        assert spec["space"] == entity.space
    assert all(s["kind"] == kind for s in specs)


# ---------------------------------------------------------------------------
# M1 kinds — display_specs adapts the proven entity_display_spec
# ---------------------------------------------------------------------------

def test_display_specs_line_adapts_m1_spec(doc):
    entity = _added(doc, Line((1.0, 2.0, 0.0), (5.0, 7.0, 0.0)))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1, role="solid")
    old = sync.entity_display_spec(entity)
    assert specs[0]["points"] == old["points"]
    assert specs[0]["cyclic"] == old["cyclic"] is False
    assert specs[0]["name"] == old["name"]


def test_display_specs_circle_and_arc_roles_and_points(doc):
    circle = _added(doc, Circle((10.0, 20.0, 0.0), 4.0))
    specs = sync.display_specs(circle, doc)
    _assert_spec_shape(specs, circle, count=1)
    assert specs[0]["cyclic"] is True
    arc = _added(doc, Arc((0.0, 0.0, 0.0), 2.0, 0.0, 90.0))
    specs = sync.display_specs(arc, doc)
    _assert_spec_shape(specs, arc, count=1)
    assert specs[0]["cyclic"] is False
    assert len(specs[0]["points"]) == sync.ARC_SEGMENTS + 1


def test_display_specs_unknown_kind_raises():
    class Fake:
        kind = "tribble"

    with pytest.raises(ValueError):
        sync.display_specs(Fake())


# ---------------------------------------------------------------------------
# point — 2 cross segments, arms POINT_ARM
# ---------------------------------------------------------------------------

def test_point_two_cross_segments_with_0_25_arms(doc):
    entity = _added(doc, Point((10.0, -3.0, 0.5)))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=2, kind="curve", role="marker")
    arm = sync.POINT_ARM
    assert specs[0]["points"] == [(10.0 - arm, -3.0, 0.5), (10.0 + arm, -3.0, 0.5)]
    assert specs[1]["points"] == [(10.0, -3.0 - arm, 0.5), (10.0, -3.0 + arm, 0.5)]
    assert all(spec["cyclic"] is False for spec in specs)


# ---------------------------------------------------------------------------
# polyline — one centerline curve; bulges sampled; widths NOT rendered
# ---------------------------------------------------------------------------

def test_polyline_straight_segments_non_cyclic(doc):
    entity = _added(doc, Polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)],
                                  widths=[(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1, kind="curve", role="centerline")
    assert specs[0]["points"] == [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
    assert specs[0]["cyclic"] is False


def test_polyline_closed_is_cyclic(doc):
    entity = _added(doc, Polyline([(0, 0, 0), (4, 0, 0), (4, 4, 0)], closed=True))
    specs = sync.display_specs(entity, doc)
    assert specs[0]["cyclic"] is True


def test_polyline_bulge_samples_arc_segment(doc):
    # one arc segment: (0,0)->(10,0) bulge 1 = semicircle dipping BELOW the
    # chord (positive bulge = CCW from start to end — the AutoCAD convention
    # verified against ezdxf's bulge_to_arc ground truth; see worklog)
    entity = _added(doc, Polyline([(0, 0, 0), (10, 0, 0)], bulges=[1.0, 0.0]))
    specs = sync.display_specs(entity, doc)
    points = specs[0]["points"]
    # 16 segments per sweep -> a semicircle samples 8 segments = 9 points
    assert len(points) == 9
    assert points[0] == (0.0, 0.0, 0.0)
    assert points[-1] == (10.0, 0.0, 0.0)
    # every sample sits on the circle of radius 5 about (5, 0)…
    for p in points:
        assert math.hypot(p[0] - 5.0, p[1] - 0.0) == pytest.approx(5.0)
    # …and the arc midpoint dips below the chord
    mid = points[len(points) // 2]
    assert mid[1] == pytest.approx(-5.0)


def test_bulge_arc_points_negative_bulge_arcs_above():
    pts = sync._bulge_arc_points((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), -1.0)
    assert pts[0] == (0.0, 0.0, 0.0)
    assert pts[-1] == (1.0, 0.0, 0.0)
    mid = pts[len(pts) // 2]
    assert mid[1] == pytest.approx(0.5)   # above the chord (CW from start)


def test_bulge_arc_points_quarter_circle_matches_ground_truth():
    # bulge tan(22.5°) over a unit chord: quarter circle, center (0.5, 0.5)
    pts = sync._bulge_arc_points((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                 math.tan(math.pi / 8))
    center = (0.5, 0.5)
    for p in pts:
        assert math.hypot(p[0] - center[0], p[1] - center[1]) == pytest.approx(
            math.sqrt(0.5), abs=1e-9)


def test_bulge_arc_points_zero_bulge_is_straight():
    assert sync._bulge_arc_points((0, 0, 0), (5, 5, 0), 0.0) == [
        (0.0, 0.0, 0.0), (5.0, 5.0, 0.0)]


# ---------------------------------------------------------------------------
# ellipse — 48-point sampling of the parametric form
# ---------------------------------------------------------------------------

def test_ellipse_full_cyclic_48_points(doc):
    entity = _added(doc, Ellipse((5.0, 5.0, 0.0), (3.0, 0.0, 0.0), 0.5))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1)
    points = specs[0]["points"]
    assert len(points) == sync.ELLIPSE_SEGMENTS
    assert specs[0]["cyclic"] is True
    # parametric form: center + major·cosθ + minor·sinθ with
    # minor = rotate(major, 90°)·ratio — i.e. every sample satisfies
    # (dx/major_len)^2 + (dy/minor_len)^2 == 1 (minor_len = 3 * 0.5)
    for p in points:
        dx, dy = p[0] - 5.0, p[1] - 5.0
        assert (dx / 3.0) ** 2 + (dy / 1.5) ** 2 == pytest.approx(1.0)
    # the major-axis endpoints are sampled (θ = 0 and θ = π)
    assert (8.0, 5.0, 0.0) in points
    assert (2.0, 5.0, 0.0) in points


def test_ellipse_partial_non_cyclic_spans_start_end(doc):
    entity = _added(doc, Ellipse((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), 1.0,
                                 start_angle=0.0, end_angle=90.0))
    specs = sync.display_specs(entity, doc)
    points = specs[0]["points"]
    assert len(points) == sync.ELLIPSE_SEGMENTS
    assert specs[0]["cyclic"] is False
    assert points[0] == pytest.approx((2.0, 0.0, 0.0))
    assert points[-1] == pytest.approx((0.0, 2.0, 0.0))


# ---------------------------------------------------------------------------
# xline / ray — display-only ±1000 clip
# ---------------------------------------------------------------------------

def test_xline_clips_1000_each_direction_around_midpoint(doc):
    entity = _added(doc, Xline((10.0, 0.0, 0.0), (12.0, 0.0, 0.0)))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1)
    assert specs[0]["points"] == [(-989.0, 0.0, 0.0), (1011.0, 0.0, 0.0)]
    assert specs[0]["cyclic"] is False


def test_ray_starts_at_p1_extends_1000_along_direction(doc):
    entity = _added(doc, Ray((0.0, 0.0, 0.0), (0.0, 4.0, 0.0)))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1)
    assert specs[0]["points"] == [(0.0, 0.0, 0.0), (0.0, 1000.0, 0.0)]


def test_degenerate_xline_raises(doc):
    entity = Xline((1.0, 1.0, 0.0), (1.0, 1.0, 0.0))
    with pytest.raises(ValueError):
        sync.display_specs(entity, doc)


# ---------------------------------------------------------------------------
# text / mtext — font specs
# ---------------------------------------------------------------------------

def test_text_left_justification_origin_at_position(doc):
    entity = _added(doc, Text((10.0, 20.0, 0.0), height=2.0, rotation=0.0,
                              content="HELLO"))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1, kind="font", role="text")
    spec = specs[0]
    assert spec["body"] == "HELLO"
    assert spec["size"] == 2.0
    assert spec["rotation"] == 0.0
    assert spec["position"] == (10.0, 20.0, 0.0)


def test_text_center_justification_offsets_origin_by_half_estimate(doc):
    entity = _added(doc, Text((10.0, 20.0, 0.0), height=2.0, rotation=0.0,
                              content="HELLO", justification="CENTER"))
    spec = sync.display_specs(entity, doc)[0]
    # documented estimate: width = len(content)*height*0.6; CENTER shifts the
    # ORIGIN back by half of it along the text direction
    estimate = len("HELLO") * 2.0 * 0.6
    assert spec["position"] == pytest.approx(
        (10.0 - estimate / 2.0, 20.0, 0.0))


def test_text_right_justification_with_rotation(doc):
    entity = _added(doc, Text((0.0, 0.0, 0.0), height=1.0, rotation=90.0,
                              content="AB", justification="RIGHT"))
    spec = sync.display_specs(entity, doc)[0]
    estimate = len("AB") * 1.0 * 0.6
    # text direction at 90° is +Y: the origin moves back along -Y
    assert spec["position"] == pytest.approx((0.0, -estimate, 0.0))
    assert spec["rotation"] == 90.0


def test_mtext_font_spec_body_keeps_newlines_width_not_wrapped(doc):
    entity = _added(doc, Mtext((1.0, 2.0, 0.0), width=40.0,
                               content="line one\nline two"))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1, kind="font", role="text")
    spec = specs[0]
    assert spec["body"] == "line one\nline two"
    # size comes from the Standard text style default height
    assert spec["size"] == doc.text_style("Standard").height
    assert spec["position"] == (1.0, 2.0, 0.0)
    assert spec["rotation"] == 0.0


def test_mtext_size_follows_its_style(doc):
    with doc.transaction("style"):
        doc.add_text_style("TALL", height=7.0)
    entity = _added(doc, Mtext((0.0, 0.0, 0.0), content="x", style="TALL"))
    spec = sync.display_specs(entity, doc)[0]
    assert spec["size"] == 7.0


# ---------------------------------------------------------------------------
# viewport — rectangle frame
# ---------------------------------------------------------------------------

def test_viewport_rectangle_five_points_non_cyclic(doc):
    with doc.transaction("layout"):
        doc.add_layout("Sheet1")
    entity = _added(doc, Viewport((0.0, 0.0, 0.0), 20.0,
                                  (10.0, 10.0, 0.0), (70.0, 50.0, 0.0),
                                  space="Sheet1"))
    specs = sync.display_specs(entity, doc)
    _assert_spec_shape(specs, entity, count=1, kind="curve",
                       role="viewport-frame")
    assert specs[0]["points"] == [
        (10.0, 10.0, 0.0), (70.0, 10.0, 0.0), (70.0, 50.0, 0.0),
        (10.0, 50.0, 0.0), (10.0, 10.0, 0.0)]
    assert specs[0]["cyclic"] is False
    assert specs[0]["space"] == "Sheet1"


# ---------------------------------------------------------------------------
# dim — gated on bcdraw (W-C); skips until integration
# ---------------------------------------------------------------------------

def test_dim_two_specs_curve_and_font(doc):
    bcdraw = pytest.importorskip(
        "bcdraw", reason="requires W-C integration (bcdraw dims + regen)")
    entity = _added(doc, Dim("linear", (0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             angle=0.0, offset_point=(5.0, 5.0, 0.0),
                             measurement=10.0))
    assert hasattr(bcdraw.dims, "resolve_dimension"), (
        "bcdraw landed without resolve_dimension — API drift")
    specs = sync.display_specs(entity, doc)
    assert len(specs) == 2
    curve, font = specs
    assert curve["kind"] == "curve"
    assert curve["role"] == "dim"
    assert curve["bcdoc_id"] == entity.id
    # ONE curve object with 7 polylines: ext1, ext2, dim line, 2+2 arrow segs
    assert len(curve["splines"]) == 7
    assert curve["points"] == [tuple(curve["splines"][2]["points"][0]),
                               tuple(curve["splines"][2]["points"][1])]
    assert font["kind"] == "font"
    assert font["role"] == "dim-text"
    assert font["bcdoc_id"] == entity.id
    assert len(font["body"]) > 0
    standard = doc.dim_style("Standard")
    assert font["size"] == pytest.approx(standard.dimtxt * standard.dimscale)
    # both specs carry the binding + routing keys
    for spec in (curve, font):
        assert not (_binding_keys(spec) - set(spec))
        assert spec["space"] == entity.space


def test_dim_without_doc_raises(doc):
    pytest.importorskip("bcdraw",
                        reason="requires W-C integration (bcdraw dims)")
    entity = Dim("linear", (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        sync.display_specs(entity, None)


# ---------------------------------------------------------------------------
# insert — gated on bcdraft.geometry.apply_insert_transform (W-D)
# ---------------------------------------------------------------------------

def _insert_doc():
    document = Document()
    with document.transaction("block"):
        document.add_block("MYBLOCK", (0.0, 0.0, 0.0),
                           [Line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                            Circle((0.0, 1.0, 0.0), 0.5)])
        document.add_entity(Insert("MYBLOCK", (10.0, 0.0, 0.0)))
    return document


def test_insert_members_all_tagged_with_insert_id():
    from bcdraft import geometry as bcdraft_geometry
    if not hasattr(bcdraft_geometry, "apply_insert_transform"):
        pytest.skip("requires W-D integration "
                    "(bcdraft.geometry.apply_insert_transform)")
    document = _insert_doc()
    insert = document.entities()[0]
    specs = sync.display_specs(insert, document)
    assert len(specs) >= 2                     # 2 members × their own specs
    for spec in specs:
        assert spec["role"] == "member"
        assert spec["bcdoc_id"] == insert.id   # the INSERT's id, not members'
        assert spec["space"] == insert.space
    # transformed: the line member's first point sits at the insert position
    line_members = [s for s in specs if s["kind"] == "curve"
                    and s["points"][0] == (10.0, 0.0, 0.0)]
    assert line_members, "member geometry was not moved to the insert position"


def test_insert_byblock_member_resolves_through_insert_chain():
    from bcdraft import geometry as bcdraft_geometry
    if not hasattr(bcdraft_geometry, "apply_insert_transform"):
        pytest.skip("requires W-D integration "
                    "(bcdraft.geometry.apply_insert_transform)")
    document = _insert_doc()
    # give the block a ByBlock (color 0) member and the insert a color chain
    with document.transaction("redefine"):
        document.redefine_block(
            "MYBLOCK", [Line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), color=0)])
        document.update_entity(document.entities()[0].id, color=2)
    insert = document.entities()[0]
    specs = sync.display_specs(insert, document)
    assert all(spec["aci"] == 2 for spec in specs)   # ByBlock -> insert color


def test_insert_transform_helper_integrated():
    """W-D's apply_insert_transform IS present (integration landed): the
    insert display path uses it directly — no fallback remains."""
    from bcdraft.geometry import apply_insert_transform  # noqa: F401
    document = _insert_doc()
    insert = document.entities()[0]
    specs = sync.display_specs(insert, document)
    assert specs, "insert display specs must resolve through the integrated helper"


# ---------------------------------------------------------------------------
# layer-visible predicate + ACI resolution
# ---------------------------------------------------------------------------

def test_layer_visible_policy():
    class Record:
        def __init__(self, on, frozen):
            self.on = on
            self.frozen = frozen

    assert sync.layer_visible(Record(True, False)) is True
    assert sync.layer_visible(Record(False, False)) is False   # off -> hidden
    assert sync.layer_visible(Record(True, True)) is False     # frozen -> hidden
    assert sync.layer_visible(None) is True                    # unknown -> shown


def test_display_aci_bylayer_uses_layer_color(doc):
    entity = Line((0, 0, 0), (1, 0, 0), layer="WALLS")   # WALLS color 1
    assert sync.display_aci(entity, doc) == 1
    entity = Line((0, 0, 0), (1, 0, 0))                  # layer 0 color 7
    assert sync.display_aci(entity, doc) == 7


def test_display_aci_explicit_color_wins(doc):
    entity = Line((0, 0, 0), (1, 0, 0), layer="WALLS", color=5)
    assert sync.display_aci(entity, doc) == 5


def test_display_aci_byblock_uses_inherited_then_fallback(doc):
    entity = Line((0, 0, 0), (1, 0, 0), color=0)
    assert sync.display_aci(entity, doc, _inherited=3) == 3
    assert sync.display_aci(entity, doc) == sync.FALLBACK_ACI


def test_specs_carry_layer_driven_hide_flag(doc):
    visible = _added(doc, Line((0, 0, 0), (1, 0, 0), layer="WALLS"))
    off = _added(doc, Line((0, 1, 0), (1, 1, 0), layer="HIDDEN"))
    frozen = _added(doc, Line((0, 2, 0), (1, 2, 0), layer="ICE"))
    assert sync.display_specs(visible, doc)[0]["hide"] is False
    assert sync.display_specs(off, doc)[0]["hide"] is True
    assert sync.display_specs(frozen, doc)[0]["hide"] is True
    # aci follows the layer table (WALLS=1 red, HIDDEN=5 blue, ICE=3 green)
    assert sync.display_specs(visible, doc)[0]["aci"] == 1
    assert sync.display_specs(off, doc)[0]["aci"] == 5


# ---------------------------------------------------------------------------
# ACI palette sanity (colors.py)
# ---------------------------------------------------------------------------

def test_aci_table_complete():
    assert sorted(ACI_TABLE) == list(range(1, 256))


def test_aci_classic_first_nine():
    assert aci_to_rgb(1) == (1.0, 0.0, 0.0)
    assert aci_to_rgb(2) == (1.0, 1.0, 0.0)
    assert aci_to_rgb(3) == (0.0, 1.0, 0.0)
    assert aci_to_rgb(4) == (0.0, 1.0, 1.0)
    assert aci_to_rgb(5) == (0.0, 0.0, 1.0)
    assert aci_to_rgb(6) == (1.0, 0.0, 1.0)
    assert aci_to_rgb(7) == (1.0, 1.0, 1.0)
    assert aci_to_rgb(8) == (128 / 255.0,) * 3
    assert aci_to_rgb(9) == (192 / 255.0,) * 3


def test_aci_grayscale_ramp_250_255():
    ramp = [aci_to_rgb(i) for i in range(250, 256)]
    for r, g, b in ramp:
        assert r == g == b                       # grayscale
    values = [c[0] for c in ramp]
    assert values == sorted(values)             # monotone dark -> light
    assert ramp[0] == (0.0, 0.0, 0.0)           # 250 = black
    assert ramp[-1] == (1.0, 1.0, 1.0)          # 255 = white


def test_aci_hue_wheel_is_distinct_and_deterministic():
    assert aci_to_rgb(10) != aci_to_rgb(30) != aci_to_rgb(90)
    assert aci_to_rgb(10) == aci_to_rgb(10)      # deterministic
    # same hue group, one brightness step down: 10 vs 12 (both reds)
    assert aci_to_rgb(10)[0] > aci_to_rgb(12)[0]


def test_aci_out_of_range_raises():
    for bad in (0, -1, 256, None, "x", "7"):
        with pytest.raises(ValueError):
            aci_to_rgb(bad)


# ---------------------------------------------------------------------------
# space → collection name mapping
# ---------------------------------------------------------------------------

def test_space_collection_names():
    assert sync.space_collection_name("MODEL") == "BlenderCAD"
    assert sync.space_collection_name("Sheet1") == "BlenderCAD/Layout Sheet1"
    assert sync.COLLECTION_NAME == "BlenderCAD"
    assert sync.LAYOUT_COLLECTION_PREFIX == "BlenderCAD/Layout "


# ---------------------------------------------------------------------------
# dimension regen glue (bcdraw feature-detection)
# ---------------------------------------------------------------------------

def test_refresh_document_dims_zero_for_dimless_doc(doc):
    # the feature-detected helper: a doc without dims refreshes nothing and
    # never raises (pre-W-C it was a no-op import guard; post-W-C the regen
    # runs and reports 0 refreshed for this dim-less fixture)
    assert sync.refresh_document_dims(doc) == 0
    assert sync.refresh_document_dims(None) == 0


def test_refresh_document_dims_uses_bcdraw_when_present(doc):
    regen = pytest.importorskip(
        "bcdraw.regen", reason="requires W-C integration (bcdraw.regen)")
    assert hasattr(regen, "refresh_document")
    assert sync.refresh_document_dims(doc) >= 0
