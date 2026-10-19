"""bcio — DXF interchange for Blender CAD (milestone M2, task m2-2d).

Public API (contract: docs/00-architecture/m1-module-contracts.md §7,
extended by m2-module-contracts.md §6):

- :func:`export_dxf`(path, doc, ledger=None) -> stats dict
- :func:`import_dxf`(path, doc=None, ledger=None) -> (Document, stats dict)
- :class:`~bcio.loss_ledger.LossLedger` — the ADR-0003 honesty record

Engines: the conformance oracle :mod:`bcio.ezdxf_bridge` (R2010 through
ezdxf; the preferred path for the full M2 entity set — all 13 kinds,
layer/block/style tables, layouts/paper space, header sysvars, dimensions
through the ezdxf dimension factory) runs when ezdxf is importable; the
in-product pure-Python :mod:`bcio.dxf_minimal` (R12 ASCII) path is the
always-available fallback (LINE/CIRCLE/ARC/TEXT + basic layer records;
every other M2 kind is skipped WITH a loss-ledger entry — never silent).

Import policy (ADR-0003 honesty rules):

- DXF handles are preserved into the document handle space; collisions
  re-allocate the next free handle and are recorded in the ledger; block
  definitions keep their definition handles (members are owned copies
  with handle 0 — member handles are ledgered, never silently dropped);
- unknown entity types are ledgered, never silently dropped;
- import happens inside ONE document transaction (single undo step).

The stats dict is additive over M1: ``stats["entities"]`` /
``stats["imported"]`` carry per-kind counts for all 13 kinds (zero-filled
so the shape is stable), plus ``blocks`` / ``layouts`` /
``layers`` / ``settings`` / ``styles`` counts and the ledger summary
(``losses``).

Pure Python: this package never imports ``bpy``.
"""

from __future__ import annotations

import os
from pathlib import Path

