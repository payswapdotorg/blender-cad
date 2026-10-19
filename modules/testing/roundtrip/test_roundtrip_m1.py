"""Cross-module DXF round-trip suite — TP-CAT-04 precursor (M1).

End-to-end scenario spanning two W2 packages (bcdoc + bcio) plus the ezdxf
conformance oracle, per docs/00-architecture/m1-module-contracts.md §9:

    document -> export_dxf -> file -> import_dxf -> document -> compare
    (+ ezdxf-authored fixture -> import -> export -> ezdxf re-read)

Plain pytest, no Blender (contracts §10 testability rule 1). All fixture
files are self-authored at runtime into ``tmp_path`` — licensing-clean per
test-plan §8; nothing outside the repo working tree is ever touched.
"""

import json

import ezdxf
import ezdxf.recover
import pytest

import bcio
from bcdoc import Arc, Circle, Document, Line
from bcio import LossLedger, export_dxf, import_dxf


def kind_counts(**overrides):
    """Additive v2 stats shape (all 13 kinds zero-filled + total)."""
    counts = {kind: 0 for kind in bcio.KINDS}
    counts.update(overrides)
    counts["total"] = sum(counts[k] for k in bcio.KINDS)
    return counts


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def build_working_drawing() -> Document:
    """A small but representative v0 drawing: every entity kind, two layers,
    explicit ACI colors, one ByLayer-colored entity."""
    doc = Document("m1-roundtrip", units={"length": "mm", "angle": "deg"})
    with doc.transaction("draw the sample"):
        doc.add_layer("WALLS")
        doc.add_layer("ANNOT")
        doc.add_entity(Line((0.0, 0.0, 0.0), (120.0, 0.0, 0.0), layer="WALLS", color=30))
        doc.add_entity(Line((0.0, 0.0), (0.0, 90.5), layer="WALLS"))
        doc.add_entity(Circle((60.0, 45.0, 0.0), 25.25, layer="0", color=1))
        doc.add_entity(Arc((60.0, 45.0), 12.75, 15.5, 202.25, layer="ANNOT", color=140))
        doc.add_entity(Arc((-3.5, -2.25, 1.5), 0.001, -45.0, 45.0, layer="WALLS"))
    assert doc.doc_version == 1
    return doc


def geometry_payload(entity) -> list:
    """Flat float list of an entity's geometry (kind-independent compare)."""
    values = []
    for value in entity.geometry_dict().values():
        if isinstance(value, tuple):
            values.extend(float(v) for v in value)
        else:
            values.append(float(value))
    return values


def assert_content_equivalent(source: Document, mirror: Document) -> None:
    """The engineering content of two documents is the same (the mission's
    compare step): same entity sequence, ids may differ (fresh import), but
    kind / handle / layer / color / geometry must match to 1e-9."""
    src = source.entities()
    dst = mirror.entities()
    assert [e.kind for e in src] == [e.kind for e in dst]
    for a, b in zip(src, dst):
        assert a.handle == b.handle, (
            "DXF handles must be preserved into the document handle space"
        )
        assert a.layer == b.layer
        assert a.color == b.color
        for x, y in zip(geometry_payload(a), geometry_payload(b)):
            assert x == pytest.approx(y, abs=1e-9), (a.kind, x, y)
    # every source layer must be present in the mirror; the mirror may carry
    # additional foreign table entries (ezdxf always writes the standard
    # "Defpoints" layer into R2010 files — imported honestly as a name).
    assert "0" in mirror.layers
    assert set(source.layers) <= set(mirror.layers)
    assert mirror.count_by_kind() == source.count_by_kind()


# ---------------------------------------------------------------------------
# scenario 1: bcdoc -> bcio export -> bcio import -> compare
# ---------------------------------------------------------------------------

