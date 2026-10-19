"""No-bpy guarantee for the bcdraw package (M1 contracts §2 testability
rule 1, kept at M2): bcdraw is pure Python — it may import bcdoc, bccmd
and bcdraft (declared dependencies, contracts §1 dependency direction),
never bpy.

Three independent checks: source scan + runtime sys.modules walk + a
clean-subprocess import with ONLY the four module dirs on PYTHONPATH.
"""

import importlib
import re
import subprocess
import sys
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "bcdraw"

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
    assert not offenders, "bcdraw must not import bpy:\n" + "\n".join(offenders)


def test_bpy_absent_from_sys_modules_after_import():
    import bcdraw  # noqa: F401  (the package under test)

    for value in list(vars(bcdraw).values()):
        if isinstance(value, types.ModuleType) and value.__name__.startswith("bcdraw."):
            importlib.import_module(value.__name__)
    loaded = [m for m in sys.modules if m == _BPY or m.startswith(_BPY + ".")]
    assert not loaded, f"bpy leaked into the process: {loaded}"


def test_import_in_clean_subprocess_without_blender():
    """Import bcdraw in a FRESH interpreter (no Blender, no repo conftest)
    — together with its declared dependencies bcdoc, bccmd and bcdraft —
    and verify bpy never enters sys.modules."""
    script = (
        "import importlib, sys, types\n"
        "import bcdraw\n"
        "for value in list(vars(bcdraw).values()):\n"
        "    if isinstance(value, types.ModuleType) and value.__name__.startswith('bcdraw.'):\n"
        "        importlib.import_module(value.__name__)\n"
        "leaked = [m for m in sys.modules if m == 'bpy' or m.startswith('bpy.')]\n"
        "assert not leaked, 'bpy leaked into the process: %r' % leaked\n"
        "print('bcdraw-imports-clean')\n"
    )
    modules_dir = PACKAGE_DIR.parent.parent  # modules/
    env = dict(_clean_env())
    env["PYTHONPATH"] = _pythonpath(modules_dir)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, (
        f"clean-process import failed:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "bcdraw-imports-clean" in proc.stdout


def _clean_env():
    import os

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _pythonpath(modules_dir):
    import os

    return os.pathsep.join(
        [str(modules_dir / "drawings"), str(modules_dir / "drafting"),
         str(modules_dir / "commands"), str(modules_dir / "document")]
    )
