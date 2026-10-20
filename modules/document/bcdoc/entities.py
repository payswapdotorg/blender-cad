"""Entity classes for the document model (v0 at M1, v2 at M2).

Contract: docs/00-architecture/m1-module-contracts.md §3.1 (M1 kinds),
docs/00-architecture/m2-module-contracts.md §2.1 (v2 generalization).

Geometry is stored in document/world coordinates, in unit-free "drawing
units" (v0 performs no unit conversion; ``Document.units`` is display
metadata only). Entities carry dual identity (document-model doc §3.1):

- ``id`` — a stable UUID4 hex, generated at creation, immutable, never
  reused (the product-internal identity);
- ``handle`` — a DWG-style per-document monotonic handle, assigned by
  ``Document.add_entity`` (the interchange identity; DXF round-trips
  preserve it).

Entities are "immutable-ish": direct attribute mutation outside a
transaction is not the legal path — use ``Document.update_entity`` inside
``with doc.transaction(...)`` so the change is journaled and undoable.

v2 (contract §2.1) adds:

- ``lineweight`` (float mm | None; None = ByLayer) and ``space``
  ("MODEL" or a layout name) common property fields;
- color semantics gain ``0`` = ByBlock (valid for entities inside block
  definitions; resolved against the insert at display/interchange);
- an explicit per-kind geometry field registry with typed coercers used by
  ``set_field``, ``to_json_dict`` and ``serialize`` (single source of
  truth for validation AND wire form);
- the ten M2 entity kinds (point, polyline, ellipse, xline, ray, text,
  mtext, dim, insert, viewport).

``to_json_dict`` emits common properties in the pinned order
(kind, id, handle, layer, color, linetype, lineweight, space) followed by
the kind's geometry fields in registry order — the key order is part of
the byte-stable serialization contract.
"""

from __future__ import annotations

import uuid

from . import errors

#: Per-kind geometry fields; order = serialization order (contracts §2.1).
GEOMETRY_FIELDS: dict = {
    "line": ("p1", "p2"),
    "circle": ("center", "radius"),
    "arc": ("center", "radius", "start_angle", "end_angle"),
    "point": ("position",),
    "polyline": ("vertices", "bulges", "widths", "closed"),
    "ellipse": ("center", "major_axis", "ratio", "start_angle", "end_angle"),
    "xline": ("p1", "p2"),
    "ray": ("p1", "p2"),
    "text": ("position", "height", "rotation", "content", "style", "justification"),
    "mtext": ("position", "width", "content", "style"),
    "dim": (
        "dim_type", "p1", "p2", "angle", "offset_point", "measured_id",
        "measurement", "text_override", "style", "text_position",
    ),
    "insert": ("name", "position", "scale", "rotation"),
    "viewport": ("center", "view_height", "p1", "p2", "locked"),
}

#: Per-kind geometry-field coercer names (contracts §2.1 coercer vocabulary:
#: point / float / str / bool / point_list / float_list / width_list /
#: point_or_none).
GEOMETRY_COERCERS: dict = {
    "line": {"p1": "point", "p2": "point"},
    "circle": {"center": "point", "radius": "float"},
    "arc": {"center": "point", "radius": "float",
            "start_angle": "float", "end_angle": "float"},
    "point": {"position": "point"},
    "polyline": {"vertices": "point_list", "bulges": "float_list",
                 "widths": "width_list", "closed": "bool"},
    "ellipse": {"center": "point", "major_axis": "point", "ratio": "float",
                "start_angle": "float", "end_angle": "float"},
    "xline": {"p1": "point", "p2": "point"},
    "ray": {"p1": "point", "p2": "point"},
    "text": {"position": "point", "height": "float", "rotation": "float",
              "content": "str", "style": "str", "justification": "str"},
    "mtext": {"position": "point", "width": "float",
              "content": "str", "style": "str"},
    "dim": {"dim_type": "str", "p1": "point", "p2": "point", "angle": "float",
            "offset_point": "point", "measured_id": "str", "measurement": "float",
            "text_override": "str", "style": "str", "text_position": "point_or_none"},
    "insert": {"name": "str", "position": "point", "scale": "point",
               "rotation": "float"},
    "viewport": {"center": "point", "view_height": "float", "p1": "point",
                 "p2": "point", "locked": "bool"},
}

