"""Entity classes for the document model v0.

Contract: docs/00-architecture/m1-module-contracts.md §3.1.

Geometry is stored in document/world coordinates, in unit-free "drawing
units" (v0 performs no unit conversion; ``Document.units`` is display
metadata only). Entities carry dual identity (document-model doc §3.1):

- ``id`` — a stable UUID4 hex, generated at creation, immutable, never
  reused (the product-internal identity);
- ``handle`` — a DWG-style per-document monotonic handle, assigned by
  ``Document.add_entity`` (the interchange identity; DXF/DXF round-trips
  preserve it).

Entities are "immutable-ish": direct attribute mutation outside a
transaction is not the legal path — use ``Document.update_entity`` inside
``with doc.transaction(...)`` so the change is journaled and undoable.
"""

from __future__ import annotations

import uuid

from . import errors

#: Point fields per entity kind (insertion order is the serialization order).
GEOMETRY_FIELDS: dict = {
    "line": ("p1", "p2"),
    "circle": ("center", "radius"),
    "arc": ("center", "radius", "start_angle", "end_angle"),
}

#: Common mutable property fields (contract §3.1: layer / color / linetype).
PROPERTY_FIELDS = ("layer", "color", "linetype")


def is_point(field: str) -> bool:
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


def set_field(entity: "Entity", field: str, value) -> None:
    """Validate + apply a field change on ``entity`` (used by transactions
    and journal replay). Raises :class:`errors.InvalidEntityField` for
    unknown fields and ``ValueError`` for malformed values."""
    if field in PROPERTY_FIELDS:
        if field == "layer":
            entity.layer = str(value)
        elif field == "linetype":
            entity.linetype = str(value)
        else:  # color: ACI int or None (= ByLayer)
            entity.color = None if value is None else int(value)
        return
    if field in GEOMETRY_FIELDS[entity.kind]:
        if is_point(field):
            setattr(entity, field, normalize_point(value))
        else:
            setattr(entity, field, float(value))
        return
    raise errors.InvalidEntityField(entity.kind, field)


class Entity:
    """Base class for all document entities (plain Python, no bpy)."""

    #: Overridden by subclasses to "line" | "circle" | "arc".
    _KIND = "entity"

    def __init__(self, layer="0", color=None, linetype="ByLayer"):
        self.id = uuid.uuid4().hex
        #: 0 = "not yet assigned by a Document" (handles are >= 1 once added).
        self.handle = 0
        self.layer = str(layer)
        #: ACI color index or None (= ByLayer). ByBlock (0) is also mapped
        #: to None by interchange (bcdoc v0 has no ByBlock concept).
        self.color = color
        self.linetype = str(linetype)

    @property
    def kind(self) -> str:
        return self._KIND

    @property
    def mutable_fields(self) -> tuple:
        return tuple(PROPERTY_FIELDS) + GEOMETRY_FIELDS[self.kind]

    def to_json_dict(self) -> dict:
        """Fixed-order JSON-safe dict of every field (the single source for
        bcdoc/1 entity records and journal snapshots; key order is part of the
        byte-stable serialization contract)."""
        data = {
            "kind": self.kind,
            "id": self.id,
            "handle": int(self.handle),
            "layer": self.layer,
            "color": None if self.color is None else int(self.color),
            "linetype": self.linetype,
        }
        for field in GEOMETRY_FIELDS[self.kind]:
            value = getattr(self, field)
            if isinstance(value, tuple):
                data[field] = list(value)
            else:
                data[field] = float(value)
        return data

    def copy(self) -> "Entity":
        """State-identical copy (same id, same handle, same field values).

        Used for transaction snapshots and journal records; tuples/strings
        are immutable, so a ``__dict__`` copy is sufficient."""
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


class Line(Entity):
    """Two-point line segment (world coordinates, drawing units)."""

    _KIND = "line"

    def __init__(self, p1, p2, layer="0", color=None, linetype="ByLayer"):
        super().__init__(layer=layer, color=color, linetype=linetype)
        self.p1 = normalize_point(p1)
        self.p2 = normalize_point(p2)


class Circle(Entity):
    """Full circle: center + radius (degrees of freedom: none at v0)."""

    _KIND = "circle"

    def __init__(self, center, radius, layer="0", color=None, linetype="ByLayer"):
        super().__init__(layer=layer, color=color, linetype=linetype)
        self.center = normalize_point(center)
        self.radius = float(radius)


class Arc(Entity):
    """Arc: center + radius + start/end angle in degrees, CCW about +Z."""

    _KIND = "arc"

    def __init__(
        self,
        center,
        radius,
        start_angle,
        end_angle,
        layer="0",
        color=None,
        linetype="ByLayer",
    ):
        super().__init__(layer=layer, color=color, linetype=linetype)
        self.center = normalize_point(center)
        self.radius = float(radius)
        self.start_angle = float(start_angle)
        self.end_angle = float(end_angle)


#: kind -> entity class (single dispatch point for serialization + import).
ENTITY_CLASSES: dict = {
    "line": Line,
    "circle": Circle,
    "arc": Arc,
}
