"""bcdoc — CAD document model v0 (Blender CAD, milestone M1).

Public API (contract: docs/00-architecture/m1-module-contracts.md §3):

- :class:`Document` — the authoritative document model
- :class:`Transaction` — context manager from ``Document.transaction(label)``
- :class:`UndoGroup` — one committed transaction's reversal
- :class:`Entity`, :class:`Line`, :class:`Circle`, :class:`Arc` — entities
- :class:`SelectionState` — session selection state
- :mod:`bcdoc.errors` — exception types (NoOpenTransaction, SerializationError, …)

Pure Python: this package never imports ``bpy``; it runs identically under
pytest, in the extension host, and in the agent sidecar.
"""

from . import errors, units
from .document import Document
from .entities import Arc, Circle, Entity, Line
from .selection import SelectionState
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
    "SelectionState",
    "errors",
    "units",
]

__version__ = "0.1.0"
