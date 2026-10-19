"""Loss ledger — the round-trip honesty record (ADR-0003).

Every unsupported entity, property or degradation on an import/export
path is appended here; import/export NEVER silently drops content. The
ledger is an appendable list of entry dicts with the exact shape required
by the M1 contract:

``{"kind": "import" | "export", "dxf_type": str, "reason": str,
   "at": <ISO-8601 UTC date>}``

M2 (m2-module-contracts.md §6) widens the *vocabulary* of the
``dxf_type`` field beyond entity classes: table-level and file-level
entries use :data:`TABLE_TYPES` names (LAYER, LTYPE, BLOCK, PAPER_SPACE,
HEADER, DIMENSION, VIEWPORT, …). The entry SHAPE is unchanged — the M1
assertions (kind ∈ import/export, dxf_type is a string) still hold.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

#: Allowed values for the ``kind`` field (direction of the loss).
KINDS = ("import", "export")

#: M2 dxf_type vocabulary beyond entity classes (table/file/session-level
#: entries). Entity classes (LINE, TEXT, LWPOLYLINE, …) keep their DXF
#: names; entries about a whole table, a section or session state use one
#: of these pseudo-types.
TABLE_TYPES = (
    "FILE",
    "HEADER",       # a $SYSVAR we cannot express / did not find
    "SETTINGS",     # document settings as a whole
    "LAYER",        # layer-table record level
    "LTYPE",        # linetype definition (dash pattern) level
    "STYLE",        # text style table level
    "DIMSTYLE",     # dim style table level
    "BLOCK",        # block definition level
    "LAYOUT",       # layout / paper space level
    "PAPER_SPACE",  # paper-space routing level
    "VIEWPORT",     # viewport presentation attributes
    "DIMENSION",    # dimension definition level
    "MODEL_SPACE",  # model-space routing level
)


class LossLedger:
    """Appendable, JSON-serializable list of interchange-loss records."""

    def __init__(self, entries=None):
        self.entries: list = list(entries) if entries else []

    # -- mutation -----------------------------------------------------------
    def append(self, kind: str, dxf_type: str, reason: str) -> dict:
        """Append one loss record; returns the created entry."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        entry = {
            "kind": kind,
            "dxf_type": str(dxf_type),
            "reason": str(reason),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.entries.append(entry)
        return entry

    # -- list protocol (read-only views) -------------------------------------
    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __getitem__(self, index):
        return self.entries[index]

    def __bool__(self) -> bool:
        return bool(self.entries)

    # -- serialization ---------------------------------------------------------
    def to_json(self) -> str:
        """Stable JSON dump of all entries."""
        return json.dumps(self.entries, indent=2, ensure_ascii=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LossLedger {len(self.entries)} entrie(s)>"