class TestDocumentDxfDocument:
    def test_full_round_trip(self, tmp_path):
        doc = build_working_drawing()
        path = str(tmp_path / "working.dxf")

        stats = export_dxf(path, doc)
        assert stats["engine"] == "ezdxf", "ezdxf is installed — oracle path"
        assert stats["entities"]["total"] == 5
        assert stats["losses"] == [], "v0 content must be loss-free"

        mirror, istats = import_dxf(path)
        assert istats["engine"] == "ezdxf"
        assert istats["imported"]["total"] == 5
        assert istats["handle_reallocations"] == 0
        assert mirror.name == "working"  # fresh document named after the file
        assert_content_equivalent(doc, mirror)

        # the bcdoc/2 serialization of the imported document round-trips
        # (load also accepts bcdoc/1 per contracts §2.7/§14)
        reloaded = Document.load(mirror.serialize())
        assert reloaded.serialize() == mirror.serialize()
        assert_content_equivalent(doc, reloaded)

    def test_double_round_trip_is_stable(self, tmp_path):
        """export -> import -> export -> import must be a fixed point: the
        second mirror is content-equivalent to the first mirror (handles,
        geometry and layers stable across repeated interchange)."""
        doc = build_working_drawing()
        first_path = str(tmp_path / "first.dxf")
        second_path = str(tmp_path / "second.dxf")

        export_dxf(first_path, doc)
        mirror1, _ = import_dxf(first_path)

        stats2 = export_dxf(second_path, mirror1)
        assert stats2["entities"]["total"] == 5
        mirror2, _ = import_dxf(second_path)

        assert_content_equivalent(mirror1, mirror2)
        assert_content_equivalent(doc, mirror2)

    def test_round_trip_survives_bcdoc_persistence(self, tmp_path):
        """The M1 persistence path (bcdoc JSON — schema bcdoc/2 as of M2,
        e.g. the Blender text block per contracts §6.2) composes with DXF
        interchange: save -> load -> export -> import -> compare."""
        doc = build_working_drawing()
        text = doc.serialize()  # "save"
        revived = Document.load(text)  # "reopen"
        path = str(tmp_path / "reopened.dxf")
        export_dxf(path, revived)
        mirror, _ = import_dxf(path)
        assert_content_equivalent(doc, mirror)
        assert revived.doc_version == doc.doc_version

    def test_import_is_one_undoable_transaction(self, tmp_path):
        doc = build_working_drawing()
        path = str(tmp_path / "tx.dxf")
        export_dxf(path, doc)

        target = Document("target")
        version0 = target.doc_version
        import_dxf(path, doc=target)
        assert target.doc_version == version0 + 1
        assert target.undo_depth() == 1
        assert target.undo() is True
        assert target.entities() == []
        assert target.layers == ["0"]
        assert target.redo() is True
        assert_content_equivalent(doc, target)


# ---------------------------------------------------------------------------
# scenario 2: ezdxf-authored fixture -> import -> export -> ezdxf re-read
# ---------------------------------------------------------------------------

