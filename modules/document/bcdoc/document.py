"""The CAD document model (contract: m1-module-contracts.md §3.2 as
amended by m2-module-contracts.md §2/§14).

The Document is the authoritative engineering model (document-model doc
§1): every mutation of content happens inside a transaction and produces
a monotonically increasing ``doc_version`` (glossary §6). The Blender
scene, when present, is a one-way derived display of this model.

v2 (m2-module-contracts.md §2) adds the layer table (records, not bare
names), block definitions, layouts/spaces, settings (sysvars) and
text/dim style tables — all document content, all journaled — plus the
session state ``current_space`` / ``active_layout`` /
``last_selection_ids`` (like selection: never serialized, never
journaled).

Conventions and honest notes:

- handle allocation starts at 4097 (0x1001): low handles are reserved
  for table/dictionary objects in exported files, mirroring real DWG/DXF
  documents, so a fresh bcdoc exports into ezdxf collision-free. Block
  definitions draw their handles from the same monotonic allocator;
- SETTINGS EXCEPTION (binding): ``doc.settings`` is persisted
  (bcdoc/2 ``settings`` key) but NOT journaled and NOT rolled back —
  UNDO does not revert sysvars (AutoCAD precedent). A failed transaction
  deliberately leaves settings changes applied while every table
  (entities/layers/blocks/layouts/styles) rolls back bit-identically;
- ``current_space`` / ``active_layout`` / ``last_selection_ids`` are
  session state: a loaded document always starts in "MODEL" space with
  no active layout and no previous selection;
- selection is session state (epoch bumps, ``doc_version`` untouched) and
  is NOT auto-evicted when entities are removed;
- one open transaction per document at a time (no nesting at M2).
"""

from __future__ import annotations

from . import errors, serialize, units as units_mod
from .entities import Entity, normalize_point, set_field
from .layers import LayerRecord, LayerTable
from .blocks import BlockDefinition, BlockTable
from .layouts import LayoutRecord, LayoutTable
from .settings import Settings
from .styles import DimStyleRecord, DimStyleTable, TextStyleRecord, TextStyleTable
from .selection import SelectionState
from .transaction import Transaction
from .undo import UndoGroup, inverse_of_applied

#: First handle handed out by a fresh document (see module docstring).
FIRST_HANDLE = 0x1001

#: The only non-layout space name (entities route via ``space``).
MODEL_SPACE = "MODEL"


