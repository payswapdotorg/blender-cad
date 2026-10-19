"""Analytic 2D/3D geometry helpers for bcdraft — no kernel dependency.

Everything here is plain math on tuples/Points (M1 scope: lines, circles,
arcs live in the XY plane, angles in degrees CCW about +Z — kernel adoption
is M3, ADR-0002). Entity transforms are split in two:

* ``move_changes`` / ``rotate_changes`` / ``scale_changes`` compute the new
  field values for an entity — commands apply them via
  ``Document.update_entity(eid, **changes)`` inside a transaction, which is
  the journaled mutation path (contract §3.1: Document APIs are the only
  legal mutation path) and therefore UNDOABLE;
* the in-place ``move_entity`` / ``rotate_entity`` / ``scale_entity``
  wrappers exist for transient preview data only (rubberband copies) —
  never for document entities.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from bcdoc.entities import Arc, Circle, Line  # document entities (declared dep)

TOL = 1e-9

Pt = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# point helpers
# ---------------------------------------------------------------------------

def dist_2d(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def dist_3d(a, b) -> float:
    return math.sqrt(
        (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2
    )


def angle_of(vector) -> float:
    """Angle of a 2D vector in degrees, CCW from +X, normalized to [0, 360)."""
    degrees = math.degrees(math.atan2(vector[1], vector[0]))
    return normalize_deg(degrees)


def normalize_deg(degrees: float) -> float:
    """Normalize an angle to [0, 360)."""
    normalized = math.fmod(degrees, 360.0)
    if normalized < 0.0:
        normalized += 360.0
    if abs(normalized - 360.0) < TOL:
        normalized = 0.0
    return normalized


def move_pt(p, delta) -> Tuple[float, float, float]:
    return (p[0] + delta[0], p[1] + delta[1], p[2] + delta[2])


def rotate_pt(p, center, angle_deg: float) -> Tuple[float, float, float]:
    """Rotate ``p`` about ``center`` around +Z, CCW positive (XY plane only)."""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = p[0] - center[0], p[1] - center[1]
    return (
        center[0] + dx * cos_a - dy * sin_a,
        center[1] + dx * sin_a + dy * cos_a,
        p[2],
    )


def scale_pt(p, center, factor: float) -> Tuple[float, float, float]:
    return (
        center[0] + (p[0] - center[0]) * factor,
        center[1] + (p[1] - center[1]) * factor,
        center[2] + (p[2] - center[2]) * factor,
    )


# ---------------------------------------------------------------------------
# circles/arcs through points
# ---------------------------------------------------------------------------

def circumcenter(p1, p2, p3) -> Optional[Tuple[Tuple[float, float, float], float]]:
    """Circle through three 2D points → (center, radius); None if collinear."""
    ax, ay = p1[0], p1[1]
    bx, by = p2[0], p2[1]
    cx, cy = p3[0], p3[1]
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / d
    uy = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / d
    center = (ux, uy, 0.0)
    return center, dist_2d(center, p1)


def arc_from_3p(start, mid, end):
    """3-point arc → (center, radius, start_angle, end_angle), CCW convention.

    The returned arc is the CCW sweep from ``start_angle`` to ``end_angle``
    that passes through ``mid``. Returns None when the points are collinear.
    """
    circle = circumcenter(start, mid, end)
    if circle is None:
        return None
    center, radius = circle
    a_start = angle_of((start[0] - center[0], start[1] - center[1]))
    a_mid = angle_of((mid[0] - center[0], mid[1] - center[1]))
    a_end = angle_of((end[0] - center[0], end[1] - center[1]))
    # going CCW from start, do we reach mid before end?
    if _ccw_from(a_start, a_mid) < _ccw_from(a_start, a_end):
        return center, radius, a_start, a_end
    # mid lies on the other sweep: represent CCW from end to start
    return center, radius, a_end, a_start


def _ccw_from(a_from: float, a_to: float) -> float:
    """CCW sweep (degrees) from angle a_from to a_to."""
    return normalize_deg(a_to - a_from) or 360.0


def arc_points(center, radius: float, start_angle: float, end_angle: float,
               segments: int = 32) -> List[Pt]:
    """Sample polyline points along the CCW arc start→end (display + tests)."""
    sweep = _ccw_from(start_angle, end_angle)
    if sweep >= 360.0 - TOL:
        sweep = 360.0
    count = max(2, segments)
    points: List[Pt] = []
    for i in range(count + 1):
        angle = start_angle + sweep * (i / count)
        rad = math.radians(angle)
        points.append(
            (
                center[0] + radius * math.cos(rad),
                center[1] + radius * math.sin(rad),
                center[2],
            )
        )
    return points


def circle_points(center, radius: float, segments: int = 8) -> List[Pt]:
    """Polyline points around a full circle (samples on the circle)."""
    return arc_points(center, radius, 0.0, 360.0, segments)[:-1]


# ---------------------------------------------------------------------------
# in-place entity transforms (duck-typed on bcdoc entities)
# ---------------------------------------------------------------------------
#
# IMPORTANT (undo correctness): the ``*_changes`` functions are the ones
# commands use — they compute the new field values and the command applies
# them via ``Document.update_entity(eid, **changes)``, which journals the
# old values so UNDO restores geometry. Mutating entity attributes directly
# would bypass the undo journal (bcdoc does not trap attribute writes). The
# in-place ``*_entity`` variants below exist for transient preview data
# (rubberband copies), never for document entities.

def entity_anchor(entity) -> Tuple[float, float, float]:
    """A representative point for an entity (rubberband + dynamic readout)."""
    kind = getattr(entity, "kind", "")
    if kind == "line":
        return tuple(entity.p1)
    if kind in ("circle", "arc"):
        return tuple(entity.center)
    return (0.0, 0.0, 0.0)


def move_changes(entity, delta) -> dict:
    """Field changes translating ``entity`` by ``delta`` (apply via
    ``Document.update_entity`` inside a transaction — journaled + undoable)."""
    kind = getattr(entity, "kind", "")
    if kind == "line":
        return {"p1": move_pt(entity.p1, delta), "p2": move_pt(entity.p2, delta)}
    if kind in ("circle", "arc"):
        return {"center": move_pt(entity.center, delta)}
    raise ValueError(f"move_changes: unsupported kind {kind!r}")


def rotate_changes(entity, center, angle_deg: float) -> dict:
    """Field changes rotating ``entity`` about ``center`` (+Z, CCW positive)."""
    kind = getattr(entity, "kind", "")
    if kind == "line":
        return {
            "p1": rotate_pt(entity.p1, center, angle_deg),
            "p2": rotate_pt(entity.p2, center, angle_deg),
        }
    if kind == "circle":
        return {"center": rotate_pt(entity.center, center, angle_deg)}
    if kind == "arc":
        return {
            "center": rotate_pt(entity.center, center, angle_deg),
            "start_angle": normalize_deg(entity.start_angle + angle_deg),
            "end_angle": normalize_deg(entity.end_angle + angle_deg),
        }
    raise ValueError(f"rotate_changes: unsupported kind {kind!r}")


def scale_changes(entity, center, factor: float) -> dict:
    """Field changes scaling ``entity`` uniformly about ``center``."""
    kind = getattr(entity, "kind", "")
    if kind == "line":
        return {
            "p1": scale_pt(entity.p1, center, factor),
            "p2": scale_pt(entity.p2, center, factor),
        }
    if kind == "circle":
        return {
            "center": scale_pt(entity.center, center, factor),
            "radius": entity.radius * factor,
        }
    if kind == "arc":
        return {
            "center": scale_pt(entity.center, center, factor),
            "radius": entity.radius * factor,
        }
    raise ValueError(f"scale_changes: unsupported kind {kind!r}")


# -- in-place variants (transient preview data only, never document entities) --

def move_entity(entity, delta) -> None:
    for field, value in move_changes(entity, delta).items():
        setattr(entity, field, value)


def rotate_entity(entity, center, angle_deg: float) -> None:
    for field, value in rotate_changes(entity, center, angle_deg).items():
        setattr(entity, field, value)


def scale_entity(entity, center, factor: float) -> None:
    for field, value in scale_changes(entity, center, factor).items():
        setattr(entity, field, value)


def clone_moved(entity, delta):
    """New entity of the same kind/geometry, translated by ``delta``.

    Used by COPY: duplicates keep display properties (layer/color/linetype)
    and receive a fresh id at construction; handles are assigned by the
    document on add_entity.
    """
    kind = getattr(entity, "kind", "")
    props = {
        "layer": getattr(entity, "layer", "0"),
        "color": getattr(entity, "color", None),
        "linetype": getattr(entity, "linetype", "ByLayer"),
    }
    if kind == "line":
        return Line(move_pt(entity.p1, delta), move_pt(entity.p2, delta), **props)
    if kind == "circle":
        return Circle(move_pt(entity.center, delta), entity.radius, **props)
    if kind == "arc":
        return Arc(
            move_pt(entity.center, delta),
            entity.radius,
            entity.start_angle,
            entity.end_angle,
            **props,
        )
    raise ValueError(f"clone_moved: unsupported kind {kind!r}")


# convenience for commands/tests ----------------------------------------------

def distance_between(a, b) -> float:
    return dist_3d(
        (a[0], a[1], a[2]), (b[0], b[1], b[2])
    )
