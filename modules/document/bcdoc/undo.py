"""Undo journal: undo groups and the op vocabulary (contract §3.3).

Journal op vocabulary (plain dicts; JSON-serializable via ``UndoGroup.to_dict``):

``{"op": "add", "entity": <entity dict | live Entity>, "index": int}``
    Put the (previously removed) entity back into the store at ``index``.
    Within a live session the op carries the ENTITY OBJECT ITSELF so undo
    restores the very same Python object (identity guarantee relied on by
    the command layer); ``to_dict`` lazily converts it to the JSON form.
    After a save/load round-trip the entity is a plain dict and undo
    necessarily produces an equal copy (identity cannot survive JSON).
    Inverse: ``{"op": "remove", "id": ...}``.

``{"op": "remove", "id": str, "entity": ..., "index": int}``
    Remove the entity with ``id`` (the live journal keeps the entity + its
    insertion index so the inverse can restore both position and identity).
    Inverse: add-with-entity (captured live).

``{"op": "mutate", "id": str, "changes": {field: value, ...}}``
    Set ``changes`` on the entity. Inverse: mutate with the prior values
    (captured live).

``{"op": "add_layer", "name": str}`` / ``{"op": "remove_layer", "name": str}``
    Layer-table edits; inverses of each other.

Every committed transaction appends one :class:`UndoGroup` whose entries
are the *reversed* journal — applying them in order undoes the
transaction. Undo itself re-applies those entries as a new committed
transaction (bumping ``doc_version``, per the monotonicity rule) and the
counter-ops it captures become the redo group.
"""

from __future__ import annotations


class UndoGroup:
    """One committed transaction's reversal, ready to be applied by undo."""

    __slots__ = ("label", "doc_version", "entries")

    def __init__(self, label: str, doc_version: int, entries):
        self.label = str(label)
        #: doc_version this group's transaction PRODUCED (post-bump).
        self.doc_version = int(doc_version)
        #: reversed-op journal (list of op dicts; see module docstring).
        self.entries = list(entries)

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        """JSON-safe view of the group: journal ops may carry the LIVE entity
        object (identity-preserving undo within a session); this converts
        them to the fixed-order entity dict form on the way out."""
        return {
            "label": self.label,
            "doc_version": self.doc_version,
            "entries": [_op_to_json(op) for op in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UndoGroup":
        return cls(data["label"], data["doc_version"], data["entries"])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<UndoGroup {self.label!r} v{self.doc_version} "
            f"{len(self.entries)} op(s)>"
        )


def _op_to_json(op: dict) -> dict:
    """One journal op in JSON-safe form (live Entity payloads -> dicts)."""
    data = dict(op)
    entity = data.get("entity")
    if entity is not None and not isinstance(entity, dict):
        data["entity"] = entity.to_json_dict()
    return data


def inverse_of_applied(op: dict) -> dict:
    """Pure function: given a journal op that was APPLIED to the document,
    return the op that reverses it (no live state required — remove ops
    carry their own entity snapshot, mutate ops carry the prior values)."""
    kind = op["op"]
    if kind == "add":
        return {"op": "remove", "id": op["id"]}
    if kind == "remove":
        return {"op": "add", "entity": op["entity"], "index": op["index"]}
    if kind == "mutate":
        return {
            "op": "mutate",
            "id": op["id"],
            "changes": dict(op["changes"]),
        }
    if kind == "add_layer":
        return {"op": "remove_layer", "name": op["name"]}
    if kind == "remove_layer":
        return {"op": "add_layer", "name": op["name"]}
    raise ValueError(f"unknown journal op {op!r}")
