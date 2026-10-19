"""Layouts and spaces (contract: m2-module-contracts.md §2.4).

A layout is a named paper-space page (:class:`LayoutRecord`); entities
route to spaces through their ``space`` field ("MODEL" or a layout
name). Viewports are ``viewport`` entities whose ``space`` is the layout
they belong to.

Session state (binding): ``current_space`` and ``active_layout`` are
SESSION state like selection — NOT serialized, NOT journaled; documents
always load with ``current_space == "MODEL"`` and ``active_layout is
None`` (a documented divergence from DXF, which persists the active
layout — interchange records it in the loss ledger on export).

Invariant (binding): entities never reference a removed layout —
``remove_layout`` refuses while entities live in that space
(:class:`errors.LayoutNotEmpty`).
"""

from __future__ import annotations

from . import errors

#: Model space name (the only non-layout space).
MODEL_SPACE = "MODEL"


class LayoutRecord:
    """One paper-space page: name + page size + paper units (§2.4)."""

    def __init__(self, name, page_width=420.0, page_height=297.0,
                 paper_units="mm"):
        self.name = str(name)
        self.page_width = float(page_width)
        self.page_height = float(page_height)
        self.paper_units = str(paper_units)

    def to_dict(self) -> dict:
        """Fixed-order record dict {name, page_width, page_height,
        paper_units} (pinned key order, contract §2.7)."""
        return {"name": self.name,
                "page_width": self.page_width,
                "page_height": self.page_height,
                "paper_units": self.paper_units}

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutRecord":
        if not isinstance(data, dict) or "name" not in data:
            raise ValueError(
                f"layout record must be a dict with a 'name', got {data!r}")
        return cls(data["name"],
                   page_width=data.get("page_width", 420.0),
                   page_height=data.get("page_height", 297.0),
                   paper_units=data.get("paper_units", "mm"))

    def copy(self) -> "LayoutRecord":
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        return clone

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<LayoutRecord {self.name!r} {self.page_width}x"
                f"{self.page_height} {self.paper_units}>")


class LayoutTable:
    """Ordered layout list + journaled mutations (transaction-gated)."""

    def __init__(self, document=None):
        self._doc = document
        self._records: list = []

    # -- reads ---------------------------------------------------------------
    def names(self) -> list:
        return [record.name for record in self._records]

    def get(self, name: str):
        name = str(name)
        for record in self._records:
            if record.name == name:
                return record
        return None

    def records(self) -> list:
        return [record.copy() for record in self._records]

    def __contains__(self, name) -> bool:
        try:
            return self.get(name) is not None
        except Exception:
            return False

    def __iter__(self):
        return iter(self.names())

    def __len__(self) -> int:
        return len(self._records)

    def __eq__(self, other) -> bool:
        if isinstance(other, (list, tuple)):
            return self.names() == list(other)
        if isinstance(other, LayoutTable):
            return self.names() == other.names()
        return NotImplemented

    __hash__ = None

    # -- mutations (transaction + journal required) --------------------------
    def add(self, name, page_width=420.0, page_height=297.0,
            paper_units="mm") -> LayoutRecord:
        tx = self._doc._require_tx()
        name = str(name)
        if self.get(name) is not None:
            raise errors.DuplicateLayout(name)
        record = LayoutRecord(name, page_width=page_width,
                              page_height=page_height, paper_units=paper_units)
        self._records.append(record)
        tx._record({"op": "add_layout", "name": name,
                    "page_width": record.page_width,
                    "page_height": record.page_height,
                    "paper_units": record.paper_units})
        return record

    def rename(self, old: str, new: str) -> LayoutRecord:
        """Rename a layout; entities living in its space are re-routed to
        the new name (invariant: entities never reference a missing
        layout). Session state (``current_space`` / ``active_layout``)
        follows when it referenced the old name."""
        tx = self._doc._require_tx()
        record = self.get(old)
        if record is None:
            raise errors.LayoutNotFound(str(old))
        new = str(new)
        if new != record.name and self.get(new) is not None:
            raise errors.DuplicateLayout(new)
        old_name = record.name
        record.name = new
        self._doc._reroute_space(old_name, new)
        tx._record({"op": "rename_layout", "old": old_name, "new": new})
        return record

    def remove(self, name: str) -> LayoutRecord:
        tx = self._doc._require_tx()
        record = self.get(name)
        if record is None:
            raise errors.LayoutNotFound(str(name))
        carriers = self._doc._entities_in_space_raw(record.name)
        if carriers:
            raise errors.LayoutNotEmpty(record.name, len(carriers))
        self._records.remove(record)
        tx._record({"op": "remove_layout", "name": record.name,
                    "record": record.to_dict()})
        return record

    def reorder(self, name, index: int) -> LayoutRecord:
        tx = self._doc._require_tx()
        record = self.get(name)
        if record is None:
            raise errors.LayoutNotFound(str(name))
        old_index = self._records.index(record)
        index = int(index)
        if not 0 <= index < len(self._records):
            raise ValueError(
                f"reorder index {index} out of range "
                f"(0..{len(self._records) - 1})")
        self._records.remove(record)
        self._records.insert(index, record)
        tx._record({"op": "reorder_layout", "name": record.name,
                    "old_index": old_index})
        return record

    # -- internals (journal application / rebuild; no tx) --------------------
    def _append(self, record: LayoutRecord) -> None:
        self._records.append(record)

    def _drop(self, name: str):
        record = self.get(name)
        if record is not None:
            self._records.remove(record)
        return record

    def _restore(self, records: list) -> None:
        names = [record.name for record in records]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate layout names in {names!r}")
        self._records = list(records)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LayoutTable {self.names()!r}>"
