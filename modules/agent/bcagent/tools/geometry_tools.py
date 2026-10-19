"""``cad.geometry`` namespace — M1 subset: create / get / query / transform.

Implemented (contract §6.3; m1-module-contracts §8):

- ``cad.geometry.create``    — line|circle|arc (doc-edit · propose, transactional)
- ``cad.geometry.get``       — entity by id (— · read-only)
- ``cad.geometry.query``     — properties: ``length``, ``radius``, ``area``,
  ``start_angle``, ``end_angle`` as applicable (— · read-only)
- ``cad.geometry.transform`` — ops: ``move`` | ``rotate`` | ``scale``
  (doc-edit · propose, transactional)

NOT implemented at M1 (honest subset, NOT advertised): ``cad.geometry.edit``
(fillet/chamfer/trim/… — needs the M3 kernel, ADR-0002), ``cad.geometry.validate``,
and the ``mirror``/``offset``/``array`` transform ops of contract §6.3.

Subset decisions (contract ambiguities resolved here; recorded in the spike + worklog):

- ``create`` builds ONE entity per call (the contract §6.3 request is one
  ``type`` + one ``params``); the result arrays therefore carry one element,
  matching the contract's own JSON example.
- ``transform``/``rotate``: contract §6.3 says ``rotate {axis: point3/vec3, angle}``
  while contract §2 fixes angles as "degrees, CCW about +Z (or about ``normal``
  when given)". The M1 entity set is planar, so the subset implements rotation
  about +Z only: params ``{"angle": <deg>, "center"?: point3 (default origin)}``.
  An explicit ``axis`` argument is accepted ONLY when equal to ``[0, 0, 1]`;
  anything else is ``CAD_E_VALIDATION`` with a clear message (not silently
  reinterpreted).
- ``transform``/``scale``: non-uniform XY scaling of a circle/arc would produce an
  ellipse, which is not in the v0 entity set (m1-module-contracts §3.1) — that case
  returns ``CAD_E_UNSUPPORTED_ENTITY``; lines scale with any non-zero factors.
- ``query`` properties: ``length`` (line |p2−p1|; circle circumference 2πr; arc
  r·Δθ, degenerate start==end → 0), ``radius`` (circle/arc), ``area`` (circle only),
  ``start_angle``/``end_angle`` (arc only). Requested-but-inapplicable properties
  are OMITTED per the contract §6.3 rule ("unavailable → omitted, never faked").

Transactionality (contract §4): ``create`` and ``transform`` require
``base_doc_version``; the adapter opens ONE bcdoc transaction per call (one undo
step). Mid-tool failure rolls back via bcdoc — partial states are impossible by
construction. All geometry is in document units / WCS.
"""

from __future__ import annotations

import math

from ..contract import UnsupportedEntityError, ValidationError
from .base import (
    ToolContext,
    ToolSpec,
    entity_dict,
    get_entity,
    id_list,
    number,
    point3,
    require_args,
    require_str,
)

