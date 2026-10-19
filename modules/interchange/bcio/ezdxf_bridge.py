"""ezdxf conformance oracle for DXF interchange (contract §7).

Used by ``bcio.export_dxf`` / ``bcio.import_dxf`` whenever ``import ezdxf``
succeeds (test environment, user site). When ezdxf is missing the
in-product pure-Python path (``bcio.dxf_minimal``) runs instead — the
returned stats dict always records honestly which engine produced it
(``"engine": "ezdxf" | "r12-minimal"``).

Export: ezdxf ``R2010`` document, ``$INSUNITS`` set from the document's
display unit metadata, layers created, entities written with their
DOCUMENT handles forced into group code 5 (remapped at the ezdxf entity-db
level; collisions with ezdxf-internal object handles are re-allocated and
ledgered — with bcdoc's 0x1001+ handle space this is rare).

Import: ``ezdxf.readfile``; if strict parsing fails, ``ezdxf.recover``
is the fallback for imperfect files (reported via ``recovered=True``).
Model space is iterated for LINE/CIRCLE/ARC + the layer table; anything
else is recorded in the loss ledger, never silently dropped.
"""

from __future__ import annotations

from .loss_ledger import LossLedger

try:  # optional conformance oracle (MIT-licensed); absent = minimal path
    import ezdxf
    import ezdxf.recover as _recover
except ImportError:  # pragma: no cover - environment dependent
    ezdxf = None
    _recover = None

ENGINE = "ezdxf"
#: DXF version written by this bridge.
EXPORT_DXFVERSION = "R2010"

#: bcdoc length-unit display string -> DXF $INSUNITS machine-unit code.
#: This mapping is owned by interchange (document-model doc §3.6).
INSUNITS = {
    "unitless": 0, "none": 0,
    "in": 1, "inch": 1, "inches": 1,
    "ft": 2, "foot": 2, "feet": 2,
    "mi": 3, "mile": 3, "miles": 3,
    "mm": 4, "millimeter": 4, "millimeters": 4,
    "cm": 5, "centimeter": 5, "centimeters": 5,
    "m": 6, "meter": 6, "meters": 6,
    "km": 7, "kilometer": 7, "kilometers": 7,
    "yd": 10, "yard": 10, "yards": 10,
}


class EzdxfReadError(RuntimeError):
    """ezdxf (strict AND recover) could not read the file."""


def available() -> bool:
    """True when the ezdxf oracle is importable."""
    return ezdxf is not None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _aci_color(value):
    """DXF entity color -> bcdoc color: 0 (ByBlock) / 256 (ByLayer) -> None;
    anything else is a plain ACI int."""
    if value is None:
        return None
    try:
        aci = int(value)
    except (TypeError, ValueError):
        return None
    if aci in (0, 256):
        return None
    return aci


def _xyz(vec) -> tuple:
    return (float(vec[0]), float(vec[1]), float(vec[2]))


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def write_dxf(path, doc, ledger: LossLedger = None) -> dict:
    """Write ``doc`` through ezdxf as an R2010 ASCII DXF file."""
    if ezdxf is None:
        raise EzdxfReadError("ezdxf is not installed")
    ledger = ledger if ledger is not None else LossLedger()

    dxf = ezdxf.new(EXPORT_DXFVERSION, setup=False)
    length_unit = str(doc.units.get("length", "")).strip().lower()
    dxf.header["$INSUNITS"] = INSUNITS.get(length_unit, 0)

    for name in doc.layers:
        if name == "0":
            continue  # exists in every ezdxf document
        if name not in dxf.layers:
            # bcdoc v0 layers are names-only -> default color 7 / CONTINUOUS
            dxf.layers.add(str(name), color=7, linetype="CONTINUOUS")

    modelspace = dxf.modelspace()
    db = dxf.entitydb
    written = {"line": 0, "circle": 0, "arc": 0}
    skipped = 0
    max_handle = 0

    for entity in doc.entities():
        dxfattribs = {"layer": str(entity.layer)}
        if entity.color is not None:
            dxfattribs["color"] = int(entity.color)
        try:
            if entity.kind == "line":
                made = modelspace.add_line(
                    _xyz(entity.p1), _xyz(entity.p2), dxfattribs=dxfattribs)
            elif entity.kind == "circle":
                made = modelspace.add_circle(
                    _xyz(entity.center), float(entity.radius), dxfattribs=dxfattribs)
            elif entity.kind == "arc":
                made = modelspace.add_arc(
                    _xyz(entity.center), float(entity.radius),
                    float(entity.start_angle), float(entity.end_angle),
                    dxfattribs=dxfattribs)
            else:  # future kinds — never silent
                skipped += 1
                ledger.append(
                    "export", str(entity.kind).upper(),
                    f"entity kind {entity.kind!r} is not supported by the "
                    "ezdxf writer at v0; entity skipped",
                )
                continue
        except Exception as exc:  # invalid geometry etc. — ledger, don't crash
            skipped += 1
            ledger.append(
                "export", entity.kind.upper(),
                f"ezdxf refused to create the {entity.kind} "
                f"(handle {entity.handle}): {exc}; entity skipped",
            )
            continue

        used = _force_handle(db, made, entity, ledger)
        written[entity.kind] += 1
        max_handle = max(max_handle, used)

    # Keep ezdxf's handle generator above every written handle so
    # $HANDSEED stays consistent for downstream readers.
    seed = int(str(db.handles), 16)
    db.handles.reset("%X" % max(seed, max_handle + 1))

    dxf.saveas(str(path))
    return {
        "engine": ENGINE,
        "dxfversion": EXPORT_DXFVERSION,
        "path": str(path),
        "entities": {**written, "total": sum(written.values())},
        "layers": len(doc.layers),
        "skipped": skipped,
        "losses": list(ledger.entries),
    }