#: Common mutable property fields (contracts §2.1: layer / color / linetype /
#: lineweight / space — the M1 set plus the two v2 additions).
PROPERTY_FIELDS = ("layer", "color", "linetype", "lineweight", "space")

#: Text justification values (contract §2.1: "LEFT" | "CENTER" | "RIGHT").
TEXT_JUSTIFICATIONS = ("LEFT", "CENTER", "RIGHT")

#: Dimension type values (contract §2.1: "linear" | "aligned").
DIM_TYPES = ("linear", "aligned")


def is_point(field: str) -> bool:
    """M1 helper kept for compatibility (v2 uses the coercer registry)."""
    return field in ("p1", "p2", "center")


def normalize_point(value) -> tuple:
    """Coerce 2D/3D input into a ``(x, y, z)`` float tuple (missing z -> 0.0)."""
    try:
        seq = tuple(value)
        if len(seq) not in (2, 3):
            raise ValueError
        coords = [float(seq[0]), float(seq[1])]
        coords.append(float(seq[2]) if len(seq) == 3 else 0.0)
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"not a valid 2D/3D point: {value!r}") from None
    return (coords[0], coords[1], coords[2])


# ---------------------------------------------------------------------------
# coercers (contracts §2.1 registry)
# ---------------------------------------------------------------------------

def _coerce_float(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"expected a number, got {value!r}")
    return float(value)


def _coerce_str(value) -> str:
    if not isinstance(value, str):
        raise ValueError(f"expected a string, got {value!r}")
    return value


def _coerce_bool(value) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"expected a bool, got {value!r}")
    return value


def _coerce_point_list(value) -> tuple:
    try:
        items = list(value)
    except TypeError:
        raise ValueError(f"expected a list of points, got {value!r}") from None
    return tuple(normalize_point(item) for item in items)


def _coerce_float_list(value) -> tuple:
    try:
        items = list(value)
    except TypeError:
        raise ValueError(f"expected a list of numbers, got {value!r}") from None
    return tuple(_coerce_float(item) for item in items)


def _coerce_width_list(value) -> tuple:
    """[start_width, end_width] float pairs — widths[i] belongs to the
    segment LEAVING vertex i (AutoCAD convention, contracts §2.1)."""
    try:
        items = list(value)
    except TypeError:
        raise ValueError(f"expected a list of width pairs, got {value!r}") from None
    widths = []
    for item in items:
        try:
            pair = tuple(item)
        except TypeError:
            raise ValueError(f"not a valid width pair: {item!r}") from None
        if len(pair) != 2:
            raise ValueError(f"not a valid width pair: {item!r}")
        widths.append((_coerce_float(pair[0]), _coerce_float(pair[1])))
    return tuple(widths)


def _coerce_point_or_none(value):
    return None if value is None else normalize_point(value)


#: coercer name -> function (single registry used by set_field, to_json_dict
#: and serialize; every coercer is idempotent — already-normalized values
#: pass through unchanged, which journal replay relies on).
COERCERS: dict = {
    "point": normalize_point,
    "float": _coerce_float,
    "str": _coerce_str,
    "bool": _coerce_bool,
    "point_list": _coerce_point_list,
    "float_list": _coerce_float_list,
    "width_list": _coerce_width_list,
    "point_or_none": _coerce_point_or_none,
}


def coerce_geometry_value(kind: str, field: str, value):
    """Validate + normalize one geometry value for the given entity kind
    (raises ``ValueError`` on malformed input)."""
    try:
        coercer_name = GEOMETRY_COERCERS[kind][field]
    except KeyError:
        raise errors.InvalidEntityField(kind, field) from None
    return COERCERS[coercer_name](value)


