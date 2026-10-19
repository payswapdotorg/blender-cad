"""Golden-value tests for the dimension geometry engine (contracts §5.1).

Hand-computed cases, asserted EXACTLY where every value is a binary
fraction (horizontal / vertical / reversed / dimscale) and via
pytest.approx for the irrational 30°-rotated and 45°-aligned cases
(values derived analytically, printed with full precision).

Standard style (bcdoc defaults): dimexo=0.625, dimexe=1.25, dimasz=2.5,
dimtxt=2.5, dimscale=1. Chevron wing half-spread = 0.25 * dimasz = 0.625.
"""

import math

import pytest

from bcdoc.document import Document
from bcdoc.entities import Circle, Line, Dim
from bcdoc.settings import Settings
from bcdoc.styles import DimStyleRecord
from bcdraw.dims import (
    DimensionGeometry,
    aligned_geometry,
    linear_geometry,
    resolve_dimension,
)


def settings(**changes):
    """A Settings object with the given overrides (shared with test_formats)."""
    store = Settings()
    for name, value in changes.items():
        store.set(name, value)
    return store


STD = DimStyleRecord("Standard")


def test_horizontal_dimension_golden_exact():
    """Dim (0,0)-(10,0) measured horizontally, placed at (5,3)."""
    g = linear_geometry((0, 0, 0), (10, 0, 0), 0.0, (5, 3, 0), STD, settings())
    assert isinstance(g, DimensionGeometry)
    assert g.measurement == 10.0
    assert g.dim_line_p1 == (0.0, 3.0, 0.0)
    assert g.dim_line_p2 == (10.0, 3.0, 0.0)
    assert g.ext1 == ((0.0, 0.625, 0.0), (0.0, 4.25, 0.0))
    assert g.ext2 == ((10.0, 0.625, 0.0), (10.0, 4.25, 0.0))
    assert g.arrow1 == [(0.0, 3.0, 0.0), (2.5, 3.625, 0.0), (2.5, 2.375, 0.0)]
    assert g.arrow2 == [(10.0, 3.0, 0.0), (7.5, 3.625, 0.0), (7.5, 2.375, 0.0)]
    assert g.text_point == (5.0, 4.25, 0.0)
    assert g.text_value == "10.0000"


def test_vertical_dimension_golden_exact():
    """Dim (0,0)-(0,10) measured vertically, placed at (3,5).

    approx rather than == only because cos(90°) is 6.1e-17 in floating
    point, so the 3.0 comes out as 2.9999999999999996 — the construction
    itself is exact math over the axis trigonometry.
    """
    g = linear_geometry((0, 0, 0), (0, 10, 0), 90.0, (3, 5, 0), STD, settings())
    assert g.measurement == pytest.approx(10.0)
    assert g.dim_line_p1 == pytest.approx((3.0, 0.0, 0.0))
    assert g.dim_line_p2 == pytest.approx((3.0, 10.0, 0.0))
    # extension lines run horizontally toward the dim line (x = 3)
    assert g.ext1[0] == pytest.approx((0.625, 0.0, 0.0))
    assert g.ext1[1] == pytest.approx((4.25, 0.0, 0.0))
    assert g.ext2[0] == pytest.approx((0.625, 10.0, 0.0))
    assert g.ext2[1] == pytest.approx((4.25, 10.0, 0.0))
    assert g.arrow1[0] == pytest.approx((3.0, 0.0, 0.0))
    assert g.arrow1[1] == pytest.approx((2.375, 2.5, 0.0))
    assert g.arrow1[2] == pytest.approx((3.625, 2.5, 0.0))
    assert g.arrow2[0] == pytest.approx((3.0, 10.0, 0.0))
    assert g.arrow2[1] == pytest.approx((2.375, 7.5, 0.0))
    assert g.arrow2[2] == pytest.approx((3.625, 7.5, 0.0))
    assert g.text_point == pytest.approx((1.75, 5.0, 0.0))  # left of travel
    assert g.text_value == "10.0000"


def test_dimension_below_the_measured_line_golden_exact():
    """Placement on the -normal side flips the ext-line signs; the text
    stays on the LEFT-of-travel side (pinned rule, documented)."""
    g = linear_geometry((0, 0, 0), (10, 0, 0), 0.0, (5, -3, 0), STD, settings())
    assert g.dim_line_p1 == (0.0, -3.0, 0.0)
    assert g.ext1 == ((0.0, -0.625, 0.0), (0.0, -4.25, 0.0))
    assert g.ext2 == ((10.0, -0.625, 0.0), (10.0, -4.25, 0.0))
    assert g.text_point == (5.0, -1.75, 0.0)


