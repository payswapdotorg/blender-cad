"""bcshell.sync — document → scene display sync (contract §6.2, one-way).

The Blender scene is DERIVED data (document-model doc §2 invariant 3):
every entity maps to one or more display objects in the collection
"BlenderCAD" (model space) or "BlenderCAD/Layout <name>" (per paper-space
layout), each carrying the custom property ``bcdoc_id``; deleting display
objects never touches the document — the next sync rebuilds them (the scene
can always be regenerated from the document).

Headless-testable core (pure, no bpy):

* :func:`entity_display_spec` — the M1 single-object description for
  line/circle/arc (kept for the M1 tests + driver, unchanged shape);
* :func:`display_specs` — the v2 general dispatch (contract §7): one entity
  → a LIST of display spec dicts (see SHAPE below);
* :func:`_bulge_arc_points` — display-only bulge→arc sampling (documented
  duplication: bcdraft.geometry owns the authoritative math; this local
  copy keeps the display path independent of W-D's M2 work);
* :func:`layer_visible` / :func:`display_aci` — the pure layer-display
  policy (OFF/FROZEN ⇒ hidden; ByLayer/ByBlock color chains);
* :func:`aci_to_rgb` — re-exported from :mod:`bcshell.colors`;
* :func:`space_collection_name` — MODEL vs "BlenderCAD/Layout <name>".

Display spec dict SHAPE (binding keys — every spec carries all of these,
font-only keys present on font specs, curve-only keys on curve specs)::

    {"role": str,          # display role (vocabulary in ROLES below)
     "kind": "curve"|"font",
     "name": str,          # Blender object name base
     "bcdoc_id": str,      # owning document entity id
     # curve specs:
     "points": [(x, y, z), ...],
     "cyclic": bool,
     # font specs:
     "body": str, "size": float, "rotation": float,   # rotation in degrees
     "position": (x, y, z)}

Additive (non-binding, documented) keys threaded for the Blender build
path — the binding keys above are always present; these are extra display
routing data:

* ``"aci"``: int — the resolved display ACI (ByLayer → layer color,
  ByBlock → the insert's own color chain; see :func:`display_aci`);
* ``"hide"``: bool — layer policy (``layer.on`` False or ``frozen`` ⇒ the
  display object is hidden; insert members additionally hide with the
  INSERT's own layer);
* ``"space"``: str — the collection the object routes to ("MODEL" or a
  layout name; insert members inherit the INSERT's space);
* ``"splines"``: list of ``{"points": [...], "cyclic": bool}`` — the extra
  polylines of ONE multi-spline curve object (used only by the ``dim``
  mapping, which draws ext lines + dim line + arrow chevrons in a single
  curve object; the binding ``points``/``cyclic`` keys carry the dim line).

Honest v0 budget note: ``sync_display`` is a FULL rebuild after every
committed transaction. Fine up to roughly 200 entities (measured behavior
target: < 16 ms budget applies from M3 — TP-CAT-02/06); beyond that the
rebuild is still correct but interactive-frame sync needs the incremental
dirty-set path (document-model doc §8 "Sync granularity").

bpy is imported lazily so THIS module imports under plain pytest (the pure
helpers are covered by modules/shell/tests).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .colors import ACI_TABLE, aci_to_rgb  # noqa: F401  (re-exported)

#: display collection name for MODEL space (contract §6.2/§7)
COLLECTION_NAME = "BlenderCAD"

#: layout collection prefix: "BlenderCAD/Layout <name>" (contract §7)
LAYOUT_COLLECTION_PREFIX = COLLECTION_NAME + "/Layout "

#: custom property linking a display object to its document entity
ID_PROP = "bcdoc_id"

#: arc sampling density for display polylines (32 segments per full sweep)
ARC_SEGMENTS = 32

#: point-entity cross arm length (drawing units, contract §7)
POINT_ARM = 0.25

#: ellipse sampling density (48 points, contract §7)
ELLIPSE_SEGMENTS = 48

#: bulge segments per full-circle sweep (contract §7: 16/sweep)
SEGMENTS_PER_SWEEP = 16

#: xline/ray display clip length (drawing units; display-only)
INFINITE_CLIP = 1000.0

#: insert-expansion recursion cap (self-referential blocks would loop)
INSERT_DEPTH_CAP = 8

#: display role vocabulary (contract §7 + task binding): plain geometry is
#: "solid", point markers "marker", polyline centerlines "centerline"
#: (widths are NOT rendered — documented), insert members "member",
#: viewport frames "viewport-frame", dimension line-work "dim", dimension
#: text "dim-text", text/mtext "text".
ROLES = ("solid", "marker", "centerline", "member", "viewport-frame",
         "dim", "dim-text", "text")

#: fallback ACI when a layer/insert chain cannot resolve (defensive display)
FALLBACK_ACI = 7


class DisplayDependencyMissing(ImportError):
    """An entity kind needs a parallel-package integration that is not
    present yet (bcdraw for dims, bcdraft.apply_insert_transform for
    inserts). sync_display SKIPS such entities and counts them in the
    ``"skipped"`` stat instead of failing the whole rebuild."""


# ---------------------------------------------------------------------------
# pure helpers (no bpy — headless-testable)
# ---------------------------------------------------------------------------

def layer_visible(record) -> bool:
    """Pure layer-display predicate (contract §7): ``on=False`` or
    ``frozen=True`` ⇒ hidden. An unknown layer (``record is None``) is
    shown — display degrades open, never silently blanks content."""
    if record is None:
        return True
    return bool(record.on) and not bool(record.frozen)


def display_aci(entity, doc, _inherited: Optional[int] = None) -> int:
    """Pure ACI resolution for display coloring (contract §7).

    * entity.color is an explicit ACI (1..255) → that index;
    * ``None`` (ByLayer) → the entity's layer record color (fallback 7);
    * ``0`` (ByBlock — block members) → ``_inherited`` (the insert's own
      resolved chain: insert.color or the insert's layer color); fallback 7
      when a ByBlock color appears outside an insert chain (defensive).
    """
    color = getattr(entity, "color", None)
    if color is not None and color != 0:
        return int(color)
    if color == 0:
        if _inherited is not None:
            return int(_inherited)
        return FALLBACK_ACI
    record = _layer_record(doc, getattr(entity, "layer", "0"))
    if record is not None:
        return int(getattr(record, "color", FALLBACK_ACI))
    return FALLBACK_ACI


def _layer_record(doc, name):
    table = getattr(doc, "layers", None)
    if table is None:
        return None
    try:
        return table.get(name)
    except Exception:
        return None


def space_collection_name(space: str) -> str:
    """Pure space → collection name mapping (contract §7): MODEL →
    "BlenderCAD"; a layout → "BlenderCAD/Layout <name>"."""
    space = str(space)
    if space == "MODEL":
        return COLLECTION_NAME
    return LAYOUT_COLLECTION_PREFIX + space


def _display_name(entity, suffix: str = "") -> str:
    """Object-name base for one entity (M1-compatible for the M1 kinds)."""
    base = f"BC_{getattr(entity, 'kind', 'entity').capitalize()}_{entity.handle}"
    return f"{base}_{suffix}" if suffix else base


def _angle_2d_deg(p_from, p_to) -> float:
    """Local 2D angle helper (degrees, CCW from +X, 0..360) — display-only
    duplication of bcdraft.geometry.angle_of so the dim text rotation never
    depends on W-D's M2 geometry churn."""
    degrees = math.degrees(math.atan2(p_to[1] - p_from[1],
                                       p_to[0] - p_from[0]))
    return degrees % 360.0


def _bulge_arc_points(p1, p2, bulge: float,
                      segments_per_sweep: int = SEGMENTS_PER_SWEEP
                      ) -> List[Tuple[float, float, float]]:
    """Display-only bulge → arc sampling (LOCAL, documented duplication:
    bcdraft.geometry owns the authoritative bulge math — this copy keeps
    the display path headless-independent of W-D's M2 geometry work).

    AutoCAD convention (bcdoc §2.1, binding): bulge = tan(Δ/4), positive =
    CCW arc from ``p1`` to ``p2``. Returns a polyline point list sampled at
    ``segments_per_sweep`` points per full-circle sweep (at least 1
    segment), INCLUDING both endpoints. A zero bulge (or degenerate chord)
    returns the plain two endpoints."""
    p1 = (float(p1[0]), float(p1[1]), float(p1[2]))
    p2 = (float(p2[0]), float(p2[1]), float(p2[2]))
    bulge = float(bulge)
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if bulge == 0.0 or chord < 1e-12:
        return [p1, p2]
    sweep = 4.0 * math.atan(bulge)          # signed Δ (CCW positive)
    radius = (chord / 2.0) / max(abs(math.sin(sweep / 2.0)), 1e-12)
    # center = chord midpoint + left normal * (chord/2)/tan(Δ/2)
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    dx, dy = (p2[0] - p1[0]) / chord, (p2[1] - p1[1]) / chord
    half_tan = math.tan(sweep / 2.0)
    if abs(half_tan) < 1e-12:               # Δ ≈ π: center on the chord
        offset = 0.0
    else:
        offset = (chord / 2.0) / half_tan
    cx = mid[0] - dy * offset               # left normal = (-dy, dx)
    cy = mid[1] + dx * offset
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    steps = max(1, int(round(segments_per_sweep * abs(sweep) / (2.0 * math.pi))))
    points = []
    for i in range(steps + 1):
        angle = a1 + sweep * (i / steps)
        points.append((cx + radius * math.cos(angle),
                       cy + radius * math.sin(angle), p1[2]))
    points[0] = p1
    points[-1] = p2
    return points


# ---------------------------------------------------------------------------
# spec builders (pure)
# ---------------------------------------------------------------------------

def _display_common(entity, doc, _inherited, _hidden):
    """The additive per-entity display context: resolved ACI + hidden flag.

    Hidden iff the entity's layer is OFF/FROZEN — or, for insert members,
    the INSERT's own layer is (threaded through ``_hidden``)."""
    aci = display_aci(entity, doc, _inherited)
    hidden = bool(_hidden) or not layer_visible(
        _layer_record(doc, getattr(entity, "layer", "0")))
    return aci, hidden


def _curve_spec(name, entity_id, points, cyclic, role, aci, hide, space,
                splines=None) -> Dict:
    spec = {
        "role": role,
        "kind": "curve",
        "name": name,
        "bcdoc_id": str(entity_id),
        "points": [(float(p[0]), float(p[1]), float(p[2])) for p in points],
        "cyclic": bool(cyclic),
        "aci": int(aci),
        "hide": bool(hide),
        "space": str(space),
    }
    if splines is not None:
        spec["splines"] = [
            {"points": [(float(p[0]), float(p[1]), float(p[2])) for p in poly],
             "cyclic": bool(cyc)}
            for poly, cyc in splines
        ]
    return spec


def _font_spec(name, entity_id, body, size, rotation, position, role,
               aci, hide, space) -> Dict:
    position = (float(position[0]), float(position[1]), float(position[2]))
    return {
        "role": role,
        "kind": "font",
        "name": name,
        "bcdoc_id": str(entity_id),
        "body": str(body),
        "size": float(size),
        "rotation": float(rotation),
        "position": position,
        "aci": int(aci),
        "hide": bool(hide),
        "space": str(space),
    }


def entity_display_spec(entity) -> Dict:
    """M1 display description for one bcdoc entity (line/circle/arc).

    Returns ``{"name": str, "kind": str, "bcdoc_id": str, "points": [(x,y,z)..],
    "cyclic": bool}``. Mapping per contract §6.2:

    * line  → two-point polyline (non-cyclic)
    * circle→ cyclic 4-point curve (points at 0/90/180/270°) — a deliberate
      coarse display approximation at v0; the authoritative geometry stays
      exact in the document and finer tessellation is M2+ display work
    * arc   → non-cyclic polyline sampled CCW start→end (ARC_SEGMENTS)

    Kept as-is at v2 (the M1 tests + driver pin this shape); the v2 general
    path is :func:`display_specs`.
    """
    kind = getattr(entity, "kind", "")
    points: List = []
    cyclic = False
    if kind == "line":
        points = [tuple(entity.p1), tuple(entity.p2)]
    elif kind == "circle":
        cx, cy, cz = entity.center
        r = float(entity.radius)
        points = [
            (cx + r, cy, cz),
            (cx, cy + r, cz),
            (cx - r, cy, cz),
            (cx, cy - r, cz),
        ]
        cyclic = True
    elif kind == "arc":
        from bcdraft.geometry import arc_points

        points = arc_points(
            entity.center, entity.radius,
            entity.start_angle, entity.end_angle, segments=ARC_SEGMENTS,
        )
    else:
        raise ValueError(f"no display mapping for entity kind {kind!r}")
    return {
        "name": _display_name(entity),
        "kind": kind,
        "bcdoc_id": entity.id,
        "points": [(float(p[0]), float(p[1]), float(p[2])) for p in points],
        "cyclic": cyclic,
    }


def _point_specs(entity, doc, aci, hide):
    """point → 2 short cross segments (arms POINT_ARM, contract §7).

    Rendered as an X-cross of two perpendicular segments through the
    position (task binding; contracts §7 phrases the same marker as one
    8-point polyline — visually identical, this returns two 2-point specs
    which the spline-per-spec build path draws identically)."""
    x, y, z = entity.position
    arm = POINT_ARM
    return [
        _curve_spec(_display_name(entity, "0"), entity.id,
                    ((x - arm, y, z), (x + arm, y, z)), False,
                    "marker", aci, hide, entity.space),
        _curve_spec(_display_name(entity, "1"), entity.id,
                    ((x, y - arm, z), (x, y + arm, z)), False,
                    "marker", aci, hide, entity.space),
    ]


def _polyline_spec(entity, doc, aci, hide):
    """polyline → ONE curve from the vertices, bulge segments sampled at
    SEGMENTS_PER_SWEEP per sweep; closed → cyclic. Widths are NOT rendered
    (contract §7): the display is the centerline, role "centerline" —
    documented."""
    vertices = list(entity.vertices)
    closed = bool(entity.closed)
    bulges = list(entity.bulges) if entity.bulges else []
    if not vertices:
        raise ValueError("polyline without vertices cannot be displayed")
    points: List[Tuple[float, float, float]] = []
    seg_count = len(vertices) if closed else len(vertices) - 1
    for i in range(seg_count):
        start = vertices[i]
        end = vertices[(i + 1) % len(vertices)]
        bulge = bulges[i] if i < len(bulges) else 0.0
        if bulge:
            arc_pts = _bulge_arc_points(start, end, bulge)
            points.extend(arc_pts[:-1])     # avoid duplicating joints
        else:
            points.append((float(start[0]), float(start[1]), float(start[2])))
    if not closed:
        last = vertices[-1]
        points.append((float(last[0]), float(last[1]), float(last[2])))
    return _curve_spec(_display_name(entity), entity.id, points, closed,
                       "centerline", aci, hide, entity.space)


def _ellipse_spec(entity, doc, aci, hide):
    """ellipse → 48-point sampling of
    ``point(θ) = center + major·cosθ + minor·sinθ`` where
    ``minor = rotate(major, 90°)·ratio`` (contract §7). Full ellipse
    (0..360) → cyclic 48 points (the cycle closes the seam); partial →
    non-cyclic 48 points spanning start..end inclusive."""
    cx, cy, cz = entity.center
    mx, my, _mz = entity.major_axis
    ratio = float(entity.ratio)
    start = float(entity.start_angle)
    end = float(entity.end_angle)
    # minor axis = major rotated 90° CCW, scaled by ratio
    nx, ny = -my * ratio, mx * ratio
    span_mod = (end - start) % 360.0
    full = span_mod < 1e-9            # (start==end covers the AutoCAD "full" case)
    if full:
        thetas = [2.0 * math.pi * i / ELLIPSE_SEGMENTS
                  for i in range(ELLIPSE_SEGMENTS)]
        cyclic = True
    else:
        span = math.radians(span_mod)
        thetas = [math.radians(start) + span * i / (ELLIPSE_SEGMENTS - 1)
                  for i in range(ELLIPSE_SEGMENTS)]
        cyclic = False
    points = [(cx + mx * math.cos(t) + nx * math.sin(t),
               cy + my * math.cos(t) + ny * math.sin(t), cz) for t in thetas]
    return _curve_spec(_display_name(entity), entity.id, points, cyclic,
                       "solid", aci, hide, entity.space)


def _infinite_line_spec(entity, doc, aci, hide, semi: bool):
    """xline/ray → display-clipped segment (contract §7: display-only clip).

    * xline (infinite through p1/p2): a segment centered on the chord
      midpoint, extending INFINITE_CLIP in each direction;
    * ray (semi-infinite from p1 THROUGH p2): from p1 extending
      INFINITE_CLIP along the p1→p2 direction."""
    p1 = tuple(float(v) for v in entity.p1)
    p2 = tuple(float(v) for v in entity.p2)
    dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-12:
        raise ValueError("degenerate infinite line cannot be displayed")
    ux, uy, uz = dx / length, dy / length, dz / length
    if semi:
        points = (p1, (p1[0] + ux * INFINITE_CLIP, p1[1] + uy * INFINITE_CLIP,
                       p1[2] + uz * INFINITE_CLIP))
    else:
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0,
               (p1[2] + p2[2]) / 2.0)
        points = ((mid[0] - ux * INFINITE_CLIP, mid[1] - uy * INFINITE_CLIP,
                  mid[2] - uz * INFINITE_CLIP),
                 (mid[0] + ux * INFINITE_CLIP, mid[1] + uy * INFINITE_CLIP,
                  mid[2] + uz * INFINITE_CLIP))
    return _curve_spec(_display_name(entity), entity.id, points, False,
                       "solid", aci, hide, entity.space)


