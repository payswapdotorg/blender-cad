"""ezdxf conformance oracle for DXF interchange (contracts §6/§7).

Used by ``bcio.export_dxf`` / ``bcio.import_dxf`` whenever ``import ezdxf``
succeeds (test environment, user site). When ezdxf is missing the
in-product pure-Python path (``bcio.dxf_minimal``) runs instead — the
returned stats dict always records honestly which engine produced it
(``"engine": "ezdxf" | "r12-minimal"``).

Verified against ezdxf 1.4.3 (python3.12) AND 1.4.5 (Blender 5.2.2's
python3.13) with probe scripts — the exact API names this module relies on:

- ``msp.add_lwpolyline(points, format="xyseb", close=bool, dxfattribs=)``
  — point tuples are ``(x, y, start_width, end_width, bulge)``; the bulge
  sign convention is AutoCAD's (positive = CCW) — identical to bcdoc,
  mapped 1:1. Read-back: ``get_points("xyseb")``, ``dxf.flags & 1``
  (closed), ``dxf.elevation`` (the single z of the 2D polyline).
- ``add_point(location)`` -> ``dxf.location``.
- ``add_ellipse(center, major_axis=(dx,dy), ratio, start_param, end_param)``
  — params in RADIANS (bcdoc stores degrees; ``math.radians`` maps 360° to
  exactly ``2*math.pi``). ratio must be <= 1.0 (ezdxf refuses larger).
- ``add_xline(start, unit_vector)`` / ``add_ray(start, unit_vector)`` —
  DXF stores p1 + a NORMALIZED direction (``dxf.unit_vector``); the second
  point's magnitude is therefore not representable (ledgered on export,
  reconstructed as ``p1 + unit_vector`` on import).
- ``add_text(text, dxfattribs={"height","rotation","style"})`` +
  ``.set_placement(point, align=TextEntityAlignment.LEFT/CENTER/RIGHT)``
  — writes ``insert`` + ``align_point`` + ``halign``/``valign``.
- ``add_mtext(text, dxfattribs={"width"})`` + ``.set_location(point,
  attachment_point=7)``; newlines are written as ``\\P`` — read back via
  ``plain_text()``; ``dxf.char_height`` (default 2.5) is NOT representable
  in bcdoc (ledgered when non-default).
- INSERT: ``add_blockref(name, insert=..., dxfattribs={"rotation",
  "xscale","yscale","zscale"})`` (there is NO ``add_insert`` in ezdxf).
- Layouts: ``doc.layouts.names()/get(name)/new(name)``; page size via
  ``layout.dxf.paper_width``/``paper_height`` (direct assignment audits
  clean); paperspace entities carry ``dxf.paperspace == 1``.
- VIEWPORT: ``layout.add_viewport(center, size=(w,h), view_center_point,
  view_height, status=2)``; paper rect = ``dxf.center``/``width``/
  ``height``; model view = ``dxf.view_center_point``/``dxf.view_height``;
  display lock = bit 0x4000 of ``dxf.flags`` (16384, "zoom locking").
- Layers: ``doc.layers.add(name, color=, linetype=, lineweight=)`` +
  helpers ``off()/freeze()/lock()``; read ``is_off()/is_frozen()/
  is_locked()``, ``dxf.color`` (negative = off), ``dxf.flags`` (bit 1
  frozen, bit 4 locked), ``dxf.plot``.
- Lineweight (group 370): enum in 1/100 mm; specials -3 BYLAYER, -2
  BYBLOCK, -1 DEFAULT. bcdoc mm floats map to the nearest enum value
  (ledgered when the rounding is lossy).
- Dimensions: ``add_linear_dim(base=, p1=, p2=, location=None, text=
  '<>'|str|None, angle=, dimstyle=).render()`` and ``add_aligned_dim(p1=,
  p2=, distance=, text=, dimstyle=).render()``; the rendered DIMENSION
  carries ``dxf.dimtype`` (bit 6 = 0x20 "anonymous geometry block" is
  always set; type = ``dimtype & 7`` — 0 linear, 1 aligned), definition
  points ``defpoint`` (a point ON the dimension line), ``defpoint2`` (p1),
  ``defpoint3`` (p2), ``dxf.angle``, ``dxf.text`` (``'<>'`` = auto
  measurement), ``dxf.text_midpoint``, bit 0x80 = user-positioned text.
  Post-render patching is VERIFIED audit-clean: ``dxf.defpoint = our
  offset_point`` (exact round-trip of the dim-line anchor) and
  ``dxf.dimtype |= 1`` for aligned dims (ezdxf itself writes aligned dims
  as rotated linear dims).
- Styles: ``doc.styles.add(name, font=..., dxfattribs={"height","width"})``
  (``width``, not width_factor; ``font`` required); ``doc.dimstyles.new(
  name, dxfattribs={"dimscale","dimtxt","dimasz","dimexo","dimexe"})``
  (lowercase). ezdxf's built-in "Standard" dim style defaults match the
  bcdoc DimStyleRecord defaults exactly.
- Linetypes: ``doc.linetypes.add(name, pattern=[total, dash, gap, ...],
  description=)`` — bcdoc stores linetype NAMES only, so non-continuous
  types are exported with a solid stub pattern (ledgered).
- Header: $CLAYER, $OSMODE, $ORTHOMODE, $TILEMODE, $INSUNITS, $LUNITS,
  $LUPREC, $AUNITS, $AUPREC, $LTSCALE, $DIMSTYLE, $TEXTSTYLE are safe;
  $DYNMODE / $SNAPMODE / $SNAPUNIT / $GRIDMODE / $GRIDUNIT / $APERTURE /
  $PICKFIRST are NOT in ezdxf's header registry (ledgered). $CLAYER may
  read back as a layer NAME or a HANDLE — both are resolved.

Import: ``ezdxf.readfile``; on failure ``ezdxf.recover``; the loaded
document is audited and every issue ledgered (never hidden). Everything
outside the bcdoc model is ledgered, never silently dropped.
"""

from __future__ import annotations

import math

from .loss_ledger import LossLedger

try:  # optional conformance oracle (MIT-licensed); absent = minimal path
    import ezdxf
    import ezdxf.recover as _recover
    from ezdxf.enums import TextEntityAlignment
except ImportError:  # pragma: no cover - environment dependent
    ezdxf = None
    _recover = None
    TextEntityAlignment = None

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

#: $INSUNITS machine-unit code -> canonical bcdoc length-unit display
#: string (short form preferred; reverse of :data:`INSUNITS`).
INSUNITS_BY_CODE = {
    1: "in", 2: "ft", 3: "mi", 4: "mm", 5: "cm", 6: "m", 7: "km", 10: "yd",
}