def test_reversed_points_flip_travel_golden_exact():
    """Swapping p1/p2 flips the q1->q2 travel direction (arrows + text
    follow); the measurement stays positive (|projection|)."""
    g = linear_geometry((10, 0, 0), (0, 0, 0), 0.0, (5, 3, 0), STD, settings())
    assert g.measurement == 10.0
    assert g.dim_line_p1 == (10.0, 3.0, 0.0)
    assert g.dim_line_p2 == (0.0, 3.0, 0.0)
    assert g.arrow1 == [(10.0, 3.0, 0.0), (7.5, 2.375, 0.0), (7.5, 3.625, 0.0)]
    assert g.arrow2 == [(0.0, 3.0, 0.0), (2.5, 2.375, 0.0), (2.5, 3.625, 0.0)]
    assert g.text_point == (5.0, 1.75, 0.0)
    assert g.text_value == "10.0000"


def test_vertical_measurement_of_a_horizontal_line_is_zero():
    g = linear_geometry((0, 0, 0), (10, 0, 0), 90.0, (3, 5, 0), STD, settings())
    # |projection| is 0 up to the cos(90°)=6.1e-17 float residue
    assert g.measurement == pytest.approx(0.0, abs=1e-12)
    assert g.text_value == "0.0000"
    # both feet coincide: the dim line degenerates to a point
    assert g.dim_line_p1 == pytest.approx(g.dim_line_p2)


def test_rotated_30_degrees_golden_approx():
    g = linear_geometry((0, 0, 0), (10, 0, 0), 30.0, (5, 3, 0), STD, settings())
    assert g.measurement == pytest.approx(10.0 * math.cos(math.radians(30.0)))
    assert g.text_value == "8.6603"
    assert g.dim_line_p1 == pytest.approx((-0.04903810567665822,
                                           0.08493649053890384, 0.0))
    assert g.dim_line_p2 == pytest.approx((7.450961894323342,
                                           4.415063509461097, 0.0))
    # ext lines start dimexo off the measured point along the axis normal
    cos30, sin30 = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
    n = (-sin30, cos30)
    assert g.ext1[0] == pytest.approx((0.0 + n[0] * 0.625, 0.0 + n[1] * 0.625, 0.0))
    # ... and end dimexe past the dim line foot
    assert g.ext1[1] == pytest.approx(
        (g.dim_line_p1[0] + n[0] * 1.25, g.dim_line_p1[1] + n[1] * 1.25, 0.0))
    # arrows: tips on the dim-line ends, chevrons parallel to the axis
    assert g.arrow1[0] == pytest.approx(g.dim_line_p1)
    assert g.arrow2[0] == pytest.approx(g.dim_line_p2)
    wing_base = (g.dim_line_p1[0] + 2.5 * cos30, g.dim_line_p1[1] + 2.5 * sin30)
    for wing in g.arrow1[1:]:
        assert math.hypot(wing[0] - wing_base[0], wing[1] - wing_base[1]) \
            == pytest.approx(0.625)
    assert g.text_point == pytest.approx((3.075961894323342,
                                          3.3325317547305486, 0.0))


def test_aligned_45_degree_diagonal_golden_approx():
    g = aligned_geometry((0, 0, 0), (10, 10, 0), (12, 2, 0), STD, settings())
    assert g.measurement == pytest.approx(math.sqrt(200.0))
    assert g.text_value == "14.1421"
    assert g.dim_line_p1 == pytest.approx((4.999999999999999, -5.0, 0.0))
    assert g.dim_line_p2 == pytest.approx((15.0, 4.999999999999999, 0.0))
    s2 = math.sqrt(2.0) / 2.0
    # ext1 start = p1 - exo*n (the dim line lies on the -n side here)
    assert g.ext1[0] == pytest.approx((0.0 + s2 * 0.625, 0.0 - s2 * 0.625, 0.0))
    assert g.text_point == pytest.approx((9.116116523516816,
                                          0.883883476483184, 0.0))
    # arrows stay parallel to the diagonal, length dimasz
    travel = (s2, s2)
    assert g.arrow1[0] == pytest.approx(g.dim_line_p1)
    assert g.arrow1[1] == pytest.approx(
        (g.dim_line_p1[0] + 2.5 * travel[0] - 0.625 * s2,
         g.dim_line_p1[1] + 2.5 * travel[1] + 0.625 * s2, 0.0))


def test_aligned_axis_follows_the_measured_pair_not_the_placement():
    # aligned axis = p1 -> p2 direction (here horizontal); a diagonal
    # placement only offsets the dim line, never the measurement axis.
    g = aligned_geometry((0, 0, 0), (10, 0, 0), (4, 4, 0), STD, settings())
    assert g.measurement == 10.0
    assert g.dim_line_p1 == pytest.approx((0.0, 4.0, 0.0))
    assert g.dim_line_p2 == pytest.approx((10.0, 4.0, 0.0))