def _force_handle(db, ezdxf_entity, bcdoc_entity, ledger) -> int:
    """Force the bcdoc entity handle onto the ezdxf entity (group code 5).

    Returns the handle actually written. On a collision with an existing
    DXF object handle the ezdxf-assigned handle is kept and the deviation
    is recorded in the ledger."""
    target = "%X" % int(bcdoc_entity.handle)
    current = ezdxf_entity.dxf.handle
    if db.get(target) is not None:
        ledger.append(
            "export", bcdoc_entity.kind.upper(),
            f"document handle {bcdoc_entity.handle} (0x{target}) collides "
            f"with an existing DXF object handle; exported with reallocated "
            f"handle 0x{current}",
        )
        return int(current, 16)
    if current is not None and current != target:
        del db[current]
        ezdxf_entity.dxf.handle = target
        db.add(ezdxf_entity)
    return int(bcdoc_entity.handle)


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def read_dxf(path, ledger: LossLedger = None) -> dict:
    """Read an ASCII DXF file through ezdxf into engine-neutral raw dicts.

    Raises :class:`EzdxfReadError` when neither strict reading nor
    ``ezdxf.recover`` can process the file (caller falls back to the
    tolerant minimal reader)."""
    if ezdxf is None:
        raise EzdxfReadError("ezdxf is not installed")
    ledger = ledger if ledger is not None else LossLedger()

    recovered = False
    try:
        # NB: ezdxf.readfile raises OSError (not DXFError) for files that are
        # not DXF at all, so BOTH exception types route into the recover
        # fallback (and from there into the caller's minimal-reader path).
        dxf = ezdxf.readfile(str(path))
    except (OSError, ezdxf.DXFError) as exc:
        try:
            dxf, auditor = _recover.readfile(str(path))
            recovered = True
            ledger.append(
                "import", "FILE",
                f"file failed strict ezdxf parsing ({exc}); "
                "loaded through ezdxf.recover",
            )
            if getattr(auditor, "errors", None):
                ledger.append(
                    "import", "FILE",
                    f"ezdxf.recover reported {len(auditor.errors)} issue(s) "
                    "while rebuilding the file",
                )
        except Exception as exc2:
            raise EzdxfReadError(
                f"ezdxf cannot read {path!r} (strict: {exc}; recover: {exc2})"
            ) from exc2

    # Conformance oracle (contract §7 "... and audit"): audit the loaded
    # document and ledger every issue — importing is never allowed to hide
    # file problems. A clean file contributes no entries (asserted by tests).
    try:
        auditor = dxf.audit()
        if getattr(auditor, "errors", None):
            ledger.append(
                "import", "FILE",
                f"ezdxf audit reported {len(auditor.errors)} issue(s) "
                "in this file",
            )
    except Exception as exc:  # audit must never break an otherwise-good import
        ledger.append(
            "import", "FILE",
            f"ezdxf audit could not run ({exc}); file imported unaudited",
        )

    # -- layer table ---------------------------------------------------------
    layers = []
    for layer in dxf.layers:
        layers.append({
            "name": str(layer.dxf.name),
            "color": int(getattr(layer.dxf, "color", 7) or 7),
            "linetype": getattr(layer.dxf, "linetype", None),
        })

    # -- model space entities ---------------------------------------------------
    entities = []
    for entity in dxf.modelspace():
        dxftype = entity.dxftype()
        try:
            handle = int(str(entity.dxf.handle), 16)
        except (ValueError, TypeError, AttributeError):
            handle = None
        if dxftype not in ("LINE", "CIRCLE", "ARC"):
            ledger.append(
                "import", dxftype,
                "entity type not supported by bcio v0 "
                "(LINE/CIRCLE/ARC only); entity not imported",
            )
            continue

        true_color = getattr(entity.dxf, "true_color", None)
        if true_color is not None:
            ledger.append(
                "import", dxftype,
                f"true color {true_color} (group code 420) is not "
                "representable in bcdoc v0 (ACI only); reduced to ACI",
            )

        try:
            color = _aci_color(getattr(entity.dxf, "color", None))
            record = {
                "type": dxftype,
                "handle": handle,
                "layer": str(getattr(entity.dxf, "layer", "0") or "0"),
                "color": color,
            }
            if dxftype == "LINE":
                record["p1"] = _xyz(entity.dxf.start)
                record["p2"] = _xyz(entity.dxf.end)
            elif dxftype == "CIRCLE":
                record["center"] = _xyz(entity.dxf.center)
                record["radius"] = float(entity.dxf.radius)
            else:  # ARC
                record["center"] = _xyz(entity.dxf.center)
                record["radius"] = float(entity.dxf.radius)
                record["start_angle"] = float(entity.dxf.start_angle)
                record["end_angle"] = float(entity.dxf.end_angle)
        except Exception as exc:  # malformed entity — ledger, don't crash
            ledger.append(
                "import", dxftype,
                f"malformed {dxftype} entity (handle {entity.dxf.handle}): "
                f"{exc}; entity not imported",
            )
            continue
        entities.append(record)

    # -- paper space honesty -----------------------------------------------------
    paper_space_count = 0
    try:
        for name in dxf.layouts.names():
            if name.upper() == "MODEL":
                continue
            paper_space_count += len(list(dxf.layouts.get(name)))
    except Exception:  # layouts API differs across versions — never fatal
        pass
    if paper_space_count:
        ledger.append(
            "import", "<paperspace>",
            f"{paper_space_count} paper-space entities exist; paper space "
            "is not imported at M1 (model space only)",
        )

    return {
        "acadver": getattr(dxf, "dxfversion", None),
        "layers": layers,
        "entities": entities,
        "recovered": recovered,
        "engine": ENGINE,
    }
