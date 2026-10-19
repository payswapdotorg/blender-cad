"""bcdoc conformance checks for the semantics W1 depends on (contract §3).

These run against whichever ``bcdoc`` is active — the REAL package
(``modules/document/bcdoc``, W2) when present, the fallback contract double
otherwise (see conftest). They pin exactly the observable behavior the
command layer (bccmd/bcdraft/bcshell) builds on; a failure here against the
real bcdoc flags a contract divergence for the TL.
"""

import pytest

from bcdoc.document import Document
from bcdoc.entities import Arc, Circle, Line
from bcdoc.errors import (
    EntityNotFound,
    NoOpenTransaction,
    SerializationError,
)


def test_fresh_document_state():
    doc = Document()
    assert doc.doc_version == 0
    assert "0" in doc.layers
    assert doc.entities() == []
    assert doc.count_by_kind() == {}
    assert doc.undo_depth() == 0 and doc.redo_depth() == 0
    assert doc.selection.epoch == 0


def test_mutations_require_open_transaction():
    doc = Document()
    with pytest.raises(NoOpenTransaction):
        doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    with pytest.raises(NoOpenTransaction):
        doc.update_entity("whatever", layer="x")


def test_add_entity_assigns_monotonic_handles():
    doc = Document()
    with doc.transaction("create"):
        e1 = doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
        e2 = doc.add_entity(Circle((5, 5, 0), 2))
        e3 = doc.add_entity(Arc((0, 0, 0), 3, 0, 90))
    assert e2.handle == e1.handle + 1
    assert e3.handle == e2.handle + 1
    assert doc.count_by_kind() == {"line": 1, "circle": 1, "arc": 1}


def test_missing_entity_raises_entity_not_found():
    doc = Document()
    with pytest.raises(EntityNotFound):
        doc.get("missing")


def test_transaction_commit_bumps_version_and_fires_events():
    doc = Document()
    events = []
    doc.on_change.append(lambda event: events.append(event))
    with doc.transaction("create"):
        doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    assert doc.doc_version == 1
    assert events == [("doc", 1)]


def test_transaction_exception_rolls_back_bit_identical():
    doc = Document()
    with doc.transaction("keep"):
        doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    before = doc.serialize()
    with pytest.raises(ValueError):
        with doc.transaction("bad"):
            doc.add_entity(Line((1, 0, 0), (1, 1, 0)))
            raise ValueError("nope")
    assert doc.doc_version == 1
    assert doc.serialize() == before
    assert doc.undo_depth() == 1


def test_undo_redo_roundtrip_and_monotonic_version():
    doc = Document()
    with doc.transaction("a"):
        a = doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    with doc.transaction("b"):
        doc.add_entity(Line((1, 0, 0), (1, 1, 0)))
    version_after_commits = doc.doc_version
    assert doc.undo() is True
    assert doc.doc_version == version_after_commits + 1  # monotonic
    assert [e.id for e in doc.entities()] == [a.id]
    assert doc.undo_depth() == 1 and doc.redo_depth() == 1
    assert doc.redo() is True
    assert doc.doc_version == version_after_commits + 2
    assert doc.count_by_kind() == {"line": 2}


def test_undo_returns_false_when_empty():
    doc = Document()
    assert doc.undo() is False
    assert doc.redo() is False


def test_update_entity_is_journaled_undo_restores_geometry():
    """The path MOVE/ROTATE/SCALE rely on: transforms via update_entity are
    undone by document.undo()."""
    doc = Document()
    with doc.transaction("create"):
        line = doc.add_entity(Line((0, 0, 0), (10, 0, 0)))
        circle = doc.add_entity(Circle((0, 5, 0), 2))
        arc = doc.add_entity(Arc((0, 0, 0), 3, 10, 260))
    with doc.transaction("MOVE"):
        doc.update_entity(line.id, p1=(5, 5, 0), p2=(15, 5, 0))
        doc.update_entity(circle.id, center=(5, 10, 0))
        doc.update_entity(arc.id, center=(5, 20, 0), start_angle=30.0,
                           end_angle=280.0)
    assert line.p1 == (5.0, 5.0, 0.0)
    assert circle.center == (5.0, 10.0, 0.0)
    assert doc.undo() is True
    assert line.p1 == (0.0, 0.0, 0.0) and line.p2 == (10.0, 0.0, 0.0)
    assert circle.center == (0.0, 5.0, 0.0)
    assert arc.center == (0.0, 0.0, 0.0)
    assert arc.start_angle == pytest.approx(10.0)
    assert arc.end_angle == pytest.approx(260.0)


def test_remove_is_journaled_and_undoable():
    doc = Document()
    with doc.transaction("create"):
        entity = doc.add_entity(Circle((0, 0, 0), 1))
    with doc.transaction("erase"):
        doc.remove(entity.id)
    with pytest.raises(EntityNotFound):
        doc.get(entity.id)
    doc.undo()
    assert doc.get(entity.id) is entity


def test_selection_epoch_bumps_without_doc_version():
    doc = Document()
    with doc.transaction("c"):
        entity = doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    version = doc.doc_version
    events = []
    doc.on_select.append(lambda event: events.append(event))
    doc.selection.set([entity.id])
    epoch_1 = doc.selection.epoch
    assert epoch_1 == 1
    doc.selection.add(["other"])
    doc.selection.remove(["other"])
    doc.selection.clear()
    assert doc.selection.epoch == 4
    assert events[-1] == ("select", 4)
    assert doc.doc_version == version


def test_selection_noop_does_not_bump():
    doc = Document()
    doc.selection.set([])
    assert doc.selection.epoch == 0  # no change → no bump
    doc.selection.set(["a"])
    doc.selection.set(["a"])
    assert doc.selection.epoch == 1


def test_serialize_load_roundtrip():
    doc = Document(name="RT")
    with doc.transaction("t1"):
        doc.add_entity(Line((0, 0, 0), (10, 0, 0), layer="0", color=1))
        doc.add_entity(Circle((5, 5, 0), 2.5))
        doc.add_entity(Arc((0, 0, 0), 3, 10, 260))
    doc.undo()
    text = doc.serialize()
    loaded = Document.load(text)
    assert loaded.serialize() == text  # byte-stable round trip
    assert loaded.doc_version == doc.doc_version
    assert loaded.name == "RT"
    assert [e.kind for e in loaded.entities()] == [e.kind for e in doc.entities()]
    assert loaded.undo_depth() == doc.undo_depth()
    assert loaded.selection.epoch == doc.selection.epoch


def test_load_rejects_wrong_schema():
    with pytest.raises(SerializationError):
        Document.load('{"schema": "bcdoc/2", "name": "x"}')
    with pytest.raises(SerializationError):
        Document.load("not json at all")


def test_entities_preserve_insertion_order_after_undo_redo():
    doc = Document()
    ids = []
    with doc.transaction("a"):
        ids.append(doc.add_entity(Line((0, 0, 0), (1, 0, 0))).id)
    with doc.transaction("b"):
        ids.append(doc.add_entity(Line((1, 0, 0), (2, 0, 0))).id)
    doc.undo()
    doc.redo()
    assert [e.id for e in doc.entities()] == ids
