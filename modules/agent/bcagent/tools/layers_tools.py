"""``cad.layers`` namespace — M1 subset: read-only listing.

Implemented (contract §6.5; m1-module-contracts §8):

- ``cad.layers.list`` — layer names (alphabetical, per contract §6.5) with
  entity counts (— · read-only, paginated per contract §2)

NOT implemented at M1 (honest subset, NOT advertised): ``cad.layers.create``,
``cad.layers.set_state``, ``cad.layers.set_properties``,
``cad.layers.move_entities_to`` — bcdoc v0 carries layer NAMES only
(m1-module-contracts §3.2: ``layers: list[str]``, layer management is M2).

Subset decisions (never faked):

- ``state``: v0 has no visibility/freeze/lock machinery, so every layer reports
  ``{"on": true, "frozen": false, "locked": false}`` — nothing is hidden, frozen or
  locked in v0 and entities on all layers render. ``color``, ``linetype`` and
  ``lineweight`` are OMITTED (v0 has no per-layer properties; omitting beats
  inventing — contract §6.3 "unavailable → omitted, never faked" applied to
  layer metadata).
- ``entity_count`` is computed by a linear scan over ``doc.entities()`` — O(n)
  per call; fine at M1 scale, revisited when layers get an index at M2.
"""

from __future__ import annotations

from .base import ToolContext, ToolSpec, paginate


def _layers_list(ctx: ToolContext, args: dict) -> dict:
    doc = ctx.doc
    counts: dict[str, int] = {name: 0 for name in doc.layers}
    for entity in doc.entities():
        counts[entity.layer] = counts.get(entity.layer, 0) + 1
    names = sorted(counts)  # alphabetical per contract §6.5
    page, next_cursor = paginate(args, names)
    layers = [
        {
            "name": name,
            "state": {"on": True, "frozen": False, "locked": False},
            "entity_count": counts[name],
        }
        for name in page
    ]
    result = {"layers": layers, "names": page}
    if next_cursor is not None:
        result["next_cursor"] = next_cursor
    return result


TOOL_SPECS = [
    ToolSpec(tool_id="cad.layers.list", run=_layers_list),
]
