"""bcdoc v0 contract tests — M1 module contracts §3.

Plain pytest, no Blender, no mocks of bcdoc internals (honesty rule).
Covers: creation defaults, transaction commit/rollback semantics,
NoOpenTransaction, undo/redo round-trips + doc_version monotonicity,
handle monotonicity (no reuse after remove), selection epochs,
serialization round-trip equality + schema rejection, events.
"""

import pytest

from bcdoc import (
    Arc,
    Circle,
    Document,
    Entity,
    Line,
    SelectionState,
    Transaction,
    UndoGroup,
    errors,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_sample_doc():
    doc = Document("sample")
    with doc.transaction("draw"):
        doc.add_layer("WALLS")
        doc.add_entity(Line((0, 0, 0), (10, 0, 0), layer="0", color=1))
        doc.add_entity(Line((0, 0), (0, 7), layer="WALLS", color=30))
        doc.add_entity(Circle((5, 3), 2.5, layer="WALLS"))
        doc.add_entity(Arc((2.5, 2.5), 1.75, 15.5, 202.25, layer="0", color=7))
    return doc


# ---------------------------------------------------------------------------
# creation defaults (contract §3.2)
# ---------------------------------------------------------------------------

class TestCreationDefaults:
    def test_defaults(self):
        doc = Document()
        assert doc.name == "Untitled"
        assert doc.doc_version == 0
        assert doc.layers == ["0"]
        assert doc.units == {"length": "mm", "angle": "deg"}
        assert doc.next_handle == 4097
        assert doc.entities() == []
        assert doc.count_by_kind() == {}
        assert doc.undo_depth() == 0
        assert doc.redo_depth() == 0
        assert doc.selection.ids == frozenset()
        assert doc.selection.epoch == 0
        assert doc.on_change == []
        assert doc.on_select == []

    def test_units_merge_fixed_order(self):
        doc = Document(units={"length": "in"})
        assert doc.units == {"length": "in", "angle": "deg"}
        doc = Document(units={"angle": "rad", "length": "m"})
        assert doc.units == {"length": "m", "angle": "rad"}

    def test_entity_defaults_and_kinds(self):
        line = Line((0, 0), (1, 2, 3))
        circle = Circle((1, 2), 5)
        arc = Arc((1, 2), 5, 0, 90)
        assert isinstance(line, Entity) and isinstance(circle, Entity) and isinstance(arc, Entity)
        assert (line.kind, circle.kind, arc.kind) == ("line", "circle", "arc")
        for e in (line, circle, arc):
            assert isinstance(e.id, str) and len(e.id) == 32  # uuid4 hex
            assert e.handle == 0  # unassigned until added
            assert e.layer == "0"
            assert e.color is None
            assert e.linetype == "ByLayer"
        # 2D input is normalized to 3D with z=0.0; values to float
        assert line.p1 == (0.0, 0.0, 0.0)
        assert circle.center == (1.0, 2.0, 0.0)
        assert circle.radius == 5.0
        assert (arc.start_angle, arc.end_angle) == (0.0, 90.0)

    def test_ids_are_unique_and_immutable_in_use(self):
        a, b = Line((0, 0), (1, 1)), Line((0, 0), (1, 1))
        assert a.id != b.id


# ---------------------------------------------------------------------------
# transactions (contract §3.3)
# ---------------------------------------------------------------------------

class TestTransactions:
    def test_commit_bumps_version_and_returns_entity(self):
        doc = Document()
        line = Line((0, 0), (1, 1))
        with doc.transaction("add line") as tx:
            added = doc.add_entity(line)
        assert added is line
        assert tx.committed is True
        assert tx.closed is True
        assert doc.doc_version == 1
        assert doc.get(line.id) is line
        assert doc.entities() == [line]
        assert line.handle == 4097
        assert doc.next_handle == 4098

    def test_rollback_is_byte_identical(self):
        doc = make_sample_doc()
        doc.selection.set(["nonsense-id"])
        before = doc.serialize()
        with pytest.raises(RuntimeError):
            with doc.transaction("doomed"):
                doc.add_entity(Line((9, 9), (8, 8)))
                doc.update_entity(doc.entities()[0].id, p2=(100, 100, 100))
                doc.remove(doc.entities()[1].id)
                doc.add_layer("NEWLAYER")
                doc.selection.set([])
                raise RuntimeError("mid-transaction failure")
        assert doc.serialize() == before, "rolled-back document must be bit-identical"
        assert doc.doc_version == 1  # unchanged by the aborted tx
        assert "NEWLAYER" not in doc.layers
        assert doc.selection.ids == frozenset({"nonsense-id"})

    def test_no_open_transaction_raised(self):
        doc = Document()
        with pytest.raises(errors.NoOpenTransaction):
            doc.add_entity(Line((0, 0), (1, 1)))
        with pytest.raises(errors.NoOpenTransaction):
            doc.remove("anything")
        with pytest.raises(errors.NoOpenTransaction):
            doc.update_entity("anything", layer="X")
        with pytest.raises(errors.NoOpenTransaction):
            doc.add_layer("WALLS")

    def test_nested_transaction_rejected(self):
        doc = Document()
        with doc.transaction("outer"):
            with pytest.raises(errors.TransactionAlreadyOpen):
                doc.transaction("inner")
            with pytest.raises(errors.TransactionAlreadyOpen):
                doc.undo()
            with pytest.raises(errors.TransactionAlreadyOpen):
                doc.redo()

    def test_transaction_is_reusable_object_semantics(self):
        doc = Document()
        tx = doc.transaction("one")
        with tx:
            doc.add_entity(Line((0, 0), (1, 1)))
        assert isinstance(tx, Transaction)
        # a closed transaction cannot be re-entered
        with pytest.raises(errors.BcdocError):
            with tx:
                pass


# ---------------------------------------------------------------------------
# entities: order, lookup, errors
# ---------------------------------------------------------------------------

class TestEntityStore:
    def test_insertion_order_and_count_by_kind(self):
        doc = make_sample_doc()
        kinds = [e.kind for e in doc.entities()]
        assert kinds == ["line", "line", "circle", "arc"]
        assert doc.count_by_kind() == {"line": 2, "circle": 1, "arc": 1}

    def test_get_remove_errors(self):
        doc = Document()
        with pytest.raises(errors.EntityNotFound):
            doc.get("nope")
        with doc.transaction("t"):
            with pytest.raises(errors.EntityNotFound):
                doc.remove("nope")

    def test_duplicate_entity_rejected(self):
        doc = Document()
        line = Line((0, 0), (1, 1))
        with doc.transaction("t"):
            doc.add_entity(line)
            with pytest.raises(errors.DuplicateEntity):
                doc.add_entity(line)

    def test_remove(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("rm"):
            removed = doc.remove(line.id)
        assert removed is line
        assert doc.entities() == []
        with pytest.raises(errors.EntityNotFound):
            doc.get(line.id)

    def test_update_entity_journaled(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("move"):
            doc.update_entity(line.id, p1=(5, 5, 5), color=3)
        moved = doc.get(line.id)
        assert moved.p1 == (5.0, 5.0, 5.0)
        assert moved.color == 3
        assert doc.undo()
        assert doc.get(line.id).p1 == (0.0, 0.0, 0.0)
        assert doc.get(line.id).color is None
        assert doc.redo()
        assert doc.get(line.id).p1 == (5.0, 5.0, 5.0)

    def test_update_entity_invalid_field(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("bad"):
            with pytest.raises(errors.InvalidEntityField):
                doc.update_entity(line.id, radius=10.0)  # lines have no radius

    def test_update_entity_layer_auto_creates_and_undo_reverts_both(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("relabel"):
            doc.update_entity(line.id, layer="NEW")
        assert doc.layers == ["0", "NEW"]
        assert doc.get(line.id).layer == "NEW"
        assert doc.undo()
        assert doc.layers == ["0"]
        assert doc.get(line.id).layer == "0"

    def test_update_entity_no_partial_apply_on_bad_field(self):
        doc = Document()
        with doc.transaction("t"):
            line = doc.add_entity(Line((0, 0), (1, 1)))
        with doc.transaction("bad"):
            with pytest.raises(errors.InvalidEntityField):
                doc.update_entity(line.id, p1=(9, 9, 9), bogus=1)
        # p1 must NOT have been applied (fields validated first)
        assert doc.get(line.id).p1 == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# handles (contract §3.1: monotonic, never reused)
# ---------------------------------------------------------------------------

class TestHandles:
    def test_monotonic_allocation(self):
        doc = Document()
        with doc.transaction("t"):
            handles = [doc.add_entity(Line((0, 0), (1, 1))).handle
                       for _ in range(3)]
        assert handles == [4097, 4098, 4099]
        assert doc.next_handle == 4100

    def test_no_reuse_after_remove(self):
        doc = Document()
        with doc.transaction("t"):
            first = doc.add_entity(Line((0, 0), (1, 1))).handle
        with doc.transaction("rm+add"):
            doc.remove(doc.entities()[0].id)
            second = doc.add_entity(Line((0, 0), (1, 1))).handle
        assert second > first, "handles must never be reused after a remove"

    def test_explicit_handle_preserved_and_advances_next(self):
        doc = Document()
        with doc.transaction("t"):
            e = doc.add_entity(Line((0, 0), (1, 1)), handle=0x2000)
            f = doc.add_entity(Line((0, 0), (1, 1)))
        assert e.handle == 0x2000
        assert f.handle == 0x2001
        assert doc.next_handle == 0x2002

    def test_explicit_handle_collision_raises(self):
        doc = Document()
        with doc.transaction("t"):
            a = doc.add_entity(Line((0, 0), (1, 1)))
            with pytest.raises(errors.DuplicateHandle):
                doc.add_entity(Line((0, 0), (1, 1)), handle=a.handle)
            with pytest.raises(errors.InvalidHandle):
                doc.add_entity(Line((0, 0), (1, 1)), handle=0)
            # failed attempts consumed nothing
            b = doc.add_entity(Line((0, 0), (1, 1)))
        assert b.handle == a.handle + 1

    def test_undo_does_not_rewind_handle_allocation(self):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 1)))
        assert doc.undo()
        assert doc.entities() == []
        with doc.transaction("t2"):
            fresh = doc.add_entity(Line((0, 0), (1, 1)))
        assert fresh.handle == 4098, "undo must not free its handle for reuse"


# ---------------------------------------------------------------------------
# undo / redo (contract §3.3: monotonic doc_version both directions)
# ---------------------------------------------------------------------------

class TestUndoRedo:
    def _draw(self, doc):
        with doc.transaction("draw"):
            doc.add_entity(Line((0, 0), (10, 0)))
            doc.add_entity(Circle((0, 0), 4))

    def test_undo_redo_roundtrip_and_monotonicity(self):
        doc = Document()
        assert doc.undo() is False
        assert doc.redo() is False
        self._draw(doc)
        versions = [doc.doc_version]  # 1

        assert doc.undo() is True
        versions.append(doc.doc_version)  # 2
        assert doc.entities() == []
        assert doc.undo_depth() == 0 and doc.redo_depth() == 1

        assert doc.redo() is True
        versions.append(doc.doc_version)  # 3
        assert doc.undo_depth() == 1 and doc.redo_depth() == 0

        assert versions == sorted(versions), "doc_version must be monotonic"
        assert versions == [1, 2, 3]

        # geometry + handles survive the undo -> redo cycle exactly
        for entity in doc.entities():
            assert entity.handle >= 4097, "handles must not be re-allocated"
        line = [e for e in doc.entities() if e.kind == "line"][0]
        assert line.p1 == (0.0, 0.0, 0.0) and line.p2 == (10.0, 0.0, 0.0)
        circle = [e for e in doc.entities() if e.kind == "circle"][0]
        assert circle.center == (0.0, 0.0, 0.0) and circle.radius == 4.0

        # a serialized copy of the same state is byte-identical
        mirror = Document.load(doc.serialize())
        assert [e.kind for e in mirror.entities()] == ["line", "circle"]
        assert mirror.serialize() == doc.serialize()
        assert mirror.doc_version == doc.doc_version

    def test_doc_version_never_decreases_across_interleavings(self):
        """Monotonicity rule (glossary §6): every committed transaction —
        user, import or UNDO/REDO themselves — only ever moves doc_version
        UP, even when the geometry moves back in history."""
        doc = Document()
        history = [doc.doc_version]
        with doc.transaction("a"):
            doc.add_entity(Line((0, 0), (1, 1)))
        history.append(doc.doc_version)
        for _ in range(2):  # undo/redo ping-pong bumps the counter twice
            assert doc.undo()
            history.append(doc.doc_version)
            assert doc.redo()
            history.append(doc.doc_version)
        with doc.transaction("b"):
            doc.add_entity(Circle((0, 0), 1))
        assert doc.undo()
        history.append(doc.doc_version)
        assert all(later >= earlier
                   for earlier, later in zip(history, history[1:])), history
        assert len(set(history)) == len(history), history  # strictly increasing

    def test_undo_restores_geometry_and_insertion_order(self):
        doc = Document()
        with doc.transaction("t1"):
            a = doc.add_entity(Line((0, 0), (1, 0)))
        with doc.transaction("t2"):
            b = doc.add_entity(Line((0, 1), (1, 1)))
            c = doc.add_entity(Circle((0, 0), 2))
        order_before = [(e.kind, e.id) for e in doc.entities()]

        assert doc.undo()  # undo t2
        assert [(e.kind, e.id) for e in doc.entities()] == [(a.kind, a.id)]
        assert doc.redo()
        assert [(e.kind, e.id) for e in doc.entities()] == order_before
        assert doc.get(b.id).p2 == (1.0, 1.0, 0.0)

    def test_redo_cleared_on_new_mutation(self):
        doc = Document()
        self._draw(doc)
        assert doc.undo()
        assert doc.redo_depth() == 1
        with doc.transaction("new work"):
            doc.add_entity(Arc((0, 0), 1, 0, 90))
        assert doc.redo_depth() == 0
        assert doc.redo() is False

    def test_undo_of_remove_restores_position(self):
        doc = Document()
        with doc.transaction("t"):
            doc.add_entity(Line((0, 0), (1, 0)))
            mid = doc.add_entity(Line((0, 1), (1, 1))).id
            doc.add_entity(Line((0, 2), (1, 2)))
        with doc.transaction("rm middle"):
            doc.remove(mid)
        assert len(doc.entities()) == 2
        assert doc.undo()
        assert [e.p1[1] for e in doc.entities()] == [0.0, 1.0, 2.0]

    def test_undo_depth_across_transactions(self):
        doc = Document()
        for i in range(3):
            with doc.transaction(f"tx{i}"):
                doc.add_entity(Line((i, 0), (i, 1)))
        assert doc.undo_depth() == 3
        assert doc.undo()
        assert doc.undo_depth() == 2
        assert doc.redo_depth() == 1
        assert len(doc.entities()) == 2

    def test_undo_group_content(self):
        doc = Document()
        with doc.transaction("label me"):
            doc.add_entity(Line((0, 0), (1, 1)))
        group = doc.undo_groups()[-1]
        assert isinstance(group, UndoGroup)
        assert group.label == "label me"
        assert group.doc_version == 1
        assert group.entries == [{"op": "remove", "id": doc.entities()[0].id}]


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------

class TestLayers:
    def test_add_layer_requires_tx_and_journaled(self):
        doc = Document()
        with doc.transaction("layers"):
            doc.add_layer("WALLS")
        assert doc.layers == ["0", "WALLS"]
        with pytest.raises(errors.DuplicateLayer):
            with doc.transaction("dup"):
                doc.add_layer("WALLS")
        assert doc.undo()
        assert doc.layers == ["0"]

    def test_layer_zero_always_present(self):
        doc = Document()
        assert "0" in doc.layers
        # removing "0" through a hand-built journal is refused
        with pytest.raises(errors.JournalConflict):
            doc._apply_op({"op": "remove_layer", "name": "0"})


# ---------------------------------------------------------------------------
# selection (contract §3.4)
# ---------------------------------------------------------------------------

class TestSelection:
    def test_epoch_bumps_only_on_change(self):
        state = Document().selection
        start = state.epoch
        state.set(["a", "b"])
        assert state.epoch == start + 1
        state.add(["b", "c"])  # content actually changes
        assert state.epoch == start + 2
        state.add(["c"])  # no-op
        assert state.epoch == start + 2, "no-op calls must not bump epoch"
        state.remove(["z"])  # no-op
        assert state.epoch == start + 2
        state.remove("a")  # single string accepted
        assert state.ids == frozenset({"b", "c"})
        assert state.epoch == start + 3
        state.clear()
        assert state.epoch == start + 4
        state.clear()  # no-op
        assert state.epoch == start + 4

    def test_selection_never_bumps_doc_version(self):
        doc = make_sample_doc()
        v = doc.doc_version
        ids = [e.id for e in doc.entities()]
        doc.selection.set(ids)
        doc.selection.add("x")
        doc.selection.clear()
        assert doc.doc_version == v

    def test_ids_frozenset(self):
        doc = Document()
        doc.selection.set(["a", "b"])
        assert isinstance(doc.selection.ids, frozenset)
        assert doc.selection == doc.selection  # object identity trivially
        assert isinstance(doc.selection, SelectionState)


# ---------------------------------------------------------------------------
# events (contract §3.6)
# ---------------------------------------------------------------------------

class TestEvents:
    def test_change_event_fires_on_commit_only(self):
        doc = Document()
        seen = []
        doc.on_change.append(seen.append)
        with doc.transaction("tx"):
            doc.add_entity(Line((0, 0), (1, 1)))
            assert seen == [], "no event before commit"
        assert seen == [("doc", 1)]
        with pytest.raises(RuntimeError):
            with doc.transaction("boom"):
                raise RuntimeError
        assert seen == [("doc", 1)], "rollback must not fire on_change"
        assert doc.undo()
        assert seen == [("doc", 1), ("doc", 2)]

    def test_select_event_fires_with_epoch(self):
        doc = Document()
        seen = []
        doc.on_select.append(seen.append)
        doc.selection.set(["a"])
        assert seen == [("select", 1)]
        doc.selection.clear()
        assert seen == [("select", 1), ("select", 2)]


# ---------------------------------------------------------------------------
# serialization (contract §3.5)
# ---------------------------------------------------------------------------

class TestSerialization:
    """Schema assertions updated to the bcdoc/2 reality per m2 contracts
    §2.7/§14 (M1 file amended — intent kept: schema exactness, tolerant
    reads, byte-stability)."""

    def test_schema_is_bcdoc3(self):
        import json

        doc = make_sample_doc()
        payload = json.loads(doc.serialize())
        # bcdoc/3 since the m3 schema lane (m3-module-contracts.md §3
        # amends m2 §2.7; load still accepts bcdoc/1 + bcdoc/2)
        assert payload["schema"] == "bcdoc/3"
        # pinned v3 key order ("sketches" slots before "entities")
        assert list(payload) == [
            "schema", "name", "units", "doc_version", "next_handle",
            "settings", "layers", "current_layer", "text_styles",
            "dim_styles", "blocks", "layouts", "sketches", "entities",
            "undo", "redo", "selection",
        ]

    def test_byte_stable_round_trip(self):
        doc = make_sample_doc()
        doc.selection.set([doc.entities()[0].id])
        text1 = doc.serialize()
        doc2 = Document.load(text1)
        text2 = doc2.serialize()
        assert text1 == text2, "serialize(load(s)) must be byte-stable"
        assert doc2.name == "sample"
        assert doc2.doc_version == doc.doc_version
        assert doc2.layers == doc.layers
        assert doc2.count_by_kind() == doc.count_by_kind()
        assert doc2.undo_depth() == doc.undo_depth()
        assert doc2.selection.ids == doc.selection.ids
        assert doc2.selection.epoch == doc.selection.epoch

    def test_entities_round_trip_field_exact(self):
        doc = make_sample_doc()
        loaded = Document.load(doc.serialize())
        for original, mirror in zip(doc.entities(), loaded.entities()):
            assert original.id == mirror.id
            assert original.handle == mirror.handle
            assert original.layer == mirror.layer
            assert original.color == mirror.color
            assert original.linetype == mirror.linetype
            assert original.geometry_dict() == mirror.geometry_dict()

    def test_undo_journal_survives_round_trip(self):
        doc = make_sample_doc()  # 1 committed tx
        assert Document.load(doc.serialize()).undo_depth() == 1
        assert Document.load(doc.serialize()).undo() is True, (
            "a reloaded document can still undo its pre-save transaction"
        )

    def test_load_rejects_unknown_schema(self):
        for bad in (
            '{"schema": "bcdoc/3", "name": "x"}',  # newer unknown schema
            '{"schema": "acme/9", "name": "x"}',
            "not json at all",
            '["also", "not", "an", "object"]',
            "{}",  # missing schema key
            '{"schema": "bcdoc/1"}',  # v1 but missing required keys
            '{"schema": "bcdoc/2"}',  # v2 but missing required keys
        ):
            with pytest.raises(errors.SerializationError):
                Document.load(bad)

    def test_load_rejects_structural_garbage(self):
        base = ('{"schema": "bcdoc/2", "name": "x", "units": {}, '
                '"doc_version": 0, "next_handle": 1, "settings": {}, '
                '"current_layer": "0", "text_styles": [], "dim_styles": [], '
                '"blocks": [], "layouts": [], "layers": [{"name": "0"}], ')
        for bad in (
            base + '"entities": [{"kind": "triangle", "id": "a", "handle": 1, "layer": "0", "color": null, "linetype": "x"}], '
                   '"undo": [], "redo": [], "selection": {"ids": [], "epoch": 0}}',
            base + '"entities": [{"kind": "line", "id": "a", "handle": 1, "layer": "0", "color": null, "linetype": "x", "p1": [0,0,0]}], '
                   '"undo": [], "redo": [], "selection": {"ids": [], "epoch": 0}}',  # missing p2
            base + '"entities": [{"kind": "line", "id": "a", "handle": 1, "layer": "0", "color": null, "linetype": "x", "p1": [0,0,0], "p2": [1,1,1]}, '
                   '{"kind": "line", "id": "a", "handle": 2, "layer": "0", "color": null, "linetype": "x", "p1": [0,0,0], "p2": [1,1,1]}], '
                   '"undo": [], "redo": [], "selection": {"ids": [], "epoch": 0}}',  # duplicate id
            base + '"entities": [], "undo": [{"label": "x", "doc_version": 1, "entries": [{"op": "teleport"}]}], '
                   '"redo": [], "selection": {"ids": [], "epoch": 0}}',  # unknown op
        ):
            with pytest.raises(errors.SerializationError):
                Document.load(bad)

    def test_stable_json_key_order(self):
        doc = make_sample_doc()
        assert doc.serialize().startswith('{"schema": "bcdoc/3", "name": "sample"')
        entity = doc.serialize().split('"entities": [', 1)[1]
        assert '"kind": "line", "id":' in entity, "entity dicts keep fixed field order"


# ---------------------------------------------------------------------------
# identity + persistence guarantees relied on by the command layer (W1
# contract tests) — regression-pinned here after two real bugs were caught
# by modules/commands/tests/test_document_contract.py at M1 integration.
# ---------------------------------------------------------------------------


class TestIdentityAndJournalPersistence:
    def test_undo_of_remove_restores_the_same_object(self):
        """Undo of a removal must bring back the very same Python object
        (the command layer and display sync hold direct references)."""
        doc = Document()
        with doc.transaction("create"):
            circle = doc.add_entity(Circle((0, 0, 0), 1))
        with doc.transaction("erase"):
            removed = doc.remove(circle.id)
        assert removed is circle
        assert doc.undo()
        assert doc.get(circle.id) is circle, (
            "undo must restore the SAME object, not an equal copy"
        )
        # and the full remove -> undo -> redo -> undo cycle keeps identity
        assert doc.redo()
        assert doc.entities() == []
        assert doc.undo()
        assert doc.get(circle.id) is circle

    def test_serialize_load_after_undo_keeps_redo_and_byte_stability(self):
        """A document with a NON-EMPTY redo stack (undo ops carry embedded
        entity records without a top-level 'id') must survive
        serialize -> load byte-stably and stay redoable after reload."""
        doc = Document(name="RT")
        with doc.transaction("t1"):
            doc.add_entity(Line((0, 0, 0), (10, 0, 0), color=1))
            doc.add_entity(Circle((5, 5, 0), 2.5))
            doc.add_entity(Arc((0, 0, 0), 3, 10, 260))
        assert doc.undo()  # pushes the redo group with three add ops
        assert doc.redo_depth() == 1

        text = doc.serialize()
        loaded = Document.load(text)
        assert loaded.serialize() == text, "byte-stable with a live redo stack"
        assert loaded.doc_version == doc.doc_version
        assert loaded.redo_depth() == 1
        assert loaded.undo_depth() == doc.undo_depth()
        assert loaded.selection.epoch == doc.selection.epoch

        # redo still works from the reloaded journal (rebuilds the entities)
        assert loaded.redo() is True
        assert [e.kind for e in loaded.entities()] == ["line", "circle", "arc"]
        assert [e.handle for e in loaded.entities()] == [4097, 4098, 4099]
        # redo moved the group back onto the undo stack (one deep, not two:
        # the original tx group was already consumed by the pre-save undo)
        assert loaded.redo_depth() == 0 and loaded.undo_depth() == 1
