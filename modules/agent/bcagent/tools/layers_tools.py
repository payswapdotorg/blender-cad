"""``cad.layers`` namespace — M2 subset: full layer table + property writes.

Implemented (contract §6.5; m2-module-contracts §8):

- ``cad.layers.list`` — the full layer table: names (alphabetical, per contract
  §6.5), per-layer state (on/frozen/locked/plot from the bcdoc records), color
  (ACI), linetype name, lineweight (mm or None), current flag (CLAYER) and
  entity counts (— · read-only, paginated per contract §2).
- ``cad.layers.set_props`` — set per-layer properties inside one transaction
  (— · transactional, ``propose``/``approve``/``autonomous`` gated, class
  ``doc-edit``; accepts color/linetype/lineweight/on/frozen/locked/plot).

NOT implemented at M2 (honest subset, NOT advertised): ``cad.layers.create``,
``cad.layers.set_state``, ``cad.layers.move_entities_to`` — layer-table writes
beyond property mutation and layer creation remain M5+ surface (the
``LAYER`` command and the shell panel own the user-facing paths at M2).

Honesty notes (never faked):

- ``color``, ``linetype`` and ``lineweight`` come from the bcdoc records
  (v2); when a record carries the default the wire reports the default —
  contract §6.3 "unavailable → omitted" no longer applies because v2 has
  the data.
- ``entity_count`` is computed by a linear scan over ``doc.entities()`` —
  O(n) per call; fine at M2 scale, revisited when layers get an index.
"""

from __future__ import annotations

from .base import ToolContext, ToolSpec, paginate, require_args
from ..contract import EntityNotFoundError, ValidationError


#: set_props keys -> wire names (bcdoc record attribute == wire name here)
_PROP_KEYS = ("color", "linetype", "lineweight", "on", "frozen", "locked", "plot")


def _layers_list(ctx: ToolContext, args: dict) -> dict:
    doc = ctx.doc
    counts: dict[str, int] = {name: 0 for name in doc.layers}
    for entity in doc.entities():
        counts[entity.layer] = counts.get(entity.layer, 0) + 1
    names = sorted(counts)  # alphabetical per contract §6.5
    current = doc.current_layer
    page, next_cursor = paginate(args, names)
    layers = []
    for name in page:
        record = doc.layers.get(name)
        state = {
            "on": bool(record.on),
            "frozen": bool(record.frozen),
            "locked": bool(record.locked),
            "plot": bool(record.plot),
        }
        entry = {
            "name": name,
            "state": state,
            "color": int(record.color),
            "linetype": str(record.linetype),
            "lineweight": None if record.lineweight is None else float(record.lineweight),
            "current": name == current,
            "entity_count": counts[name],
        }
        layers.append(entry)
    result = {"layers": layers, "names": page}
    if next_cursor is not None:
        result["next_cursor"] = next_cursor
    return result


def _layers_set_props(ctx: ToolContext, args: dict) -> dict:
    """The adapter opens the single transaction (base.ToolSpec rule);
    this body must NOT open its own."""
    doc = ctx.doc
    names = require_args(args, "names")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValidationError("names must be a list of layer name strings")
    props = require_args(args, "props")
    if not isinstance(props, dict) or not props:
        raise ValidationError("props must be a non-empty object")
    unknown = sorted(set(props) - set(_PROP_KEYS))
    if unknown:
        raise ValidationError(
            f"unknown layer property(ies): {', '.join(unknown)} "
            f"(supported: {', '.join(_PROP_KEYS)})",
            details={"field": "props", "unknown": unknown},
        )
    # validate targets before any mutation
    missing = [n for n in names if doc.layers.get(n) is None]
    if missing:
        raise EntityNotFoundError(
            f"layer(s) not found: {', '.join(missing)}",
            details={"layers": missing},
        )
    for key, value in props.items():
        if key == "color":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 255:
                raise ValidationError(
                    f"color must be an ACI int 1..255, got {value!r}",
                    details={"field": "color"},
                )
        elif key == "linetype":
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    f"linetype must be a non-empty string, got {value!r}",
                    details={"field": "linetype"},
                )
        elif key == "lineweight":
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or float(value) < 0
            ):
                raise ValidationError(
                    f"lineweight must be a non-negative number or null, got {value!r}",
                    details={"field": "lineweight"},
                )
        else:  # on/frozen/locked/plot
            if not isinstance(value, bool):
                raise ValidationError(
                    f"{key} must be a boolean, got {value!r}",
                    details={"field": key},
                )
    for name in names:
        doc.layers.set_props(name, **dict(props))
    return {
        "layers": list(names),
        "applied": dict(props),
    }


TOOL_SPECS = [
    ToolSpec(tool_id="cad.layers.list", run=_layers_list),
    ToolSpec(
        tool_id="cad.layers.set_props",
        run=_layers_set_props,
        transactional=True,
        min_mode="propose",
        classes=("doc-edit",),
        version_added="1.1-m2",
    ),
]
