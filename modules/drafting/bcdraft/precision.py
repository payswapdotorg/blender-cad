"""Precision input engine — object snaps, grid snap, ortho, direct distance
entry (contract: m2-module-contracts.md §4; scope §0-A).

Pure analytic 2D math on the XY plane (angles in degrees CCW about +Z; the
M3 kernel is not involved — ADR-0002). The module is the single snap engine
behind ``bcdraft._common.ask_point``:

* ``running_modes`` decodes the ``OSMODE`` setting into mode names;
* ``snap_candidates`` computes ALL candidates for the requested modes over
  entities in ``doc.current_space`` — entities on FROZEN layers are excluded
  (contract §2.2), entities in other spaces never participate, and ``insert``
  entities contribute their TRANSFORMED members (position/scale/rotation
  about the block base_point; the member transform helper lives here because
  ``bcdraft.geometry`` is W-D's file);
* ``resolve_point`` runs the binding chain grid snap -> ortho -> osnap for
  one mouse pick and returns marker data (mode + entity id) for the UI;
* ``dde_point`` implements direct distance entry (direction last_point ->
  pointer, ORTHO-snapped to the nearest 90°).

Mode coverage (M2 P0 set, per mode):

=============  ==============================================================
ENDPOINT       line endpoints; arc sweep endpoints; polyline vertices (the
               bulge-arc segment endpoints ARE the vertices); xline/ray base
               point p1 (their far end is infinite — p1 is the only fixed
               point).
MIDPOINT       line midpoint; arc sweep midpoint; polyline per-segment
               midpoints (straight chord midpoints and bulge-arc midpoints).
CENTER         circle / arc / ellipse centers.
QUADRANT       circle/arc points at 0/90/180/270 within the sweep; ellipse
               axis extremes (major/minor vector ends) within the sweep.
INTERSECTION   pairwise between DIFFERENT entities: line/xline/ray/
               polyline-segment/bulge-arc curves, incl. segment-domain
               tests (segments within [0,1], ray >= 0, xline unbounded, arc
               sweeps) and line x circle, circle x circle. Self-intersections
               within one store entity are skipped (adjacent polyline
               segments share vertices — that noise is not a snap); members
               of one INSERT do intersect each other.
TANGENT        tangent points on circles/arcs seen from ``from_point``
               (the last point; deferred per ux-spec §3.4).
PERPENDICULAR  foot of the perpendicular from ``from_point`` onto
               line/xline/ray/polyline segments (clamped to the segment
               domain); circle/arc radial-alignment points (the two points
               where the from_point-center line meets the circle — ranking
               by cursor distance delivers "nearest cursor").
INSERTION      insert reference positions and text/mtext positions.
=============  ==============================================================

Documented M2 limits (P0 scope): no NODE (point entities), no ellipse
intersection/tangent math (no analytic conic solver at M2), no candidates
for dim/viewport entities, one nesting level for insert members (nested
inserts inside blocks are skipped), and block members under NON-UNIFORM
scale keep only their exact affine candidates (endpoints/vertices/segment
midpoints/centers) — curved members become ellipses under non-uniform
scale and contribute their center only.

Settings consumed (contract §2.5): OSMODE (running modes), ORTHOMODE,
SNAPMODE, SNAPUNIT (the grid-SNAP lattice spacing — GRIDUNIT is the DISPLAY
grid), APERTURE (magnet radius in drawing units).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bccmd import Point
from bccmd.input import osnap_tokens  # the single token vocabulary (contract §3)

#: mode name -> OSMODE bit (AutoCAD bit-layout subset, contract §4).
#: INTERSECTION carries the AutoCAD INT bit 32, pinned by the §2.5 settings
#: table ("32 INT") and required by the default OSMODE 55 = 1+2+4+16+32
#: (END+MID+CEN+QUA+INT) — the §4 dict literal omits it; flagged to the TL.
OSMODE_BITS: dict = {
    "ENDPOINT": 1,
    "MIDPOINT": 2,
    "CENTER": 4,
    "QUADRANT": 16,
    "INTERSECTION": 32,
    "INSERTION": 64,
    "PERPENDICULAR": 128,
    "TANGENT": 1024,
}

#: OSMODE value meaning "no running osnap".
OSMODE_NONE = 0

TOL = 1e-9
_INF = math.inf


# ---------------------------------------------------------------------------
# tokens + running modes (contract §4)
# ---------------------------------------------------------------------------

def parse_osnap_tokens(text) -> List[str]:
    """Parse an osnap token list (``"END"``, ``"mid,cen"``) into canonical
    mode names; ``[]`` when nothing matches (contract §4).

    Delegates to :func:`bccmd.input.osnap_tokens` — bcdraft imports bccmd,
    never the reverse (contracts §1) — so the typed-token vocabulary has a
    single source of truth shared with ``bccmd.input.parse``.
    """
    return osnap_tokens(text)


def running_modes(doc) -> List[str]:
    """Decode the ``OSMODE`` setting into running osnap mode names (in
    OSMODE_BITS order); ``[]`` when osnap is off."""
    value = _setting(doc, "OSMODE", 0)
    try:
        osmode = int(value)
    except (TypeError, ValueError):
        return []
    return [name for name, bit in OSMODE_BITS.items() if osmode & bit]


@dataclass
class SnapResult:
    """One snap outcome: the resolved point plus marker data (which osnap
    mode produced it and which entity it belongs to — insert-member snaps
    attribute to the INSERT reference). ``mode``/``entity_id`` are None when
    the point came from the grid/ortho fallback chain (no marker)."""

    point: Point
    mode: Optional[str] = None
    entity_id: Optional[str] = None


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _as_point(value) -> Point:
    """Point or (x, y[, z]) sequence -> Point (never mutates the input)."""
    if isinstance(value, Point):
        return Point(value.x, value.y, value.z)
    try:
        coords = tuple(value)
    except TypeError:
        raise ValueError(f"not a point: {value!r}") from None
    if len(coords) not in (2, 3):
        raise ValueError(f"not a point: {value!r}")
    z = float(coords[2]) if len(coords) == 3 else 0.0
    return Point(float(coords[0]), float(coords[1]), z)


def _setting(doc, name, default):
    """Read one sysvar; any failure (missing settings store, unknown name)
    falls back to ``default`` — snapping must never crash on a host oddity."""
    settings = getattr(doc, "settings", None)
    if settings is None:
        return default
    try:
        return settings.get(name)
    except Exception:
        return default


def _flag(doc, name) -> bool:
    """Truthy-int setting read (on/off sysvars)."""
    try:
        return bool(int(_setting(doc, name, 0)))
    except (TypeError, ValueError):
        return False


def _layer_frozen(doc, layer_name) -> bool:
    """FROZEN layers are excluded from osnap (contract §2.2). OFF layers
    stay snappable (headless rule); LOCKED layers stay snappable too
    (locked restricts modification, not snapping)."""
    table = getattr(doc, "layers", None)
    if table is None:
        return False
    try:
        record = table.get(layer_name)
    except Exception:
        record = None
    return bool(record.frozen) if record is not None else False


def _space_entities(doc) -> list:
    """Entities in the CURRENT space (cross-space exclusion is inherent —
    entities of other spaces never participate, contract §4)."""
    try:
        return doc.entities_in_space(doc.current_space)
    except Exception:
        return []


def _dist2(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _normalize_deg(degrees: float) -> float:
    normalized = math.fmod(degrees, 360.0)
    if normalized < 0.0:
        normalized += 360.0
    if abs(normalized - 360.0) < TOL:
        normalized = 0.0
    return normalized


def _sweep(amin: float, amax: float) -> float:
    """CCW sweep from amin to amax (degrees, in (0, 360])."""
    sweep = _normalize_deg(amax - amin)
    return sweep if sweep > TOL else 360.0


def _in_sweep(theta: float, amin: float, amax: float, full: bool) -> bool:
    """Is polar angle ``theta`` on the CCW arc amin -> amax?"""
    if full:
        return True
    return _normalize_deg(theta - amin) <= _sweep(amin, amax) + 1e-9


def _polar(center, radius: float, angle_deg: float):
    """Point on the circle (center, radius) at polar ``angle_deg``."""
    rad = math.radians(angle_deg)
    return (
        center[0] + radius * math.cos(rad),
        center[1] + radius * math.sin(rad),
        center[2],
    )


def _bulge_arc(p1, p2, bulge: float):
    """AutoCAD bulge geometry (contract §2.1): bulge = tan(delta/4), positive
    = CCW from p1 to p2. Returns (center, radius, start_angle, end_angle)
    with end = start + delta (unnormalized, CCW); None for straight or
    degenerate segments."""
    bulge = float(bulge)
    if abs(bulge) < 1e-12:
        return None
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if chord < TOL:
        return None
    delta = 4.0 * math.atan(bulge)  # signed included angle
    half = delta / 2.0
    sin_half = math.sin(half)
    if abs(sin_half) < 1e-12:
        return None
    radius = abs((chord / 2.0) / sin_half)
    ux = (p2[0] - p1[0]) / chord
    uy = (p2[1] - p1[1]) / chord
    mid_x = (p1[0] + p2[0]) / 2.0
    mid_y = (p1[1] + p2[1]) / 2.0
    # perpendicular offset from the chord midpoint: the LEFT normal for a
    # positive (CCW) delta, the RIGHT one for negative
    offset = (chord / 2.0) / math.tan(half)
    center = (mid_x - uy * offset, mid_y + ux * offset, p1[2])
    start = math.degrees(math.atan2(p1[1] - center[1], p1[0] - center[0]))
    return center, radius, start, start + math.degrees(delta)


# ---------------------------------------------------------------------------
# entity -> normalized geometry parts
# ---------------------------------------------------------------------------

class _Parts:
    """Normalized snap geometry for one entity (or one expanded insert).

    segments: ``(p1, p2, tmin, tmax)`` — param point = p1 + t*(p2-p1);
    xline is unbounded, ray is t >= 0, finite segments are [0, 1].
    circles:  ``(center, radius, amin, amax, full)`` — full circles and arcs
    (bulge-arc segments included); CCW polar sweep window.
    ellipses: ``(center, major_vec, minor_vec, amin, amax, full)`` — param
    angles: point(t) = center + major*cos t + minor*sin t.
    vertices / singles / centers: plain (x, y, z) tuples.
    """

    __slots__ = ("segments", "circles", "ellipses", "vertices", "singles",
                 "centers")

    def __init__(self):
        self.segments: List[tuple] = []
        self.circles: List[tuple] = []
        self.ellipses: List[tuple] = []
        self.vertices: List[tuple] = []
        self.singles: List[tuple] = []
        self.centers: List[tuple] = []


def _entity_parts(entity) -> _Parts:
    parts = _Parts()
    kind = entity.kind
    if kind == "line":
        parts.segments.append((entity.p1, entity.p2, 0.0, 1.0))
        parts.vertices.extend((entity.p1, entity.p2))
    elif kind == "xline":
        parts.segments.append((entity.p1, entity.p2, -_INF, _INF))
        parts.vertices.append(entity.p1)
    elif kind == "ray":
        parts.segments.append((entity.p1, entity.p2, 0.0, _INF))
        parts.vertices.append(entity.p1)
    elif kind == "circle":
        center = entity.center
        parts.circles.append((center, float(entity.radius), 0.0, 360.0, True))
        parts.centers.append(center)
    elif kind == "arc":
        center = entity.center
        a_min = float(entity.start_angle)
        a_max = float(entity.end_angle)
        parts.circles.append((center, float(entity.radius), a_min, a_max, False))
        parts.centers.append(center)
        parts.vertices.append(_polar(center, float(entity.radius), a_min))
        parts.vertices.append(_polar(center, float(entity.radius), a_max))
    elif kind == "polyline":
        _polyline_parts(entity, parts)
    elif kind == "ellipse":
        center = entity.center
        parts.centers.append(center)
        axis = entity.major_axis
        ratio = float(entity.ratio)
        major = (float(axis[0]), float(axis[1]))
        minor = (-major[1] * ratio, major[0] * ratio)
        a_min = float(entity.start_angle)
        a_max = float(entity.end_angle)
        full = _sweep(a_min, a_max) >= 360.0 - TOL
        parts.ellipses.append((center, major, minor, a_min, a_max, full))
    elif kind in ("text", "mtext", "insert"):
        parts.singles.append(entity.position)
    # point (NODE — not in the M2 P0 set), dim, viewport: no candidates
    return parts


def _polyline_parts(entity, parts: _Parts) -> None:
    vertices = [tuple(v) for v in entity.vertices]
    parts.vertices.extend(vertices)
    count = len(vertices)
    if count == 0:
        return
    bulges = [float(b) for b in entity.bulges] if entity.bulges else []
    last = count - 1 if entity.closed else count - 2
    for i in range(max(last + 1, 0)):
        a = vertices[i]
        b = vertices[(i + 1) % count]
        bulge = bulges[i] if i < len(bulges) else 0.0
        if abs(bulge) < 1e-12:
            parts.segments.append((a, b, 0.0, 1.0))
        else:
            arc = _bulge_arc(a, b, bulge)
            if arc is not None:
                parts.circles.append((arc[0], arc[1], arc[2], arc[3], False))


# -- insert member transform (local helper; bcdraft.geometry is W-D's) ------

def _insert_transform(ref, base_point):
    """Local block -> world transform for one insert reference (contract
    §2.3): ``world = position + R(rotation) * S(scale) * (local - base)``
    (rotation CCW about +Z, scale componentwise).

    Returns ``(tx, vec, uniform, angle_shift, scale_abs)``:

    * ``tx(p)`` maps a local POINT to world;
    * ``vec(v)`` maps a local VECTOR (no translation, no base offset);
    * ``uniform`` — sx == sy (same sign): curved members stay circular and
      are transformed exactly;
    * ``angle_shift`` — added to polar angles (the rotation, plus 180° for
      a negative uniform scale);
    * ``scale_abs`` — |sx|, the radius factor for uniform scales.
    """
    scale = ref.scale
    sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])
    rotation = float(ref.rotation)
    rad = math.radians(rotation)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    bx, by, bz = base_point[0], base_point[1], base_point[2]
    position = ref.position
    px, py, pz = position[0], position[1], position[2]

    def tx(p):
        dx = (p[0] - bx) * sx
        dy = (p[1] - by) * sy
        return (
            px + dx * cos_r - dy * sin_r,
            py + dx * sin_r + dy * cos_r,
            pz + (p[2] - bz) * sz,
        )

    def vec(v):
        dx = v[0] * sx
        dy = v[1] * sy
        return (dx * cos_r - dy * sin_r, dx * sin_r + dy * cos_r)

    uniform = abs(sx - sy) <= TOL and abs(sx) > TOL
    angle_shift = rotation + (180.0 if sx < 0.0 else 0.0)
    return tx, vec, uniform, angle_shift, abs(sx)


def _insert_parts(doc, ref) -> _Parts:
    """All members of one insert reference, transformed to world space
    (contract §4: inserts contribute their transformed members; snap
    attribution stays with the INSERT entity id)."""
    parts = _Parts()
    parts.singles.append(ref.position)  # INSERTION candidate
    try:
        definition = doc.block(ref.name)
    except Exception:
        return parts  # dangling reference: only the insertion point snaps
    tx, vec, uniform, angle_shift, scale_abs = _insert_transform(
        ref, definition.base_point)
    for member in definition.entities:
        if _layer_frozen(doc, member.layer):
            continue
        kind = member.kind
        if kind == "line":
            w1, w2 = tx(member.p1), tx(member.p2)
            parts.segments.append((w1, w2, 0.0, 1.0))
            parts.vertices.extend((w1, w2))
        elif kind == "xline":
            w1, w2 = tx(member.p1), tx(member.p2)
            parts.segments.append((w1, w2, -_INF, _INF))
            parts.vertices.append(w1)
        elif kind == "ray":
            w1, w2 = tx(member.p1), tx(member.p2)
            parts.segments.append((w1, w2, 0.0, _INF))
            parts.vertices.append(w1)
        elif kind == "polyline":
            _insert_polyline_parts(member, parts, tx, uniform, angle_shift,
                                   scale_abs)
        elif kind in ("circle", "arc"):
            world_center = tx(member.center)
            parts.centers.append(world_center)
            if uniform:
                if kind == "circle":
                    parts.circles.append(
                        (world_center, float(member.radius) * scale_abs,
                         0.0, 360.0, True))
                else:
                    parts.circles.append(
                        (world_center, float(member.radius) * scale_abs,
                         float(member.start_angle) + angle_shift,
                         float(member.end_angle) + angle_shift, False))
            # non-uniform scale: curved members contribute their center only
        elif kind == "ellipse":
            world_center = tx(member.center)
            parts.centers.append(world_center)
            if uniform:
                axis = member.major_axis
                ratio = float(member.ratio)
                major = vec((axis[0], axis[1]))
                minor = vec((-axis[1] * ratio, axis[0] * ratio))
                a_min = float(member.start_angle)
                a_max = float(member.end_angle)
                full = _sweep(a_min, a_max) >= 360.0 - TOL
                parts.ellipses.append(
                    (world_center, major, minor, a_min, a_max, full))
        elif kind in ("text", "mtext"):
            parts.singles.append(tx(member.position))
        # point members and nested inserts inside blocks: skipped (documented)
    return parts


def _insert_polyline_parts(member, parts: _Parts, tx, uniform, angle_shift,
                           scale_abs) -> None:
    """Transformed polyline member: vertices and straight segments are exact
    under any affine transform; bulge-arc segments stay circular ONLY under
    uniform scale (rotation + uniform scale maps circles to circles) — the
    local arc is transformed via center/radius/angles. Non-uniform bulge
    segments become ellipses and are skipped (documented M2 limit)."""
    vertices = [tx(v) for v in member.vertices]
    parts.vertices.extend(vertices)
    count = len(vertices)
    if not count:
        return
    local = [tuple(v) for v in member.vertices]
    bulges = [float(b) for b in member.bulges] if member.bulges else []
    last = count - 1 if member.closed else count - 2
    for i in range(max(last + 1, 0)):
        a = vertices[i]
        b = vertices[(i + 1) % count]
        bulge = bulges[i] if i < len(bulges) else 0.0
        if abs(bulge) < 1e-12:
            parts.segments.append((a, b, 0.0, 1.0))
        elif uniform:
            arc = _bulge_arc(local[i], local[(i + 1) % count], bulge)
            if arc is not None:
                parts.circles.append(
                    (tx(arc[0]), arc[1] * scale_abs,
                     arc[2] + angle_shift, arc[3] + angle_shift, False))


# ---------------------------------------------------------------------------
# per-mode candidate collection
# ---------------------------------------------------------------------------

_QUADRANT_ANGLES = (0.0, 90.0, 180.0, 270.0)


def _finite(seg) -> bool:
    """A bounded [0, 1] segment (lines and polyline segments — xline/ray
    have no midpoint)."""
    return seg[2] > -_INF and seg[3] < _INF


def _add(out: list, point: tuple, mode: str, entity_id) -> None:
    out.append((point, mode, entity_id))


def _collect_simple(out: list, owner_id, parts: _Parts, mode: str,
                    from_point) -> None:
    """Candidates for every non-intersection mode over one entity's parts."""
    if mode == "ENDPOINT":
        for vertex in parts.vertices:
            _add(out, vertex, mode, owner_id)
    elif mode == "MIDPOINT":
        for seg in parts.segments:
            if _finite(seg):
                p1, p2 = seg[0], seg[1]
                _add(out, ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0,
                           (p1[2] + p2[2]) / 2.0), mode, owner_id)
        for center, radius, a_min, a_max, full in parts.circles:
            if not full:
                mid_angle = a_min + _sweep(a_min, a_max) / 2.0
                _add(out, _polar(center, radius, mid_angle), mode, owner_id)
    elif mode == "CENTER":
        for center in parts.centers:
            _add(out, center, mode, owner_id)
    elif mode == "QUADRANT":
        for center, radius, a_min, a_max, full in parts.circles:
            for angle in _QUADRANT_ANGLES:
                if _in_sweep(angle, a_min, a_max, full):
                    _add(out, _polar(center, radius, angle), mode, owner_id)
        for center, major, minor, a_min, a_max, full in parts.ellipses:
            for angle in _QUADRANT_ANGLES:
                if _in_sweep(angle, a_min, a_max, full):
                    rad = math.radians(angle)
                    _add(out, (
                        center[0] + major[0] * math.cos(rad) + minor[0] * math.sin(rad),
                        center[1] + major[1] * math.cos(rad) + minor[1] * math.sin(rad),
                        center[2],
                    ), mode, owner_id)
    elif mode == "TANGENT":
        if from_point is None:
            return  # deferred snaps need a from-point (the last point)
        for circle in parts.circles:
            for point in _tangent_points(circle, from_point):
                _add(out, point, mode, owner_id)
    elif mode == "PERPENDICULAR":
        if from_point is None:
            return
        for seg in parts.segments:
            point = _perpendicular_foot(seg, from_point)
            if point is not None:
                _add(out, point, mode, owner_id)
        for circle in parts.circles:
            for point in _radial_alignment(circle, from_point):
                _add(out, point, mode, owner_id)
    elif mode == "INSERTION":
        for single in parts.singles:
            _add(out, single, mode, owner_id)
    # INTERSECTION is handled cross-entity by _collect_intersections