#: bcdoc setting name -> DXF header variable actually written by export.
SETTINGS_TO_HEADER = {
    "CLAYER": "$CLAYER",
    "OSMODE": "$OSMODE",
    "ORTHOMODE": "$ORTHOMODE",
    "TILEMODE": "$TILEMODE",
    "LUNITS": "$LUNITS",
    "LUPREC": "$LUPREC",
    "AUNITS": "$AUNITS",
    "AUPREC": "$AUPREC",
    "LTSCALE": "$LTSCALE",
    "TEXTSTYLE": "$TEXTSTYLE",
    "DIMSTYLE": "$DIMSTYLE",
}

#: bcdoc settings that have NO DXF header variable (or none expressible
#: through ezdxf's header registry) — exported values are lost, ledgered
#: whenever they differ from the registry default.
SETTINGS_NOT_IN_HEADER = (
    "SNAPMODE", "SNAPUNIT", "GRIDMODE", "GRIDUNIT", "APERTURE",
    "PICKFIRST", "DYNMODE",
)

#: DXF lineweight enum values (group 370) in 1/100 mm — the OFFICIAL
#: 24-step set from the DXF reference (AutoCAD's lineweight dropdown:
#: 0.00 … 2.11 mm), identical to ezdxf's ``ezdxf.const.VALID_DXF_LINEWEIGHTS``.
#: Probe evidence (m2-2d-fix, ezdxf 1.4.3): an entity created with a code
#: outside this set (e.g. 31) is silently mangled by ezdxf to 35 — values
#: outside this enum are NOT writable, so lossy mm values map to the
#: NEAREST VALID step and the deviation is ledgered in :func:`_lineweight_to_enum`.
LINEWEIGHT_ENUM = (
    0, 5, 9, 13, 15,  18, 20, 25, 30, 35,  40, 50, 53, 60, 70, 80,
    90, 100, 106, 120, 140, 158, 200, 211,
)
LINEWEIGHT_BY_LAYER = -3
LINEWEIGHT_BY_BLOCK = -2
LINEWEIGHT_DEFAULT = -1

#: bcdoc entity kinds handled by this engine (export counts are seeded
#: with every kind so the stats shape is stable and additive).
KINDS = (
    "line", "circle", "arc", "point", "polyline", "ellipse", "xline",
    "ray", "text", "mtext", "dim", "insert", "viewport",
)

#: DXF entity type -> bcdoc kind (import dispatch).
DXFTYPE_TO_KIND = {
    "LINE": "line",
    "CIRCLE": "circle",
    "ARC": "arc",
    "POINT": "point",
    "LWPOLYLINE": "polyline",
    "ELLIPSE": "ellipse",
    "XLINE": "xline",
    "RAY": "ray",
    "TEXT": "text",
    "MTEXT": "mtext",
    "DIMENSION": "dim",
    "INSERT": "insert",
    "VIEWPORT": "viewport",
}

#: ezdxf text alignment enum value -> bcdoc justification string.
_ALIGNMENT_TO_JUSTIFICATION = {
    0: "LEFT", 1: "CENTER", 2: "RIGHT",
}
_JUSTIFICATION_TO_ALIGNMENT = {
    "LEFT": "LEFT", "CENTER": "CENTER", "RIGHT": "RIGHT",
}

#: VIEWPORT display-lock bit ("Enables viewport zoom locking").
VIEWPORT_LOCKED_FLAG = 0x4000
#: Default ezdxf MTEXT character height (bcdoc has no mtext height field).
MTEXT_DEFAULT_CHAR_HEIGHT = 2.5

#: MTEXT raw-content characters that indicate inline formatting codes or
#: grouping braces (contract §13: "MTEXT inline formatting" is NOT claimed).
_MTEXT_FORMATTING_CHARS = tuple("\\{}")


class EzdxfReadError(RuntimeError):
    """ezdxf (strict AND recover) could not read the file."""


def available() -> bool:
    """True when the ezdxf oracle is importable."""
    return ezdxf is not None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _aci_color(value):
    """DXF entity color -> bcdoc color: 256 (ByLayer) / absent -> None
    (bcdoc's ByLayer default); 0 (ByBlock) IS representable at M2 (bcdoc
    color 0 = ByBlock, contract §2.1/§6 — block members keep it) and maps
    through unchanged; anything else is a plain ACI int."""
    if value is None:
        return None
    try:
        aci = int(value)
    except (TypeError, ValueError):
        return None
    if aci == 256:
        return None
    return aci


def _xyz(vec) -> tuple:
    return (float(vec[0]), float(vec[1]), float(vec[2]))


def _lineweight_to_enum(mm: float, kind: str, name: str, ledger):
    """bcdoc millimeters -> nearest DXF lineweight enum value (1/100 mm).

    A lossy rounding (the exact mm value is not a valid enum step) is
    recorded in the ledger — never silent."""
    value = int(round(float(mm) * 100.0))
    nearest = min(LINEWEIGHT_ENUM, key=lambda code: abs(code - value))
    if abs(nearest / 100.0 - float(mm)) > 1e-9:
        ledger.append(
            "export", "LAYER" if kind == "layer" else "ENTITY",
            f"lineweight {mm} mm of {name!r} is not a valid DXF lineweight "
            f"step; exported as the nearest enum value {nearest / 100.0} mm",
        )
    return nearest


def _enum_to_lineweight(value, ledger, what: str):
    """DXF lineweight enum -> bcdoc mm (None for ByLayer/default).

    ByBlock (-2) is not representable in bcdoc (no per-entity ByBlock
    lineweight) — ledgered and reduced to ByLayer."""
    if value is None:
        return None
    try:
        code = int(value)
    except (TypeError, ValueError):
        return None
    if code in (LINEWEIGHT_BY_LAYER, LINEWEIGHT_DEFAULT):
        return None
    if code == LINEWEIGHT_BY_BLOCK:
        ledger.append(
            "import", "LAYER" if what == "layer" else "ENTITY",
            "ByBlock lineweight (-2) is not representable in bcdoc "
            "(lineweight is None or mm); reduced to ByLayer",
        )
        return None
    if code in LINEWEIGHT_ENUM:
        return code / 100.0
    if code < 0:  # unknown special value — tolerate as ByLayer
        return None
    return code / 100.0  # tolerant: nonstandard but numeric


def exported_settings(doc) -> dict:
    """The settings values AS EXPORTED (shared by write_dxf and the
    round-trip compare so both sides agree on derivations).

    - INSUNITS: the registry setting when nonzero, else derived from the
      document's length-unit display metadata (M1 behavior preserved);
    - the SETTINGS_TO_HEADER subset 1:1;
    - settings without a header variable are omitted (the caller ledgers
      non-default ones)."""
    values = {}
    insunits = int(doc.settings.get("INSUNITS"))
    if insunits == 0:
        insunits = INSUNITS.get(
            str(doc.units.get("length", "")).strip().lower(), 0)
    values["INSUNITS"] = insunits
    for name in SETTINGS_TO_HEADER:
        if name == "INSUNITS":
            continue
        values[name] = doc.settings.get(name)
    return values


