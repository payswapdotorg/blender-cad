"""``cad.doc`` namespace — M1 subset: read-only document state tools.

Implemented (contract §6.1 subset; m1-module-contracts §8):

- ``cad.doc.info``    — document metadata (— · read-only)
- ``cad.doc.status``  — counts + modified state (— · read-only)

NOT implemented at M1 (honest subset; NOT advertised): ``cad.doc.checkpoints``
(list/create) and ``cad.doc.restore`` — bcdoc v0 has no named-checkpoint API yet
(m1-module-contracts §3.2); they arrive with the M5 shared-document work.

Subset decisions (documented, not faked):

- ``modified``: bcdoc v0 exposes no dirty flag; M1 interprets it as
  "the undo journal is non-empty" (``undo_depth() > 0``) — i.e. the document has
  committed transactions. This is a conservative proxy, labeled as such here.
- ``coordinate_systems``: v0 has exactly one implicit system — the document WCS
  (contract §2). Reported as a single entry, never invented.
"""

from __future__ import annotations

from ..contract import APP_VERSION
from .base import ToolContext, ToolSpec


def _doc_info(ctx: ToolContext, args: dict) -> dict:
    doc = ctx.doc
    return {
        "name": doc.name,
        "units": dict(doc.units),
        "coordinate_systems": [
            {"name": "WCS", "type": "world", "up": [0.0, 0.0, 1.0]},
        ],
        "app_version": APP_VERSION,
        # M2 (m2-module-contracts §8): table counts, honest breadth markers
        "counts": {
            "layers": len(list(doc.layers)),
            "blocks": len(doc.block_names()),
            "layouts": len(doc.layouts()),
            "text_styles": len(doc.text_styles()),
            "dim_styles": len(doc.dim_styles()),
        },
        "spaces": ["MODEL"] + list(doc.layouts()),
    }


def _doc_status(ctx: ToolContext, args: dict) -> dict:
    doc = ctx.doc
    return {
        "entity_counts": dict(doc.count_by_kind()),
        # v0 has no dirty flag: "modified" == has committed undoable transactions.
        "modified": doc.undo_depth() > 0,
        "undo_depth": doc.undo_depth(),
        "selection_epoch": doc.selection.epoch,
    }


TOOL_SPECS = [
    ToolSpec(
        tool_id="cad.doc.info",
        run=_doc_info,
    ),
    ToolSpec(
        tool_id="cad.doc.status",
        run=_doc_status,
    ),
]