def _tangent_points(circle, from_pt) -> List[tuple]:
    """Tangent points on (center, radius, amin, amax, full) seen from
    ``from_pt`` (outside: two; on the circle: the point itself; inside/center
    of the circle: none). Arc sweeps are respected."""
    center, radius, a_min, a_max, full = circle
    dx = from_pt[0] - center[0]
    dy = from_pt[1] - center[1]
    distance = math.hypot(dx, dy)
    if distance < TOL or distance < radius - TOL:
        return []
    if abs(distance - radius) <= TOL:
        # from-point ON the circle: the tangent point is the point itself
        candidates = [(from_pt[0], from_pt[1], center[2])]
    else:
        alpha = math.atan2(dy, dx)
        beta = math.acos(radius / distance)
        candidates = [
            _polar(center, radius, math.degrees(alpha + beta)),
            _polar(center, radius, math.degrees(alpha - beta)),
        ]
    if full:
        return candidates
    out = []
    for point in candidates:
        theta = math.degrees(math.atan2(point[1] - center[1],
                                         point[0] - center[0]))
        if _in_sweep(theta, a_min, a_max, full):
            out.append(point)
    return out


def _perpendicular_foot(seg, from_pt):
    """Foot of the perpendicular from ``from_pt`` onto a segment, clamped to
    its domain ([0,1] segments clamp to the segment; ray clamps to t >= 0;
    xline is unclamped). None for degenerate zero-length segments."""
    p1, p2, t_min, t_max = seg
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length_sq = dx * dx + dy * dy
    if length_sq < TOL * TOL:
        return None
    t = ((from_pt[0] - p1[0]) * dx + (from_pt[1] - p1[1]) * dy) / length_sq
    t = max(t_min, min(t, t_max))
    return (
        p1[0] + t * dx,
        p1[1] + t * dy,
        p1[2] + t * (p2[2] - p1[2]),
    )


