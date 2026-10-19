"""Document unit metadata (contract: m1-module-contracts.md §3.2).

v0 scope: units are *display metadata only* — geometry is stored in
unit-free drawing units and no conversion is ever applied. The
INSUNITS-style machine-unit enumeration is owned by the interchange module
(``bcio``), per the document-model doc §3.6, and is deliberately NOT
defined here.
"""

from __future__ import annotations

#: Default unit metadata for a new document (display formatting only).
DEFAULT_UNITS: dict = {"length": "mm", "angle": "deg"}


def normalized(units=None) -> dict:
    """Return a unit metadata dict with fixed key order (``length``, then
    ``angle``), filling missing keys from :data:`DEFAULT_UNITS`."""
    merged = dict(DEFAULT_UNITS)
    if units:
        for key in ("length", "angle"):
            if key in units and units[key] is not None:
                merged[key] = str(units[key])
    # Rebuild in fixed key order for byte-stable serialization.
    return {"length": merged["length"], "angle": merged["angle"]}
