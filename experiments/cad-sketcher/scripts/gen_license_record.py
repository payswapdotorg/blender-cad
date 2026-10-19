#!/usr/bin/env python3
"""Generate results/license-supply-chain.json — machine-readable license/supply-chain record.

Machine-verifies the license facts that live in the pinned checkout
(.upstream/CAD_Sketcher at v0.32.1): the addon manifest/LICENSE/units.py, and the
pinned wheel's METADATA classifier vs its bundled licenses/COPYING.txt. Facts from
the slvs sdist (solvespace @ 477d4c8) are re-verified when the sdist is present at
$CAD_SKETCHER_SDIST (default /home/z/cad-sketcher-eval-scratch/slvs-3.2, produced
by downloading the PyPI sdist whose sha256 fetch-solver.sh records); otherwise the
recorded values are emitted with verified:false + a note. No verdict is produced —
the record feeds the TL-owned license-inventory process.

Usage: python3 gen_license_record.py
"""

import hashlib
import json
import os
import re
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = HERE.parent
UP = LANE / ".upstream" / "CAD_Sketcher"
OUT = LANE / "results" / "license-supply-chain.json"
SDIST = Path(os.environ.get("CAD_SKETCHER_SDIST", "/home/z/cad-sketcher-eval-scratch/slvs-3.2"))
SDIST_SHA256 = "cf7c00fb17a2d100df7cfa80db5e04c7ec16e6093b3d9a74402f001043550a9b"
WHEEL = "wheels/slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
WHEEL_SHA256 = "9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80"
SOLVESPACE_SHA = "477d4c87ca51b9727fbc0765cbd94253c3968b8b"

checks = []