def _radial_alignment(circle, from_pt) -> List[tuple]:
    """The two circle points radially aligned with ``from_pt`` (a line from
    the from-point perpendicular to the circle passes through the center);
    ranking by cursor distance keeps the one "nearest cursor"."""
    center, radius, a_min, a_max, full = circle
    dx = from_pt[0] - center[0]
    dy = from_pt[1] - center[1]
    distance = math.hypot(dx, dy)
    if distance < TOL:
        return []
    ux, uy = dx / distance, dy / distance
    near = (center[0] + radius * ux, center[1] + radius * uy, center[2])
    far = (center[0] - radius * ux, center[1] - radius * uy, center[2])
    if full:
        return [near, far]
    out = []
    for point in (near, far):
        theta = math.degrees(math.atan2(point[1] - center[1],
                                         point[0] - center[0]))
        if _in_sweep(theta, a_min, a_max, full):
            out.append(point)
    return out


# ---------------------------------------------------------------------------
# intersections (pairwise across entities; segments + circles)
# ---------------------------------------------------------------------------

def _seg_point(seg, t: float) -> tuple:
    p1, p2 = seg[0], seg[1]
    return (
        p1[0] + t * (p2[0] - p1[0]),
        p1[1] + t * (p2[1] - p1[1]),
        p1[2] + t * (p2[2] - p1[2]),
    )


