"""bcdraft — drafting commands (Blender CAD, M1).

Pure Python (no Blender dependency — importable under pytest and in the
host). M1 command set (contract §5): LINE, CIRCLE, ARC, ERASE, MOVE, COPY,
ROTATE, SCALE, UNDO, REDO. Layer management is M2; M1 commands use layer
"0"/current-layer metadata only.

Boundary note (recorded for the TL): bcdraft imports ``bccmd`` because the
commands ARE :class:`bccmd.CommandSpec` objects per m1-module-contracts §5.
The package edge is strictly one-way (bcdraft → bccmd; bccmd imports nothing
from bcdraft), so no cycle exists at package level; the glossary §4
``drafting`` depends_on row (document, kernel) predates the M1 contract and
is flagged in the worklog for amendment.
"""

from bccmd import CommandSpec, Registry

from . import (
    commands_doc,
    commands_draw,
    commands_modify,
    commands_organization,
    commands_precision,
    selection,
)
from .commands_doc import COMMANDS as _DOC_COMMANDS
from .commands_draw import COMMANDS as _DRAW_COMMANDS
from .commands_modify import COMMANDS as _MODIFY_COMMANDS
from .commands_organization import COMMANDS as _ORG_COMMANDS
from .commands_precision import COMMANDS as _PRECISION_COMMANDS
from .selection import COMMANDS as _SELECTION_COMMANDS

COMMANDS = (
    tuple(_DRAW_COMMANDS)
    + tuple(_MODIFY_COMMANDS)
    + tuple(_DOC_COMMANDS)
    + tuple(_PRECISION_COMMANDS)
    + tuple(_SELECTION_COMMANDS)
    + tuple(_ORG_COMMANDS)
)


def register_all(registry: Registry) -> Registry:
    """Register every bcdraft command spec into ``registry``."""
    for spec in COMMANDS:
        registry.register(spec)
    return registry


def command_names() -> tuple:
    return tuple(spec.name for spec in COMMANDS)


__all__ = [
    "COMMANDS",
    "register_all",
    "command_names",
    "commands_draw",
    "commands_modify",
    "commands_doc",
    "commands_precision",
    "commands_organization",
    "selection",
]

__version__ = "0.1.0"
