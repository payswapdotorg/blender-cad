"""Stable serialization for documents — schema ``bcdoc/1`` (contract §3.5).

Byte-stability rules:

- the JSON object is constructed in a FIXED key order and dumped WITHOUT
  ``sort_keys`` (the entities list preserves insertion order; only the
  inner dicts are constructed in fixed key order);
- floats round-trip exactly through ``json`` (repr-based shortest form);
- selection ids are sorted (frozensets have arbitrary iteration order);
- the undo journal + redo stack are serialized, so a saved/reloaded
  document keeps undo/redo depth intact.

``Document.load`` accepts EXACTLY schema ``bcdoc/1``; anything else
(including newer/unknown schemas and malformed JSON) raises
:class:`bcdoc.errors.SerializationError`.
"""

from __future__ import annotations

import json

from . import errors
from .entities import ENTITY_CLASSES
from .undo import UndoGroup

SCHEMA = "bcdoc/1"

_OP_KINDS = {"add", "remove", "mutate", "add_layer", "remove_layer"}


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------

def entity_to_dict(entity) -> dict:
    """Fixed-order entity dict (contract §3.5 field set + geometry).

    Delegates to :meth:`bcdoc.entities.Entity.to_json_dict` — the single
    field-order/precision source shared by document records and journal
    snapshots (byte-stability rule)."""
    return entity.to_json_dict()


def entity_from_dict(data: dict):
    """Rebuild an entity from its dict form.

    Raises :class:`errors.SerializationError` on unknown kinds, missing
    fields or malformed values."""
    if not isinstance(data, dict):
        raise errors.SerializationError(f"entity record must be a dict, got {type(data).__name__}")
    kind = data.get("kind")
    cls = ENTITY_CLASSES.get(kind)
    if cls is None:
        raise errors.SerializationError(f"unknown entity kind {kind!r}")
    try:
        eid = data["id"]
        handle = data["handle"]
        layer = data["layer"]
        color = data["color"]
        linetype = data["linetype"]
    except KeyError as exc:
        raise errors.SerializationError(f"entity record missing field {exc}") from None
    if not isinstance(eid, str) or not eid:
        raise errors.SerializationError("entity id must be a non-empty string")
    if not isinstance(handle, int) or isinstance(handle, bool) or handle < 0:
        raise errors.SerializationError(f"entity handle must be an int >= 0, got {handle!r}")
    if color is not None and (not isinstance(color, int) or isinstance(color, bool) or color < 0):
        raise errors.SerializationError(f"entity color must be None or a non-negative int, got {color!r}")

    try:
        if kind == "line":
            entity = cls(data["p1"], data["p2"])
        elif kind == "circle":
            entity = cls(data["center"], data["radius"])
        else:  # arc
            entity = cls(
                data["center"], data["radius"],
                data["start_angle"], data["end_angle"],
            )
    except KeyError as exc:
        raise errors.SerializationError(f"{kind} record missing geometry field {exc}") from None
    except ValueError as exc:
        raise errors.SerializationError(f"malformed geometry in {kind} record: {exc}") from None

    # Replace the fresh uuid with the stored identity.
    entity.id = eid
    entity.handle = handle
    entity.layer = str(layer)
    entity.color = color
    entity.linetype = str(linetype)
    return entity


# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------

def to_json(doc) -> str:
    """Serialize ``doc`` to a stable ``bcdoc/1`` JSON string."""
    data = {
        "schema": SCHEMA,
        "name": doc.name,
        "units": dict(doc.units),
        "doc_version": int(doc.doc_version),
        "next_handle": int(doc.next_handle),
        "layers": list(doc.layers),
        "entities": [entity_to_dict(e) for e in doc.entities()],
        "undo": [g.to_dict() for g in doc.undo_groups()],
        "redo": [g.to_dict() for g in doc.redo_groups()],
        "selection": {
            "ids": sorted(doc.selection.ids),
            "epoch": int(doc.selection.epoch),
        },
    }
    return json.dumps(data, ensure_ascii=True)