class Document:
    """Authoritative document model (pure Python, no bpy)."""

    def __init__(self, name: str = "Untitled", units=None):
        self.name = str(name)
        self.units = units_mod.normalized(units)
        #: Monotonic counter; bumped by every COMMITTED transaction.
        self.doc_version = 0
        #: Next handle to allocate (never decreases across commits).
        self.next_handle = FIRST_HANDLE
        #: System variables (typed; persisted, NOT journaled — §2.5).
        self.settings = Settings()
        #: Session selection state (never bumps doc_version).
        self.selection = SelectionState(on_change=self._fire_select)
        #: SESSION state: which space edits flow to ("MODEL" or a layout
        #: name). NOT serialized, NOT journaled (contracts §2.4).
        self.current_space = MODEL_SPACE
        #: SESSION state: which layout tab is being viewed (None = the
        #: Model tab). NOT serialized, NOT journaled (contracts §5.4).
        self.active_layout = None
        #: SESSION state: the last non-empty selection used by a command
        #: (the "Previous" selection mode reads this — contracts §4).
        #: NOT serialized, NOT journaled.
        self.last_selection_ids = []
        #: Event callback lists: callables receive ("doc", doc_version)
        #: and ("select", epoch) tuples (contract §3.6).
        self.on_change = []
        self.on_select = []
        # -- internal state (all document content) --------------------------
        self._layer_table = LayerTable(self)
        self._block_table = BlockTable(self)
        self._layout_table = LayoutTable(self)
        self._text_styles = TextStyleTable(self)
        self._dim_styles = DimStyleTable(self)
        self._store: dict = {}  # entity id -> Entity (insertion ordered)
        self._by_handle: dict = {}  # handle -> entity id
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._open_tx = None

    # ------------------------------------------------------------------
    # layers (contract §2.2; M1 §3.2 type change sanctioned by §14)
    # ------------------------------------------------------------------
    @property
    def layers(self) -> LayerTable:
        """The ordered layer table ("0" first, always present).

        Type change vs M1: ``list[str]`` -> :class:`bcdoc.layers.LayerTable`
        (contracts §14). M1 call sites keep working: ``name in doc.layers``,
        ``len(...)``, iteration over names and ``doc.layers == ["0", ...]``
        name-sequence equality. Table mutations go through
        ``doc.layers.add/set_props/remove`` (transaction + journal) or the
        thin :meth:`add_layer` compat wrapper.
        """
        return self._layer_table

    @property
    def current_layer(self) -> str:
        """The CLAYER setting, with fallback "0" when it references a
        layer that does not exist (contract §2.2)."""
        try:
            name = self.settings.get("CLAYER")
        except errors.BcdocError:  # pragma: no cover - CLAYER always defined
            return "0"
        if isinstance(name, str) and self._layer_table.get(name) is not None:
            return name
        return "0"

    def add_layer(self, name: str) -> str:
        """Thin M1 compat wrapper (kept for bcio import): creates a layer
        with DEFAULT properties inside the open transaction. Rich records
        go through ``doc.layers.add(name, **props)``."""
        record = self._layer_table.add(name)
        return record.name

    def _entities_on_layer(self, name: str) -> list:
        return [entity for entity in self._store.values()
                if entity.layer == name]

    # ------------------------------------------------------------------
    # blocks (contract §2.3)
    # ------------------------------------------------------------------
    def blocks(self) -> list:
        """Block definition names in definition order."""
        return self._block_table.names()

    def block_names(self) -> list:
        """Alias of :meth:`blocks` (kept for callers preferring the
        table-naming convention)."""
        return self._block_table.names()

    def add_block(self, name, base_point, entities) -> BlockDefinition:
        """Create a block definition (requires an open transaction).

        COPIES the passed entities (``entity.copy()``), strips their
        space to "MODEL" and keeps layer/color/linetype/lineweight
        (ByBlock color 0 is legal for members). The definition handle
        comes from the document handle space."""
        return self._block_table.add(name, base_point, entities)

    def block(self, name) -> BlockDefinition:
        definition = self._block_table.get(name)
        if definition is None:
            raise errors.BlockNotFound(str(name))
        return definition

    def redefine_block(self, name, entities, base_point=None) -> BlockDefinition:
        """Replace a definition's members (and optionally its base point);
        every insert reference updates automatically (references are BY
        NAME). ``base_point=None`` keeps the current base point."""
        return self._block_table.redefine(name, entities, base_point)

    def remove_block(self, name) -> BlockDefinition:
        """Remove a definition; :class:`errors.BlockInUse` while insert
        references exist."""
        return self._block_table.remove(name)

    def block_ref_ids(self, name) -> list:
        """Insert entity ids referencing ``name``, in store order."""
        return self._block_table.ref_ids(name)

    def _insert_ref_ids(self, name: str) -> list:
        return [entity.id for entity in self._store.values()
                if entity.kind == "insert" and entity.name == name]

    # ------------------------------------------------------------------
    # layouts + spaces (contract §2.4)
    # ------------------------------------------------------------------
    def layouts(self) -> list:
        """Layout names in table order."""
        return self._layout_table.names()

    def add_layout(self, name, page_width=420.0, page_height=297.0,
                   paper_units="mm") -> LayoutRecord:
        return self._layout_table.add(name, page_width=page_width,
                                       page_height=page_height,
                                       paper_units=paper_units)

    def layout(self, name) -> LayoutRecord:
        record = self._layout_table.get(name)
        if record is None:
            raise errors.LayoutNotFound(str(name))
        return record

    def rename_layout(self, old, new) -> LayoutRecord:
        """Rename a layout; entities in its space are re-routed to the new
        name (they never reference a missing layout)."""
        return self._layout_table.rename(old, new)

    def remove_layout(self, name) -> LayoutRecord:
        """Remove a layout; refuses while entities live in its space."""
        return self._layout_table.remove(name)

    def reorder_layout(self, name, index) -> LayoutRecord:
        return self._layout_table.reorder(name, index)

    def set_current_space(self, name) -> None:
        """Set the session's active space; validates ``name`` ∈ {"MODEL"}
        ∪ layout names (else :class:`errors.InvalidSpace`). Maintains the
        TILEMODE setting (1 in MODEL, 0 in paper — contracts §5.4)."""
        name = str(name)
        if name != MODEL_SPACE and self._layout_table.get(name) is None:
            raise errors.InvalidSpace(name)
        self.current_space = name
        self.settings.set("TILEMODE", 1 if name == MODEL_SPACE else 0)

    def entities_in_space(self, name) -> list:
        """Entities whose ``space`` is ``name`` ("MODEL" or a layout
        name), in store order; live objects."""
        name = str(name)
        if name != MODEL_SPACE and self._layout_table.get(name) is None:
            raise errors.InvalidSpace(name)
        return self._entities_in_space_raw(name)

    def _entities_in_space_raw(self, name: str) -> list:
        return [entity for entity in self._store.values()
                if entity.space == name]

    def _reroute_space(self, old: str, new: str) -> None:
        """Move every entity of space ``old`` to ``new`` and follow the
        session-space pointers when they named the old layout."""
        for entity in self._store.values():
            if entity.space == old:
                entity.space = new
        if self.current_space == old:
            self.current_space = new
        if self.active_layout == old:
            self.active_layout = new

    # ------------------------------------------------------------------
    # styles (contract §2.6)
    # ------------------------------------------------------------------
    def text_styles(self) -> list:
        """Text style names ("Standard" always present)."""
        return self._text_styles.names()

    def add_text_style(self, name, **props) -> TextStyleRecord:
        return self._text_styles.add(name, **props)

    def text_style(self, name) -> TextStyleRecord:
        record = self._text_styles.get(name)
        if record is None:
            raise errors.StyleNotFound("text", str(name))
        return record

    def set_text_style_props(self, name, **changes) -> TextStyleRecord:
        """Journaled property mutation of a text style (the
        ``mutate_text_style`` journal op)."""
        return self._text_styles.mutate(name, **changes)

    def remove_text_style(self, name) -> TextStyleRecord:
        """Journaled removal; "Standard" is protected (always present)."""
        return self._text_styles.remove(name)

    def dim_styles(self) -> list:
        """Dim style names ("Standard" always present)."""
        return self._dim_styles.names()

    def add_dim_style(self, name, **props) -> DimStyleRecord:
        return self._dim_styles.add(name, **props)

    def dim_style(self, name) -> DimStyleRecord:
        record = self._dim_styles.get(name)
        if record is None:
            raise errors.StyleNotFound("dim", str(name))
        return record

    def set_dim_style_props(self, name, **changes) -> DimStyleRecord:
        """Journaled property mutation of a dim style (the
        ``mutate_dim_style`` journal op)."""
        return self._dim_styles.mutate(name, **changes)

    def remove_dim_style(self, name) -> DimStyleRecord:
        """Journaled removal; "Standard" is protected (always present)."""
        return self._dim_styles.remove(name)

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
        Handles are never reused after a remove. The entity's ``space``
        must be "MODEL" or an existing layout name (else
        :class:`errors.InvalidSpace`).
        """
        tx = self._require_tx()
        if not isinstance(e, Entity):
            raise TypeError(f"add_entity expects an Entity, got {type(e).__name__}")
        if e.id in self._store:
            raise errors.DuplicateEntity(e.id)
        if e.space != MODEL_SPACE and self._layout_table.get(e.space) is None:
            raise errors.InvalidSpace(e.space)

        if handle is None:
            assigned = self._alloc_handle()
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
        Valid fields: layer, color, linetype, lineweight, space + the
        kind's geometry fields. Unknown layers are auto-created (same
        transaction); a ``space`` change must target "MODEL" or an
        existing layout.
        """
        tx = self._require_tx()
        entity = self.get(eid)
        for field, _value in changes.items():
            if field not in entity.mutable_fields:
                raise errors.InvalidEntityField(entity.kind, field)
        if "space" in changes:
            new_space = str(changes["space"])
            if new_space != MODEL_SPACE and self._layout_table.get(new_space) is None:
                raise errors.InvalidSpace(new_space)
        # Keep the layer-table invariant: an entity may only reference
        # layers that exist — auto-create inside this same transaction
        # (journaled, so undo reverts both atomically).
        if "layer" in changes:
            new_layer = str(changes["layer"])
            if self._layer_table.get(new_layer) is None:
                record = LayerRecord(new_layer)
                self._layer_table._append(record)
                tx._record({"op": "add_layer", "name": new_layer,
                            "props": record.props_dict()})
        old = {}
        for field, value in changes.items():
            old[field] = getattr(entity, field)
            set_field(entity, field, value)
        tx._record({"op": "mutate", "id": eid, "changes": old})
        return entity

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

    def _alloc_handle(self) -> int:
        """Monotonic handle allocation (entities + block definitions)."""
        assigned = int(self.next_handle)
        self.next_handle = assigned + 1
        return assigned

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

        return self._apply_table_op(op, kind)

    def _apply_table_op(self, op: dict, kind: str) -> dict:
        """Journal application for the v2 table ops (layers/blocks/layouts/
        styles). Replays are tolerant: M1 bare layer ops (``add_layer`` /
        ``remove_layer`` without payloads) rebuild default records."""

        def _conflict(message: str):
            raise errors.JournalConflict(message)

        # -- layers -----------------------------------------------------
        if kind == "add_layer":
            name = op["name"]
            if self._layer_table.get(name) is not None:
                _conflict(f"layer {name!r} already present")
            try:
                record = LayerRecord(name, **(op.get("props") or {}))
            except (TypeError, ValueError) as exc:
                _conflict(f"bad add_layer op for {name!r}: {exc}")
            self._layer_table._append(record)
            return {"op": "remove_layer", "name": name}
        if kind == "remove_layer":
            name = op["name"]
            record = self._layer_table.get(name)
            if record is None:
                _conflict(f"layer {name!r} absent")
            if name == "0":
                _conflict("layer '0' can never be removed")
            self._layer_table._drop(name)
            return {"op": "add_layer", "name": name,
                    "props": record.props_dict()}
        if kind == "mutate_layer":
            name = op["name"]
            record = self._layer_table.get(name)
            if record is None:
                _conflict(f"layer {name!r} absent")
            try:
                prior = record.set(**op["changes"])
            except (TypeError, ValueError) as exc:
                _conflict(f"bad mutate_layer op for {name!r}: {exc}")
            return {"op": "mutate_layer", "name": name, "changes": prior}

        # -- blocks -----------------------------------------------------
        if kind == "add_block":
            name = op["name"]
            if self._block_table.get(name) is not None:
                _conflict(f"block {name!r} already present")
            handle = int(op["handle"])
            for other in self._block_table._blocks.values():
                if other.handle == handle:
                    _conflict(f"block handle {handle} already in use")
            members = self._block_members(op["entities"])
            definition = BlockDefinition(name, op["base_point"], handle,
                                         members)
            self._block_table._insert(definition)
            return {"op": "remove_block", "name": name}
        if kind == "remove_block":
            name = op["name"]
            definition = self._block_table.get(name)
            if definition is None:
                _conflict(f"block {name!r} absent")
            if self._insert_ref_ids(name):
                _conflict(f"block {name!r} is still referenced by inserts")
            self._block_table._drop(name)
            return {"op": "add_block", "name": name,
                    "base_point": list(definition.base_point),
                    "handle": definition.handle,
                    "entities": [m.to_json_dict()
                                 for m in definition.entities]}
        if kind == "redefine_block":
            name = op["name"]
            definition = self._block_table.get(name)
            if definition is None:
                _conflict(f"block {name!r} absent")
            state = op["new"]
            counter = {"op": "redefine_block", "name": name,
                       "new": definition.state_dict(), "old": state}
            definition.base_point = normalize_point(state["base_point"])
            definition.entities = self._block_members(state["entities"])
            return counter

        # -- layouts ----------------------------------------------------
        if kind == "add_layout":
            name = op["name"]
            if self._layout_table.get(name) is not None:
                _conflict(f"layout {name!r} already present")
            record = LayoutRecord(name,
                                  page_width=op.get("page_width", 420.0),
                                  page_height=op.get("page_height", 297.0),
                                  paper_units=op.get("paper_units", "mm"))
            self._layout_table._append(record)
            return {"op": "remove_layout", "name": name}
        if kind == "remove_layout":
            name = op["name"]
            record = self._layout_table.get(name)
            if record is None:
                _conflict(f"layout {name!r} absent")
            if self._entities_in_space_raw(name):
                _conflict(f"space {name!r} still carries entities")
            self._layout_table._drop(name)
            return {"op": "add_layout", "name": name,
                    "page_width": record.page_width,
                    "page_height": record.page_height,
                    "paper_units": record.paper_units}
        if kind == "rename_layout":
            old = op["old"]
            new = op["new"]
            record = self._layout_table.get(old)
            if record is None:
                _conflict(f"layout {old!r} absent")
            if new != old and self._layout_table.get(new) is not None:
                _conflict(f"layout {new!r} already present")
            record.name = new
            self._reroute_space(old, new)
            return {"op": "rename_layout", "old": new, "new": old}
        if kind == "reorder_layout":
            name = op["name"]
            record = self._layout_table.get(name)
            if record is None:
                _conflict(f"layout {name!r} absent")
            index = int(op["old_index"])
            records = self._layout_table._records
            if not 0 <= index < len(records):
                _conflict(f"reorder index {index} out of range")
            old_index = records.index(record)
            records.remove(record)
            records.insert(index, record)
            return {"op": "reorder_layout", "name": name,
                    "old_index": old_index}

        # -- styles -----------------------------------------------------
        if kind in ("add_text_style", "add_dim_style"):
            table, record_cls = self._style_target(kind[4:])
            name = op["name"]
            if table.get(name) is not None:
                _conflict(f"style {name!r} already present")
            try:
                record = record_cls(name, **(op.get("props") or {}))
            except (TypeError, ValueError) as exc:
                _conflict(f"bad {kind} op for {name!r}: {exc}")
            table._insert(record)
            return {"op": kind.replace("add_", "remove_", 1), "name": name}
        if kind in ("remove_text_style", "remove_dim_style"):
            table, _record_cls = self._style_target(kind[7:])
            name = op["name"]
            record = table.get(name)
            if record is None:
                _conflict(f"style {name!r} absent")
            if name == "Standard":
                _conflict("style 'Standard' can never be removed")
            table._drop(name)
            return {"op": kind.replace("remove_", "add_", 1), "name": name,
                    "props": record.props_dict()}
        if kind in ("mutate_text_style", "mutate_dim_style"):
            table, _record_cls = self._style_target(kind[7:])
            name = op["name"]
            record = table.get(name)
            if record is None:
                _conflict(f"style {name!r} absent")
            try:
                prior = record.set(**op["changes"])
            except (TypeError, ValueError) as exc:
                _conflict(f"bad {kind} op for {name!r}: {exc}")
            return {"op": kind, "name": name, "changes": prior}

        raise errors.JournalConflict(f"unknown journal op {op!r}")

    def _style_target(self, which: str):
        """'text_style'/'dim_style' -> (table, record class)."""
        if which == "text_style":
            return self._text_styles, TextStyleRecord
        if which == "dim_style":
            return self._dim_styles, DimStyleRecord
        raise errors.JournalConflict(f"unknown style journal target {which!r}")

    def _block_members(self, records: list) -> list:
        """Rebuild owned block members from entity dicts (space forced to
        "MODEL" — definitions never route to layouts)."""
        members = []
        for record in records:
            member = serialize.entity_from_dict(record)
            member.space = MODEL_SPACE
            members.append(member)
        return members

    def _insert_at(self, index: int, entity: Entity) -> None:
        items = list(self._store.items())
        items.insert(max(0, min(index, len(items))), (entity.id, entity))
        self._store = dict(items)
        self._by_handle[entity.handle] = entity.id

    # -- snapshot/rollback support ----------------------------------------
    def _snapshot_state(self) -> dict:
        """Pre-transaction snapshot of ALL document content.

        Settings are deliberately EXCLUDED (sysvar exception — see module
        docstring): a failed transaction rolls back content, never
        sysvars."""
        return {
            "entities": [(eid, e.copy()) for eid, e in self._store.items()],
            "layers": [record.copy() for record in self._layer_table._records],
            "blocks": [definition.copy()
                       for definition in self._block_table._blocks.values()],
            "layouts": [record.copy() for record in self._layout_table._records],
            "text_styles": [record.copy()
                            for record in self._text_styles._records.values()],
            "dim_styles": [record.copy()
                           for record in self._dim_styles._records.values()],
            "next_handle": self.next_handle,
            "selection": self.selection.snapshot(),
            "doc_version": self.doc_version,
        }

    def _restore_state(self, snapshot: dict) -> None:
        """Full rollback to a snapshot (serialize()-bit-identical content;
        no events fire — the failed transaction never happened)."""
        self._store = dict(snapshot["entities"])
        self._by_handle = {e.handle: eid for eid, e in self._store.items()}
        self._layer_table._restore(snapshot["layers"])
        self._block_table._restore(snapshot["blocks"])
        self._layout_table._restore(snapshot["layouts"])
        self._text_styles._restore(snapshot["text_styles"])
        self._dim_styles._restore(snapshot["dim_styles"])
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
        """Stable ``bcdoc/2`` JSON (byte-stable for untouched documents)."""
        return serialize.to_json(self)

    @staticmethod
    def load(text: str) -> "Document":
        """Rebuild a document from ``bcdoc/1`` (deterministic upgrade) or
        ``bcdoc/2`` JSON; anything else raises
        :class:`bcdoc.errors.SerializationError`."""
        data = serialize.parse(text)
        doc = Document(name=data["name"], units=data["units"])
        doc._rebuild(data)
        return doc

    def _rebuild(self, data: dict) -> None:
        """Adopt parsed state directly (no events, no journal)."""
        self.doc_version = data["doc_version"]
        self.next_handle = data["next_handle"]
        self.settings._values = dict(data["__settings__"]._values)
        self._layer_table._restore(data["__layers__"])
        self._block_table._restore(data["__blocks__"])
        self._layout_table._restore(data["__layouts__"])
        self._text_styles._restore(data["__text_styles__"])
        self._dim_styles._restore(data["__dim_styles__"])
        self._store = {}
        self._by_handle = {}
        for entity in data["__entities__"]:
            self._store[entity.id] = entity
            self._by_handle[entity.handle] = entity.id
        self._undo_stack = list(data["__undo__"])
        self._redo_stack = list(data["__redo__"])
        self.selection._restore(data["selection"]["ids"], data["selection"]["epoch"])
        # Session state always starts fresh (contracts §2.4).
        self.current_space = MODEL_SPACE
        self.active_layout = None
        self.last_selection_ids = []
