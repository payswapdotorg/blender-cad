"""bcdoc exception types (contracts: m1-module-contracts.md §3 for the M1
set, m2-module-contracts.md §2 for the v2 additions).

Pure Python — this package must never import `bpy` (enforced by
modules/document/tests/test_no_bpy.py).
"""

from __future__ import annotations


class BcdocError(Exception):
    """Base class for all bcdoc errors."""


class NoOpenTransaction(BcdocError):
    """A mutating API was called outside an open transaction.

    The document model is transactional by construction: every mutation of
    document content must happen inside ``with doc.transaction(...)``.
    """


class TransactionAlreadyOpen(BcdocError):
    """A second transaction was opened while one is already open, or
    undo/redo was requested while a transaction is open.

    bcdoc v0 allows exactly one open transaction per document at a time
    (nested transactions are not supported at M1)."""

    def __init__(self, label: str = ""):
        label_part = f" ({label!r})" if label else ""
        super().__init__(
            "a transaction is already open on this document"
            + label_part
            + "; bcdoc v0 does not support nested transactions"
        )


class EntityNotFound(BcdocError):
    """``get``/``remove``/``update_entity`` referenced an unknown entity id."""

    def __init__(self, eid: str):
        super().__init__(f"no entity with id {eid!r}")
        self.eid = eid


class DuplicateEntity(BcdocError):
    """An entity with the same id is already stored in the document."""

    def __init__(self, eid: str):
        super().__init__(f"entity id {eid!r} already exists in the document")
        self.eid = eid


class DuplicateHandle(BcdocError):
    """The requested entity handle is already used by another entity.

    Interchange callers (bcio) catch this to re-allocate and record the
    deviation in the loss ledger."""

    def __init__(self, handle: int):
        super().__init__(f"entity handle {handle} is already in use")
        self.handle = handle


class InvalidHandle(BcdocError):
    """A handle value outside the legal range (must be >= 1) was requested."""

    def __init__(self, handle):
        super().__init__(f"invalid entity handle {handle!r} (must be an int >= 1)")
        self.handle = handle


class InvalidEntityField(BcdocError):
    """``update_entity`` was asked to change a field the entity kind does
    not have (or a field name that is not valid at all)."""

    def __init__(self, kind: str, field: str):
        super().__init__(f"entity kind {kind!r} has no mutable field {field!r}")
        self.kind = kind
        self.field = field


class DuplicateLayer(BcdocError):
    """``add_layer`` was called with a name that already exists."""

    def __init__(self, name: str):
        super().__init__(f"layer {name!r} already exists")
        self.name = name


class LayerNotFound(BcdocError):
    """A layer-table mutation referenced an unknown layer name."""

    def __init__(self, name: str):
        super().__init__(f"no layer named {name!r}")
        self.name = name


class LayerNotEmpty(BcdocError):
    """A layer carrying entities cannot be removed (guard, contracts §2.2)."""

    def __init__(self, name: str, count: int = 0):
        super().__init__(
            f"layer {name!r} still carries {count} entity(ies); "
            "move or erase them before removing the layer"
        )
        self.name = name
        self.count = count


class ProtectedRecord(BcdocError):
    """An always-present table record cannot be removed (the "0" layer and
    the "Standard" text/dim styles — contracts §2.2/§2.6)."""

    def __init__(self, kind: str, name: str):
        super().__init__(f"{kind} {name!r} is always present and can never be removed")
        self.kind = kind
        self.name = name


class BlockNotFound(BcdocError):
    """A block operation referenced an unknown block definition."""

    def __init__(self, name: str):
        super().__init__(f"no block definition named {name!r}")
        self.name = name


class DuplicateBlock(BcdocError):
    """``add_block`` was called with a name that already exists."""

    def __init__(self, name: str):
        super().__init__(f"block {name!r} already exists")
        self.name = name


class BlockInUse(BcdocError):
    """The block definition is referenced by insert entities and cannot be
    removed (scan the store for kind == "insert" with matching name)."""

    def __init__(self, name: str, refs: int = 0):
        super().__init__(
            f"block {name!r} is referenced by {refs} insert entity(ies); "
            "erase the references before removing the definition"
        )
        self.name = name
        self.refs = refs


class LayoutNotFound(BcdocError):
    """A layout operation referenced an unknown layout name."""

    def __init__(self, name: str):
        super().__init__(f"no layout named {name!r}")
        self.name = name


class DuplicateLayout(BcdocError):
    """A layout was created/renamed to a name that already exists."""

    def __init__(self, name: str):
        super().__init__(f"layout {name!r} already exists")
        self.name = name


class LayoutNotEmpty(BcdocError):
    """A layout whose space still carries entities cannot be removed
    (invariant: entities never reference a removed layout)."""

    def __init__(self, name: str, count: int = 0):
        super().__init__(
            f"layout {name!r} still carries {count} entity(ies) in its space; "
            "move or erase them before removing the layout"
        )
        self.name = name
        self.count = count


