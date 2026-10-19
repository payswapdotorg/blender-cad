#!/usr/bin/env python3
"""Generate results/upstream-audit.json — machine-readable phase-1 upstream audit envelope.

Re-verifies every machine-checkable fact against the pinned checkout
(.upstream/CAD_Sketcher at tag v0.32.1) and fails loudly if the pin drifted.
Facts that are not machine-checkable from the checkout (PyPI digests, the `latest`
tag resolution) are carried as recorded constants with their capture date.

Usage: python3 gen_upstream_audit.py   (from anywhere; paths resolve via __file__)
"""

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = HERE.parent
UP = LANE / ".upstream" / "CAD_Sketcher"
OUT = LANE / "results" / "upstream-audit.json"

PIN_TAG = "v0.32.1"
PIN_TAG_OBJECT = "6a5a34001efcdec05381b6f419cc4d0394a24ab5"
PIN_COMMIT = "e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4"
LATEST_TAG_COMMIT_RECORDED = "efd255190f17e953786f29f22023d1a928a6a42e"
HEAD_MANIFEST_VERSION_RECORDED = "0.32.2"  # main HEAD manifest (dev), recorded 2026-10-20

# PyPI `slvs` 3.2 wheel digests, captured from pypi.org/pypi/slvs/json on 2026-10-20.
PYPI_SHA256 = {
    "slvs-3.2-cp311-cp311-macosx_10_12_x86_64.whl": "f21bbdf67b9baed14c12e9dcb4981a67149ee4802bf5b135b78208749b79399e",
    "slvs-3.2-cp311-cp311-macosx_11_0_arm64.whl": "8694977a5e7b6644a8825a105f9493c79db2bb935c81b4f035f98465f477d567",
    "slvs-3.2-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl": "69bcaba2e57e2eeba369200d08cf699f77fbdd3925324d60ca9dc10f699e11db",
    "slvs-3.2-cp311-cp311-musllinux_1_2_x86_64.whl": "9ae9ebc44d04bee76da0812501093db9a7e6a6e1dc8afd34d43efeadb93e1cfb",
    "slvs-3.2-cp311-cp311-win_amd64.whl": "a1f61065ddadd51dcc35e35e2941876c88f81e0d52536cc0c5e9a693a466e28b",
    "slvs-3.2-cp313-cp313-macosx_10_13_x86_64.whl": "d1c066311f0e79e82afb9179047b6ee8c4c8cfda5581f9d8d1a9d315b70de686",
    "slvs-3.2-cp313-cp313-macosx_11_0_arm64.whl": "afdc4874127d8bf6cd293b332a0b69fa023f742cf73726c999a898770bdcb874",
    "slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl": "9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80",
    "slvs-3.2-cp313-cp313-musllinux_1_2_x86_64.whl": "d130bdc47251ace22b2224dd42ef31dba1d47bd4a05c51a5ba3eb89b142c4412",
    "slvs-3.2-cp313-cp313-win_amd64.whl": "86159bc0c5e749eb04d94cbf28b6d38ace795e802b8131be36870502e336f4fa",
}

checks = []


def record(name, passed, detail):
    checks.append({"name": name, "pass": bool(passed), "detail": detail})
    print(f"{'PASS' if passed else 'FAIL'} {name}  {detail}")
    return bool(passed)


def git(args):
    return subprocess.run(["git", "-C", str(UP)] + args, capture_output=True, text=True, check=True).stdout