def parse(text: str) -> dict:
    """Parse + structurally validate a ``bcdoc/1`` JSON document.

    Raises :class:`errors.SerializationError` for anything that is not a
    valid ``bcdoc/1`` payload (wrong schema string, bad JSON, missing keys,
    malformed entities/journal/selection)."""
    if not isinstance(text, str):
        raise errors.SerializationError("load() expects a string")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise errors.SerializationError(f"not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise errors.SerializationError("document payload must be a JSON object")
    if data.get("schema") != SCHEMA:
        raise errors.SerializationError(
            f"unsupported schema {data.get('schema')!r} (expected {SCHEMA!r})"
        )

    required = ("name", "units", "doc_version", "next_handle", "layers",
                "entities", "undo", "redo", "selection")
    for key in required:
        if key not in data:
            raise errors.SerializationError(f"document payload missing key {key!r}")

    if not isinstance(data["name"], str):
        raise errors.SerializationError("'name' must be a string")
    if not isinstance(data["units"], dict):
        raise errors.SerializationError("'units' must be an object")
    for intkey in ("doc_version", "next_handle"):
        value = data[intkey]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise errors.SerializationError(f"{intkey!r} must be an int >= 0")

    layers = data["layers"]
    if not isinstance(layers, list) or any(not isinstance(n, str) for n in layers):
        raise errors.SerializationError("'layers' must be a list of strings")
    if len(set(layers)) != len(layers):
        raise errors.SerializationError("'layers' contains duplicate names")

    if not isinstance(data["entities"], list):
        raise errors.SerializationError("'entities' must be a list")
    entities = [entity_from_dict(rec) for rec in data["entities"]]
    ids = [e.id for e in entities]
    if len(set(ids)) != len(ids):
        raise errors.SerializationError("duplicate entity id in 'entities'")
    handles = [e.handle for e in entities]
    if len(set(handles)) != len(handles):
        raise errors.SerializationError("duplicate entity handle in 'entities'")

    for stackkey in ("undo", "redo"):
        stack = data[stackkey]
        if not isinstance(stack, list):
            raise errors.SerializationError(f"{stackkey!r} must be a list")
        for group in stack:
            _validate_group(group, stackkey)

    selection = data["selection"]
    if not isinstance(selection, dict) or "ids" not in selection or "epoch" not in selection:
        raise errors.SerializationError("'selection' must be {ids, epoch}")
    if not isinstance(selection["ids"], list) or any(not isinstance(i, str) for i in selection["ids"]):
        raise errors.SerializationError("selection 'ids' must be a list of strings")
    if not isinstance(selection["epoch"], int) or isinstance(selection["epoch"], bool) or selection["epoch"] < 0:
        raise errors.SerializationError("selection 'epoch' must be an int >= 0")

    # Replace entity dicts with constructed entities for the caller.
    data["__entities__"] = entities
    data["__undo__"] = [UndoGroup.from_dict(g) for g in data["undo"]]
    data["__redo__"] = [UndoGroup.from_dict(g) for g in data["redo"]]
    return data


def _validate_group(group, where: str) -> None:
    if not isinstance(group, dict):
        raise errors.SerializationError(f"{where} groups must be dicts")
    for key in ("label", "doc_version", "entries"):
        if key not in group:
            raise errors.SerializationError(f"{where} group missing {key!r}")
    if not isinstance(group["entries"], list):
        raise errors.SerializationError(f"{where} group 'entries' must be a list")
    for op in group["entries"]:
        if not isinstance(op, dict) or op.get("op") not in _OP_KINDS:
            raise errors.SerializationError(f"unknown journal op in {where}: {op!r}")
        kind = op["op"]
        if kind == "add":
            # add ops address the entity via its embedded record (the id
            # lives INSIDE op["entity"], not at the top level — this is the
            # exact shape `serialize()` emits for undo/redo groups)
            record = op.get("entity")
            if not isinstance(record, dict) or "id" not in record or "kind" not in record:
                raise errors.SerializationError(
                    f"journal add op missing 'entity' record in {where}: {op!r}"
                )
        elif kind in ("remove", "mutate"):
            if "id" not in op:
                raise errors.SerializationError(
                    f"journal op missing 'id' in {where}: {op!r}"
                )
            if kind == "mutate" and not isinstance(op.get("changes"), dict):
                raise errors.SerializationError("journal mutate op missing 'changes'")
        elif "name" not in op:  # add_layer / remove_layer
            raise errors.SerializationError(f"journal layer op missing 'name' in {where}: {op!r}")