#: estimated glyph aspect for text width (monospace approximation)
TEXT_WIDTH_FACTOR_ESTIMATE = 0.6


def _text_font_spec(entity, doc, aci, hide):
    """text → font object (contract §7): body=content, size=height,
    rotation, object origin placed per justification.

    Justification origin estimate (documented, task binding): text width is
    NOT measured (Blender font metrics arrive at build time); CENTER/RIGHT
    offset the object origin back along the text direction by the ESTIMATED
    width ``len(content) * height * 0.6`` (crude monospace estimate — the
    rendered glyphs may overflow; the document keeps the exact insertion
    point in ``position``)."""
    x, y, z = entity.position
    height = float(entity.height)
    rotation = float(entity.rotation)
    body = str(entity.content)
    direction = (math.cos(math.radians(rotation)),
                 math.sin(math.radians(rotation)))
    estimate = len(body) * height * TEXT_WIDTH_FACTOR_ESTIMATE
    justification = str(getattr(entity, "justification", "LEFT"))
    if justification == "CENTER":
        offset = estimate / 2.0
    elif justification == "RIGHT":
        offset = estimate
    else:                                   # LEFT: origin at the position
        offset = 0.0
    position = (x - direction[0] * offset, y - direction[1] * offset, z)
    return _font_spec(_display_name(entity), entity.id, body, height,
                      rotation, position, "text", aci, hide, entity.space)


