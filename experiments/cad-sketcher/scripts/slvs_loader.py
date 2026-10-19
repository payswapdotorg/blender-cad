"""Resolve and import the pinned slvs solver binary for the M3-eval harness.

Isolation (binding): the wheel is NEVER committed; it is read from the pinned
upstream checkout (.upstream/CAD_Sketcher, materialized by fetch-upstream.sh)
and extracted to a scratch --target dir OUTSIDE the repo (default
/home/z/cad-sketcher-eval-scratch/pytarget, overridable via
CAD_SKETCHER_SLVS_TARGET or --slvs-path). The digest is verified against the pin
recorded in fetch-solver.sh, so every result envelope can state the exact binary.

The importing interpreter MUST be CPython 3.13 (the wheel is cp313) — in practice
Blender 5.2.2's bundled Python: /home/z/runtime/blender-5.2.2-linux-x64/5.2/python/bin/python3.13
"""

import hashlib
import os
import sys
import zipfile
from pathlib import Path

WHEEL_NAME = "slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
WHEEL_SHA256 = "9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80"
WHEEL_SIZE = 2861309
PIN_TAG = "v0.32.1"
PIN_COMMIT = "e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4"
LANE = Path(__file__).resolve().parent.parent
UPSTREAM_WHEEL = LANE / ".upstream" / "CAD_Sketcher" / "wheels" / WHEEL_NAME
DEFAULT_TARGET = Path("/home/z/cad-sketcher-eval-scratch/pytarget")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(slvs_path=None, target=None):
    """Import slvs from a verified scratch extraction; returns (module, provenance)."""
    target = Path(target or os.environ.get("CAD_SKETCHER_SLVS_TARGET") or DEFAULT_TARGET)
    if not UPSTREAM_WHEEL.is_file():
        raise SystemExit(
            f"pinned wheel missing at {UPSTREAM_WHEEL} — run "
            f"{LANE}/fetch-upstream.sh + fetch-solver.sh first")
    digest = _sha256(UPSTREAM_WHEEL)
    if digest != WHEEL_SHA256:
        raise SystemExit(f"wheel sha256 {digest} != pinned {WHEEL_SHA256}")

    marker = target / ".slvs-pin"
    if (target / "slvs" / "solvespace.so").is_file() and marker.is_file() \
            and marker.read_text().strip() == WHEEL_SHA256:
        pass  # already extracted from the verified wheel
    else:
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(UPSTREAM_WHEEL) as z:
            z.extractall(target)
        marker.write_text(WHEEL_SHA256 + "\n")

    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    import slvs  # noqa: E402
    provenance = {
        "wheel": WHEEL_NAME,
        "wheel_sha256": WHEEL_SHA256,
        "wheel_size": WHEEL_SIZE,
        "wheel_source": f"CAD_Sketcher {PIN_TAG} @ {PIN_COMMIT} in-repo wheels/ "
                        "(byte-identical to PyPI slvs 3.2)",
        "solvespace_source": "solvespace/solvespace @ 477d4c87ca51b9727fbc0765cbd94253c3968b8b",
        "extracted_to": str(target),
        "imported_by": sys.executable,
    }
    return slvs, provenance
