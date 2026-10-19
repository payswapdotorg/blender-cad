"""Analytic 2D/3D geometry helpers for bcdraft — no kernel dependency.

Everything here is plain math on tuples/Points (M1 scope: lines, circles,
arcs live in the XY plane, angles in degrees CCW about +Z — kernel adoption
is M3, ADR-0002). Entity transforms are split in two:

* ``move_changes`` / ``rotate_changes`` / ``scale_changes`` / ``mirror_changes``
  compute the new field values for an entity — commands apply them via
  ``Document.update_entity(eid, **changes)`` inside a transaction, which is
  the journaled mutation path (contract §3.1: Document APIs are the only
  legal mutation path) and therefore UNDOABLE;
* the clone builders (``clone_moved``, ``apply_mirror``,
  ``apply_insert_transform``) return NEW entities with fresh ids — used by
  COPY/ARRAYRECT/MIRROR-keep-source/EXPLODE, added to the document through
  ``add_entity`` inside a transaction;
* the in-place ``move_entity`` / ``rotate_entity`` / ``scale_entity``
  wrappers exist for transient preview data only (rubberband copies) —
  never for document entities.

M2 additions (W-D, drafting core): bbox computation for every kind, the
AutoCAD bulge math (``arc_from_bulge`` and friends), polyline sampling,
exact line/circle intersections, mirror reflection and the per-kind
transform dispatch for all ten new bcdoc kinds.

Conventions (documented limits, honest scope):

* ``REACH`` — xline/ray bboxes and (in bcshell) display clip infinite
  entities at ±1000 drawing units around their defining points. Selection
  therefore "sees" them inside that reach only (documented approximation).
* Ellipse ``major_axis`` is the CENTER-RELATIVE semi-major vector (DXF
  convention, what ezdxf expects on interchange): the vector from the
  center to the first-axis endpoint. ``ratio`` = minor/major in (0, 1].
* Non-uniform SCALE of ellipses/arcs/circles (per-axis factors) is NOT
  supported by the M2 command set — commands pass uniform factors only;
  the transform helpers below take a single uniform factor.
* Text/mtext bboxes are rough estimates (no font metrics at M2 — content
  width is unknowable headlessly; documented).
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from bcdoc.entities import Arc, Circle, Line  # document entities (declared dep)
from bcdoc.entities import set_field as _set_field

TOL = 1e-9

#: Reach used to bound infinite entities (xline/ray) for bbox/selection and
#: by bcshell for display clipping (contract §7 "±1000 units").
REACH = 1000.0

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


def reflect_point(p, a, b) -> Tuple[float, float, float]:
    """Reflect ``p`` across the infinite line through ``a`` and ``b`` (XY).

    The z coordinate is preserved (M2 mirroring is a 2D operation about an
    axis line in the XY plane).
    """
    ux, uy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ux, uy)
    if length <= TOL:
        raise ValueError("mirror axis points coincide")
    ux, uy = ux / length, uy / length
    vx, vy = p[0] - a[0], p[1] - a[1]
    dot = vx * ux + vy * uy
    # reflected = a + u*(2(v·u)) - v  (mirror the offset vector)
    return (a[0] + 2.0 * dot * ux - vx, a[1] + 2.0 * dot * uy - vy, p[2])


def rect_of(p1, p2):
    """Normalized (min_x, min_y, max_x, max_y) rectangle from two corners."""
    return (
        min(p1[0], p2[0]), min(p1[1], p2[1]),
        max(p1[0], p2[0]), max(p1[1], p2[1]),
    )


def point_in_rect(p, rect, tol: float = TOL) -> bool:
    """Inclusive rectangle containment with tolerance (STRETCH crossing)."""
    min_x, min_y, max_x, max_y = rect
    return (
        p[0] >= min_x - tol and p[0] <= max_x + tol
        and p[1] >= min_y - tol and p[1] <= max_y + tol
    )


def project_on_segment(p, a, b):
    """Nearest point on segment ``a``-``b`` to ``p`` -> (point, t) with
    ``t`` clamped to [0, 1]. Degenerate segments project to ``a`` with t=0."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= TOL * TOL:
        return (ax, ay, a[2]), 0.0
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    point = (ax + t * dx, ay + t * dy, a[2])
    return point, t


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
# AutoCAD bulge math (contract §2.1: bulge = tan(delta/4), positive = CCW)
# ---------------------------------------------------------------------------