def _mtext_font_spec(entity, doc, aci, hide):
    """mtext → font object (contract §7): body with embedded newlines
    (Blender font objects render them as line breaks). The column WIDTH is
    NOT wrapped (contract §7: wrapping not rendered — documented); size
    comes from the entity's text style height (Standard default when the
    style/doc is unavailable)."""
    try:
        size = float(doc.text_style(entity.style).height)
    except Exception:
        size = 2.5
    return _font_spec(_display_name(entity), entity.id, str(entity.content),
                      size, 0.0, tuple(entity.position), "text",
                      aci, hide, entity.space)


def _dim_specs(entity, doc, aci, hide):
    """dim → ONE curve object (ext lines + dim line + arrow chevrons as
    multiple POLY splines) + ONE font object, both tagged with the dim's
    bcdoc_id (contract §7). Geometry comes from
    ``bcdraw.dims.resolve_dimension(dim, doc)`` (W-C, feature-detected);
    the font size is ``dimtxt * dimscale`` of the dim's style and the font
    sits at the stored ``text_position`` when present, else the resolved
    ``text_point``, rotated along the dim line."""
    if doc is None:
        raise ValueError("dim display requires the document (resolve_dimension)")
    try:
        from bcdraw.dims import resolve_dimension
    except ImportError:
        raise DisplayDependencyMissing(
            "bcdraw.dims.resolve_dimension (W-C) is required to display "
            "dimensions") from None
    geometry, text_value = resolve_dimension(entity, doc)
    try:
        style = doc.dim_style(entity.style)
        size = float(style.dimtxt) * float(style.dimscale)
    except Exception:
        size = 2.5
    dim_line = (tuple(geometry.dim_line_p1), tuple(geometry.dim_line_p2))
    ext1 = (tuple(geometry.ext1[0]), tuple(geometry.ext1[1]))
    ext2 = (tuple(geometry.ext2[0]), tuple(geometry.ext2[1]))
    arrow1 = [tuple(p) for p in geometry.arrow1]
    arrow2 = [tuple(p) for p in geometry.arrow2]
    splines = [
        (ext1, False), (ext2, False), (dim_line, False),
        ((arrow1[0], arrow1[1]), False), ((arrow1[0], arrow1[2]), False),
        ((arrow2[0], arrow2[1]), False), ((arrow2[0], arrow2[2]), False),
    ]
    if entity.text_position is not None:
        position = tuple(float(v) for v in entity.text_position)
    else:
        position = tuple(float(v) for v in geometry.text_point)
    rotation = _angle_2d_deg(dim_line[0], dim_line[1])
    return [
        _curve_spec(_display_name(entity, "curve"), entity.id, dim_line,
                    False, "dim", aci, hide, entity.space, splines=splines),
        _font_spec(_display_name(entity, "text"), entity.id, text_value,
                   size, rotation, position, "dim-text", aci, hide,
                   entity.space),
    ]


