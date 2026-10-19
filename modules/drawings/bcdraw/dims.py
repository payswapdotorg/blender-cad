"""Dimension geometry engine — the bcdraw core (contracts §5.1;
inventory FP-ANN-001/002/015).

Pure analytic 2D construction of dimension geometry from definition points
(no kernel, no bpy — ADR-0002). Two constructors build a
:class:`DimensionGeometry` (the display/interchange-ready layout of one
dimension) and :func:`resolve_dimension` binds a stored :class:`bcdoc.Dim`
entity to geometry + formatted text, including ASSOCIATIVITY: when
``dim.measured_id`` references a live LINE entity, its CURRENT endpoints
drive the geometry (FP-ANN-015; the free-dim path uses the stored points).

Construction rules (binding — contracts §5.1 + W-C task letter):

- ``angle_deg`` is the MEASUREMENT DIRECTION (0 = horizontal, 90 = vertical);
  measurement = |projection of (p2 - p1) on that axis|;
- the dimension line passes through ``offset_point``; its endpoints are the
  projections of the measured points onto that line (so the dim line is
  always parallel to the measurement axis and spans the projected points);
- extension lines run from each measured point TOWARD the dimension line,
  starting ``dimexo`` off the point and ending ``dimexe`` past the dim line
  (perpendicular offsets, sign = which side the dim line is on);
- arrows: 3-point chevrons of length ``dimasz`` at the dim-line ends —
  [tip, wing, wing] — tips ON the ends, pointing outward along the dim
  line, wings folded back; the wing half-spread is ``0.25 * dimasz``
  (a documented presentation choice: the contract pins only the length);
- text: the dim-line midpoint offset ``dimtxt * 0.5`` along the LEFT normal
  of the q1 -> q2 travel direction ("above" the dim line as drawn);
  ``resolve_dimension`` moves it to ``dim.text_position`` when the dim
  carries a placement override;
- ``dimscale`` multiplies every SIZE above (exo/exe/asz/txt); the
  measurement itself is never scaled.

Documented M2 limits:

- dimensions are constructed in the XY plane — z coordinates are carried
  through for storage/display but never enter the math;
- only "linear" and "aligned" dim types exist (radius/diameter/angular/
  ordinate are P1+ per inventory FP-ANN-003..012);
- associated entities must be LINEs at v0 (a polyline-segment pick needs
  shell-side pick-point resolution — the contract's "line/polyline segment"
  note; recorded honestly); a ``measured_id`` that is missing or not a line
  falls back to the dim's stored points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from bcdoc.errors import EntityNotFound, StyleNotFound
from bcdoc.styles import DimStyleRecord

from .formats import format_length

#: Degenerate-direction tolerance (axis/length collapses).
TOL = 1e-12

#: Chevron wing half-spread as a fraction of dimasz (documented choice).
ARROW_WING_FACTOR = 0.25

#: Text lift above the dim line, as a fraction of dimtxt (contract §5.1
#: pins "dimtxt * 0.5 above the dim line center").
TEXT_OFFSET_FACTOR = 0.5

Pt = Tuple[float, float, float]


@dataclass
class DimensionGeometry:
    """Layout of one dimension (pinned field set/order, contracts §5.1).

    ``ext1``/``ext2`` are (start, end) point pairs; ``arrow1``/``arrow2``
    are ``[tip, wing, wing]`` triples; ``text_value`` is the formatted
    measurement (formats.format_length).
    """

    measurement: float
    dim_line_p1: tuple
    dim_line_p2: tuple
    ext1: tuple            # ((x, y, z), (x, y, z)) — extension line from p1
    ext2: tuple            # ((x, y, z), (x, y, z)) — extension line from p2
    arrow1: list           # [tip, wing, wing] at the dim-line p1 end
    arrow2: list           # [tip, wing, wing] at the dim-line p2 end
    text_point: tuple
    text_value: str


# ---------------------------------------------------------------------------
# internal construction
# ---------------------------------------------------------------------------

def _sizes(style) -> dict:
    """Scaled sizing values from a DimStyleRecord (validated)."""
    scale = float(getattr(style, "dimscale", 1.0))
    exo = float(getattr(style, "dimexo", 0.625))
    exe = float(getattr(style, "dimexe", 1.25))
    asz = float(getattr(style, "dimasz", 2.5))
    txt = float(getattr(style, "dimtxt", 2.5))
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"dimscale must be a positive number, got {scale!r}")
    if asz <= 0.0 or txt <= 0.0:
        raise ValueError(
            f"dimasz/dimtxt must be positive, got dimasz={asz!r} dimtxt={txt!r}")
    if exo < 0.0 or exe < 0.0:
        raise ValueError(
            f"dimexo/dimexe must be >= 0, got dimexo={exo!r} dimexe={exe!r}")
    return {
        "exo": exo * scale,
        "exe": exe * scale,
        "asz": asz * scale,
        "txt": txt * scale,
    }


def _build(p1: Pt, p2: Pt, u, n, offset_point, style, settings) -> DimensionGeometry:
    """Shared linear/aligned construction over given axis (u) + normal (n)."""
    sizes = _sizes(style)
    exo, exe, asz, txt = sizes["exo"], sizes["exe"], sizes["asz"], sizes["txt"]

    # Perpendicular position of the dim line relative to each measured point.
    off1 = (offset_point[0] - p1[0]) * n[0] + (offset_point[1] - p1[1]) * n[1]
    off2 = (offset_point[0] - p2[0]) * n[0] + (offset_point[1] - p2[1]) * n[1]
    sign1 = 1.0 if off1 >= 0.0 else -1.0
    sign2 = 1.0 if off2 >= 0.0 else -1.0

    # Dim-line endpoints: the measured points projected onto the dim line.
    q1 = (p1[0] + n[0] * off1, p1[1] + n[1] * off1, p1[2])
    q2 = (p2[0] + n[0] * off2, p2[1] + n[1] * off2, p2[2])

    # Measurement: |projection of (p2 - p1) on the axis|. The same dot
    # product gives the q1 -> q2 travel direction ("along"); a zero
    # projection collapses the dim line to a point (travel falls back to u).
    along = (p2[0] - p1[0]) * u[0] + (p2[1] - p1[1]) * u[1]
    measurement = abs(along)
    if abs(along) > TOL:
        travel = u if along > 0.0 else (-u[0], -u[1])
    else:
        travel = (1.0, 0.0)  # degenerate: deterministic fallback
    tnorm = (-travel[1], travel[0])  # LEFT of travel — "above" the dim line

    # Extension lines: measured point + exo*sign along n  ->  foot + exe*sign.
    ext1 = (
        (p1[0] + n[0] * sign1 * exo, p1[1] + n[1] * sign1 * exo, p1[2]),
        (q1[0] + n[0] * sign1 * exe, q1[1] + n[1] * sign1 * exe, q1[2]),
    )
    ext2 = (
        (p2[0] + n[0] * sign2 * exo, p2[1] + n[1] * sign2 * exo, p2[2]),
        (q2[0] + n[0] * sign2 * exe, q2[1] + n[1] * sign2 * exe, q2[2]),
    )

    # Arrow chevrons: tip on the dim-line end, wings folded back along the
    # dim line, spread perpendicular by 0.25 * dimasz.
    half_wing = ARROW_WING_FACTOR * asz
    back1 = (travel[0] * asz, travel[1] * asz)       # inward from tip1 (toward q2)
    back2 = (-travel[0] * asz, -travel[1] * asz)     # inward from tip2 (toward q1)
    arrow1 = [
        (q1[0], q1[1], q1[2]),
        (q1[0] + back1[0] + tnorm[0] * half_wing,
         q1[1] + back1[1] + tnorm[1] * half_wing, q1[2]),
        (q1[0] + back1[0] - tnorm[0] * half_wing,
         q1[1] + back1[1] - tnorm[1] * half_wing, q1[2]),
    ]
    arrow2 = [
        (q2[0], q2[1], q2[2]),
        (q2[0] + back2[0] + tnorm[0] * half_wing,
         q2[1] + back2[1] + tnorm[1] * half_wing, q2[2]),
        (q2[0] + back2[0] - tnorm[0] * half_wing,
         q2[1] + back2[1] - tnorm[1] * half_wing, q2[2]),
    ]

    # Text: dim-line midpoint, offset dimtxt*0.5 along the LEFT of travel.
    mid = ((q1[0] + q2[0]) / 2.0, (q1[1] + q2[1]) / 2.0, (q1[2] + q2[2]) / 2.0)
    lift = txt * TEXT_OFFSET_FACTOR
    text_point = (
        mid[0] + tnorm[0] * lift,
        mid[1] + tnorm[1] * lift,
        mid[2],
    )

    return DimensionGeometry(
        measurement=measurement,
        dim_line_p1=q1,
        dim_line_p2=q2,
        ext1=ext1,
        ext2=ext2,
        arrow1=arrow1,
        arrow2=arrow2,
        text_point=text_point,
        text_value=format_length(measurement, settings),
    )


def _as_point(value) -> Pt:
    """Normalize a 2D/3D coordinate into a float 3-tuple."""
    try:
        seq = tuple(value)
        x, y = float(seq[0]), float(seq[1])
        z = float(seq[2]) if len(seq) > 2 else 0.0
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"not a valid 2D/3D point: {value!r}") from None
    return (x, y, z)


# ---------------------------------------------------------------------------
# public constructors
# ---------------------------------------------------------------------------

def linear_geometry(p1, p2, angle_deg: float, offset_point, style,
                    settings) -> DimensionGeometry:
    """Geometry of a LINEAR dimension measured along ``angle_deg``.

    ``angle_deg`` is the measurement direction (0 = horizontal, 90 =
    vertical); the dim line passes through ``offset_point`` parallel to the
    axis. ``settings`` (bcdoc Settings) drives the text formatting.
    """
    rad = math.radians(float(angle_deg))
    u = (math.cos(rad), math.sin(rad))
    n = (-u[1], u[0])
    return _build(_as_point(p1), _as_point(p2), u, n, _as_point(offset_point),
                  style, settings)


def aligned_geometry(p1, p2, offset_point, style,
                     settings) -> DimensionGeometry:
    """Geometry of an ALIGNED dimension: axis = the p1 -> p2 direction."""
    a, b = _as_point(p1), _as_point(p2)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= TOL:
        # Degenerate pair: deterministic horizontal fallback (the callers
        # reject coincident points before reaching here).
        u, n = (1.0, 0.0), (0.0, 1.0)
    else:
        u = (dx / length, dy / length)
        n = (-u[1], u[0])
    return _build(a, b, u, n, _as_point(offset_point), style, settings)


def style_for(doc, name: str) -> DimStyleRecord:
    """Resolve a dim style name against ``doc`` with a Standard fallback.

    Bcdoc does not guard dims against their style being removed (any
    non-"Standard" style can vanish while dims reference it), so resolution
    degrades to "Standard" (and to a stock record if even that is somehow
    absent) instead of crashing display/regen paths.
    """
    try:
        return doc.dim_style(name)
    except StyleNotFound:
        pass
    try:
        return doc.dim_style("Standard")
    except Exception:  # pragma: no cover - "Standard" is always present
        return DimStyleRecord("Standard")


def resolve_dimension(dim, doc):
    """Resolve a stored :class:`bcdoc.Dim` to ``(DimensionGeometry, text)``.

    Associativity (FP-ANN-015): when ``dim.measured_id`` references a live
    LINE entity, its CURRENT endpoints drive the geometry; missing or
    non-line references fall back to the dim's stored ``p1``/``p2`` (free
    dims by definition). ``text_position`` overrides the automatic text
    placement; a non-empty ``text_override`` replaces the formatted
    measurement text. The stored ``measurement`` cache is NOT touched here —
    :func:`bcdraw.regen.refresh_document` refreshes it (one place, one
    policy; documented divergence from the contract §5.1 wording, which
    folded the cache update into this function).
    """
    p1, p2 = dim.p1, dim.p2
    if dim.measured_id:
        try:
            measured = doc.get(dim.measured_id)
        except EntityNotFound:
            measured = None
        if measured is not None and getattr(measured, "kind", "") == "line":
            p1, p2 = measured.p1, measured.p2

    style = style_for(doc, dim.style)
    if dim.dim_type == "aligned":
        geometry = aligned_geometry(p1, p2, dim.offset_point, style, doc.settings)
    else:
        geometry = linear_geometry(p1, p2, dim.angle, dim.offset_point, style,
                                   doc.settings)
    if dim.text_position is not None:
        geometry.text_point = _as_point(dim.text_position)
    text = dim.text_override if dim.text_override else geometry.text_value
    return geometry, text


__all__ = [
    "DimensionGeometry",
    "linear_geometry",
    "aligned_geometry",
    "resolve_dimension",
    "style_for",
    "TOL",
    "ARROW_WING_FACTOR",
    "TEXT_OFFSET_FACTOR",
]
