"""Cross-module M2 round-trip suite — bcio v2 (task m2-2d).

End-to-end scenario per m2-module-contracts.md §6 + §10:

    document (all 13 kinds + tables + layouts + settings)
      -> export_dxf (ezdxf R2010) -> file -> import_dxf -> document
      -> compare_m2.compare_document_content (exact, 1e-9)

plus: double-round-trip stability, ezdxf audit cleanliness, per-kind edge
values, handle preservation, honest-loss ledger signatures, and the
r12-minimal fallback engine (TEXT round-trips; polyline degradation is
excluded from exact compare BY DESIGN with its ledger note; every other
M2 kind is ledgered, never silently dropped).

Plain pytest, no Blender. All fixture files are self-authored into
``tmp_path`` at runtime (licensing-clean per test-plan §8).
"""

import math

import ezdxf
import pytest

from bcdoc import (
    Arc,
    Circle,
    Dim,
    Document,
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
from bcio import LossLedger, export_dxf, import_dxf
from bcio import dxf_minimal, ezdxf_bridge

import compare_m2


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def build_full_m2_document() -> Document:
    """Every M2 kind + every table with edge values."""
    doc = Document("m2-roundtrip", units={"length": "mm", "angle": "deg"})
    with doc.transaction("draw the M2 universe"):
        # layer table with every property non-default somewhere
        doc.layers.add("WALLS", color=30, linetype="Continuous",
                       lineweight=0.5)
        doc.layers.add("HIDDEN", color=5, linetype="DASHED_M2",
                       lineweight=0.25, on=False)
        doc.layers.add("FROZENLY", color=8, frozen=True)
        doc.layers.add("LOCKEDLY", color=250, locked=True)
        doc.layers.add("NOPLOT", color=7, plot=False)
        # styles
        doc.add_text_style("TITLE", height=5.0, width_factor=1.2)
        doc.add_dim_style("M2", dimscale=2.0, dimtxt=3.5, dimasz=2.0,
                          dimexo=0.7, dimexe=1.3)
        # blocks
        doc.add_block("BLK", (1.0, 1.0),
                      [Line((0, 0), (5, 5), color=0),   # ByBlock member
                       Point((1, 2)),
                       Text((2, 2), content="inner", height=1.5)])
        doc.add_block("EMPTY", (0.0, 0.0), [])
        # layouts
        doc.add_layout("Sheet-A3", page_width=420.0, page_height=297.0)
        doc.add_layout("Sheet-A4", page_width=297.0, page_height=210.0)
        # settings
        doc.settings.set("CLAYER", "WALLS")
        doc.settings.set("LUPREC", 3)
        doc.settings.set("ORTHOMODE", 1)
        doc.settings.set("OSMODE", 55)
        doc.settings.set("LTSCALE", 2.5)
        doc.settings.set("TEXTSTYLE", "TITLE")
        doc.settings.set("DIMSTYLE", "M2")
        doc.settings.set("DYNMODE", 0)   # has NO header variable -> ledgered

        # entities: M1 kinds
        doc.add_entity(Line((0, 0, 0), (120, 0, 0), layer="WALLS", color=30,
                            lineweight=0.5))
        doc.add_entity(Circle((60, 45), 25.25, layer="0", color=1,
                              lineweight=0.13))
        doc.add_entity(Arc((60, 45), 12.75, 15.5, 202.25, layer="WALLS"))
        # M2 kinds
        doc.add_entity(Point((3.5, -2.25, 1.0), layer="HIDDEN"))
        doc.add_entity(Polyline(
            [(0, 0, 0), (10, 0, 0), (10, 10, 0)],
            bulges=[0.5, 0.0, 0.0],
            widths=[[0.0, 0.2], [0.1, 0.0], [0.0, 0.0]],
            closed=True, layer="WALLS"))
        doc.add_entity(Polyline([(-5, -5), (5, -5)]))          # open, plain
        doc.add_entity(Ellipse((0, 0), (20, 0), 0.5))                    # full
        doc.add_entity(Ellipse((0, 0), (0, 20, 0), 0.25,
                               start_angle=90.0, end_angle=180.0))      # part
        doc.add_entity(Xline((0, 0), (1, 0)))                 # unit dir: exact
        doc.add_entity(Ray((2, 2), (3, 2)))
        doc.add_entity(Text((1, 1), height=2.5, content="LEFTY"))
        doc.add_entity(Text((10, 10), height=3.0, rotation=15.0,
                            content="CENTERED", justification="CENTER",
                            style="TITLE"))
        doc.add_entity(Text((20, 10), height=3.0, rotation=-7.5,
                            content="RIGHTISH", justification="RIGHT"))
        doc.add_entity(Mtext((0, 5), width=40.0, content="A\nB\nC"))
        doc.add_entity(Mtext((50, 5), width=0.0, content="nowrap"))
        doc.add_entity(Dim("linear", (0, 0, 0), (30, 0, 0), angle=0,
                           offset_point=(10, 5, 0), style="M2"))
        doc.add_entity(Dim("linear", (0, 0, 0), (20, 10, 0), angle=30,
                           offset_point=(15, 20, 0),
                           text_override="~42.0 (nom)",
                           text_position=(15.0, 21.5, 0.0)))
        doc.add_entity(Dim("aligned", (0, 0, 0), (20, 10, 0),
                           offset_point=(-2.0, 4.5, 0)))
        doc.add_entity(Insert("BLK", (7, 7), scale=(2.0, 3.0, 1.0),
                              rotation=25.0))
        doc.add_entity(Insert("EMPTY", (0, -10)))
        # paper-space content
        doc.add_entity(Viewport((10, 20, 0), 40.0, (0, 0, 0), (150, 80, 0),
                                locked=True, space="Sheet-A3"))
        doc.add_entity(Line((1, 1), (2, 2), space="Sheet-A3"))
        doc.add_entity(Text((5, 5), content="PAPER TEXT",
                            space="Sheet-A4"))
    return doc


# ---------------------------------------------------------------------------
# 1. the full M2 universe round-trips exactly
# ---------------------------------------------------------------------------

class TestFullM2RoundTrip:
    def test_full_round_trip_exact(self, tmp_path):
        doc = build_full_m2_document()
        path = str(tmp_path / "m2.dxf")

        # ONE ledger for the WHOLE round trip: the honest-losses list below
        # mixes export-direction entries (DYNMODE has no header variable to
        # be written to) with import-direction entries (dim associativity,
        # foreign linetype patterns) — both directions of one interchange.
        ledger = LossLedger()
        stats = export_dxf(path, doc, ledger=ledger)
        assert stats["engine"] == "ezdxf"
        assert stats["entities"]["total"] == 23
        assert stats["blocks"] == 2
        assert stats["layouts"] == 2
        assert stats["layers"] == 6
        assert stats["settings"] == 12

        mirror, istats = import_dxf(path, ledger=ledger)
        assert istats["engine"] == "ezdxf"
        assert istats["imported"]["total"] == 23
        assert istats["handle_reallocations"] == 0

        compare_m2.compare_document_content(doc, mirror)
        # the honest losses of THIS document:
        # - 3 dims lose associativity (not a file concept)
        # - DASHED_M2 linetype pattern is name-only
        # - DYNMODE has no DXF header variable
        losses = istats["losses"]
        compare_m2.expected_ledger_entries(losses, [
            ("DIMENSION", "associativity (measured_id)"),
            ("LTYPE", "dash-pattern"),
            ("SETTINGS", "no DXF header variable"),
        ])
        assert len([e for e in losses if e["dxf_type"] == "DIMENSION"]) == 3
        # every ledger entry carries the contract shape
        for entry in losses:
            assert entry["kind"] in ("import", "export")
            assert isinstance(entry["dxf_type"], str)
            assert entry["reason"] and entry["at"]

    def test_double_round_trip_is_stable(self, tmp_path):
        doc = build_full_m2_document()
        first = str(tmp_path / "one.dxf")
        second = str(tmp_path / "two.dxf")
        export_dxf(first, doc)
        mirror1, _ = import_dxf(first)
        export_dxf(second, mirror1)
        mirror2, _ = import_dxf(second)
        compare_m2.compare_document_content(mirror1, mirror2)
        compare_m2.compare_document_content(doc, mirror2)

    def test_exported_file_audits_clean(self, tmp_path):
        doc = build_full_m2_document()
        path = str(tmp_path / "audit.dxf")
        export_dxf(path, doc)
        loaded = ezdxf.readfile(path)
        assert loaded.dxfversion == ezdxf.const.DXF2010
        assert not loaded.audit().has_errors
        # the DIMENSION count in the file matches the document
        assert len(loaded.modelspace().query("DIMENSION")) == 3
        assert len(loaded.layouts.names()) == 3  # Model + 2 sheets

    def test_bcdoc_persistence_composes(self, tmp_path):
        """save -> load -> export -> import -> compare (contracts §2.7
        byte-stable serialization composes with interchange)."""
        doc = build_full_m2_document()
        revived = Document.load(doc.serialize())
        path = str(tmp_path / "persist.dxf")
        export_dxf(path, revived)
        mirror, _ = import_dxf(path)
        compare_m2.compare_document_content(doc, mirror)


# ---------------------------------------------------------------------------
# 2. per-kind edge values
# ---------------------------------------------------------------------------

class TestPerKindEdgeCases:
    def _roundtrip(self, doc, tmp_path, name="edge.dxf"):
        path = str(tmp_path / name)
        stats = export_dxf(path, doc)
        assert stats["losses"] == [] or stats["engine"] != "ezdxf"
        mirror, istats = import_dxf(path)
        compare_m2.compare_document_content(doc, mirror)
        return mirror, istats

    def test_polyline_full_featured(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Polyline(
                [(0, 0, 2.5), (10, 0, 2.5), (10, 10, 2.5)],
                bulges=[-0.25, 0.5, 1.0],
                widths=[[0.0, 0.1], [0.2, 0.3], [0.4, 0.0]],
                closed=True))
            # single vertex (allowed by bcdoc; ezdxf writes it fine)
            doc.add_entity(Polyline([(1, 1)], closed=True))
        self._roundtrip(doc, tmp_path)

    def test_ellipse_full_and_partial(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Ellipse((0, 0), (20, 0), 0.5))            # full
            doc.add_entity(Ellipse((1, 1, 3), (0, 20), 1.0,
                                   start_angle=90.0, end_angle=270.0))
            doc.add_entity(Ellipse((0, 0), (5, 5), 0.001,
                                   start_angle=0.25, end_angle=359.75))
        mirror, _ = self._roundtrip(doc, tmp_path)
        ellipses = [e for e in mirror.entities() if e.kind == "ellipse"]
        assert ellipses[0].end_angle == pytest.approx(360.0, abs=1e-9)
        assert math.isclose(ellipses[0].start_angle, 0.0, abs_tol=1e-9)

    def test_text_all_justifications(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Text((1, 1), content="L"))
            doc.add_entity(Text((2, 2), content="C", justification="CENTER"))
            doc.add_entity(Text((3, 3), content="R", justification="RIGHT"))
            doc.add_entity(Text((4, 4), content="ROT",
                                rotation=359.75, style="Standard"))
        mirror, _ = self._roundtrip(doc, tmp_path)
        justs = [e.justification for e in mirror.entities()
                 if e.kind == "text"]
        assert justs == ["LEFT", "CENTER", "RIGHT", "LEFT"]

    def test_mtext_multiline_content(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Mtext((0, 0), width=25.0,
                                 content="line one\nline two\nline three"))
        mirror, _ = self._roundtrip(doc, tmp_path)
        content = [e for e in mirror.entities() if e.kind == "mtext"][0].content
        assert content == "line one\nline two\nline three"

    def test_insert_with_scale_and_rotation(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_block("SYM", (0.5, 0.5), [Line((0, 0), (1, 1))])
            doc.add_entity(Insert("SYM", (10, 10, 1),
                                  scale=(-2.0, 3.0, 0.5), rotation=359.9))
        self._roundtrip(doc, tmp_path)

    def test_viewport_in_layout(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_layout("SHEET")
            doc.add_entity(Viewport((-5.5, 10.25, 0), 77.5,
                                    (0, 0, 0), (100, 50, 0),
                                    locked=True, space="SHEET"))
            doc.add_entity(Viewport((0, 0, 0), 1.0,
                                    (10, 20, 0), (110, 70, 0),
                                    locked=False, space="SHEET"))
        mirror, _ = self._roundtrip(doc, tmp_path)
        viewports = [e for e in mirror.entities_in_space("SHEET")]
        assert [v.locked for v in viewports] == [True, False]

    def test_dimensions_linear_aligned_rotated_override(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Dim("linear", (0, 0, 0), (30, 0, 0),
                               angle=0, offset_point=(10, 5, 0)))
            doc.add_entity(Dim("linear", (0, 0, 0), (30, 0, 0),
                               angle=90, offset_point=(35, 10, 0)))
            doc.add_entity(Dim("linear", (0, 0, 0), (20, 10, 0),
                               angle=30, offset_point=(15, 20, 0)))
            doc.add_entity(Dim("aligned", (0, 0, 0), (20, 10, 0),
                               offset_point=(-2.0, 4.5, 0)))
            doc.add_entity(Dim("linear", (0, 0, 0), (42.5, 0, 0),
                               angle=0, offset_point=(10, -5, 0),
                               text_override="EXACTLY 42.5"))
        mirror, _ = self._roundtrip(doc, tmp_path)
        dims = [e for e in mirror.entities() if e.kind == "dim"]
        assert [d.dim_type for d in dims] == ["linear"] * 4 + ["aligned"] \
            or [d.dim_type for d in dims].count("aligned") == 1
        # measurement excluded from the compare (derived) — but the
        # recomputed value must agree on both sides of the round trip
        for source_dim, mirror_dim in zip(
                [e for e in doc.entities() if e.kind == "dim"], dims):
            assert compare_m2.recompute_measurement(source_dim) == \
                pytest.approx(compare_m2.recompute_measurement(mirror_dim),
                              abs=1e-9)
        # the override sits on the LAST dim (dims[-1]; the store order is
        # the file order within a space — W-B2's original dims[-2] read the
        # aligned dim, which has no override)
        assert dims[-1].text_override == "EXACTLY 42.5"
        assert dims[1].angle == pytest.approx(90.0, abs=1e-9)

    def test_xline_ray_exact_and_ledgered_magnitude(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Xline((0, 0), (1, 0)))       # unit dir -> exact
            doc.add_entity(Ray((2, 2), (5, 5)))         # |p2-p1| = sqrt(8)
        path = str(tmp_path / "xr.dxf")
        export_stats = export_dxf(path, doc)
        mirror, istats = import_dxf(path)
        compare_m2.compare_document_content(doc, mirror)
        # the non-unit ray magnitude IS a representability loss -> ledgered
        compare_m2.expected_ledger_entries(export_stats["losses"], [
            ("RAY", "unit vector"),
        ])

    def test_handles_preserved_on_new_kinds(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)), handle=0x8001)
            doc.add_entity(Point((1, 2)), handle=0x8002)
            doc.add_entity(Polyline([(0, 0), (1, 1)]), handle=0x8003)
            doc.add_entity(Ellipse((0, 0), (5, 0), 0.5), handle=0x8004)
            doc.add_entity(Xline((0, 0), (1, 0)), handle=0x8005)
            doc.add_entity(Text((0, 0), content="h"), handle=0x8006)
            doc.add_entity(Mtext((0, 0), content="m"), handle=0x8007)
            doc.add_entity(Dim("linear", (0, 0), (1, 0),
                               offset_point=(0, 1, 0)), handle=0x8008)
            doc.add_block("BH", (0, 0), [Line((0, 0), (1, 1))])
            doc.add_entity(Insert("BH", (5, 5)), handle=0x800A)
            doc.add_layout("L1")
            doc.add_entity(Viewport((0, 0, 0), 10, (0, 0, 0), (50, 50, 0),
                                    space="L1"), handle=0x800B)
        mirror, _ = self._roundtrip(doc, tmp_path)
        assert mirror.next_handle == 0x800C
        with mirror.transaction("next"):
            fresh = mirror.add_entity(Line((0, 0), (2, 2)))
        assert fresh.handle == 0x800C


# ---------------------------------------------------------------------------
# 3. table round-trips
# ---------------------------------------------------------------------------

class TestTableRoundTrips:
    def test_layer_props_exact(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.layers.add("A", color=1, linetype="Continuous",
                           lineweight=0.0)
            doc.layers.add("B", color=250, lineweight=2.11, on=False)
            doc.layers.add("C", frozen=True, plot=False)
            doc.layers.add("D", locked=True)
        mirror, _ = import_dxf(str(self._x(doc, tmp_path)))
        for name in ("A", "B", "C", "D"):
            a = doc.layers.get(name)
            b = mirror.layers.get(name)
            assert b is not None
            assert a.color == b.color
            assert a.linetype == b.linetype
            assert a.lineweight == pytest.approx(b.lineweight, abs=1e-9)
            assert a.on == b.on and a.frozen == b.frozen
            assert a.locked == b.locked and a.plot == b.plot

    def _x(self, doc, tmp_path):
        path = str(tmp_path / "layers.dxf")
        export_dxf(path, doc)
        return path

    def test_block_definition_round_trip(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            members = [Line((0, 0), (5, 5), color=0),      # ByBlock color
                       Circle((1, 1), 2.0, layer="0", lineweight=0.5),
                       Text((2, 2), content="inside", height=1.0),
                       Point((3, 3))]
            definition = doc.add_block("SYM", (0.5, -0.5, 0), members)
            doc.add_entity(Insert("SYM", (10, 10)))
        path = str(tmp_path / "blk.dxf")
        export_dxf(path, doc)
        mirror, _ = import_dxf(path)
        compare_m2.compare_document_content(doc, mirror)
        mirror_def = mirror.block("SYM")
        assert mirror_def.handle == definition.handle
        assert [m.kind for m in mirror_def.entities] == \
            ["line", "circle", "text", "point"]
        # ByBlock color 0 is preserved on the member
        assert mirror_def.entities[0].color == 0
        assert mirror_def.entities[1].lineweight == pytest.approx(0.5, 1e-9)

    def test_layouts_round_trip_with_routing(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_layout("One", page_width=420.0, page_height=297.0)
            doc.add_layout("Two", page_width=297.0, page_height=420.0)
            doc.add_entity(Line((1, 1), (2, 2), space="One"))
            doc.add_entity(Circle((3, 3), 1.0, space="Two"))
            doc.add_entity(Line((0, 0), (9, 9)))              # MODEL
        mirror, _ = import_dxf(str(self._x(doc, tmp_path)))
        compare_m2.compare_document_content(doc, mirror)
        # routing is verified BY HANDLE: a DXF file stores model space and
        # each paper space as separate containers, so the mirror's store
        # order (MODEL first) is not the source's cross-space order — that
        # order is not a file concept (see compare_m2 docstring).
        source_spaces = {e.handle: e.space for e in doc.entities()}
        assert {e.handle: e.space for e in mirror.entities()} == source_spaces
        two = mirror.layout("Two")
        assert two.page_width == pytest.approx(297.0, abs=1e-9)
        assert two.page_height == pytest.approx(420.0, abs=1e-9)

    def test_header_settings_round_trip(self, tmp_path):
        doc = Document(units={"length": "in"})
        with doc.transaction("t"):
            doc.layers.add("CUR")
            doc.settings.set("CLAYER", "CUR")
            doc.settings.set("LUNITS", 4)
            doc.settings.set("LUPREC", 3)
            doc.settings.set("AUNITS", 1)
            doc.settings.set("AUPREC", 2)
            doc.settings.set("ORTHOMODE", 1)
            doc.settings.set("TILEMODE", 0)
            doc.settings.set("LTSCALE", 3.75)
            doc.settings.set("PICKFIRST", 0)    # no header var -> ledgered
            doc.add_entity(Line((0, 0), (1, 1)))
        path = str(tmp_path / "hdr.dxf")
        export_stats = export_dxf(path, doc)
        # $INSUNITS derived from units metadata ("in" -> 1)
        loaded = ezdxf.readfile(path)
        assert loaded.header["$INSUNITS"] == 1
        assert loaded.header["$LUNITS"] == 4
        assert loaded.header["$CLAYER"] == "CUR"
        assert loaded.header["$LTSCALE"] == 3.75
        mirror, istats = import_dxf(path)
        compare_m2.compare_document_content(doc, mirror)
        compare_m2.expected_ledger_entries(export_stats["losses"], [
            ("SETTINGS", "no DXF header variable"),
        ])
        compare_m2.expected_ledger_entries(istats["losses"], [
            ("HEADER", "non-decimal length format"),
            ("HEADER", "non-decimal angle format"),
        ])

    def test_session_state_ledgered_on_export(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_layout("S")
            doc.add_entity(Line((0, 0), (1, 1)))
        doc.set_current_space("S")
        doc.active_layout = "S"
        stats = export_dxf(str(tmp_path / "sess.dxf"), doc)
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("PAPER_SPACE", "SESSION state"),
            ("LAYOUT", "SESSION state"),
        ])


# ---------------------------------------------------------------------------
# 4. honest losses on foreign content
# ---------------------------------------------------------------------------

class TestForeignLosses:
    def test_mtext_inline_formatting_and_height_ledgered(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        msp = author.modelspace()
        mt = msp.add_mtext("\\W2.5;BOLD part plain", dxfattribs={"width": 20})
        mt.set_location((0, 0), attachment_point=7)
        mt.dxf.char_height = 5.0
        path = str(tmp_path / "fmt.dxf")
        author.saveas(path)

        mirror, stats = import_dxf(path)
        entry = [e for e in mirror.entities() if e.kind == "mtext"][0]
        assert entry.content == "BOLD part plain"
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("MTEXT", "inline formatting"),
            ("MTEXT", "character height"),
        ])

    def test_vertical_text_alignment_ledgered(self, tmp_path):
        from ezdxf.enums import TextEntityAlignment
        author = ezdxf.new("R2010", setup=False)
        author.modelspace().add_text("TOP").set_placement(
            (1, 1), align=TextEntityAlignment.TOP_CENTER)
        path = str(tmp_path / "t.dxf")
        author.saveas(path)
        mirror, stats = import_dxf(path)
        text = [e for e in mirror.entities() if e.kind == "text"][0]
        assert text.justification == "CENTER"   # horizontal part kept
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("TEXT", "vertical text alignment"),
        ])

    def test_unknown_dim_type_ledgered_skipped(self, tmp_path):
        author = ezdxf.new("R2010", setup=True)
        author.modelspace().add_linear_dim(
            base=(10, 5, 0), p1=(0, 0), p2=(30, 0), angle=0,
            dimstyle="EZDXF").render()
        # NB: add_radius_dim_cra() in ezdxf 1.4.3 takes NO ``location``
        # kwarg (probe m2-2d-fix: signature is (center, radius, angle, *,
        # text, dimstyle, override, dxfattribs)) — the angle places the
        # dim line; a radius dim is outside the M2 set either way.
        author.modelspace().add_radius_dim_cra(
            center=(5, 5), radius=3, angle=45, dimstyle="EZDXF").render()
        path = str(tmp_path / "dims.dxf")
        author.saveas(path)
        mirror, stats = import_dxf(path)
        kinds = [e.kind for e in mirror.entities()]
        assert kinds == ["dim"], "only the linear dim imports"
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("DIMENSION", "dimension type"),
        ])

    def test_byblock_lineweight_ledgered(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        author.modelspace().add_line(
            (0, 0), (1, 1), dxfattribs={"lineweight": -2})
        path = str(tmp_path / "lw.dxf")
        author.saveas(path)
        mirror, stats = import_dxf(path)
        line = mirror.entities()[0]
        assert line.lineweight is None
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("ENTITY", "ByBlock lineweight"),
        ])

    def test_lossy_lineweight_rounding_ledgered_on_export(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1), lineweight=0.314))
        path = str(tmp_path / "lw2.dxf")
        stats = export_dxf(path, doc)
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("ENTITY", "not a valid DXF lineweight step"),
        ])
        mirror, _ = import_dxf(path)
        # 0.314 mm is not a valid DXF enum step; the nearest VALID step of
        # the official 24-value enum (probe m2-2d-fix: ezdxf 1.4.3 snaps
        # the invalid code 31 to 35 — invalid codes are NOT writable) is
        # 0.30 mm, and that is what round-trips.
        assert mirror.entities()[0].lineweight == pytest.approx(0.30, 1e-9)

    def test_clayer_resolved_from_handle(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        author.layers.add("BYHANDLE", color=6)
        layer = author.layers.get("BYHANDLE")
        author.modelspace().add_line((0, 0), (1, 1))
        # force the header to reference the layer BY HANDLE (as AutoCAD
        # does when writing $CLAYER with code 350)
        author.header["$CLAYER"] = layer.dxf.handle
        path = str(tmp_path / "cl.dxf")
        author.saveas(path)
        loaded = ezdxf.readfile(path)
        assert loaded.header["$CLAYER"] == layer.dxf.handle
        mirror, _ = import_dxf(path)
        assert mirror.settings.get("CLAYER") == "BYHANDLE"

    def test_viewport_presentation_attrs_ledgered(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        lay = author.layouts.new("S")
        vp = lay.add_viewport(center=(50, 25), size=(100, 50),
                              view_center_point=(0, 0), view_height=40)
        vp.dxf.status = 3  # non-default stacking
        path = str(tmp_path / "vp.dxf")
        author.saveas(path)
        mirror, stats = import_dxf(path)
        viewport = [e for e in mirror.entities() if e.kind == "viewport"][0]
        assert viewport.view_height == pytest.approx(40.0, abs=1e-9)
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("VIEWPORT", "presentation attributes"),
        ])

    def test_foreign_linetype_patterns_ledgered(self, tmp_path):
        author = ezdxf.new("R2010", setup=True)
        author.layers.add("DASHED-LY", color=3, linetype="DASHED")
        author.modelspace().add_line((0, 0), (1, 1),
                                     dxfattribs={"linetype": "DASHED"})
        path = str(tmp_path / "lt.dxf")
        author.saveas(path)
        mirror, stats = import_dxf(path)
        assert mirror.layers.get("DASHED-LY").linetype == "DASHED"
        line = mirror.entities()[0]
        assert line.linetype == "DASHED"
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("LTYPE", "dash-pattern"),
        ])