def json_geometry_value(kind: str, field: str, value):
    """The JSON-safe form of one geometry value (tuples -> lists)."""
    try:
        coercer_name = GEOMETRY_COERCERS[kind][field]
    except KeyError:
        raise errors.InvalidEntityField(kind, field) from None
    if coercer_name == "point_or_none":
        return None if value is None else list(value)
    if coercer_name in ("point_list",):
        return [list(point) for point in value]
    if coercer_name == "float_list":
        return [float(v) for v in value]
    if coercer_name == "width_list":
        return [[float(start), float(end)] for start, end in value]
    if coercer_name in ("point",):
        return list(value)
    if coercer_name in ("float",):
        return float(value)
    return value  # str / bool


def _validate_polyline_lengths(entity: "Polyline") -> None:
    """Keep the bulges/widths-per-vertex invariant after any geometry
    mutation (set_field/journal replay path)."""
    count = len(entity.vertices)
    for name in ("bulges", "widths"):
        values = getattr(entity, name)
        if values and len(values) != count:
            raise ValueError(
                f"polyline {name} length {len(values)} != vertex count {count}")


def set_field(entity: "Entity", field: str, value) -> None:
    """Validate + apply a field change on ``entity`` (used by transactions
    and journal replay). Raises :class:`errors.InvalidEntityField` for
    unknown fields and ``ValueError`` for malformed values."""
    if field in PROPERTY_FIELDS:
        if field == "layer":
            entity.layer = str(value)
        elif field == "linetype":
            entity.linetype = str(value)
        elif field == "space":
            entity.space = str(value)
        elif field == "lineweight":
            if value is None:
                entity.lineweight = None
            else:
                weight = _coerce_float(value)
                if weight < 0:
                    raise ValueError(f"lineweight must be >= 0, got {value!r}")
                entity.lineweight = weight
        else:  # color: ACI int, None (= ByLayer) or 0 (= ByBlock)
            entity.color = None if value is None else int(value)
        return
    if field in GEOMETRY_FIELDS[entity.kind]:
        new_value = coerce_geometry_value(entity.kind, field, value)
        if entity.kind == "polyline" and field in ("vertices", "bulges", "widths"):
            # validate on a scratch copy so a rejected change leaves the
            # entity untouched (no partial apply)
            scratch = entity.copy()
            scratch.__setattr__(field, new_value)
            _validate_polyline_lengths(scratch)
        setattr(entity, field, new_value)
        return
    raise errors.InvalidEntityField(entity.kind, field)


def _property_kwargs(layer, color, linetype, lineweight, space) -> dict:
    """Normalized common-property constructor kwargs (shared by every kind)."""
    return {
        "layer": layer,
        "color": color,
        "linetype": linetype,
        "lineweight": lineweight,
        "space": space,
    }