def arc_from_bulge(p1, p2, bulge):
    """Bulge arc → (center, radius, start_angle, end_angle) in the CCW
    entity convention (the returned CCW sweep start→end is the same point
    set as the bulge arc from ``p1`` to ``p2``).

    ``bulge`` is the AutoCAD value: ``tan(delta/4)`` with ``delta`` the
    signed included angle (CCW positive). ``|bulge| == 1`` is a semicircle,
    ``|bulge| > 1`` a major arc. For a NEGATIVE bulge the traversal from
    ``p1`` to ``p2`` is clockwise, so the returned CCW representation runs
    from ``p2`` to ``p1`` (same points, reversed direction).

    Raises ValueError for a zero bulge (straight segment) or coincident
    endpoints.
    """
    b = float(bulge)
    if abs(b) <= TOL:
        raise ValueError("arc_from_bulge: zero bulge is a straight segment")
    chord = dist_2d(p1, p2)
    if chord <= TOL:
        raise ValueError("arc_from_bulge: endpoints coincide")
    delta = 4.0 * math.atan(b)  # signed included angle, radians
    sin_half = math.sin(delta / 2.0)
    if abs(sin_half) < 1e-12:
        raise ValueError("arc_from_bulge: bulge too close to a full circle")
    radius = abs(chord / (2.0 * sin_half))
    ux = (p2[0] - p1[0]) / chord
    uy = (p2[1] - p1[1]) / chord
    mx = (p1[0] + p2[0]) / 2.0
    my = (p1[1] + p2[1]) / 2.0
    tan_half = math.tan(delta / 2.0)  # huge for |bulge| == 1 (center at mid)
    cx = mx + (-uy) * (chord / 2.0) / tan_half
    cy = my + (ux) * (chord / 2.0) / tan_half
    center = (cx, cy, p1[2])
    a1 = angle_of((p1[0] - cx, p1[1] - cy))
    a2 = angle_of((p2[0] - cx, p2[1] - cy))
    if b > 0.0:
        return center, radius, a1, a2
    return center, radius, a2, a1


def bulge_from_arc(p1, p2, center) -> float:
    """Bulge of the CCW arc from ``p1`` to ``p2`` about ``center``.

    Returns ``tan(sweep/4)`` for the CCW sweep from ``p1`` to ``p2`` (always
    positive, in (0, +inf)). Callers traversing the same arc CLOCKWISE (from
    its end point back to its start) must NEGATE the result — the point set
    is identical, the direction is not. Raises ValueError when ``p1`` and
    ``p2`` coincide or ``center`` is not equidistant (tolerance 1e-6).
    """
    r1 = dist_2d(p1, center)
    r2 = dist_2d(p2, center)
    if r1 <= TOL or abs(r1 - r2) > 1e-6:
        raise ValueError("bulge_from_arc: points are not on a common circle")
    if dist_2d(p1, p2) <= TOL:
        raise ValueError("bulge_from_arc: endpoints coincide")
    a1 = angle_of((p1[0] - center[0], p1[1] - center[1]))
    a2 = angle_of((p2[0] - center[0], p2[1] - center[1]))
    sweep = _ccw_from(a1, a2)
    return math.tan(math.radians(sweep) / 4.0)


def bulge_from_tangent(p1, p2, tangent) -> float:
    """Bulge of the arc from ``p1`` to ``p2`` whose tangent at ``p1`` is
    ``tangent`` (any non-zero 2D vector; the PLINE Arc option's
    tangent-continuation rule).

    The arc curves towards ``p2``: positive cross(T, p2-p1) → CCW (positive
    bulge), negative → CW (negative bulge). When ``p2`` lies exactly on the
    tangent line the arc degenerates and 0.0 (a straight segment) is
    returned (documented v0 behavior). Raises ValueError for a zero
    tangent or ``p2 == p1``.
    """
    tx, ty = float(tangent[0]), float(tangent[1])
    tlen = math.hypot(tx, ty)
    if tlen <= TOL:
        raise ValueError("bulge_from_tangent: zero tangent direction")
    tx, ty = tx / tlen, ty / tlen
    qx, qy = p2[0] - p1[0], p2[1] - p1[1]
    chord = math.hypot(qx, qy)
    if chord <= TOL:
        raise ValueError("bulge_from_tangent: endpoint equals the start point")
    cross = tx * qy - ty * qx
    if abs(cross) <= 1e-12:
        return 0.0
    # center = p1 + r*n with n the unit normal on the curve's side; the
    # circle through p2 fixes r = |q|^2 / (2*(n·q)) = |q|^2 / (2*cross).
    radius = (chord * chord) / (2.0 * cross)
    sin_half = chord / (2.0 * abs(radius))
    sin_half = max(-1.0, min(1.0, sin_half))
    sweep = 2.0 * math.asin(sin_half)  # radians, in [0, pi]
    dot = tx * qx + ty * qy
    if dot < 0.0:
        # p2 behind the tangent point: the arc sweeps past a semicircle
        sweep = 2.0 * math.pi - sweep
    sweep = math.copysign(sweep, cross)
    return math.tan(sweep / 4.0)


def tangent_at_end(p1, p2, bulge) -> Tuple[float, float]:
    """Unit outgoing tangent (x, y) at ``p2`` of the bulge arc p1→p2.

    For a zero bulge (straight segment) this is the segment direction.
    """
    if abs(float(bulge)) <= TOL:
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length <= TOL:
            raise ValueError("tangent_at_end: degenerate segment")
        return (dx / length, dy / length)
    center, _radius, _s, _e = arc_from_bulge(p1, p2, bulge)
    vx, vy = p2[0] - center[0], p2[1] - center[1]
    length = math.hypot(vx, vy)
    vx, vy = vx / length, vy / length
    if bulge > 0.0:  # CCW: tangent = radius rotated +90°
        return (-vy, vx)
    return (vy, -vx)  # CW: radius rotated -90°


