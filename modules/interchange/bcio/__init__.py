"""bcio — DXF interchange for Blender CAD (milestone M1).

Public API (contract: docs/00-architecture/m1-module-contracts.md §7):

- :func:`export_dxf`(path, doc, ledger=None) -> stats dict
- :func:`import_dxf`(path, doc=None, ledger=None) -> (Document, stats dict)
- :class:`~bcio.loss_ledger.LossLedger` — the ADR-0003 honesty record

Engines: the conformance oracle :mod:`bcio.ezdxf_bridge` (R2010 through
ezdxf) runs when ezdxf is importable; the in-product pure-Python
:mod:`bcio.dxf_minimal` (R12 ASCII) path is the always-available fallback.
The stats dict records which engine ran (``stats["engine"]``).

Import policy (ADR-0003 honesty rules):

- DXF handles are preserved into the document handle space; collisions
  re-allocate the next free handle and are recorded in the ledger;
- unknown entity types are ledgered, never silently dropped;
- import happens inside ONE document transaction (single undo step).

Pure Python: this package never imports ``bpy``.
"""

from __future__ import annotations

import os
from pathlib import Path

from bcdoc import Arc, Circle, Document, Line
from bcdoc import errors as bcdoc_errors

from . import dxf_minimal, ezdxf_bridge, loss_ledger
from .loss_ledger import LossLedger

__all__ = [
    "export_dxf",
    "import_dxf",
    "LossLedger",
    "dxf_minimal",
    "ezdxf_bridge",
    "loss_ledger",
]

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def export_dxf(path, doc, ledger: LossLedger = None) -> dict:
    """Write ``doc`` to ``path`` as ASCII DXF.

    Prefers the ezdxf bridge (R2010); falls back to the pure-Python R12
    writer when ezdxf is not installed. Returns a stats dict with the
    engine used, entity counts and the recorded losses."""
    ledger = ledger if ledger is not None else LossLedger()
    path = str(path)
    if ezdxf_bridge.available():
        stats = ezdxf_bridge.write_dxf(path, doc, ledger)
        stats["engine"] = ezdxf_bridge.ENGINE
    else:  # pragma: no cover - exercised implicitly in minimal-path tests
        stats = dxf_minimal.write_dxf(path, doc, ledger)
        stats["engine"] = dxf_minimal.ENGINE
    stats["path"] = path
    stats["losses"] = list(ledger.entries)
    return stats


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def import_dxf(path, doc=None, ledger: LossLedger = None):
    """Import an ASCII DXF file into a fresh (or the given) document.

    Returns ``(document, stats)``. The import runs inside ONE transaction
    (one undo step). DXF handles are preserved where possible; collisions
    are re-allocated + ledgered; unknown content is ledgered, never
    dropped silently."""
    ledger = ledger if ledger is not None else LossLedger()
    path = str(path)
    if doc is None:
        doc = Document(name=Path(path).stem or "imported")
    if not isinstance(doc, Document):
        raise TypeError("doc must be a bcdoc.Document")

    recovered = False
    if ezdxf_bridge.available():
        try:
            raw = ezdxf_bridge.read_dxf(path, ledger)
            engine = ezdxf_bridge.ENGINE
            recovered = bool(raw.get("recovered"))
        except ezdxf_bridge.EzdxfReadError as exc:
            ledger.append(
                "import", "FILE",
                f"{exc}; falling back to the tolerant r12-minimal reader",
            )
            raw = dxf_minimal.read_dxf(path, ledger)
            engine = dxf_minimal.ENGINE
    else:  # pragma: no cover - exercised implicitly in minimal-path tests
        raw = dxf_minimal.read_dxf(path, ledger)
        engine = dxf_minimal.ENGINE

    label = "DXF import: " + os.path.basename(path)
    counts, reallocations, layers_added = _import_raw(doc, raw, label, ledger)

    stats = {
        "engine": engine,
        "path": path,
        "acadver": raw.get("acadver"),
        "recovered": recovered,
        "imported": {**counts, "total": sum(counts.values())},
        "layers": [str(rec.get("name")) for rec in raw.get("layers", [])],
        "layers_added": layers_added,
        "handle_reallocations": reallocations,
        "losses": list(ledger.entries),
    }
    return doc, stats


def _import_raw(doc, raw, label, ledger):
    """Apply engine-neutral raw records to ``doc`` inside one transaction."""
    counts = {"line": 0, "circle": 0, "arc": 0}
    reallocations = 0
    layers_added: list = []

    with doc.transaction(label):
        # -- layer table -----------------------------------------------------
        for record in raw.get("layers", []):
            name = str(record.get("name") or "0")
            color = record.get("color")
            linetype = record.get("linetype")
            linetype_is_default = (
                linetype is None or str(linetype).upper() == "CONTINUOUS"
            )
            if (color is not None and color != 7) or not linetype_is_default:
                ledger.append(
                    "import", "LAYER",
                    f"layer {name!r} properties (color={color}, "
                    f"linetype={linetype!r}) are not representable in bcdoc "
                    "v0 (layers are names-only); imported as a plain name",
                )
            if name not in doc.layers:
                doc.add_layer(name)
                layers_added.append(name)

        # -- entities -----------------------------------------------------------
        for record in raw.get("entities", []):
            dxftype = record.get("type")
            layer = str(record.get("layer") or "0")
            color = record.get("color")
            if layer not in doc.layers:
                doc.add_layer(layer)
                layers_added.append(layer)
                ledger.append(
                    "import", "LAYER",
                    f"entity referenced undefined layer {layer!r}; "
                    "name-only layer record created",
                )
            if dxftype == "LINE":
                entity = Line(record["p1"], record["p2"], layer=layer, color=color)
            elif dxftype == "CIRCLE":
                entity = Circle(
                    record["center"], record["radius"], layer=layer, color=color)
            elif dxftype == "ARC":
                entity = Arc(
                    record["center"], record["radius"],
                    record["start_angle"], record["end_angle"],
                    layer=layer, color=color,
                )
            else:
                continue  # engines ledger unknown types at parse time

            handle = record.get("handle")
            if handle is None:
                doc.add_entity(entity)
            elif int(handle) < 1:
                doc.add_entity(entity)
                reallocations += 1
                ledger.append(
                    "import", dxftype,
                    f"unusable DXF handle {handle!r}; entity allocated "
                    f"fresh handle {entity.handle}",
                )
            else:
                handle = int(handle)
                try:
                    doc.add_entity(entity, handle=handle)
                except bcdoc_errors.DuplicateHandle:
                    doc.add_entity(entity)
                    reallocations += 1
                    ledger.append(
                        "import", dxftype,
                        f"DXF handle 0x{handle:X} collides with an existing "
                        f"document handle; entity reallocated as "
                        f"handle {entity.handle}",
                    )
            counts[entity.kind] += 1

    return counts, reallocations, layers_added