def _seg_seg(s1, s2) -> List[tuple]:
    p1 = s1[0]
    q1 = s2[0]
    rx = s1[1][0] - p1[0]
    ry = s1[1][1] - p1[1]
    sx = s2[1][0] - q1[0]
    sy = s2[1][1] - q1[1]
    denom = rx * sy - ry * sx
    if abs(denom) < TOL:
        return []  # parallel or collinear (overlap gives no point candidate)
    qpx = q1[0] - p1[0]
    qpy = q1[1] - p1[1]
    t = (qpx * sy - qpy * sx) / denom
    u = (qpx * ry - qpy * rx) / denom
    if not (s1[2] - 1e-9 <= t <= s1[3] + 1e-9):
        return []
    if not (s2[2] - 1e-9 <= u <= s2[3] + 1e-9):
        return []
    return [_seg_point(s1, t)]


def _seg_circle(seg, circle) -> List[tuple]:
    p1 = seg[0]
    p2 = seg[1]
    center, radius, a_min, a_max, full = circle
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    fx = p1[0] - center[0]
    fy = p1[1] - center[1]
    a = dx * dx + dy * dy
    if a < TOL * TOL:
        return []
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return []
    sqrt_disc = math.sqrt(disc)
    roots = [(-b - sqrt_disc) / (2.0 * a)]
    if sqrt_disc > 0.0:
        roots.append((-b + sqrt_disc) / (2.0 * a))
    out = []
    for t in roots:
        if not (seg[2] - 1e-9 <= t <= seg[3] + 1e-9):
            continue
        point = _seg_point(seg, t)
        if not full:
            theta = math.degrees(math.atan2(point[1] - center[1],
                                             point[0] - center[0]))
            if not _in_sweep(theta, a_min, a_max, full):
                continue
        out.append(point)
    return out