def _ensure_ltype(dxf, name: str, ledger) -> None:
    """Make sure a linetype NAME exists in the LTYPE table (bcdoc stores
    names only — non-continuous types are stubbed with a solid pattern
    and the missing pattern data is ledgered)."""
    if not name or name.upper() in ("BYLAYER", "BYBLOCK", "CONTINUOUS"):
        return
    if name in dxf.linetypes:
        return
    dxf.linetypes.add(name, pattern=[0.0], description="bcdoc name-only stub")
    ledger.append(
        "export", "LTYPE",
        f"linetype {name!r} has no dash-pattern data in bcdoc (names only); "
        "exported as a solid stub so the name round-trips",
    )


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def write_dxf(path, doc, ledger: LossLedger = None) -> dict:
    """Write ``doc`` through ezdxf as an R2010 ASCII DXF file."""
    if ezdxf is None:
        raise EzdxfReadError("ezdxf is not installed")
    ledger = ledger if ledger is not None else LossLedger()

    dxf = ezdxf.new(EXPORT_DXFVERSION, setup=False)
    db = dxf.entitydb

    # M1 handle rule (contract §6: "foreign handles preserved on import;
    # export maps back; zero reallocations expected") requires that every
    # bcdoc handle can be forced onto its DXF object WITHOUT collision.
    # ezdxf's own factory objects (block members with bcdoc handle 0,
    # dimension-geometry blocks, layout/block-record containers) draw their
    # handles from the generator; if the generator runs THROUGH the bcdoc
    # handle range it steals exactly those values and every later force
    # becomes a reallocation (probe m2-2d-fix: BLK's members consumed
    # 0x1002-0x1004 and 23 of 23 entities were displaced). Pre-seeding the
    # generator strictly above the bcdoc handle space makes every forced
    # handle collision-free; factory objects get handles beyond the
    # document's, which nothing else claims.
    ceiling = _doc_handle_ceiling(doc)
    seed = int(str(db.handles), 16)
    db.handles.reset("%X" % max(seed, ceiling + 1))

    # -- header sysvars ------------------------------------------------------
    settings_written = _export_header(dxf, doc, ledger)

    # -- layer table ----------------------------------------------------------
    _export_layers(dxf, doc, ledger)

    # -- style tables -----------------------------------------------------------
    _export_styles(dxf, doc, ledger)

    # -- layouts (paper space) --------------------------------------------------
    layout_space = _export_layouts(dxf, doc, ledger)

    # -- block definitions -------------------------------------------------------
    blocks_written = _export_blocks(dxf, doc, db, ledger)

    # -- entities (model + paper, routed by entity.space) -------------------------
    written = {kind: 0 for kind in KINDS}
    skipped = 0
    max_handle = 0
    for entity in doc.entities():
        space = entity.space
        target = layout_space.get(space)
        if space != "MODEL" and target is None:
            skipped += 1
            ledger.append(
                "export", entity.kind.upper(),
                f"entity references layout {space!r} which could not be "
                "created in the DXF file; entity skipped",
            )
            continue
        made = _export_entity(target, entity, dxf, ledger)
        if made is None:
            skipped += 1
            continue
        used = _force_handle(db, made, entity, ledger)
        max_handle = max(max_handle, used)
        written[entity.kind] += 1

    # -- session state honesty (contract §2.4/§6: not a file concept) -------------
    if doc.current_space != "MODEL":
        ledger.append(
            "export", "PAPER_SPACE",
            f"current space {doc.current_space!r} is SESSION state; DXF "
            "persists only $TILEMODE — the active space is not exported",
        )
    if getattr(doc, "active_layout", None) is not None:
        ledger.append(
            "export", "LAYOUT",
            f"active layout {doc.active_layout!r} is SESSION state; DXF "
            "persists an active-layout marker that bcdoc deliberately does "
            "not model — not exported",
        )

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
        "blocks": blocks_written,
        "layouts": len(doc.layouts()),
        "styles": {"text": len(doc.text_styles()),
                   "dim": len(doc.dim_styles())},
        "settings": settings_written,
        "skipped": skipped,
        "losses": list(ledger.entries),
    }


def _export_header(dxf, doc, ledger) -> int:
    """Write the representable settings subset into the DXF header; ledger
    every non-representable non-default setting."""
    values = exported_settings(doc)
    written = 0
    for name, value in values.items():
        variable = SETTINGS_TO_HEADER.get(name)
        if name == "INSUNITS":
            variable = "$INSUNITS"
        if variable is None:
            continue
        try:
            if name == "CLAYER":
                if value not in doc.layers:
                    ledger.append(
                        "export", "HEADER",
                        f"$CLAYER {value!r} references a layer that does not "
                        "exist in the layer table; exported as-is",
                    )
                dxf.header[variable] = str(value)
            else:
                dxf.header[variable] = value
            written += 1
        except Exception as exc:  # unknown var, type refused — ledger
            ledger.append(
                "export", "HEADER",
                f"setting {name}={value!r} could not be written to the DXF "
                f"header ({exc}); value lost",
            )
    # settings with no header variable: honest loss note when non-default
    for name in SETTINGS_NOT_IN_HEADER:
        value = doc.settings.get(name)
        default = doc.settings.definitions()[name]["default"]
        if value != default:
            ledger.append(
                "export", "SETTINGS",
                f"setting {name}={value!r} has no DXF header variable "
                "(not representable in a DXF file through ezdxf); lost",
            )
    return written


def _doc_handle_ceiling(doc) -> int:
    """Highest handle anywhere in the bcdoc handle space (store entities,
    block definitions, block members). Members normally carry 0 (owned
    copies have no individual identity) but a poked/migrated document can
    carry real member handles — they count too."""
    handles = [int(entity.handle) for entity in doc.entities()]
    for name in doc.block_names():
        definition = doc.block(name)
        handles.append(int(definition.handle))
        handles.extend(int(member.handle) for member in definition.entities)
    return max(handles, default=0)


def _export_layers(dxf, doc, ledger) -> None:
    """Full layer table: color ACI, linetype name, lineweight, on/frozen/
    locked/plot flags."""
    for record in doc.layers.records():
        name = str(record.name)
        if name not in dxf.layers:
            dxf.layers.add(name)
        layer = dxf.layers.get(name)
        _ensure_ltype(dxf, record.linetype, ledger)
        layer.dxf.color = int(record.color) if record.color is not None else 7
        if not record.on:
            layer.off()
        layer.dxf.linetype = str(record.linetype)
        if record.lineweight is None:
            layer.dxf.lineweight = LINEWEIGHT_DEFAULT
        else:
            layer.dxf.lineweight = _lineweight_to_enum(
                record.lineweight, "layer", name, ledger)
        if record.frozen:
            layer.freeze()
        if record.locked:
            layer.lock()
        layer.dxf.plot = 1 if record.plot else 0


