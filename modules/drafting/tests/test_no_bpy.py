"""No-bpy guarantee for the bcdraft package (M1 contracts §2, testability
rule 1): bcdraft is pure Python — it may import bcdoc and bccmd (declared
dependencies per the M1 contract §5 command-spec inversion, recorded in the
package docstring), never bpy.

Two independent checks: source scan + runtime sys.modules walk.
"""

import importlib
import re
import sys
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "bcdraft"

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
    assert not offenders, "bcdraft must not import bpy:\n" + "\n".join(offenders)


def test_bpy_absent_from_sys_modules_after_import():
    import bcdraft  # noqa: F401  (the package under test)

    for value in list(vars(bcdraft).values()):
        if isinstance(value, types.ModuleType) and value.__name__.startswith("bcdraft."):
            importlib.import_module(value.__name__)
    loaded = [m for m in sys.modules if m == _BPY or m.startswith(_BPY + ".")]
    assert not loaded, f"bpy leaked into the process: {loaded}"


def test_import_in_clean_subprocess_without_blender():
    """Import bcdraft in a FRESH interpreter (no Blender, no repo conftest)
    — together with its declared dependencies bcdoc and bccmd — and verify
    bpy never enters sys.modules (M1 contracts §2/§10 rule 1)."""
    import os
    import subprocess

    script = (
        "import importlib, sys, types\n"
        "import bcdraft\n"
        "for value in list(vars(bcdraft).values()):\n"
        "    if isinstance(value, types.ModuleType) and value.__name__.startswith('bcdraft.'):\n"
        "        importlib.import_module(value.__name__)\n"
        "leaked = [m for m in sys.modules if m == 'bpy' or m.startswith('bpy.')]\n"
        "assert not leaked, 'bpy leaked into the process: %r' % leaked\n"
        "print('bcdraft-imports-clean')\n"
    )
    modules_dir = PACKAGE_DIR.parent.parent  # modules/
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(modules_dir / "drafting"), str(modules_dir / "commands"),
         str(modules_dir / "document")]
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, (
        f"clean-process import failed:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "bcdraft-imports-clean" in proc.stdout