def _circle_circle(c1, c2) -> List[tuple]:
    center1, r1, a_min1, a_max1, full1 = c1
    center2, r2, a_min2, a_max2, full2 = c2
    dx = center2[0] - center1[0]
    dy = center2[1] - center1[1]
    distance = math.hypot(dx, dy)
    if distance < TOL:
        return []  # concentric: no radical-line intersection points
    if distance > r1 + r2 + TOL or distance < abs(r1 - r2) - TOL:
        return []
    # radical line: distance along c1->c2 to the chord foot
    a = (distance * distance + r1 * r1 - r2 * r2) / (2.0 * distance)
    h_sq = r1 * r1 - a * a
    h = math.sqrt(h_sq) if h_sq > 0.0 else 0.0
    foot_x = center1[0] + (dx / distance) * a
    foot_y = center1[1] + (dy / distance) * a
    points = []
    if h > TOL:
        points.append((foot_x - (dy / distance) * h,
                       foot_y + (dx / distance) * h, center1[2]))
        points.append((foot_x + (dy / distance) * h,
                       foot_y - (dx / distance) * h, center1[2]))
    else:
        points.append((foot_x, foot_y, center1[2]))  # tangent circles
    out = []
    for point in points:
        theta1 = math.degrees(math.atan2(point[1] - center1[1],
                                         point[0] - center1[0]))
        theta2 = math.degrees(math.atan2(point[1] - center2[1],
                                         point[0] - center2[0]))
        if not _in_sweep(theta1, a_min1, a_max1, full1):
            continue
        if not _in_sweep(theta2, a_min2, a_max2, full2):
            continue
        out.append(point)
    return out


