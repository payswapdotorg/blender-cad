"""bcdoc v3 contract tests — m3-module-contracts.md (the bcdoc/3 schema
lane: SketchTable, junction identity, workplane records, driving-dimension
records, solve-report records).

Plain pytest, no Blender, no mocks of bcdoc internals (honesty rule — the
same discipline as the v2 suite). Covers: the record vocabulary (closed
constraint kinds, arity, dimensional/geometric value+driven rules, ref
forms), the journaled table ops with per-constraint undo granularity (the
first-class parametric edit), junction identity across member growth, the
dangling-ref/EntityInUse guards, bcdoc/3 serialization (pinned key order,
byte-stability, the v2/v1 deterministic upgrades, parse-time cross
validation, journals through save/load), solve-report session state, and
failed-transaction rollback atomicity over sketches.

The W1 rect fixture from the committed canonical corpus (the fixture that
rejected slvs and named the redundancy via SolidCraft) is stored as REAL
document content — the schema's tie to the measured evidence.
"""

import json

import pytest

from bcdoc import (
    Circle,
    Document,
    Line,
    SketchRecord,
    Workplane,
    errors,
)
from bcdoc.sketches import (
    CONSTRAINT_KINDS,
    ConstraintRecord,
    JunctionRecord,
    SolveReport,
    SolveReports,
    SketchTable,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_sketch_doc() -> Document:
    """The seam's demonstrated triangle (findings/bcdoc-seam.md §3) as
    first-class bcdoc/3 content: 3 lines sharing 3 junctions, A on the
    origin, l1 horizontal, |AB|=50, |BC|=45, angle(l1,l3)=60."""
    doc = Document("sketch-sample")
    with doc.transaction("triangle"):
        l1 = doc.add_entity(Line((0, 0, 0), (50, 0, 0)))
        l2 = doc.add_entity(Line((50, 0, 0), (48, 3, 0)))
        l3 = doc.add_entity(Line((33, 22, 0), (0, 0, 0)))
        doc.sketches.add("sk1", name="Triangle")
        for jid, members in (
            ("jA", [{"entity": l3.id, "slot": 1}, {"entity": l1.id, "slot": 0}]),
            ("jB", [{"entity": l1.id, "slot": 1}, {"entity": l2.id, "slot": 0}]),
            ("jC", [{"entity": l2.id, "slot": 1}, {"entity": l3.id, "slot": 0}]),
        ):
            doc.sketches.add_junction("sk1", members, junction_id=jid)
        doc.sketches.add_constraint("sk1", "coincident_origin",
                                    [{"junction": "jA"}], c_id="k1")
        doc.sketches.add_constraint("sk1", "horizontal",
                                    [{"entity": l1.id}], c_id="k2")
        doc.sketches.add_constraint("sk1", "distance",
                                    [{"junction": "jA"}, {"junction": "jB"}],
                                    value=50.0, c_id="d1")
        doc.sketches.add_constraint("sk1", "distance",
                                    [{"junction": "jB"}, {"junction": "jC"}],
                                    value=45.0, c_id="d2")
        doc.sketches.add_constraint("sk1", "angle",
                                    [{"entity": l1.id}, {"entity": l3.id}],
                                    value=60.0, c_id="d3")
    return doc


# ---------------------------------------------------------------------------
# records: vocabulary, refs, value/driven rules
# ---------------------------------------------------------------------------

class TestConstraintRecord:
    def test_vocabulary_is_the_evidenced_set(self):
        assert CONSTRAINT_KINDS == {
            "coincident": (2, "geometric"),
            "coincident_origin": (1, "geometric"),
            "horizontal": (1, "geometric"),
            "vertical": (1, "geometric"),
            "parallel": (2, "geometric"),
            "perpendicular": (2, "geometric"),
            "tangent": (2, "geometric"),
            "concentric": (2, "geometric"),
            "midpoint": (2, "geometric"),
            "symmetric": (3, "geometric"),
            "distance": (2, "dimensional"),
            "length": (1, "dimensional"),
            "radius": (1, "dimensional"),
            "diameter": (1, "dimensional"),
            "angle": (2, "dimensional"),
        }

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="unknown constraint kind"):
            ConstraintRecord(kind="welded", refs=())

    def test_arity_is_exact(self):
        with pytest.raises(ValueError, match="takes exactly 2 ref"):
            ConstraintRecord(kind="coincident", refs=[{"entity": "a"}])
        with pytest.raises(ValueError, match="takes exactly 1 ref"):
            ConstraintRecord(kind="horizontal",
                             refs=[{"entity": "a"}, {"entity": "b"}])

    def test_dimensional_needs_finite_value(self):
        with pytest.raises(ValueError, match="numeric value"):
            ConstraintRecord(kind="distance",
                             refs=[{"entity": "a"}, {"entity": "b"}])
        with pytest.raises(ValueError, match="finite"):
            ConstraintRecord(kind="length", refs=[{"entity": "a"}],
                            value=float("inf"))

    def test_geometric_takes_no_value_no_driven(self):
        with pytest.raises(ValueError, match="takes no value"):
            ConstraintRecord(kind="horizontal", refs=[{"entity": "a"}],
                             value=5.0)
        with pytest.raises(ValueError, match="cannot be driven"):
            ConstraintRecord(kind="parallel",
                             refs=[{"entity": "a"}, {"entity": "b"}],
                             driven=True)

    def test_driven_reference_dimension_is_first_class(self):
        rec = ConstraintRecord(kind="distance",
                               refs=[{"entity": "a"}, {"entity": "b"}],
                               value=50.0, driven=True)
        assert rec.driven is True and rec.value == 50.0
        # the gating flag round-trips and toggles through set()
        prior = rec.set(driven=False)
        assert prior == {"driven": True}
        assert rec.driven is False

    def test_ref_forms(self):
        whole = {"entity": "e1"}
        slot = {"entity": "e1", "slot": 0}
        junction = {"junction": "j1"}
        assert ConstraintRecord(kind="symmetric",
                                refs=[whole, slot, junction]).refs == \
            (whole, slot, junction)
        with pytest.raises(ValueError, match="slot must be 0 or 1"):
            ConstraintRecord(kind="symmetric",
                             refs=[whole, {"entity": "e", "slot": 2}, junction])
        with pytest.raises(ValueError, match="slot must be 0 or 1"):
            ConstraintRecord(kind="symmetric",
                            refs=[whole, {"entity": "e", "slot": True}, junction])
        with pytest.raises(ValueError, match="'entity' or 'junction'"):
            ConstraintRecord(kind="symmetric", refs=[whole, {}, junction])

    def test_auto_c_id_and_pinned_dict(self):
        auto = ConstraintRecord(kind="radius", refs=[{"entity": "c"}], value=2.0)
        assert auto.c_id and isinstance(auto.c_id, str)
        assert auto.to_dict() == {
            "c_id": auto.c_id, "kind": "radius",
            "refs": [{"entity": "c"}], "value": 2.0, "driven": False,
        }
        assert list(auto.to_dict()) == ["c_id", "kind", "refs", "value", "driven"]

    def test_set_is_atomic_no_partial_apply(self):
        rec = ConstraintRecord(kind="distance",
                               refs=[{"entity": "a"}, {"entity": "b"}],
                               value=50.0)
        with pytest.raises(ValueError, match="immutable"):
            rec.set(c_id="other")
        with pytest.raises(ValueError):
            rec.set(kind="length", value=None)  # length needs a value
        assert rec.kind == "distance" and rec.value == 50.0  # untouched
        prior = rec.set(kind="length", refs=[{"entity": "a"}], value=40.0)
        assert prior == {"kind": "distance",
                         "refs": ({"entity": "a"}, {"entity": "b"}),
                         "value": 50.0}

    def test_from_dict_round_trip(self):
        rec = ConstraintRecord(kind="angle",
                               refs=[{"entity": "a"}, {"entity": "b"}],
                               value=60.0, c_id="d3")
        assert ConstraintRecord.from_dict(rec.to_dict()) == rec
        with pytest.raises(ValueError):
            ConstraintRecord.from_dict({"kind": "distance"})


