"""bcshell.pick — viewport picking + rubberband drawing (contract §6.2).

Two pure helpers are the headless-testable core (no bpy needed to import
THIS module — bpy/gpu are imported lazily inside the Blender-facing
functions, which is what lets the pure helpers run under plain pytest):

* :func:`ray_plane_z0` — ray ∩ z=0 plane math (the CAD drawing plane).
* :func:`dynamic_readout` — the ``distance < angle`` live overlay text.

The Blender-facing side: :func:`point_from_event` (viewport click →
:class:`bccmd.Point` on the XY plane via ``bpy_extras.view3d_utils``) and
:class:`Rubberband` (gpu polyline draw-handler added POST_PIXEL on start,
removed on finish ALWAYS — the try/finally discipline is a TP-CAT-06 clean-
unload requirement, so unregister() also sweeps live rubberbands).
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

#: rays closer to parallel than this (|dz| fraction) never hit the plane
PARALLEL_EPS = 1e-9


# ---------------------------------------------------------------------------
# pure math (headless-testable)
# ---------------------------------------------------------------------------

def ray_plane_z0(origin, direction) -> Optional[Tuple[float, float]]:
    """Intersect the ray ``origin + t*direction`` with the z=0 plane.

    Returns ``(x, y)`` on the plane, or None when the ray is parallel to
    the plane or points away from it (t < 0 — the intersection is behind
    the viewer). ``origin``/``direction`` are 3-vectors (any indexable).
    """
    dz = float(direction[2])
    if abs(dz) < PARALLEL_EPS:
        return None
    t = -float(origin[2]) / dz
    if t < 0.0:
        return None
    return (float(origin[0]) + t * float(direction[0]),
            float(origin[1]) + t * float(direction[1]))


def dynamic_readout(anchor, cursor) -> str:
    """AutoCAD-style dynamic input text: ``"<dist> <angle>"`` from the
    anchor (last accepted point) to the cursor; empty string without anchor."""
    if anchor is None or cursor is None:
        return ""
    dx = float(cursor[0]) - float(anchor[0])
    dy = float(cursor[1]) - float(anchor[1])
    distance = math.hypot(dx, dy)
    if distance < PARALLEL_EPS:
        return "0.000 < 0°"
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    return f"{distance:.3f} < {angle:.1f}°"


# ---------------------------------------------------------------------------
# Blender-facing picking (bpy imported lazily)
# ---------------------------------------------------------------------------

def point_from_event(event, context):
    """Resolve a viewport mouse event to a :class:`bccmd.Point` on z=0.

    Returns None when the view ray is parallel to the drawing plane or the
    intersection lies behind the viewer (contract §6.2 mouse point input).
    """
    from bpy_extras import view3d_utils  # lazy: Blender only

    from bccmd import Point

    region = getattr(context, "region", None)
    rv3d = getattr(context, "region_data", None)
    if region is None or rv3d is None:
        return None
    coord = (event.mouse_region_x, event.mouse_region_y)
    if not (0 <= coord[0] < region.width and 0 <= coord[1] < region.height):
        return None
    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    except Exception:  # malformed region data — never crash the modal op
        return None
    hit = ray_plane_z0(origin, direction)
    if hit is None:
        return None
    return Point(hit[0], hit[1], 0.0)


# ---------------------------------------------------------------------------
# Rubberband (gpu drawing; every start() is paired by finish()/cleanup)
# ---------------------------------------------------------------------------

class Rubberband:
    """One live rubberband line for the modal command operator.

    ``start(anchor)`` registers the POST_PIXEL draw handler and remembers
    the anchor point; ``update(point)`` moves the free end; ``finish()``
    removes the handler (idempotent, exception-safe). Instances register
    themselves in :data:`ACTIVE_RUBBERBANDS` so ``bcshell.unregister()`` can
    sweep any survivor (TP-CAT-06).
    """

    def __init__(self, color=(0.9, 0.85, 0.3, 0.9), width=1.5):
        self.color = tuple(color)
        self.width = float(width)
        self._handle = None
        self._anchor = None
        self._cursor = None

    # -- lifecycle ----------------------------------------------------------
    def start(self, anchor) -> None:
        import bpy  # lazy: Blender only

        if self._handle is None:
            self._handle = bpy.types.SpaceView3D.draw_handler_add(
                self._draw, (), "WINDOW", "POST_PIXEL"
            )
            ACTIVE_RUBBERBANDS.append(self)
        self._anchor = anchor

    def update(self, cursor) -> None:
        self._cursor = cursor

    def finish(self) -> None:
        try:
            if self._handle is not None:
                import bpy  # lazy: Blender only

                bpy.types.SpaceView3D.draw_handler_remove(
                    self._handle, "WINDOW"
                )
        except Exception:
            pass  # handler already gone (window closed) — never crash
        finally:
            self._handle = None
            self._anchor = None
            self._cursor = None
            if self in ACTIVE_RUBBERBANDS:
                ACTIVE_RUBBERBANDS.remove(self)

    @property
    def active(self) -> bool:
        return self._handle is not None

    # -- drawing ------------------------------------------------------------
    def _draw(self) -> None:
        anchor, cursor = self._anchor, self._cursor
        if anchor is None or cursor is None:
            return
        try:
            import gpu
            from gpu.types import GPUBatch, GPUVertBuf, GPUVertFormat

            try:
                gpu.init()  # Blender 5.x: gpu must be initialized headless
            except Exception:
                pass
            shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
            fmt = GPUVertFormat()
            fmt.attr_add(id="pos", comp_type="F32", len=3, fetch_mode="FLOAT")
            vbuf = GPUVertBuf(format=fmt, len=2)
            vbuf.attr_fill(
                0,
                ((anchor[0], anchor[1], anchor[2]),
                 (cursor[0], cursor[1], cursor[2])),
            )
            batch = GPUBatch(type="LINES", buf=vbuf)
            gpu.state.line_width_set(self.width)
            gpu.state.blend_set("ALPHA")
            batch.draw(shader)
            gpu.state.blend_set("NONE")
        except Exception:
            # Drawing problems must never take down the modal operator or
            # Blender's drawing loop (honest v0: rubberband is cosmetic).
            pass


#: every live rubberband (swept on unregister — TP-CAT-06 clean unload)
ACTIVE_RUBBERBANDS = []


def cleanup_all() -> None:
    """Remove every live draw handler (called by bcshell.unregister)."""
    for rubber in list(ACTIVE_RUBBERBANDS):
        rubber.finish()
