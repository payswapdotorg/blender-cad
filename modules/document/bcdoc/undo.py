"""Undo journal: undo groups and the op vocabulary (contracts §3.3 M1,
§2.8 M2).

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
    (captured live; the API records ops carry the PRIOR values, so the
    pure inverse is the op itself).

``{"op": "add_layer", "name": str, "props": {...}}`` /
``{"op": "remove_layer", "name": str, "record": {...}}`` /
``{"op": "mutate_layer", "name": str, "changes": {...}}``
    Layer-table edits (v2 payloads: add carries the record properties,
    remove the full record, mutate the PRIOR values). M1 journals with
    bare ``{"op": "add_layer"/"remove_layer", "name"}`` still replay
    (missing payloads -> default records — tolerant replay rule).

``{"op": "add_block", "name", "base_point", "handle", "entities": [...]}`` /
``{"op": "remove_block", "name", "record": {...}}`` /
``{"op": "redefine_block", "name", "new": {...}, "old": {...}}``
    Block table edits; every op carries full entity-dict snapshots so
    journal replay rebuilds definitions (restored members are equal
    copies, not identity-preserving objects).

``{"op": "add_layout", "name", "page_width", "page_height", "paper_units"}`` /
``{"op": "remove_layout", "name", "record": {...}}`` /
``{"op": "rename_layout", "old", "new"}`` /
``{"op": "reorder_layout", "name", "old_index"}``
    Layout table edits (reorder's ``old_index`` is the PRE-move index, so
    applying the op moves the layout back there).

``{"op": "add_text_style"|"add_dim_style", "name", "props"}`` /
``{"op": "remove_text_style"|"remove_dim_style", "name", "record"}`` /
``{"op": "mutate_text_style"|"mutate_dim_style", "name", "changes"}``
    Style table edits (same shapes as the layer ops).

``{"op": "add_sketch", "sketch_id", "record": {...}}`` /
``{"op": "remove_sketch", "sketch_id", "record"}`` /
``{"op": "mutate_sketch", "sketch_id", "changes"}``
    Sketch-table lifecycle (bcdoc/3, contract m3 §2): add/remove carry the
    FULL record (the inverse re-adds byte-exactly); mutate carries the
    PRIOR field values (name/workplane), so the pure inverse is the op
    itself.

``{"op": "add_constraint", "sketch_id", "constraint": {...}}`` /
``{"op": "remove_constraint", "sketch_id", "c_id", "constraint"}`` /
``{"op": "mutate_constraint", "sketch_id", "c_id", "changes"}``
    Constraint edits (the parametric edit is the first-class op): mutate
    carries the PRIOR values of value/driven/refs/kind; undo granularity is
    per-constraint, never per-sketch.

``{"op": "add_junction", "sketch_id", "junction": {...}}`` /
``{"op": "remove_junction", "sketch_id", "junction_id", "junction"}`` /
``{"op": "mutate_junction", "sketch_id", "junction_id", "changes"}``
    Junction-map edits: identity (``junction_id``) is immutable and
    survives member changes (the record's whole point).

Every committed transaction appends one :class:`UndoGroup` whose entries
are the *reversed* journal — applying them in order undoes the
transaction. Undo itself re-applies those entries as a new committed
transaction (bumping ``doc_version``, per the monotonicity rule) and the
counter-ops it captures become the redo group.

Settings/sysvars are deliberately NOT part of this vocabulary (contracts
§2.5 undo-policy exception).
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
    # -- layers ----------------------------------------------------------
    if kind == "add_layer":
        return {"op": "remove_layer", "name": op["name"]}
    if kind == "remove_layer":
        inverse = {"op": "add_layer", "name": op["name"]}
        record = op.get("record")
        if record is not None:  # v2 payload; M1 bare ops replay with defaults
            inverse["props"] = {key: record[key] for key in record
                               if key != "name"}
        return inverse
    if kind == "mutate_layer":
        return {"op": "mutate_layer", "name": op["name"],
                "changes": dict(op["changes"])}
    # -- blocks ----------------------------------------------------------
    if kind == "add_block":
        return {"op": "remove_block", "name": op["name"]}
    if kind == "remove_block":
        record = op["record"]
        return {"op": "add_block", "name": record["name"],
                "base_point": record["base_point"],
                "handle": record["handle"],
                "entities": record["entities"]}
    if kind == "redefine_block":
        return {"op": "redefine_block", "name": op["name"],
                "new": dict(op["old"]), "old": dict(op["new"])}
    # -- layouts ----------------------------------------------------------
    if kind == "add_layout":
        return {"op": "remove_layout", "name": op["name"]}
    if kind == "remove_layout":
        record = op["record"]
        return {"op": "add_layout", "name": record["name"],
                "page_width": record["page_width"],
                "page_height": record["page_height"],
                "paper_units": record["paper_units"]}
    if kind == "rename_layout":
        return {"op": "rename_layout", "old": op["new"], "new": op["old"]}
    if kind == "reorder_layout":
        # the op's old_index is the PRE-move position: applying the op
        # again moves the layout back there
        return {"op": "reorder_layout", "name": op["name"],
                "old_index": op["old_index"]}
    # -- styles -------------------------------------------------------------
    if kind in ("add_text_style", "add_dim_style"):
        return {"op": kind.replace("add_", "remove_", 1), "name": op["name"]}
    if kind in ("remove_text_style", "remove_dim_style"):
        record = op["record"]
        inverse = {"op": kind.replace("remove_", "add_", 1),
                   "name": record["name"]}
        inverse["props"] = {key: record[key] for key in record
                            if key != "name"}
        return inverse
    if kind in ("mutate_text_style", "mutate_dim_style"):
        return {"op": kind, "name": op["name"], "changes": dict(op["changes"])}
    # -- sketches (bcdoc/3 — contract m3 §2) ------------------------------
    if kind == "add_sketch":
        return {"op": "remove_sketch", "sketch_id": op["sketch_id"]}
    if kind == "remove_sketch":
        inverse = {"op": "add_sketch", "sketch_id": op["sketch_id"]}
        record = op.get("record")
        if record is not None:  # full-payload ops carry the record
            inverse["record"] = dict(record)
        if "index" in op:  # position restoring (entity-add precedent)
            inverse["index"] = op["index"]
        return inverse
    if kind == "mutate_sketch":
        return {"op": "mutate_sketch", "sketch_id": op["sketch_id"],
                "changes": dict(op["changes"])}
    if kind == "add_constraint":
        return {"op": "remove_constraint", "sketch_id": op["sketch_id"],
                "c_id": op["constraint"]["c_id"]}
    if kind == "remove_constraint":
        inverse = {"op": "add_constraint", "sketch_id": op["sketch_id"]}
        record = op.get("constraint")
        if record is not None:  # full-payload ops carry the record
            inverse["constraint"] = dict(record)
        if "index" in op:  # position restoring (entity-add precedent)
            inverse["index"] = op["index"]
        return inverse
    if kind == "mutate_constraint":
        return {"op": "mutate_constraint", "sketch_id": op["sketch_id"],
                "c_id": op["c_id"], "changes": dict(op["changes"])}
    if kind == "add_junction":
        return {"op": "remove_junction", "sketch_id": op["sketch_id"],
                "junction_id": op["junction"]["junction_id"]}
    if kind == "remove_junction":
        inverse = {"op": "add_junction", "sketch_id": op["sketch_id"]}
        record = op.get("junction")
        if record is not None:  # full-payload ops carry the record
            inverse["junction"] = dict(record)
        if "index" in op:  # position restoring (entity-add precedent)
            inverse["index"] = op["index"]
        return inverse
    if kind == "mutate_junction":
        return {"op": "mutate_junction", "sketch_id": op["sketch_id"],
                "junction_id": op["junction_id"],
                "changes": dict(op["changes"])}
    raise ValueError(f"unknown journal op {op!r}")
