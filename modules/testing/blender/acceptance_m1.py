#!/usr/bin/env python3
"""M1 acceptance battery (TL-owned) — the operator-directive gate.

Proves, against the SELECTED Blender build (recorded in release-manifests/manifest-0.2.0-m1.json),
through Blender's ACTUAL extension system (no sys.path bootstrap of repo sources):

  1. the built extension (dist/blender_cad-<version>.zip) installs via
     `blender --command extension install-file` and is enabled at startup;
  2. the CAD workspace opens;
  3. LINE, CIRCLE and ARC work through the command interface (the same registry
     + prompt state machine the modal UI uses);
  4. basic modifications work (MOVE, COPY, ROTATE, SCALE, ERASE) through the same interface;
  5. documents survive save/reopen across Blender processes;
  6. a real DXF round-trip passes inside Blender (export -> wipe -> re-import -> compare);
  7. native Blender functions remain usable (primitive add, scene ops, save);
  8. the extension unregisters cleanly (TP-CAT-06 clean-unload precondition).

Orchestrator (this file, plain Python) drives three Blender subprocesses:
  A. install  : blender --command extension install-file   (isolated BLENDER_USER_RESOURCES)
  B. verify   : blender --background --python acceptance_verify_phase.py
  C. reopen   : blender --background --python acceptance_reopen_phase.py  (fresh process,
                reopens the .blend saved in B)

Result artifact: modules/testing/blender/acceptance_m1_result.json (commit-worthy evidence).
Exit code 0 only if every check passes.

Run from the repo root:
  python3 modules/testing/blender/acceptance_m1.py [--blender PATH] [--keep-userdir]
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DIST = REPO / "dist"
RESULT = HERE / "acceptance_m1_result.json"

DEFAULT_BLENDER = "/home/z/runtime/blender-5.2.2-linux-x64/blender"


def find_zip() -> Path:
    zips = sorted(DIST.glob("blender_cad-*.zip"))
    if not zips:
        raise SystemExit("no dist/blender_cad-*.zip — run scripts/build_extension.py first")
    return zips[-1]


def run(cmd, env, timeout=300):
    t0 = time.time()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    return p, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=DEFAULT_BLENDER)
    ap.add_argument("--keep-userdir", action="store_true")
    args = ap.parse_args()

    blender = Path(args.blender)
    if not blender.is_file():
        raise SystemExit(f"blender binary not found: {blender}")

    zip_path = find_zip()
    userdir = Path(tempfile.mkdtemp(prefix="bcad-accept-"))
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = str(userdir)
    env.pop("BLENDER_USER_EXTENSIONS", None)

    checks = []
    result = {
        "battery": "acceptance_m1",
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blender_binary": str(blender),
        "extension_zip": zip_path.name,
        "blender_version": None,
        "phases": {},
        "checks": checks,
        "all_passed": False,
    }

    def record(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + name + (f"  — {detail}" if detail else ""))
        return bool(passed)

    try:
        # ---- phase 0: version probe ------------------------------------------------
        p, _ = run([str(blender), "--version"], env)
        ver_line = next((l for l in (p.stdout or "").splitlines() if l.startswith("Blender")), "?")
        result["blender_version"] = ver_line.strip()
        record("blender.version", "Blender" in ver_line, ver_line.strip())

        # ---- phase A: install the built zip through the extension system ---------
        p, dur = run(
            [str(blender), "--command", "extension", "install-file",
             "-r", "user_default", "-e", str(zip_path)],
            env, timeout=300,
        )
        out = (p.stdout or "") + (p.stderr or "")
        installed = p.returncode == 0 and ("Installed" in out or "Reinstalled" in out)
        result["phases"]["install"] = {
            "exit": p.returncode, "seconds": round(dur, 1), "output": out.strip()[:400],
        }
        record("extension.install", installed, f"exit {p.returncode}; {out.strip()[:120]}")

        # ---- phase B: verify inside Blender (extension auto-enabled at startup) --
        outb = userdir / "verify_phase.json"
        p, dur = run(
            [str(blender), "--background", "--python",
             str(HERE / "acceptance_verify_phase.py"), "--", str(outb)],
            env, timeout=600,
        )
        out = (p.stdout or "") + (p.stderr or "")
        vd = {}
        if outb.is_file():
            vd = json.loads(outb.read_text())
            result["phases"]["verify"] = {
                "exit": p.returncode, "seconds": round(dur, 1),
                "blend": vd.get("blend_file"),
                "phase_all_passed": vd.get("all_passed"),
                "dxf_engine": vd.get("dxf_engine"),
            }
            for c in vd.get("checks", []):
                record("verify." + c["check"], c["passed"], c.get("detail", ""))
        else:
            record("verify.phase_ran", False, f"no result json; exit {p.returncode}; tail: {out[-500:]}")

        blend_file = vd.get("blend_file")

        # ---- phase C: fresh process reopens the .blend ---------------------------
        outc = userdir / "reopen_phase.json"
        if blend_file and Path(blend_file).is_file():
            p, dur = run(
                [str(blender), "--background", "--python",
                 str(HERE / "acceptance_reopen_phase.py"), "--", str(blend_file), str(outc)],
                env, timeout=600,
            )
            out = (p.stdout or "") + (p.stderr or "")
            if outc.is_file():
                rd = json.loads(outc.read_text())
                result["phases"]["reopen"] = {
                    "exit": p.returncode, "seconds": round(dur, 1),
                    "phase_all_passed": rd.get("all_passed"),
                }
                for c in rd.get("checks", []):
                    record("reopen." + c["check"], c["passed"], c.get("detail", ""))
            else:
                record("reopen.phase_ran", False, f"no result json; exit {p.returncode}; tail: {out[-500:]}")
        else:
            record("reopen.blend_exists", False, "phase B produced no .blend to reopen")

        # ---- uninstall cleanly (extension system) --------------------------------
        p, _ = run(
            [str(blender), "--command", "extension", "remove", "blender_cad"],
            env, timeout=120,
        )
        out = (p.stdout or "") + (p.stderr or "")
        removed = p.returncode == 0 or "not installed" in out.lower() or "removed" in out.lower()
        record("extension.uninstall", removed, f"exit {p.returncode}; {out.strip()[:120]}")
    finally:
        result["all_passed"] = bool(checks) and all(c["passed"] for c in checks)
        result["platform"] = platform.platform()
        RESULT.write_text(json.dumps(result, indent=2))
        print(f"\n{'ALL CHECKS PASSED' if result['all_passed'] else 'BATTERY FAILED'} "
              f"({sum(c['passed'] for c in checks)}/{len(checks)} checks)")
        print(f"evidence: {RESULT}")
        if not args.keep_userdir:
            shutil.rmtree(userdir, ignore_errors=True)
        else:
            print(f"userdir kept: {userdir}")

    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