def test_dimscale_multiplies_sizes_not_measurement():
    scaled = DimStyleRecord("Scaled", dimscale=2.0)
    g = linear_geometry((0, 0, 0), (10, 0, 0), 0.0, (5, 3, 0), scaled, settings())
    assert g.measurement == 10.0            # never scaled
    assert g.ext1 == ((0.0, 1.25, 0.0), (0.0, 5.5, 0.0))   # exo/exe x2
    assert g.arrow1 == [(0.0, 3.0, 0.0), (5.0, 4.25, 0.0), (5.0, 1.75, 0.0)]
    assert g.text_point == (5.0, 5.5, 0.0)  # dimtxt*0.5 x2


def test_style_validation_rejects_bogus_sizing():
    with pytest.raises(ValueError):
        linear_geometry((0, 0, 0), (10, 0, 0), 0.0, (5, 3, 0),
                        DimStyleRecord("Bad", dimscale=0.0), settings())
    with pytest.raises(ValueError):
        linear_geometry((0, 0, 0), (10, 0, 0), 0.0, (5, 3, 0),
                        DimStyleRecord("Bad", dimtxt=-1.0), settings())
    with pytest.raises(ValueError):
        linear_geometry((0, 0, 0), (10, 0, 0), 0.0, (5, 3, 0),
                        DimStyleRecord("Bad", dimexo=-0.5), settings())


# ---------------------------------------------------------------------------
# resolve_dimension — associativity + text resolution
# ---------------------------------------------------------------------------

def _doc_with_line(p1, p2):
    doc = Document(name="DimTest")
    with doc.transaction("setup"):
        line = doc.add_entity(Line(p1, p2))
    return doc, line


def test_resolve_dimension_uses_live_line_endpoints():
    doc, line = _doc_with_line((0, 0, 0), (10, 0, 0))
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=line.id, measurement=10.0)
    geometry, text = resolve_dimension(dim, doc)
    assert geometry.measurement == 10.0
    assert text == "10.0000"

    # MOVE the measured line (journaled) — the dim follows WITHOUT any
    # stored-point change (associativity, FP-ANN-015)
    with doc.transaction("move"):
        doc.update_entity(line.id, p1=(0, 5, 0), p2=(15, 5, 0))
    geometry, text = resolve_dimension(dim, doc)
    assert geometry.measurement == 15.0
    assert text == "15.0000"
    assert geometry.dim_line_p1[1] == pytest.approx(3.0)  # offset_point kept


def test_resolve_dimension_missing_measured_entity_falls_back_to_stored_points():
    doc = Document(name="DimTest")
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id="deadbeef", measurement=10.0)
    geometry, text = resolve_dimension(dim, doc)
    assert geometry.measurement == 10.0
    assert text == "10.0000"


def test_resolve_dimension_non_line_measured_entity_falls_back():
    doc = Document(name="DimTest")
    with doc.transaction("setup"):
        circle = doc.add_entity(Circle((0, 0, 0), 5.0))
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=circle.id, measurement=10.0)
    geometry, _text = resolve_dimension(dim, doc)
    assert geometry.measurement == 10.0  # stored points, not the circle


def test_resolve_dimension_text_override_wins():
    doc, line = _doc_with_line((0, 0, 0), (10, 0, 0))
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              measured_id=line.id, measurement=10.0, text_override="TYP")
    geometry, text = resolve_dimension(dim, doc)
    assert text == "TYP"
    assert geometry.measurement == 10.0  # geometry still measured


def test_resolve_dimension_text_position_override():
    doc = Document(name="DimTest")
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              text_position=(7.0, 9.0, 0.0))
    geometry, _text = resolve_dimension(dim, doc)
    assert geometry.text_point == (7.0, 9.0, 0.0)


def test_resolve_dimension_resolves_aligned_type():
    doc = Document(name="DimTest")
    dim = Dim("aligned", (0, 0, 0), (10, 10, 0), offset_point=(12, 2, 0),
              angle=45.0)  # aligned ignores the stored angle by definition
    geometry, text = resolve_dimension(dim, doc)
    assert geometry.measurement == pytest.approx(math.sqrt(200.0))
    assert text == "14.1421"


def test_resolve_dimension_missing_style_falls_back_to_standard():
    doc = Document(name="DimTest")
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0),
              style="Vanished")  # removed style: Standard sizing, no crash
    geometry, _text = resolve_dimension(dim, doc)
    assert geometry.ext1 == ((0.0, 0.625, 0.0), (0.0, 4.25, 0.0))


def test_resolve_dimension_uses_luprec_from_document_settings():
    doc = Document(name="DimTest")
    doc.settings.set("LUPREC", 2)
    dim = Dim("linear", (0, 0, 0), (10, 0, 0), angle=0.0, offset_point=(5, 3, 0))
    _geometry, text = resolve_dimension(dim, doc)
    assert text == "10.00"
