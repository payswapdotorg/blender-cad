"""Pure-Python DXF **R12 ASCII** writer/reader for the v0 entity set.

In-product interchange path (contract: m1-module-contracts.md §7) — no
third-party dependency. The writer emits the minimal standard-compliant
R12 subset:

- HEADER section: ``$ACADVER`` = ``AC1009`` and ``$HANDLING`` = 1
  (handles ARE written). ``$INSUNITS`` does not exist in R12 (it was
  introduced with R2000) — that limitation is a recorded v0 loss note,
  not something this writer can fix;
- TABLES section: a ``CONTINUOUS`` LTYPE table and the LAYER table
  (name, color 62, linetype ``CONTINUOUS``); bcdoc v0 layers are
  names-only, so every layer is exported with color 7 / CONTINUOUS;
- ENTITIES section: LINE (8, 10/20/30, 11/21/31), CIRCLE (8, 10/20/30,
  40), ARC (8, 10/20/30, 40, 50, 51), each with group code 5 handle
  (hex, uppercase) and optional ACI color 62;
- terminated with EOF.

The reader parses the same subset from ANY R12-ish ASCII file, tolerant of
unknown group pairs (skipped), misaligned/garbage lines (skipped + ledgered;
the recognizable subset still imports) and unknown entity types (recorded in
the loss ledger instead of crashing). Strict-standard conformance of this
writer's output is verified in tests against ``ezdxf.recover.readfile`` +
``doc.audit()``. A path that does not exist raises ``FileNotFoundError``
(honest caller error); a file that exists but is not valid DXF imports the
recognizable subset with every deviation ledgered.
"""

from __future__ import annotations

from decimal import Decimal

from .loss_ledger import LossLedger

ENGINE = "r12-minimal"
#: AutoCAD DXF version string for Release 12.
ACADVER = "AC1009"
#: Newline used by classic DXF ASCII files (DOS style).
LINESEP = "\r\n"

_SUPPORTED_ENTITIES = ("LINE", "CIRCLE", "ARC")


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
    # LAYER table — bcdoc v0 layers are names-only, so color is always the
    # default 7 and linetype is always CONTINUOUS (recorded v0 loss).
    layer_names = list(doc.layers)
    w(0, "TABLE")
    w(2, "LAYER")
    w(70, str(len(layer_names)))
    for name in layer_names:
        clean, lossy = _ascii(str(name))
        if lossy:
            ledger.append(
                "export", "LAYER",
                f"layer name {name!r} is not representable in ASCII DXF; "
                "written with '?' replacement characters",
            )
        w(0, "LAYER")
        w(2, clean)
        w(70, "0")
        w(62, "7")
        w(6, "CONTINUOUS")
    w(0, "ENDTAB")
    w(0, "ENDSEC")

    # -- ENTITIES ---------------------------------------------------------------
    written = {"line": 0, "circle": 0, "arc": 0}
    skipped = 0
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
        if entity.kind == "line":
            w(0, "LINE")
            w(5, "%X" % int(entity.handle))
            w(8, layer)
            if entity.color is not None:
                w(62, str(int(entity.color)))
            w(10, _fmt_float(entity.p1[0]))
            w(20, _fmt_float(entity.p1[1]))
            w(30, _fmt_float(entity.p1[2]))
            w(11, _fmt_float(entity.p2[0]))
            w(21, _fmt_float(entity.p2[1]))
            w(31, _fmt_float(entity.p2[2]))
            written["line"] += 1
        elif entity.kind == "circle":
            w(0, "CIRCLE")
            w(5, "%X" % int(entity.handle))
            w(8, layer)
            if entity.color is not None:
                w(62, str(int(entity.color)))
            w(10, _fmt_float(entity.center[0]))
            w(20, _fmt_float(entity.center[1]))
            w(30, _fmt_float(entity.center[2]))
            w(40, _fmt_float(entity.radius))
            written["circle"] += 1
        elif entity.kind == "arc":
            w(0, "ARC")
            w(5, "%X" % int(entity.handle))
            w(8, layer)
            if entity.color is not None:
                w(62, str(int(entity.color)))
            w(10, _fmt_float(entity.center[0]))
            w(20, _fmt_float(entity.center[1]))
            w(30, _fmt_float(entity.center[2]))
            w(40, _fmt_float(entity.radius))
            w(50, _fmt_float(entity.start_angle))
            w(51, _fmt_float(entity.end_angle))
            written["arc"] += 1
        else:  # future kinds — never silent
            skipped += 1
            ledger.append(
                "export", str(entity.kind).upper(),
                f"entity kind {entity.kind!r} is not supported by the "
                "r12-minimal writer at v0; entity skipped",
            )
    w(0, "ENDSEC")
    w(0, "EOF")

    with open(path, "w", encoding="ascii", errors="replace", newline="") as handle:
        handle.write(LINESEP.join(lines) + LINESEP)

    return {
        "engine": ENGINE,
        "dxfversion": ACADVER,
        "path": str(path),
        "entities": {**written, "total": sum(written.values())},
        "layers": len(layer_names),
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
    (contract §7 tolerance: unknown content is recorded, never fatal)."""
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
    """Read the v0 subset from (any) ASCII DXF into engine-neutral raw dicts.

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

    def _flush_entity() -> None:
        nonlocal entity, entity_pts, entity_vals
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
        entities.append(entity)
        entity = None
        entity_pts = {}
        entity_vals = {}

    def _flush_layer() -> None:
        nonlocal layer_record
        if layer_record:
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
                        "entity type not supported by bcio v0 "
                        "(LINE/CIRCLE/ARC only); entity not imported",
                    )
                    entity = None
            elif section == "TABLES" and table_name == "LAYER" and upper == "LAYER":
                layer_record = {"name": None, "color": 7, "linetype": None}
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
                # 0 = ByBlock, 256 = ByLayer -> bcdoc None
                entity["color"] = None if aci in (None, 0, 256) else aci
            elif code in (10, 20, 30, 11, 21, 31):
                try:
                    entity_pts[code] = float(value)
                except ValueError:
                    ledger.append(
                        "import", entity["type"],
                        f"unparseable coordinate (group {code}) {value!r}; treated as 0.0",
                    )
            elif code in (40, 50, 51):
                try:
                    entity_vals[code] = float(value)
                except ValueError:
                    ledger.append(
                        "import", entity["type"],
                        f"unparseable value (group {code}) {value!r}; treated as 0.0",
                    )
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
            continue

        # everything else (HEADER vars, other tables, other sections):
        # skip silently — those are not part of the v0 subset.

    _flush_entity()
    _flush_layer()

    if block_count:
        ledger.append(
            "import", "BLOCK",
            f"{block_count} block definition(s) present; blocks are not "
            "imported at M1 (planned M2+, ORG area)",
        )

    return {
        "acadver": acadver,
        "layers": layers,
        "entities": entities,
        "engine": ENGINE,
    }
