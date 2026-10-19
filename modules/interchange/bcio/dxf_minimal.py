"""Pure-Python DXF **R12 ASCII** writer/reader — the M2 fallback engine.

In-product interchange path (contract: m1-module-contracts.md §7 +
m2-module-contracts.md §6) — no third-party dependency. The writer emits
the minimal standard-compliant R12 subset:

- HEADER section: ``$ACADVER`` = ``AC1009`` and ``$HANDLING`` = 1
  (handles ARE written). ``$INSUNITS`` does not exist in R12 — that
  limitation is a recorded v0 loss note; M2 settings/sysvars are NOT
  written here either (one honest ledger note when non-default);
- TABLES section: a ``CONTINUOUS`` LTYPE table and the LAYER table with
  the R12-representable subset of the bcdoc record: name, ACI color 62
  (NEGATIVE = layer off, the R12 convention), linetype name 6 (stub —
  bcdoc has no pattern data), frozen flag (group 70 bit 1). Locked /
  plot / lineweight are NOT representable in R12 layer records —
  ledgered when non-default;
- ENTITIES section: LINE (8, 10/20/30, 11/21/31), CIRCLE (8, 10/20/30,
  40), ARC (8, 10/20/30, 40, 50, 51), TEXT (8, 10/20/30, 40 height, 1
  content, 50 rotation, 7 style) — each with group code 5 handle (hex,
  uppercase) and optional ACI color 62;
- terminated with EOF.

M2 additions beyond that set are NEVER silently dropped:

- TEXT with CENTER/RIGHT justification is written as LEFT (ledgered —
  the minimal engine writes the pinned simple-TEXT subset only);
- POLYLINE degrades to LINE segments when (and only when) every bulge is
  0.0 (straight segments): the closed flag becomes a closing segment,
  the per-vertex widths and the polyline IDENTITY (kind + handle) are
  lost — one explicit ledger note records that this degradation is NOT
  round-trip-safe BY DESIGN and the compare suite excludes it; a polyline
  with ANY arc segment (bulge != 0) is skipped + ledgered;
- POINT, ELLIPSE, XLINE, RAY, MTEXT, DIMENSION, INSERT, VIEWPORT,
  block definitions, layouts/paper-space routing and non-default
  settings are skipped with loss-ledger entries;
- entities living in a paper-space layout are skipped + ledgered twice:
  once individually by entity kind and once at the routing level with
  the ``PAPER_SPACE`` pseudo-type (the minimal engine writes model space
  only).

The reader parses the same subset from ANY R12-ish ASCII file, tolerant
of unknown group pairs (skipped), misaligned/garbage lines (skipped +
ledgered; the recognizable subset still imports), unknown entity types
(recorded in the loss ledger instead of crashing) and foreign TEXT
justification (72/11 groups are honored when present). Strict-standard
conformance of this writer's output is verified in tests against
``ezdxf.recover.readfile`` + ``doc.audit()``. A path that does not exist
raises ``FileNotFoundError`` (honest caller error); a file that exists
but is not valid DXF imports the recognizable subset with every
deviation ledgered.
"""

from __future__ import annotations

from decimal import Decimal

from .loss_ledger import LossLedger

ENGINE = "r12-minimal"
#: AutoCAD DXF version string for Release 12.
ACADVER = "AC1009"
#: Newline used by classic DXF ASCII files (DOS style).
LINESEP = "\r\n"

#: Entity kinds the minimal writer emits directly.
_SUPPORTED_ENTITIES = ("LINE", "CIRCLE", "ARC", "TEXT")

#: bcdoc kinds that degrade to LINE segments when all bulges are 0.
_DEGRADABLE_KINDS = ("polyline",)

#: M2 document content this engine cannot express (one ledger note each).
_UNSUPPORTED_CONTENT = (
    ("point", "POINT entities are not written by the r12-minimal engine"),
    ("ellipse", "ELLIPSE entities are not written by the r12-minimal engine"),
    ("xline", "XLINE entities are not written by the r12-minimal engine"),
    ("ray", "RAY entities are not written by the r12-minimal engine"),
    ("mtext", "MTEXT entities are not written by the r12-minimal engine"),
    ("dim", "DIMENSION entities are not written by the r12-minimal engine"),
    ("insert", "INSERT block references are not written by the r12-minimal "
               "engine (block definitions are not written either)"),
    ("viewport", "VIEWPORT entities are not written by the r12-minimal "
                 "engine (paper space is not written)"),
)


# ---------------------------------------------------------------------------
# number formatting
# ---------------------------------------------------------------------------