_KIND_FACTORIES = ("line", "circle", "arc")
_QUERY_PROPERTIES = ("length", "radius", "area", "start_angle", "end_angle")
_ROTATE_AXIS = (0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def _build_entity(entity_type: str, params):
    """Validate params and construct a bcdoc entity (id assigned by bcdoc)."""
    from bcdoc import entities as bcdoc_entities

    if not isinstance(params, dict):
        raise ValidationError(
            "params must be an object", details={"field": "params"}
        )
    if entity_type == "line":
        p1 = point3(require_args(params, "from"), "params.from")
        p2 = point3(require_args(params, "to"), "params.to")
        return bcdoc_entities.Line(p1=p1, p2=p2)
    if entity_type == "circle":
        center = point3(require_args(params, "center"), "params.center")
        radius = number(require_args(params, "radius"), "params.radius", positive=True)
        return bcdoc_entities.Circle(center=center, radius=radius)
    if entity_type == "arc":
        center = point3(require_args(params, "center"), "params.center")
        radius = number(require_args(params, "radius"), "params.radius", positive=True)
        start_angle = number(
            require_args(params, "start_angle"), "params.start_angle"
        )
        end_angle = number(require_args(params, "end_angle"), "params.end_angle")
        return bcdoc_entities.Arc(
            center=center,
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
        )
    raise ValidationError(
        f"unsupported entity type at M1: {entity_type!r} "
        f"(M1 supports: line, circle, arc)",
        details={"field": "type", "got": entity_type},
    )


def _geometry_create(ctx: ToolContext, args: dict) -> dict:
    entity_type = require_str(args, "type")
    if entity_type not in _KIND_FACTORIES:
        raise ValidationError(
            f"unsupported entity type at M1: {entity_type!r} "
            f"(M1 supports: line, circle, arc)",
            details={"field": "type", "got": entity_type},
        )
    params = require_args(args, "params")
    layer = args.get("layer")
    if layer is not None:
        if not isinstance(layer, str) or not layer.strip():
            raise ValidationError(
                "layer must be a non-empty string",
                details={"field": "layer", "got": layer},
            )
        if layer not in ctx.doc.layers:
            raise ValidationError(
                f"layer not found: {layer} (no auto-create at M1)",
                details={"field": "layer", "layer": layer},
            )
    entity = _build_entity(entity_type, params)
    if layer is not None:
        entity.layer = layer
    ctx.doc.add_entity(entity)
    return {"ids": [entity.id], "entities": [entity_dict(entity)]}


# ---------------------------------------------------------------------------
# get / query
# ---------------------------------------------------------------------------


def _geometry_get(ctx: ToolContext, args: dict) -> dict:
    entity_id = require_str(args, "id")
    entity = get_entity(ctx.doc, entity_id)
    return {"entity": entity_dict(entity)}


def _property_value(entity, prop: str):
    """Property value or None when not applicable to this kind (never faked)."""
    kind = entity.kind
    if prop == "length":
        if kind == "line":
            (x1, y1, _), (x2, y2, _) = entity.p1, entity.p2
            return math.hypot(x2 - x1, y2 - y1)
        if kind == "circle":
            return 2.0 * math.pi * float(entity.radius)
        if kind == "arc":
            if abs(entity.end_angle - entity.start_angle) < 1e-12:
                return 0.0
            sweep = math.radians((entity.end_angle - entity.start_angle) % 360.0)
            return float(entity.radius) * sweep
        return None
    if prop == "radius":
        return float(entity.radius) if kind in ("circle", "arc") else None
    if prop == "area":
        if kind == "circle":
            return math.pi * float(entity.radius) ** 2
        return None  # arc/line: no honest area at M1 (no segment math in v0)
    if prop == "start_angle":
        return float(entity.start_angle) if kind == "arc" else None
    if prop == "end_angle":
        return float(entity.end_angle) if kind == "arc" else None
    raise ValidationError(  # unknown property — validated before any id lookup
        f"unknown query property: {prop!r} (M1 supports: "
        f"{list(_QUERY_PROPERTIES)})",
        details={"field": "properties", "property": prop},
    )


def _geometry_query(ctx: ToolContext, args: dict) -> dict:
    ids = id_list(args)
    properties = args.get("properties")
    if not isinstance(properties, (list, tuple)) or not properties:
        raise ValidationError(
            "properties must be a non-empty array of property names",
            details={"field": "properties"},
        )
    for prop in properties:  # validate ALL properties first (fail fast)
        if not isinstance(prop, str) or prop not in _QUERY_PROPERTIES:
            raise ValidationError(
                f"unknown query property: {prop!r} (M1 supports: "
                f"{list(_QUERY_PROPERTIES)})",
                details={"field": "properties", "property": prop},
            )
    items = []
    for entity_id in ids:  # then resolve ids (ENTITY_NOT_FOUND wins over validation
        entity = get_entity(ctx.doc, entity_id)  # only for well-formed requests)
        computed = {}
        for prop in properties:
            value = _property_value(entity, prop)
            if value is not None:  # unavailable -> omitted, never faked
                computed[prop] = value
        items.append({"id": entity_id, "properties": computed})
    return {"items": items}


# ---------------------------------------------------------------------------
# transform (move | rotate | scale)
#
# Per-entity math lives in module-level functions (_move_entity/_rotate_entity/
# _scale_entity) so transaction-atomicity tests can monkeypatch them to induce a
# mid-batch failure. All mutations go through ``doc.update_entity`` — the ONLY
# journaled mutation path (bcdoc: direct attribute writes bypass the undo
# journal and rollback; m1 contracts §3.1 "Document APIs are the only legal
# mutation path") — inside the transaction the adapter opens (except where a
# tool delegates transactions to bcio, see io_tools).
# ---------------------------------------------------------------------------


def _move_entity(doc, entity, delta) -> None:
    if entity.kind == "line":
        doc.update_entity(
            entity.id,
            p1=(entity.p1[0] + delta[0], entity.p1[1] + delta[1],
                entity.p1[2] + delta[2]),
            p2=(entity.p2[0] + delta[0], entity.p2[1] + delta[1],
                entity.p2[2] + delta[2]),
        )
    else:
        doc.update_entity(
            entity.id,
            center=(entity.center[0] + delta[0], entity.center[1] + delta[1],
                    entity.center[2] + delta[2]),
        )


def _rotate_entity(doc, entity, center, radians_) -> None:
    cos_t, sin_t = math.cos(radians_), math.sin(radians_)

    def rot(point):
        dx, dy = point[0] - center[0], point[1] - center[1]
        return (center[0] + dx * cos_t - dy * sin_t,
                center[1] + dx * sin_t + dy * cos_t,
                point[2])

    if entity.kind == "line":
        doc.update_entity(entity.id, p1=rot(entity.p1), p2=rot(entity.p2))
    else:
        doc.update_entity(entity.id, center=rot(entity.center))  # angles unchanged: rotation about +Z


def _scale_entity(doc, entity, about, factors) -> None:
    sx, sy, sz = factors

    def scale_point(point):
        return (about[0] + (point[0] - about[0]) * sx,
                about[1] + (point[1] - about[1]) * sy,
                about[2] + (point[2] - about[2]) * sz)

    if entity.kind == "line":
        doc.update_entity(entity.id, p1=scale_point(entity.p1),
                          p2=scale_point(entity.p2))
    else:
        if sx != sy:
            # circle/arc + non-uniform XY scale == ellipse (not in v0 entity set)
            raise UnsupportedEntityError(
                "non-uniform XY scale is not valid for a circle/arc at M1: the "
                "result would be an ellipse, which is not in the v0 entity set",
                details={"kind": entity.kind, "id": entity.id, "factors": list(factors)},
            )
        doc.update_entity(entity.id, center=scale_point(entity.center),
                          radius=float(entity.radius) * sx)


def _geometry_transform(ctx: ToolContext, args: dict) -> dict:
    ids = id_list(args)
    op = require_str(args, "op")
    params = require_args(args, "params")
    if not isinstance(params, dict):
        raise ValidationError(
            "params must be an object", details={"field": "params"}
        )
    # resolve every id up front (nothing applied on unknown ids)
    entities = [get_entity(ctx.doc, entity_id) for entity_id in ids]
    if op == "move":
        delta = point3(require_args(params, "delta"), "params.delta")
        for entity in entities:
            _move_entity(ctx.doc, entity, delta)
    elif op == "rotate":
        if "axis" in params:
            axis = point3(params["axis"], "params.axis")
            if tuple(axis) != _ROTATE_AXIS:
                raise ValidationError(
                    "M1 subset: rotation axis must be +Z ([0, 0, 1]); angles are "
                    "degrees CCW about +Z (contract §2)",
                    details={"field": "params.axis", "got": list(axis)},
                )
        angle = number(require_args(params, "angle"), "params.angle")
        center = point3(params.get("center", (0.0, 0.0, 0.0)), "params.center")
        radians_ = math.radians(angle)
        for entity in entities:
            _rotate_entity(ctx.doc, entity, center, radians_)
    elif op == "scale":
        about = point3(params.get("about", (0.0, 0.0, 0.0)), "params.about")
        factors = require_args(params, "factors")
        if not isinstance(factors, (list, tuple)) or len(factors) != 3:
            raise ValidationError(
                "params.factors must be [sx, sy, sz]",
                details={"field": "params.factors"},
            )
        factors = tuple(
            number(f, "params.factors entry", nonzero=True) for f in factors
        )
        # circles/arcs need uniform XY (checked per entity in _scale_entity)
        for entity in entities:
            _scale_entity(ctx.doc, entity, about, factors)
    else:
        raise ValidationError(
            f"unsupported transform op at M1: {op!r} (M1 supports: move, rotate, "
            f"scale; mirror/offset/array are contract v1 ops planned with the "
            f"kernel)",
            details={"field": "op", "got": op},
        )
    refreshed = [entity_dict(get_entity(ctx.doc, e.id)) for e in entities]
    return {"ids": ids, "entities": refreshed}


TOOL_SPECS = [
    ToolSpec(
        tool_id="cad.geometry.create",
        run=_geometry_create,
        transactional=True,
        min_mode="propose",
        classes=("doc-edit",),
    ),
    ToolSpec(tool_id="cad.geometry.get", run=_geometry_get),
    ToolSpec(tool_id="cad.geometry.query", run=_geometry_query),
    ToolSpec(
        tool_id="cad.geometry.transform",
        run=_geometry_transform,
        transactional=True,
        min_mode="propose",
        classes=("doc-edit",),
    ),
]
