"""Transactions (contract: m1-module-contracts.md §3.3; m2 §2.8).

``with doc.transaction(label) as tx:`` — on clean exit the transaction's
journal is committed (an :class:`~bcdoc.undo.UndoGroup` is pushed,
``doc_version`` bumps, ``on_change`` fires); on exception the document is
restored bit-identically from the ``__enter__`` snapshot (entity store in
insertion order, ALL v2 tables — layers, blocks, layouts, text/dim
styles — next_handle, selection ids+epoch).

Rollback strategy: full snapshot restore (the alternative — op-journal
reversal — would not cover in-place entity field changes as robustly).
A mid-transaction failure therefore leaves the document content
serialize()-bit-identical; that invariant is asserted by tests.

SETTINGS EXCEPTION (contracts §2.5, binding): ``doc.settings`` is NOT part
of the snapshot — sysvar changes made inside a failing transaction
deliberately survive (UNDO does not revert sysvars, matching AutoCAD for
out-of-command changes). Session state (``current_space`` /
``active_layout`` / ``last_selection_ids``) is likewise not rolled back.

Identity note (honest scope): undo/redo restore the SAME Python objects
(journal ops carry the live entities); a FAILED transaction restores
pre-existing entities as equal copies (same id/handle/values, new
object), and the same holds for block-definition members (no identity
contract). Nothing in the M1/M2 contracts or the command layer holds
object identity across a rollback, and id-keyed access (CommandResult,
display sync) is unaffected.
"""

from __future__ import annotations

from . import errors


class Transaction:
    """Context manager returned by :meth:`bcdoc.document.Document.transaction`."""

    def __init__(self, document, label: str):
        self._doc = document
        self.label = str(label)
        #: ops in application order (see bcdoc.undo docstring)
        self._journal = []
        self._snapshot = None
        self._committed = False
        self._closed = False

    # -- state ---------------------------------------------------------------
    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def journal(self):
        """Ops recorded so far (application order); read-only view."""
        return tuple(self._journal)

    # -- internals (used by Document) ----------------------------------------
    def _begin(self) -> None:
        self._snapshot = self._doc._snapshot_state()

    def _record(self, op: dict) -> None:
        self._journal.append(op)

    def _rollback(self) -> None:
        self._doc._restore_state(self._snapshot)
        self._journal = []
        self._snapshot = None
        self._closed = True

    def _commit(self) -> None:
        self._doc._commit_journal(self._journal, self.label)
        self._journal = []
        self._snapshot = None
        self._committed = True
        self._closed = True

    # -- context manager -------------------------------------------------------
    def __enter__(self) -> "Transaction":
        if self._closed:
            raise errors.BcdocError("transaction already closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._closed:  # defensive; Document keeps us single-open
            return False
        if exc_type is None:
            self._commit()
        else:
            self._rollback()
            # Never swallow the exception.
            return False
        return False