def _curves(parts: _Parts) -> List[tuple]:
    """(kind, payload) curve list — kind "seg"/"circle" with the raw tuple."""
    curves = [("seg", seg) for seg in parts.segments]
    curves.extend(("circle", circle) for circle in parts.circles)
    return curves


def _intersect(curves_a, curves_b, out: list, mode: str, owner_id) -> None:
    for kind_a, a in curves_a:
        for kind_b, b in curves_b:
            if kind_a == "seg" and kind_b == "seg":
                points = _seg_seg(a, b)
            elif kind_a == "seg":
                points = _seg_circle(a, b)
            elif kind_b == "seg":
                points = _seg_circle(b, a)
            else:
                points = _circle_circle(a, b)
            for point in points:
                _add(out, point, mode, owner_id)


def _collect_intersections(out: list, owners: list, mode: str) -> None:
    """Pairwise curve intersections ACROSS entities (plus between the
    members of one expanded insert); same-entity pairs of a store entity are
    skipped (adjacent polyline segments share vertices — documented)."""
    prepared = [(owner_id, _curves(parts), allow_self)
                for owner_id, parts, allow_self in owners]
    for index, (owner_id, curves, allow_self) in enumerate(prepared):
        if allow_self:
            for i in range(len(curves)):
                for j in range(i + 1, len(curves)):
                    _intersect([curves[i]], [curves[j]], out, mode, owner_id)
        for other_id, other_curves, _ in prepared[index + 1:]:
            _intersect(curves, other_curves, out, mode, owner_id)