def polyline_segments(entity) -> List[Tuple[Pt, Pt, float]]:
    """Polyline segments as ``(start, end, bulge)`` tuples, INCLUDING the
    closing segment for ``closed`` polylines. Bulges default to 0.0 when the
    entity carries no bulge list."""
    vertices = list(entity.vertices)
    count = len(vertices)
    if count < 2:
        return []
    bulges = list(entity.bulges) if entity.bulges else []
    segments = count - 1 + (1 if entity.closed else 0)
    out: List[Tuple[Pt, Pt, float]] = []
    for i in range(segments):
        bulge = float(bulges[i]) if i < len(bulges) else 0.0
        out.append((vertices[i], vertices[(i + 1) % count], bulge))
    return out


def polyline_points(entity, segments_per_arc: int = 16) -> List[Pt]:
    """Flat ordered point list along the polyline path (display/selection).

    Bulge segments are sampled at ``segments_per_arc`` samples per sweep;
    straight segments contribute only their endpoints (every segment's
    final point is the next segment's first point, emitted once).
    """
    vertices = list(entity.vertices)
    count = len(vertices)
    if count == 0:
        return []
    if count == 1:
        return [tuple(vertices[0])]
    out: List[Pt] = [tuple(vertices[0])]
    for start, end, bulge in polyline_segments(entity):
        if abs(bulge) > TOL:
            center, radius, s, e = arc_from_bulge(start, end, bulge)
            samples = arc_points(center, radius, s, e, max(2, segments_per_arc))
            if bulge < 0.0:
                # CCW representation runs end→start; reverse to walk the
                # actual traversal direction (start→end, clockwise).
                samples = list(reversed(samples))
            out.extend(samples[1:-1])
        out.append(tuple(end))
    return out


# ---------------------------------------------------------------------------
# exact intersections (tolerance 1e-9) — OFFSET/BREAK/JOIN + selection
# (W-A's precision.py re-derives its own osnap candidates in a separate
# file on purpose: independent modules, no cross-import)
# ---------------------------------------------------------------------------

def line_line_intersection(p1, p2, p3, p4) -> Optional[Pt]:
    """Infinite lines (p1,p2) × (p3,p4) → intersection point or None
    (parallel or collinear). z is interpolated along line 1."""
    ax, ay = p2[0] - p1[0], p2[1] - p1[1]
    bx, by = p4[0] - p3[0], p4[1] - p3[1]
    denom = ax * by - ay * bx
    if abs(denom) < 1e-12:
        return None
    t = ((p3[0] - p1[0]) * by - (p3[1] - p1[1]) * bx) / denom
    point = (p1[0] + t * ax, p1[1] + t * ay, p1[2] + t * (p2[2] - p1[2]))
    return point


