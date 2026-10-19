"""FALLBACK contract double for ``bcdoc`` (W2's document model).

**contract double — replaced by the real bcdoc at TL integration.**

History: W2's ``modules/document/bcdoc`` had not landed when worker 3-a (W1)
started; this double let W1's work proceed against contract §3 names. The
REAL bcdoc has since landed, so this module is normally dormant — the test
conftests and the Blender driver import the real package when present and
only fall back to this double when it is absent.

It is aligned with the real implementation's observable semantics where W1
depends on them:

* events fire with a single tuple argument: ``("doc", doc_version)`` /
  ``("select", epoch)``;
* ``get``/``remove`` raise :class:`EntityNotFound` (no None returns);
* ``update_entity(eid, **changes)`` is the journaled mutation path for
  transforms (undo restores geometry);
* selection no-ops (no epoch bump) when the set is unchanged;
* serialize/load round-trip is byte-stable within this implementation
  (its JSON layout is the double's own; documents do not cross
  implementations).

Undo is snapshot-based (correct, heavy) rather than the real journal-reversal.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Dict, List, Optional

SCHEMA = "bcdoc/1"


# ---------------------------------------------------------------------------
# errors (bcdoc.errors)
# ---------------------------------------------------------------------------


class BcdocError(Exception):
    pass


class NoOpenTransaction(BcdocError):
    pass


class TransactionAlreadyOpen(BcdocError):
    pass


class EntityNotFound(BcdocError):
    def __init__(self, eid):
        super().__init__(f"no entity with id {eid!r}")
        self.eid = eid


class DuplicateEntity(BcdocError):
    def __init__(self, eid):
        super().__init__(f"entity id {eid!r} already exists in the document")
        self.eid = eid


class DuplicateHandle(BcdocError):
    def __init__(self, handle):
        super().__init__(f"entity handle {handle} is already in use")
        self.handle = handle


class InvalidEntityField(BcdocError):
    def __init__(self, kind, field):
        super().__init__(f"entity kind {kind!r} has no mutable field {field!r}")


class SerializationError(BcdocError):
    pass


# ---------------------------------------------------------------------------
# entities (bcdoc.entities)
# ---------------------------------------------------------------------------

GEOMETRY_FIELDS = {
    "line": ("p1", "p2"),
    "circle": ("center", "radius"),
    "arc": ("center", "radius", "start_angle", "end_angle"),
}


def normalize_point(value):
    seq = tuple(value)
    if len(seq) not in (2, 3):
        raise ValueError(f"not a valid 2D/3D point: {value!r}")
    return (
        float(seq[0]),
        float(seq[1]),
        float(seq[2]) if len(seq) == 3 else 0.0,
    )


def set_field(entity, field, value):
    if field == "layer":
        entity.layer = str(value)
    elif field == "linetype":
        entity.linetype = str(value)
    elif field == "color":
        entity.color = None if value is None else int(value)
    elif field in GEOMETRY_FIELDS[entity.kind]:
        if field in ("p1", "p2", "center"):
            setattr(entity, field, normalize_point(value))
        else:
            setattr(entity, field, float(value))
    else:
        raise InvalidEntityField(entity.kind, field)


class Entity:
    _KIND = "entity"

    def __init__(self, layer="0", color=None, linetype="ByLayer"):
        self.id: str = uuid.uuid4().hex
        self.handle: int = 0
        self.layer = layer
        self.color = color
        self.linetype = linetype

    @property
    def kind(self) -> str:
        return self._KIND

    @property
    def mutable_fields(self):
        return ("layer", "color", "linetype") + GEOMETRY_FIELDS[self.kind]

    def copy(self):
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        return clone

    def _attrs(self) -> Dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "handle": self.handle,
            "layer": self.layer,
            "color": self.color,
            "linetype": self.linetype,
        }

    def _geometry(self) -> Dict:
        out = {}
        for field in GEOMETRY_FIELDS[self.kind]:
            value = getattr(self, field)
            out[field] = list(value) if isinstance(value, tuple) else value
        return out

    def to_dict(self) -> Dict:
        return dict(self._attrs(), **self._geometry())


class Line(Entity):
    _KIND = "line"

    def __init__(self, p1, p2, **kwargs):
        super().__init__(**kwargs)
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)


class Circle(Entity):
    _KIND = "circle"

    def __init__(self, center, radius, **kwargs):
        super().__init__(**kwargs)
        self.center = normalize_point(center)
        self.radius = float(radius)


class Arc(Entity):
    _KIND = "arc"

    def __init__(self, center, radius, start_angle, end_angle, **kwargs):
        super().__init__(**kwargs)
        self.center = normalize_point(center)
        self.radius = float(radius)
        self.start_angle = float(start_angle)
        self.end_angle = float(end_angle)


def entity_from_dict(data: Dict) -> Entity:
    attrs = {
        "layer": data.get("layer", "0"),
        "color": data.get("color"),
        "linetype": data.get("linetype", "ByLayer"),
    }
    kind = data.get("kind")
    if kind == "line":
        entity = Line(data["p1"], data["p2"], **attrs)
    elif kind == "circle":
        entity = Circle(data["center"], data["radius"], **attrs)
    elif kind == "arc":
        entity = Arc(
            data["center"], data["radius"],
            data["start_angle"], data["end_angle"], **attrs
        )
    else:
        raise SerializationError(f"unknown entity kind {kind!r}")
    entity.id = data["id"]
    entity.handle = int(data["handle"])
    return entity


# ---------------------------------------------------------------------------
# selection (bcdoc.selection)
# ---------------------------------------------------------------------------


def _as_id_set(ids) -> frozenset:
    if isinstance(ids, str):
        return frozenset((ids,))
    return frozenset(str(i) for i in ids)


class SelectionState:
    def __init__(self, on_change=None):
        self._ids: frozenset = frozenset()
        self._epoch: int = 0
        self._on_change = on_change

    @property
    def ids(self) -> frozenset:
        return self._ids

    @property
    def epoch(self) -> int:
        return self._epoch

    def _bump(self) -> None:
        self._epoch += 1
        if self._on_change is not None:
            self._on_change(("select", self._epoch))

    def set(self, ids) -> None:
        new = _as_id_set(ids)
        if new != self._ids:
            self._ids = new
            self._bump()

    def add(self, ids) -> None:
        new = self._ids | _as_id_set(ids)
        if new != self._ids:
            self._ids = new
            self._bump()

    def remove(self, ids) -> None:
        new = self._ids - _as_id_set(ids)
        if new != self._ids:
            self._ids = new
            self._bump()

    def clear(self) -> None:
        self.set([])

    def snapshot(self):
        return (self._ids, self._epoch)

    def _restore(self, ids, epoch) -> None:
        self._ids = frozenset(str(i) for i in ids)
        self._epoch = int(epoch)


# ---------------------------------------------------------------------------
# transaction + undo (bcdoc.transaction / bcdoc.undo)
# ---------------------------------------------------------------------------


class Transaction:
    def __init__(self, document: "Document", label: str):
        self._doc = document
        self.label = str(label)
        self.committed: bool = False
        self._snapshot = document._snapshot_state()

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self._doc._commit(self.label, self._snapshot)
            self.committed = True
            return False
        self._doc._restore_state(self._snapshot)
        return False


class UndoGroup:
    def __init__(self, label: str, doc_version: int, entries=None):
        self.label = label
        self.doc_version = doc_version
        self.entries = list(entries or [])

    def to_dict(self) -> Dict:
        return {"label": self.label, "doc_version": self.doc_version, "entries": self.entries}

    @classmethod
    def from_dict(cls, data: Dict) -> "UndoGroup":
        return cls(data["label"], data["doc_version"], data["entries"])


# ---------------------------------------------------------------------------
# document (bcdoc.document)
# ---------------------------------------------------------------------------


class Document:
    def __init__(self, name: str = "Untitled", units=None):
        self.name = name
        self.units: Dict[str, str] = dict(units or {"length": "mm", "angle": "deg"})
        self.doc_version: int = 0
        self.layers: List[str] = ["0"]
        self.next_handle: int = 1
        self.on_change: List = []      # callbacks receive ("doc", doc_version)
        self.on_select: List = []      # callbacks receive ("select", epoch)
        self.selection = SelectionState(on_change=self._fire_select)
        self._entities: Dict[str, Entity] = {}   # insertion order preserved
        self._undo_stack: List[Dict] = []
        self._redo_stack: List[Dict] = []
        self._open_tx: Optional[Transaction] = None

    # -- events --------------------------------------------------------------
    def _fire_change(self, event) -> None:
        for callback in list(self.on_change):
            callback(event)

    def _fire_select(self, event) -> None:
        for callback in list(self.on_select):
            callback(event)

    # -- entity store --------------------------------------------------------
    def _require_tx(self) -> Transaction:
        if self._open_tx is None:
            raise NoOpenTransaction(
                "mutating document APIs require an open transaction"
            )
        return self._open_tx

    def add_entity(self, entity: Entity, handle=None) -> Entity:
        self._require_tx()
        if not isinstance(entity, Entity):
            raise TypeError(
                f"add_entity expects an Entity, got {type(entity).__name__}"
            )
        if entity.id in self._entities:
            raise DuplicateEntity(entity.id)
        handles = {e.handle for e in self._entities.values()}
        if handle is None:
            assigned = self.next_handle
            self.next_handle = assigned + 1
        else:
            assigned = int(handle)
            if assigned < 1:
                raise ValueError("handle must be >= 1")
            if assigned in handles:
                raise DuplicateHandle(assigned)
            if assigned >= self.next_handle:
                self.next_handle = assigned + 1
        entity.handle = assigned
        self._entities[entity.id] = entity
        return entity

    def get(self, entity_id: str) -> Entity:
        try:
            return self._entities[entity_id]
        except KeyError:
            raise EntityNotFound(entity_id) from None

    def has(self, entity_id: str) -> bool:
        return entity_id in self._entities

    def remove(self, entity_id: str) -> Entity:
        self._require_tx()
        entity = self.get(entity_id)
        del self._entities[entity_id]
        return entity

    def update_entity(self, entity_id: str, **changes) -> Entity:
        """Journaled in-place mutation (transforms use this so undo works)."""
        self._require_tx()
        entity = self.get(entity_id)
        for field in changes:
            if field not in entity.mutable_fields:
                raise InvalidEntityField(entity.kind, field)
        if "layer" in changes and changes["layer"] not in self.layers:
            self.layers.append(str(changes["layer"]))
        for field, value in changes.items():
            set_field(entity, field, value)
        return entity

    def entities(self) -> List[Entity]:
        return list(self._entities.values())

    def count_by_kind(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entity in self._entities.values():
            counts[entity.kind] = counts.get(entity.kind, 0) + 1
        return counts

    # -- transactions --------------------------------------------------------
    def transaction(self, label: str = "") -> Transaction:
        if self._open_tx is not None:
            raise TransactionAlreadyOpen(self._open_tx.label)
        tx = Transaction(self, label)
        self._open_tx = tx
        return tx

    def _snapshot_state(self) -> Dict:
        return {
            "entities": [(eid, e.copy()) for eid, e in self._entities.items()],
            "layers": list(self.layers),
            "next_handle": self.next_handle,
            "doc_version": self.doc_version,
            "selection": self.selection.snapshot(),
        }

    def _restore_state(self, snapshot: Dict) -> None:
        self._entities = dict(snapshot["entities"])
        self.layers = list(snapshot["layers"])
        self.next_handle = snapshot["next_handle"]
        self.doc_version = snapshot["doc_version"]
        self.selection._restore(*snapshot["selection"])
        self._open_tx = None

    def _commit(self, label: str, snapshot: Dict) -> None:
        self._open_tx = None
        self._undo_stack.append({"label": label, "pre": snapshot})
        self._redo_stack = []
        self.doc_version += 1
        self._fire_change(("doc", self.doc_version))

    # -- undo / redo (each is a NEW committed transaction) --------------------
    def _require_no_open_tx(self) -> None:
        if self._open_tx is not None:
            raise TransactionAlreadyOpen(self._open_tx.label)

    def undo(self) -> bool:
        self._require_no_open_tx()
        if not self._undo_stack:
            return False
        group = self._undo_stack.pop()
        current = self._snapshot_state()
        self._restore_state(group["pre"])
        self._redo_stack.append({"label": group["label"], "pre": current})
        self.doc_version += 1
        self._fire_change(("doc", self.doc_version))
        return True

    def redo(self) -> bool:
        self._require_no_open_tx()
        if not self._redo_stack:
            return False
        group = self._redo_stack.pop()
        current = self._snapshot_state()
        self._restore_state(group["pre"])
        self._undo_stack.append({"label": group["label"], "pre": current})
        self.doc_version += 1
        self._fire_change(("doc", self.doc_version))
        return True

    def undo_depth(self) -> int:
        return len(self._undo_stack)

    def redo_depth(self) -> int:
        return len(self._redo_stack)

    def undo_groups(self):
        return tuple(
            UndoGroup(g["label"], 0) for g in reversed(list(self._undo_stack))
        )

    def undo_labels(self) -> List[str]:
        return [g["label"] for g in self._undo_stack]

    # -- serialization ---------------------------------------------------------
    def _snap_entities(self, snapshot: Dict) -> List[Dict]:
        return [e.to_dict() for (_eid, e) in snapshot["entities"]]

    def serialize(self) -> str:
        payload = {
            "schema": SCHEMA,
            "name": self.name,
            "units": dict(self.units),
            "doc_version": self.doc_version,
            "next_handle": self.next_handle,
            "layers": list(self.layers),
            "entities": [e.to_dict() for e in self._entities.values()],
            "undo": [
                {"label": g["label"], "entities": self._snap_entities(g["pre"]),
                 "next_handle": g["pre"]["next_handle"],
                 "doc_version": g["pre"]["doc_version"]}
                for g in self._undo_stack
            ],
            "redo": [
                {"label": g["label"], "entities": self._snap_entities(g["pre"]),
                 "next_handle": g["pre"]["next_handle"],
                 "doc_version": g["pre"]["doc_version"]}
                for g in self._redo_stack
            ],
            "selection": {
                "ids": sorted(self.selection.ids),
                "epoch": self.selection.epoch,
            },
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @staticmethod
    def load(text: str) -> "Document":
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SerializationError(f"not valid JSON: {exc}") from None
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise SerializationError("expected schema bcdoc/1")
        doc = Document(name=payload.get("name", "Untitled"))
        doc.units = dict(payload.get("units", doc.units))
        doc.doc_version = int(payload.get("doc_version", 0))
        doc.layers = list(payload.get("layers", ["0"]))
        for data in payload.get("entities", []):
            entity = entity_from_dict(data)
            doc._entities[entity.id] = entity
        doc.next_handle = int(payload.get("next_handle", 1))

        def _snap(group: Dict) -> Dict:
            entities = [(e["id"], entity_from_dict(e))
                        for e in group["entities"]]
            return {
                "entities": entities,
                "layers": list(doc.layers),
                "next_handle": int(group["next_handle"]),
                "doc_version": int(group["doc_version"]),
                "selection": (frozenset(), 0),
            }

        doc._undo_stack = [
            {"label": g["label"], "pre": _snap(g)}
            for g in payload.get("undo", [])
        ]
        doc._redo_stack = [
            {"label": g["label"], "pre": _snap(g)}
            for g in payload.get("redo", [])
        ]
        selection = payload.get("selection", {})
        doc.selection._restore(
            selection.get("ids", []), selection.get("epoch", 0)
        )
        return doc


# ---------------------------------------------------------------------------
# package shim — install the double under the REAL bcdoc names
# ---------------------------------------------------------------------------


def install_as_bcdoc() -> None:
    """Register this double in ``sys.modules`` as the ``bcdoc`` package.

    Only used when the real ``modules/document/bcdoc`` is absent (pytest
    conftest + Blender driver fallback). Product code keeps importing the
    real names: ``from bcdoc.document import Document``,
    ``from bcdoc.entities import Line``, ``bcdoc.errors.NoOpenTransaction``.
    """
    import sys
    import types

    if "bcdoc" in sys.modules:
        return  # real package already importable

    pkg = types.ModuleType("bcdoc")
    pkg.__doc__ = "contract double installed as bcdoc (replaced by real bcdoc)"
    pkg.SCHEMA = SCHEMA

    for name, attrs in (
        ("entities", (Entity, Line, Circle, Arc, entity_from_dict,
                      normalize_point, set_field, GEOMETRY_FIELDS)),
        ("document", (Document, Transaction, UndoGroup)),
        ("errors", (BcdocError, NoOpenTransaction, TransactionAlreadyOpen,
                    EntityNotFound, DuplicateEntity, DuplicateHandle,
                    InvalidEntityField, SerializationError)),
        ("selection", (SelectionState,)),
        ("transaction", (Transaction,)),
        ("undo", (UndoGroup,)),
    ):
        module = types.ModuleType(f"bcdoc.{name}")
        module.__doc__ = f"bcdoc.{name} — contract double"
        for attr in attrs:
            setattr(module, getattr(attr, "__name__", name), attr)
        setattr(pkg, name, module)
        sys.modules[f"bcdoc.{name}"] = module

    module = types.ModuleType("bcdoc.serialize")
    module.__doc__ = "bcdoc.serialize — contract double"
    module.SCHEMA = SCHEMA
    module.entity_to_dict = lambda e: e.to_dict()
    module.entity_from_dict = entity_from_dict
    setattr(pkg, "serialize", module)
    sys.modules["bcdoc.serialize"] = module

    module = types.ModuleType("bcdoc.units")
    module.__doc__ = "bcdoc.units — contract double"
    module.normalized = lambda units: dict(units or {"length": "mm", "angle": "deg"})
    setattr(pkg, "units", module)
    sys.modules["bcdoc.units"] = module

    pkg.Document = Document
    pkg.Transaction = Transaction
    pkg.UndoGroup = UndoGroup
    pkg.Entity = Entity
    pkg.Line = Line
    pkg.Circle = Circle
    pkg.Arc = Arc
    pkg.SelectionState = SelectionState
    pkg.errors = sys.modules["bcdoc.errors"]
    sys.modules["bcdoc"] = pkg
