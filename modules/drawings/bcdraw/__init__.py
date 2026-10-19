"""bcdraw — annotations + layouts (Blender CAD, M2).

Binding spec: docs/00-architecture/m2-module-contracts.md §5 (this package
IS the §5 "bcdraw" row) + §10 test-matrix row ``modules/drawings/tests``.
Implements inventory FP-ANN-001/002/015/017/020/021/023 (annotation side)
and FP-LAY-001/002/004/007 (layout side).

Surface:

- :func:`register_all(registry)` — registers every bcdraw command
  (DIMLINEAR, DIMALIGNED, DIMSTYLE, DIMREGEN, TEXT, MTEXT, STYLE, LAYOUT,
  MSPACE, PSPACE, MVIEW [aliases MV / VIEWPORT]) into a bccmd Registry.
  All names are NEW — no collisions with bccmd/bcdraft commands;
- :func:`regen.refresh_document(doc)` — re-exported here because bcshell's
  post-transaction sync hook calls ``bcdraw.regen.refresh_document(doc)``
  (contracts §7); DIMREGEN is its command face;
- :mod:`bcdraw.dims` — the dimension geometry engine
  (:func:`dims.linear_geometry`, :func:`dims.aligned_geometry`,
  :func:`dims.resolve_dimension` — the display/interchange geometry source);
- :mod:`bcdraw.formats` — LUNITS/LUPREC/AUNITS/AUPREC value formatting.

Dependency direction (contracts §1, binding): bcdraw imports bcdoc, bccmd
and bcdraft (``drawings`` depends on ``drafting`` per modules.json; the
``drafting -> commands`` edge is transitive). Pure Python, no bpy.
"""

from bccmd import Registry

from . import commands_ann, commands_layout, dims, formats, regen
from .regen import refresh_document

#: Every bcdraw CommandSpec in registration order.
COMMANDS = tuple(commands_ann.COMMANDS) + tuple(commands_layout.COMMANDS)


def register_all(registry: Registry) -> Registry:
    """Register every bcdraw command spec into ``registry`` (idempotent
    registration order; Registry raises on name/alias collisions)."""
    commands_ann.register_all(registry)
    commands_layout.register_all(registry)
    return registry


def command_names() -> tuple:
    return tuple(spec.name for spec in COMMANDS)


__all__ = [
    "COMMANDS",
    "register_all",
    "command_names",
    "refresh_document",
    "commands_ann",
    "commands_layout",
    "dims",
    "formats",
    "regen",
]

__version__ = "0.1.0"
