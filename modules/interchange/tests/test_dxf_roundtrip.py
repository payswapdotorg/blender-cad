"""bcio DXF round-trip tests (M1 contracts §7 + M2 contract §6; TP-CAT-04
precursor).

Scenarios (plain pytest, ezdxf IS installed in this environment and is
therefore the exercised engine; the pure-Python R12 path is forced
simulated-unavailable through ``bcio.ezdxf_bridge.available`` patches and
exercised directly through ``bcio.dxf_minimal``):

1. document -> export (ezdxf R2010) -> import -> kinds/geometry/handles/
   layers preserved (1e-9 tolerance), file passes ``doc.audit()``;
2. R12-minimal writer -> reader round-trip, validated with
   ``ezdxf.recover.readfile`` + ``doc.audit()`` (standard-compliance
   oracle);
3. loss ledger: an ezdxf-authored file with unsupported entity types
   (SPLINE/SOLID) imports without crashing, ledgered — never silently
   dropped; layer properties round-trip since bcdoc v2 (the M1
   names-only ledger expectation is lifted by contract §2.2/§14);
4. handle-collision honesty: re-importing the same file into one
   document reallocates every colliding handle and ledgered each one;
5. color mapping: DXF 0/256 (ByBlock/ByLayer) -> None, else ACI int.

The M2 kind set (13 kinds, tables, layouts, settings) is covered by
test_dxf_m2.py + modules/testing/roundtrip/test_roundtrip_m2.py.
"""

import ezdxf
import ezdxf.recover
import pytest

import bcio
from bcdoc import Arc, Circle, Document, Line
from bcio import LossLedger, export_dxf, import_dxf
from bcio import dxf_minimal, ezdxf_bridge


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def build_sample_document():
    doc = Document("roundtrip-sample")
    with doc.transaction("draw"):
        doc.add_layer("WALLS")
        doc.add_entity(Line((0, 0, 0), (10, 0, 0), layer="0", color=1))
        doc.add_entity(Line((0, 0), (0, 7), layer="WALLS", color=30))
        doc.add_entity(Circle((5, 3), 2.5, layer="WALLS", color=140))
        doc.add_entity(Arc((2.5, 2.5), 1.75, 15.5, 202.25, layer="0"))
    return doc


def kind_counts(**overrides):
    """The additive v2 stats shape: per-kind counts for all 13 kinds +
    total (M1 keys kept, M2 keys added — contract §6)."""
    counts = {kind: 0 for kind in bcio.KINDS}
    counts.update(overrides)
    counts["total"] = sum(counts[k] for k in bcio.KINDS)
    return counts


def geometry_values(entity):
    values = []
    for field_value in entity.geometry_dict().values():
        if isinstance(field_value, tuple):
            values.extend(field_value)
        else:
            values.append(field_value)
    return values


def assert_same_entities(source, mirror, approx=1e-9):
    assert [e.kind for e in source.entities()] == [e.kind for e in mirror.entities()]
    for a, b in zip(source.entities(), mirror.entities()):
        assert a.handle == b.handle, "handles must be preserved across the round trip"
        assert a.layer == b.layer
        assert a.color == b.color
        for x, y in zip(geometry_values(a), geometry_values(b)):
            assert abs(x - y) < approx, (a.kind, x, y)


# ---------------------------------------------------------------------------
# 1. ezdxf-engine round trip
# ---------------------------------------------------------------------------

