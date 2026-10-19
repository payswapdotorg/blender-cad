#!/usr/bin/env python3
"""M0 repo-consistency suite — the acceptance evidence for milestone M0.

Glossary §11 (M0 exit): "docs merged, CI green on the repo-consistency suite".
These six tests ARE that suite. They assert structural consistency of the
repository only — at M0 no product feature code exists (glossary §1 honesty
rules). See docs/30-process/test-plan.md (TP-CAT-00).
"""

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
INVENTORY_DIR = REPO_ROOT / "data" / "inventory"

ID_RE = re.compile(r"^FP-[A-Z0-9]+-[0-9]{3}$")
# Doc scanner: any concrete FP id referenced in markdown must exist in the inventory.
ID_SCAN_RE = re.compile(r"FP-[A-Z0-9]+-[0-9]+")

# Secret patterns are assembled by concatenation so that THIS file never
# contains a literal pattern (test_no_secrets scans this file too).
SECRET_PATTERNS = [
    "napi" + "_",
    "sk-or-" + "v1-",
    "ghp" + "_",
    "vcp" + "_",
    "e2b" + "_",
    "apify_api" + "_",
    "cfat" + "_",
    "re" + "_" + "gRr",
    "AKI" + "A",
    "sk-ws-" + "H.",
]

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
MAX_SCAN_BYTES = 2 * 1024 * 1024


def _run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *args],
        capture_output=True,
        text=True,
    )


def _inventory_files():
    return sorted(INVENTORY_DIR.glob("*.yaml"))


def _collect_inventory_ids():
    ids = set()
    for path in _inventory_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            for entry in doc.get("entries", []) or []:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    ids.add(entry["id"])
    return ids


def test_render_check():
    """docs/10-product/inventory-tables.md must match a fresh render (TP-CAT-00)."""
    result = _run_script("render_inventory.py", "--check")
    assert result.returncode == 0, (
        "render_inventory.py --check failed (generated tables are stale or "
        "inventory YAML is invalid):\n" + result.stdout + result.stderr
    )


def test_manifest_valid():
    """Every release manifest must pass the glossary §8 validator (TP-CAT-00)."""
    result = _run_script("validate_manifest.py")
    assert result.returncode == 0, (
        "validate_manifest.py failed:\n" + result.stdout + result.stderr
    )


def test_module_boundaries():
    """modules/modules.json + module dirs must satisfy glossary §4 rules (TP-CAT-00)."""
    result = _run_script("check_module_boundaries.py")
    assert result.returncode == 0, (
        "check_module_boundaries.py failed:\n" + result.stdout + result.stderr
    )


def test_inventory_yaml_basics():
    """Every data/inventory/*.yaml must be schema-shaped with globally unique ids."""
    files = _inventory_files()
    assert files, f"no inventory files found under {INVENTORY_DIR}"
    seen = set()
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), f"{path.name}: top level must be a mapping"
        for key in ("area", "title", "module", "entries"):
            assert key in doc, f"{path.name}: missing top-level key '{key}'"
        entries = doc["entries"]
        assert isinstance(entries, list) and entries, (
            f"{path.name}: 'entries' must be a non-empty list"
        )
        for entry in entries:
            entry_id = entry["id"]
            assert ID_RE.match(entry_id), f"{path.name}: invalid id {entry_id!r}"
            assert entry_id not in seen, f"{path.name}: duplicate id {entry_id!r}"
            seen.add(entry_id)


def test_feature_ids_in_docs_are_real():
    """Every concrete FP id cited under docs/ and modules/ must exist in the inventory.

    M0 authors cite features by name + area, never by concrete id, so any id
    that appears in a markdown file must trace to a real inventory entry.
    """
    inventory_ids = _collect_inventory_ids()
    assert inventory_ids, "inventory id set is empty — cannot verify doc references"
    scanned = 0
    for directory in ("docs", "modules"):
        for path in sorted((REPO_ROOT / directory).rglob("*.md")):
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for match in ID_SCAN_RE.findall(text):
                assert match in inventory_ids, (
                    f"{path.relative_to(REPO_ROOT)} references {match}, "
                    "which does not exist in data/inventory/"
                )
    assert scanned >= 20, (
        f"expected to scan the markdown under docs/ and modules/, found only {scanned} files"
    )


def test_no_secrets():
    """No secret-like strings anywhere in the repo (docs, code, data, workflows)."""
    offenders = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if relative.parts[0] in SKIP_DIRS:
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue  # binary file
        text = data.decode("utf-8", errors="replace")
        for secret in SECRET_PATTERNS:
            if secret in text:
                offenders.append(f"{relative}: contains secret pattern {secret!r}")
    assert not offenders, "secret-like strings found:\n" + "\n".join(offenders)
