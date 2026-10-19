"""The CAD document model v0 (contract: m1-module-contracts.md §3.2).

The Document is the authoritative engineering model (document-model doc
§1): every mutation of content happens inside a transaction and produces
a monotonically increasing ``doc_version`` (glossary §6). The Blender
scene, when present, is a one-way derived display of this model.

v0 conventions and honest notes:

- handle allocation starts at 4097 (0x1001): low handles are reserved for
  table/dictionary objects in exported files, mirroring real DWG/DXF
  documents, so a fresh bcdoc exports into ezdxf collision-free;
- layer state is names-only (contract §3.2 ``layers: list[str]``) —
  per-layer colors/linetypes are a recorded loss on interchange;
- selection is session state (epoch bumps, ``doc_version`` untouched) and
  is NOT auto-evicted when entities are removed;
- one open transaction per document at a time (no nesting at M1).
"""

from __future__ import annotations

from . import errors, serialize, units as units_mod
from .entities import Entity, set_field
from .selection import SelectionState
from .transaction import Transaction
from .undo import UndoGroup, inverse_of_applied

#: First handle handed out by a fresh document (see module docstring).
FIRST_HANDLE = 0x1001


class Document:
    """Authoritative document model (pure Python, no bpy)."""

    def __init__(self, name: str = "Untitled", units=None):
        self.name = str(name)
        self.units = units_mod.normalized(units)
        #: Monotonic counter; bumped by every COMMITTED transaction.
        self.doc_version = 0
        #: Layer names — "0" always present; names-only at v0.
        self.layers = ["0"]
        #: Next handle to allocate (never decreases across commits).
        self.next_handle = FIRST_HANDLE
        #: Session selection state (never bumps doc_version).
        self.selection = SelectionState(on_change=self._fire_select)
        #: Event callback lists: callables receive ("doc", doc_version)
        #: and ("select", epoch) tuples (contract §3.6).
        self.on_change = []
        self.on_select = []
        # -- internal state ------------------------------------------------
        self._store: dict = {}  # entity id -> Entity (insertion ordered)
        self._by_handle: dict = {}  # handle -> entity id
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._open_tx = None

    # ------------------------------------------------------------------
    # entities
    # ------------------------------------------------------------------
    def entities(self) -> list:
        """All entities in insertion order."""
        return list(self._store.values())

    def get(self, eid: str) -> Entity:
        try:
            return self._store[eid]
        except KeyError:
            raise errors.EntityNotFound(eid) from None

    def count_by_kind(self) -> dict:
        counts: dict = {}
        for entity in self._store.values():
            counts[entity.kind] = counts.get(entity.kind, 0) + 1
        return counts

    def add_entity(self, e: Entity, handle=None) -> Entity:
        """Add ``e`` (requires an open transaction).

        The entity gets a fresh monotonic handle, or the explicitly
        requested ``handle`` (used by DXF import to preserve foreign
        handles; raises :class:`errors.DuplicateHandle` on collision).
        Handles are never reused after a remove.
        """
        tx = self._require_tx()
        if not isinstance(e, Entity):
            raise TypeError(f"add_entity expects an Entity, got {type(e).__name__}")
        if e.id in self._store:
            raise errors.DuplicateEntity(e.id)

        if handle is None:
            assigned = int(self.next_handle)
            self.next_handle = assigned + 1
        else:
            try:
                assigned = int(handle)
            except (TypeError, ValueError):
                raise errors.InvalidHandle(handle) from None
            if assigned < 1:
                raise errors.InvalidHandle(assigned)
            if assigned in self._by_handle:
                raise errors.DuplicateHandle(assigned)
            if assigned >= self.next_handle:
                self.next_handle = assigned + 1

        e.handle = assigned
        index = len(self._store)
        self._store[e.id] = e
        self._by_handle[assigned] = e.id
        tx._record({"op": "add", "id": e.id})
        return e

    def remove(self, eid: str) -> Entity:
        """Remove the entity with ``eid`` (requires an open transaction).

        The journal keeps the LIVE entity object and its insertion index so
        an undo of this removal restores the very same Python object at the
        very same position (identity guarantee relied on by the command
        layer, W1 contract test `test_remove_is_journaled_and_undoable`)."""
        tx = self._require_tx()
        entity = self.get(eid)
        index = list(self._store).index(eid)
        del self._store[eid]
        self._by_handle.pop(entity.handle, None)
        tx._record({
            "op": "remove",
            "id": eid,
            "entity": entity,  # live object; serialized lazily (undo.py)
            "index": index,
        })
        return entity

    def update_entity(self, eid: str, **changes) -> Entity:
        """Change mutable fields of an entity inside the open transaction.

        Extension beyond the letter of contract §3.2 (which lists
        add/get/remove only): the contract requires transforms to go
        through document APIs inside transactions (§3.1 "the Document APIs
        are the only legal mutation path"), and undo requires the old
        values to be journaled — this method is that journaled path.
        Valid fields: layer, color, linetype + the kind's geometry fields.
        """
        tx = self._require_tx()
        entity = self.get(eid)
        old = {}
        for field, _value in changes.items():
            if field not in entity.mutable_fields:
                raise errors.InvalidEntityField(entity.kind, field)
        # Keep the layer-table invariant: an entity may only reference
        # layers that exist — auto-create inside this same transaction
        # (journaled, so undo reverts both atomically).
        if "layer" in changes:
            new_layer = str(changes["layer"])
            if new_layer not in self.layers:
                self.layers.append(new_layer)
                tx._record({"op": "add_layer", "name": new_layer})
        for field, value in changes.items():
            old[field] = getattr(entity, field)
            set_field(entity, field, value)
        tx._record({"op": "mutate", "id": eid, "changes": old})
        return entity

    # ------------------------------------------------------------------
    # layers
    # ------------------------------------------------------------------
    def add_layer(self, name: str) -> str:
        """Append a layer to the layer table (requires an open
        transaction; used by interchange import)."""
        tx = self._require_tx()
        name = str(name)
        if name in self.layers:
            raise errors.DuplicateLayer(name)
        self.layers.append(name)
        tx._record({"op": "add_layer", "name": name})
        return name

    # ------------------------------------------------------------------
    # transactions / undo
    # ------------------------------------------------------------------
    def transaction(self, label: str = "") -> Transaction:
        """Open the document's single transaction (context manager)."""
        if self._open_tx is not None:
            raise errors.TransactionAlreadyOpen(self._open_tx.label)
        tx = Transaction(self, label)
        self._open_tx = tx
        tx._begin()
        return tx

    def _require_tx(self) -> Transaction:
        if self._open_tx is None:
            raise errors.NoOpenTransaction(
                "document mutations are only legal inside "
                "'with document.transaction(...)'"
            )
        return self._open_tx

    def _commit_journal(self, journal, label: str) -> None:
        """Commit an applied journal: push the reversal as an UndoGroup,
        clear the redo stack, bump doc_version, fire on_change."""
        entries = [inverse_of_applied(op) for op in reversed(journal)]
        group = UndoGroup(label, self.doc_version + 1, entries)
        self._undo_stack.append(group)
        self._redo_stack.clear()
        self._open_tx = None
        self._bump_and_fire()

    def undo(self) -> bool:
        """Undo one committed transaction (itself a new committed
        transaction — doc_version bumps). False if the undo stack is empty."""
        self._require_no_open_tx()
        if not self._undo_stack:
            return False
        group = self._undo_stack.pop()
        redo_group = self._reapply(group.entries, f"undo: {group.label}")
        self._redo_stack.append(redo_group)
        self._bump_and_fire()
        return True

    def redo(self) -> bool:
        """Redo one undone transaction (symmetric to undo)."""
        self._require_no_open_tx()
        if not self._redo_stack:
            return False
        group = self._redo_stack.pop()
        undo_group = self._reapply(group.entries, f"redo: {group.label}")
        self._undo_stack.append(undo_group)
        self._bump_and_fire()
        return True

    def undo_depth(self) -> int:
        return len(self._undo_stack)

    def redo_depth(self) -> int:
        return len(self._redo_stack)

    def undo_groups(self):
        """Read-only view of the undo stack (oldest first)."""
        return tuple(self._undo_stack)

    def redo_groups(self):
        """Read-only view of the redo stack (oldest first)."""
        return tuple(self._redo_stack)

    # -- journal application ---------------------------------------------
    def _reapply(self, entries, label: str) -> UndoGroup:
        """Apply ``entries`` (in the given order), capturing the counter-ops.

        The returned group's entries are stored REVERSED: each counter was
        captured in application order, so reversing restores the order the
        opposite direction must apply them in (undo groups undo in
        reverse-journal order; redo groups re-apply in original-journal
        order) — this keeps undo→redo→undo… a stable ping-pong with exact
        insertion-order restoration."""
        counters = [self._apply_op(op) for op in entries]
        return UndoGroup(label, self.doc_version + 1, list(reversed(counters)))

    def _apply_op(self, op: dict) -> dict:
        """Apply one journal op; return its counter-op (live state captured
        here). Raises :class:`errors.JournalConflict` when the document
        state does not match what the op expects."""
        kind = op.get("op")
        if kind == "add":
            record = op["entity"]
            if isinstance(record, dict):
                # deserialized journal (post save/load): rebuild the entity
                entity = serialize.entity_from_dict(record)
            else:
                # live-session journal: the original object itself — undo
                # restores IDENTITY (same Python object, same handle)
                entity = record
            if entity.id in self._store:
                raise errors.JournalConflict(f"entity {entity.id!r} already present")
            if entity.handle in self._by_handle:
                raise errors.JournalConflict(f"handle {entity.handle} already in use")
            index = int(op.get("index", len(self._store)))
            self._insert_at(index, entity)
            return {"op": "remove", "id": entity.id}
        if kind == "remove":
            eid = op["id"]
            entity = self._store.get(eid)
            if entity is None:
                raise errors.JournalConflict(f"cannot remove absent entity {eid!r}")
            index = list(self._store).index(eid)
            del self._store[eid]
            self._by_handle.pop(entity.handle, None)
            # counter keeps the live object (identity for the redo path)
            return {"op": "add", "entity": entity, "index": index}
        if kind == "mutate":
            eid = op["id"]
            entity = self._store.get(eid)
            if entity is None:
                raise errors.JournalConflict(f"cannot mutate absent entity {eid!r}")
            prior = {}
            for field, value in op["changes"].items():
                prior[field] = getattr(entity, field)
                set_field(entity, field, value)
            return {"op": "mutate", "id": eid, "changes": prior}
        if kind == "add_layer":
            name = op["name"]
            if name in self.layers:
                raise errors.JournalConflict(f"layer {name!r} already present")
            self.layers.append(name)
            return {"op": "remove_layer", "name": name}
        if kind == "remove_layer":
            name = op["name"]
            if name not in self.layers:
                raise errors.JournalConflict(f"layer {name!r} absent")
            if name == "0":
                raise errors.JournalConflict("layer '0' can never be removed")
            self.layers.remove(name)
            return {"op": "add_layer", "name": name}
        raise errors.JournalConflict(f"unknown journal op {op!r}")

    def _insert_at(self, index: int, entity: Entity) -> None:
        items = list(self._store.items())
        items.insert(max(0, min(index, len(items))), (entity.id, entity))
        self._store = dict(items)
        self._by_handle[entity.handle] = entity.id

    # -- snapshot/rollback support ----------------------------------------
    def _snapshot_state(self) -> dict:
        return {
            "entities": [(eid, e.copy()) for eid, e in self._store.items()],
            "layers": list(self.layers),
            "next_handle": self.next_handle,
            "selection": self.selection.snapshot(),
            "doc_version": self.doc_version,
        }

    def _restore_state(self, snapshot: dict) -> None:
        """Full rollback to a snapshot (bit-identical serialize() output;
        no events fire — the failed transaction never happened)."""
        self._store = dict(snapshot["entities"])
        self._by_handle = {e.handle: eid for eid, e in self._store.items()}
        self.layers = list(snapshot["layers"])
        self.next_handle = snapshot["next_handle"]
        self.selection._restore(*snapshot["selection"])
        self.doc_version = snapshot["doc_version"]
        self._open_tx = None

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def _bump_and_fire(self) -> None:
        self.doc_version += 1
        self._fire_change(("doc", self.doc_version))

    def _fire_change(self, event) -> None:
        for callback in list(self.on_change):
            callback(event)

    def _fire_select(self, event) -> None:
        for callback in list(self.on_select):
            callback(event)

    def _require_no_open_tx(self) -> None:
        if self._open_tx is not None:
            raise errors.TransactionAlreadyOpen(self._open_tx.label)

    # ------------------------------------------------------------------
    # serialization
    # ------------------------------------------------------------------
    def serialize(self) -> str:
        """Stable ``bcdoc/1`` JSON (byte-stable for untouched documents)."""
        return serialize.to_json(self)

    @staticmethod
    def load(text: str) -> "Document":
        """Rebuild a document from ``bcdoc/1`` JSON (schema-exact)."""
        data = serialize.parse(text)
        doc = Document(name=data["name"], units=data["units"])
        doc._rebuild(data)
        return doc

    def _rebuild(self, data: dict) -> None:
        """Adopt parsed state directly (no events, no journal)."""
        self.doc_version = data["doc_version"]
        self.next_handle = data["next_handle"]
        self.layers = list(data["layers"])
        if "0" not in self.layers:  # invariant enforcement (tolerant read)
            self.layers.insert(0, "0")
        self._store = {}
        self._by_handle = {}
        for entity in data["__entities__"]:
            self._store[entity.id] = entity
            self._by_handle[entity.handle] = entity.id
        self._undo_stack = list(data["__undo__"])
        self._redo_stack = list(data["__redo__"])
        self.selection._restore(data["selection"]["ids"], data["selection"]["epoch"])