def _export_styles(dxf, doc, ledger) -> None:
    """Text + dim style tables (name + the fields bcdoc models). bcdoc has
    no font data, so created styles carry ezdxf's default font ("txt") —
    nothing we own is lost (fonts are ledgered on IMPORT, where they
    genuinely drop)."""
    for name in doc.text_styles():
        data = doc.text_style(name).to_dict()
        if name in dxf.styles:
            style = dxf.styles.get(name)
        else:
            style = dxf.styles.add(name, font="txt")
        style.dxf.height = float(data["height"])
        style.dxf.width = float(data["width_factor"])

    for name in doc.dim_styles():
        data = doc.dim_style(name).to_dict()
        if name in dxf.dimstyles:
            style = dxf.dimstyles.get(name)
        else:
            style = dxf.dimstyles.new(name)
        for field in ("dimscale", "dimtxt", "dimasz", "dimexo", "dimexe"):
            setattr(style.dxf, field, float(data[field]))


def _export_layouts(dxf, doc, ledger) -> dict:
    """One paper-space layout per doc layout record. Returns
    ``{layout name -> Paperspace}`` for entity routing (MODEL -> msp).

    ezdxf.new() seeds a default empty "Layout1" paper space in every fresh
    document. The contract says ONE paper-space layout PER DOC LAYOUT, so
    when the document owns at least one layout the unused default is
    DELETED (probe m2-2d-fix: re-read + audit clean) and the file's layout
    set matches the document exactly. A document with no layouts keeps it
    — the DXF format requires at least one paper-space layout (probe:
    "Can not delete last paperspace layout") — and the importer accepts it
    as the foreign extra the compare subset rule already anticipates."""
    routing = {"MODEL": dxf.modelspace()}
    for name in doc.layouts():
        record = doc.layout(name)
        if name in dxf.layouts:
            layout = dxf.layouts.get(name)
        else:
            layout = dxf.layouts.new(name)
        layout.dxf.paper_width = float(record.page_width)
        layout.dxf.paper_height = float(record.page_height)
        routing[name] = layout
    if doc.layouts() and "Layout1" in dxf.layouts \
            and "Layout1" not in doc.layouts():
        try:
            dxf.layouts.delete("Layout1")
        except Exception as exc:  # structural default refused to die
            ledger.append(
                "export", "LAYOUT",
                f"the default empty 'Layout1' paper space could not be "
                f"removed ({exc}); the file carries one layout more than "
                "the document (no document content is lost)",
            )
    return routing


def _export_blocks(dxf, doc, db, ledger) -> int:
    """Block definitions with member geometry + definition handles."""
    written = 0
    for name in doc.block_names():
        definition = doc.block(name)
        try:
            block = dxf.blocks.new(str(name), base_point=_xyz(definition.base_point))
        except Exception as exc:
            ledger.append(
                "export", "BLOCK",
                f"block definition {name!r} could not be created in the DXF "
                f"file ({exc}); definition + its inserts skipped",
            )
            continue
        # force the bcdoc definition handle onto the BLOCK table entity
        max_used = _force_handle(db, block.block, definition, ledger)
        for member in definition.entities:
            made = _export_entity(block, member, dxf, ledger)
            if made is None:
                continue
            used = _force_handle(db, made, member, ledger)
            max_used = max(max_used, used)
        written += 1
    return written


def _export_dim(dxf, target, entity, dxfattribs, ledger):
    """DIMENSION export through the ezdxf dimension factory.

    The rendered DIMENSION's ``defpoint`` is patched to the bcdoc
    ``offset_point`` (both lie on the dimension line, so the geometry is
    unchanged and the anchor round-trips exactly — verified audit-clean)
    and aligned dims get dimtype bit 1 set (ezdxf itself writes aligned
    dims as rotated linear dims)."""
    dimstyle = str(entity.style)
    if dimstyle not in dxf.dimstyles:
        dxf.dimstyles.new(dimstyle)
        ledger.append(
            "export", "DIMSTYLE",
            f"dimension references dim style {dimstyle!r} that is not "
            "defined in the document's dim style table; exported with a "
            "default-definition stub so the name round-trips",
        )
    # NB: text=None is NOT safe — ezdxf stringifies it; '<>' means "auto
    # measurement" (verified: None writes the literal string "None").
    text = str(entity.text_override) if entity.text_override else "<>"
    location = entity.text_position if entity.text_position is not None else None
    if entity.dim_type == "aligned":
        # distance = signed perpendicular offset of the dim line from p1->p2
        dx = entity.p2[0] - entity.p1[0]
        dy = entity.p2[1] - entity.p1[1]
        length = math.hypot(dx, dy)
        if length < 1e-12:
            raise ValueError("aligned dim p1 == p2")
        distance = ((entity.offset_point[0] - entity.p1[0]) * dy
                    - (entity.offset_point[1] - entity.p1[1]) * dx) / length
        renderer = target.add_aligned_dim(
            p1=_xyz(entity.p1), p2=_xyz(entity.p2),
            distance=float(distance), text=text, dimstyle=dimstyle,
            dxfattribs=dxfattribs)
    else:
        renderer = target.add_linear_dim(
            base=_xyz(entity.offset_point), p1=_xyz(entity.p1),
            p2=_xyz(entity.p2), angle=float(entity.angle), text=text,
            location=location, dimstyle=dimstyle, dxfattribs=dxfattribs)
    renderer.render()
    dimension = renderer.dimension
    # exact round-trip of the dim-line anchor + aligned type bit
    dimension.dxf.defpoint = _xyz(entity.offset_point)
    if entity.dim_type == "aligned":
        dimension.dxf.dimtype = int(dimension.dxf.dimtype) | 1
        if location is not None:  # no `location` arg on aligned dims
            dimension.dxf.text_midpoint = _xyz(location)
            dimension.dxf.dimtype = int(dimension.dxf.dimtype) | 0x80
    return dimension


