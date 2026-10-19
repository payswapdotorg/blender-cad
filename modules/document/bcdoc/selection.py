"""Document-owned selection state (contract: m1-module-contracts.md §3.4).

Selection is session state, not document content:

- the ``epoch`` (``selection_epoch``, glossary §6) bumps on every content
  change (calls that would not change the set are no-ops and do not bump);
- selection changes NEVER bump ``doc_version``;
- ids are opaque strings — bcdoc v0 does not validate them against the
  entity store and does not auto-evict ids of removed entities (the
  drafting/agent layer owns that policy at M2+).
"""

from __future__ import annotations


def _as_id_set(ids) -> frozenset:
    """Accept an iterable of ids, or a single id string."""
    if isinstance(ids, str):
        return frozenset((ids,))
    return frozenset(str(i) for i in ids)


class SelectionState:
    def __init__(self, on_change=None):
        self._ids: frozenset = frozenset()
        self._epoch = 0
        #: callable fired with ("select", epoch) after every change; the
        #: Document wires this to its ``on_select`` callback list.
        self._on_change = on_change

    # -- state ------------------------------------------------------------
    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def ids(self) -> frozenset:
        return self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def __contains__(self, eid) -> bool:
        return eid in self._ids

    # -- mutation ---------------------------------------------------------
    def set(self, ids) -> None:
        """Replace the selection (list of ids, or one id string)."""
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
        if self._ids:
            self._ids = frozenset()
            self._bump()

    # -- internals ---------------------------------------------------------
    def _bump(self) -> None:
        self._epoch += 1
        if self._on_change is not None:
            self._on_change(("select", self._epoch))

    def _restore(self, ids, epoch: int) -> None:
        """Deserialization/rollback hook: set state without firing events."""
        self._ids = frozenset(str(i) for i in ids)
        self._epoch = int(epoch)

    def snapshot(self) -> tuple:
        """(ids, epoch) pair used for transaction rollback snapshots."""
        return (self._ids, self._epoch)