class TestWorkplaneAndJunctionRecords:
    def test_default_workplane_is_xy_at_origin(self):
        assert Workplane().to_dict() == {
            "origin": [0.0, 0.0, 0.0], "x_axis": [1.0, 0.0, 0.0],
            "y_axis": [0.0, 1.0, 0.0],
        }

    def test_workplane_rejects_degenerate_bases(self):
        with pytest.raises(ValueError, match="non-zero"):
            Workplane(x_axis=(0, 0, 0))
        with pytest.raises(ValueError, match="parallel"):
            Workplane(x_axis=(1, 0, 0), y_axis=(2, 0, 0))

    def test_junction_members_need_slots(self):
        with pytest.raises(ValueError, match="need a slot"):
            JunctionRecord([{"entity": "a"}])
        with pytest.raises(ValueError, match="at least one member"):
            JunctionRecord([])
        rec = JunctionRecord([{"entity": "a", "slot": 0}], junction_id="j1")
        assert rec.to_dict() == {"junction_id": "j1",
                                 "members": [{"entity": "a", "slot": 0}]}

    def test_junction_set_grows_members_keeping_identity(self):
        rec = JunctionRecord([{"entity": "a", "slot": 0}], junction_id="j1")
        prior = rec.set(members=[{"entity": "a", "slot": 0},
                                 {"entity": "b", "slot": 1}])
        assert prior == {"members": ({"entity": "a", "slot": 0},)}
        assert rec.junction_id == "j1" and len(rec.members) == 2