def _export_entity(target, entity, dxf, ledger):
    """One bcdoc entity -> one DXF entity in ``target`` (modelspace, a
    paperspace layout or a block layout). Returns the ezdxf entity or
    None (the failure is already ledgered)."""
    dxfattribs = {"layer": str(entity.layer)}
    if entity.color is not None:
        dxfattribs["color"] = int(entity.color)
    linetype = getattr(entity, "linetype", None)
    if linetype and linetype != "ByLayer":
        dxfattribs["linetype"] = str(linetype)
        _ensure_ltype(dxf, str(linetype), ledger)
    if entity.lineweight is not None:
        dxfattribs["lineweight"] = _lineweight_to_enum(
            entity.lineweight, "entity",
            f"{entity.kind} handle {entity.handle}", ledger)
    kind = entity.kind
    try:
        if kind == "line":
            return target.add_line(_xyz(entity.p1), _xyz(entity.p2),
                                    dxfattribs=dxfattribs)
        if kind == "circle":
            return target.add_circle(_xyz(entity.center), float(entity.radius),
                                     dxfattribs=dxfattribs)
        if kind == "arc":
            return target.add_arc(_xyz(entity.center), float(entity.radius),
                                  float(entity.start_angle), float(entity.end_angle),
                                  dxfattribs=dxfattribs)
        if kind == "point":
            return target.add_point(_xyz(entity.position), dxfattribs=dxfattribs)
        if kind == "polyline":
            return _export_polyline(target, entity, dxfattribs)
        if kind == "ellipse":
            return target.add_ellipse(
                _xyz(entity.center), major_axis=_xyz(entity.major_axis),
                ratio=float(entity.ratio),
                start_param=math.radians(float(entity.start_angle)),
                end_param=math.radians(float(entity.end_angle)),
                dxfattribs=dxfattribs)
        if kind == "xline" or kind == "ray":
            start = _xyz(entity.p1)
            dx = entity.p2[0] - entity.p1[0]
            dy = entity.p2[1] - entity.p1[1]
            dz = entity.p2[2] - entity.p1[2]
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length < 1e-12:
                raise ValueError(f"{kind} needs a nonzero direction (p2 != p1)")
            if length != 1.0:
                ledger.append(
                    "export", kind.upper(),
                    f"{kind} second point distance {length!r} is not "
                    "representable — DXF stores a normalized unit direction "
                    "vector (the entity is infinite; the direction is the "
                    "geometry); exported as a unit vector",
                )
            unit = (dx / length, dy / length, dz / length)
            if kind == "xline":
                return target.add_xline(start, unit, dxfattribs=dxfattribs)
            return target.add_ray(start, unit, dxfattribs=dxfattribs)
        if kind == "text":
            return _export_text(target, entity, dxfattribs)
        if kind == "mtext":
            mtext = target.add_mtext(str(entity.content),
                                     dxfattribs={**dxfattribs,
                                                 "width": float(entity.width)})
            mtext.set_location(_xyz(entity.position), attachment_point=7)
            return mtext
        if kind == "dim":
            return _export_dim(dxf, target, entity, dxfattribs, ledger)
        if kind == "insert":
            return target.add_blockref(
                str(entity.name), insert=_xyz(entity.position),
                dxfattribs={
                    **dxfattribs,
                    "rotation": float(entity.rotation),
                    "xscale": float(entity.scale[0]),
                    "yscale": float(entity.scale[1]),
                    "zscale": float(entity.scale[2]),
                })
        if kind == "viewport":
            return _export_viewport(target, entity, dxfattribs)
        # unknown future kind — never silent
        ledger.append(
            "export", str(kind).upper(),
            f"entity kind {kind!r} is not supported by the ezdxf writer; "
            "entity skipped",
        )
        return None
    except Exception as exc:  # invalid geometry etc. — ledger, don't crash
        ledger.append(
            "export", kind.upper(),
            f"ezdxf refused to create the {kind} "
            f"(handle {entity.handle}): {exc}; entity skipped",
        )
        return None


def _export_polyline(target, entity, dxfattribs):
    """LWPOLYLINE: format "xyseb" = (x, y, start_width, end_width, bulge)."""
    vertices = list(entity.vertices)
    bulges = list(entity.bulges) if entity.bulges else [0.0] * len(vertices)
    widths = ([list(pair) for pair in entity.widths]
              if entity.widths else [[0.0, 0.0]] * len(vertices))
    points = []
    for i, vertex in enumerate(vertices):
        points.append((float(vertex[0]), float(vertex[1]),
                       float(widths[i][0]), float(widths[i][1]),
                       float(bulges[i])))
    dxfattribs = dict(dxfattribs)
    if any(abs(v[2]) > 1e-12 for v in vertices):
        elevations = {round(v[2], 9) for v in vertices}
        if len(elevations) != 1:
            raise ValueError(
                "LWPOLYLINE stores one elevation for all vertices; "
                "non-uniform vertex z is not representable")
        dxfattribs["elevation"] = float(vertices[0][2])
    return target.add_lwpolyline(points, format="xyseb",
                                  close=bool(entity.closed),
                                  dxfattribs=dxfattribs)


def _export_text(target, entity, dxfattribs):
    text = target.add_text(
        str(entity.content),
        dxfattribs={**dxfattribs, "height": float(entity.height),
                    "rotation": float(entity.rotation),
                    "style": str(entity.style)})
    align = _JUSTIFICATION_TO_ALIGNMENT.get(
        str(entity.justification), "LEFT")
    text.set_placement(_xyz(entity.position),
                       align=getattr(TextEntityAlignment, align))
    return text


def _export_viewport(target, entity, dxfattribs):
    """VIEWPORT: paper rect corners -> center/size; model view +
    display-lock flag. Viewports only exist in paper-space layouts."""
    cx = (entity.p1[0] + entity.p2[0]) / 2.0
    cy = (entity.p1[1] + entity.p2[1]) / 2.0
    cz = (entity.p1[2] + entity.p2[2]) / 2.0
    width = abs(entity.p2[0] - entity.p1[0])
    height = abs(entity.p2[1] - entity.p1[1])
    viewport = target.add_viewport(
        center=(cx, cy, cz), size=(width, height),
        view_center_point=(entity.center[0], entity.center[1]),
        view_height=float(entity.view_height),
        dxfattribs=dxfattribs)
    if entity.locked:
        viewport.dxf.flags = int(viewport.dxf.flags) | VIEWPORT_LOCKED_FLAG
    return viewport


def _force_handle(db, ezdxf_entity, bcdoc_entity, ledger) -> int:
    """Force the bcdoc entity handle onto the ezdxf entity (group code 5).

    Returns the handle actually written. On a collision with an existing
    DXF object handle the ezdxf-assigned handle is kept and the deviation
    is recorded in the ledger. A bcdoc handle of 0 means "never assigned
    by a document" (block members created outside the store keep 0) — the
    ezdxf-assigned handle is kept without a ledger entry (no identity was
    lost; there was nothing to preserve)."""
    try:
        source_handle = int(bcdoc_entity.handle)
    except (AttributeError, TypeError, ValueError):
        source_handle = 0
    if source_handle < 1:
        return int(str(ezdxf_entity.dxf.handle), 16)
    target = "%X" % source_handle
    current = ezdxf_entity.dxf.handle
    # NB: the freshly created entity is already IN the db with its
    # generator-assigned handle — when ezdxf happens to issue exactly the
    # bcdoc handle (low imported handles do), that is NOT a collision.
    existing = db.get(target)
    if existing is not None and existing is not ezdxf_entity:
        ledger.append(
            "export", getattr(bcdoc_entity, "kind", "entity").upper()
            if hasattr(bcdoc_entity, "kind") else "BLOCK",
            f"document handle {source_handle} (0x{target}) collides "
            f"with an existing DXF object handle; exported with reallocated "
            f"handle 0x{current}",
        )
        return int(current, 16)
    if current is not None and current != target:
        del db[current]
        ezdxf_entity.dxf.handle = target
        db.add(ezdxf_entity)
    # keep the ezdxf handle generator above the forced handle — otherwise
    # ezdxf re-issues the just-claimed handle for the next entity (only
    # matters for LOW foreign handles that overlap the generator range)
    seed = int(str(db.handles), 16)
    if seed <= source_handle:
        db.handles.reset("%X" % (source_handle + 1))
    return source_handle


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def read_dxf(path, ledger: LossLedger = None) -> dict:
    """Read an ASCII DXF file through ezdxf into engine-neutral raw dicts
    (the shape consumed by ``bcio._import_raw``).

    Raises :class:`EzdxfReadError` when neither strict reading nor
    ``ezdxf.recover`` can process the file (caller falls back to the
    tolerant minimal reader)."""
    if ezdxf is None:
        raise EzdxfReadError("ezdxf is not installed")
    ledger = ledger if ledger is not None else LossLedger()

    dxf, recovered = _load(path, ledger)
    _audit(dxf, ledger)

    layers = _read_layers(dxf, ledger)
    text_styles, dim_styles = _read_styles(dxf, ledger)
    blocks = _read_blocks(dxf, ledger)
    layouts = _read_layouts(dxf)
    settings, insunits_hint = _read_header(dxf, layers, ledger)
    entities, spaces_seen = _read_entities(dxf, ledger)

    return {
        "acadver": getattr(dxf, "dxfversion", None),
        "recovered": recovered,
        "engine": ENGINE,
        "layers": layers,
        "linetypes": _read_linetypes(dxf, ledger),
        "text_styles": text_styles,
        "dim_styles": dim_styles,
        "blocks": blocks,
        "layouts": layouts,
        "settings": settings,
        "insunits_hint": insunits_hint,
        "entities": entities,
        "spaces_seen": spaces_seen,
    }