def _insert_specs(entity, doc, _inherited, _hidden, _depth):
    """insert → N member display specs (role "member"), every one tagged
    with the INSERT's bcdoc_id (contract §7: one id, many objects —
    selecting any member selects the reference). Members come from
    ``doc.block(name).entities`` transformed by
    ``bcdraft.geometry.apply_insert_transform`` (W-D, feature-detected).

    ByBlock members (color 0) resolve against the INSERT's own color chain
    (insert.color or the insert's layer color); a member hides when either
    ITS layer or the INSERT's layer is off/frozen. Nested inserts (a block
    whose members reference further blocks) expand recursively up to
    INSERT_DEPTH_CAP (self-referential definitions then surface as a
    documented skip, not a hang)."""
    if doc is None:
        raise ValueError("insert display requires the document (block table)")
    if _depth >= INSERT_DEPTH_CAP:
        raise ValueError("insert nesting too deep to display")
    try:
        from bcdraft import geometry as _geometry
    except ImportError:
        _geometry = None
    apply_transform = getattr(_geometry, "apply_insert_transform", None)
    if apply_transform is None:
        raise DisplayDependencyMissing(
            "bcdraft.geometry.apply_insert_transform (W-D) is required to "
            "display block references")
    definition = doc.block(entity.name)  # bcdoc.errors.BlockNotFound propagates
    insert_aci = display_aci(entity, doc, _inherited)
    insert_hidden = bool(_hidden) or not layer_visible(
        _layer_record(doc, getattr(entity, "layer", "0")))
    specs: List[Dict] = []
    for index, member in enumerate(definition.entities):
        transformed = apply_transform(member, definition.base_point,
                                      entity.position, entity.scale,
                                      entity.rotation)
        inherited = insert_aci if getattr(member, "color", None) == 0 else _inherited
        for spec in display_specs(transformed, doc, _inherited=inherited,
                                  _hidden=insert_hidden,
                                  _depth=_depth + 1):
            spec["role"] = "member"
            spec["bcdoc_id"] = str(entity.id)   # ALL members carry the INSERT id
            spec["name"] = _display_name(entity, f"member{index}")
            spec["space"] = str(entity.space)   # members live in the insert's space
            specs.append(spec)
    return specs