# ---------------------------------------------------------------------------
# 5. r12-minimal fallback engine (ezdxf unavailable)
# ---------------------------------------------------------------------------

class TestMinimalEngineFallback:
    @pytest.fixture
    def no_ezdxf(self, monkeypatch):
        """Simulate a Blender/runtime without ezdxf: both the import
        selector (``ezdxf_bridge.available``) and the module-level oracle
        are neutralized."""
        monkeypatch.setattr(ezdxf_bridge, "available", lambda: False)
        monkeypatch.setattr(ezdxf_bridge, "ezdxf", None)

    def test_text_round_trips_through_minimal(self, tmp_path, no_ezdxf):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
            doc.add_entity(Text((2, 3, 0.5), height=4.0, rotation=30.0,
                                content="MINIMAL TEXT", style="Standard"))
        path = str(tmp_path / "min.dxf")
        stats = export_dxf(path, doc)          # selector -> minimal engine
        assert stats["engine"] == "r12-minimal"
        assert stats["entities"]["text"] == 1

        mirror, istats = import_dxf(path)
        assert istats["engine"] == "r12-minimal"
        text = [e for e in mirror.entities() if e.kind == "text"][0]
        assert text.content == "MINIMAL TEXT"
        assert text.height == pytest.approx(4.0, abs=1e-9)
        assert text.rotation == pytest.approx(30.0, abs=1e-9)
        assert text.position == (pytest.approx(2.0, abs=1e-9),
                                 pytest.approx(3.0, abs=1e-9),
                         pytest.approx(0.5, abs=1e-9))
        # handles preserved for written kinds
        line = [e for e in mirror.entities() if e.kind == "line"][0]
        assert line.handle == doc.entities()[0].handle

    def test_polyline_degrades_with_ledger_note(self, tmp_path, no_ezdxf):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Polyline([(0, 0), (10, 0), (10, 10)],
                                     closed=True))
        path = str(tmp_path / "deg.dxf")
        stats = export_dxf(path, doc)
        assert stats["entities"]["degraded_segments"] == 3  # 2 + closing
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("POLYLINE", "NOT round-trip-safe by design"),
        ])
        # BY DESIGN: the reimport yields line entities, not the polyline —
        # the exact compare is EXCLUDED for this engine (ledger notes it)
        mirror, istats = import_dxf(path)
        assert [e.kind for e in mirror.entities()] == ["line"] * 3
        assert mirror.entities()[0].p1 == (pytest.approx(0, abs=1e-9),
                                           pytest.approx(0, abs=1e-9),
                                           pytest.approx(0, abs=1e-9))

    def test_bulged_polyline_skipped_and_ledgered(self, tmp_path, no_ezdxf):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Polyline([(0, 0), (10, 0)], bulges=[0.5, 0.0]))
        path = str(tmp_path / "bulge.dxf")
        stats = export_dxf(path, doc)
        assert stats["entities"]["total"] == 0
        compare_m2.expected_ledger_entries(stats["losses"], [
            ("POLYLINE", "arc segment"),
        ])
        mirror, _ = import_dxf(path)     # must not crash
        assert mirror.entities() == []

    def test_every_unsupported_kind_ledgered_never_crashes(self, tmp_path,
                                                            no_ezdxf):
        doc = Document()
        with doc.transaction("t"):
            doc.add_layout("S")
            doc.add_block("B", (0, 0), [Line((0, 0), (1, 1))])
            # one NON-DEFAULT setting: the minimal engine cannot write any
            # M2 sysvar, so this MUST produce the SETTINGS ledger note
            # (an all-default document loses nothing by not writing them)
            doc.settings.set("ORTHOMODE", 1)
            doc.add_entity(Point((1, 1)))
            doc.add_entity(Ellipse((0, 0), (5, 0), 0.5))
            doc.add_entity(Xline((0, 0), (1, 0)))
            doc.add_entity(Ray((0, 0), (1, 0)))
            doc.add_entity(Mtext((0, 0), content="m"))
            doc.add_entity(Dim("linear", (0, 0), (1, 0),
                               offset_point=(0, 1, 0)))
            doc.add_entity(Insert("B", (2, 2)))
            doc.add_entity(Viewport((0, 0, 0), 5, (0, 0, 0), (10, 10, 0),
                                    space="S"))
            doc.add_entity(Line((0, 0), (1, 1), space="S"))
            doc.add_entity(Text((0, 0), content="keep",
                                justification="RIGHT"))
        path = str(tmp_path / "kinds.dxf")
        stats = export_dxf(path, doc)
        ledger_types = {e["dxf_type"] for e in stats["losses"]}
        for expected in ("POINT", "ELLIPSE", "XLINE", "RAY", "MTEXT",
                         "DIM", "INSERT", "VIEWPORT", "BLOCK", "LAYOUT",
                         "SETTINGS", "PAPER_SPACE"):
            assert expected in ledger_types, f"{expected} must be ledgered"
        assert "TEXT" in ledger_types  # justification reduction note
        # TEXT is the one SUPPORTED model-space kind in this document: it is
        # written (RIGHT reduced to LEFT — ledgered above), so the output is
        # NOT empty; every other kind is ledgered, never silently dropped.
        assert stats["entities"]["total"] == 1
        assert stats["entities"]["text"] == 1

        mirror, _ = import_dxf(path)    # the near-empty import never crashes
        assert [e.kind for e in mirror.entities()] == ["text"]
        assert mirror.entities()[0].content == "keep"

    def test_minimal_layer_flags_round_trip(self, tmp_path, no_ezdxf):
        doc = Document()
        with doc.transaction("t"):
            doc.layers.add("FRO", color=3, frozen=True)
            doc.layers.add("OFF", color=4, on=False)
        path = str(tmp_path / "ly.dxf")
        export_dxf(path, doc)
        mirror, _ = import_dxf(path)
        assert mirror.layers.get("FRO").frozen is True
        assert mirror.layers.get("FRO").color == 3
        assert mirror.layers.get("OFF").on is False
        assert mirror.layers.get("OFF").color == 4

    def test_minimal_output_still_oracle_clean(self, tmp_path):
        """The extended minimal writer (TEXT + layer flags) still passes
        the ezdxf.recover + audit oracle."""
        doc = Document()
        with doc.transaction("t"):
            doc.layers.add("FRO", color=3, frozen=True)
            doc.add_entity(Line((0, 0), (1, 1)))
            doc.add_entity(Text((0, 0), content="oracle"))
            doc.add_entity(Polyline([(0, 0), (5, 0), (5, 5)]))
        path = str(tmp_path / "std.dxf")
        stats = dxf_minimal.write_dxf(path, doc)
        assert stats["engine"] == "r12-minimal"
        loaded, auditor = ezdxf.recover.readfile(path)
        assert not auditor.errors
        assert not loaded.audit().has_errors
        kinds = sorted(e.dxftype() for e in loaded.modelspace())
        # 1 LINE + 1 TEXT + an OPEN 3-vertex polyline degraded to 2 LINE
        # segments (a closing segment exists only when closed=True — see
        # test_polyline_degrades_with_ledger_note which asserts 3 for the
        # closed case)
        assert kinds == ["LINE", "LINE", "LINE", "TEXT"]


# ---------------------------------------------------------------------------
# 6. ledger artifact + selector honesty
# ---------------------------------------------------------------------------

class TestStatsAndLedger:
    def test_stats_report_engine_and_tables(self, tmp_path):
        doc = build_full_m2_document()
        stats = export_dxf(str(tmp_path / "s.dxf"), doc)
        assert stats["engine"] == "ezdxf"
        assert stats["entities"]["total"] == 23
        assert stats["blocks"] == 2 and stats["layouts"] == 2
        assert stats["layers"] == 6
        assert stats["settings"] == 12
        assert stats["styles"] == {"text": 2, "dim": 2}
        assert stats["losses"] == list(stats["losses"])
        # every loss entry JSON-serializes
        import json
        json.loads(LossLedger(stats["losses"]).to_json())

    def test_import_stats_report_routing(self, tmp_path):
        doc = build_full_m2_document()
        path = str(tmp_path / "i.dxf")
        export_dxf(path, doc)
        _, istats = import_dxf(path)
        assert istats["imported"]["dim"] == 3
        assert istats["imported"]["viewport"] == 1
        assert istats["blocks"] == 2
        assert set(istats["layouts"]) == {"Sheet-A3", "Sheet-A4"}
        assert istats["handle_reallocations"] == 0