def _load(path, ledger):
    """strict readfile -> ezdxf.recover fallback (M1 behavior)."""
    recovered = False
    try:
        # NB: ezdxf.readfile raises OSError (not DXFError) for files that
        # are not DXF at all, so BOTH exception types route into the
        # recover fallback (and from there into the caller's minimal path).
        return ezdxf.readfile(str(path)), recovered
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
            return dxf, recovered
        except Exception as exc2:
            raise EzdxfReadError(
                f"ezdxf cannot read {path!r} (strict: {exc}; recover: {exc2})"
            ) from exc2


def _audit(dxf, ledger) -> None:
    """Conformance oracle (contract: "... and audit"): audit the loaded
    document and ledger every issue — importing is never allowed to hide
    file problems. A clean file contributes no entries."""
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


def _entity_handle(entity):
    try:
        return int(str(entity.dxf.handle), 16)
    except (ValueError, TypeError, AttributeError):
        return None


def _common_record(entity, dxftype: str) -> dict:
    """Engine-neutral common fields for one entity record."""
    handle = _entity_handle(entity)
    color = _aci_color(getattr(entity.dxf, "color", None))
    linetype = getattr(entity.dxf, "linetype", None)
    if linetype is not None and str(linetype).upper() in ("BYLAYER", ""):
        linetype = None
    return {
        "type": dxftype,
        "handle": handle,
        "layer": str(getattr(entity.dxf, "layer", "0") or "0"),
        "color": color,
        "linetype": str(linetype) if linetype else None,
        "lineweight": getattr(entity.dxf, "lineweight", None),
    }


def _true_color_ledger(entity, dxftype: str, ledger) -> None:
    """bcdoc is ACI-only — group 420/440 extras are ledgered, never hidden."""
    true_color = getattr(entity.dxf, "true_color", None)
    if true_color is not None:
        ledger.append(
            "import", dxftype,
            f"true color {true_color} (group code 420) is not "
            "representable in bcdoc (ACI only); reduced to ACI",
        )
    transparency = getattr(entity.dxf, "transparency", None)
    if transparency is not None:
        ledger.append(
            "import", dxftype,
            f"transparency {transparency} is not representable in bcdoc; "
            "dropped",
        )


def _read_layers(dxf, ledger) -> list:
    """Layer records with every prop bcdoc models; tolerant of missing
    fields (defaults per contract)."""
    records = []
    for layer in dxf.layers:
        color = int(getattr(layer.dxf, "color", 7) or 7)
        on = not layer.is_off()
        if color < 0:
            color = abs(color)
        if color == 256:  # ByLayer is meaningless for a layer record
            color = 7
        linetype = getattr(layer.dxf, "linetype", None) or "Continuous"
        if str(linetype).upper() in ("BYLAYER", "BYBLOCK"):
            linetype = "Continuous"
        records.append({
            "name": str(layer.dxf.name),
            "color": color,
            "linetype": str(linetype),
            "lineweight": _enum_to_lineweight(
                layer.dxf.lineweight if layer.dxf.hasattr("lineweight")
                else None, ledger, "layer"),
            "on": on,
            "frozen": bool(layer.is_frozen()),
            "locked": bool(layer.is_locked()),
            # NB: no ``x or 1`` fallback — plot=0 (do-not-plot) is a legal,
            # meaningful falsy value and must NOT be coerced to True
            # (probe m2-2d-fix: round-trips 0 -> 0 cleanly).
            "plot": (bool(int(layer.dxf.plot))
                     if layer.dxf.hasattr("plot") else True),
        })
    return records


def _read_linetypes(dxf, ledger) -> list:
    """LTYPE table: bcdoc stores linetype NAMES only — any real dash
    pattern is not representable (one honest note per file)."""
    patterned = []
    for linetype in dxf.linetypes:
        name = str(linetype.dxf.name)
        if name.upper() in ("BYLAYER", "BYBLOCK", "CONTINUOUS"):
            continue
        patterned.append(name)
    if patterned:
        ledger.append(
            "import", "LTYPE",
            f"{len(patterned)} named linetype definition(s) "
            f"({', '.join(patterned[:5])}…) carry dash-pattern data that "
            "bcdoc does not model; only the linetype names are preserved",
        )
    return patterned


def _read_styles(dxf, ledger):
    """STYLE / DIMSTYLE tables -> bcdoc text/dim style records."""
    text_styles = []
    for style in dxf.styles:
        font = str(getattr(style.dxf, "font", "") or "")
        if font and font not in ("txt", ""):
            ledger.append(
                "import", "STYLE",
                f"text style {style.dxf.name!r} font {font!r} is not "
                "representable in bcdoc (name/height/width only); dropped",
            )
        text_styles.append({
            "name": str(style.dxf.name),
            "height": float(getattr(style.dxf, "height", 0.0) or 0.0),
            "width_factor": float(getattr(style.dxf, "width", 1.0) or 1.0),
        })
    dim_styles = []
    for style in dxf.dimstyles:
        dim_styles.append({
            "name": str(style.dxf.name),
            "dimscale": float(getattr(style.dxf, "dimscale", 1.0) or 1.0),
            "dimtxt": float(getattr(style.dxf, "dimtxt", 2.5) or 2.5),
            "dimasz": float(getattr(style.dxf, "dimasz", 2.5) or 2.5),
            "dimexo": float(getattr(style.dxf, "dimexo", 0.625) or 0.625),
            "dimexe": float(getattr(style.dxf, "dimexe", 1.25) or 1.25),
        })
    return text_styles, dim_styles


