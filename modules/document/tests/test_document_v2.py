"""bcdoc v2 contract tests — m2-module-contracts.md §2 (M2 worker W-B1).

Plain pytest, no Blender, no mocks of bcdoc internals (honesty rule).
Covers: the ten new entity kinds (construct/add/mutate/undo + wire
round-trip), the layer table (journaled add/set/remove + guards + M1
journal replay compat), blocks (copy semantics, redefinition, BlockInUse,
persistence), layouts/spaces (ops + guards + entity routing + session
state), settings (typed store + v1 upgrade defaults + the not-journaled
exception), styles, bcdoc/2 serialization (pinned key order, byte
stability, deterministic v1 upgrade, new journal ops through save/load)
and snapshot-rollback atomicity for table ops.
"""

import json

import pytest

from bcdoc import (
    Arc,
    BlockDefinition,
    Circle,
    Dim,
    DimStyleRecord,
    Document,
    Ellipse,
    Insert,
    Line,
    LayerRecord,
    LayoutRecord,
    Mtext,
    Point,
    Polyline,
    Ray,
    Settings,
    Text,
    TextStyleRecord,
    Viewport,
    Xline,
    errors,
)
from bcdoc.settings import SETTING_DEFS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_v2_doc() -> Document:
    """A document exercising every v2 table + all 13 entity kinds."""
    doc = Document("v2-sample")
    with doc.transaction("setup"):
        doc.layers.add("WALLS", color=30, linetype="DASHED", lineweight=0.35,
                       frozen=False, locked=True, plot=False)
        doc.layers.add("ANNOT", color=5)
        doc.add_text_style("TECH", height=3.5, width_factor=0.9)
        doc.add_dim_style("ARCH", dimscale=2.0, dimtxt=3.0)
        doc.add_layout("Page1", page_width=297.0, page_height=210.0)
        doc.add_block("SYM", (1.0, 1.0, 0.0), [
            Line((0, 0), (2, 0), color=0),          # ByBlock member
            Circle((1, 1), 0.5, lineweight=0.25),
        ])
        doc.add_entity(Line((0, 0, 0), (10, 0, 0), layer="WALLS", color=1))
        doc.add_entity(Circle((5, 3), 2.5, layer="WALLS"))
        doc.add_entity(Arc((2.5, 2.5), 1.75, 15.5, 202.25))
        doc.add_entity(Point((7, 7, 0), color=3))
        doc.add_entity(Polyline([(0, 0), (10, 0), (10, 5)], bulges=[0.5, 0.0, 0.25],
                                widths=[[0.0, 0.1], [0.1, 0.1], [0.1, 0.0]],
                                closed=True))
        doc.add_entity(Ellipse((0, 0), (10, 0, 0), 0.5))
        doc.add_entity(Xline((0, 0), (1, 1)))
        doc.add_entity(Ray((0, 0), (1, 0)))
        doc.add_entity(Text((1, 1), height=2.5, rotation=15.0, content="HELLO",
                            style="TECH", justification="CENTER"))
        doc.add_entity(Mtext((1, 5), width=40.0, content="TWO\nLINES"))
        doc.add_entity(Dim("linear", (0, 0), (10, 0), angle=0.0,
                           offset_point=(5, 3, 0), measured_id="", measurement=10.0,
                           style="ARCH"))
        doc.add_entity(Insert("SYM", (20, 20), scale=(2.0, 2.0, 1.0),
                              rotation=30.0))
        doc.add_entity(Viewport((0, 0, 0), 50.0, (10, 10, 0), (100, 80, 0),
                                space="Page1"))
        doc.add_entity(Line((0, 0), (100, 0), space="Page1"))
    with doc.transaction("tweak"):
        doc.layers.set_props("WALLS", color=8)
    assert doc.undo_depth() == 2
    return doc


ALL_NEW_KIND_CASES = {
    "point": lambda: Point((7, 7, 0), color=3),
    "polyline": lambda: Polyline([(0, 0), (10, 0), (10, 5)],
                                 bulges=[0.5, 0.0, 0.25],
                                 widths=[[0.0, 0.1], [0.1, 0.1], [0.1, 0.0]],
                                 closed=True),
    "ellipse": lambda: Ellipse((0, 0), (10, 0, 0), 0.5),
    "xline": lambda: Xline((0, 0), (1, 1)),
    "ray": lambda: Ray((0, 0), (1, 0)),
    "text": lambda: Text((1, 1), height=3.0, rotation=15.0, content="HELLO",
                         justification="CENTER"),
    "mtext": lambda: Mtext((1, 5), width=40.0, content="TWO\nLINES"),
    "dim": lambda: Dim("aligned", (0, 0), (10, 10), angle=45.0,
                       offset_point=(5, 5, 0), measured_id="e1",
                       measurement=14.1421356, text_override="<> mm",
                       text_position=(5.0, 5.5, 0.0)),
    "insert": lambda: Insert("SYM", (20, 20), scale=(2.0, 2.0, 1.0),
                             rotation=30.0),
    "viewport": lambda: Viewport((0, 0, 0), 50.0, (10, 10, 0), (100, 80, 0),
                                 locked=True),
}


# ---------------------------------------------------------------------------
# entity framework generalization (contract §2.1)
# ---------------------------------------------------------------------------

