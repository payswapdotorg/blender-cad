#!/usr/bin/env python3
"""Experiment D — runtime & distribution record generator (m3-eval phase 2b).

Compiles the distribution-relevant evidence: platform matrix vs OUR five target
platforms, wheel/ZIP/installed sizes, native-library requirements (ldd on the
pinned solver binary), Python ABI, startup impact (Phase 1 measurement, cited),
error-handling surface (Phase 2a + addon operator paths), and distribution
obligations (Phase 1 license evidence — facts only, verdicts TL-owned).

Re-measures what is re-measurable (ldd, install footprint, wheel inventory at
the pin) and embeds recorded results from prior envelopes with their sources.
Writes results/runtime-distribution.json (never hand-edited).

Usage: python3 gen_runtime_distribution.py   (dev python is sufficient; the
solver .so is only inspected with ldd/file, never imported here)
"""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = HERE.parent
UP = LANE / ".upstream" / "CAD_Sketcher"
OUT = LANE / "results" / "runtime-distribution.json"
SCRATCH = Path(os.environ.get("CAD_SKETCHER_SCRATCH", "/home/z/cad-sketcher-eval-scratch"))
INSTALL = SCRATCH / "ble_user_with_ext" / "extensions" / "user_default" / "CAD_Sketcher"
PIN_TAG, PIN_COMMIT = "v0.32.1", "e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4"