def _fmt_float(value) -> str:
    """Shortest round-trip decimal text for a float, without exponent
    notation (exactly recoverable via float(); exactness verified by the
    1e-9 round-trip tests)."""
    number = float(value)
    text = repr(number)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


def _ascii(text: str):
    """Coerce to ASCII; returns ``(clean, lossy)``."""
    try:
        text.encode("ascii")
        return text, False
    except UnicodeEncodeError:
        return text.encode("ascii", errors="replace").decode("ascii"), True


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------

def _layer_flags_70(record) -> str:
    """R12 LAYER flags (group 70): bit 1 = frozen (the only R12-representable
    state bit of the bcdoc record)."""
    return "1" if record.frozen else "0"


def write_dxf(path, doc, ledger: LossLedger = None) -> dict:
    """Write ``doc`` to ``path`` as minimal R12 ASCII. Returns stats."""
    ledger = ledger if ledger is not None else LossLedger()
    lines: list = []

    def w(code, value) -> None:
        lines.append(str(code))
        lines.append(str(value))

    # -- HEADER -------------------------------------------------------------
    w(0, "SECTION")
    w(2, "HEADER")
    w(9, "$ACADVER")
    w(1, ACADVER)
    w(9, "$HANDLING")  # R12: 1 = handles are present in the file
    w(70, "1")
    w(0, "ENDSEC")

    # -- TABLES ---------------------------------------------------------------
    w(0, "SECTION")
    w(2, "TABLES")
    # LTYPE table with CONTINUOUS (the only linetype v0 references).
    w(0, "TABLE")
    w(2, "LTYPE")
    w(70, "1")
    w(0, "LTYPE")
    w(2, "CONTINUOUS")
    w(70, "0")
    w(3, "Solid line")
    w(72, "65")
    w(73, "0")
    w(40, "0.0")
    w(0, "ENDTAB")
    # LAYER table — R12-representable props only (color sign = off, group
    # 70 bit 1 = frozen, group 6 = linetype name); the rest is ledgered.
    layer_records = []
    for name in doc.layers:
        record = doc.layers.get(name)
        layer_records.append(record)
        if record is None:  # pragma: no cover - table iteration yields names
            continue
        non_r12 = []
        if record.locked:
            non_r12.append("locked")
        if not record.plot:
            non_r12.append("plot")
        if record.lineweight is not None:
            non_r12.append(f"lineweight {record.lineweight}")
        if non_r12:
            ledger.append(
                "export", "LAYER",
                f"layer {name!r} properties ({', '.join(non_r12)}) are not "
                "representable in a DXF R12 LAYER record; lost in the "
                "r12-minimal output",
            )
    w(0, "TABLE")
    w(2, "LAYER")
    w(70, str(len(layer_records)))
    for record in layer_records:
        clean, lossy = _ascii(str(record.name))
        if lossy:
            ledger.append(
                "export", "LAYER",
                f"layer name {record.name!r} is not representable in ASCII "
                "DXF; written with '?' replacement characters",
            )
        w(0, "LAYER")
        w(2, clean)
        w(70, _layer_flags_70(record))
        # R12 convention: negative color = layer off
        color = int(record.color)
        w(62, str(-color if not record.on else color))
        lt_clean, _ = _ascii(str(record.linetype))
        w(6, lt_clean)
    w(0, "ENDTAB")
    w(0, "ENDSEC")

    # -- non-entity document content the minimal engine cannot express ---------
    for block_name in doc.block_names():
        ledger.append(
            "export", "BLOCK",
            f"block definition {block_name!r} is not written by the "
            "r12-minimal engine; definition + references lost in this output",
        )
    for layout_name in doc.layouts():
        ledger.append(
            "export", "LAYOUT",
            f"paper-space layout {layout_name!r} is not written by the "
            "r12-minimal engine; its entities are ledgered individually",
        )
    changed_settings = []
    for name in doc.settings.names():
        value = doc.settings.get(name)
        if value != doc.settings.definitions()[name]["default"]:
            changed_settings.append(name)
    if changed_settings:
        ledger.append(
            "export", "SETTINGS",
            f"{len(changed_settings)} non-default setting(s) "
            f"({', '.join(changed_settings[:6])}) are not written by the "
            "r12-minimal engine (R12 subset has no M2 sysvars); lost",
        )

    # -- ENTITIES ---------------------------------------------------------------
    written = {kind: 0 for kind in (
        "line", "circle", "arc", "point", "polyline", "ellipse", "xline",
        "ray", "text", "mtext", "dim", "insert", "viewport")}
    written["degraded_segments"] = 0  # polyline -> LINE degradations (extra key)
    skipped = 0
    paper_skipped = []    # entities dropped because they live in a layout
    w(0, "SECTION")
    w(2, "ENTITIES")
    for entity in doc.entities():
        layer, layer_lossy = _ascii(str(entity.layer))
        if layer_lossy:
            ledger.append(
                "export", entity.kind.upper(),
                f"entity layer name {entity.layer!r} is not representable "
                "in ASCII DXF; written with '?' replacement characters",
            )
        if entity.space != "MODEL":
            skipped += 1
            paper_skipped.append(entity)
            ledger.append(
                "export", entity.kind.upper(),
                f"entity lives in paper-space layout {entity.space!r}; the "
                "r12-minimal engine writes model space only; entity skipped",
            )
            continue
        if entity.kind in ("line", "circle", "arc"):
            w(0, entity.kind.upper())
            w(5, "%X" % int(entity.handle))
            w(8, layer)
            if entity.color is not None:
                w(62, str(int(entity.color)))
            if entity.kind == "line":
                w(10, _fmt_float(entity.p1[0]))
                w(20, _fmt_float(entity.p1[1]))
                w(30, _fmt_float(entity.p1[2]))
                w(11, _fmt_float(entity.p2[0]))
                w(21, _fmt_float(entity.p2[1]))
                w(31, _fmt_float(entity.p2[2]))
            elif entity.kind == "circle":
                w(10, _fmt_float(entity.center[0]))
                w(20, _fmt_float(entity.center[1]))
                w(30, _fmt_float(entity.center[2]))
                w(40, _fmt_float(entity.radius))
            else:
                w(10, _fmt_float(entity.center[0]))
                w(20, _fmt_float(entity.center[1]))
                w(30, _fmt_float(entity.center[2]))
                w(40, _fmt_float(entity.radius))
                w(50, _fmt_float(entity.start_angle))
                w(51, _fmt_float(entity.end_angle))
            written[entity.kind] += 1
        elif entity.kind == "text":
            content, content_lossy = _ascii(str(entity.content))
            if content_lossy:
                ledger.append(
                    "export", "TEXT",
                    f"text content {entity.content!r} is not representable "
                    "in ASCII DXF; written with '?' replacement characters",
                )
            if entity.justification != "LEFT":
                ledger.append(
                    "export", "TEXT",
                    f"TEXT justification {entity.justification!r} is reduced "
                    "to LEFT (the r12-minimal engine writes the pinned "
                    "simple-TEXT subset); alignment lost",
                )
            w(0, "TEXT")
            w(5, "%X" % int(entity.handle))
            w(8, layer)
            if entity.color is not None:
                w(62, str(int(entity.color)))
            w(10, _fmt_float(entity.position[0]))
            w(20, _fmt_float(entity.position[1]))
            w(30, _fmt_float(entity.position[2]))
            w(40, _fmt_float(entity.height))
            w(1, content)
            w(50, _fmt_float(entity.rotation))
            w(7, str(entity.style))
            written["text"] += 1
        elif entity.kind == "polyline":
            bulges = list(entity.bulges) if entity.bulges \
                else [0.0] * len(entity.vertices)
            if any(abs(b) > 1e-12 for b in bulges):
                skipped += 1
                ledger.append(
                    "export", "POLYLINE",
                    "polyline with arc segment(s) (bulge != 0) cannot be "
                    "represented as line segments; entity skipped",
                )
                continue
            # straight-segment degradation (NOT round-trip-safe by design):
            vertices = list(entity.vertices)
            segments = list(zip(vertices, vertices[1:]))
            if entity.closed and len(vertices) > 1:
                segments.append((vertices[-1], vertices[0]))
            widths_note = "per-vertex widths lost" if entity.widths else ""
            ledger.append(
                "export", "POLYLINE",
                f"polyline (handle {entity.handle}, {len(segments)} segment"
                f"{'s' if len(segments) != 1 else ''}) degraded to LINE "
                "segments in the r12-minimal engine; the polyline identity "
                f"(kind/handle/closed flag) is lost{'; ' + widths_note if widths_note else ''}"
                " — NOT round-trip-safe by design (the compare suite "
                "excludes this path)",
            )
            for start, end in segments:
                w(0, "LINE")
                # no group-5 handle: degraded segments have no source
                # identity; the importing reader assigns fresh handles
                w(8, layer)
                if entity.color is not None:
                    w(62, str(int(entity.color)))
                w(10, _fmt_float(start[0]))
                w(20, _fmt_float(start[1]))
                w(30, _fmt_float(start[2]))
                w(11, _fmt_float(end[0]))
                w(21, _fmt_float(end[1]))
                w(31, _fmt_float(end[2]))
                written["degraded_segments"] += 1
        else:
            reason = dict(_UNSUPPORTED_CONTENT).get(
                entity.kind,
                f"entity kind {entity.kind!r} is not supported by the "
                "r12-minimal writer; entity skipped")
            skipped += 1
            ledger.append("export", entity.kind.upper(), reason)
    w(0, "ENDSEC")
    w(0, "EOF")

    # routing-level note: paper-space routing as a whole is dropped (each
    # affected entity is ALSO ledgered individually by kind above)
    if paper_skipped:
        layouts_hit = sorted({str(e.space) for e in paper_skipped})
        ledger.append(
            "export", "PAPER_SPACE",
            f"{len(paper_skipped)} entity/entities routed to paper-space "
            f"layout(s) ({', '.join(layouts_hit)}) are not written — the "
            "r12-minimal engine has no paper-space concept (model space "
            "only)",
        )

    with open(path, "w", encoding="ascii", errors="replace", newline="") as handle:
        handle.write(LINESEP.join(lines) + LINESEP)

    total = sum(count for key, count in written.items()
                if key != "degraded_segments")
    return {
        "engine": ENGINE,
        "dxfversion": ACADVER,
        "path": str(path),
        "entities": {**written, "total": total},
        "layers": len(layer_records),
        "skipped": skipped,
        "losses": list(ledger.entries),
    }


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------