def _viewport_spec(entity, doc, aci, hide):
    """viewport → rectangle polyline from p1/p2 (contract §7: not cyclic —
    five points closing back to the first corner), drawn in its layout's
    space collection (routed by the additive ``space`` key). The rectangle
    is drawn on the XY plane at p1's elevation (paper-space rects are
    display frames, not geometry)."""
    x1, y1, z1 = (float(v) for v in entity.p1)
    x2, y2, _z2 = (float(v) for v in entity.p2)
    rect = ((x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1),
            (x1, y1, z1))
    return _curve_spec(_display_name(entity), entity.id, rect, False,
                       "viewport-frame", aci, hide, entity.space)


def display_specs(entity, doc=None, _inherited: Optional[int] = None,
                  _hidden: bool = False, _depth: int = 0) -> List[Dict]:
    """The v2 general display dispatch (contract §7): one entity → a list of
    1..N display spec dicts (SHAPE in the module docstring). M1 kinds adapt
    the proven :func:`entity_display_spec` output; new kinds map per the
    contract table. ``_inherited``/``_hidden``/``_depth`` are internal
    recursion state for insert members (ByBlock ACI chain, insert-layer
    hide chain, nesting cap) — callers use ``display_specs(entity, doc)``.

    Raises :class:`ValueError` for unknown kinds (as M1 did) and
    :class:`DisplayDependencyMissing` when a kind's integration package
    (bcdraw for dims, W-D's apply_insert_transform for inserts) has not
    landed yet — sync_display SKIPS such entities (counted in the
    ``"skipped"`` stat) instead of failing the whole rebuild.
    """
    kind = getattr(entity, "kind", "")
    if kind in ("line", "circle", "arc"):
        old = entity_display_spec(entity)  # keeps the M1 shape + errors
        aci, hide = _display_common(entity, doc, _inherited, _hidden)
        return [_curve_spec(old["name"], entity.id, old["points"],
                            old["cyclic"], "solid", aci, hide, entity.space)]
    if kind in ("point", "polyline", "ellipse", "xline", "ray", "text",
                "mtext", "dim", "insert", "viewport"):
        aci, hide = _display_common(entity, doc, _inherited, _hidden)
        if kind == "point":
            return _point_specs(entity, doc, aci, hide)
        if kind == "polyline":
            return [_polyline_spec(entity, doc, aci, hide)]
        if kind == "ellipse":
            return [_ellipse_spec(entity, doc, aci, hide)]
        if kind == "xline":
            return [_infinite_line_spec(entity, doc, aci, hide, semi=False)]
        if kind == "ray":
            return [_infinite_line_spec(entity, doc, aci, hide, semi=True)]
        if kind == "text":
            return [_text_font_spec(entity, doc, aci, hide)]
        if kind == "mtext":
            return [_mtext_font_spec(entity, doc, aci, hide)]
        if kind == "dim":
            return _dim_specs(entity, doc, aci, hide)
        if kind == "insert":
            return _insert_specs(entity, doc, _inherited, _hidden, _depth)
        return [_viewport_spec(entity, doc, aci, hide)]
    raise ValueError(f"no display mapping for entity kind {kind!r}")