def record(name, passed, detail):
    checks.append({"name": name, "pass": bool(passed), "detail": detail})
    print(f"{'PASS' if passed else 'FAIL'} {name}  {detail}")
    return bool(passed)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not (UP / "wheels" / "slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl").is_file():
        raise SystemExit("pinned checkout missing — run fetch-upstream.sh first")
    wheel_bytes = (UP / WHEEL).read_bytes()
    record("wheel.pinned_digest", sha256_bytes(wheel_bytes) == WHEEL_SHA256,
           f"{WHEEL.split('/')[-1]} sha256 matches pin")

    z = zipfile.ZipFile(UP / WHEEL)
    meta = z.read("slvs-3.2.dist-info/METADATA").decode()
    wheel_copying = z.read("slvs-3.2.dist-info/licenses/COPYING.txt")
    mit_classifier = "Classifier: License :: OSI Approved :: MIT License" in meta
    copying_is_gplv3 = wheel_copying.decode(errors="replace")[:120].lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    record("wheel.metadata_claims_mit", mit_classifier, "METADATA carries 'License :: OSI Approved :: MIT License'")
    record("wheel.shipped_license_is_gplv3", copying_is_gplv3,
           "dist-info/licenses/COPYING.txt = full GPLv3 text — contradicts the MIT classifier")

    # addon license facts
    manifest = (UP / "blender_manifest.toml").read_text()
    record("addon.manifest_gpl3_or_later", 'license = ["SPDX:GPL-3.0-or-later"]' in manifest,
           "blender_manifest.toml license field")
    lic = (UP / "LICENSE").read_text(errors="replace")
    record("addon.license_text_is_gplv3", lic[:80].lstrip().startswith("GNU GENERAL PUBLIC LICENSE"),
           "LICENSE = full GPLv3 text (no 'or later' wording inside; grant = manifest SPDX)")
    units_head = "\n".join((UP / "units.py").read_text(errors="replace").splitlines()[:2])
    record("addon.units_provenance_header", "MeasureIt_ARCH" in units_head,
           f"units.py:1-2 = {units_head!r}")

    # sdist-side facts (solvespace source @ 477d4c8)
    sdist_present = (SDIST / "COPYING.txt").is_file()
    sv = {}
    if sdist_present:
        sc = (SDIST / "COPYING.txt").read_text(errors="replace")
        sv["copying_is_gplv3"] = sc[:120].lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
        sv["copying_identical_to_wheel_license"] = sha256_bytes((SDIST / "COPYING.txt").read_bytes()) == sha256_bytes(wheel_copying)
        readme = (SDIST / "README.md").read_text(errors="replace")
        sv["readme_license_statement"] = "GPL v3" in readme and "or later" in readme.split("## License")[1][:200]
        contrib = (SDIST / "CONTRIBUTING.md").read_text(errors="replace")
        sv["contributing_license_statement"] = "GPLv3 or later" in contrib
        githead = (SDIST / ".git" / "HEAD").read_text().strip()
        gittag = (SDIST / ".git" / "refs" / "tags" / "v3.2").read_text().strip()
        sv["embedded_git_sha"] = githead == SOLVESPACE_SHA == gittag
        no_exception = ("special exception" not in sc.lower()) and ("as a special" not in sc.lower())
        pyproject = (SDIST / "pyproject.toml").read_text(errors="replace")
        sv["pyproject_mit_classifier"] = '"License :: OSI Approved :: MIT License"' in pyproject
        sv["pyproject_no_license_field"] = not re.search(r"^license\s*=", pyproject, re.M)
        record("sdist.git_provenance", sv["embedded_git_sha"],
               f".git/HEAD == .git/refs/tags/v3.2 == solvespace@{SOLVESPACE_SHA[:9]}…")
        record("sdist.copying_no_linking_exception", no_exception and sv["copying_is_gplv3"],
               "COPYING.txt = plain GPLv3, no appended exception clause (grep 'special exception' negative)")
        record("sdist.statements_gplv3_or_later", sv["readme_license_statement"] and sv["contributing_license_statement"],
               "README.md:356 'GPL v3 or later'; CONTRIBUTING.md:20 'GPLv3 or later'")
        record("sdist.wheel_license_matches_solvespace", sv["copying_identical_to_wheel_license"],
               "wheel licenses/COPYING.txt byte-identical to solvespace COPYING.txt")
        record("sdist.pyproject_mit_classifier_source", sv["pyproject_mit_classifier"] and sv["pyproject_no_license_field"],
               "the MIT classifier originates in pyproject.toml (no SPDX license field present)")
    else:
        print(f"NOTE: sdist not found at {SDIST} — solvespace-side facts emitted as recorded values (verified: false)")
        sv = {"copying_is_gplv3": None, "copying_identical_to_wheel_license": None,
              "readme_license_statement": None, "contributing_license_statement": None,
              "embedded_git_sha": None, "pyproject_mit_classifier": None, "pyproject_no_license_field": None}

    envelope = {
        "experiment": "license-supply-chain",
        "issue_ref": "m3-eval phase 1 (CAD Sketcher evaluation)",
        "command": "python3 experiments/cad-sketcher/scripts/gen_license_record.py",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream": {"repo": "https://github.com/hlorus/CAD_Sketcher", "tag": "v0.32.1",
                     "sha": "e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4"},
        "verdict_policy": "NO COMPATIBILITY VERDICT IS PRODUCED HERE — the TL owns the "
                          "license-inventory row and the adoption/evaluation verdict. Unresolved items "
                          "are blockers below, never assumptions.",
        "artifacts": {
            "cad_sketcher_addon_v0.32.1": {
                "license": "GPL-3.0-or-later",
                "source_of_truth": "blender_manifest.toml:12 ('SPDX:GPL-3.0-or-later') + LICENSE (full GPLv3 text, 674 lines)",
                "quote": "license = [\"SPDX:GPL-3.0-or-later\"]",
                "verified": True,
                "notes": "no per-file SPDX/copyright headers in 356 py files; units.py re-distributes "
                         "MeasureIt_ARCH code (GPL-2.0-or-later) with the license block dropped, only a URL comment kept",
            },
            "slvs_wheel_3.2_cp313_manylinux_x86_64": {
                "license_evidence": "CONFLICTING: METADATA classifier 'MIT' vs shipped licenses/COPYING.txt = GPLv3 text",
                "source_of_truth": "slvs-3.2.dist-info/METADATA; slvs-3.2.dist-info/licenses/COPYING.txt",
                "quotes": {
                    "metadata": "Classifier: License :: OSI Approved :: MIT License",
                    "shipping_license": "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007 (full text)",
                },
                "sha256": WHEEL_SHA256,
                "verified": True,
                "notes": "governing terms for the binary are presented in findings/license-supply-chain.md §3.4: "
                         "the .so is a compiled derivative of GPLv3-or-later solver code (no linking exception), "
                         "with Eigen MPL-2.0 and mimalloc MIT statically linked in",
            },
            "solvespace_source_of_slvs_3.2": {
                "license": "GPL-3.0-or-later",
                "source_of_truth": "README.md:355-356; CONTRIBUTING.md:20-21; COPYING.txt at solvespace@477d4c8",
                "quotes": {
                    "README.md:356": "SolveSpace is distributed under the terms of the [GPL v3](COPYING.txt) or later.",
                    "CONTRIBUTING.md:20-21": "SolveSpace is licensed under the GPLv3 or later and any contributions must be made available under the terms of that license.",
                    "COPYING.txt": "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007 — full text, NO appended exception/linking-permission clause",
                },
                "repo": "https://github.com/solvespace/solvespace",
                "sha": SOLVESPACE_SHA,
                "provenance": "slvs-3.2 sdist embeds .git/HEAD and .git/refs/tags/v3.2 == 477d4c8 (pyproject sdist.include); "
                              "commit confirmed present in solvespace/solvespace via git fetch --depth 1",
                "tag_drift": "solvespace v3.2 tag moved to 27b6a08 on 2026-03-26, AFTER the 2026-03-23 PyPI upload; "
                             "477d4c8 is an ancestor of 27b6a08 (merge-base --is-ancestor verified)",
                "verified": bool(sdist_present and sv["embedded_git_sha"]),
            },
            "eigen_in_so": {
                "license": "MPL-2.0 (UNVERIFIED AT PIN)",
                "source_of_truth": "gitlink 3147391d946bb4b6c68edd901f2add6ac1f31f8c in solvespace@477d4c8 extlib/eigen -> gitlab.com/libeigen/eigen",
                "verified": False,
                "notes": "gitlab raw endpoint Cloudflare-blocked in this sandbox; GitHub mirrors lack the commit — BLOCKER",
            },
            "mimalloc_in_so": {
                "license": "MIT",
                "source_of_truth": "LICENSE at mimalloc@f81bf1b31af819a31195e08f9546dc80f8931587 (raw file fetched at that SHA)",
                "quote": "MIT License / Copyright (c) 2018-2025 Microsoft Corporation, Daan Leijen",
                "verified": True,
            },
            "pypi_slvs_project_urls": {"project_urls": None, "author_email": "Koen Schmeets <koen@schmeets.de>",
                                       "summary": "SolveSpace solver wrapped with Cython",
                                       "upload_3_2": "2026-03-23T15:04:46Z…T15:05:55Z (48 files)"},
            "pypi_py_slvs_distinct_project": {
                "note": "py-slvs 1.0.6 (realthunder/slvs_py, Zheng Lei) is a DIFFERENT older binding; CAD_Sketcher "
                        "docs reference it historically; v0.32.1 ships only `slvs` 3.2",
                "verified": True,
            },
        },
        "inconsistencies": [
            {"id": "slvs-wheel-metadatavs-copying",
             "severity": "blocker for any adoption/derivation; supply-chain scan risk",
             "facts": "wheel METADATA says 'License :: OSI Approved :: MIT License' while the same wheel ships "
                      "licenses/COPYING.txt = full GPLv3 (byte-identical to solvespace's COPYING.txt) and wraps "
                      "GPLv3-or-later solver code with no linking exception",
             "resolution_owner": "TL (verdict) + upstream (classifier fix); recorded here as evidence only"},
        ],
        "open_questions": [
            {"id": "eigen-license-at-pin", "blocker": True,
             "question": "Eigen's license text must be read at gitlink 3147391d (gitlab raw blocked in this sandbox)",
             "until": "verify before any decision that ships the wheel"},
            {"id": "binding-wrapper-per-file-license", "blocker": False,
             "question": "src/slvs/lib.pyx + python/slvs carry no license headers; if the author ever states the "
                         "wrapper-only is MIT (as the classifier hints), the .so remains GPLv3+ as a combined work; "
                         "per-file status matters only for extracting wrapper patterns",
             "until": "upstream statement or future commit"},
            {"id": "solvespace-tag-drift", "blocker": False,
             "question": "solvespace v3.2 tag moved after the PyPI upload; always take slvs provenance from the "
                         "sdist's embedded .git refs, never from the upstream tag",
             "until": "standing policy, re-checked per future slvs release"},
            {"id": "units.py-notice-gap", "blocker": False,
             "question": "CAD_Sketcher ships MeasureIt_ARCH GPL-2.0+-derived units.py without the license block; "
                         "if we ever adapt that file we must restore the block + attribution",
             "until": "only relevant if code is derived"},
        ],
        "verification_log": [
            "2026-10-20 · CAD_Sketcher v0.32.1 LICENSE + blender_manifest.toml (pinned checkout) · license/manifest file read · E1 (m3-eval) · GPL-3.0-or-later (high)",
            "2026-10-20 · solvespace@477d4c8 COPYING.txt/README.md:355-356/CONTRIBUTING.md:20-21 (slvs-3.2 sdist, sha256 " + SDIST_SHA256[:16] + "…) · license file read + repo statements · E1 (m3-eval) · GPL-3.0-or-later (high); NO linking exception (full read + grep)",
            "2026-10-20 · slvs-3.2 wheel METADATA vs licenses/COPYING.txt (pinned wheel) · metadata vs license-file comparison · E1 (m3-eval) · INCONSISTENT: classifier MIT vs shipped GPLv3 text (high confidence in the inconsistency)",
            "2026-10-20 · mimalloc LICENSE @f81bf1b (raw file at SHA) · license file read · E1 (m3-eval) · MIT (high)",
            "2026-10-20 · eigen COPYING.MPL2 @3147391d · NOT VERIFIED — gitlab raw Cloudflare-blocked; mirrors lack the commit · E1 (m3-eval) · MPL-2.0 unverified ((verify) blocker)",
            "2026-10-20 · MeasureIt_ARCH measureit_arch_units.py GPL block + repo LICENSE (branch development) · license file read · E1 (m3-eval) · units.py content GPL-2.0-or-later-derived, notice block dropped by upstream (high)",
        ],
        "checks": checks,
        "failures": [c for c in checks if not c["pass"]],
        "summary": {"all_machine_checks_passed": all(c["pass"] for c in checks),
                    "human_blockers": ["eigen-license-at-pin", "slvs-wheel-metadatavs-copying (TL-owned resolution)"],
                    "sdist_reverified_this_run": bool(sdist_present)},
    }
    envelope["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUT.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    return 0 if envelope["summary"]["all_machine_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
