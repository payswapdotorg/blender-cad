"""Stable serialization for documents — schema ``bcdoc/2`` (contract
m2-module-contracts.md §2.7; M1 §3.5 amended by §14).

``serialize()`` ALWAYS writes ``bcdoc/2`` with keys in the pinned order:
schema, name, units, doc_version, next_handle, settings, layers,
current_layer, text_styles, dim_styles, blocks, layouts, entities, undo,
redo, selection. ``load`` accepts BOTH ``bcdoc/1`` (deterministic
upgrade: layer names -> default records, settings defaults, entities get
``lineweight=None`` + ``space="MODEL"``, no blocks/layouts/styles) and
``bcdoc/2``; anything else raises :class:`bcdoc.errors.SerializationError`.

Byte-stability rules:

- the JSON object is constructed in a FIXED key order and dumped WITHOUT
  ``sort_keys`` (the entities list preserves insertion order; only the
  inner dicts are constructed in fixed key order);
- floats round-trip exactly through ``json`` (repr-based shortest form);
- selection ids are sorted (frozensets have arbitrary iteration order);
- the undo journal + redo stack are serialized, so a saved/reloaded
  document keeps undo/redo depth intact — including the v2 op kinds
  (v1 journals with bare ``add_layer`` ops replay tolerantly: missing
  payloads -> default records).
"""

from __future__ import annotations

import json

from . import errors
from .blocks import BlockDefinition
from .entities import ENTITY_CLASSES, GEOMETRY_FIELDS
from .layers import LayerRecord
from .layouts import LayoutRecord
from .settings import Settings
from .styles import DimStyleRecord, TextStyleRecord
from .undo import UndoGroup

SCHEMA_V1 = "bcdoc/1"
SCHEMA_V2 = "bcdoc/2"
#: What :func:`to_json` writes (loads accept V1 and V2).
SCHEMA = SCHEMA_V2

_OP_KINDS = {
    "add", "remove", "mutate",
    "add_layer", "remove_layer", "mutate_layer",
    "add_block", "remove_block", "redefine_block",
    "add_layout", "remove_layout", "rename_layout", "reorder_layout",
    "add_text_style", "remove_text_style", "mutate_text_style",
    "add_dim_style", "remove_dim_style", "mutate_dim_style",
}

_V2_REQUIRED_KEYS = (
    "name", "units", "doc_version", "next_handle", "settings", "layers",
    "current_layer", "text_styles", "dim_styles", "blocks", "layouts",
    "entities", "undo", "redo", "selection",
)


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------

def entity_to_dict(entity) -> dict:
    """Fixed-order entity dict (contract §2.7 field set + geometry).

    Delegates to :meth:`bcdoc.entities.Entity.to_json_dict` — the single
    field-order/precision source shared by document records and journal
    snapshots (byte-stability rule)."""
    return entity.to_json_dict()


def entity_from_dict(data: dict):
    """Rebuild an entity from its dict form (per-kind coercer validation).

    Tolerant reads for the v1 upgrade path: ``lineweight`` and ``space``
    are optional (defaults None / "MODEL"); every geometry field is
    required. Raises :class:`errors.SerializationError` on unknown kinds,
    missing fields or malformed values."""
    if not isinstance(data, dict):
        raise errors.SerializationError(
            f"entity record must be a dict, got {type(data).__name__}")
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
    if not isinstance(layer, str) or not isinstance(linetype, str):
        raise errors.SerializationError("entity layer/linetype must be strings")
    # v1 records carry no lineweight/space (tolerant upgrade defaults).
    lineweight = data.get("lineweight")
    if lineweight is not None:
        if isinstance(lineweight, bool) or not isinstance(lineweight, (int, float)):
            raise errors.SerializationError(
                f"entity lineweight must be None or a number, got {lineweight!r}")
        if float(lineweight) < 0:
            raise errors.SerializationError(
                f"entity lineweight must be >= 0, got {lineweight!r}")
    space = data.get("space", "MODEL")
    if not isinstance(space, str):
        raise errors.SerializationError(f"entity space must be a string, got {space!r}")

    geometry = []
    for field in GEOMETRY_FIELDS[kind]:
        if field not in data:
            raise errors.SerializationError(
                f"{kind} record missing geometry field {field!r}")
        geometry.append(data[field])
    try:
        entity = cls(*geometry)
    except (TypeError, ValueError) as exc:
        raise errors.SerializationError(
            f"malformed geometry in {kind} record: {exc}") from None

    # Replace the fresh uuid with the stored identity.
    entity.id = eid
    entity.handle = handle
    entity.layer = str(layer)
    entity.color = color
    entity.linetype = str(linetype)
    entity.lineweight = None if lineweight is None else float(lineweight)
    entity.space = str(space)
    return entity


# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------

def to_json(doc) -> str:
    """Serialize ``doc`` to a stable ``bcdoc/2`` JSON string."""
    data = {
        "schema": SCHEMA,
        "name": doc.name,
        "units": dict(doc.units),
        "doc_version": int(doc.doc_version),
        "next_handle": int(doc.next_handle),
        "settings": doc.settings.to_json(),
        "layers": [record.to_dict() for record in doc._layer_table._records],
        "current_layer": doc.current_layer,
        "text_styles": [record.to_dict()
                        for record in doc._text_styles._records.values()],
        "dim_styles": [record.to_dict()
                       for record in doc._dim_styles._records.values()],
        "blocks": [definition.to_dict()
                   for definition in doc._block_table._blocks.values()],
        "layouts": [record.to_dict() for record in doc._layout_table._records],
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
    """Parse + structurally validate a ``bcdoc/1`` or ``bcdoc/2`` JSON
    document (v1 payloads are deterministically upgraded in place).

    Raises :class:`errors.SerializationError` for anything that is not a
    valid payload (wrong schema string, bad JSON, missing keys, malformed
    entities/journal/selection/tables)."""
    if not isinstance(text, str):
        raise errors.SerializationError("load() expects a string")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise errors.SerializationError(f"not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise errors.SerializationError("document payload must be a JSON object")
    schema = data.get("schema")
    if schema == SCHEMA_V1:
        _upgrade_v1(data)
    elif schema != SCHEMA_V2:
        raise errors.SerializationError(
            f"unsupported schema {schema!r} (expected {SCHEMA_V2!r} or {SCHEMA_V1!r})"
        )

    for key in _V2_REQUIRED_KEYS:
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

    # -- settings ---------------------------------------------------------
    settings = Settings()
    try:
        settings.from_json(data["settings"])
    except errors.BcdocError as exc:
        raise errors.SerializationError(f"invalid 'settings': {exc}") from None
    if not isinstance(data["current_layer"], str):
        raise errors.SerializationError("'current_layer' must be a string")

    # -- layers ------------------------------------------------------------
    layers = data["layers"]
    if not isinstance(layers, list):
        raise errors.SerializationError("'layers' must be a list")
    records = []
    for item in layers:
        try:
            records.append(LayerRecord.from_dict(item))
        except (TypeError, ValueError) as exc:
            raise errors.SerializationError(f"invalid layer record: {exc}") from None
    names = [record.name for record in records]
    if len(set(names)) != len(names):
        raise errors.SerializationError("'layers' contains duplicate names")

    # -- styles --------------------------------------------------------------
    text_styles = _style_records(data["text_styles"], TextStyleRecord,
                                 "text_styles")
    dim_styles = _style_records(data["dim_styles"], DimStyleRecord,
                                "dim_styles")

    # -- layouts -------------------------------------------------------------
    layouts = data["layouts"]
    if not isinstance(layouts, list):
        raise errors.SerializationError("'layouts' must be a list")
    layout_records = []
    for item in layouts:
        try:
            layout_records.append(LayoutRecord.from_dict(item))
        except (TypeError, ValueError) as exc:
            raise errors.SerializationError(f"invalid layout record: {exc}") from None
    layout_names = [record.name for record in layout_records]
    if len(set(layout_names)) != len(layout_names):
        raise errors.SerializationError("'layouts' contains duplicate names")

    # -- entities --------------------------------------------------------------
    if not isinstance(data["entities"], list):
        raise errors.SerializationError("'entities' must be a list")
    entities = [entity_from_dict(rec) for rec in data["entities"]]
    ids = [e.id for e in entities]
    if len(set(ids)) != len(ids):
        raise errors.SerializationError("duplicate entity id in 'entities'")
    handles = [e.handle for e in entities]
    if len(set(handles)) != len(handles):
        raise errors.SerializationError("duplicate entity handle in 'entities'")

    # -- blocks -------------------------------------------------------------
    blocks = data["blocks"]
    if not isinstance(blocks, list):
        raise errors.SerializationError("'blocks' must be a list")
    definitions = []
    seen_blocks = set()
    for item in blocks:
        definition = _block_definition_from_dict(item, handles)
        if definition.name in seen_blocks:
            raise errors.SerializationError(
                f"duplicate block name {definition.name!r} in 'blocks'")
        seen_blocks.add(definition.name)
        definitions.append(definition)
        handles = handles + [definition.handle]

    # -- journal stacks --------------------------------------------------------
    for stackkey in ("undo", "redo"):
        stack = data[stackkey]
        if not isinstance(stack, list):
            raise errors.SerializationError(f"{stackkey!r} must be a list")
        for group in stack:
            _validate_group(group, stackkey)

    # -- selection ------------------------------------------------------------
    selection = data["selection"]
    if not isinstance(selection, dict) or "ids" not in selection or "epoch" not in selection:
        raise errors.SerializationError("'selection' must be {ids, epoch}")
    if not isinstance(selection["ids"], list) or any(not isinstance(i, str) for i in selection["ids"]):
        raise errors.SerializationError("selection 'ids' must be a list of strings")
    if not isinstance(selection["epoch"], int) or isinstance(selection["epoch"], bool) or selection["epoch"] < 0:
        raise errors.SerializationError("selection 'epoch' must be an int >= 0")

    # Replace dict forms with constructed objects for the caller.
    data["__settings__"] = settings
    data["__layers__"] = records
    data["__text_styles__"] = text_styles
    data["__dim_styles__"] = dim_styles
    data["__layouts__"] = layout_records
    data["__blocks__"] = definitions
    data["__entities__"] = entities
    data["__undo__"] = [UndoGroup.from_dict(g) for g in data["undo"]]
    data["__redo__"] = [UndoGroup.from_dict(g) for g in data["redo"]]
    return data


def _style_records(payload, record_cls, key: str) -> list:
    if not isinstance(payload, list):
        raise errors.SerializationError(f"{key!r} must be a list")
    records = []
    for item in payload:
        try:
            records.append(record_cls.from_dict(item))
        except (TypeError, ValueError) as exc:
            raise errors.SerializationError(
                f"invalid style record in {key!r}: {exc}") from None
    names = [record.name for record in records]
    if len(set(names)) != len(names):
        raise errors.SerializationError(f"{key!r} contains duplicate names")
    return records


def _block_definition_from_dict(item, entity_handles: list) -> BlockDefinition:
    """Rebuild one block definition (members built + space stripped to
    MODEL — exactly the shape :meth:`BlockDefinition.to_dict` writes)."""
    if not isinstance(item, dict):
        raise errors.SerializationError(f"block record must be a dict, got {item!r}")
    for key in ("name", "base_point", "handle", "entities"):
        if key not in item:
            raise errors.SerializationError(f"block record missing key {key!r}")
    if not isinstance(item["name"], str) or not item["name"]:
        raise errors.SerializationError("block name must be a non-empty string")
    handle = item["handle"]
    if not isinstance(handle, int) or isinstance(handle, bool) or handle < 1:
        raise errors.SerializationError(
            f"block handle must be an int >= 1, got {handle!r}")
    if handle in entity_handles:
        raise errors.SerializationError(
            f"block handle {handle} collides with another handle in the "
            "document handle space")
    if not isinstance(item["entities"], list):
        raise errors.SerializationError("block 'entities' must be a list")
    members = []
    for record in item["entities"]:
        member = entity_from_dict(record)
        member.space = "MODEL"
        members.append(member)
    try:
        return BlockDefinition(item["name"], item["base_point"], handle,
                               members)
    except (TypeError, ValueError) as exc:
        raise errors.SerializationError(f"malformed block record: {exc}") from None


def _upgrade_v1(data: dict) -> None:
    """Deterministically upgrade a parsed ``bcdoc/1`` payload to the v2
    shape (in place). Layer names become default records; settings take
    the registry defaults; entities/journals are handled by the tolerant
    readers (``entity_from_dict`` defaults for lineweight/space, journal
    layer ops replay with default props)."""
    layers = data.get("layers")
    if not isinstance(layers, list) or any(not isinstance(n, str) for n in layers):
        # keep the M1 validation error for malformed v1 layer lists
        raise errors.SerializationError("'layers' must be a list of strings")
    if len(set(layers)) != len(layers):
        raise errors.SerializationError("'layers' contains duplicate names")
    data["layers"] = [{"name": name} for name in layers]
    data["settings"] = {}          # registry defaults
    data["current_layer"] = "0"
    data["text_styles"] = []       # -> Standard default (tolerant insert)
    data["dim_styles"] = []
    data["blocks"] = []
    data["layouts"] = []


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
        elif kind in ("add_layer", "remove_layer",
                      "add_text_style", "remove_text_style",
                      "add_dim_style", "remove_dim_style"):
            if "name" not in op:
                raise errors.SerializationError(
                    f"journal {kind} op missing 'name' in {where}: {op!r}")
            if "props" in op and not isinstance(op["props"], dict):
                raise errors.SerializationError(
                    f"journal {kind} op 'props' must be a dict in {where}")
            if "record" in op and not isinstance(op["record"], dict):
                raise errors.SerializationError(
                    f"journal {kind} op 'record' must be a dict in {where}")
        elif kind in ("mutate_layer", "mutate_text_style", "mutate_dim_style"):
            if "name" not in op or not isinstance(op.get("changes"), dict):
                raise errors.SerializationError(
                    f"journal {kind} op needs 'name' + 'changes' in {where}: {op!r}")
        elif kind == "add_block":
            for key in ("name", "base_point", "handle", "entities"):
                if key not in op:
                    raise errors.SerializationError(
                        f"journal add_block op missing {key!r} in {where}: {op!r}")
            if not isinstance(op["entities"], list):
                raise errors.SerializationError(
                    f"journal add_block op 'entities' must be a list in {where}")
        elif kind == "remove_block":
            if "name" not in op:
                raise errors.SerializationError(
                    f"journal remove_block op missing 'name' in {where}: {op!r}")
            if "record" in op and not isinstance(op["record"], dict):
                raise errors.SerializationError(
                    f"journal remove_block op 'record' must be a dict in {where}")
        elif kind == "redefine_block":
            if "name" not in op:
                raise errors.SerializationError(
                    f"journal redefine_block op missing 'name' in {where}")
            for key in ("new", "old"):
                if key not in op or not isinstance(op[key], dict):
                    raise errors.SerializationError(
                        f"journal redefine_block op needs dict {key!r} in {where}")
        elif kind == "add_layout":
            if "name" not in op:
                raise errors.SerializationError(
                    f"journal add_layout op missing 'name' in {where}: {op!r}")
        elif kind == "remove_layout":
            if "name" not in op:
                raise errors.SerializationError(
                    f"journal remove_layout op missing 'name' in {where}: {op!r}")
            if "record" in op and not isinstance(op["record"], dict):
                raise errors.SerializationError(
                    f"journal remove_layout op 'record' must be a dict in {where}")
        elif kind == "rename_layout":
            if "old" not in op or "new" not in op:
                raise errors.SerializationError(
                    f"journal rename_layout op needs 'old' + 'new' in {where}")
        elif kind == "reorder_layout":
            if "name" not in op or not isinstance(op.get("old_index"), int) \
                    or isinstance(op.get("old_index"), bool):
                raise errors.SerializationError(
                    f"journal reorder_layout op needs 'name' + int 'old_index' "
                    f"in {where}")