# ---------------------------------------------------------------------------
# dimension regeneration (bcdraw, feature-detected — contract §7)
# ---------------------------------------------------------------------------

def refresh_document_dims(doc) -> int:
    """Refresh every dim's cached measurement via
    ``bcdraw.regen.refresh_document(doc)`` (W-C, feature-detected: returns
    0 when bcdraw is absent). Called by the on_change chain BEFORE sync so
    dimensions stay current after a MOVE of the measured entity. Failures
    never break the caller (display is derived data)."""
    if doc is None:
        return 0
    try:
        from bcdraw import regen
    except ImportError:
        return 0
    try:
        return int(regen.refresh_document(doc).get("refreshed", 0))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Blender-facing rebuild (bpy lazily imported)
# ---------------------------------------------------------------------------

def _ensure_collection(name: str):
    import bpy

    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    scene = bpy.context.scene
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def ensure_collection():
    """Get or create the MODEL display collection (linked to the scene)."""
    return _ensure_collection(COLLECTION_NAME)


def _session_layouts() -> List[str]:
    """Layout names from the session document (empty without a session)."""
    from . import session

    doc = session._doc
    if doc is None:
        return []
    try:
        return list(doc.layouts())
    except Exception:
        return []


def all_space_collections() -> List:
    """Every display collection we own: MODEL + "BlenderCAD/Layout <name>"
    (stale layout collections included — they are pruned by sync_display)."""
    import bpy

    out = []
    names = [COLLECTION_NAME] + [LAYOUT_COLLECTION_PREFIX + layout
                                 for layout in _session_layouts()]
    for collection in bpy.data.collections:
        if collection.name == COLLECTION_NAME or collection.name.startswith(
                LAYOUT_COLLECTION_PREFIX):
            if collection.name in names or collection not in out:
                out.append(collection)
    return out


