"""``cad.io`` namespace — M1 subset: DXF export/import through module interchange.

Implemented (contract §6.9; m1-module-contracts §8):

- ``cad.io.export_dxf`` — write DXF (class ``filesystem`` · read-only mode; the
  contract §5 rule "exports need ``filesystem`` and work in read-only mode")
- ``cad.io.import_dxf`` — read DXF into the CURRENT document
  (classes ``doc-edit`` + ``filesystem`` · propose; transactional — contract §6.9)

NOT implemented at M1 (honest subset, NOT advertised): ``export_dwg``/``export_pdf``/
``export_ifc`` (interchange milestones — ADR-0003 DXF-first), ``import_dwg``, xref ops.

M1 rules (binding for this adapter):

- **Path confinement:** paths are used AS GIVEN by the HOST (M1 rule, recorded in
  the module docstring + security tests). The adapter performs no path
  validation/traversal checks of its own — the in-process caller (the CAD
  application, which owns the permission authority) supplies paths it has already
  approved. The security-boundary test asserts the tools touch NOTHING except the
  provided path argument.
- **DXF version:** v0 writes R12 ASCII via ``bcio.dxf_minimal`` (m1-module-contracts
  §7); an explicit non-R12 ``version`` arg is a validation error (honest refusal
  beats silent downgrade).
- **``into``:** only ``into: "current"`` (the default) at M1 — the in-process
  adapter has exactly one document. ``into: "new"`` returns a validation error
  explaining the subset (document swaps are a HOST action, not an adapter action).

Integration contract with ``bcio`` (worker 3-b, m1-module-contracts §7):
``export_dxf(path, doc, ledger=None) -> dict`` (stats), ``import_dxf(path,
doc=None, ledger=None) -> (Document, dict)``. RECONCILED against the landed bcio:

- ``bcio.import_dxf`` runs inside ONE transaction OF ITS OWN (single undo
  step) and bcdoc v0 does not support nested transactions — so this tool is
  registered with ``adapter_managed_transaction=False``: the adapter still
  enforces the ``base_doc_version`` precondition BEFORE the tool runs (R1
  holds), and the one-undo-step guarantee comes from bcio's transaction.
- With ``into: "current"`` the adapter passes the session document and asserts
  the returned Document IS that document (a different object would be an
  integration mismatch -> ``CAD_E_INTERNAL``, never a silent swap).
- bcio's stats dict maps into the contract result: ``stats["imported"]``
  (per-kind counts + total) becomes ``result.imported.counts`` and the ADR-0003
  loss-ledger entries are surfaced as plain-language ``warnings`` — import never
  silently drops content.
- Filesystem failures (missing/unreadable path) map to ``CAD_E_VALIDATION``
  with ``details.path`` — the 8-code model (contract §3) has no IO-specific
  code and an unusable path argument is a request problem.
"""

from __future__ import annotations

import os

from ..contract import InternalCadError, ValidationError
from .base import ToolContext, ToolSpec, require_str

#: The only DXF version bcio v0 writes (m1-module-contracts §7).
_SUPPORTED_DXF_VERSION = "R12"


def _export_dxf(ctx: ToolContext, args: dict) -> dict:
    import bcio

    path = require_str(args, "path")
    version = args.get("version")
    if version is not None and version != _SUPPORTED_DXF_VERSION:
        raise ValidationError(
            f"unsupported DXF version at M1: {version!r} "
            f"(only {_SUPPORTED_DXF_VERSION}; the v0 writer is R12 ASCII)",
            details={"field": "version", "got": version},
        )
    try:
        stats = bcio.export_dxf(path, ctx.doc)
    except OSError as exc:
        raise ValidationError(
            f"cannot write DXF to path: {path} ({exc})",
            details={"path": path, "reason": str(exc)},
        ) from exc
    if not isinstance(stats, dict):
        stats = {}
    try:
        size = os.stat(path).st_size
    except OSError:  # pragma: no cover — bcio claimed success but path unreadable
        size = int(stats.get("bytes", 0))
    return {
        "path": path,
        "bytes": size,
        "warnings": list(stats.get("warnings", [])),
    }


def _import_dxf(ctx: ToolContext, args: dict) -> dict:
    import bcio

    path = require_str(args, "path")
    into = args.get("into", "current")
    if into != "current":
        raise ValidationError(
            "M1 subset: import targets the current document only "
            "(into='current'); document creation is a host action",
            details={"field": "into", "got": into},
        )
    options = args.get("options")
    if options is not None and not isinstance(options, dict):
        raise ValidationError(
            "options must be an object", details={"field": "options"}
        )
    try:
        merged, stats = bcio.import_dxf(path, doc=ctx.doc)
    except OSError as exc:
        raise ValidationError(
            f"cannot read DXF from path: {path} ({exc})",
            details={"path": path, "reason": str(exc)},
        ) from exc
    if merged is not ctx.doc:
        raise InternalCadError(
            "bcio.import_dxf returned a different Document object instead of "
            "merging into the provided document — integration mismatch "
            "(expected in-place merge per m1-module-contracts §7)",
            details={"path": path},
        )
    if not isinstance(stats, dict):
        stats = {}
    # bcio stats: {engine, path, acadver, recovered, imported: {line, circle,
    # arc, total}, layers, layers_added, handle_reallocations, losses}
    imported = stats.get("imported")
    if not isinstance(imported, dict):
        # honest fallback: the post-merge kind counts (bcio owns the merge)
        imported = dict(ctx.doc.count_by_kind())
    # ADR-0003: losses are surfaced, never silently dropped. The stats->result
    # mapping is EXCEPTION-SAFE by design: bcio's import has already committed
    # its single transaction at this point, so a mapping bug must never turn
    # into an error envelope over an applied change ("never silent partial
    # application" cuts both ways — an error response must mean nothing applied).
    warnings = []
    try:
        losses = stats.get("losses") or []
        if isinstance(losses, (list, tuple)):
            for loss in losses:
                if isinstance(loss, dict):
                    warnings.append(
                        f"{loss.get('dxf_type', loss.get('kind', 'DXF'))}: "
                        f"{loss.get('reason', 'recorded loss')}"
                    )
                else:
                    warnings.append(str(loss))
        reallocations = stats.get("handle_reallocations")
        if isinstance(reallocations, int):
            if reallocations:
                warnings.append(
                    f"{reallocations} DXF handle(s) reallocated on collision")
        elif isinstance(reallocations, (list, tuple)):
            for reallocation in reallocations:
                warnings.append(f"handle reallocated: {reallocation}")
    except Exception:  # pragma: no cover — degrade honestly, never fail post-commit
        warnings.append("import completed; stats mapping degraded")
    return {
        "path": path,
        "imported": {"counts": dict(imported)},
        "engine": stats.get("engine"),
        "warnings": warnings,
    }


TOOL_SPECS = [
    ToolSpec(
        tool_id="cad.io.export_dxf",
        run=_export_dxf,
        classes=("filesystem",),
    ),
    ToolSpec(
        tool_id="cad.io.import_dxf",
        run=_import_dxf,
        transactional=True,
        adapter_managed_transaction=False,  # bcio owns the single transaction
        min_mode="propose",
        classes=("doc-edit", "filesystem"),
    ),
]