class TestEzdxfEngineRoundTrip:
    def test_round_trip_preserves_content(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "rt.dxf")

        stats = export_dxf(path, doc)
        assert stats["engine"] == "ezdxf", "ezdxf is installed — it must be the engine"
        assert stats["entities"] == kind_counts(line=2, circle=1, arc=1)
        assert stats["losses"] == [], "no losses are expected for v0 content"

        mirror, istats = import_dxf(path)
        assert istats["engine"] == "ezdxf"
        assert istats["imported"] == kind_counts(line=2, circle=1, arc=1)
        assert istats["handle_reallocations"] == 0
        for layer in ("0", "WALLS"):
            assert layer in mirror.layers, "layers must survive the round trip"
        assert_same_entities(doc, mirror)

    def test_exported_file_is_ezdxf_clean(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "clean.dxf")
        export_dxf(path, doc)
        loaded = ezdxf.readfile(path)
        assert loaded.dxfversion == ezdxf.const.DXF2010
        assert not loaded.audit().has_errors, "exported file must audit clean"

    def test_insunits_written_from_unit_metadata(self, tmp_path):
        doc = Document("units", units={"length": "mm"})
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
        path = str(tmp_path / "units.dxf")
        export_dxf(path, doc)
        loaded = ezdxf.readfile(path)
        assert loaded.header["$INSUNITS"] == 4  # millimeters

    def test_import_into_existing_document_single_transaction(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "rt.dxf")
        export_dxf(path, doc)
        source_version = doc.doc_version
        target = Document("target")
        target_version_before = target.doc_version
        _, stats = import_dxf(path, doc=target)
        assert target.doc_version == target_version_before + 1, (
            "an import must be exactly ONE committed transaction"
        )
        assert doc.doc_version == source_version, (
            "exporting/ importing must never mutate the source document"
        )
        assert len(target.entities()) == len(doc.entities())
        assert stats["imported"]["total"] == 4
        # exactly one undo step brings the target back to its pre-import state
        assert target.undo_depth() == 1
        assert target.undo()
        assert target.entities() == [] and target.layers == ["0"]

    def test_import_undoable_as_one_step(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "rt.dxf")
        export_dxf(path, doc)
        target = Document("target")
        import_dxf(path, doc=target)
        layers_before = list(target.layers)
        assert target.undo()
        assert target.entities() == []
        assert list(target.layers) == ["0"]
        assert target.redo()
        assert [e.kind for e in target.entities()] == ["line", "line", "circle", "arc"]
        assert list(target.layers) == layers_before


# ---------------------------------------------------------------------------
# 2. minimal R12 engine (forced directly)
# ---------------------------------------------------------------------------