from bcdoc import (
    Arc,
    Circle,
    Dim,
    Document,
    Ellipse,
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
from bcdoc import errors as bcdoc_errors

from . import dxf_minimal, ezdxf_bridge, loss_ledger
from .ezdxf_bridge import INSUNITS_BY_CODE
from .loss_ledger import LossLedger

__all__ = [
    "export_dxf",
    "import_dxf",
    "LossLedger",
    "dxf_minimal",
    "ezdxf_bridge",
    "loss_ledger",
]

__version__ = "0.2.0"

#: bcdoc entity kinds in stats/counts order (M1 kinds first, then M2).
KINDS = ezdxf_bridge.KINDS


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
    counts, reallocations, layers_added, extras = _import_raw(
        doc, raw, label, ledger)

    stats = {
        "engine": engine,
        "path": path,
        "acadver": raw.get("acadver"),
        "recovered": recovered,
        "imported": {**counts, "total": sum(counts.values())},
        "layers": [str(rec.get("name")) for rec in raw.get("layers", [])],
        "layers_added": layers_added,
        "handle_reallocations": reallocations,
        "blocks": extras["blocks"],
        "layouts": [str(rec.get("name")) for rec in raw.get("layouts", [])],
        "settings": extras["settings"],
        "losses": list(ledger.entries),
    }
    return doc, stats


# ---------------------------------------------------------------------------
# raw-record -> document application
# ---------------------------------------------------------------------------

def _entity_from_record(record: dict):
    """Engine-neutral record -> bcdoc entity (geometry + common props)."""
    kwargs = {
        "layer": record.get("layer") or "0",
        "color": record.get("color"),
        "linetype": record.get("linetype") or "ByLayer",
        "lineweight": record.get("lineweight"),
        "space": record.get("space") or "MODEL",
    }
    kind = ezdxf_bridge.DXFTYPE_TO_KIND.get(record["type"])
    if kind == "line":
        return Line(record["p1"], record["p2"], **kwargs)
    if kind == "circle":
        return Circle(record["center"], record["radius"], **kwargs)
    if kind == "arc":
        return Arc(record["center"], record["radius"],
                   record["start_angle"], record["end_angle"], **kwargs)
    if kind == "point":
        return Point(record["position"], **kwargs)
    if kind == "polyline":
        elevation = float(record.get("elevation", 0.0) or 0.0)
        vertices = [(float(x), float(y), elevation)
                    for x, y in record["points"]]
        return Polyline(vertices,
                        bulges=[float(b) for b in record["bulges"]],
                        widths=[[float(s), float(e)] for s, e in record["widths"]],
                        closed=bool(record.get("closed")), **kwargs)
    if kind == "ellipse":
        return Ellipse(record["center"], record["major_axis"],
                       float(record["ratio"]), float(record["start_angle"]),
                       float(record["end_angle"]), **kwargs)
    if kind in ("xline", "ray"):
        start = tuple(record["p1"])
        direction = tuple(record["dir"])
        p2 = (start[0] + direction[0], start[1] + direction[1],
              start[2] + direction[2])
        cls = Xline if kind == "xline" else Ray
        return cls(start, p2, **kwargs)
    if kind == "text":
        return Text(record["position"], float(record["height"]),
                    float(record.get("rotation", 0.0)),
                    record["content"], record.get("style", "Standard"),
                    record.get("justification", "LEFT"), **kwargs)
    if kind == "mtext":
        return Mtext(record["position"], float(record.get("width", 0.0)),
                     record["content"], record.get("style", "Standard"),
                     **kwargs)
    if kind == "dim":
        return Dim(record["dim_type"], record["p1"], record["p2"],
                   float(record.get("angle", 0.0)), record["offset_point"],
                   measured_id="", measurement=float(record.get("measurement", 0.0)),
                   text_override=record.get("text_override", ""),
                   style=record.get("style", "Standard"),
                   text_position=record.get("text_position"), **kwargs)
    if kind == "insert":
        return Insert(record["name"], record["position"],
                     scale=record.get("scale", (1.0, 1.0, 1.0)),
                     rotation=float(record.get("rotation", 0.0)), **kwargs)
    if kind == "viewport":
        return Viewport(record["center"], float(record["view_height"]),
                        record["p1"], record["p2"],
                        locked=bool(record.get("locked")), **kwargs)
    return None


def _add_with_handle(doc, entity, record, ledger, counts, state):
    """Add an entity preserving the DXF handle (M1 rule: import keeps
    foreign handles; collisions re-allocate + ledger)."""
    handle = record.get("handle")
    if handle is None:
        doc.add_entity(entity)
    elif int(handle) < 1:
        doc.add_entity(entity)
        state["reallocations"] += 1
        ledger.append(
            "import", record.get("type", "ENTITY"),
            f"unusable DXF handle {handle!r}; entity allocated "
            f"fresh handle {entity.handle}",
        )
    else:
        handle = int(handle)
        try:
            doc.add_entity(entity, handle=handle)
        except bcdoc_errors.DuplicateHandle:
            doc.add_entity(entity)
            state["reallocations"] += 1
            ledger.append(
                "import", record.get("type", "ENTITY"),
                f"DXF handle 0x{handle:X} collides with an existing "
                f"document handle; entity reallocated as handle {entity.handle}",
            )
    counts[entity.kind] = counts.get(entity.kind, 0) + 1
    state["max_handle"] = max(state["max_handle"], entity.handle)


def _import_raw(doc, raw, label, ledger):
    """Apply engine-neutral raw records to ``doc`` inside one transaction."""
    counts = {kind: 0 for kind in KINDS}
    state = {"reallocations": 0, "max_handle": 0}
    layers_added: list = []
    layout_map: dict = {}   # raw layout name -> doc layout name

    # layout paper units derive from the file's machine-unit hint
    paper_units = "mm"
    hint = raw.get("insunits_hint")
    if hint in INSUNITS_BY_CODE:
        paper_units = INSUNITS_BY_CODE[int(hint)]

    with doc.transaction(label):
        # -- settings (sysvars) ------------------------------------------------
        settings_read = 0
        for name, value in (raw.get("settings") or {}).items():
            try:
                if str(value) != str(doc.settings.get(name)):
                    doc.settings.set(name, value)
                settings_read += 1
            except bcdoc_errors.BcdocError as exc:
                ledger.append(
                    "import", "HEADER",
                    f"header variable for {name}={value!r} rejected by the "
                    f"settings registry ({exc}); value dropped",
                )
        if hint in INSUNITS_BY_CODE:
            try:
                if int(doc.settings.get("INSUNITS")) == 0:
                    doc.settings.set("INSUNITS", int(hint))
                    settings_read += 1
            except bcdoc_errors.BcdocError:
                pass

        # -- layer table --------------------------------------------------------
        for record in raw.get("layers", []):
            name = str(record.get("name") or "0")
            props = {}
            for key in ("color", "linetype", "lineweight", "on", "frozen",
                        "locked", "plot"):
                if key in record and record[key] is not None:
                    props[key] = record[key]
            existing = doc.layers.get(name)
            try:
                if existing is None:
                    doc.layers.add(name, **props)
                    layers_added.append(name)
                elif props:
                    doc.layers.set_props(name, **props)
            except (ValueError, bcdoc_errors.BcdocError) as exc:
                ledger.append(
                    "import", "LAYER",
                    f"layer {name!r} properties {props!r} are not valid "
                    f"bcdoc values ({exc}); imported with defaults",
                )
                if existing is None:
                    doc.add_layer(name)
                    layers_added.append(name)

        # -- style tables ---------------------------------------------------------
        for style in raw.get("text_styles", []):
            name = str(style.get("name", ""))
            if not name:
                continue
            try:
                if name in doc.text_styles():
                    doc.set_text_style_props(
                        name, height=float(style.get("height", 2.5)),
                        width_factor=float(style.get("width_factor", 1.0)))
                else:
                    doc.add_text_style(
                        name, height=float(style.get("height", 2.5)),
                        width_factor=float(style.get("width_factor", 1.0)))
            except (ValueError, bcdoc_errors.BcdocError) as exc:
                ledger.append(
                    "import", "STYLE",
                    f"text style {name!r} rejected ({exc}); skipped",
                )
        for style in raw.get("dim_styles", []):
            name = str(style.get("name", ""))
            if not name:
                continue
            props = {key: float(style.get(key, default))
                     for key, default in (("dimscale", 1.0), ("dimtxt", 2.5),
                                           ("dimasz", 2.5), ("dimexo", 0.625),
                                           ("dimexe", 1.25))}
            try:
                if name in doc.dim_styles():
                    doc.set_dim_style_props(name, **props)
                else:
                    doc.add_dim_style(name, **props)
            except (ValueError, bcdoc_errors.BcdocError) as exc:
                ledger.append(
                    "import", "DIMSTYLE",
                    f"dim style {name!r} rejected ({exc}); skipped",
                )

        # -- layouts (paper spaces) ------------------------------------------------
        for record in raw.get("layouts", []):
            name = str(record.get("name", ""))
            if not name:
                continue
            target_name = name
            if target_name == "MODEL":  # paper layout collides with the space name
                target_name = name + "_FILE"
                ledger.append(
                    "import", "LAYOUT",
                    f"paper layout named {name!r} collides with the bcdoc "
                    f"model-space name; imported as {target_name!r}",
                )
            try:
                layout_record = doc.add_layout(
                    target_name,
                    page_width=float(record.get("page_width", 420.0)),
                    page_height=float(record.get("page_height", 297.0)),
                    paper_units=str(record.get("paper_units", paper_units)),
                )
            except bcdoc_errors.BcdocError as exc:
                ledger.append(
                    "import", "LAYOUT",
                    f"layout {name!r} could not be created ({exc}); its "
                    "entities route to MODEL space",
                )
                layout_map[name] = "MODEL"
                continue
            layout_map[name] = layout_record.name

        # -- block definitions -------------------------------------------------------
        # bcdoc convention (contract §2.3/§6): block members are OWNED
        # copies with NO individual identity — every member of a definition
        # built through the bcdoc API carries handle 0, and only the
        # DEFINITION handle round-trips. File member handles (real DXF
        # handles in foreign files; generator artifacts of our own export)
        # are therefore NOT copied onto the members — the mirror matches
        # the canonical bcdoc form exactly and the handle space stays
        # clean (next_handle tracks definitions + entities only). The drop
        # is ledgered once below — never silent.
        blocks_added = 0
        used_handles = set()
        stripped_member_handles = 0
        for record in raw.get("blocks", []):
            name = str(record.get("name", ""))
            members = []
            for member_record in record.get("entities", []):
                member = _entity_from_record(member_record)
                if member is None:
                    ledger.append(
                        "import", "BLOCK",
                        f"unsupported member in block {name!r} skipped",
                    )
                    continue
                member_handle = member_record.get("handle")
                if member_handle is not None and int(member_handle) >= 1:
                    stripped_member_handles += 1
                members.append(member)
            try:
                definition = doc.add_block(
                    name, record.get("base_point", (0.0, 0.0, 0.0)), members)
            except (ValueError, bcdoc_errors.BcdocError) as exc:
                ledger.append(
                    "import", "BLOCK",
                    f"block definition {name!r} rejected ({exc}); skipped",
                )
                continue
            blocks_added += 1
            # preserve the file's definition handle (table-record rule);
            # a colliding foreign definition handle re-allocates + ledgers
            foreign = record.get("handle")
            if foreign is not None and int(foreign) >= 1:
                foreign = int(foreign)
                if foreign in used_handles:
                    ledger.append(
                        "import", "BLOCK",
                        f"block {name!r} definition handle 0x{foreign:X} "
                        "collides with an imported handle; definition keeps "
                        f"its allocated handle {definition.handle}",
                    )
                else:
                    definition.handle = foreign
                used_handles.add(definition.handle)
            for member in definition.entities:
                state["max_handle"] = max(state["max_handle"], member.handle)
            state["max_handle"] = max(state["max_handle"], definition.handle)

        if stripped_member_handles:
            ledger.append(
                "import", "BLOCK",
                f"{stripped_member_handles} block member handle(s) from the "
                "file are not preserved: bcdoc block members are owned "
                "copies without individual identity (handle 0); the block "
                "definition handle is the identity that round-trips",
            )

        # -- entities (model + paper, routed by record["space"]) ---------------------
        for record in raw.get("entities", []):
            entity = _entity_from_record(record)
            if entity is None:
                continue  # engines ledger unknown types at parse time
            layer = entity.layer
            if layer not in doc.layers:
                doc.add_layer(layer)
                layers_added.append(layer)
                ledger.append(
                    "import", "LAYER",
                    f"entity referenced undefined layer {layer!r}; "
                    "default-property layer record created",
                )
            space = entity.space
            if space != "MODEL":
                entity.space = layout_map.get(space, "MODEL")
                if space not in layout_map:
                    ledger.append(
                        "import", "PAPER_SPACE",
                        f"entity lived in space {space!r} which has no "
                        "matching layout; routed to MODEL space",
                    )
            _add_with_handle(doc, entity, record, ledger, counts, state)

        # keep the monotonic allocator above every preserved foreign handle
        if state["max_handle"] >= doc.next_handle:
            doc.next_handle = state["max_handle"] + 1

    return (counts, state["reallocations"], layers_added,
            {"blocks": blocks_added, "settings": settings_read})