# ---------------------------------------------------------------------------
# the sketch table: journaled lifecycle ops
# ---------------------------------------------------------------------------

class TestSketchTableOps:
    def test_add_get_remove_are_journaled_and_undoable(self):
        doc = Document()
        with doc.transaction("t1"):
            doc.sketches.add("s1", name="First")
            doc.sketches.add("s2")
        assert doc.sketches.ids() == ["s1", "s2"]
        assert doc.sketches.get("s1").name == "First"
        assert doc.sketches.get("s2").name == "s2"  # defaults to the id
        assert len(doc.sketches.records()) == 2

        with doc.transaction("t2"):
            doc.sketches.remove("s1")
        assert doc.sketches.ids() == ["s2"]
        doc.undo()
        assert doc.sketches.ids() == ["s1", "s2"]
        assert doc.sketches.get("s1").name == "First"   # full-record inverse
        doc.redo()
        assert doc.sketches.ids() == ["s2"]
        doc.undo()
        # undo/redo replays are committed transactions (doc_version bumps,
        # new journal groups with replay labels), so serialize() differs —
        # the CONTENT invariants are what hold across the ping-pong:
        assert doc.sketches.ids() == ["s1", "s2"]
        assert doc.sketches.get("s1").name == "First"
        # ...and the state at any point round-trips byte-stably
        text = doc.serialize()
        assert Document.load(text).serialize() == text

    def test_journal_payloads(self):
        doc = Document()
        with doc.transaction("t") as tx:
            doc.sketches.add("s1", workplane=Workplane())
            raw_ops = list(tx.journal)
        (op,) = raw_ops
        assert op["op"] == "add_sketch" and op["sketch_id"] == "s1"
        assert op["record"]["workplane"]["origin"] == [0.0, 0.0, 0.0]

    def test_mutations_require_open_transaction(self):
        doc = Document()
        for call in (
            lambda: doc.sketches.add("s1"),
            lambda: doc.sketches.remove("s1"),
            lambda: doc.sketches.set_props("s1", name="x"),
            lambda: doc.sketches.add_constraint("s1", "horizontal", []),
            lambda: doc.sketches.set_constraint("s1", "k", value=1.0),
            lambda: doc.sketches.remove_constraint("s1", "k"),
            lambda: doc.sketches.add_junction("s1", []),
            lambda: doc.sketches.set_junction("s1", "j", []),
            lambda: doc.sketches.remove_junction("s1", "j"),
        ):
            with pytest.raises(errors.NoOpenTransaction):
                call()

    def test_set_props_journals_prior_values(self):
        doc = make_sketch_doc()
        with doc.transaction("rename + workplane") as tx:
            doc.sketches.set_props("sk1", name="Frame",
                                   workplane=Workplane(origin=(1, 2, 3)))
            raw_ops = list(tx.journal)
        assert doc.sketches.get("sk1").name == "Frame"
        assert doc.sketches.get("sk1").workplane.origin == (1.0, 2.0, 3.0)
        assert raw_ops[0]["changes"] == {
            "name": "Triangle",
            "workplane": {"origin": [0.0, 0.0, 0.0], "x_axis": [1.0, 0.0, 0.0],
                          "y_axis": [0.0, 1.0, 0.0]},
        }
        doc.undo()
        assert doc.sketches.get("sk1").name == "Triangle"
        assert doc.sketches.get("sk1").workplane.origin == (0.0, 0.0, 0.0)

    def test_duplicate_and_missing_keys(self):
        doc = Document()
        with doc.transaction("t"):
            doc.sketches.add("s1")
            with pytest.raises(errors.DuplicateSketch):
                doc.sketches.add("s1")
        # get() is the LayerTable convention: None for unknown keys
        assert doc.sketches.get("nope") is None
        with doc.transaction("t2"):
            with pytest.raises(errors.SketchNotFound):
                doc.sketches.remove("nope")

    def test_workplane_change_journal_survives_save_reopen(self):
        """A workplane change journals the PRIOR plane in its JSON-safe dict
        form (live objects would break undo-stack serialization) and the
        replay path converts the dict back."""
        doc = Document()
        with doc.transaction("t1"):
            doc.sketches.add("s1")
        with doc.transaction("t2"):
            doc.sketches.set_props("s1", workplane=Workplane(origin=(5, 5, 5)))
        text = doc.serialize()
        (entry,) = [e for g in json.loads(text)["undo"] for e in g["entries"]
                    if e["op"] == "mutate_sketch"]
        assert entry["changes"] == {
            "workplane": {"origin": [0.0, 0.0, 0.0], "x_axis": [1.0, 0.0, 0.0],
                          "y_axis": [0.0, 1.0, 0.0]}}
        revived = Document.load(text)
        assert revived.sketches.get("s1").workplane.origin == (5.0, 5.0, 5.0)
        assert revived.undo()
        assert revived.sketches.get("s1").workplane.origin == (0.0, 0.0, 0.0)

    def test_remove_sketch_leaves_entities(self):
        """Contract §2: sketch removal deletes the sketch's own content;
        referenced bcdoc entities are untouched document content."""
        doc = make_sketch_doc()
        n_entities = len(doc.entities())
        with doc.transaction("drop sketch"):
            doc.sketches.remove("sk1")
        assert len(doc.sketches) == 0
        assert len(doc.entities()) == n_entities
        doc.undo()
        assert len(doc.sketches.get("sk1").constraints) == 5
        assert len(doc.sketches.get("sk1").junctions) == 3