class TestMinimalR12Engine:
    def test_write_read_round_trip(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "min.dxf")

        stats = dxf_minimal.write_dxf(path, doc)
        assert stats["engine"] == "r12-minimal"
        assert stats["entities"]["total"] == 4
        assert stats["dxfversion"] == "AC1009"

        raw = dxf_minimal.read_dxf(path)
        assert raw["acadver"] == "AC1009"
        assert {rec["type"] for rec in raw["entities"]} == {"LINE", "CIRCLE", "ARC"}
        assert len(raw["entities"]) == 4
        layer_names = {rec["name"] for rec in raw["layers"]}
        assert {"0", "WALLS"} <= layer_names

        # raw records match the document (geometry 1e-9, handles preserved)
        by_handle = {}
        for rec in raw["entities"]:
            by_handle[rec["handle"]] = rec
        for entity in doc.entities():
            rec = by_handle[entity.handle]
            assert rec["layer"] == entity.layer
            assert rec["color"] == entity.color
            if entity.kind == "line":
                for x, y in zip(list(entity.p1) + list(entity.p2),
                                list(rec["p1"]) + list(rec["p2"])):
                    assert abs(x - y) < 1e-9
            elif entity.kind == "circle":
                for x, y in zip(list(entity.center) + [entity.radius],
                                list(rec["center"]) + [rec["radius"]]):
                    assert abs(x - y) < 1e-9
            else:
                for x, y in zip(
                    list(entity.center) + [entity.radius, entity.start_angle, entity.end_angle],
                    list(rec["center"]) + [rec["radius"], rec["start_angle"], rec["end_angle"]],
                ):
                    assert abs(x - y) < 1e-9

    def test_minimal_file_is_standard_compliant_for_ezdxf(self, tmp_path):
        """The R12 output must load and audit clean through the oracle."""
        doc = build_sample_document()
        path = str(tmp_path / "standard.dxf")
        dxf_minimal.write_dxf(path, doc)

        loaded, auditor = ezdxf.recover.readfile(path)
        assert loaded.dxfversion == ezdxf.const.DXF12
        assert not auditor.errors, "ezdxf.recover reported issues"
        assert not loaded.audit().has_errors, "the minimal R12 file must audit clean"
        kinds = sorted(e.dxftype() for e in loaded.modelspace())
        assert kinds == ["ARC", "CIRCLE", "LINE", "LINE"]

    def test_minimal_file_header_content(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
        path = str(tmp_path / "hdr.dxf")
        dxf_minimal.write_dxf(path, doc)
        loaded, _ = ezdxf.recover.readfile(path)
        assert loaded.dxfversion == ezdxf.const.DXF12
        # R12 predates $INSUNITS — the reader must not find one
        assert "INSUNITS" not in loaded.header
        # group-5 handles were requested via $HANDLING=1 and are present
        entity = list(loaded.modelspace())[0]
        assert int(entity.dxf.handle, 16) == 4097

    def test_minimal_reader_tolerates_unknown_content(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        msp = author.modelspace()
        msp.add_line((0, 0), (1, 1))
        msp.add_text("hello")  # supported by the r12-minimal reader since M2
        msp.add_point((5, 5))   # NOT supported by the minimal engine
        author.layers.add("EXTRA", color=3)
        path = str(tmp_path / "mixed.dxf")
        author.saveas(path)

        ledger = LossLedger()
        raw = dxf_minimal.read_dxf(path, ledger)
        assert [rec["type"] for rec in raw["entities"]] == ["LINE", "TEXT"], (
            "TEXT imports through the minimal reader at M2; the POINT must not"
        )
        assert any(
            entry["dxf_type"] == "POINT" and entry["kind"] == "import"
            for entry in ledger
        ), "the dropped POINT must be ledgered"
        layer_names = {rec["name"] for rec in raw["layers"]}
        assert "EXTRA" in layer_names, "unknown tables entries are still parsed"


# ---------------------------------------------------------------------------
# 3. loss ledger honesty
# ---------------------------------------------------------------------------

class TestLossLedger:
    def test_unsupported_entity_ledgered_not_crashed(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        author.layers.add("WALLS", color=5)
        msp = author.modelspace()
        msp.add_line((0, 0), (12, 0), dxfattribs={"layer": "WALLS", "color": 2})
        msp.add_circle((3, 3), 1.5)
        msp.add_spline([(0, 0), (1, 1), (2, 0)])          # outside the M2 set
        msp.add_solid([(0, 0), (1, 0), (1, 1), (0, 1)])   # outside the M2 set
        path = str(tmp_path / "lossy.dxf")
        author.saveas(path)

        doc, stats = import_dxf(path)
        assert stats["imported"] == kind_counts(line=1, circle=1)
        ledger_types = {entry["dxf_type"] for entry in stats["losses"]}
        assert "SPLINE" in ledger_types
        assert "SOLID" in ledger_types
        assert {e.kind for e in doc.entities()} == {"line", "circle"}
        assert "WALLS" in doc.layers
        # ledger entries carry the full contract shape
        for entry in stats["losses"]:
            assert entry["kind"] in ("import", "export")
            assert isinstance(entry["dxf_type"], str)
            assert isinstance(entry["reason"], str) and entry["reason"]
            assert entry["at"]

    def test_ledger_json_serializable(self, tmp_path):
        author = ezdxf.new("R2010", setup=False)
        author.modelspace().add_spline([(0, 0), (1, 1), (2, 0)])
        path = str(tmp_path / "t.dxf")
        author.saveas(path)
        _, stats = import_dxf(path)
        ledger = LossLedger(stats["losses"])
        payload = ledger.to_json()
        import json

        json.loads(payload)  # must be valid JSON

    def test_layer_properties_round_trip_since_v2(self, tmp_path):
        """bcdoc v2 has a full layer table (contract §2.2): the M1
        names-only limitation (and its ledger entry) is LIFTED — foreign
        layer records import WITH their properties and no longer lose."""
        author = ezdxf.new("R2010", setup=True)  # setup: the LTYPE table must
        # actually define DASHED so the fixture itself is a well-formed file
        author.layers.add("FANCY", color=3, linetype="DASHED", lineweight=35)
        fancy = author.layers.get("FANCY")
        fancy.freeze()
        author.modelspace().add_line((0, 0), (1, 1))
        path = str(tmp_path / "fancy.dxf")
        author.saveas(path)

        doc, stats = import_dxf(path)
        assert "FANCY" in doc.layers
        record = doc.layers.get("FANCY")
        assert record.color == 3
        assert record.linetype == "DASHED"
        assert record.lineweight == 0.35  # enum 35 -> 0.35 mm
        assert record.frozen is True
        # the dash PATTERN (not the name) is the honest v2 loss
        entry = [e for e in stats["losses"] if e["dxf_type"] == "LTYPE"]
        assert entry, "linetype pattern data must be ledgered (names only)"
        assert not [e for e in stats["losses"] if e["dxf_type"] == "LAYER"], (
            "layer records themselves round-trip losslessly since bcdoc v2"
        )

    def test_no_losses_for_supported_content(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "pure.dxf")
        export_dxf(path, doc)
        _, stats = import_dxf(path)
        # ezdxf writes layer records with default color/linetype — no loss
        assert stats["losses"] == []
        assert stats["recovered"] is False


# ---------------------------------------------------------------------------
# 4. handle-collision honesty
# ---------------------------------------------------------------------------

class TestHandleCollisions:
    def test_double_import_reallocates_and_ledgers(self, tmp_path):
        doc = build_sample_document()
        path = str(tmp_path / "twice.dxf")
        export_dxf(path, doc)

        target = Document("target")
        import_dxf(path, doc=target)
        assert target.count_by_kind() == doc.count_by_kind()

        _, second = import_dxf(path, doc=target)
        assert second["handle_reallocations"] == 4, "every handle collides on re-import"
        assert second["imported"]["total"] == 4, "content still imports — never dropped"
        assert len(second["losses"]) >= 4
        collision_entries = [
            e for e in second["losses"] if "collides" in e["reason"]
        ]
        assert len(collision_entries) == 4

        handles = [e.handle for e in target.entities()]
        assert len(set(handles)) == 8, "all document handles must be unique"
        assert all(h >= 4097 for h in handles)

    def test_preserved_handles_advance_next_handle(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)), handle=0x8000)
        path = str(tmp_path / "high.dxf")
        export_dxf(path, doc)

        mirror, _ = import_dxf(path)
        assert mirror.entities()[0].handle == 0x8000
        assert mirror.next_handle == 0x8001
        with mirror.transaction("next"):
            fresh = mirror.add_entity(Line((0, 0), (2, 2)))
        assert fresh.handle == 0x8001


# ---------------------------------------------------------------------------
# 5. color mapping + stats honesty
# ---------------------------------------------------------------------------

class TestColorAndStats:
    def test_byblock_bylayer_map_to_none(self):
        # M1 treated DXF 0 (ByBlock) as unrepresentable; bcdoc v2 models
        # color 0 = ByBlock (contract §2.1/§6 — block members keep it), so
        # 0 now maps through UNCHANGED; only 256 (ByLayer) / absent -> None.
        assert ezdxf_bridge._aci_color(0) == 0
        assert ezdxf_bridge._aci_color(256) is None
        assert ezdxf_bridge._aci_color(None) is None
        assert ezdxf_bridge._aci_color(7) == 7
        assert ezdxf_bridge._aci_color(-3) == -3  # odd but honest passthrough

    def test_stats_report_engine_honestly(self, tmp_path):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
        path = str(tmp_path / "stats.dxf")

        stats = export_dxf(path, doc)
        assert stats["engine"] == "ezdxf"  # ezdxf installed in this env
        assert stats["path"] == path
        assert stats["entities"]["total"] == 1

        if not ezdxf_bridge.available():  # pragma: no cover
            pytest.skip("ezdxf required for the oracle path")
        _, istats = import_dxf(path)
        assert istats["engine"] == "ezdxf"
        assert istats["path"] == path

    def test_corrupt_file_falls_back_and_reports(self, tmp_path):
        """A file ezdxf cannot parse strictly either recovers (reported
        honestly via ``recovered=True``) or falls back to the tolerant
        minimal reader — both outcomes are ledgered, never silent."""
        path = str(tmp_path / "not-a-dxf.dxf")
        with open(path, "w", encoding="ascii") as handle:
            handle.write("this is definitely\nnot a dxf file\n0\nEOF\n")

        doc, stats = import_dxf(path)
        assert stats["imported"]["total"] == 0
        assert stats["engine"] in ("ezdxf", "r12-minimal")
        if stats["engine"] == "ezdxf":
            assert stats["recovered"] is True, "strict parse failed — recovery must be flagged"
            assert any("recover" in e["reason"] for e in stats["losses"])
        else:
            assert any("falling back" in e["reason"] for e in stats["losses"])
        assert doc.doc_version == 1, "even an empty import is one committed tx"


def test_bcio_exports_contract_names():
    """The public surface promised by m1-module-contracts.md §7 exists."""
    import bcio

    for name in ("export_dxf", "import_dxf", "LossLedger",
                 "dxf_minimal", "ezdxf_bridge", "loss_ledger"):
        assert hasattr(bcio, name), name
    assert bcio.__file__.endswith("__init__.py")