class InvalidSpace(BcdocError):
    """An entity/space operation referenced a space that is neither
    "MODEL" nor an existing layout name."""

    def __init__(self, space: str):
        super().__init__(
            f"unknown space {space!r} (expected 'MODEL' or an existing layout name)"
        )
        self.space = space


class UnknownSetting(BcdocError):
    """A settings operation referenced a name outside SETTING_DEFS."""

    def __init__(self, name: str):
        super().__init__(f"unknown setting {name!r}")
        self.name = name


class InvalidSettingValue(BcdocError):
    """A settings value failed type/choices validation for its name."""

    def __init__(self, name: str, value, reason: str = ""):
        message = f"invalid value for setting {name!r}: {value!r}"
        if reason:
            message += f" ({reason})"
        super().__init__(message)
        self.name = name
        self.value = value


class StyleNotFound(BcdocError):
    """A style operation referenced an unknown text/dim style name."""

    def __init__(self, kind: str, name: str):
        super().__init__(f"no {kind} style named {name!r}")
        self.kind = kind
        self.name = name


class DuplicateStyle(BcdocError):
    """A style was created with a name that already exists."""

    def __init__(self, kind: str, name: str):
        super().__init__(f"{kind} style {name!r} already exists")
        self.kind = kind
        self.name = name


class JournalConflict(BcdocError):
    """An undo/redo journal operation could not be applied because the
    document state does not match the journal's expectations (corrupted or
    foreign journal data, or an inconsistent op sequence)."""


class SerializationError(BcdocError):
    """``Document.load`` received text that is not a valid ``bcdoc/1``,
    ``bcdoc/2`` or ``bcdoc/3`` document (unknown schema, malformed JSON,
    or structurally invalid content)."""


# ---------------------------------------------------------------------------
# bcdoc/3 — constrained-sketch content (m3-module-contracts.md §5)
# ---------------------------------------------------------------------------

class SketchNotFound(BcdocError):
    """A sketch-table operation referenced an unknown sketch id."""

    def __init__(self, sketch_id: str):
        super().__init__(f"no sketch with id {sketch_id!r}")
        self.sketch_id = sketch_id


class DuplicateSketch(BcdocError):
    """``SketchTable.add`` was called with a sketch id that already exists."""

    def __init__(self, sketch_id: str):
        super().__init__(f"sketch {sketch_id!r} already exists")
        self.sketch_id = sketch_id


class ConstraintNotFound(BcdocError):
    """A constraint operation referenced an unknown constraint id."""

    def __init__(self, sketch_id: str, c_id: str):
        super().__init__(f"no constraint {c_id!r} in sketch {sketch_id!r}")
        self.sketch_id = sketch_id
        self.c_id = c_id


class DuplicateConstraint(BcdocError):
    """A constraint with the same c_id already exists in the sketch
    (per-sketch uniqueness, contracts §5.2)."""

    def __init__(self, sketch_id: str, c_id: str):
        super().__init__(f"constraint {c_id!r} already exists in sketch "
                         f"{sketch_id!r}")
        self.sketch_id = sketch_id
        self.c_id = c_id


class JunctionNotFound(BcdocError):
    """A junction operation or junction ref referenced an unknown junction
    id (junctions are sketch-local, contracts §1.3/§5.1)."""

    def __init__(self, sketch_id: str, junction_id: str):
        super().__init__(f"no junction {junction_id!r} in sketch "
                         f"{sketch_id!r}")
        self.sketch_id = sketch_id
        self.junction_id = junction_id


class DuplicateJunction(BcdocError):
    """A junction with the same id already exists in the sketch."""

    def __init__(self, sketch_id: str, junction_id: str):
        super().__init__(f"junction {junction_id!r} already exists in "
                         f"sketch {sketch_id!r}")
        self.sketch_id = sketch_id
        self.junction_id = junction_id


class DanglingSketchRef(BcdocError):
    """A constraint ref or junction member addressed an entity that is not
    in the document (guards §5.1: refs are validated at every ref-writing
    mutation against the live document; parse rejects them at load)."""

    def __init__(self, eid: str):
        super().__init__(f"sketch ref addresses unknown entity {eid!r}")
        self.eid = eid


class EntityInUse(BcdocError):
    """``Document.remove`` refused: the entity is still referenced by a
    sketch constraint or junction member (BlockInUse precedent, contracts
    §5.3 — compose remove-constraint-then-remove-entity; bcdoc never
    silently deletes constraints)."""

    def __init__(self, eid: str, count: int = 0):
        super().__init__(
            f"entity {eid!r} is still referenced by {count} sketch "
            "constraint/junction ref(s); remove the referencing sketch "
            "content first")
        self.eid = eid
        self.count = count
