"""bcdoc — CAD document model v2 (Blender CAD, milestone M2).

Public API (contracts: docs/00-architecture/m1-module-contracts.md §3 for
the M1 surface, m2-module-contracts.md §2 for the v2 additions):

- :class:`Document` — the authoritative document model (entities, layer
  table, blocks, layouts/spaces, settings, text/dim styles)
- :class:`Transaction` — context manager from ``Document.transaction(label)``
- :class:`UndoGroup` — one committed transaction's reversal
- :class:`Entity` + all kinds — :class:`Line`, :class:`Circle`, :class:`Arc`
  (M1) and :class:`Point`, :class:`Polyline`, :class:`Ellipse`,
  :class:`Xline`, :class:`Ray`, :class:`Text`, :class:`Mtext`,
  :class:`Dim`, :class:`Insert`, :class:`Viewport` (M2)
- :class:`LayerRecord` / :class:`LayerTable`, :class:`BlockDefinition`,
  :class:`LayoutRecord`, :class:`TextStyleRecord` / :class:`DimStyleRecord`,
  :class:`Settings` — the v2 table/record types
- :class:`SelectionState` — session selection state
- :mod:`bcdoc.errors` — exception types (NoOpenTransaction,
  SerializationError, BlockNotFound, UnknownSetting, …)

Pure Python: this package never imports ``bpy``; it runs identically under
pytest, in the extension host, and in the agent sidecar.
"""

from . import errors, units
from .blocks import BlockDefinition, BlockTable
from .document import Document
from .entities import (
    Arc,
    Circle,
    Dim,
    Ellipse,
    Entity,
    Insert,
    Line,
    Mtext,
    Point,
    Polyline,
    Ray,
    Text,
    Viewport,
    Xline,
)
from .layers import LayerRecord, LayerTable
from .layouts import LayoutRecord, LayoutTable
from .selection import SelectionState
from .settings import SETTING_DEFS, Settings
from .styles import DimStyleRecord, TextStyleRecord
from .transaction import Transaction
from .undo import UndoGroup

__all__ = [
    "Document",
    "Transaction",
    "UndoGroup",
    "Entity",
    "Line",
    "Circle",
    "Arc",
    "Point",
    "Polyline",
    "Ellipse",
    "Xline",
    "Ray",
    "Text",
    "Mtext",
    "Dim",
    "Insert",
    "Viewport",
    "LayerRecord",
    "LayerTable",
    "BlockDefinition",
    "BlockTable",
    "LayoutRecord",
    "LayoutTable",
    "TextStyleRecord",
    "DimStyleRecord",
    "Settings",
    "SETTING_DEFS",
    "SelectionState",
    "errors",
    "units",
]

__version__ = "0.2.0"
