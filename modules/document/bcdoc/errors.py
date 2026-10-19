"""bcdoc exception types (contract: docs/00-architecture/m1-module-contracts.md §3).

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


class JournalConflict(BcdocError):
    """An undo/redo journal operation could not be applied because the
    document state does not match the journal's expectations (corrupted or
    foreign journal data, or an inconsistent op sequence)."""


class SerializationError(BcdocError):
    """``Document.load`` received text that is not a valid ``bcdoc/1``
    document (unknown schema, malformed JSON, or structurally invalid
    content)."""