class TestConstraintOps:
    def test_parametric_edit_is_one_op_undo_granular(self):
        doc = make_sketch_doc()
        with doc.transaction("d1 50 -> 40") as tx:
            doc.sketches.set_constraint("sk1", "d1", value=40.0)
            raw_ops = list(tx.journal)
        assert doc.sketches.get("sk1").constraint("d1").value == 40.0
        (op,) = raw_ops
        assert op == {"op": "mutate_constraint", "sketch_id": "sk1",
                      "c_id": "d1", "changes": {"value": 50.0}}
        doc.undo()
        assert doc.sketches.get("sk1").constraint("d1").value == 50.0
        doc.redo()
        assert doc.sketches.get("sk1").constraint("d1").value == 40.0

    def test_add_remove_constraint_undoable(self):
        doc = make_sketch_doc()
        with doc.transaction("add k3"):
            doc.sketches.add_constraint("sk1", "vertical",
                                        [{"entity": doc.entities()[0].id}],
                                        c_id="k3")
        assert doc.sketches.get("sk1").constraint("k3") is not None
        with doc.transaction("remove k3"):
            doc.sketches.remove_constraint("sk1", "k3")
        assert doc.sketches.get("sk1").constraint("k3") is None
        doc.undo()  # undo the removal
        restored = doc.sketches.get("sk1").constraint("k3")
        assert restored is not None and restored.kind == "vertical"
        doc.undo()  # undo the addition
        assert doc.sketches.get("sk1").constraint("k3") is None

    def test_set_constraint_kind_change_validated(self):
        doc = make_sketch_doc()
        line = doc.entities()[0]
        with doc.transaction("retype"):
            doc.sketches.set_constraint("sk1", "k2", kind="vertical")
        assert doc.sketches.get("sk1").constraint("k2").kind == "vertical"
        with pytest.raises(ValueError):
            with doc.transaction("bad retype"):
                doc.sketches.set_constraint("sk1", "k2", kind="nonsense")

    def test_duplicate_constraint_and_junction_ids(self):
        doc = make_sketch_doc()
        line = doc.entities()[0]  # a real entity, so only uniqueness fires
        with doc.transaction("dup"):
            with pytest.raises(errors.DuplicateConstraint):
                doc.sketches.add_constraint("sk1", "horizontal",
                                            [{"entity": line.id}], c_id="k2")
            with pytest.raises(errors.DuplicateJunction):
                doc.sketches.add_junction(
                    "sk1", [{"entity": line.id, "slot": 0}], junction_id="jA")
        with doc.transaction("missing"):
            with pytest.raises(errors.ConstraintNotFound):
                doc.sketches.set_constraint("sk1", "nope", value=1.0)
            with pytest.raises(errors.ConstraintNotFound):
                doc.sketches.remove_constraint("sk1", "nope")

    def test_unknown_sketch_for_constraint_ops(self):
        doc = Document()
        with doc.transaction("t"):
            with pytest.raises(errors.SketchNotFound):
                doc.sketches.add_constraint("ghost", "horizontal", [])


class TestJunctionOps:
    def test_member_growth_keeps_identity_through_undo(self):
        doc = make_sketch_doc()
        l4 = None
        with doc.transaction("extra line"):
            l4 = doc.add_entity(Line((10, 10, 0), (11, 11, 0)))
            doc.sketches.set_junction("sk1", "jA",
                                      members=[{"entity": doc.entities()[2].id,
                                                "slot": 1},
                                               {"entity": doc.entities()[0].id,
                                                "slot": 0},
                                               {"entity": l4.id, "slot": 0}])
        j = doc.sketches.get("sk1").junction("jA")
        assert j.junction_id == "jA" and len(j.members) == 3
        doc.undo()
        j = doc.sketches.get("sk1").junction("jA")
        assert j.junction_id == "jA" and len(j.members) == 2

    def test_add_remove_junction_undoable_and_journaled(self):
        doc = make_sketch_doc()
        with doc.transaction("add jX") as tx:
            doc.sketches.add_junction(
                "sk1", [{"entity": doc.entities()[0].id, "slot": 1}],
                junction_id="jX")
            raw_ops = list(tx.journal)
        assert raw_ops[0]["op"] == "add_junction"
        with doc.transaction("remove jX"):
            doc.sketches.remove_junction("sk1", "jX")
        assert doc.sketches.get("sk1").junction("jX") is None
        doc.undo()
        assert doc.sketches.get("sk1").junction("jX") is not None