class TestEntityFramework:
    def test_property_fields_and_defaults(self):
        entity = Line((0, 0), (1, 1))
        assert entity.lineweight is None        # None = ByLayer
        assert entity.space == "MODEL"
        assert entity.mutable_fields == (
            "layer", "color", "linetype", "lineweight", "space", "p1", "p2")

    def test_common_property_order_in_to_json_dict(self):
        """Pinned order: kind, id, handle, layer, color, linetype,
        lineweight, space — then geometry fields in registry order."""
        doc = Document()
        with doc.transaction("t"):
            added = doc.add_entity(Point((1, 2, 3), color=0, lineweight=0.5))
        record = added.to_json_dict()
        assert list(record) == [
            "kind", "id", "handle", "layer", "color", "linetype",
            "lineweight", "space", "position",
        ]
        assert record["color"] == 0              # 0 = ByBlock is a legal value
        assert record["lineweight"] == 0.5
        assert record["space"] == "MODEL"
        assert record["position"] == [1.0, 2.0, 3.0]

    def test_geometry_field_order_per_kind(self):
        from bcdoc.entities import GEOMETRY_FIELDS
        assert GEOMETRY_FIELDS["polyline"] == ("vertices", "bulges", "widths",
                                               "closed")
        assert GEOMETRY_FIELDS["dim"] == (
            "dim_type", "p1", "p2", "angle", "offset_point", "measured_id",
            "measurement", "text_override", "style", "text_position")
        assert GEOMETRY_FIELDS["insert"] == ("name", "position", "scale",
                                             "rotation")

    def test_m1_kinds_wire_output_changed_per_contract(self):
        """M1 entity dicts gain lineweight+space (sanctioned schema change,
        contracts §14): the M1 field ORDER is unchanged, the two new keys
        slot in right after linetype."""
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1), color=1))
        text = doc.serialize().split('"entities": [', 1)[1]
        assert text.startswith(
            '{"kind": "line", "id": ' + json.dumps(line.id))
        assert '"linetype": "ByLayer", "lineweight": null, "space": "MODEL", "p1"' \
            in text

    def test_set_field_lineweight_and_space(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("props"):
            doc.update_entity(line.id, lineweight=0.25, space="MODEL")
        assert line.lineweight == 0.25
        with pytest.raises(ValueError):
            with doc.transaction("bad"):
                doc.update_entity(line.id, lineweight=-1.0)
        assert line.lineweight == 0.25  # no partial apply

    def test_coercers_normalize_wire_forms(self):
        pline = Polyline([(0, 0), (10, 0)], bulges=(0, 0), widths=[[0, 0.5], [0.5, 0]])
        record = pline.to_json_dict()
        assert record["vertices"] == [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]
        assert record["bulges"] == [0.0, 0.0]
        assert record["widths"] == [[0.0, 0.5], [0.5, 0.0]]
        assert record["closed"] is False

    @pytest.mark.parametrize("kind", sorted(ALL_NEW_KIND_CASES))
    def test_new_kinds_full_lifecycle(self, kind):
        factory = ALL_NEW_KIND_CASES[kind]
        doc = Document()
        with doc.transaction("add"):
            entity = doc.add_entity(factory())
        assert doc.count_by_kind() == {kind: 1}
        assert entity.handle == 4097
        original = entity.to_json_dict()

        # mutate the first float-ish geometry field + a property, then undo
        with doc.transaction("mutate"):
            doc.update_entity(entity.id, layer="0", color=7)
        assert doc.undo()
        assert entity.to_json_dict() == original

        # serialize + load round-trip: equal geometry, byte-stable, undoable
        text = doc.serialize()
        mirror = Document.load(text)
        assert mirror.serialize() == text
        [loaded] = mirror.entities()
        assert loaded.to_json_dict() == original
        assert loaded.geometry_dict() == entity.geometry_dict()
        assert mirror.undo_depth() == 1
        assert mirror.undo() is True          # the add is still undoable
        assert mirror.entities() == []

    def test_polyline_construction_validation(self):
        with pytest.raises(ValueError):
            Polyline([])  # needs at least one vertex
        with pytest.raises(ValueError):
            Polyline([(0, 0), (1, 1)], bulges=[0.1])  # bulge count mismatch
        with pytest.raises(ValueError):
            Polyline([(0, 0), (1, 1)], widths=[[0, 0]])  # width count mismatch
        with pytest.raises(ValueError):
            Polyline([(0, 0), (1, 1)], closed=1)  # bools only

    def test_polyline_mutation_keeps_lengths(self):
        doc = Document()
        with doc.transaction("t"):
            pline = doc.add_entity(Polyline([(0, 0), (1, 1)]))
        with pytest.raises(ValueError):
            with doc.transaction("bad"):
                doc.update_entity(pline.id, bulges=[0.5, 0.5, 0.5])
        assert pline.bulges == ()

    def test_semantic_validators(self):
        with pytest.raises(ValueError):
            Text((0, 0), justification="MIDDLE")
        with pytest.raises(ValueError):
            Dim("radius", (0, 0), (1, 1))
        with pytest.raises(ValueError):
            Insert(123, (0, 0))
        with pytest.raises(ValueError):
            Mtext((0, 0), content=5)
        with pytest.raises(ValueError):
            Xline("nope", (1, 1))
        with pytest.raises(ValueError):
            Viewport((0, 0), 10, (0, 0), (1, 1), locked="yes")

    def test_ellipse_and_insert_defaults(self):
        ellipse = Ellipse((0, 0), (10, 0), 0.25)
        assert (ellipse.start_angle, ellipse.end_angle) == (0.0, 360.0)
        insert = Insert("B", (1, 2))
        assert insert.scale == (1.0, 1.0, 1.0)
        assert insert.rotation == 0.0

    def test_block_members_allow_byblock_color(self):
        member = Line((0, 0), (1, 1), color=0)
        assert member.color == 0  # ByBlock: legal, distinct from ByLayer None


# ---------------------------------------------------------------------------
# layer table (contract §2.2)
# ---------------------------------------------------------------------------

class TestLayerTable:
    def test_table_basics_and_compat_surface(self):
        doc = Document()
        table = doc.layers
        assert isinstance(table, type(doc.layers))
        assert table.names() == ["0"]
        assert "0" in table and "GHOST" not in table
        assert len(table) == 1
        assert list(table) == ["0"]
        assert table == ["0"]                       # M1 list-equality compat
        assert doc.layers == ["0"]
        record = table.get("0")
        assert isinstance(record, LayerRecord)
        assert (record.color, record.linetype, record.lineweight) == (7, "Continuous", None)
        assert (record.on, record.frozen, record.locked, record.plot) == (True, False, False, True)
        assert table.get("MISSING") is None

    def test_add_with_props_is_journaled(self):
        doc = Document()
        with doc.transaction("layers") as tx:
            record = doc.layers.add("WALLS", color=30, linetype="DASHED",
                                    lineweight=0.35, frozen=True)
            raw_ops = list(tx.journal)
        assert raw_ops == [{
            "op": "add_layer", "name": "WALLS",
            "props": record.props_dict(),
        }]
        assert doc.layers.names() == ["0", "WALLS"]
        assert doc.layers.get("WALLS") is record
        assert (record.color, record.linetype, record.lineweight, record.frozen) \
            == (30, "DASHED", 0.35, True)
        # the RAW journal carries the op as applied (captured pre-commit
        # in the test above); the undo group carries its reversal
        assert doc.undo_groups()[-1].entries == [
            {"op": "remove_layer", "name": "WALLS"},
        ]
        assert doc.undo()
        assert doc.layers.names() == ["0"]
        assert doc.redo()
        assert doc.layers.get("WALLS").color == 30

    def test_mutations_require_open_transaction(self):
        doc = Document()
        for call in (lambda: doc.layers.add("X"),
                     lambda: doc.layers.set_props("0", color=1),
                     lambda: doc.layers.remove("0")):
            with pytest.raises(errors.NoOpenTransaction):
                call()

    def test_duplicate_and_unknown_names(self):
        doc = Document()
        with doc.transaction("t"):
            with pytest.raises(errors.DuplicateLayer):
                doc.layers.add("0")
        with doc.transaction("t2"):
            with pytest.raises(errors.LayerNotFound):
                doc.layers.set_props("GHOST", color=1)
            with pytest.raises(errors.LayerNotFound):
                doc.layers.remove("GHOST")

    def test_bad_props_rejected_without_partial_apply(self):
        doc = Document()
        with doc.transaction("t"):
            with pytest.raises(ValueError):
                doc.layers.add("BAD", color="red")
            with pytest.raises(ValueError):
                doc.layers.add("BAD2", unknown_prop=1)
            with pytest.raises(ValueError):
                doc.layers.set_props("0", on=1)  # bools only
            with pytest.raises(ValueError):
                doc.layers.set_props("0", nope=1)
        assert doc.layers.names() == ["0"]
        assert doc.layers.get("0").color == 7  # untouched

    def test_set_props_journaled_undo_redo(self):
        doc = Document()
        with doc.transaction("t"):
            doc.layers.add("WALLS", color=30)
        with doc.transaction("mutate"):
            doc.layers.set_props("WALLS", color=8, locked=True)
        assert (doc.layers.get("WALLS").color, doc.layers.get("WALLS").locked) \
            == (8, True)
        group = doc.undo_groups()[-1]
        assert group.entries[-1] == {
            "op": "mutate_layer", "name": "WALLS",
            "changes": {"color": 30, "locked": False},
        }
        assert doc.undo()
        assert doc.layers.get("WALLS").color == 30
        assert doc.layers.get("WALLS").locked is False
        assert doc.redo()
        assert doc.layers.get("WALLS").color == 8

    def test_remove_guards(self):
        doc = Document()
        with doc.transaction("draw"):
            line = doc.add_entity(Line((0, 0), (1, 1), layer="WALLS"))
            doc.layers.add("WALLS")
        with doc.transaction("guard"):
            with pytest.raises(errors.LayerNotEmpty):
                doc.layers.remove("WALLS")
            with pytest.raises(errors.ProtectedRecord):
                doc.layers.remove("0")
        # empty the layer, then removal works and is undoable
        with doc.transaction("erase"):
            doc.remove(line.id)
        with doc.transaction("rm"):
            doc.layers.remove("WALLS")
        assert doc.layers.names() == ["0"]
        assert doc.undo()
        assert doc.layers.names() == ["0", "WALLS"]

    def test_zero_cannot_leave_the_table_via_journal(self):
        doc = Document()
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "remove_layer", "name": "0"})
        # but property mutations of "0" are legal (AutoCAD parity)
        with doc.transaction("t"):
            doc.layers.set_props("0", color=5)
        assert doc.layers.get("0").color == 5

    def test_add_layer_compat_wrapper_creates_default_record(self):
        doc = Document()
        with doc.transaction("io"):
            name = doc.add_layer("FROM_BCIO")
        assert name == "FROM_BCIO"
        record = doc.layers.get("FROM_BCIO")
        assert record.to_dict() == LayerRecord("FROM_BCIO").to_dict()

    def test_update_entity_layer_auto_create_uses_table(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("relabel"):
            doc.update_entity(line.id, layer="NEW")
        assert doc.layers.names() == ["0", "NEW"]
        assert doc.layers.get("NEW").color == 7
        assert doc.undo()
        assert doc.layers.names() == ["0"]

    def test_current_layer_reads_clayer_with_fallback(self):
        doc = Document()
        assert doc.current_layer == "0"
        with doc.transaction("t"):
            doc.layers.add("WALLS")
        doc.settings.set("CLAYER", "WALLS")
        assert doc.current_layer == "WALLS"
        doc.settings.set("CLAYER", "GHOST")      # references a missing layer
        assert doc.current_layer == "0"
        # serialize round-trips the fallback deterministically
        text = doc.serialize()
        assert Document.load(text).serialize() == text

    def test_layer_records_serialize_in_pinned_key_order(self):
        doc = Document()
        with doc.transaction("t"):
            doc.layers.add("WALLS", color=30, lineweight=0.35)
        text = doc.serialize()
        assert '"layers": [{"name": "0", "color": 7, "linetype": "Continuous", ' \
               '"lineweight": null, "on": true, "frozen": false, "locked": false, ' \
               '"plot": true}' in text
        assert '"name": "WALLS", "color": 30' in text

    def test_m1_bare_journal_replays_with_default_record(self):
        """Tolerant replay rule: bare M1 layer ops rebuild default records."""
        doc = Document()
        counter = doc._apply_op({"op": "add_layer", "name": "LEGACY"})
        assert counter["op"] == "remove_layer"
        record = doc.layers.get("LEGACY")
        assert record.to_dict() == LayerRecord("LEGACY").to_dict()
        counter2 = doc._apply_op(counter)
        assert doc.layers.get("LEGACY") is None
        assert counter2 == {"op": "add_layer", "name": "LEGACY",
                            "props": LayerRecord("LEGACY").props_dict()}

    def test_layer_ops_survive_save_load_with_undo_intact(self):
        doc = Document()
        with doc.transaction("t"):
            doc.layers.add("WALLS", color=30, locked=True)
        mirror = Document.load(doc.serialize())
        assert mirror.serialize() == doc.serialize()
        assert mirror.layers.get("WALLS").to_dict() == \
            doc.layers.get("WALLS").to_dict()
        assert mirror.undo()
        assert mirror.layers.names() == ["0"]


# ---------------------------------------------------------------------------
# blocks (contract §2.3)
# ---------------------------------------------------------------------------

class TestBlocks:
    def _base_doc(self):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
        return doc

    def test_add_block_copies_entities(self):
        doc = self._base_doc()
        original = Line((0, 0), (5, 0), color=0)
        with doc.transaction("b"):
            definition = doc.add_block("SYM", (1.0, 1.0, 0.0), [original])
        member = definition.entities[0]
        assert member is not original
        assert member.to_json_dict() == original.to_json_dict()
        # mutating the ORIGINAL after add_block must not touch the definition
        original.p2 = (99, 99)
        assert definition.entities[0].p2 == (5.0, 0.0, 0.0)
        # the member is NOT in the document entity store
        assert doc.entities() != [member]
        assert member.id not in {e.id for e in doc.entities()}

    def test_add_block_strips_space_keeps_properties(self):
        doc = self._base_doc()
        with doc.transaction("lay"):
            doc.add_layout("Page1")
        member = Line((0, 0), (2, 0), color=0, lineweight=0.13,
                      space="Page1")
        with doc.transaction("b"):
            definition = doc.add_block("SYM", (0, 0), [member])
        assert definition.entities[0].space == "MODEL"
        assert definition.entities[0].color == 0            # ByBlock kept
        assert definition.entities[0].lineweight == 0.13

    def test_definition_handle_comes_from_document_space(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("A", (0, 0), [Line((0, 0), (1, 0))])
            doc.add_block("B", (0, 0), [Line((0, 0), (1, 0))])
        assert [doc.block("A").handle, doc.block("B").handle] == [4098, 4099]
        with doc.transaction("e"):
            doc.add_entity(Line((0, 0), (1, 1)))
        assert doc.entities()[-1].handle == 4100
        assert doc.next_handle == 4101

    def test_block_lookup_and_errors(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("SYM", (0, 0), [Line((0, 0), (1, 0))])
        assert doc.blocks() == ["SYM"]
        assert doc.block_names() == ["SYM"]
        assert isinstance(doc.block("SYM"), BlockDefinition)
        with pytest.raises(errors.BlockNotFound):
            doc.block("GHOST")
        with doc.transaction("dup"):
            with pytest.raises(errors.DuplicateBlock):
                doc.add_block("SYM", (0, 0), [])
        with pytest.raises(errors.NoOpenTransaction):
            doc.add_block("LATER", (0, 0), [])

    def test_insert_references_and_block_ref_ids(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("SYM", (0, 0), [Line((0, 0), (1, 0))])
            first = doc.add_entity(Insert("SYM", (10, 10)))
            other = doc.add_entity(Insert("OTHER", (20, 20)))
            second = doc.add_entity(Insert("SYM", (30, 30)))
        assert doc.block_ref_ids("SYM") == [first.id, second.id]
        assert doc.block_ref_ids("OTHER") == [other.id]
        assert doc.block_ref_ids("MISSING") == []

    def test_redefine_updates_refs_view_and_is_undoable(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("SYM", (0, 0), [Line((0, 0), (1, 0))])
            ref = doc.add_entity(Insert("SYM", (10, 10)))
        new_members = [Line((0, 0), (2, 0)), Circle((1, 1), 0.5)]
        with doc.transaction("redefine"):
            doc.redefine_block("SYM", new_members, base_point=(5, 5, 0))
        # references resolve BY NAME: the insert is untouched, the members
        # it now displays are the new ones
        definition = doc.block("SYM")
        assert doc.get(ref.id).name == "SYM"
        assert definition.base_point == (5.0, 5.0, 0.0)
        assert [m.kind for m in definition.entities] == ["line", "circle"]
        # mutating the caller's list after redefine changes nothing
        new_members.append(Line((0, 0), (1, 1)))
        assert len(doc.block("SYM").entities) == 2
        # undo restores the previous members + base point
        assert doc.undo()
        definition = doc.block("SYM")
        assert definition.base_point == (0.0, 0.0, 0.0)
        assert [m.kind for m in definition.entities] == ["line"]
        assert doc.redo()
        assert len(doc.block("SYM").entities) == 2
        with pytest.raises(errors.BlockNotFound):
            with doc.transaction("r"):
                doc.redefine_block("GHOST", [])

    def test_remove_block_guards(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("SYM", (0, 0), [Line((0, 0), (1, 0))])
            doc.add_entity(Insert("SYM", (10, 10)))
        with doc.transaction("guard"):
            with pytest.raises(errors.BlockInUse):
                doc.remove_block("SYM")
        with doc.transaction("rm ref"):
            doc.remove(doc.block_ref_ids("SYM")[0])
        with doc.transaction("rm block"):
            doc.remove_block("SYM")
        assert doc.blocks() == []
        assert doc.undo()               # block back
        assert doc.blocks() == ["SYM"]
        assert doc.block("SYM").entities[0].p2 == (1.0, 0.0, 0.0)

    def test_definitions_survive_save_load_with_undo_intact(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("SYM", (1, 2), [Line((0, 0), (5, 0), color=0)])
        text = doc.serialize()
        mirror = Document.load(text)
        assert mirror.serialize() == text
        definition = mirror.block("SYM")
        assert definition.base_point == (1.0, 2.0, 0.0)
        assert definition.handle == doc.block("SYM").handle
        assert definition.entities[0].to_json_dict() == \
            doc.block("SYM").entities[0].to_json_dict()
        assert mirror.undo_depth() == 2
        assert mirror.undo() is True       # the add_block journal replays
        assert mirror.blocks() == []

    def test_undo_of_add_block_then_redo_reuses_handle(self):
        doc = self._base_doc()
        with doc.transaction("b"):
            doc.add_block("SYM", (0, 0), [Line((0, 0), (1, 0))])
        assert doc.undo()
        assert doc.blocks() == []
        assert doc.redo()
        assert doc.block("SYM").handle == 4098
        assert doc.next_handle == 4099     # no rewind, no reuse


# ---------------------------------------------------------------------------
# layouts + spaces (contract §2.4)
# ---------------------------------------------------------------------------

class TestLayouts:
    def test_add_layout_defaults_and_lookup(self):
        doc = Document()
        with doc.transaction("l"):
            record = doc.add_layout("Page1")
        assert isinstance(record, LayoutRecord)
        assert (record.page_width, record.page_height, record.paper_units) \
            == (420.0, 297.0, "mm")
        assert doc.layouts() == ["Page1"]
        assert doc.layout("Page1") is record
        with pytest.raises(errors.LayoutNotFound):
            doc.layout("GHOST")
        with pytest.raises(errors.NoOpenTransaction):
            doc.add_layout("L2")
        with doc.transaction("dup"):
            with pytest.raises(errors.DuplicateLayout):
                doc.add_layout("Page1")

    def test_add_layout_page_size(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("A4", page_width=297.0, page_height=210.0,
                           paper_units="mm")
        assert doc.layout("A4").page_width == 297.0

    def test_add_entity_space_validation(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1")
        with doc.transaction("e"):
            in_layout = doc.add_entity(Line((0, 0), (1, 1), space="Page1"))
            in_model = doc.add_entity(Line((0, 0), (1, 1)))
        assert in_layout.space == "Page1"
        with doc.transaction("bad"):
            with pytest.raises(errors.InvalidSpace):
                doc.add_entity(Line((0, 0), (1, 1), space="GHOST"))
        with doc.transaction("bad2"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
            with pytest.raises(errors.InvalidSpace):
                doc.update_entity(line.id, space="GHOST")

    def test_entities_in_space(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1")
        with doc.transaction("e"):
            model_line = doc.add_entity(Line((0, 0), (1, 1)))
            paper_line = doc.add_entity(Line((0, 0), (1, 1), space="Page1"))
        assert [e.id for e in doc.entities_in_space("MODEL")] == [model_line.id]
        assert [e.id for e in doc.entities_in_space("Page1")] == [paper_line.id]
        with pytest.raises(errors.InvalidSpace):
            doc.entities_in_space("GHOST")

    def test_set_current_space_validates_and_maintains_tilemode(self):
        doc = Document()
        assert doc.current_space == "MODEL"
        assert doc.settings.get("TILEMODE") == 1
        with doc.transaction("l"):
            doc.add_layout("Page1")
        doc.set_current_space("Page1")
        assert doc.current_space == "Page1"
        assert doc.settings.get("TILEMODE") == 0
        doc.set_current_space("MODEL")
        assert doc.current_space == "MODEL"
        assert doc.settings.get("TILEMODE") == 1
        with pytest.raises(errors.InvalidSpace):
            doc.set_current_space("GHOST")

    def test_session_state_is_not_serialized(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1")
        doc.set_current_space("Page1")
        doc.active_layout = "Page1"
        doc.last_selection_ids = ["a", "b"]
        mirror = Document.load(doc.serialize())
        assert mirror.current_space == "MODEL"
        assert mirror.active_layout is None
        assert mirror.last_selection_ids == []

    def test_rename_layout_reroutes_entities(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1")
        with doc.transaction("e"):
            line = doc.add_entity(Line((0, 0), (1, 1), space="Page1"))
        doc.set_current_space("Page1")
        doc.active_layout = "Page1"
        with doc.transaction("ren"):
            doc.rename_layout("Page1", "Sheet-A")
        assert doc.layouts() == ["Sheet-A"]
        assert doc.get(line.id).space == "Sheet-A"   # re-routed, no orphans
        assert doc.current_space == "Sheet-A"        # session state follows
        assert doc.active_layout == "Sheet-A"
        assert doc.undo()
        assert doc.layouts() == ["Page1"]
        assert doc.get(line.id).space == "Page1"
        with doc.transaction("dup2"):
            doc.add_layout("Taken")
        with doc.transaction("dup3"):
            with pytest.raises(errors.DuplicateLayout):
                doc.rename_layout("Page1", "Taken")
            doc.rename_layout("Page1", "Page1")     # no-op rename is legal
        with pytest.raises(errors.LayoutNotFound):
            with doc.transaction("x"):
                doc.rename_layout("GHOST", "X")

    def test_remove_layout_guard(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1")
        with doc.transaction("e"):
            doc.add_entity(Line((0, 0), (1, 1), space="Page1"))
        with doc.transaction("guard"):
            with pytest.raises(errors.LayoutNotEmpty):
                doc.remove_layout("Page1")
        with doc.transaction("empty it"):
            doc.remove(doc.entities_in_space("Page1")[0].id)
        with doc.transaction("rm"):
            doc.remove_layout("Page1")
        assert doc.layouts() == []
        assert doc.undo()
        assert doc.layouts() == ["Page1"]

    def test_reorder_layout(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("A")
            doc.add_layout("B")
            doc.add_layout("C")
        with doc.transaction("move"):
            doc.reorder_layout("C", 0)
        assert doc.layouts() == ["C", "A", "B"]
        group = doc.undo_groups()[-1]
        assert group.entries == [{"op": "reorder_layout", "name": "C",
                                  "old_index": 2}]
        assert doc.undo()
        assert doc.layouts() == ["A", "B", "C"]
        assert doc.redo()
        assert doc.layouts() == ["C", "A", "B"]
        with doc.transaction("oob"):
            with pytest.raises(ValueError):
                doc.reorder_layout("A", 9)
        with pytest.raises(errors.LayoutNotFound):
            with doc.transaction("oob2"):
                doc.reorder_layout("GHOST", 0)

    def test_layouts_serialize_in_pinned_key_order(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1", page_width=297.0, page_height=210.0)
        assert '"layouts": [{"name": "Page1", "page_width": 297.0, ' \
               '"page_height": 210.0, "paper_units": "mm"}]' in doc.serialize()


# ---------------------------------------------------------------------------
# settings (contract §2.5)
# ---------------------------------------------------------------------------

class TestSettings:
    def test_registry_defaults_exact(self):
        assert doc_defaults() == {
            "CLAYER": "0", "OSMODE": 55, "ORTHOMODE": 0, "SNAPMODE": 0,
            "SNAPUNIT": 1.0, "GRIDMODE": 0, "GRIDUNIT": 10.0,
            "APERTURE": 0.5, "DYNMODE": 3, "PICKFIRST": 1, "TILEMODE": 1,
            "INSUNITS": 0, "LUNITS": 2, "LUPREC": 4, "AUNITS": 0,
            "AUPREC": 0, "TEXTSTYLE": "Standard", "DIMSTYLE": "Standard",
            "LTSCALE": 1.0,
        }
        assert set(SETTING_DEFS) == {
            "CLAYER", "OSMODE", "ORTHOMODE", "SNAPMODE", "SNAPUNIT",
            "GRIDMODE", "GRIDUNIT", "APERTURE", "DYNMODE", "PICKFIRST",
            "TILEMODE", "INSUNITS", "LUNITS", "LUPREC", "AUNITS",
            "AUPREC", "TEXTSTYLE", "DIMSTYLE", "LTSCALE",
        }
        for definition in SETTING_DEFS.values():
            assert set(definition) >= {"type", "default", "help"}

    def test_typed_get_set(self):
        doc = Document()
        assert doc.settings.get("OSMODE") == 55
        doc.settings.set("OSMODE", 1)
        assert doc.settings.get("OSMODE") == 1
        doc.settings.set("SNAPUNIT", 2)          # floats accept ints
        assert doc.settings.get("SNAPUNIT") == 2.0
        assert isinstance(doc.settings.get("SNAPUNIT"), float)
        doc.settings["GRIDUNIT"] = 5.0           # subscript style
        assert doc.settings["GRIDUNIT"] == 5.0
        assert "CLAYER" in doc.settings
        assert list(doc.settings.names())[0] == "CLAYER"

    def test_unknown_and_invalid(self):
        doc = Document()
        with pytest.raises(errors.UnknownSetting):
            doc.settings.get("NOT_A_VAR")
        with pytest.raises(errors.UnknownSetting):
            doc.settings.set("NOT_A_VAR", 1)
        with pytest.raises(errors.UnknownSetting):
            doc.settings["NOT_A_VAR"]
        for bad in (55.0, "55", None, True):     # ints reject bools/floats/strs
            with pytest.raises(errors.InvalidSettingValue):
                doc.settings.set("OSMODE", bad)
        with pytest.raises(errors.InvalidSettingValue):
            doc.settings.set("SNAPUNIT", "wide")
        with pytest.raises(errors.InvalidSettingValue):
            doc.settings.set("SNAPUNIT", float("inf"))
        with pytest.raises(errors.InvalidSettingValue):
            doc.settings.set("CLAYER", 0)
        with pytest.raises(errors.InvalidSettingValue):
            doc.settings.set("ORTHOMODE", 5)     # choices [0, 1]
        with pytest.raises(errors.InvalidSettingValue):
            doc.settings.set("DYNMODE", "off")

    def test_to_json_from_json_round_trip(self):
        settings = Settings()
        settings.set("LUPREC", 6)
        settings.set("CLAYER", "WALLS")
        payload = settings.to_json()
        assert list(payload) == list(SETTING_DEFS)     # registry order
        mirror = Settings()
        mirror.from_json(payload)
        assert mirror.to_json() == payload
        sparse = Settings()
        sparse.from_json({"LUPREC": 3})               # tolerant: rest default
        assert sparse.get("LUPREC") == 3
        assert sparse.get("CLAYER") == "0"
        with pytest.raises(errors.UnknownSetting):
            Settings().from_json({"NOPE": 1})

    def test_settings_persisted_but_not_journaled(self):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
            doc.settings.set("OSMODE", 1)
        assert doc.settings.get("OSMODE") == 1
        assert doc.undo() is True                    # undoes the entity
        assert doc.settings.get("OSMODE") == 1       # ... but NOT the sysvar
        payload = json.loads(doc.serialize())
        assert payload["settings"]["OSMODE"] == 1    # persisted though
        assert payload["current_layer"] == "0"
        mirror = Document.load(doc.serialize())
        assert mirror.settings.get("OSMODE") == 1

    def test_failed_transaction_keeps_settings_but_rolls_back_content(self):
        """The sysvar exception, documented: a FAILED transaction rolls
        back all content bit-identically EXCEPT settings."""
        doc = Document()
        with doc.transaction("keep"):
            doc.add_entity(Line((0, 0), (1, 1)))
        before = doc.serialize()
        with pytest.raises(RuntimeError):
            with doc.transaction("doomed"):
                doc.layers.add("TEMP", color=1)
                doc.add_block("B", (0, 0), [Line((0, 0), (1, 1))])
                doc.add_layout("L")
                doc.add_text_style("S")
                doc.add_entity(Circle((0, 0), 1))
                doc.settings.set("OSMODE", 0)
                raise RuntimeError("boom")
        after = json.loads(doc.serialize())
        assert after["settings"]["OSMODE"] == 0          # sysvar survives
        before_payload = json.loads(before)
        before_payload["settings"]["OSMODE"] = 0
        assert after == before_payload                  # everything else identical
        assert doc.layers.names() == ["0"]
        assert doc.blocks() == []
        assert doc.layouts() == []
        assert doc.text_styles() == ["Standard"]
        assert len(doc.entities()) == 1


def doc_defaults() -> dict:
    return {name: value for name, value in Settings().items()}


# ---------------------------------------------------------------------------
# styles (contract §2.6)
# ---------------------------------------------------------------------------

class TestStyles:
    def test_standard_always_present(self):
        doc = Document()
        assert doc.text_styles() == ["Standard"]
        assert doc.dim_styles() == ["Standard"]
        standard = doc.text_style("Standard")
        assert isinstance(standard, TextStyleRecord)
        assert (standard.height, standard.width_factor) == (2.5, 1.0)
        dim = doc.dim_style("Standard")
        assert isinstance(dim, DimStyleRecord)
        assert (dim.dimscale, dim.dimtxt, dim.dimasz, dim.dimexo, dim.dimexe) \
            == (1.0, 2.5, 2.5, 0.625, 1.25)

    def test_add_mutate_remove_journaled(self):
        doc = Document()
        with doc.transaction("s"):
            doc.add_text_style("TECH", height=3.5, width_factor=0.9)
            doc.add_dim_style("ARCH", dimscale=2.0, dimexe=2.0)
        assert doc.text_style("TECH").height == 3.5
        assert doc.dim_style("ARCH").dimscale == 2.0
        group = doc.undo_groups()[-1]
        assert group.entries == [
            {"op": "remove_dim_style", "name": "ARCH"},
            {"op": "remove_text_style", "name": "TECH"},
        ]
        with doc.transaction("mut"):
            doc.set_text_style_props("TECH", height=5.0)
            doc.set_dim_style_props("ARCH", dimtxt=4.0)
        assert (doc.text_style("TECH").height,
                doc.dim_style("ARCH").dimtxt) == (5.0, 4.0)
        mutate_group = doc.undo_groups()[-1]
        assert mutate_group.entries == [
            {"op": "mutate_dim_style", "name": "ARCH",
             "changes": {"dimtxt": 2.5}},
            {"op": "mutate_text_style", "name": "TECH",
             "changes": {"height": 3.5}},
        ]
        assert doc.undo()
        assert doc.text_style("TECH").height == 3.5
        assert doc.dim_style("ARCH").dimtxt == 2.5
        assert doc.redo()
        assert doc.text_style("TECH").height == 5.0
        with doc.transaction("r"):
            doc.remove_text_style("TECH")
            doc.remove_dim_style("ARCH")
        assert doc.text_styles() == ["Standard"]
        assert doc.dim_styles() == ["Standard"]
        assert doc.undo()
        assert doc.text_styles() == ["Standard", "TECH"]
        assert doc.dim_styles() == ["Standard", "ARCH"]
        with pytest.raises(errors.NoOpenTransaction):
            doc.add_text_style("X")

    def test_style_guards(self):
        doc = Document()
        with doc.transaction("t"):
            doc.add_text_style("TECH")
        with doc.transaction("g"):
            with pytest.raises(errors.DuplicateStyle):
                doc.add_text_style("TECH")
            with pytest.raises(errors.DuplicateStyle):
                doc.add_dim_style("Standard")
            with pytest.raises(errors.ProtectedRecord):
                doc.remove_text_style("Standard")
            with pytest.raises(errors.ProtectedRecord):
                doc.remove_dim_style("Standard")
        with pytest.raises(errors.StyleNotFound):
            doc.text_style("GHOST")
        with pytest.raises(errors.StyleNotFound):
            doc.dim_style("GHOST")

    def test_current_style_is_the_setting(self):
        doc = Document()
        assert doc.settings.get("TEXTSTYLE") == "Standard"
        assert doc.settings.get("DIMSTYLE") == "Standard"
        with doc.transaction("t"):
            doc.add_text_style("TECH")
        doc.settings.set("TEXTSTYLE", "TECH")
        assert doc.settings.get("TEXTSTYLE") == "TECH"

    def test_styles_serialize_in_pinned_key_order(self):
        doc = Document()
        with doc.transaction("t"):
            doc.add_text_style("TECH", height=3.5)
            doc.add_dim_style("ARCH", dimscale=2.0)
        text = doc.serialize()
        assert '"text_styles": [{"name": "Standard", "height": 2.5, ' \
               '"width_factor": 1.0}, {"name": "TECH", "height": 3.5, ' \
               '"width_factor": 1.0}]' in text
        assert '"dim_styles": [{"name": "Standard", "dimscale": 1.0, ' \
               '"dimtxt": 2.5, "dimasz": 2.5, "dimexo": 0.625, ' \
               '"dimexe": 1.25}, {"name": "ARCH", "dimscale": 2.0, ' \
               '"dimtxt": 2.5, "dimasz": 2.5, "dimexo": 0.625, ' \
               '"dimexe": 1.25}]' in text


# ---------------------------------------------------------------------------
# serialization (contract §2.7)
# ---------------------------------------------------------------------------

V1_TEXT = (
    '{"schema": "bcdoc/1", "name": "legacy", '
    '"units": {"length": "mm", "angle": "deg"}, '
    '"doc_version": 2, "next_handle": 4100, '
    '"layers": ["0", "WALLS"], '
    '"entities": ['
    '{"kind": "line", "id": "aaaa", "handle": 4097, "layer": "0", '
    '"color": null, "linetype": "ByLayer", "p1": [0, 0, 0], "p2": [10, 0, 0]}, '
    '{"kind": "circle", "id": "bbbb", "handle": 4098, "layer": "WALLS", '
    '"color": 3, "linetype": "ByLayer", "center": [1, 2, 0], "radius": 2.5}'
    '], '
    '"undo": [{"label": "draw", "doc_version": 1, "entries": ['
    '{"op": "remove", "id": "bbbb"}, {"op": "remove", "id": "aaaa"}, '
    '{"op": "remove_layer", "name": "WALLS"}]}, '
    '{"label": "restore ghost layer", "doc_version": 1, "entries": '
    '[{"op": "add_layer", "name": "GHOST"}]}], '
    '"redo": [{"label": "undone erase", "doc_version": 2, "entries": '
    '[{"op": "add", "entity": {"kind": "arc", "id": "cccc", "handle": 4099, '
    '"layer": "0", "color": null, "linetype": "ByLayer", '
    '"center": [3, 3, 0], "radius": 1.0, "start_angle": 0.0, '
    '"end_angle": 90.0}, "index": 2}]}], '
    '"selection": {"ids": ["bbbb"], "epoch": 1}}'
)


class TestSerializationV2:
    def test_pinned_key_order(self):
        payload = json.loads(make_v2_doc().serialize())
        # write schema moved to bcdoc/3 by the m3 schema lane (amends m2
        # §2.7 — m3-module-contracts.md §6); v2 payloads still LOAD
        assert list(payload) == [
            "schema", "name", "units", "doc_version", "next_handle",
            "settings", "layers", "current_layer", "text_styles",
            "dim_styles", "blocks", "layouts", "sketches", "entities",
            "undo", "redo", "selection",
        ]
        assert payload["schema"] == "bcdoc/3"

    def test_byte_stable_with_all_tables_and_kinds(self):
        doc = make_v2_doc()
        assert doc.undo_depth() == 2
        assert doc.undo()                       # non-empty redo stack, too
        text1 = doc.serialize()
        mirror = Document.load(text1)
        assert mirror.serialize() == text1
        assert Document.load(mirror.serialize()).serialize() == text1
        assert mirror.redo()                   # journals still apply post-load
        assert [e.kind for e in mirror.entities()] == \
            [e.kind for e in doc.entities()]

    def test_v1_upgrade_is_deterministic(self):
        doc = Document.load(V1_TEXT)
        assert doc.name == "legacy"
        assert doc.layers.names() == ["0", "WALLS"]
        assert doc.layers.get("WALLS").to_dict() == LayerRecord("WALLS").to_dict()
        line = [e for e in doc.entities() if e.kind == "line"][0]
        assert line.lineweight is None          # v1 entities get the defaults
        assert line.space == "MODEL"
        assert doc.settings.get("OSMODE") == 55  # settings defaults
        assert doc.blocks() == [] and doc.layouts() == []
        assert doc.text_styles() == ["Standard"] and doc.dim_styles() == ["Standard"]
        assert doc.current_layer == "0"
        # byte-stable across repeated cycles (write schema = bcdoc/3
        # since the m3 schema lane; the v1 upgrade path itself is unchanged)
        text = doc.serialize()
        assert text.startswith('{"schema": "bcdoc/3"')
        assert Document.load(text).serialize() == text
        again = Document.load(Document.load(text).serialize())
        assert again.serialize() == text

    def test_v1_bare_journal_replays_after_load(self):
        doc = Document.load(V1_TEXT)
        assert doc.undo_depth() == 2
        assert doc.undo()                        # applies the bare add_layer op
        assert "GHOST" in doc.layers.names()     # ... with a DEFAULT record
        assert doc.layers.get("GHOST").to_dict() == LayerRecord("GHOST").to_dict()
        # and the upgraded document round-trips byte-stably afterwards
        text = doc.serialize()
        assert Document.load(text).serialize() == text

    def test_v1_redo_rebuilds_entities_with_upgrade_defaults(self):
        """A v1 redo group carrying an add-with-entity op (v1 entity dict,
        no lineweight/space) redoes correctly after the upgrade."""
        doc = Document.load(V1_TEXT)
        assert doc.redo_depth() == 1
        assert doc.redo()
        arc = doc.get("cccc")
        assert arc.kind == "arc"
        assert arc.lineweight is None and arc.space == "MODEL"
        assert [e.id for e in doc.entities()] == ["aaaa", "bbbb", "cccc"]
        text = doc.serialize()
        assert Document.load(text).serialize() == text

    def test_v1_undo_works_and_keeps_working(self):
        doc = Document.load(V1_TEXT)
        assert doc.undo()   # pops the ghost group: bare add_layer -> defaults
        assert doc.layers.names() == ["0", "WALLS", "GHOST"]
        assert doc.undo()   # pops the draw group: entities + WALLS removed
        assert doc.layers.names() == ["0", "GHOST"]
        assert doc.entities() == []
        assert doc.redo()   # the draw group re-applies in original order
        assert [e.id for e in doc.entities()] == ["aaaa", "bbbb"]
        assert "WALLS" in doc.layers.names()

    def test_new_journal_ops_survive_save_load(self):
        doc = make_v2_doc()
        text = doc.serialize()
        mirror = Document.load(text)
        assert mirror.undo_depth() == doc.undo_depth()
        # undo the "tweak" (mutate_layer) group, then the big "setup" group
        assert mirror.undo()
        assert mirror.layers.get("WALLS").color == 30
        assert mirror.undo()
        assert mirror.layers.names() == ["0"]
        assert mirror.blocks() == []
        assert mirror.layouts() == []
        assert mirror.entities() == []
        assert mirror.text_styles() == ["Standard"]
        assert mirror.dim_styles() == ["Standard"]
        # redo restores everything (all new op kinds replay)
        assert mirror.redo()
        assert mirror.blocks() == ["SYM"]
        assert mirror.redo()
        assert mirror.layers.get("WALLS").color == 8
        assert Document.load(mirror.serialize()).serialize() == mirror.serialize()

    def test_unknown_schemas_rejected(self):
        for bad in (
            '{"schema": "bcdoc/3", "name": "x"}',
            '{"schema": "acme/9", "name": "x"}',
            "not json at all",
            '{"schema": "bcdoc/1"}',   # v1 but missing required keys
            '{"schema": "bcdoc/2"}',   # v2 but missing required keys
            "{}",
        ):
            with pytest.raises(errors.SerializationError):
                Document.load(bad)

    def test_v2_structural_garbage_rejected(self):
        """Corrupt exactly one key of an otherwise valid bcdoc/2 payload
        (built programmatically — no fragile JSON string surgery)."""
        def base() -> dict:
            return {
                "schema": "bcdoc/2", "name": "x", "units": {},
                "doc_version": 0, "next_handle": 1, "settings": {},
                "current_layer": "0", "layers": [{"name": "0"}],
                "text_styles": [], "dim_styles": [], "blocks": [],
                "layouts": [], "entities": [], "undo": [], "redo": [],
                "selection": {"ids": [], "epoch": 0},
            }

        line_record = {"kind": "line", "id": "a", "handle": 1, "layer": "0",
                       "color": None, "linetype": "x",
                       "p1": [0, 0, 0], "p2": [1, 1, 1]}
        cases = []
        payload = base()
        payload["layers"] = [{"color": 7}]          # record without a name
        cases.append(payload)
        payload = base()
        payload["layers"] = [{"name": "0"}, {"name": "0"}]  # duplicate layer
        cases.append(payload)
        payload = base()
        payload["blocks"] = [{"name": "B", "base_point": [0, 0],
                              "handle": 1, "entities": []}]
        payload["entities"] = [dict(line_record)]  # block handle vs entity handle
        cases.append(payload)
        payload = base()
        payload["layouts"] = [{"name": "P"}, {"name": "P"}]
        cases.append(payload)
        payload = base()
        payload["text_styles"] = [{"name": "S"}, {"name": "S"}]
        cases.append(payload)
        payload = base()
        payload["settings"] = {"NOPE": 1}           # unknown setting name
        cases.append(payload)
        payload = base()
        payload["undo"] = [{"label": "x", "doc_version": 1,
                            "entries": [{"op": "teleport"}]}]
        cases.append(payload)
        payload = base()
        payload["blocks"] = [{"name": "B", "base_point": [0, 0],
                              "handle": 1, "entities": [line_record]},
                             {"name": "B", "base_point": [0, 0],
                              "handle": 2, "entities": []}]
        cases.append(payload)                       # duplicate block name
        for bad in cases:
            with pytest.raises(errors.SerializationError):
                Document.load(json.dumps(bad))
        # the untouched base payload loads fine (control)
        assert Document.load(json.dumps(base())).name == "x"

    def test_entity_space_and_lineweight_round_trip(self):
        doc = Document()
        with doc.transaction("l"):
            doc.add_layout("Page1")
        with doc.transaction("e"):
            doc.add_entity(Line((0, 0), (1, 1), space="Page1", lineweight=0.5))
            doc.add_entity(Text((0, 0), content="note", space="Page1"))
        text = doc.serialize()
        mirror = Document.load(text)
        assert mirror.serialize() == text
        [line, note] = mirror.entities_in_space("Page1")
        assert line.lineweight == 0.5
        assert note.content == "note"
        assert [e.space for e in mirror.entities()] == ["Page1", "Page1"]

    def test_insert_dim_text_survive_journal_undo_after_load(self):
        """New kinds inside undo/redo groups rebuild correctly after a
        save/load cycle (entity_from_dict per-kind validation)."""
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Insert("A", (1, 2)))
            doc.add_entity(Dim("linear", (0, 0), (5, 0), measurement=5.0))
        text = doc.serialize()
        mirror = Document.load(text)
        assert mirror.undo()
        assert mirror.entities() == []
        assert mirror.redo()
        insert, dim = mirror.entities()
        assert insert.name == "A" and insert.scale == (1.0, 1.0, 1.0)
        assert dim.dim_type == "linear" and dim.measurement == 5.0


# ---------------------------------------------------------------------------
# snapshot/rollback atomicity with table ops (contract §2.8)
# ---------------------------------------------------------------------------

class TestRollbackAtomicity:
    def test_failing_transaction_rolls_back_all_tables(self):
        doc = make_v2_doc()
        doc.selection.set(["mark"])
        before = doc.serialize()
        with pytest.raises(RuntimeError):
            with doc.transaction("doomed"):
                doc.layers.add("DOOMED")
                doc.layers.set_props("WALLS", color=1)
                doc.add_block("DOOMED", (0, 0), [Line((0, 0), (1, 1))])
                doc.add_layout("DOOMED")
                doc.add_text_style("DOOMED")
                doc.add_dim_style("DOOMED")
                doc.add_entity(Point((50, 50)))
                doc.remove(doc.entities()[0].id)
                # sysvar exception: settings changes inside a failing tx
                # deliberately SURVIVE the rollback (contracts §2.5)
                doc.settings.set("LUNITS", 3)
                doc.set_current_space("Page1")   # touches TILEMODE
                raise RuntimeError("mid-transaction failure")
        after = json.loads(doc.serialize())
        expected = json.loads(before)
        expected["settings"]["LUNITS"] = 3
        expected["settings"]["TILEMODE"] = 0
        assert after == expected
        assert "DOOMED" not in doc.layers.names()
        assert doc.layers.get("WALLS").color == 8   # set_props rolled back
        assert doc.blocks() == ["SYM"]
        assert doc.layouts() == ["Page1"]
        assert doc.text_styles() == ["Standard", "TECH"]
        assert doc.undo_depth() == 2            # no phantom undo group
        assert doc.current_space == "Page1"     # session state kept
        # undo still works on the pre-failure history
        assert doc.undo()
        assert doc.layers.get("WALLS").color == 30

    def test_journal_conflicts_on_state_mismatch(self):
        doc = Document()
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "remove_block", "name": "GHOST"})
        with doc.transaction("b"):
            doc.add_block("B", (0, 0), [Line((0, 0), (1, 1))])
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "add_block", "name": "B", "base_point": [0, 0],
                           "handle": 9999, "entities": []})
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "rename_layout", "old": "X", "new": "Y"})
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "reorder_layout", "name": "X",
                            "old_index": 0})
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "remove_text_style", "name": "Standard"})
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "remove_layer", "name": "0"})