def _read_blocks(dxf, ledger) -> list:
    """User block definitions.

    ``*Model_Space`` / ``*Paper_Space`` are the space CONTAINERS — their
    members are the model/paper-space entities already imported through
    the layout iteration, so "skipping" them as blocks loses nothing
    (structural, always present in every DXF file). Anonymous dimension-
    geometry blocks (``*D…``) and arrowhead blocks (``_ClosedFilled``
    style) are skipped with a ledger note — they are regenerated display
    cache, not user content. The BLOCK entity carries the case-preserved
    name (ezdxf's ``blocks`` name-keying lowercases its dict keys)."""
    skipped_display = 0
    blocks = []
    for key in dxf.blocks.block_names():
        if key.upper() in ("*MODEL_SPACE", "*PAPER_SPACE"):
            continue
        if key.startswith("*") or key.startswith("_"):
            skipped_display += 1
            continue
        block = dxf.blocks.get(key)
        record = {
            "name": str(block.block.dxf.name),
            "base_point": _xyz(block.block.dxf.base_point),
            "handle": _entity_handle(block.block),
            "entities": [],
        }
        for member in block:
            parsed = _parse_entity(member, ledger, space="MODEL")
            if parsed is not None:
                record["entities"].append(parsed)
        blocks.append(record)
    if skipped_display:
        ledger.append(
            "import", "BLOCK",
            f"{skipped_display} anonymous display block definition(s) "
            "(*D dimension geometry, _ClosedFilled-style arrowheads) are "
            "regenerated cache, not user blocks; skipped",
        )
    return blocks


def _read_layouts(dxf) -> list:
    """Paper-space layouts (the 'Model' entry is the model space itself)."""
    layouts = []
    for name in dxf.layouts.names():
        if str(name).upper() == "MODEL":
            continue
        layout = dxf.layouts.get(name)
        layouts.append({
            "name": str(name),
            "page_width": float(getattr(layout.dxf, "paper_width", 420.0) or 420.0),
            "page_height": float(getattr(layout.dxf, "paper_height", 297.0) or 297.0),
        })
    return layouts


def _read_header(dxf, layers, ledger) -> tuple:
    """The settings subset present in the header, + the $INSUNITS code.

    $CLAYER may hold a layer NAME or a layer HANDLE (both verified
    round-tripping) — both are resolved against the layer table."""
    settings = {}
    header = dxf.header

    def _resolve_clayer(value):
        if value is None:
            return None
        text = str(value)
        for layer in layers:
            if layer["name"] == text:
                return text
        for layer in dxf.layers:
            if str(layer.dxf.handle) == text:
                return str(layer.dxf.name)
        return None

    for name, variable in SETTINGS_TO_HEADER.items():
        if variable not in header:
            continue
        if name == "CLAYER":
            resolved = _resolve_clayer(header[variable])
            if resolved is not None:
                settings["CLAYER"] = resolved
            continue
        try:
            settings[name] = header[variable]
        except Exception:
            continue

    insunits = header.get("$INSUNITS", 0) if "$INSUNITS" in header else 0

    # non-decimal display formats: the CODE round-trips; the formatting
    # behavior is documented as decimal-only in bcdoc (settings §2.5)
    lunits = int(settings.get("LUNITS", 2) or 2)
    if lunits != 2:
        ledger.append(
            "import", "HEADER",
            f"$LUNITS={lunits} (non-decimal length format) is stored as-is; "
            "bcdoc formats lengths decimal (documented M2 limitation)",
        )
    aunits = int(settings.get("AUNITS", 0) or 0)
    if aunits != 0:
        ledger.append(
            "import", "HEADER",
            f"$AUNITS={aunits} (non-decimal angle format) is stored as-is; "
            "bcdoc formats angles decimal (documented M2 limitation)",
        )
    return settings, int(insunits or 0)


def _read_entities(dxf, ledger) -> tuple:
    """Model-space + every paper-space layout; each record carries its
    target ``space`` ("MODEL" or the layout name)."""
    entities = []
    spaces_seen = ["MODEL"]
    for entity in dxf.modelspace():
        parsed = _parse_entity(entity, ledger, space="MODEL")
        if parsed is not None:
            entities.append(parsed)
    for name in dxf.layouts.names():
        if str(name).upper() == "MODEL":
            continue
        spaces_seen.append(str(name))
        for entity in dxf.layouts.get(name):
            parsed = _parse_entity(entity, ledger, space=str(name))
            if parsed is not None:
                entities.append(parsed)
    return entities, spaces_seen


def _parse_entity(entity, ledger, space: str):
    """One ezdxf entity -> engine-neutral record (or None + ledger)."""
    dxftype = entity.dxftype()
    record = _common_record(entity, dxftype)
    record["space"] = space
    kind = DXFTYPE_TO_KIND.get(dxftype)
    if kind is None:
        ledger.append(
            "import", dxftype,
            "entity type is not supported by bcio at M2 "
            "(LINE/CIRCLE/ARC/POINT/LWPOLYLINE/ELLIPSE/XLINE/RAY/TEXT/"
            "MTEXT/DIMENSION/INSERT/VIEWPORT); entity not imported",
        )
        return None
    _true_color_ledger(entity, dxftype, ledger)
    try:
        record["lineweight"] = _enum_to_lineweight(
            record.pop("lineweight"), ledger, "entity")
        _GEOMETRY_READERS[kind](entity, record, ledger)
    except Exception as exc:  # malformed entity — ledger, don't crash
        ledger.append(
            "import", dxftype,
            f"malformed {dxftype} entity "
            f"(handle {entity.dxf.handle}): {exc}; entity not imported",
        )
        return None
    return record


def _read_line(entity, record, ledger):
    record["p1"] = _xyz(entity.dxf.start)
    record["p2"] = _xyz(entity.dxf.end)


def _read_circle(entity, record, ledger):
    record["center"] = _xyz(entity.dxf.center)
    record["radius"] = float(entity.dxf.radius)


def _read_arc(entity, record, ledger):
    record["center"] = _xyz(entity.dxf.center)
    record["radius"] = float(entity.dxf.radius)
    record["start_angle"] = float(entity.dxf.start_angle)
    record["end_angle"] = float(entity.dxf.end_angle)


def _read_point(entity, record, ledger):
    record["position"] = _xyz(entity.dxf.location)


def _read_polyline(entity, record, ledger):
    points = [(float(p[0]), float(p[1]))
              for p in entity.get_points("xyseb")]
    bulges = [float(p[4]) for p in entity.get_points("xyseb")]
    widths = [(float(p[2]), float(p[3])) for p in entity.get_points("xyseb")]
    record["points"] = points
    record["bulges"] = bulges
    record["widths"] = widths
    record["closed"] = bool(int(entity.dxf.flags) & 1)
    record["elevation"] = float(getattr(entity.dxf, "elevation", 0.0) or 0.0)


def _read_ellipse(entity, record, ledger):
    record["center"] = _xyz(entity.dxf.center)
    record["major_axis"] = _xyz(entity.dxf.major_axis)
    record["ratio"] = float(entity.dxf.ratio)
    record["start_angle"] = math.degrees(float(entity.dxf.start_param))
    record["end_angle"] = math.degrees(float(entity.dxf.end_param))