# ---------------------------------------------------------------------------
# guards (contract §5)
# ---------------------------------------------------------------------------

class TestRefGuards:
    def test_dangling_entity_ref_refused(self):
        doc = Document()
        with doc.transaction("t"):
            doc.sketches.add("s1")
            with pytest.raises(errors.DanglingSketchRef):
                doc.sketches.add_constraint(
                    "s1", "horizontal", [{"entity": "ghost"}])
            with pytest.raises(errors.DanglingSketchRef):
                doc.sketches.add_junction(
                    "s1", [{"entity": "ghost", "slot": 0}])

    def test_slot_refs_must_address_lines(self):
        doc = Document()
        with doc.transaction("t"):
            circle = doc.add_entity(Circle((0, 0, 0), 1.0))
            doc.sketches.add("s1")
            # geometric kinds take no value, so the SLOT rule is what fires
            with pytest.raises(ValueError, match="line endpoints"):
                doc.sketches.add_constraint(
                    "s1", "coincident",
                    [{"entity": circle.id, "slot": 0},
                     {"entity": circle.id, "slot": 1}])
            with pytest.raises(ValueError, match="line endpoints"):
                doc.sketches.add_junction(
                    "s1", [{"entity": circle.id, "slot": 0}])
            # whole-entity refs on non-lines are fine (radius on a circle)
            record = doc.sketches.add_constraint(
                "s1", "radius", [{"entity": circle.id}], value=1.5)
            assert record.value == 1.5

    def test_junction_refs_are_sketch_local(self):
        doc = make_sketch_doc()
        with doc.transaction("t"):
            doc.sketches.add("s2")
            with pytest.raises(errors.JunctionNotFound):
                doc.sketches.add_constraint(
                    "s2", "coincident_origin", [{"junction": "jA"}])
            # same junction id in ANOTHER sketch is a different point
            doc.sketches.add_junction(
                "s2", [{"entity": doc.entities()[0].id, "slot": 1}],
                junction_id="jA")
            doc.sketches.add_constraint("s2", "coincident_origin",
                                        [{"junction": "jA"}], c_id="ok")

    def test_set_constraint_revalidates_refs(self):
        doc = make_sketch_doc()
        with pytest.raises(errors.DanglingSketchRef):
            with doc.transaction("bad retarget"):
                doc.sketches.set_constraint("sk1", "k2",
                                            refs=[{"entity": "ghost"}])
        assert doc.sketches.get("sk1").constraint("k2").refs == \
            ({'entity': doc.entities()[0].id},)  # untouched


class TestEntityInUse:
    def test_remove_refused_while_constraint_holds_a_ref(self):
        doc = make_sketch_doc()
        line = doc.entities()[0]  # referenced by k2 (whole-entity ref)
        with pytest.raises(errors.EntityInUse):
            with doc.transaction("refused"):
                doc.remove(line.id)

    def test_remove_refused_for_junction_membership(self):
        doc = make_sketch_doc()
        # l2 is a junction member (jB/jC) but holds NO whole-entity
        # constraint ref; the membership alone must protect it
        line2 = doc.entities()[1]
        with pytest.raises(errors.EntityInUse):
            with doc.transaction("refused"):
                doc.remove(line2.id)

    def test_composed_removal_then_entity_remove(self):
        doc = make_sketch_doc()
        line = doc.entities()[0]
        with doc.transaction("clean sketch first"):
            for c in [c.c_id for c in doc.sketches.get("sk1").constraints]:
                if any(r.get("entity") == line.id
                       for r in doc.sketches.get("sk1").constraint(c).refs):
                    doc.sketches.remove_constraint("sk1", c)
            for j in [j.junction_id for j in doc.sketches.get("sk1").junctions]:
                doc.sketches.set_junction(
                    "sk1", j,
                    members=[m for m in doc.sketches.get("sk1").junction(j).members
                             if m["entity"] != line.id])
                if len(doc.sketches.get("sk1").junction(j).members) == 0:
                    doc.sketches.remove_junction("sk1", j)
            doc.remove(line.id)
        assert line.id not in {e.id for e in doc.entities()}
        # and the whole composition undoes atomically
        doc.undo()
        assert line.id in {e.id for e in doc.entities()}
        assert len(doc.sketches.get("sk1").constraints) == 5