def _remove_objects(collection, objects) -> None:
    import bpy

    for obj in objects:
        try:
            if obj.name in collection.objects:
                collection.objects.unlink(obj)
            bpy.data.objects.remove(obj)
        except ReferenceError:
            pass  # already gone


def _remove_collection(collection) -> None:
    """Delete one display collection + its objects + its scene link."""
    import bpy

    _remove_objects(collection, list(collection.objects))
    try:
        scene = bpy.context.scene
        if collection.name in scene.collection.children:
            scene.collection.children.unlink(collection)
    except ReferenceError:
        pass
    try:
        bpy.data.collections.remove(collection)
    except (ReferenceError, RuntimeError):
        pass  # already gone / still linked elsewhere — never crash


def _build_object(spec: Dict):
    """Create the display object for one display spec (curve or font)."""
    import bpy

    if spec["kind"] == "font":
        curve = bpy.data.curves.new(name=spec["name"], type="FONT")
        curve.body = spec["body"]
        curve.size = spec["size"]
        obj = bpy.data.objects.new(spec["name"], curve)
        obj.location = spec["position"]
        obj.rotation_euler = (0.0, 0.0, math.radians(spec["rotation"]))
    else:
        curve = bpy.data.curves.new(name=spec["name"], type="CURVE")
        curve.dimensions = "3D"
        splines = spec.get("splines") or [
            {"points": spec["points"], "cyclic": spec["cyclic"]}
        ]
        for poly in splines:
            points = poly["points"]
            if len(points) < 2:
                continue  # a degenerate spline would corrupt the display
            spline = curve.splines.new("POLY")
            spline.points.add(count=len(points) - 1)  # new() starts with 1
            for point, coord in zip(spline.points, points):
                point.co = (coord[0], coord[1], coord[2], 1.0)
            spline.use_cyclic_u = bool(poly["cyclic"])
            spline.type = "POLY"
        obj = bpy.data.objects.new(spec["name"], curve)
    obj[ID_PROP] = spec["bcdoc_id"]
    try:
        obj.color = (*aci_to_rgb(spec.get("aci", FALLBACK_ACI)), 1.0)
    except ValueError:
        obj.color = (*aci_to_rgb(FALLBACK_ACI), 1.0)
    hidden = bool(spec.get("hide", False))
    obj.hide_viewport = hidden
    obj.hide_render = hidden
    return obj