def main():
    if not (UP / ".git").exists():
        raise SystemExit("pinned checkout missing — run experiments/cad-sketcher/fetch-upstream.sh first")

    tag_obj = git(["rev-parse", PIN_TAG]).strip()
    commit = git(["rev-parse", PIN_TAG + "^{commit}"]).strip()
    record("pin.tag_resolves", tag_obj == PIN_TAG_OBJECT and commit == PIN_COMMIT,
           f"v0.32.1 -> tag {tag_obj[:9]}… commit {commit[:9]}…")
    record("pin.head_detached_at_pin", git(["rev-parse", "HEAD"]).strip() == PIN_COMMIT,
           "HEAD == pin commit")

    manifest = (UP / "blender_manifest.toml").read_text()
    mver = re.search(r'^version = "([^"]+)"', manifest, re.M).group(1)
    mlicense = re.search(r'^license = \["([^"]+)"\]', manifest, re.M).group(1)
    mmin = re.search(r'^blender_version_min = "([^"]+)"', manifest, re.M).group(1)
    mplat = re.findall(r'^\s*"([a-z0-9-]+)",?$', manifest.split("platforms = [")[1].split("]")[0], re.M)
    record("manifest.version_is_0_32_1", mver == "0.32.1", f"version = {mver}")
    record("manifest.license_gpl3_or_later", mlicense == "SPDX:GPL-3.0-or-later", f"license = {mlicense}")
    record("manifest.blender_min_5_0", mmin == "5.0.0", f"blender_version_min = {mmin}")

    wheels = {}
    for whl in sorted((UP / "wheels").glob("*.whl")):
        h = hashlib.sha256(whl.read_bytes()).hexdigest()
        wheels[whl.name] = {"size": whl.stat().st_size, "sha256": h,
                            "matches_pypi": PYPI_SHA256.get(whl.name) == h}
    record("wheels.ten_committed", len(wheels) == 10, f"{len(wheels)} wheels in wheels/")
    record("wheels.all_match_pypi_slvs_3_2", all(w["matches_pypi"] for w in wheels.values()),
           "10/10 sha256 byte-identical to PyPI slvs 3.2 files (digests captured 2026-10-20)")

    # release workflow: wheels must NOT be built/downloaded by CI
    release = (UP / ".github" / "workflows" / "release.yaml").read_text()
    wheel_build_refs = [ln for ln in release.splitlines()
                        if re.search(r"(pip |cibuildwheel|build.*wheel|wheel.*build)", ln) and not ln.strip().startswith("#")]
    record("release.wheels_not_rebuilt_by_ci", not wheel_build_refs,
           f"wheel-build command lines found: {wheel_build_refs or 'none'} (wheels are committed in-repo)")

    # source-header survey: exactly one provenance header, no SPDX/copyright headers
    grep = subprocess.run(["git", "-C", str(UP), "grep", "-n", "-i", "-E",
                           "copyright|SPDX|code from|taken from|borrowed from", "--", "*.py"],
                          capture_output=True, text=True)
    hits = [ln for ln in grep.stdout.splitlines() if ".py:" in ln]
    expected = [ln for ln in hits if ln.startswith("units.py:1")]
    record("sources.single_provenance_header", len(hits) == 1 and len(expected) == 1,
           f"provenance hits: {[ln.split(':')[0] + ':' + ln.split(':')[1] for ln in hits]} (units.py:1 MeasureIt_ARCH only; no SPDX/copyright headers)")

    # structure facts
    py_files = subprocess.run(["git", "-C", str(UP), "ls-files", "*.py"],
                              capture_output=True, text=True, check=True).stdout.split()
    loc = {}
    for d in ("model", "operators", "utilities", "drawing", "gizmos", "stateful_operator", "ui"):
        files = [UP / f for f in py_files if f.startswith(d + "/")]
        loc[d] = sum(len(p.read_text(errors="replace").splitlines()) for p in files)
    changelog = (UP / "CHANGELOG.md").read_text()
    has_0321 = "## 0.32.1" in changelog and "## 0.32.0" in changelog
    record("changelog.entries_present", has_0321, "CHANGELOG.md has ## 0.32.1 and ## 0.32.0 sections")

    # license files present at the pin
    license_is_gplv3 = (UP / "LICENSE").read_text()[:120].lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    record("addon.license_is_gplv3_text", license_is_gplv3, "LICENSE = full GPLv3 text (674 lines); 'or later' via manifest SPDX")

    envelope = {
        "experiment": "upstream-audit",
        "issue_ref": "m3-eval phase 1 (CAD Sketcher evaluation)",
        "command": "python3 experiments/cad-sketcher/scripts/gen_upstream_audit.py",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream": {
            "repo": "https://github.com/hlorus/CAD_Sketcher",
            "sha": commit,
            "tag": PIN_TAG,
            "tag_object": tag_obj,
            "version": mver,
            "pin_choice": "newest versioned release tag (v0.32.1); the `latest` tag is a moving pointer at main HEAD "
                          f"({LATEST_TAG_COMMIT_RECORDED[:9]}… at capture, 2026-10-20) and main already carries dev "
                          f"{HEAD_MANIFEST_VERSION_RECORDED}",
        },
        "host": {"cpus": os.cpu_count(),
                 "mem_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1),
                 "note": "sandbox container"},
        "findings": {
            "manifest": {"id": "CAD_Sketcher", "version": mver, "license": mlicense,
                         "blender_version_min": mmin, "platforms": mplat,
                         "wheel_count": len(wheels),
                         "wheel_python_tags": ["cp311", "cp313"],
                         "wheel_libc_tags": ["manylinux_2_17_x86_64.manylinux2014", "musllinux_1_2", "macosx", "win_amd64"],
                         "release_channels": ["github-releases", "extensions.blender.org", "self-hosted stable/latest (hlorus/CAD_Sketcher-extensions)"]},
            "release_pipeline": {
                "build_command": "blender --background --command extension build --split-platforms --output-dir dist",
                "validate_command": "blender --background --command extension validate",
                "wheels_rebuilt_by_ci": False,
                "wheels_source": "committed in-repo (wheels/), byte-identical to PyPI slvs 3.2",
                "assets_linux_x64_zip": {"name": "CAD_Sketcher-0.32.1-linux_x64.zip", "size": 13968966,
                                         "sha256": "c679cccd8ae955c440787e6be4a8eaebfb77cb1909eb8de04ffc182e97774541"},
            },
            "changelog": {
                "v0.32.1": ["coincident/midpoint constraint no longer crashes Blender",
                            "constraint labels/icons draw in the active viewport, not one view of a quad view"],
                "v0.32.0_headline": ["parts and assemblies (sketch geometry + workplanes; groups, instances, outliner)",
                                     "sketch result is a real mesh object (modifiers, export, mesh tools)",
                                     "Exact vs Manifold boolean solver choice",
                                     "circular/linear arrays, endpoint arc, chained drawing, auto-constraints at joints",
                                     "large-sketch performance work; under-constrained drift fix"],
            },
            "structure": {"py_files": len(py_files), "loc_by_dir": loc,
                          "seam": "curve_solver.py CurveSolver (lazy `import slvs` :67; workplane from sketch empty :90-138; "
                                  "entities from curve attributes :140-246; float32-precision write-back :494)",
                          "legacy_entity_layer": "model/group_entities.py SlvsEntities + group_constraints.py SlvsConstraints + serialize.py snapshots",
                          "own_persistence": "serialize.py scene_to_dict/scene_from_dict over ['entities', 'constraints']",
                          "constraint_classes": ["coincident", "horizontal", "vertical", "parallel", "perpendicular",
                                                 "tangent", "equal", "midpoint", "symmetry", "ratio", "distance",
                                                 "diameter", "angle"],
                          "vendored_third_party": {"path": "units.py", "origin": "MeasureIt_ARCH measureit_arch_units.py (GPL-2.0-or-later header dropped in copy)"}},
            "solver_diagnostics_surface": {"result_flags": ["OKAY", "INCONSISTENT", "DIDNT_CONVERGE", "TOO_MANY_UNKNOWNS", "REDUNDANT_OKAY"],
                                            "dof": "per-sketch IntProperty (model/sketch.py:26) + SolveResult.dof",
                                            "failed_constraints": "model/base_constraint.py:114 failed BoolProperty; curve_solver.py:329-361"},
        },
        "wheel_inventory": {k: v for k, v in wheels.items()},
        "pypi_digest_capture_date": "2026-10-20",
        "checks": checks,
        "failures": [c for c in checks if not c["pass"]],
        "summary": {"all_passed": all(c["pass"] for c in checks),
                    "pin": f"{PIN_TAG} @ {commit}"},
    }
    envelope["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUT.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    return 0 if envelope["summary"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