# ---------------------------------------------------------------------------
# serialization (contract §3)
# ---------------------------------------------------------------------------

class TestSerializationV3:
    def test_pinned_key_order_and_sketch_record_order(self):
        payload = json.loads(make_sketch_doc().serialize())
        assert payload["schema"] == "bcdoc/3"
        keys = list(payload)
        assert keys == [
            "schema", "name", "units", "doc_version", "next_handle",
            "settings", "layers", "current_layer", "text_styles",
            "dim_styles", "blocks", "layouts", "sketches", "entities",
            "undo", "redo", "selection",
        ]
        (sketch,) = payload["sketches"]
        assert list(sketch) == ["sketch_id", "name", "workplane",
                               "junctions", "constraints"]
        assert list(sketch["workplane"]) == ["origin", "x_axis", "y_axis"]
        assert list(sketch["constraints"][0]) == \
            ["c_id", "kind", "refs", "value", "driven"]
        assert list(sketch["junctions"][0]) == ["junction_id", "members"]

    def test_byte_stable_with_sketches(self):
        doc = make_sketch_doc()
        text1 = doc.serialize()
        mirror = Document.load(text1)
        assert mirror.serialize() == text1
        assert Document.load(mirror.serialize()).serialize() == text1
        # content survived: same junctions, same constraint values+flags
        orig, revived = doc.sketches.get("sk1"), mirror.sketches.get("sk1")
        assert revived.name == orig.name == "Triangle"
        assert revived.junction("jB").members == orig.junction("jB").members
        assert revived.constraint("d1").value == 50.0
        assert revived.constraint("d1").driven is False
        assert revived.workplane == orig.workplane

    def test_driven_reference_dimension_survives_save_reopen(self):
        doc = make_sketch_doc()
        with doc.transaction("gate d2 as reference"):
            doc.sketches.set_constraint("sk1", "d2", driven=True)
        revived = Document.load(doc.serialize())
        d2 = revived.sketches.get("sk1").constraint("d2")
        assert d2.value == 45.0 and d2.driven is True

    def test_undo_redo_after_reopen_including_sketch_ops(self):
        """The demonstrated parametric loop across a save/reopen boundary:
        edit -> save -> reopen -> undo restores the prior dimension."""
        doc = make_sketch_doc()
        with doc.transaction("d1 50 -> 40"):
            doc.sketches.set_constraint("sk1", "d1", value=40.0)
        revived = Document.load(doc.serialize())
        assert revived.sketches.get("sk1").constraint("d1").value == 40.0
        assert revived.undo()
        assert revived.sketches.get("sk1").constraint("d1").value == 50.0
        assert revived.redo()
        assert revived.sketches.get("sk1").constraint("d1").value == 40.0
        # journals with sketch ops survive ANOTHER save cycle byte-exactly
        again = Document.load(revived.serialize())
        assert again.serialize() == revived.serialize()

    def test_v2_payload_upgrades_with_empty_sketches(self):
        payload = json.loads(make_sketch_doc().serialize())
        payload["schema"] = "bcdoc/2"
        del payload["sketches"]
        doc = Document.load(json.dumps(payload))
        assert len(doc.sketches) == 0
        revived = json.loads(doc.serialize())
        assert revived["schema"] == "bcdoc/3" and revived["sketches"] == []

    def test_v1_payload_still_upgrades(self):
        v1 = {
            "schema": "bcdoc/1", "name": "legacy", "units": {"base": "mm"},
            "doc_version": 3, "next_handle": 99,
            "layers": ["0", "WALLS"],
            "entities": [
                {"kind": "line", "id": "e1", "handle": 1, "layer": "0",
                 "color": None, "linetype": "ByLayer", "p1": [0, 0],
                 "p2": [1, 1]},
            ],
            "undo": [], "redo": [],
            "selection": {"ids": [], "epoch": 0},
        }
        doc = Document.load(json.dumps(v1))
        assert doc.sketches.ids() == []
        assert json.loads(doc.serialize())["schema"] == "bcdoc/3"

    def test_future_schema_rejected(self):
        text = make_sketch_doc().serialize()
        with pytest.raises(errors.SerializationError, match="unsupported schema"):
            Document.load(text.replace('"bcdoc/3"', '"bcdoc/4"', 1))

    def test_parse_refuses_dangling_ref_payload(self):
        payload = json.loads(make_sketch_doc().serialize())
        payload["sketches"][0]["constraints"][1]["refs"] = [
            {"entity": "ghost"}]
        with pytest.raises(errors.SerializationError, match="not in the"):
            Document.load(json.dumps(payload))

    def test_parse_refuses_slot_ref_on_non_line(self):
        doc = make_sketch_doc()
        with doc.transaction("circle"):
            circle = doc.add_entity(Circle((0, 0, 0), 1.0))
        payload = json.loads(doc.serialize())
        payload["sketches"][0]["constraints"][0]["refs"] = [
            {"entity": circle.id, "slot": 0}]
        with pytest.raises(errors.SerializationError, match="slots"):
            Document.load(json.dumps(payload))

    def test_parse_refuses_foreign_junction_ref(self):
        payload = json.loads(make_sketch_doc().serialize())
        payload["sketches"].append(dict(payload["sketches"][0],
                                        sketch_id="s2"))
        payload["sketches"][1]["junctions"] = []  # jA..jC not in s2
        with pytest.raises(errors.SerializationError,
                           match="not in the same sketch"):
            Document.load(json.dumps(payload))

    def test_parse_refuses_duplicate_sketch_and_bad_kinds(self):
        payload = json.loads(make_sketch_doc().serialize())
        payload["sketches"].append(dict(payload["sketches"][0]))
        with pytest.raises(errors.SerializationError, match="duplicate ids"):
            Document.load(json.dumps(payload))
        payload = json.loads(make_sketch_doc().serialize())
        payload["sketches"][0]["constraints"][0]["kind"] = "welded"
        with pytest.raises(errors.SerializationError, match="invalid sketch"):
            Document.load(json.dumps(payload))

    def test_journal_shapes_validated_at_load(self):
        payload = json.loads(make_sketch_doc().serialize())
        with pytest.raises(errors.SerializationError, match="sketch_id"):
            payload["undo"].append({
                "label": "forged", "doc_version": 99,
                "entries": [{"op": "mutate_constraint", "c_id": "d1",
                             "changes": {"value": 1.0}}],
            })
            Document.load(json.dumps(payload))


