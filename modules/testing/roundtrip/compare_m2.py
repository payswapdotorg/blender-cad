"""Round-trip compare engine for the M2 kind set (task m2-2d).

Extends the M1 compare rule (kind + handle + geometry) to all 13 kinds +
the v2 tables, per m2-module-contracts.md §6:

- exact float equality (``abs=1e-9``) on scalar fields and point tuples;
- polyline vertices/bulges/widths/closed;
- text content/height/rotation/justification/style; mtext content/width/style;
- dim definition fields EXCEPT ``measurement`` (derived — compared via
  the RECOMPUTED value instead) and EXCEPT ``measured_id`` (product-internal
  associativity, not a file concept — the ledger records it per dim) and
  EXCEPT ``angle`` for ALIGNED dims (the axis IS the p1->p2 direction,
  recomputed on both sides);
- insert name/position/scale/rotation; viewport center/view_height/p1/p2/locked;
- layer table (name + all props), block definitions (name, base_point,
  definition handle, member geometry), layout set (names + page sizes +
  paper units), entity space routing, settings subset as EXPORTED (the
  INSUNITS derivation from unit metadata is shared with the exporter),
  text/dim style tables.

Set semantics (M1 precedent): the MIRROR may carry ADDITIONAL foreign
table entries (ezdxf always writes the "Defpoints" layer; a document
with no layouts keeps the default "Layout1" — the exporter deletes it
whenever the document owns at least one layout). Source tables must be
a SUBSET of the mirror's.

Entities are matched BY HANDLE, not by store order: a DXF file stores
model space and each paper space as separate containers, so cross-space
store order is not a file concept (within one space, order round-trips).

Every deviation raises AssertionError with a field-level message — the
caller decides whether it is an expected ledgered loss or a bug.
"""

from __future__ import annotations

import math

#: absolute float tolerance for geometry fields.
APPROX = 1e-9


def _points_equal(a, b, what="point"):
    assert len(a) == len(b), f"{what}: {a!r} != {b!r} (arity)"
    for x, y in zip(a, b):
        assert abs(float(x) - float(y)) < APPROX, f"{what}: {a!r} != {b!r}"


def _scalars_equal(a, b, what="value"):
    assert abs(float(a) - float(b)) < APPROX, f"{what}: {a!r} != {b!r}"


