"""No-bpy guarantee for the bcio package (M1 contracts §2, testability
rule 1): bcio is pure Python (it may import bcdoc — a declared
dependency — and optionally ezdxf, but never bpy).

Two independent checks: source scan + runtime sys.modules walk.
"""

import importlib
import re
import sys
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "bcio"

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
    assert not offenders, "bcio must not import bpy:\n" + "\n".join(offenders)


def test_bpy_absent_from_sys_modules_after_import():
    import bcio  # noqa: F401  (the package under test)

    for value in list(vars(bcio).values()):
        if isinstance(value, types.ModuleType) and value.__name__.startswith("bcio."):
            importlib.import_module(value.__name__)
    for name in ("bcio.loss_ledger", "bcio.dxf_minimal", "bcio.ezdxf_bridge"):
        importlib.import_module(name)
    # bcio legitimately imports bcdoc (declared dependency) and may load
    # ezdxf; neither of those may pull in bpy either.
    loaded = [m for m in sys.modules if m == _BPY or m.startswith(_BPY + ".")]
    assert not loaded, f"bpy leaked into the process: {loaded}"


def test_import_in_clean_subprocess_without_blender():
    """Import bcio in a FRESH interpreter (no Blender, no repo conftest) —
    together with its declared dependency bcdoc — and verify bpy never
    enters sys.modules (M1 contracts §2/§10 rule 1; the bcio->bcdoc edge
    is the only module dependency bcio has)."""
    import os
    import subprocess

    script = (
        "import importlib, sys, types\n"
        "import bcio\n"
        "for value in list(vars(bcio).values()):\n"
        "    if isinstance(value, types.ModuleType) and value.__name__.startswith('bcio.'):\n"
        "        importlib.import_module(value.__name__)\n"
        "for name in ('bcio.loss_ledger', 'bcio.dxf_minimal', 'bcio.ezdxf_bridge'):\n"
        "    importlib.import_module(name)\n"
        "leaked = [m for m in sys.modules if m == 'bpy' or m.startswith('bpy.')]\n"
        "assert not leaked, 'bpy leaked into the process: %r' % leaked\n"
        "print('bcio-imports-clean')\n"
    )
    modules_dir = PACKAGE_DIR.parent.parent  # modules/
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(modules_dir / "document"), str(modules_dir / "interchange")]
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0, (
        f"clean-process import failed:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "bcio-imports-clean" in proc.stdout