# ---------------------------------------------------------------------------
# solve reports (contract §1.5 — session state)
# ---------------------------------------------------------------------------

class TestSolveReports:
    def test_record_shape_and_round_trip(self):
        report = SolveReport("sk1", solver="solidcraft-solver@3b4db52",
                             status="solved", dof=0, redundant=("k8",),
                             detail="")
        assert report.to_dict() == {
            "sketch_id": "sk1", "solver": "solidcraft-solver@3b4db52",
            "status": "solved", "dof": 0, "failed": [], "redundant": ["k8"],
            "conflicting": [], "detail": "",
        }
        assert SolveReport.from_dict(report.to_dict()) == report

    def test_empty_diagnostics_are_honest(self):
        """PlaneGCS's structurally-clean failure shape: empty lists are a
        VALID report — nothing synthesizes diagnostics (contract §1.5)."""
        report = SolveReport("sk1", solver="planegcs@4fd3bf3",
                             status="failed", dof=4)
        assert report.failed == () and report.redundant == ()
        assert report.conflicting == () and report.detail == ""

    def test_malformed_reports_rejected(self):
        with pytest.raises(ValueError, match="status"):
            SolveReport("sk1", solver="x", status="meh", dof=0)
        with pytest.raises(ValueError, match="dof"):
            SolveReport("sk1", solver="x", status="failed", dof=-1)
        with pytest.raises(ValueError, match="constraint ids"):
            SolveReport("sk1", solver="x", status="failed", dof=1,
                       failed=[3])

    def test_session_state_never_serialized_never_journaled(self):
        doc = make_sketch_doc()
        version = doc.doc_version
        depth = doc.undo_depth()
        report = SolveReport("sk1", solver="svc", status="solved", dof=0)
        doc.solve_reports.set(report)
        assert doc.solve_reports.get("sk1") == report
        assert doc.solve_reports.get("missing") is None
        assert doc.doc_version == version      # never bumps
        assert doc.undo_depth() == depth       # never journals
        assert "solve_reports" not in json.loads(doc.serialize())
        # cleared on load (session state, like selection)
        assert len(Document.load(doc.serialize()).solve_reports) == 0

    def test_failed_transaction_does_not_revert_reports(self):
        """Session state is NOT part of the snapshot (selection semantics):
        a failed transaction leaves reports set — they describe solver
        outcomes, not document content."""
        doc = make_sketch_doc()
        doc.solve_reports.set(SolveReport("sk1", solver="svc",
                                          status="failed", dof=4))
        with pytest.raises(RuntimeError):
            with doc.transaction("boom"):
                doc.sketches.set_props("sk1", name="x")
                raise RuntimeError("boom")
        assert doc.solve_reports.get("sk1").status == "failed"


# ---------------------------------------------------------------------------
# rollback atomicity over sketches (contract §2)
# ---------------------------------------------------------------------------