def _read_xline(entity, record, ledger):
    record["p1"] = _xyz(entity.dxf.start)
    record["dir"] = _xyz(entity.dxf.unit_vector)


def _read_text(entity, record, ledger):
    halign = int(getattr(entity.dxf, "halign", 0) or 0)
    valign = int(getattr(entity.dxf, "valign", 0) or 0)
    justification = _ALIGNMENT_TO_JUSTIFICATION.get(halign, "LEFT")
    if halign not in (0, 1, 2):
        ledger.append(
            "import", "TEXT",
            f"text justification halign={halign} (ALIGNED/FIT/MIDDLE) is "
            "outside the bcdoc set (LEFT/CENTER/RIGHT); reduced to the "
            "nearest horizontal justification",
        )
    if halign or valign:
        # alignment-relevant position lives in the align point (group 11)
        position = _xyz(entity.dxf.align_point)
        if valign:
            ledger.append(
                "import", "TEXT",
                f"vertical text alignment (valign {valign}) is not "
                "representable in bcdoc (baseline-only); dropped",
            )
    else:
        position = _xyz(entity.dxf.insert)
    record["position"] = position
    record["height"] = float(entity.dxf.height)
    record["rotation"] = float(getattr(entity.dxf, "rotation", 0.0) or 0.0)
    record["content"] = str(entity.dxf.text)
    record["style"] = str(getattr(entity.dxf, "style", "Standard") or "Standard")
    record["justification"] = justification


def _read_mtext(entity, record, ledger):
    raw = str(entity.text)
    # the paragraph break \P is the legitimate newline encoding; everything
    # else backslash-y is inline formatting bcdoc does not model
    if any(ch in raw.replace("\\P", "") for ch in _MTEXT_FORMATTING_CHARS):
        ledger.append(
            "import", "MTEXT",
            "MTEXT inline formatting codes (\\f, \\W, \\C, braces, …) are "
            "not representable in bcdoc (plain content + newlines only); "
            "stripped",
        )
    record["position"] = _xyz(entity.dxf.insert)
    record["width"] = float(getattr(entity.dxf, "width", 0.0) or 0.0)
    record["content"] = str(entity.plain_text())
    record["style"] = str(getattr(entity.dxf, "style", "Standard") or "Standard")
    char_height = float(getattr(entity.dxf, "char_height",
                                MTEXT_DEFAULT_CHAR_HEIGHT)
                        or MTEXT_DEFAULT_CHAR_HEIGHT)
    if abs(char_height - MTEXT_DEFAULT_CHAR_HEIGHT) > 1e-9:
        ledger.append(
            "import", "MTEXT",
            f"MTEXT character height {char_height} is not representable in "
            f"bcdoc (no mtext height field); lost (default "
            f"{MTEXT_DEFAULT_CHAR_HEIGHT} is re-exported)",
        )


def _read_dimension(entity, record, ledger):
    """DIMENSION -> bcdoc dim. Definition points + type come from the
    entity; the associativity (``measured_id``) is product-internal and
    CANNOT round-trip through a file — every imported dim is free."""
    raw_type = int(entity.dxf.dimtype)
    base_type = raw_type & 7
    if base_type not in (0, 1):
        raise ValueError(
            f"dimension type {base_type} (angular/radius/ordinate/…) is "
            "outside the M2 set (linear|aligned)")
    record["dim_type"] = "aligned" if base_type == 1 else "linear"
    record["p1"] = _xyz(entity.dxf.defpoint2)
    record["p2"] = _xyz(entity.dxf.defpoint3)
    record["offset_point"] = _xyz(entity.dxf.defpoint)
    record["angle"] = float(getattr(entity.dxf, "angle", 0.0) or 0.0)
    text = str(getattr(entity.dxf, "text", "") or "")
    record["text_override"] = "" if text in ("<>" , "") else text
    record["style"] = str(getattr(entity.dxf, "dimstyle", "Standard")
                          or "Standard")
    if raw_type & 0x80:  # bit 7 = user-positioned text
        record["text_position"] = _xyz(entity.dxf.text_midpoint)
    else:
        record["text_position"] = None
    try:
        measurement = float(entity.get_measurement())
    except Exception:
        measurement = 0.0
    record["measurement"] = measurement
    ledger.append(
        "import", "DIMENSION",
        "dimension associativity (measured_id) is product-internal and not "
        "a DXF concept; imported as a free dimension (measured_id=\"\")",
    )


def _read_insert(entity, record, ledger):
    record["name"] = str(entity.dxf.name)
    record["position"] = _xyz(entity.dxf.insert)
    # no ``or 1.0`` fallbacks: a 0 scale component is representable in bcdoc
    # (degenerate but honest) and must survive instead of snapping to 1.0
    record["scale"] = (
        float(getattr(entity.dxf, "xscale", 1.0)),
        float(getattr(entity.dxf, "yscale", 1.0)),
        float(getattr(entity.dxf, "zscale", 1.0)),
    )
    record["rotation"] = float(getattr(entity.dxf, "rotation", 0.0) or 0.0)


def _read_viewport(entity, record, ledger):
    center = _xyz(entity.dxf.center)
    # no ``or`` fallbacks on width/height/status: zero is a legal stored
    # value (degenerate viewport / status 0 = off) and must not be coerced
    width = float(getattr(entity.dxf, "width", 1.0))
    height = float(getattr(entity.dxf, "height", 1.0))
    record["center"] = (float(entity.dxf.view_center_point[0]),
                       float(entity.dxf.view_center_point[1]), 0.0)
    record["view_height"] = float(getattr(entity.dxf, "view_height", 1.0))
    record["p1"] = (center[0] - width / 2.0, center[1] - height / 2.0, center[2])
    record["p2"] = (center[0] + width / 2.0, center[1] + height / 2.0, center[2])
    record["locked"] = bool(int(getattr(entity.dxf, "flags", 0) or 0)
                            & VIEWPORT_LOCKED_FLAG)
    status = int(getattr(entity.dxf, "status", 2) or 0)
    render_mode = int(getattr(entity.dxf, "render_mode", 0) or 0)
    flags = int(getattr(entity.dxf, "flags", 0) or 0)
    if status != 2 or render_mode != 0 or flags & ~VIEWPORT_LOCKED_FLAG:
        ledger.append(
            "import", "VIEWPORT",
            "viewport presentation attributes (status/render mode/snap/"
            "UCS/perspective) are not representable in bcdoc; dropped",
        )


#: kind -> geometry reader (called by :func:`_parse_entity`).
_GEOMETRY_READERS = {
    "line": _read_line,
    "circle": _read_circle,
    "arc": _read_arc,
    "point": _read_point,
    "polyline": _read_polyline,
    "ellipse": _read_ellipse,
    "xline": _read_xline,
    "ray": _read_xline,
    "text": _read_text,
    "mtext": _read_mtext,
    "dim": _read_dimension,
    "insert": _read_insert,
    "viewport": _read_viewport,
}