class Entity:
    """Base class for all document entities (plain Python, no bpy)."""

    #: Overridden by subclasses to the kind name.
    _KIND = "entity"

    def __init__(self, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        self.id = uuid.uuid4().hex
        #: 0 = "not yet assigned by a Document" (handles are >= 1 once added).
        self.handle = 0
        self.layer = str(layer)
        #: ACI color index, None (= ByLayer) or 0 (= ByBlock; valid only for
        #: entities inside block definitions, resolved against the insert at
        #: display/interchange).
        self.color = None if color is None else int(color)
        self.linetype = str(linetype)
        #: Lineweight in millimeters; None = ByLayer.
        self.lineweight = None if lineweight is None else float(lineweight)
        #: "MODEL" or a layout name (paper space routing).
        self.space = str(space)

    @property
    def kind(self) -> str:
        return self._KIND

    @property
    def mutable_fields(self) -> tuple:
        return tuple(PROPERTY_FIELDS) + GEOMETRY_FIELDS[self.kind]

    def to_json_dict(self) -> dict:
        """Fixed-order JSON-safe dict of every field (the single source for
        bcdoc entity records (bcdoc/2 format, kept by bcdoc/3) and journal
        snapshots; key order is part of
        the byte-stable serialization contract: common properties in the
        pinned order, then geometry fields in registry order)."""
        data = {
            "kind": self.kind,
            "id": self.id,
            "handle": int(self.handle),
            "layer": self.layer,
            "color": None if self.color is None else int(self.color),
            "linetype": self.linetype,
            "lineweight": None if self.lineweight is None else float(self.lineweight),
            "space": self.space,
        }
        for field in GEOMETRY_FIELDS[self.kind]:
            data[field] = json_geometry_value(
                self.kind, field, getattr(self, field))
        return data

    def copy(self) -> "Entity":
        """State-identical copy (same id, same handle, same field values).

        Used for transaction snapshots, block-definition ownership and
        journal records; tuples/strings are immutable, so a ``__dict__`` copy
        is sufficient."""
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        return clone

    def geometry_dict(self) -> dict:
        return {f: getattr(self, f) for f in GEOMETRY_FIELDS[self.kind]}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        geom = " ".join(f"{k}={v!r}" for k, v in self.geometry_dict().items())
        return (
            f"<{self.__class__.__name__} id={self.id[:8]}… "
            f"handle={self.handle} layer={self.layer!r} {geom}>"
        )


# ---------------------------------------------------------------------------
# M1 kinds (behavior byte-identical for the M1 fields)
# ---------------------------------------------------------------------------

class Line(Entity):
    """Two-point line segment (world coordinates, drawing units)."""

    _KIND = "line"

    def __init__(self, p1, p2, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)


class Circle(Entity):
    """Full circle: center + radius (degrees of freedom: none at v0)."""

    _KIND = "circle"

    def __init__(self, center, radius, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.center = normalize_point(center)
        self.radius = float(radius)


class Arc(Entity):
    """Arc: center + radius + start/end angle in degrees, CCW about +Z."""

    _KIND = "arc"

    def __init__(self, center, radius, start_angle, end_angle,
                 layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.center = normalize_point(center)
        self.radius = float(radius)
        self.start_angle = float(start_angle)
        self.end_angle = float(end_angle)


# ---------------------------------------------------------------------------
# M2 kinds (contracts §2.1)
# ---------------------------------------------------------------------------

class Point(Entity):
    """Single point entity (marker; display owns its presentation)."""

    _KIND = "point"

    def __init__(self, position, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.position = normalize_point(position)


class Polyline(Entity):
    """Polyline: vertices + per-vertex bulges/widths + closed flag.

    Bulge convention (binding, contract §2.1): AutoCAD bulge =
    ``tan(delta_angle / 4)``; positive bulge = CCW arc from vertex i to
    vertex i+1. ``widths[i] = [start_width, end_width]`` for the segment
    leaving vertex i (for a closed polyline the last vertex's pair applies
    to the closing segment). Vertices are 3-tuples; bulges/widths default
    to empty (straight zero-width segments).
    """

    _KIND = "polyline"

    def __init__(self, vertices, bulges=None, widths=None, closed=False,
                 layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.vertices = _coerce_point_list(vertices)
        if not self.vertices:
            raise ValueError("a polyline needs at least one vertex")
        count = len(self.vertices)
        self.bulges = _coerce_float_list(bulges if bulges is not None else ())
        if self.bulges and len(self.bulges) != count:
            raise ValueError(
                f"bulges length {len(self.bulges)} != vertex count {count}")
        self.widths = _coerce_width_list(widths if widths is not None else ())
        if self.widths and len(self.widths) != count:
            raise ValueError(
                f"widths length {len(self.widths)} != vertex count {count}")
        self.closed = _coerce_bool(closed)


class Ellipse(Entity):
    """Ellipse: center + major_axis vector + ratio (minor/major) +
    start/end param angles in degrees (defaults describe the FULL
    ellipse: 0, 360 — contract §2.1)."""

    _KIND = "ellipse"

    def __init__(self, center, major_axis, ratio, start_angle=0.0,
                 end_angle=360.0, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.center = normalize_point(center)
        self.major_axis = normalize_point(major_axis)
        self.ratio = float(ratio)
        self.start_angle = float(start_angle)
        self.end_angle = float(end_angle)


class Xline(Entity):
    """Construction line: infinite through p1 and p2 (display clips it)."""

    _KIND = "xline"

    def __init__(self, p1, p2, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)


class Ray(Entity):
    """Ray: semi-infinite from p1 THROUGH p2 (beyond p2)."""

    _KIND = "ray"

    def __init__(self, p1, p2, layer="0", color=None, linetype="ByLayer",
                 lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)


class Text(Entity):
    """Single-line text: position + height + rotation + content + style +
    justification ("LEFT" | "CENTER" | "RIGHT")."""

    _KIND = "text"

    def __init__(self, position, height=2.5, rotation=0.0, content="",
                 style="Standard", justification="LEFT", layer="0",
                 color=None, linetype="ByLayer", lineweight=None,
                 space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.position = normalize_point(position)
        self.height = _coerce_float(height)
        self.rotation = _coerce_float(rotation)
        self.content = _coerce_str(content)
        self.style = _coerce_str(style)
        justification = _coerce_str(justification)
        if justification not in TEXT_JUSTIFICATIONS:
            raise ValueError(
                f"justification must be one of {TEXT_JUSTIFICATIONS}, "
                f"got {justification!r}")
        self.justification = justification


class Mtext(Entity):
    """Multiline text block: position + column width + content (embedded
    newlines respected; wrapping is display-owned) + style."""

    _KIND = "mtext"

    def __init__(self, position, width=0.0, content="", style="Standard",
                 layer="0", color=None, linetype="ByLayer", lineweight=None,
                 space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.position = normalize_point(position)
        self.width = _coerce_float(width)
        self.content = _coerce_str(content)
        self.style = _coerce_str(style)


class Dim(Entity):
    """Dimension entity: measured geometry + association + presentation
    overrides. ``dim_type`` is "linear" or "aligned"; ``measured_id``
    associates the dimension with a live entity (empty string = free dim);
    ``measurement`` is the cached value (refreshed by regen); ``style``
    names a dim style record; ``text_position`` overrides the automatic
    text placement when not None."""

    _KIND = "dim"

    def __init__(self, dim_type, p1, p2, angle=0.0, offset_point=(0.0, 0.0, 0.0),
                 measured_id="", measurement=0.0, text_override="",
                 style="Standard", text_position=None, layer="0", color=None,
                 linetype="ByLayer", lineweight=None, space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        dim_type = _coerce_str(dim_type)
        if dim_type not in DIM_TYPES:
            raise ValueError(
                f"dim_type must be one of {DIM_TYPES}, got {dim_type!r}")
        self.dim_type = dim_type
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)
        self.angle = _coerce_float(angle)
        self.offset_point = normalize_point(offset_point)
        self.measured_id = _coerce_str(measured_id)
        self.measurement = _coerce_float(measurement)
        self.text_override = _coerce_str(text_override)
        self.style = _coerce_str(style)
        self.text_position = _coerce_point_or_none(text_position)


class Insert(Entity):
    """Block reference: names a block definition + position + scale +
    rotation (degrees, CCW about +Z). References resolve BY NAME, so a
    block redefinition updates every reference automatically."""

    _KIND = "insert"

    def __init__(self, name, position, scale=(1.0, 1.0, 1.0), rotation=0.0,
                 layer="0", color=None, linetype="ByLayer", lineweight=None,
                 space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.name = _coerce_str(name)
        self.position = normalize_point(position)
        self.scale = normalize_point(scale)
        self.rotation = _coerce_float(rotation)


class Viewport(Entity):
    """Paper-space viewport: lives in a LAYOUT's space (entity.space);
    ``center``/``view_height`` describe the MODEL view shown, ``p1``/``p2``
    the paper rectangle corners, ``locked`` freezes the view."""

    _KIND = "viewport"

    def __init__(self, center, view_height, p1, p2, locked=False,
                 layer="0", color=None, linetype="ByLayer", lineweight=None,
                 space="MODEL"):
        super().__init__(**_property_kwargs(
            layer, color, linetype, lineweight, space))
        self.center = normalize_point(center)
        self.view_height = _coerce_float(view_height)
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)
        self.locked = _coerce_bool(locked)


#: kind -> entity class (single dispatch point for serialization + import).
ENTITY_CLASSES: dict = {
    "line": Line,
    "circle": Circle,
    "arc": Arc,
    "point": Point,
    "polyline": Polyline,
    "ellipse": Ellipse,
    "xline": Xline,
    "ray": Ray,
    "text": Text,
    "mtext": Mtext,
    "dim": Dim,
    "insert": Insert,
    "viewport": Viewport,
}