class TestRollbackAtomicity:
    def test_failed_mid_transaction_is_bit_identical(self):
        doc = make_sketch_doc()
        before = doc.serialize()
        with pytest.raises(RuntimeError):
            with doc.transaction("partial sketch edits"):
                doc.sketches.set_constraint("sk1", "d1", value=40.0)
                doc.sketches.add("s2")
                doc.sketches.remove_constraint("sk1", "d2")
                raise RuntimeError("boom")
        assert doc.serialize() == before
        assert doc.sketches.get("sk1").constraint("d1").value == 50.0
        assert "s2" not in doc.sketches

    def test_geometry_mutation_is_not_policed_by_sketches(self):
        """The seam design (m3-eval §4.3): the solver applies results back
        via plain update_entity; sketches never constrain geometry edits."""
        doc = make_sketch_doc()
        line = doc.entities()[0]
        with doc.transaction("apply-back"):
            doc.update_entity(line.id, p1=(1.0, 2.0, 0.0))
        assert doc.get(line.id).p1 == (1.0, 2.0, 0.0)
        doc.undo()
        assert doc.get(line.id).p1 == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# corpus representability: the W1 rect fixture as document content
# (the fixture that rejected slvs and named the redundancy via SolidCraft —
# h2h decision record §2; committed at experiments/cad-sketcher/…/cases.json)
# ---------------------------------------------------------------------------

class TestCorpusRepresentability:
    def test_w1_rect_fixture_is_storable_document_content(self):
        doc = Document()
        with doc.transaction("rect from the corpus"):
            p0, p1, p2, p3 = (0, 0), (40, 0), (40, 30), (0, 30)
            lines = [
                doc.add_entity(Line(tuple(p0) + (0,), tuple(p1) + (0,))),
                doc.add_entity(Line(tuple(p1) + (0,), tuple(p2) + (0,))),
                doc.add_entity(Line(tuple(p2) + (0,), tuple(p3) + (0,))),
                doc.add_entity(Line(tuple(p3) + (0,), tuple(p0) + (0,))),
            ]
            doc.sketches.add("w1-rect")
            # corpus corner junctions: j0..j3 (the shared vertices)
            doc.sketches.add_junction("w1-rect",
                [{"entity": lines[0].id, "slot": 0},
                 {"entity": lines[3].id, "slot": 1}], junction_id="j0")
            doc.sketches.add_junction("w1-rect",
                [{"entity": lines[0].id, "slot": 1},
                 {"entity": lines[1].id, "slot": 0}], junction_id="j1")
            doc.sketches.add_junction("w1-rect",
                [{"entity": lines[1].id, "slot": 1},
                 {"entity": lines[2].id, "slot": 0}], junction_id="j2")
            doc.sketches.add_junction("w1-rect",
                [{"entity": lines[2].id, "slot": 1},
                 {"entity": lines[3].id, "slot": 0}], junction_id="j3")
            # corpus constraint set, verbatim labels
            doc.sketches.add_constraint("w1-rect", "horizontal",
                                        [{"entity": lines[0].id}], c_id="k1")
            doc.sketches.add_constraint("w1-rect", "horizontal",
                                        [{"entity": lines[2].id}], c_id="k2")
            doc.sketches.add_constraint("w1-rect", "vertical",
                                        [{"entity": lines[1].id}], c_id="k3")
            doc.sketches.add_constraint("w1-rect", "vertical",
                                        [{"entity": lines[3].id}], c_id="k4")
            doc.sketches.add_constraint("w1-rect", "coincident_origin",
                                        [{"junction": "j0"}], c_id="k5")
            doc.sketches.add_constraint("w1-rect", "length",
                                        [{"entity": lines[0].id}],
                                        value=40.0, c_id="d1")
            doc.sketches.add_constraint("w1-rect", "length",
                                        [{"entity": lines[1].id}],
                                        value=30.0, c_id="d2")
            # the exactly-redundant duplicate Vertical that named k6/k8
            doc.sketches.add_constraint("w1-rect", "vertical",
                                        [{"entity": lines[1].id}], c_id="k6")

        revived = Document.load(doc.serialize())
        sketch = revived.sketches.get("w1-rect")
        labels = [c.c_id for c in sketch.constraints]
        assert labels == ["k1", "k2", "k3", "k4", "k5", "d1", "d2", "k6"]
        # a solver-service report for this sketch is storable session-side
        revived.solve_reports.set(SolveReport(
            "w1-rect", solver="solidcraft-solver@3b4db52",
            status="solved", dof=0, redundant=("k6",),
            detail="SOLVED dof0 redundant=[k6] — the W1/SolidCraft record"))
        assert revived.solve_reports.get("w1-rect").redundant == ("k6",)