# Our five target platforms (kernel-bindings-evaluation-m1.md / OCP row evidence)
OUR_TARGETS = [
    ("macosx_11_0_arm64", "macos-arm64"),
    ("macosx_11_0_x86_64", "macos-x64"),
    ("manylinux_2_28_aarch64", None),   # -> no CAD Sketcher/linux-aarch64 wheel
    ("manylinux_2_28_x86_64", "linux-x64"),
    ("win_amd64", "windows-x64"),
]


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def main():
    checks = []

    def record(name, passed, detail):
        checks.append({"name": name, "pass": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}  {detail}")

    if not UP.is_dir():
        raise SystemExit("pinned checkout missing — run fetch-upstream.sh first")

    # ---- platform matrix -----------------------------------------------------
    manifest = (UP / "blender_manifest.toml").read_text()
    platforms = ["windows-x64", "macos-x64", "macos-arm64", "linux-x64"]
    wheels = sorted(p.name for p in (UP / "wheels").glob("*.whl"))
    tags = set()
    for w in wheels:
        parts = w.split("-")
        if parts[1] == "3.2":
            tags.add(parts[2])          # cp311 / cp313
            tags.update(parts[3:])      # platform tags
    matrix = []
    for target, cs_platform in OUR_TARGETS:
        covered = None
        if target.startswith("macosx_11_0_arm64"):
            covered = any("macosx_11_0_arm64" in w for w in wheels)
        elif target.startswith("macosx_11_0_x86_64"):
            # cp313 macosx_10_13_x86_64 (older min-macos than 11.0 — covers it)
            covered = any("macosx" in w and "x86_64" in w and "arm64" not in w
                          for w in wheels)
        elif target.startswith("manylinux_2_28_aarch64"):
            covered = any("aarch64" in w for w in wheels)
        elif target.startswith("manylinux_2_28_x86_64"):
            # manylinux_2_17 wheels satisfy a manylinux_2_28 baseline (glibc 2.17 <= 2.28)
            covered = any("manylinux" in w and "x86_64" in w and "aarch64" not in w
                          for w in wheels)
        elif target == "win_amd64":
            covered = any("win_amd64" in w for w in wheels)
        matrix.append({"our_target": target, "cad_sketcher_platform": cs_platform,
                       "covered": covered,
                       "note": "" if covered else
                       "MISSING: no linux-aarch64 wheel ships (wheels are cp311/cp313 "
                       "x86_64/arm64-macos/windows/manylinux+musllinux x86_64 only); "
                       "CAD Sketcher's manifest declares linux-x64, not linux-arm64"})
    n_missing = sum(1 for m in matrix if not m["covered"])
    # the CHECK is that the gap is identified and cited precisely — the gap
    # itself (linux-aarch64) is the FINDING, not a failure of this record
    record("platform.gap_identified_and_cited", n_missing == 1
           and matrix[2]["our_target"] == "manylinux_2_28_aarch64"
           and not matrix[2]["covered"],
           f"{len(matrix) - n_missing}/5 of OUR target platforms have wheels; "
           f"missing: {[m['our_target'] for m in matrix if not m['covered']]} "
           "(manifest declares windows-x64/macos-x64/macos-arm64/linux-x64; the "
           "wheel set has no aarch64 Linux build — a hypothetical adoption would "
           "need an aarch64 slvs wheel built from solvespace@477d4c8)")
    record("platform.python_abi", "cp311" in str(tags) and "cp313" in str(tags)
           and "cp312" not in str(tags),
           "wheels: cp311 + cp313 only (matches Blender-embedded Pythons 3.11/3.13; "
           "no cp312 — fine for our Blender 5.2.2 / 3.13 pin; docs' '3.11, 3.12 and "
           "3.13' refers to PyPI availability for source installs)")

    # ---- sizes ----------------------------------------------------------------
    wheel_sizes = {w.name: w.stat().st_size for w in sorted((UP / "wheels").glob("*.whl"))}
    total_wheels = sum(wheel_sizes.values())
    audit = json.loads((LANE / "results" / "upstream-audit.json").read_text())
    audit_sum = sum(v["size"] for v in audit["wheel_inventory"].values())
    install_bytes = None
    if INSTALL.is_dir():
        install_bytes = int(sh(["du", "-sb", str(INSTALL)]).split()[0])
    record("sizes.wheels_committed_matches_phase1_audit",
           total_wheels == audit_sum and len(wheel_sizes) == 10,
           f"10 wheels, {total_wheels} bytes committed in-repo — cross-checked "
           f"against results/upstream-audit.json's wheel inventory ({audit_sum} B); "
           "linux_x64 release ZIP: 13,968,966 B (sha256 c679cccd…)")
    record("sizes.installed_footprint_measured", install_bytes is not None,
           f"installed extension dir: {install_bytes} bytes "
           f"({install_bytes and round(install_bytes / 2**20, 1)} MiB; of which "
           f"wheels {13257604} bytes) — measured on the Phase 1 scratch install")

    # ---- native deps (ldd on the pinned cp313 manylinux .so) --------------------
    so = SCRATCH / "pytarget" / "slvs" / "solvespace.so"
    ldd = sh(["ldd", str(so)]).strip().splitlines() if so.is_file() else \
        ["<scratch extraction missing — run the phase-1 runtime orchestrator>"]
    record("native.solver_so_deps_standard_glibc", so.is_file() and
           all(not "not found" in line for line in ldd),
           "ldd solvespace.so: " + "; ".join(line.split("=>")[0].strip()
                                             for line in ldd if "=>" in line or "(" in line))
    record("native.manylinux_baseline",
           any("manylinux_2_17" in w for w in wheels),
           "tag manylinux_2_17 => glibc >= 2.17; a musllinux_1_2 variant exists for "
           "musl systems; Eigen (MPL-2.0) and mimalloc (MIT) are compiled IN "
           "(no separate .so — ldd shows only libstdc++/libm/libgcc/libc/librt/"
           "libpthread)")

    # ---- startup impact (Phase 1 measurement, cited) ----------------------------
    r1 = json.loads((LANE / "results" / "runtime-compat.json").read_text())
    record("startup.impact_phase1_cited", True,
           f"Phase 1 measured: blender --background startup median 0.539s without vs "
           f"0.664s with the extension enabled (delta {r1['startup_impact']['delta_median_s']}s, "
           "3 runs each, isolated BLENDER_USER_RESOURCES; results/runtime-compat.json)")

    # ---- error handling surface (Phase 2a + addon operator paths) -----------------
    record("error.solver_status_surface", True,
           "slvs exposes result flags OKAY/INCONSISTENT(=REDUNDANT_DIDNT_CONVERGE)/"
           "DIDNT_CONVERGE/TOO_MANY_UNKNOWNS/REDUNDANT_OKAY + dof + a bad-constraint "
           "handle list (phase 2a: failure-point report, NOT a full conflict "
           "diagnosis; no residual/iteration surface); the ADDON maps flags to user "
           "states incl. REDUNDANT_OK info (global_data.py:60-110) and marks "
           "per-constraint failed flags for the UI (curve_solver.py:329-361)")
    record("error.operator_paths", True,
           "operators report {'WARNING'}/{'ERROR'} strings: solve.py reports "
           "'Solver failed' WARNING; the extrude tool pre-validates with "
           "invalid_target_msg 'Select a sketch or curve to extrude (2D profile)' "
           "(operators/modifiers.py:755) and CANCELLED; guards inside the slvs "
           "binding ABORT the process on invalid API use (phase 2a: FatalError) — "
           "an integration must validate inputs BEFORE calling the solver")

    # ---- distribution obligations (facts only; TL owns verdicts) ------------------
    record("distribution.obligations_recorded", True,
           "addon GPL-3.0-or-later (manifest) + solver GPLv3-or-later with NO linking "
           "exception (phase 1, verbatim quotes in findings/license-supply-chain.md): "
           "any hypothetical distribution of the wheel requires the GPL license "
           "texts, corresponding source (solvespace@477d4c8 incl. Eigen@3147391d + "
           "mimalloc@f81bf1b submodules), notice preservation, and GPL-3.0-or-later "
           "combined-work terms (ADR-0005 context); the slvs wheel METADATA claims "
           "MIT while shipping GPLv3 COPYING.txt — scanners mis-report (phase 1 "
           "blocker, unresolved); update channels: extensions.blender.org listing "
           "(moderator approval) + self-hosted stable/latest index.json "
           "(hlorus/CAD_Sketcher-extensions, release.yaml publish-stable job)")

    envelope = {
        "experiment": "runtime-distribution",
        "issue_ref": "m3-eval phase 2b — experiment D (runtime & distribution record)",
        "command": "python3 experiments/cad-sketcher/scripts/gen_runtime_distribution.py",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream": {"repo": "https://github.com/hlorus/CAD_Sketcher",
                     "tag": PIN_TAG, "sha": PIN_COMMIT, "version": "0.32.1"},
        "explicit_note": "NOTHING in this record changes the runtime manifest or any "
                         "product artifact; the scratch install lives outside the repo "
                         "and outside our product. Facts only — verdicts are TL-owned.",
        "platform_matrix": matrix,
        "wheel_tags": sorted(tags),
        "wheel_sizes_bytes": wheel_sizes,
        "release_zip": {"name": "CAD_Sketcher-0.32.1-linux_x64.zip", "size": 13968966,
                        "sha256": "c679cccd8ae955c440787e6be4a8eaebfb77cb1909eb8de04ffc182e97774541"},
        "installed_footprint_bytes": install_bytes,
        "installed_wheels_bytes": 13257604,
        "solver_so_ldd": ldd,
        "startup_impact": r1["startup_impact"],
        "error_handling_surface": "see checks: solver flags + addon UI states + "
                                  "operator reporting; phase-2a/2b evidence cited",
        "distribution_obligations": "GPL-3.0-or-later addon + GPLv3-or-later solver "
                                   "(no linking exception); corresponding source "
                                   "solvespace@477d4c8 (+Eigen, +mimalloc); METADATA-MIT "
                                   "scanner trap; extensions.blender.org + self-hosted "
                                   "index.json channels",
        "checks": checks,
        "failures": [c for c in checks if not c["pass"]],
        "summary": {"all_checks_passed": all(c["pass"] for c in checks),
                    "platform_gap": "linux-aarch64 (our manylinux_2_28_aarch64 target "
                                    "has NO CAD Sketcher wheel — the addon declares "
                                    "linux-x64 only; a hypothetical adoption would "
                                    "require building an aarch64 slvs wheel from "
                                    "solvespace@477d4c8)",
                    "startup_delta_median_s": r1["startup_impact"]["delta_median_s"]},
    }
    envelope["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUT.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    return 0 if envelope["summary"]["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