def _iter_pairs(text: str, ledger: LossLedger = None):
    """Yield (code:int, value:str) pairs from ASCII DXF text — tolerant scan.

    Classic ASCII DXF strictly alternates ``<group code>/<value>`` lines.
    When a code-position line is not an integer (stray text, truncated or
    hand-damaged file) the scanner skips ONE line (resync) and continues —
    a damaged file still imports whatever valid group pairs it contains.
    The number of skipped lines is returned via the ledger exactly once
    (contract tolerance: unknown content is recorded, never fatal)."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    lines = [ln for ln in lines if ln.strip() != ""]
    skipped = 0
    index = 0
    count = len(lines)
    while index + 1 < count:  # a truncated final group is tolerated
        code_text = lines[index].strip()
        try:
            code = int(code_text)
        except ValueError:
            skipped += 1
            index += 1
            continue
        yield code, lines[index + 1]
        index += 2
    if skipped and ledger is not None:
        ledger.append(
            "import", "FILE",
            f"{skipped} misaligned line(s) skipped while scanning the "
            "group-code stream; the file is not a well-formed DXF — only "
            "the recognizable subset (if any) was imported",
        )


def read_dxf(path, ledger: LossLedger = None) -> dict:
    """Read the M2 minimal subset from (any) ASCII DXF into engine-neutral
    raw dicts.

    Tolerant of unknown groups and sections; unknown entity types and
    block definitions are ledgered, never fatal."""
    ledger = ledger if ledger is not None else LossLedger()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()

    acadver = None
    layers: list = []
    entities: list = []
    block_count = 0

    section = None
    expect_section_name = False
    table_name = None
    expect_table_name = False
    header_var = None  # last $VAR seen in the HEADER section
    layer_record: dict = {}
    entity: dict = None
    entity_pts: dict = {}
    entity_vals: dict = {}
    entity_texts: dict = {}

    def _flush_entity() -> None:
        nonlocal entity, entity_pts, entity_vals, entity_texts
        if entity is None:
            return
        etype = entity["type"]
        p = entity_pts
        center = (p.get(10, 0.0), p.get(20, 0.0), p.get(30, 0.0))
        if etype == "LINE":
            entity["p1"] = (p.get(10, 0.0), p.get(20, 0.0), p.get(30, 0.0))
            entity["p2"] = (p.get(11, 0.0), p.get(21, 0.0), p.get(31, 0.0))
        elif etype == "CIRCLE":
            entity["center"] = center
            entity["radius"] = entity_vals.get(40, 0.0)
        elif etype == "ARC":
            entity["center"] = center
            entity["radius"] = entity_vals.get(40, 0.0)
            entity["start_angle"] = entity_vals.get(50, 0.0)
            entity["end_angle"] = entity_vals.get(51, 0.0)
        elif etype == "TEXT":
            halign = int(entity_vals.get(72, 0) or 0)
            if halign in (1, 2) and 11 in p:
                entity["position"] = (p.get(11, 0.0), p.get(21, 0.0),
                                      p.get(31, 0.0))
                entity["justification"] = "CENTER" if halign == 1 else "RIGHT"
            else:
                entity["position"] = center
                entity["justification"] = "LEFT"
            entity["height"] = entity_vals.get(40, 1.0)
            entity["rotation"] = entity_vals.get(50, 0.0)
            entity["content"] = entity_texts.get(1, "")
            entity["style"] = entity_texts.get(7, "Standard")
        entities.append(entity)
        entity = None
        entity_pts = {}
        entity_vals = {}
        entity_texts = {}

    def _flush_layer() -> None:
        nonlocal layer_record
        if layer_record:
            color = layer_record.get("color", 7)
            layer_record["on"] = color >= 0
            layer_record["color"] = abs(color)
            layer_record.setdefault("frozen", False)
            layers.append(layer_record)
            layer_record = {}

    for code, raw_value in _iter_pairs(text, ledger):
        value = raw_value.strip()

        if code == 0:
            _flush_entity()
            _flush_layer()
            upper = value.upper()
            if upper == "SECTION":
                expect_section_name = True
            elif upper == "ENDSEC":
                section = None
                table_name = None
            elif upper == "TABLE":
                expect_table_name = True
            elif upper == "ENDTAB":
                table_name = None
            elif upper == "BLOCK":
                block_count += 1
            elif section == "ENTITIES":
                if upper in _SUPPORTED_ENTITIES:
                    entity = {
                        "type": upper,
                        "handle": None,
                        "layer": "0",
                        "color": None,
                    }
                else:
                    ledger.append(
                        "import", upper or "?",
                        "entity type is not supported by the r12-minimal "
                        "reader (LINE/CIRCLE/ARC/TEXT only); entity not "
                        "imported",
                    )
                    entity = None
            elif section == "TABLES" and table_name == "LAYER" and upper == "LAYER":
                layer_record = {"name": None, "color": 7, "linetype": None,
                               "frozen": False}
            continue

        if expect_section_name and code == 2:
            section = value.upper()
            expect_section_name = False
            continue
        if expect_table_name and code == 2:
            table_name = value.upper()
            expect_table_name = False
            continue
        if section == "HEADER":
            if code == 9:
                header_var = value.upper()
                continue
            if code == 1 and header_var == "$ACADVER":
                acadver = value.upper()
            continue

        if entity is not None:
            if code == 5:
                try:
                    entity["handle"] = int(value, 16)
                except ValueError:
                    ledger.append(
                        "import", entity["type"],
                        f"unparseable handle {value!r}; entity gets a fresh "
                        "document handle on import",
                    )
                    entity["handle"] = None
            elif code == 8:
                entity["layer"] = value or "0"
            elif code == 62:
                try:
                    aci = int(value)
                except ValueError:
                    aci = None
                # 256 = ByLayer (and absent) -> bcdoc None; 0 = ByBlock IS
                # representable at M2 (bcdoc color 0) and passes through
                entity["color"] = None if aci in (None, 256) else aci
            elif code in (10, 20, 30, 11, 21, 31):
                try:
                    entity_pts[code] = float(value)
                except ValueError:
                    ledger.append(
                        "import", entity["type"],
                        f"unparseable coordinate (group {code}) {value!r}; treated as 0.0",
                    )
            elif code in (40, 50, 51, 72):
                try:
                    entity_vals[code] = float(value)
                except ValueError:
                    ledger.append(
                        "import", entity["type"],
                        f"unparseable value (group {code}) {value!r}; treated as 0.0",
                    )
            elif code in (1, 7):
                entity_texts[code] = value
            # unknown groups inside an entity are skipped (tolerant reader)
            continue

        if layer_record:
            if code == 2 and layer_record.get("name") is None:
                layer_record["name"] = value or "0"
            elif code == 62:
                try:
                    layer_record["color"] = int(value)
                except ValueError:
                    pass
            elif code == 6:
                layer_record["linetype"] = value
            elif code == 70:
                try:
                    layer_record["frozen"] = bool(int(value) & 1)
                except ValueError:
                    pass
            continue

        # everything else (HEADER vars, other tables, other sections):
        # skip silently — those are not part of the minimal subset.

    _flush_entity()
    _flush_layer()

    if block_count:
        ledger.append(
            "import", "BLOCK",
            f"{block_count} block definition(s) present; blocks are not "
            "imported by the r12-minimal reader (use the ezdxf engine for "
            "the full M2 set)",
        )

    return {
        "acadver": acadver,
        "layers": layers,
        "entities": entities,
        "engine": ENGINE,
    }
