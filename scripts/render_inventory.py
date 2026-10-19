#!/usr/bin/env python3
"""Render docs/10-product/inventory-tables.md from data/inventory/*.yaml.

Reads every ``data/inventory/*.yaml`` file (one file per inventory area,
glossary §5), validates it against the binding schema, and renders the
generated tables file. CI drift-checks the committed file against a fresh
render (``--check``).

Usage:
    python3 scripts/render_inventory.py          # validate + write the file
    python3 scripts/render_inventory.py --check  # validate + compare, no write

Exit codes:
    0  success (file written, or committed file is in sync)
    1  validation error, or (--check) committed output is stale/missing

The single ``Generated (UTC):`` timestamp line is excluded from the
``--check`` byte comparison (so CI stays deterministic across days); every
other byte must match exactly.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY_DIR = REPO_ROOT / "data" / "inventory"
OUTPUT_FILE = REPO_ROOT / "docs" / "10-product" / "inventory-tables.md"

# glossary §5 area order (validation + render order)
AREA_ORDER = [
    "CMD", "DRAW", "MOD", "PREC", "ORG", "ANN", "LAY", "P3D", "PAR",
    "IO", "TS", "UX", "AGT", "SKL",
]

# glossary §5 file column — on-disk name of each area's YAML file
AREA_FILES = {
    "CMD": "cmd.yaml",
    "DRAW": "draw.yaml",
    "MOD": "mod.yaml",
    "PREC": "prec.yaml",
    "ORG": "org.yaml",
    "ANN": "ann.yaml",
    "LAY": "lay.yaml",
    "P3D": "p3d.yaml",
    "PAR": "par.yaml",
    "IO": "io.yaml",
    "TS": "toolsets.yaml",
    "UX": "ux.yaml",
    "AGT": "agent.yaml",
    "SKL": "skills.yaml",
}

# glossary §5 owning-module map (area -> module that must own the YAML file)
AREA_MODULE = {
    "CMD": "commands",
    "DRAW": "drafting",
    "MOD": "drafting",
    "PREC": "drafting",
    "ORG": "drafting",
    "ANN": "drawings",
    "LAY": "drawings",
    "P3D": "kernel",
    "PAR": "parametric",
    "IO": "interchange",
    "TS": "toolsets",
    "UX": "shell",
    "AGT": "agent",
    "SKL": "skills",
}

ALLOWED_DEPS = [
    "occt", "ocp", "freecad", "planegcs", "build123d", "cadquery",
    "ezdxf", "libredwg", "ifcopenshell", "bonsai", "gdal", "pdal",
    "shapely", "blender-native", "zcode-runtime",
]
ALLOWED_STATUS = ["planned", "in-progress", "partial", "blocked", "verified"]
ALLOWED_PRIORITY = ["P0", "P1", "P2"]
ALLOWED_TOOLSETS = ["mechanical", "electrical", "mep", "plant", "civil", "gis", "raster"]

# the 13 modules (glossary §4)
MODULES = [
    "document", "kernel", "drafting", "parametric", "drawings", "interchange",
    "bim", "toolsets", "commands", "agent", "skills", "shell", "testing",
]

ID_RE = re.compile(r"^FP-[A-Z0-9]+-[0-9]{3}$")
REQUIRED_TOP_KEYS = ("area", "title", "module", "entries")
REQUIRED_ENTRY_KEYS = ("id", "name", "desc", "p", "status")
OPTIONAL_ENTRY_KEYS = ("dep", "test", "note")
TIMESTAMP_PREFIX = "Generated (UTC): "


def validate_area(area, doc, errors, seen_ids):
    """Validate one area document; return normalized entries or None."""
    fname = AREA_FILES[area]
    if not isinstance(doc, dict):
        errors.append(f"{fname}: top-level YAML must be a mapping, got {type(doc).__name__}")
        return None

    for key in REQUIRED_TOP_KEYS:
        if key not in doc:
            errors.append(f"{fname}: missing required top-level key '{key}'")
    unknown_top = [key for key in doc if key not in REQUIRED_TOP_KEYS]
    if unknown_top:
        errors.append(f"{fname}: unknown top-level keys {sorted(unknown_top)} (allowed: {list(REQUIRED_TOP_KEYS)})")

    if "area" in doc and doc["area"] != area:
        errors.append(f"{fname}: 'area' is {doc['area']!r}, expected {area!r} (must match the file)")

    if "module" in doc:
        module = doc["module"]
        if module not in MODULES:
            errors.append(f"{fname}: module {module!r} is not one of the 13 modules")
        if module != AREA_MODULE[area]:
            errors.append(
                f"{fname}: module {module!r} does not match the glossary §5 map "
                f"for area {area} (expected {AREA_MODULE[area]!r})"
            )

    title = doc.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{fname}: 'title' must be a non-empty string")

    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        errors.append(f"{fname}: 'entries' must be a non-empty list")
        return None

    allowed_entry_keys = set(REQUIRED_ENTRY_KEYS) | set(OPTIONAL_ENTRY_KEYS)
    if area == "TS":
        allowed_entry_keys.add("toolset")

    entries = []
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"{fname}: entry #{index} must be a mapping")
            continue
        missing = [key for key in REQUIRED_ENTRY_KEYS if key not in entry]
        if missing:
            errors.append(f"{fname}: entry #{index} missing required keys {missing}")
            continue
        entry_id = entry["id"]
        if not isinstance(entry_id, str) or not ID_RE.match(entry_id):
            errors.append(
                f"{fname}: entry #{index}: id {entry_id!r} does not match "
                "the FP-<AREA>-NNN pattern ^FP-[A-Z0-9]+-[0-9]{3}$"
            )
        else:
            if not entry_id.startswith(f"FP-{area}-"):
                errors.append(f"{fname}: id {entry_id!r} prefix does not match file area {area}")
            if entry_id in seen_ids:
                errors.append(f"{fname}: duplicate id {entry_id!r} (first seen in {seen_ids[entry_id]})")
            else:
                seen_ids[entry_id] = fname
        unknown = [key for key in entry if key not in allowed_entry_keys]
        if unknown:
            errors.append(f"{fname}: entry {entry_id!r}: unknown keys {sorted(unknown)}")
        if entry["p"] not in ALLOWED_PRIORITY:
            errors.append(f"{fname}: entry {entry_id!r}: priority {entry['p']!r} not in {ALLOWED_PRIORITY}")
        if entry["status"] not in ALLOWED_STATUS:
            errors.append(f"{fname}: entry {entry_id!r}: status {entry['status']!r} not in {ALLOWED_STATUS}")
        if not isinstance(entry["name"], str) or not entry["name"].strip():
            errors.append(f"{fname}: entry {entry_id!r}: 'name' must be a non-empty string")
        if not isinstance(entry["desc"], str):
            errors.append(f"{fname}: entry {entry_id!r}: 'desc' must be a string")
        dep = entry.get("dep", [])
        if not isinstance(dep, list) or any(item not in ALLOWED_DEPS for item in dep):
            errors.append(f"{fname}: entry {entry_id!r}: 'dep' {dep!r} must be a list drawn from {ALLOWED_DEPS}")
        for key in ("test", "note"):
            if key in entry and not isinstance(entry[key], str):
                errors.append(f"{fname}: entry {entry_id!r}: '{key}' must be a string")
        if area == "TS":
            toolset = entry.get("toolset")
            if toolset not in ALLOWED_TOOLSETS:
                errors.append(
                    f"{fname}: entry {entry_id!r}: TS entries require "
                    f"'toolset' in {ALLOWED_TOOLSETS}, got {toolset!r}"
                )
        elif "toolset" in entry:
            errors.append(f"{fname}: entry {entry_id!r}: 'toolset' is only allowed in TS entries")

        entries.append({
            "id": entry_id,
            "name": entry["name"],
            "p": entry["p"],
            "dep": dep if isinstance(dep, list) else [],
            "status": entry["status"],
            "test": entry.get("test", ""),
            "note": entry.get("note", ""),
            **({"toolset": entry["toolset"]} if area == "TS" and isinstance(entry.get("toolset"), str) else {}),
        })
    return entries


def cell(text):
    """Make a value safe for a markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def strip_timestamp(text):
    """Drop the generation-timestamp line so --check is deterministic."""
    return "\n".join(line for line in text.splitlines() if not line.startswith(TIMESTAMP_PREFIX))


