"""No-bpy guarantee for the bcdoc package (M1 contracts §2, testability
rule 1): bcdoc is pure Python and must import identically under pytest,
inside the Blender extension host, and in the agent sidecar.

Two independent checks (both CI-stable):

1. SOURCE SCAN — no module file may contain an import statement for bpy;
2. RUNTIME WALK — after importing bcdoc (and every submodule), ``bpy``
   must not appear in ``sys.modules``.
"""

import importlib
import re
import sys
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "bcdoc"

# Assembled by concatenation so this file cannot trip a literal scan.
_BPY = "b" + "py"
_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+" + re.escape(_BPY) + r"(?=[\s.,:)]|$)",
    re.MULTILINE,
)


def test_no_bpy_import_statements_in_source():
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files, f"no sources found under {PACKAGE_DIR}"
    offenders = []
    for path in files:
        matches = _IMPORT_RE.findall(path.read_text(encoding="utf-8"))
        if matches:
            offenders.append(f"{path.name}: {len(matches)} bpy import statement(s)")
    assert not offenders, "bcdoc must not import bpy:\n" + "\n".join(offenders)


def test_bpy_absent_from_sys_modules_after_import():
    import bcdoc  # noqa: F401  (the package under test)

    # Import every bcdoc submodule explicitly.
    for value in list(vars(bcdoc).values()):
        if isinstance(value, types.ModuleType) and value.__name__.startswith("bcdoc."):
            importlib.import_module(value.__name__)
    for name in (
        "bcdoc.errors", "bcdoc.entities", "bcdoc.document", "bcdoc.transaction",
        "bcdoc.undo", "bcdoc.selection", "bcdoc.serialize", "bcdoc.units",
    ):
        importlib.import_module(name)

    loaded = [m for m in sys.modules if m == _BPY or m.startswith(_BPY + ".")]
    assert not loaded, f"bpy leaked into the process: {loaded}"


def test_import_in_clean_subprocess_without_blender():
    """Import bcdoc in a FRESH interpreter (no Blender, no repo conftest) and
    walk every submodule: the package must load standalone — the way the
    agent sidecar and plain test hosts load it — without bpy ever entering
    sys.modules (M1 contracts §2/§10 rule 1)."""
    import os
    import subprocess

    script = (
        "import importlib, sys, types\n"
        "import bcdoc\n"
        "for value in list(vars(bcdoc).values()):\n"
        "    if isinstance(value, types.ModuleType) and value.__name__.startswith('bcdoc.'):\n"
        "        importlib.import_module(value.__name__)\n"
        "for name in ('bcdoc.errors', 'bcdoc.entities', 'bcdoc.document',\n"
        "             'bcdoc.transaction', 'bcdoc.undo', 'bcdoc.selection',\n"
        "             'bcdoc.serialize', 'bcdoc.units'):\n"
        "    importlib.import_module(name)\n"
        "leaked = [m for m in sys.modules if m == 'bpy' or m.startswith('bpy.')]\n"
        "assert not leaked, 'bpy leaked into the process: %r' % leaked\n"
        "print('bcdoc-imports-clean')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PACKAGE_DIR.parent)  # modules/document -> bcdoc
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, (
        f"clean-process import failed:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "bcdoc-imports-clean" in proc.stdout
