"""Block definitions and references (contract: m2-module-contracts.md §2.3).

A :class:`BlockDefinition` owns COPIES of its member entities (they are
NOT part of the document entity store). ``insert`` entities reference
definitions BY NAME, so a redefinition updates every reference
automatically (display regenerates; round-trips keep handles on the
references).

Ownership rules (binding):

- ``add_block`` deep-copies the passed entities (``entity.copy()``),
  strips their ``space`` to "MODEL" and keeps layer/color/linetype/
  lineweight (ByBlock color 0 is legal for members);
- the definition handle comes from the document handle space (the same
  monotonic allocator as entities; low handles reserved for tables are
  respected by it);
- ``remove_block`` raises :class:`errors.BlockInUse` while insert
  references exist.

Journal ops carry full entity-dict snapshots (``add_block`` /
``remove_block`` / ``redefine_block``) so replay and save/load rebuild
definitions. Restored members are equal copies, not identity-preserving
objects (block members have no identity contract — unlike store
entities, whose undo restores the same Python objects).
"""

from __future__ import annotations

from . import errors
from .entities import Entity, normalize_point


class BlockDefinition:
    """One block definition: name + base point + handle + owned members."""

    def __init__(self, name, base_point, handle, entities):
        self.name = str(name)
        self.base_point = normalize_point(base_point)
        self.handle = int(handle)
        self.entities = list(entities)

    # -- serialization --------------------------------------------------------
    def to_dict(self) -> dict:
        """Fixed-order dict {name, base_point, handle, entities} (pinned key
        order, contract §2.7; members in definition order)."""
        return {
            "name": self.name,
            "base_point": list(self.base_point),
            "handle": int(self.handle),
            "entities": [member.to_json_dict() for member in self.entities],
        }

    def state_dict(self) -> dict:
        """The mutable state subset {base_point, entities} used by
        ``redefine_block`` journal ops."""
        return {
            "base_point": list(self.base_point),
            "entities": [member.to_json_dict() for member in self.entities],
        }

    def copy(self) -> "BlockDefinition":
        """Deep copy (members copied; handles/ids preserved)."""
        return BlockDefinition(self.name, self.base_point, self.handle,
                               [member.copy() for member in self.entities])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<BlockDefinition {self.name!r} base_point={self.base_point} "
                f"handle={self.handle} members={len(self.entities)}>")


def _copy_members(entities) -> list:
    """Owned copies with space stripped to MODEL (contract §2.3)."""
    members = []
    for entity in entities:
        if not isinstance(entity, Entity):
            raise TypeError(
                f"block members must be Entity objects, got {type(entity).__name__}")
        member = entity.copy()
        member.space = "MODEL"
        members.append(member)
    return members


class BlockTable:
    """Name-keyed, insertion-ordered block definitions (journaled)."""

    def __init__(self, document=None):
        self._doc = document
        self._blocks: dict = {}

    # -- reads ---------------------------------------------------------------
    def names(self) -> list:
        return list(self._blocks)

    def get(self, name: str):
        return self._blocks.get(str(name))

    def __contains__(self, name) -> bool:
        return str(name) in self._blocks

    def __iter__(self):
        return iter(self.names())

    def __len__(self) -> int:
        return len(self._blocks)

    # -- mutations (transaction + journal required) --------------------------
    def add(self, name, base_point, entities) -> BlockDefinition:
        tx = self._doc._require_tx()
        name = str(name)
        if not name:
            raise ValueError("block name must be a non-empty string")
        if name in self._blocks:
            raise errors.DuplicateBlock(name)
        members = _copy_members(entities)
        handle = self._doc._alloc_handle()
        definition = BlockDefinition(name, base_point, handle, members)
        self._blocks[name] = definition
        tx._record({"op": "add_block", "name": name,
                    "base_point": list(definition.base_point),
                    "handle": handle,
                    "entities": [m.to_json_dict() for m in members]})
        return definition

    def redefine(self, name, entities, base_point=None) -> BlockDefinition:
        tx = self._doc._require_tx()
        name = str(name)
        definition = self._blocks.get(name)
        if definition is None:
            raise errors.BlockNotFound(name)
        members = _copy_members(entities)
        old_state = definition.state_dict()
        new_base = definition.base_point if base_point is None \
            else normalize_point(base_point)
        definition.base_point = new_base
        definition.entities = members
        tx._record({
            "op": "redefine_block", "name": name,
            "new": definition.state_dict(),
            "old": old_state,
        })
        return definition

    def remove(self, name) -> BlockDefinition:
        tx = self._doc._require_tx()
        name = str(name)
        definition = self._blocks.get(name)
        if definition is None:
            raise errors.BlockNotFound(name)
        refs = self.ref_ids(name)
        if refs:
            raise errors.BlockInUse(name, len(refs))
        del self._blocks[name]
        tx._record({"op": "remove_block", "name": name,
                    "record": definition.to_dict()})
        return definition

    def ref_ids(self, name: str) -> list:
        """Insert entity ids referencing this block, in store order."""
        return self._doc._insert_ref_ids(str(name))

    # -- internals (journal application / rebuild; no tx) --------------------
    def _insert(self, definition: BlockDefinition) -> None:
        self._blocks[definition.name] = definition

    def _drop(self, name: str):
        return self._blocks.pop(str(name), None)

    def _restore(self, definitions: list) -> None:
        names = [definition.name for definition in definitions]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate block names in {names!r}")
        self._blocks = {}
        for definition in definitions:
            self._blocks[definition.name] = definition

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BlockTable {self.names()!r}>"