def _entity_signature(entity):
    """Kind-dependent comparable signature of ONE entity.

    Returns a dict ``{field: value}`` where values are floats, strings,
    bools, point tuples, lists or None — the compare walks them
    recursively with tolerance."""
    data = {
        "kind": entity.kind,
        "layer": entity.layer,
        "color": entity.color,
        "linetype": entity.linetype,
        "lineweight": entity.lineweight,
        "space": entity.space,
    }
    kind = entity.kind
    if kind == "line":
        data["p1"], data["p2"] = entity.p1, entity.p2
    elif kind == "circle":
        data["center"], data["radius"] = entity.center, entity.radius
    elif kind == "arc":
        data["center"], data["radius"] = entity.center, entity.radius
        data["start_angle"] = entity.start_angle
        data["end_angle"] = entity.end_angle
    elif kind == "point":
        data["position"] = entity.position
    elif kind == "polyline":
        data["vertices"] = [list(v) for v in entity.vertices]
        # DXF always stores one bulge + width pair PER VERTEX; bcdoc stores
        # None when they are uniformly zero. An all-zero list IS the None
        # form (geometry-identical) — normalize both to [] so the two
        # canonical spellings compare equal.
        bulges = [float(b) for b in (entity.bulges or ())]
        data["bulges"] = bulges if any(abs(b) > 1e-12 for b in bulges) else []
        widths = [[float(pair[0]), float(pair[1])] for pair in
                   (entity.widths or ())]
        data["widths"] = (widths if any(abs(x) > 1e-12
                                         for pair in widths for x in pair)
                           else [])
        data["closed"] = entity.closed
        data["elevation"] = (entity.vertices[0][2]
                             if entity.vertices else 0.0)
    elif kind == "ellipse":
        data["center"] = entity.center
        data["major_axis"] = entity.major_axis
        data["ratio"] = entity.ratio
        data["start_angle"] = entity.start_angle
        data["end_angle"] = entity.end_angle
    elif kind in ("xline", "ray"):
        # DXF stores p1 + a NORMALIZED direction; the second point's
        # magnitude is not a file concept (infinite entity — the direction
        # IS the geometry). Compare p1 + direction.
        data["p1"] = entity.p1
        dx = entity.p2[0] - entity.p1[0]
        dy = entity.p2[1] - entity.p1[1]
        dz = entity.p2[2] - entity.p1[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        data["dir"] = (dx / length, dy / length, dz / length)
    elif kind == "text":
        data["position"] = entity.position
        data["height"] = entity.height
        data["rotation"] = entity.rotation
        data["content"] = entity.content
        data["style"] = entity.style
        data["justification"] = entity.justification
    elif kind == "mtext":
        data["position"] = entity.position
        data["width"] = entity.width
        data["content"] = entity.content
        data["style"] = entity.style
    elif kind == "dim":
        data["dim_type"] = entity.dim_type
        data["p1"], data["p2"] = entity.p1, entity.p2
        data["offset_point"] = entity.offset_point
        data["text_override"] = entity.text_override
        data["style"] = entity.style
        data["text_position"] = entity.text_position
        if entity.dim_type == "aligned":
            # the measurement axis IS p1->p2 — derived, recomputed on both
            # sides (exactly like measurement)
            data["angle_derived"] = math.degrees(math.atan2(
                entity.p2[1] - entity.p1[1], entity.p2[0] - entity.p1[0]))
        else:
            data["angle"] = entity.angle
    elif kind == "insert":
        data["name"] = entity.name
        data["position"] = entity.position
        data["scale"] = entity.scale
        data["rotation"] = entity.rotation
    elif kind == "viewport":
        data["center"] = entity.center
        data["view_height"] = entity.view_height
        data["p1"], data["p2"] = entity.p1, entity.p2
        data["locked"] = entity.locked
    return data


def _compare_value(field, a, b):
    if a is None or b is None:
        assert a is None and b is None, f"{field}: {a!r} != {b!r}"
        return
    if isinstance(a, str) or isinstance(b, str):
        assert a == b, f"{field}: {a!r} != {b!r}"
        return
    if isinstance(a, bool) or isinstance(b, bool):
        assert a is b, f"{field}: {a!r} != {b!r}"
        return
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        _scalars_equal(a, b, field)
        return
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        assert len(a) == len(b), f"{field}: {a!r} != {b!r} (arity)"
        for i, (x, y) in enumerate(zip(a, b)):
            _compare_value(f"{field}[{i}]", x, y)
        return
    assert a == b, f"{field}: {a!r} != {b!r}"


def compare_entities(source, mirror, context="entity"):
    """Compare two entities field-by-field (kind/handle + signature)."""
    assert source.kind == mirror.kind, f"{context}: kind {source.kind} != {mirror.kind}"
    assert source.handle == mirror.handle, (
        f"{context}: handle {source.handle} != {mirror.handle} "
        "(DXF handles must be preserved)")
    a = _entity_signature(source)
    b = _entity_signature(mirror)
    for field in a:
        _compare_value(f"{context}.{field}", a[field], b.get(field))


def compare_document_content(source, mirror, *, expect_losses=()):
    """Full round-trip compare (raises AssertionError on any deviation).

    ``expect_losses`` is a sequence of ``(kind, dxf_type)`` pairs that the
    caller EXPECTS in the ledger (e.g. dims losing associativity); they
    are verified against :func:`expected_ledger_entries` — every other
    loss is a deviation."""
    # -- entities (matched BY HANDLE) ------------------------------------------
    # A DXF file stores model space and each paper space as SEPARATE
    # entity containers, so the mirror's store order is MODEL-first-then-
    # paperspaces — cross-space store order is not a file concept and the
    # M1 sequence rule cannot survive it. Handles are the identity that
    # must survive: compare the two handle SETS and then every entity
    # field-by-field (within one space the file order still round-trips).
    src = {e.handle: e for e in source.entities()}
    dst = {e.handle: e for e in mirror.entities()}
    assert sorted(src) == sorted(dst), (
        "entity handle sets differ:\n"
        f"  missing in mirror: {sorted(set(src) - set(dst))}\n"
        f"  unexpected in mirror: {sorted(set(dst) - set(src))}")
    for handle in sorted(src):
        compare_entities(src[handle], dst[handle], context=f"entity[{handle}]")

    # -- layer table (subset rule: mirror may carry foreign extras) -------------
    for record in source.layers.records():
        other = mirror.layers.get(record.name)
        assert other is not None, f"layer {record.name!r} lost"
        _compare_value("layer.color", record.color, other.color)
        _compare_value("layer.linetype", record.linetype, other.linetype)
        _compare_value("layer.lineweight", record.lineweight, other.lineweight)
        _compare_value("layer.on", record.on, other.on)
        _compare_value("layer.frozen", record.frozen, other.frozen)
        _compare_value("layer.locked", record.locked, other.locked)
        _compare_value("layer.plot", record.plot, other.plot)

    # -- block definitions (name, base point, handle, member geometry) --------
    for name in source.block_names():
        assert name in mirror.block_names(), f"block {name!r} lost"
        src_def = source.block(name)
        dst_def = mirror.block(name)
        assert src_def.handle == dst_def.handle, (
            f"block {name!r} definition handle "
            f"{src_def.handle} != {dst_def.handle}")
        _points_equal(src_def.base_point, dst_def.base_point, "block base")
        assert len(src_def.entities) == len(dst_def.entities), (
            f"block {name!r} member count differs")
        for a, b in zip(src_def.entities, dst_def.entities):
            # members created outside a document carry handle 0 — compare
            # handles only when the source member has one
            if a.handle >= 1:
                assert a.handle == b.handle, (
                    f"block {name!r} member handle {a.handle} != {b.handle}")
            compare_entities(a, b, context=f"block[{name}]")

    # -- layouts (subset rule; names + page sizes + paper units) --------------
    for name in source.layouts():
        assert name in mirror.layouts(), f"layout {name!r} lost"
        a = source.layout(name)
        b = mirror.layout(name)
        _scalars_equal(a.page_width, b.page_width, "layout.page_width")
        _scalars_equal(a.page_height, b.page_height, "layout.page_height")
        assert a.paper_units == b.paper_units, (
            f"layout {name!r} paper_units {a.paper_units!r} != {b.paper_units!r}")

    # -- entity space routing --------------------------------------------------
    for name in ["MODEL"] + source.layouts():
        src_ids = [e.id for e in source.entities_in_space(name)]
        dst_ids = [e.id for e in mirror.entities_in_space(name)]
        assert len(src_ids) == len(dst_ids), (
            f"space {name!r} routing differs "
            f"({len(src_ids)} vs {len(dst_ids)} entities)")

    # -- settings (as exported — the INSUNITS derivation is shared) ----------
    from bcio import ezdxf_bridge
    exported = ezdxf_bridge.exported_settings(source)
    for name, value in exported.items():
        mirrored = mirror.settings.get(name)
        if isinstance(value, float) or isinstance(mirrored, float):
            _scalars_equal(value, mirrored, f"settings.{name}")
        else:
            assert value == mirrored, (
                f"settings.{name}: {value!r} != {mirrored!r}")

    # -- style tables ----------------------------------------------------------
    for name in source.text_styles():
        assert name in mirror.text_styles(), f"text style {name!r} lost"
        a = source.text_style(name)
        b = mirror.text_style(name)
        _scalars_equal(a.height, b.height, "style.height")
        _scalars_equal(a.width_factor, b.width_factor, "style.width_factor")
    for name in source.dim_styles():
        assert name in mirror.dim_styles(), f"dim style {name!r} lost"
        a = source.dim_style(name)
        b = mirror.dim_style(name)
        for field in ("dimscale", "dimtxt", "dimasz", "dimexo", "dimexe"):
            _scalars_equal(getattr(a, field), getattr(b, field),
                           f"dimstyle.{field}")


def recompute_measurement(dim):
    """The measurement derived from the definition points (linear:
    projection of p2-p1 on the measurement axis; aligned: |p2-p1|)."""
    if dim.dim_type == "aligned":
        return math.hypot(dim.p2[0] - dim.p1[0], dim.p2[1] - dim.p1[1])
    angle = math.radians(dim.angle)
    return abs((dim.p2[0] - dim.p1[0]) * math.cos(angle)
               + (dim.p2[1] - dim.p1[1]) * math.sin(angle))


#: expected loss signatures: dxf_type -> substring of the ledger reason.
EXPECTED_LOSS_PATTERNS = {
    ("DIMENSION", "measured_id"): "associativity (measured_id)",
    ("LTYPE", "pattern"): "dash-pattern",
    ("XLINE", "unit-vector"): "unit vector",
    ("RAY", "unit-vector"): "unit vector",
    ("MTEXT", "char-height"): "character height",
    ("STYLE", "font"): "font",
    ("VIEWPORT", "presentation"): "presentation attributes",
    ("SETTINGS", "no-header"): "no DXF header variable",
    ("PAPER_SPACE", "session"): "SESSION state",
    ("LAYOUT", "session"): "SESSION state",
}


def expected_ledger_entries(ledger_entries, expected):
    """Verify that every ``(dxf_type, reason-substring)`` signature in
    ``expected`` occurs in the ledger entries (kind-agnostic)."""
    for dxf_type, needle in expected:
        assert any(dxf_type == entry["dxf_type"] and needle in entry["reason"]
                   for entry in ledger_entries), (
            f"expected a ledger entry {dxf_type!r} containing {needle!r}")