def line_circle_intersections(p1, p2, center, radius: float) -> List[Pt]:
    """Infinite line (p1,p2) × circle → 0, 1 (tangent) or 2 points, ordered
    along the line direction. Empty for a degenerate line or radius."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length <= TOL or radius <= TOL:
        return []
    fx, fy = p1[0] - center[0], p1[1] - center[1]
    # |p1 + t*d/|d| - c|^2 = r^2  →  quadratic in t (unit direction)
    ux, uy = dx / length, dy / length
    b = 2.0 * (fx * ux + fy * uy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4.0 * c
    if disc < -TOL:
        return []
    if disc < TOL:
        disc = 0.0
    root = math.sqrt(disc)
    if root <= TOL:  # tangent: exactly one intersection point
        t = -b / 2.0
        return [(p1[0] + t * ux, p1[1] + t * uy, p1[2])]
    out = []
    for t in sorted([(-b - root) / 2.0, (-b + root) / 2.0]):
        out.append((p1[0] + t * ux, p1[1] + t * uy, p1[2]))
    return out


def circle_circle_intersections(c1, r1: float, c2, r2: float):
    """Two circles → list of 0/1/2 intersection points, or None when the
    circles are coincident (infinitely many solutions)."""
    if r1 <= TOL or r2 <= TOL:
        return []
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    dist = math.hypot(dx, dy)
    if dist <= TOL:
        return None if abs(r1 - r2) <= TOL else []
    # radical line: x = (d^2 + r1^2 - r2^2) / (2d) along the center axis
    a = (dist * dist + r1 * r1 - r2 * r2) / (2.0 * dist)
    height_sq = r1 * r1 - a * a
    if height_sq < -TOL:
        return []
    if height_sq < TOL:
        height_sq = 0.0
    height = math.sqrt(height_sq)
    ux, uy = dx / dist, dy / dist
    base = (c1[0] + a * ux, c1[1] + a * uy, c1[2])
    if height <= TOL:
        return [base]
    perp = (-uy, ux)
    first = (base[0] + height * perp[0], base[1] + height * perp[1], base[2])
    second = (base[0] - height * perp[0], base[1] - height * perp[1], base[2])
    return [first, second]


# ---------------------------------------------------------------------------
# bounding boxes
# ---------------------------------------------------------------------------

def _bbox_points(points) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _union_bboxes(boxes) -> Tuple[float, float, float, float]:
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


def _is_full_sweep(start_angle: float, end_angle: float) -> bool:
    """Full-circle test (the M1 v0 convention: start == end means full)."""
    return (
        abs(normalize_deg(start_angle) - normalize_deg(end_angle)) <= TOL
        or _ccw_from(start_angle, end_angle) >= 360.0 - TOL
    )


def _arc_bbox(center, radius: float, start_angle: float, end_angle: float):
    """Exact arc bbox: endpoints + the axis extremes inside the CCW sweep."""
    points = [
        (
            center[0] + radius * math.cos(math.radians(start_angle)),
            center[1] + radius * math.sin(math.radians(start_angle)),
        ),
        (
            center[0] + radius * math.cos(math.radians(end_angle)),
            center[1] + radius * math.sin(math.radians(end_angle)),
        ),
    ]
    sweep = _ccw_from(start_angle, end_angle)
    if sweep >= 360.0 - TOL:
        sweep = 360.0
    for axis_angle in (0.0, 90.0, 180.0, 270.0):
        if _ccw_from(start_angle, axis_angle) <= sweep + TOL:
            points.append((
                center[0] + radius * math.cos(math.radians(axis_angle)),
                center[1] + radius * math.sin(math.radians(axis_angle)),
            ))
    return _bbox_points(points)


def _ellipse_axes(entity):
    """(semi-major length, semi-minor length, major axis angle deg) — the
    ``major_axis`` field is the center-relative semi-major vector (DXF)."""
    vec = entity.major_axis
    semi_a = math.hypot(vec[0], vec[1])
    semi_b = semi_a * float(entity.ratio)
    theta = angle_of((vec[0], vec[1]))
    return semi_a, semi_b, theta


def _ellipse_point(entity, param_deg: float) -> Pt:
    semi_a, _semi_b, theta = _ellipse_axes(entity)
    rad_p = math.radians(param_deg)
    rad_t = math.radians(theta)
    # point = C + a·cos(p)·û + b·sin(p)·v̂  (û = major dir, v̂ = û +90°)
    dx = semi_a * math.cos(rad_p) * math.cos(rad_t) - semi_a * entity.ratio * math.sin(rad_p) * math.sin(rad_t)
    dy = semi_a * math.cos(rad_p) * math.sin(rad_t) + semi_a * entity.ratio * math.sin(rad_p) * math.cos(rad_t)
    return (entity.center[0] + dx, entity.center[1] + dy, entity.center[2])


def _ellipse_bbox(entity):
    semi_a, semi_b, theta = _ellipse_axes(entity)
    if _is_full_sweep(entity.start_angle, entity.end_angle):
        # exact full-ellipse extents: x = sqrt(a²cos²θ + b²sin²θ), etc.
        rad_t = math.radians(theta)
        cos_t, sin_t = math.cos(rad_t), math.sin(rad_t)
        half_w = math.sqrt((semi_a * cos_t) ** 2 + (semi_b * sin_t) ** 2)
        half_h = math.sqrt((semi_a * sin_t) ** 2 + (semi_b * cos_t) ** 2)
        return (
            entity.center[0] - half_w, entity.center[1] - half_h,
            entity.center[0] + half_w, entity.center[1] + half_h,
        )
    # partial sweep: sampled approximation (72 samples + endpoints)
    sweep = _ccw_from(entity.start_angle, entity.end_angle)
    samples = [
        _ellipse_point(entity, entity.start_angle + sweep * (i / 72.0))
        for i in range(73)
    ]
    return _bbox_points(samples)


def _infinite_reach_points(p1, p2, both_ways: bool):
    """Bounding points for xline (both ways) / ray (through p2 and beyond)."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length <= TOL:
        return [tuple(p1)]
    ux, uy = dx / length, dy / length
    points = [tuple(p1), tuple(p2), (p1[0] + REACH * ux, p1[1] + REACH * uy, p1[2])]
    if both_ways:
        points.append((p1[0] - REACH * ux, p1[1] - REACH * uy, p1[2]))
    return points