def render(docs_by_area, entries_by_area, timestamp):
    total = sum(len(entries) for entries in entries_by_area.values())
    by_status = {status: 0 for status in ALLOWED_STATUS}
    by_priority = {priority: 0 for priority in ALLOWED_PRIORITY}
    for entries in entries_by_area.values():
        for entry in entries:
            by_status[entry["status"]] += 1
            by_priority[entry["p"]] += 1

    lines = [
        "# AutoCAD Feature-Parity Inventory — Generated Tables",
        "",
        "GENERATED by scripts/render_inventory.py — DO NOT EDIT BY HAND. "
        "Edit data/inventory/*.yaml and re-run (CI drift-checks this file).",
        "",
        TIMESTAMP_PREFIX + timestamp,
        "",
        "## Totals",
        "",
        f"- Total feature entries: {total}",
        "- By status: " + " | ".join(f"{status}: {by_status[status]}" for status in ALLOWED_STATUS),
        "- By priority: " + " | ".join(f"{priority}: {by_priority[priority]}" for priority in ALLOWED_PRIORITY),
        "",
        "## Areas",
        "",
    ]
    for area in AREA_ORDER:
        doc = docs_by_area[area]
        entries = entries_by_area[area]
        p0_count = sum(1 for entry in entries if entry["p"] == "P0")
        lines.append(f"### {area} — {doc['title']}")
        lines.append("")
        lines.append(f"Owned by module: {doc['module']} — {len(entries)} entries (P0: {p0_count})")
        lines.append("")
        lines.append("| ID | Feature | Priority | Deps | Status | Test | Note |")
        lines.append("|---|---|---|---|---|---|---|")
        for entry in entries:
            feature = entry["name"]
            if area == "TS":
                feature = f"{entry['name']} [{entry.get('toolset', '')}]"
            deps = ", ".join(entry["dep"]) if entry["dep"] else "—"
            test = entry["test"] if entry["test"] else "—"
            note = entry["note"] if entry["note"] else "—"
            lines.append(
                f"| {cell(entry['id'])} | {cell(feature)} | {cell(entry['p'])} | {cell(deps)} "
                f"| {cell(entry['status'])} | {cell(test)} | {cell(note)} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate data/inventory/*.yaml (glossary §5) and render "
                    "docs/10-product/inventory-tables.md; --check verifies the "
                    "committed file is in sync instead of writing."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; compare the rendered content with the committed file "
             "(byte-for-byte, excluding the Generated (UTC) timestamp line) and "
             "exit 1 with a stale message on mismatch"
    )
    args = parser.parse_args(argv)

    errors = []
    if not INVENTORY_DIR.is_dir():
        print(f"ERROR: inventory directory not found: {INVENTORY_DIR}", file=sys.stderr)
        return 1

    present = sorted(path.name for path in INVENTORY_DIR.glob("*.yaml"))
    expected_files = set(AREA_FILES.values())
    for name in present:
        if name not in expected_files:
            errors.append(f"data/inventory/{name}: unexpected file — no such area in AREA_ORDER")
    for area in AREA_ORDER:
        if AREA_FILES[area] not in present:
            errors.append(f"data/inventory/{AREA_FILES[area]}: missing file for area {area}")

    docs_by_area = {}
    entries_by_area = {}
    seen_ids = {}
    for area in AREA_ORDER:
        path = INVENTORY_DIR / AREA_FILES[area]
        if not path.is_file():
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{AREA_FILES[area]}: YAML parse error: {exc}")
            continue
        entries = validate_area(area, doc, errors, seen_ids)
        if entries is not None:
            docs_by_area[area] = doc
            entries_by_area[area] = entries

    if errors:
        print("render_inventory: validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = render(docs_by_area, entries_by_area, timestamp)

    if args.check:
        if not OUTPUT_FILE.is_file():
            print(
                f"STALE: {OUTPUT_FILE} does not exist — run "
                "'python3 scripts/render_inventory.py' (without --check) to generate it",
                file=sys.stderr,
            )
            return 1
        existing = OUTPUT_FILE.read_text(encoding="utf-8")
        if strip_timestamp(existing) == strip_timestamp(content):
            print("in sync")
            return 0
        print(
            f"STALE: {OUTPUT_FILE} does not match data/inventory/*.yaml — re-run "
            "'python3 scripts/render_inventory.py' and commit the result",
            file=sys.stderr,
        )
        return 1

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    total = sum(len(entries) for entries in entries_by_area.values())
    print(f"wrote {OUTPUT_FILE.relative_to(REPO_ROOT)} — {total} entries across {len(AREA_ORDER)} areas:")
    for area in AREA_ORDER:
        entries = entries_by_area[area]
        p0_count = sum(1 for entry in entries if entry["p"] == "P0")
        print(f"  {area}: {len(entries)} entries (P0: {p0_count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
