#!/usr/bin/env python3
"""TP-CAT-06 — native Blender regression battery, first recorded baseline (M1).

Purpose (test-plan §5 TP-CAT-06): the extension must not break stock Blender.
This battery runs the SAME native operation list twice:
  stock   — `--factory-startup`, extension NOT installed (the baseline record)
  loaded  — isolated userdir with the extension installed + enabled at startup
and asserts: every native op succeeds in BOTH runs, the extension registers and
unregisters cleanly, and a .blend saves/reloads in both modes. Startup wall-times
are recorded (informational budget — a regression is a defect to triage, not an
automatic hard fail; crashes/failed ops ARE hard fails).

Evidence: modules/testing/blender-regression/result-<label>.json

Run:  python3 modules/testing/blender-regression/run_battery.py [--label m1]
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PHASE = HERE / "native_ops_phase.py"
DIST = REPO / "dist"
DEFAULT_BLENDER = "/home/z/runtime/blender-5.2.2-linux-x64/blender"


def find_zip():
    zips = sorted(DIST.glob("blender_cad-*.zip"))
    if not zips:
        raise SystemExit("no dist zip — run scripts/build_extension.py first")
    return zips[-1]


def run(cmd, env=None, timeout=300):
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    return p, time.time() - t0


def native_pass(userdir, label, blender, extra_args=()):
    out = userdir / f"{label}.json"
    cmd = [str(blender)] + list(extra_args) + ["--python", str(PHASE), "--", str(out), label]
    env = dict(os.environ)
    if userdir:
        env["BLENDER_USER_RESOURCES"] = str(userdir)
    p, dur = run(cmd, env, timeout=600)
    data = None
    if out.is_file():
        data = json.loads(out.read_text())
    return p, dur, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="m1")
    ap.add_argument("--blender", default=DEFAULT_BLENDER)
    args = ap.parse_args()
    blender = Path(args.blender)
    zip_path = find_zip()

    result = {
        "suite": "TP-CAT-06 native Blender regression",
        "label": args.label,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blender": str(blender),
        "extension_zip": zip_path.name,
        "runs": {},
        "checks": [],
        "all_passed": False,
    }

    def record(name, passed, detail=""):
        result["checks"].append({"check": name, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail else ""))

    userdir = Path(tempfile.mkdtemp(prefix="bcad-t6-"))
    try:
        # stock baseline (factory startup — no extension present in a fresh userdir)
        p, dur, stock = native_pass(userdir, "stock", blender, ["--background", "--factory-startup"])
        if stock:
            result["runs"]["stock"] = {"seconds": round(dur, 1), "ops": stock["ops"],
                                       "startup_s": stock.get("startup_s")}
            record("stock.native_ops", all(o["ok"] for o in stock["ops"]),
                   f"{sum(o['ok'] for o in stock['ops'])}/{len(stock['ops'])} ops in {dur:.1f}s")
            record("stock.blend_save_reload", stock.get("blend_roundtrip_ok") is True, "")
        else:
            record("stock.native_ops", False, f"phase failed; exit {p.returncode}; {(p.stderr or '')[-300:]}")

        # install the extension into an isolated userdir, then run loaded
        env = dict(os.environ)
        env["BLENDER_USER_RESOURCES"] = str(userdir)
        p, _ = run([str(blender), "--command", "extension", "install-file",
                    "-r", "user_default", "-e", str(zip_path)], env, timeout=300)
        outt = (p.stdout or "") + (p.stderr or "")
        record("extension.install_for_battery", p.returncode == 0 and "Installed" in outt,
               outt.strip()[:80])

        p, dur, loaded = native_pass(userdir, "loaded", blender, ["--background"])
        if loaded:
            result["runs"]["loaded"] = {"seconds": round(dur, 1), "ops": loaded["ops"],
                                        "startup_s": loaded.get("startup_s"),
                                        "extension_registered": loaded.get("extension_registered"),
                                        "clean_unload": loaded.get("clean_unload")}
            record("loaded.native_ops", all(o["ok"] for o in loaded["ops"]),
                   f"{sum(o['ok'] for o in loaded['ops'])}/{len(loaded['ops'])} ops in {dur:.1f}s")
            record("loaded.blend_save_reload", loaded.get("blend_roundtrip_ok") is True, "")
            record("loaded.extension_registered", loaded.get("extension_registered") is True,
                   f"registered={loaded.get('extension_registered')}")
            record("loaded.clean_unload", loaded.get("clean_unload") is True, "")
        else:
            record("loaded.native_ops", False, f"phase failed; exit {p.returncode}; {(p.stderr or '')[-300:]}")

        # comparison: no native op may regress stock -> loaded
        if stock and loaded:
            stock_map = {o["op"]: o["ok"] for o in stock["ops"]}
            load_map = {o["op"]: o["ok"] for o in loaded["ops"]}
            regressed = [k for k in stock_map if stock_map[k] and k in load_map and not load_map[k]]
            record("no_native_regressions", not regressed, f"regressed={regressed}")
            delta = result["runs"]["loaded"].get("startup_s", 0) - result["runs"]["stock"].get("startup_s", 0)
            result["startup_delta_s"] = round(delta, 2)
            print(f"info: startup delta (loaded - stock): {delta:+.2f}s (budget: informational at M1)")
    finally:
        result["platform"] = platform.platform()
        result["all_passed"] = bool(result["checks"]) and all(c["passed"] for c in result["checks"])
        outpath = HERE / f"result-{args.label}.json"
        outpath.write_text(json.dumps(result, indent=2))
        print(f"\nTP-CAT-06 ({args.label}): {'ALL PASSED' if result['all_passed'] else 'FAILED'}")
        print(f"evidence: {outpath}")
        shutil.rmtree(userdir, ignore_errors=True)
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