def entity_bbox(entity, doc=None) -> Tuple[float, float, float, float]:
    """Axis-aligned bbox (min_x, min_y, max_x, max_y) of an entity.

    Kinds: line/xline/ray (infinite kinds bounded by ``REACH`` — documented
    approximation), circle/arc (exact), point, polyline (vertices + bulge
    arc extrema, exact), ellipse (exact for full, sampled for partial),
    text/mtext (rough estimates — no font metrics at M2), dim, insert and
    viewport. ``insert`` needs ``doc`` to resolve the block definition and
    unions the TRANSFORMED member bboxes; without ``doc`` (or for nested
    inserts) the position point alone is used (documented fallback).
    """
    kind = getattr(entity, "kind", "")
    if kind == "line":
        return _bbox_points([entity.p1, entity.p2])
    if kind == "circle":
        c, r = entity.center, entity.radius
        return (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    if kind == "arc":
        return _arc_bbox(entity.center, entity.radius,
                         entity.start_angle, entity.end_angle)
    if kind == "point":
        p = entity.position
        return (p[0], p[1], p[0], p[1])
    if kind == "polyline":
        boxes = []
        for start, end, bulge in polyline_segments(entity):
            if abs(bulge) > TOL:
                center, radius, s, e = arc_from_bulge(start, end, bulge)
                boxes.append(_arc_bbox(center, radius, s, e))
            else:
                boxes.append(_bbox_points([start, end]))
        if not boxes:
            v = entity.vertices[0]
            return (v[0], v[1], v[0], v[1])
        return _union_bboxes(boxes)
    if kind == "ellipse":
        return _ellipse_bbox(entity)
    if kind == "xline":
        return _bbox_points(_infinite_reach_points(entity.p1, entity.p2, True))
    if kind == "ray":
        return _bbox_points(_infinite_reach_points(entity.p1, entity.p2, False))
    if kind == "text":
        # rough estimate (no font metrics at M2): width ~ 2× height,
        # height ~ one text height, rotation ignored — documented.
        p, h = entity.position, entity.height
        return (p[0], p[1], p[0] + 2.0 * h, p[1] + h)
    if kind == "mtext":
        # width is stored; height estimated at 2.5 units (documented).
        p = entity.position
        return (p[0], p[1], p[0] + entity.width, p[1] + 2.5)
    if kind == "dim":
        points = [entity.p1, entity.p2, entity.offset_point]
        if entity.text_position is not None:
            points.append(entity.text_position)
        return _bbox_points(points)
    if kind == "insert":
        if doc is None:
            p = entity.position
            return (p[0], p[1], p[0], p[1])
        try:
            definition = doc.block(entity.name)
        except Exception:
            p = entity.position
            return (p[0], p[1], p[0], p[1])
        boxes = []
        for member in definition.entities:
            transformed = apply_insert_transform(
                member, definition.base_point, entity.position,
                entity.scale, entity.rotation,
            )
            if getattr(transformed, "kind", "") == "insert":
                # nested inserts: use the transformed reference point only
                # (no recursive resolution at M2 — documented)
                p = transformed.position
                boxes.append((p[0], p[1], p[0], p[1]))
            else:
                boxes.append(entity_bbox(transformed, doc))
        if not boxes:
            p = entity.position
            return (p[0], p[1], p[0], p[1])
        return _union_bboxes(boxes)
    if kind == "viewport":
        return _bbox_points([entity.p1, entity.p2])
    raise ValueError(f"entity_bbox: unsupported kind {kind!r}")


# ---------------------------------------------------------------------------
# per-kind transform field changes (journaled via update_entity)
# ---------------------------------------------------------------------------
#
# IMPORTANT (undo correctness): the ``*_changes`` functions are the ones
# commands use — they compute the new field values and the command applies
# them via ``Document.update_entity(eid, **changes)``, which journals the
# old values so UNDO restores geometry. Mutating entity attributes directly
# would bypass the undo journal (bcdoc does not trap attribute writes).
#
# M2 dispatch notes (documented limits):
# * polyline bulges are INVARIANT under move/rotate/uniform scale; only
#   MIRROR negates them;
# * ellipse major_axis is a center-relative vector: rotate rotates it as a
#   free vector; uniform scale multiplies its length; non-uniform scaling
#   would change the shape (needs a ratio recompute) and is NOT supported —
#   commands pass uniform factors only;
# * text SCALE multiplies the height; text/dim/insert ROTATE adds to their
#   rotation/angle fields; MIRROR reflects rotations as 2φ − rotation;
# * xline/ray endpoints move/rotate/scale like line endpoints (the
#   infinite extent follows the transformed direction).

def move_changes(entity, delta) -> dict:
    """Field changes translating ``entity`` by ``delta`` (apply via
    ``Document.update_entity`` inside a transaction — journaled + undoable)."""
    kind = getattr(entity, "kind", "")
    if kind == "line":
        return {"p1": move_pt(entity.p1, delta), "p2": move_pt(entity.p2, delta)}
    if kind in ("circle", "arc"):
        return {"center": move_pt(entity.center, delta)}
    if kind == "point":
        return {"position": move_pt(entity.position, delta)}
    if kind == "polyline":
        return {"vertices": [move_pt(v, delta) for v in entity.vertices]}
    if kind == "ellipse":
        return {"center": move_pt(entity.center, delta)}
    if kind in ("xline", "ray"):
        return {"p1": move_pt(entity.p1, delta), "p2": move_pt(entity.p2, delta)}
    if kind == "text":
        return {"position": move_pt(entity.position, delta)}
    if kind == "mtext":
        return {"position": move_pt(entity.position, delta)}
    if kind == "dim":
        return {
            "p1": move_pt(entity.p1, delta),
            "p2": move_pt(entity.p2, delta),
            "offset_point": move_pt(entity.offset_point, delta),
            "text_position": (None if entity.text_position is None
                              else move_pt(entity.text_position, delta)),
        }
    if kind == "insert":
        return {"position": move_pt(entity.position, delta)}
    if kind == "viewport":
        return {
            "center": move_pt(entity.center, delta),
            "p1": move_pt(entity.p1, delta),
            "p2": move_pt(entity.p2, delta),
        }
    raise ValueError(f"move_changes: unsupported kind {kind!r}")


def _rotate_free_vector(vec, angle_deg: float) -> Tuple[float, float, float]:
    """Rotate a direction vector about +Z (not about a base point)."""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return (
        vec[0] * cos_a - vec[1] * sin_a,
        vec[0] * sin_a + vec[1] * cos_a,
        vec[2],
    )


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
    if kind == "point":
        return {"position": rotate_pt(entity.position, center, angle_deg)}
    if kind == "polyline":
        return {
            "vertices": [
                rotate_pt(v, center, angle_deg) for v in entity.vertices
            ]
        }
    if kind == "ellipse":
        changes = {
            "center": rotate_pt(entity.center, center, angle_deg),
            "major_axis": _rotate_free_vector(entity.major_axis, angle_deg),
        }
        if not _is_full_sweep(entity.start_angle, entity.end_angle):
            changes["start_angle"] = normalize_deg(
                entity.start_angle + angle_deg)
            changes["end_angle"] = normalize_deg(entity.end_angle + angle_deg)
        return changes
    if kind in ("xline", "ray"):
        return {
            "p1": rotate_pt(entity.p1, center, angle_deg),
            "p2": rotate_pt(entity.p2, center, angle_deg),
        }
    if kind == "text":
        return {
            "position": rotate_pt(entity.position, center, angle_deg),
            "rotation": normalize_deg(entity.rotation + angle_deg),
        }
    if kind == "mtext":
        return {"position": rotate_pt(entity.position, center, angle_deg)}
    if kind == "dim":
        return {
            "p1": rotate_pt(entity.p1, center, angle_deg),
            "p2": rotate_pt(entity.p2, center, angle_deg),
            "offset_point": rotate_pt(entity.offset_point, center, angle_deg),
            "text_position": (None if entity.text_position is None
                              else rotate_pt(entity.text_position, center,
                                             angle_deg)),
            "angle": normalize_deg(entity.angle + angle_deg),
        }
    if kind == "insert":
        return {
            "position": rotate_pt(entity.position, center, angle_deg),
            "rotation": normalize_deg(entity.rotation + angle_deg),
        }
    if kind == "viewport":
        return {
            "center": rotate_pt(entity.center, center, angle_deg),
            "p1": rotate_pt(entity.p1, center, angle_deg),
            "p2": rotate_pt(entity.p2, center, angle_deg),
        }
    raise ValueError(f"rotate_changes: unsupported kind {kind!r}")


def scale_changes(entity, center, factor: float) -> dict:
    """Field changes scaling ``entity`` UNIFORMLY about ``center``.

    Non-uniform (per-axis) scaling is NOT supported: it would turn circles
    and arcs into ellipses and change the ellipse ratio — outside the M2
    analytic command set (documented; commands pass uniform factors only).

    A NEGATIVE uniform factor is a POINT REFLECTION = |factor| scale
    composed with a 180° rotation about the base point (determinant +1 —
    orientation-preserving, unlike a mirror): point fields follow
    ``scale_pt`` with the signed factor directly, radii and other
    magnitudes use ``abs(factor)`` (a negative radius is invalid geometry),
    and angular fields rotate by 180°. Polyline bulges are INVARIANT (no
    orientation flip).
    """
    kind = getattr(entity, "kind", "")
    flip = factor < 0.0  # 180° rotation about the base point
    if kind == "line":
        return {
            "p1": scale_pt(entity.p1, center, factor),
            "p2": scale_pt(entity.p2, center, factor),
        }
    if kind == "circle":
        return {
            "center": scale_pt(entity.center, center, factor),
            "radius": entity.radius * abs(factor),
        }
    if kind == "arc":
        changes = {
            "center": scale_pt(entity.center, center, factor),
            "radius": entity.radius * abs(factor),
        }
        if flip:
            changes["start_angle"] = normalize_deg(entity.start_angle + 180.0)
            changes["end_angle"] = normalize_deg(entity.end_angle + 180.0)
        return changes
    if kind == "point":
        return {"position": scale_pt(entity.position, center, factor)}
    if kind == "polyline":
        return {
            "vertices": [scale_pt(v, center, factor) for v in entity.vertices]
        }
    if kind == "ellipse":
        changes = {
            "center": scale_pt(entity.center, center, factor),
            "major_axis": tuple(
                component * factor for component in entity.major_axis
            ),
        }
        if flip and not _is_full_sweep(entity.start_angle, entity.end_angle):
            changes["start_angle"] = normalize_deg(
                entity.start_angle + 180.0)
            changes["end_angle"] = normalize_deg(entity.end_angle + 180.0)
        return changes
    if kind in ("xline", "ray"):
        return {
            "p1": scale_pt(entity.p1, center, factor),
            "p2": scale_pt(entity.p2, center, factor),
        }
    if kind == "text":
        changes = {
            "position": scale_pt(entity.position, center, factor),
            "height": entity.height * abs(factor),
        }
        if flip:
            changes["rotation"] = normalize_deg(entity.rotation + 180.0)
        return changes
    if kind == "mtext":
        return {
            "position": scale_pt(entity.position, center, factor),
            "width": entity.width * abs(factor),
        }
    if kind == "dim":
        changes = {
            "p1": scale_pt(entity.p1, center, factor),
            "p2": scale_pt(entity.p2, center, factor),
            "offset_point": scale_pt(entity.offset_point, center, factor),
            "text_position": (None if entity.text_position is None
                              else scale_pt(entity.text_position, center,
                                            factor)),
            "measurement": entity.measurement * abs(factor),
        }
        if flip:
            changes["angle"] = normalize_deg(entity.angle + 180.0)
        return changes
    if kind == "insert":
        return {
            "position": scale_pt(entity.position, center, factor),
            "scale": tuple(component * factor for component in entity.scale),
        }
    if kind == "viewport":
        return {
            "center": scale_pt(entity.center, center, factor),
            "p1": scale_pt(entity.p1, center, factor),
            "p2": scale_pt(entity.p2, center, factor),
            "view_height": entity.view_height * abs(factor),
        }
    raise ValueError(f"scale_changes: unsupported kind {kind!r}")


def _reflect_angle(angle_deg: float, axis_angle: float) -> float:
    """A mirrored direction at ``angle_deg`` points at 2φ − angle."""
    return normalize_deg(2.0 * axis_angle - angle_deg)


def mirror_changes(entity, p1, p2) -> dict:
    """Field changes mirroring ``entity`` across the line through p1-p2.

    Mirroring reverses orientation: arc sweep angles swap (start↔end) as
    they reflect, polyline bulge signs flip, and rotations/text angles
    reflect as ``2φ − angle`` (φ = axis angle). Full-sweep ellipse angles
    are left untouched.
    """
    kind = getattr(entity, "kind", "")
    axis_angle = angle_of((p2[0] - p1[0], p2[1] - p1[1]))
    if kind == "line":
        return {"p1": reflect_point(entity.p1, p1, p2),
                "p2": reflect_point(entity.p2, p1, p2)}
    if kind == "circle":
        return {"center": reflect_point(entity.center, p1, p2)}
    if kind == "arc":
        new_start = _reflect_angle(entity.end_angle, axis_angle)
        new_end = _reflect_angle(entity.start_angle, axis_angle)
        return {
            "center": reflect_point(entity.center, p1, p2),
            "start_angle": new_start,
            "end_angle": new_end,
        }
    if kind == "point":
        return {"position": reflect_point(entity.position, p1, p2)}
    if kind == "polyline":
        return {
            "vertices": [reflect_point(v, p1, p2) for v in entity.vertices],
            "bulges": [-float(b) for b in (entity.bulges or ())],
        }
    if kind == "ellipse":
        changes = {
            "center": reflect_point(entity.center, p1, p2),
            # reflect the semi-major vector as a free vector
            "major_axis": reflect_point(
                (entity.major_axis[0], entity.major_axis[1], 0.0),
                (0.0, 0.0, 0.0), (math.cos(math.radians(axis_angle)),
                                  math.sin(math.radians(axis_angle)), 0.0)),
        }
        if not _is_full_sweep(entity.start_angle, entity.end_angle):
            # mirrored param direction reverses: [s, e] → [-e, -s]
            changes["start_angle"] = normalize_deg(-entity.end_angle)
            changes["end_angle"] = normalize_deg(-entity.start_angle)
        return changes
    if kind in ("xline", "ray"):
        return {"p1": reflect_point(entity.p1, p1, p2),
                "p2": reflect_point(entity.p2, p1, p2)}
    if kind == "text":
        return {
            "position": reflect_point(entity.position, p1, p2),
            "rotation": _reflect_angle(entity.rotation, axis_angle),
        }
    if kind == "mtext":
        return {"position": reflect_point(entity.position, p1, p2)}
    if kind == "dim":
        return {
            "p1": reflect_point(entity.p1, p1, p2),
            "p2": reflect_point(entity.p2, p1, p2),
            "offset_point": reflect_point(entity.offset_point, p1, p2),
            "text_position": (None if entity.text_position is None
                              else reflect_point(entity.text_position, p1, p2)),
            "angle": _reflect_angle(entity.angle, axis_angle),
        }
    if kind == "insert":
        return {
            "position": reflect_point(entity.position, p1, p2),
            "rotation": _reflect_angle(entity.rotation, axis_angle),
        }
    if kind == "viewport":
        return {
            "center": reflect_point(entity.center, p1, p2),
            "p1": reflect_point(entity.p1, p1, p2),
            "p2": reflect_point(entity.p2, p1, p2),
        }
    raise ValueError(f"mirror_changes: unsupported kind {kind!r}")


# ---------------------------------------------------------------------------
# clone builders — NEW entities with fresh ids (COPY/ARRAYRECT/MIRROR/
# EXPLODE keep-source paths). Never used for in-place document mutation.
# ---------------------------------------------------------------------------

def _fresh_clone(entity):
    """New entity of the same kind/properties/geometry with a FRESH id
    (built through the kind's constructor so every coercer re-validates;
    handles grow with the entity registry)."""
    kwargs = {
        "layer": getattr(entity, "layer", "0"),
        "color": getattr(entity, "color", None),
        "linetype": getattr(entity, "linetype", "ByLayer"),
        "lineweight": getattr(entity, "lineweight", None),
        "space": getattr(entity, "space", "MODEL"),
    }
    kwargs.update(entity.geometry_dict())
    return type(entity)(**kwargs)


def _clone_with_changes(entity, changes):
    clone = _fresh_clone(entity)
    for field, value in changes.items():
        _set_field(clone, field, value)
    return clone


def clone_moved(entity, delta):
    """New entity of the same kind/geometry, translated by ``delta``.

    Used by COPY/ARRAYRECT/STRETCH-whole-entity paths: duplicates keep
    display properties (layer/color/linetype/lineweight/space) and receive
    a fresh id at construction; handles are assigned by the document on
    add_entity.
    """
    return _clone_with_changes(entity, move_changes(entity, delta))


def apply_mirror(entity, p1, p2):
    """New entity mirrored across the p1-p2 axis (MIRROR keep-source path;
    the same field math as ``mirror_changes`` — see its docstring)."""
    return _clone_with_changes(entity, mirror_changes(entity, p1, p2))


def apply_insert_transform(entity, base_point, position, scale, rotation):
    """New entity = ``entity`` placed by an Insert reference.

    The member geometry is transformed by: translate −base_point, scale
    per-axis by ``scale`` (sx, sy, sz), rotate ``rotation`` degrees CCW
    about +Z, then translate to ``position``. Properties (layer/color/
    linetype/lineweight) are carried unchanged — color/layer adoption for
    ByBlock members and layer "0" members is the EXPLODE command's job.

    Documented limits: circles/arcs take |sx| as their radius factor (a true
    per-axis stretch would need an ellipse representation — INSERT scale
    prompts validate uniform-friendly values); polyline bulges are kept
    unchanged (exact for rotation + uniform scale); text height takes |sy|,
    mtext width |sx|; nested inserts compose position/rotation and multiply
    scale per-axis. MIRROR inside a block (negative scales) is NOT modeled.
    """
    sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])
    rad = math.radians(float(rotation))
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    def place(p):
        dx = (p[0] - base_point[0]) * sx
        dy = (p[1] - base_point[1]) * sy
        dz = (p[2] - base_point[2]) * sz
        return (
            position[0] + dx * cos_r - dy * sin_r,
            position[1] + dx * sin_r + dy * cos_r,
            position[2] + dz,
        )

    def place_vec(v):
        dx, dy, dz = v[0] * sx, v[1] * sy, v[2] * sz
        return (
            dx * cos_r - dy * sin_r,
            dx * sin_r + dy * cos_r,
            dz,
        )

    kind = getattr(entity, "kind", "")
    if kind == "line":
        return _clone_with_changes(entity, {"p1": place(entity.p1),
                                             "p2": place(entity.p2)})
    if kind in ("circle", "arc"):
        # per-axis circle stretch would need an ellipse — take |sx| (documented)
        changes = {"center": place(entity.center),
                   "radius": entity.radius * abs(sx)}
        if kind == "arc":
            changes["start_angle"] = normalize_deg(
                entity.start_angle + float(rotation))
            changes["end_angle"] = normalize_deg(
                entity.end_angle + float(rotation))
        return _clone_with_changes(entity, changes)
    if kind == "point":
        return _clone_with_changes(entity, {"position": place(entity.position)})
    if kind == "polyline":
        return _clone_with_changes(
            entity, {"vertices": [place(v) for v in entity.vertices]})
    if kind == "ellipse":
        changes = {
            "center": place(entity.center),
            "major_axis": place_vec(entity.major_axis),
        }
        if not _is_full_sweep(entity.start_angle, entity.end_angle):
            changes["start_angle"] = normalize_deg(
                entity.start_angle + float(rotation))
            changes["end_angle"] = normalize_deg(
                entity.end_angle + float(rotation))
        return _clone_with_changes(entity, changes)
    if kind in ("xline", "ray"):
        return _clone_with_changes(entity, {"p1": place(entity.p1),
                                            "p2": place(entity.p2)})
    if kind == "text":
        return _clone_with_changes(entity, {
            "position": place(entity.position),
            "height": entity.height * abs(sy),
            "rotation": normalize_deg(entity.rotation + float(rotation)),
        })
    if kind == "mtext":
        return _clone_with_changes(entity, {
            "position": place(entity.position),
            "width": entity.width * abs(sx),
        })
    if kind == "dim":
        return _clone_with_changes(entity, {
            "p1": place(entity.p1),
            "p2": place(entity.p2),
            "offset_point": place(entity.offset_point),
            "text_position": (None if entity.text_position is None
                              else place(entity.text_position)),
            "angle": normalize_deg(entity.angle + float(rotation)),
            "measurement": entity.measurement * abs(sx),
        })
    if kind == "insert":
        return _clone_with_changes(entity, {
            "position": place(entity.position),
            "scale": (entity.scale[0] * sx, entity.scale[1] * sy,
                      entity.scale[2] * sz),
            "rotation": normalize_deg(entity.rotation + float(rotation)),
        })
    if kind == "viewport":
        return _clone_with_changes(entity, {
            "center": place(entity.center),
            "p1": place(entity.p1),
            "p2": place(entity.p2),
            "view_height": entity.view_height * abs(sy),
        })
    raise ValueError(f"apply_insert_transform: unsupported kind {kind!r}")


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


# convenience for commands/tests ----------------------------------------------

def distance_between(a, b) -> float:
    return dist_3d(
        (a[0], a[1], a[2]), (b[0], b[1], b[2])
    )