# ---------------------------------------------------------------------------
# public: candidates
# ---------------------------------------------------------------------------

def snap_candidates(doc, modes, cursor, aperture: float,
                    from_point=None) -> List[SnapResult]:
    """ALL snap candidates for ``modes`` ranked by distance to ``cursor``.

    Computation per mode over entities in ``doc.current_space`` (entities on
    frozen layers excluded; inserts expanded to their transformed members —
    candidates attribute to the insert's id). Candidates beyond ``aperture``
    drawing units from the cursor are dropped; survivors are ranked by
    ascending cursor distance (collection order breaks ties, stable).
    """
    cursor_pt = _as_point(cursor)
    from_pt = None
    if from_point is not None:
        anchor = _as_point(from_point)
        from_pt = (anchor.x, anchor.y, anchor.z)  # tuple: mode math indexes it
    modes = [str(m).upper() for m in (modes or [])]
    raw: List[tuple] = []

    owners: List[tuple] = []  # (entity_id, parts, allow_self_intersections)
    for entity in _space_entities(doc):
        if _layer_frozen(doc, entity.layer):
            continue
        if entity.kind == "insert":
            owners.append((entity.id, _insert_parts(doc, entity), True))
        else:
            owners.append((entity.id, _entity_parts(entity), False))

    intersection_requested = "INTERSECTION" in modes
    for owner_id, parts, _allow_self in owners:
        for mode in modes:
            if mode == "INTERSECTION":
                continue
            _collect_simple(raw, owner_id, parts, mode, from_pt)
    if intersection_requested:
        _collect_intersections(raw, owners, "INTERSECTION")

    try:
        limit = float(aperture) + 1e-9
    except (TypeError, ValueError):
        limit = 1e-9
    ranked: List[tuple] = []
    for order, (point, mode, entity_id) in enumerate(raw):
        distance = _dist2((cursor_pt.x, cursor_pt.y), point)
        if distance <= limit:
            ranked.append((distance, order, point, mode, entity_id))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [
        SnapResult(point=Point(p[0], p[1], p[2]), mode=mode, entity_id=eid)
        for _distance, _order, p, mode, eid in ranked
    ]


# ---------------------------------------------------------------------------
# public: the binding chain (grid -> ortho -> osnap) + direct distance entry
# ---------------------------------------------------------------------------