class TestEzdxfFixtureRoundTrip:
    def test_foreign_file_survives_import_then_export(self, tmp_path):
        """A file authored by plain ezdxf (as any third-party CAD would
        write it): LINE + CIRCLE + ARC + TEXT + an extra layer. At M2 the
        full kind set + layer properties import (nothing is dropped); the
        re-export must then produce a file ezdxf reads back cleanly with
        the SAME handles (round-trip through our document handle space).
        The M1 version expected TEXT + layer-prop losses — both lifted by
        bcdoc v2 (contracts §2.1/§2.2)."""
        author = ezdxf.new("R2010", setup=False)
        author.layers.add("FOREIGN", color=4)
        msp = author.modelspace()
        line = msp.add_line((1, 2, 3), (9, 8, 7), dxfattribs={"layer": "FOREIGN"})
        circle = msp.add_circle((-5.5, 6.25), 3.5)
        arc = msp.add_arc((0, 0), 10.0, 30.0, 300.0, dxfattribs={"color": 5})
        msp.add_text("SUPPORTED SINCE M2")
        foreign_handles = {
            "line": int(line.dxf.handle, 16),
            "circle": int(circle.dxf.handle, 16),
            "arc": int(arc.dxf.handle, 16),
        }
        fixture = str(tmp_path / "foreign.dxf")
        author.saveas(fixture)

        doc, stats = import_dxf(fixture)
        assert stats["engine"] == "ezdxf"
        assert stats["imported"] == kind_counts(line=1, circle=1, arc=1,
                                                 text=1)
        # v2: TEXT and layer properties round-trip — no content losses
        assert stats["losses"] == [], (
            "the M2 kind set + full layer records import losslessly"
        )
        # foreign handles were preserved into the document handle space
        by_kind = {e.kind: e for e in doc.entities()}
        assert {k: e.handle for k, e in by_kind.items()
                if k in foreign_handles} == foreign_handles
        # no handle collisions were needed: reallocation count is 0
        assert stats["handle_reallocations"] == 0

        out = str(tmp_path / "re-exported.dxf")
        export_stats = export_dxf(out, doc)
        assert export_stats["losses"] == []

        reread = ezdxf.readfile(out)
        assert not reread.audit().has_errors
        kinds = sorted(e.dxftype() for e in reread.modelspace())
        assert kinds == ["ARC", "CIRCLE", "LINE", "TEXT"]
        handles = sorted(int(e.dxf.handle, 16)
                         for e in reread.modelspace())
        expected = sorted(list(foreign_handles.values())
                          + [e.handle for e in doc.entities()
                             if e.kind == "text"])
        assert handles == expected
        # colors and layers survived the import -> export path
        reread_arc = [e for e in reread.modelspace() if e.dxftype() == "ARC"][0]
        assert reread_arc.dxf.color == 5
        assert reread_arc.dxf.layer == "0"
        reread_line = [e for e in reread.modelspace() if e.dxftype() == "LINE"][0]
        assert reread_line.dxf.layer == "FOREIGN"

    def test_minimal_r12_file_round_trips_through_oracle(self, tmp_path):
        """The in-product R12 writer's file passes the ezdxf oracle
        (recover-read + audit) and re-imports content-equivalent — the
        shipped-without-dependencies path is held to the same standard."""
        from bcio import dxf_minimal

        doc = build_working_drawing()
        path = str(tmp_path / "minimal.dxf")
        write_stats = dxf_minimal.write_dxf(path, doc)
        assert write_stats["engine"] == "r12-minimal"

        loaded, auditor = ezdxf.recover.readfile(path)
        assert not auditor.errors
        assert not loaded.audit().has_errors

        ledger = LossLedger()
        mirror_doc, _ = import_dxf(path, ledger=ledger)
        assert_content_equivalent(doc, mirror_doc)
        assert not [
            entry for entry in ledger
            if entry["kind"] == "import" and entry["dxf_type"] != "FILE"
        ], "supported content must import without losses"

    def test_loss_ledger_artifact_is_valid_json(self, tmp_path):
        """The ADR-0003 ledger must be a machine-readable artifact: every
        entry has the contract fields and the whole ledger JSON-parses."""
        author = ezdxf.new("R2010", setup=False)
        author.modelspace().add_spline([(0, 0), (1, 1), (2, 0)])
        author.modelspace().add_solid([(0, 0), (1, 0), (1, 1), (0, 1)])
        fixture = str(tmp_path / "lossy.dxf")
        author.saveas(fixture)

        ledger = LossLedger()
        _, stats = import_dxf(fixture, ledger=ledger)
        assert len(ledger) >= 2
        for entry in ledger:
            assert set(entry) == {"kind", "dxf_type", "reason", "at"}
            assert entry["kind"] in ("import", "export")
        payload = json.loads(ledger.to_json())
        assert len(payload) == len(ledger)
        assert stats["losses"] == list(ledger)