def sync_display(doc) -> Dict:
    """Rebuild the WHOLE display (every space's collection) from ``doc``.

    Spaces (contract §7): collection "BlenderCAD" = MODEL;
    "BlenderCAD/Layout <name>" per layout — collections are created/removed
    to mirror ``doc.layouts()``; non-current spaces are hidden
    (``collection.hide_viewport = space != doc.current_space``).

    Layer display rules (contract §7): objects whose entity's layer is
    OFF or FROZEN get ``hide_viewport`` + ``hide_render`` True; ByLayer
    colors resolve through the layer ACI (local palette), ByBlock members
    through the insert's chain.

    Returns stats ``{"objects": n, "entities": n, "spaces": n}`` plus the
    additive ``"skipped"`` count — entities whose kind needs an integration
    that has not landed (bcdraw dims / W-D insert transforms) are skipped,
    not failed. Display deletions never touch the document: this full
    rebuild simply regenerates whatever is missing.
    """
    spaces = ["MODEL"] + list(doc.layouts())
    collections = {space: _ensure_collection(space_collection_name(space))
                   for space in spaces}
    # prune display collections of layouts that no longer exist
    live = {space_collection_name(space) for space in spaces}
    for collection in all_space_collections():
        if collection.name not in live:
            _remove_collection(collection)

    for space, collection in collections.items():
        _remove_objects(collection, list(collection.objects))
        collection.hide_viewport = (space != doc.current_space)

    objects = 0
    skipped = 0
    for entity in doc.entities():
        try:
            specs = display_specs(entity, doc)
        except Exception:
            # missing integration (bcdraw/bcdraft M2 hooks), an unmappable
            # entity (e.g. insert whose block was removed) — skip it, never
            # break the whole rebuild; the "skipped" stat surfaces the count
            skipped += 1
            continue
        space = entity.space
        collection = collections.get(space)
        if collection is None:
            # bcdoc validates entity.space against the layout table; this
            # defensively routes anything else to its own collection
            collection = _ensure_collection(space_collection_name(space))
            collections[space] = collection
        for spec in specs:
            obj = _build_object(spec)
            collection.objects.link(obj)
            objects += 1
    return {"objects": objects, "entities": len(doc.entities()),
            "spaces": len(collections), "skipped": skipped}


def clear_display() -> None:
    """Delete every display object + layout collection (document untouched
    by definition)."""
    for collection in all_space_collections():
        if collection.name == COLLECTION_NAME:
            _remove_objects(collection, list(collection.objects))
        else:
            _remove_collection(collection)


def display_ids_in_scene_selection() -> List[str]:
    """Document ids of display objects that are selected.

    v0 selection mechanism (honest scope, documented per contract §6.2):
    the modal operator and operators that need the document selection call
    this; a msgbus/DEG-driven automatic sync of Blender's viewport
    selection into ``document.selection`` is M2 UX work. Objects outside
    the display collections are ignored (blender-native data is never
    claimed by the CAD layer — document-model doc §7.2 rule 5)."""
    ids = []
    for collection in all_space_collections():
        for obj in collection.objects:
            if obj.select_get():
                entity_id = obj.get(ID_PROP)
                if entity_id:
                    ids.append(str(entity_id))
    return ids