def _grid_point(doc, point: Point) -> Point:
    """SNAPMODE on: nearest SNAPUNIT lattice point on both axes (half-up
    rounding; z passes through). A non-positive SNAPUNIT disables the snap
    (guard — division by zero would otherwise crash the chain)."""
    if not _flag(doc, "SNAPMODE"):
        return point
    unit = _setting(doc, "SNAPUNIT", 1.0)
    try:
        unit = float(unit)
    except (TypeError, ValueError):
        return point
    if not unit > TOL:
        return point
    return Point(
        math.floor(point.x / unit + 0.5) * unit,
        math.floor(point.y / unit + 0.5) * unit,
        point.z,
    )


def _ortho_point(doc, point: Point, last: Optional[Point],
                 pointer: Optional[Point]) -> Point:
    """ORTHOMODE on with a last point: project onto the horizontal/vertical
    axis through the last point (the dominant component wins; equal deltas
    resolve horizontally). When the point coincides with the last point the
    pointer provides the direction (the projected point is the anchor either
    way — the axis choice is what the pointer disambiguates)."""
    if not _flag(doc, "ORTHOMODE") or last is None:
        return point
    dx = point.x - last.x
    dy = point.y - last.y
    if abs(dx) < TOL and abs(dy) < TOL:
        # the pick coincides with the anchor: the pointer decides which
        # axis the constraint reads (contract §4 "direction taken from
        # pointer"), but both axes project the anchor onto itself
        return Point(last.x, last.y, point.z)
    if abs(dx) >= abs(dy):
        return Point(point.x, last.y, point.z)
    return Point(last.x, point.y, point.z)


def resolve_point(doc, raw, last_point=None, one_shot=None,
                  pointer=None) -> SnapResult:
    """Resolve one mouse pick through the binding chain (contract §4):
    grid snap -> ortho -> osnap.

    The osnap search runs from the RAW cursor (the magnet must find what
    the user is pointing at — an osnap hit overrides the grid/ortho result,
    matching the AutoCAD osnap-beats-ortho/grid behavior; the contract's
    grid->ortho->osnap order is the order in which the FALLBACK point is
    built). When no candidate is within the aperture the grid/ortho point is
    returned with ``mode=None`` (no marker).

    ``one_shot`` (the pending override list) is used for this resolution
    only when non-empty; consumption is the caller's job
    (``bcdraft._common.ask_point`` clears ``ctx.pending_osnap``). TANGENT and
    PERPENDICULAR use ``last_point`` as their from-point.
    """
    raw_pt = _as_point(raw)
    last_pt = _as_point(last_point) if last_point is not None else None
    pointer_pt = _as_point(pointer) if pointer is not None else None

    fallback = _grid_point(doc, raw_pt)
    fallback = _ortho_point(doc, fallback, last_pt, pointer_pt)

    modes = [m for m in (one_shot or []) if m] if one_shot else running_modes(doc)
    if modes:
        try:
            aperture = float(_setting(doc, "APERTURE", 0.5))
        except (TypeError, ValueError):
            aperture = 0.5
        candidates = snap_candidates(doc, modes, raw_pt, aperture,
                                     from_point=last_pt)
        if candidates:
            return candidates[0]
    return SnapResult(point=Point(fallback.x, fallback.y, fallback.z),
                      mode=None, entity_id=None)


def dde_point(last_point, distance: float, pointer, doc) -> Point:
    """Direct distance entry (contract §4): ``last_point`` moved ``distance``
    units along the direction last_point -> pointer (angle 0 when the
    pointer is unknown). ORTHOMODE snaps the direction to the nearest 90°
    (half-up at exact 45° diagonals). A negative distance extends opposite
    the direction; zero returns the anchor; z keeps the anchor's z.
    """
    anchor = _as_point(last_point)
    if pointer is None:
        angle_deg = 0.0
    else:
        pointer_pt = _as_point(pointer)
        angle_deg = math.degrees(math.atan2(pointer_pt.y - anchor.y,
                                            pointer_pt.x - anchor.x))
    if _flag(doc, "ORTHOMODE"):
        angle_deg = math.floor(angle_deg / 90.0 + 0.5) * 90.0
    step = float(distance)
    quadrant = int(round(angle_deg / 90.0)) % 4
    if abs(angle_deg - quadrant * 90.0) <= 1e-9:
        # axis-exact quadrants bypass trig: typed DDE straight up/down/
        # left/right keeps the orthogonal coordinate EXACT (cos(90°) carries
        # ~1e-16 noise that surfaces as 1e-15 drift near the origin)
        ux, uy = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[quadrant]
    else:
        rad = math.radians(angle_deg)
        ux, uy = math.cos(rad), math.sin(rad)
    return Point(
        anchor.x + step * ux,
        anchor.y + step * uy,
        anchor.z,
    )
