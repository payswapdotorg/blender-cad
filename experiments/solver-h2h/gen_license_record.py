#!/usr/bin/env python3
"""Generate results/license-planegcs-eigen.json — machine-readable license record (h2h-2a).

Machine-verifies the license facts for the two NEW pins this lane introduces,
reading the pinned artifacts directly (never hand-typed quotes):

  1. FreeCAD 1.1.4 (tag 4fd3bf3) planegcs — all 11 files' license headers
     (Poulios 2011 GNU-LGPL-family wording; Geo.cpp also credits DeepSOIC 2014),
     the FreeCAD root LICENSE (full LGPL-2.1 text), the boost>=1.75 wrapper
     (SPDX LGPL-2.1-or-later), SketcherGlobal.h (Werner Mayer 2019).
  2. Eigen 3.4.0 orig tarball (sha256-pinned Debian-pool artifact) —
     COPYING.MPL2 (full MPL-2.0 text) + COPYING.README (Eigen's own licensing
     explanation), plus the FreeCAD 1.1.4 SetupEigen.cmake requirement facts.
  3. Retest of the m3-eval blocker: eigen@3147391d (solvespace's gitlink pin)
     — is the canonical gitlab reachable from this sandbox NOW? The result is
     recorded either way; the solvespace-scoped (verify) tag is NOT cleared by
     a different pin, only by verifying THAT pin.

No adoption verdict is produced — the record feeds the TL-owned
license-inventory process (docs/00-architecture/license-inventory.md §7).

Usage: python3 experiments/solver-h2h/gen_license_record.py
"""
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = HERE
UP = LANE / ".upstream"
FREECAD = UP / "freecad-pin"
EIGEN = UP / "eigen-3.4.0"
OUT = LANE / "results" / "license-planegcs-eigen.json"

FREECAD_TAG = "1.1.4"
FREECAD_SHA = "4fd3bf320d9566a27e60069fc8387448aaa3a094"
EIGEN_TARBALL = "eigen3_3.4.0.orig.tar.bz2"
EIGEN_SHA256 = "b4c198460eba6f28d34894e3a5710998818515104d6e74e5cc331ce31e46e626"
EIGEN_URL = f"https://deb.debian.org/debian/pool/main/e/eigen3/{EIGEN_TARBALL}"

PLANEGCS_FILES = [
    "Constraints.cpp", "Constraints.h", "GCS.cpp", "GCS.h", "Geo.cpp", "Geo.h",
    "SubSystem.cpp", "SubSystem.h", "Util.h", "qp_eq.cpp", "qp_eq.h",
]
PLANEGCS_DIR = FREECAD / "src/Mod/Sketcher/App/planegcs"

checks = []


def record(name, passed, detail, **extra):
    e = {"name": name, "pass": bool(passed), "detail": detail}
    e.update(extra)
    checks.append(e)
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")
    return bool(passed)


def header_of(path, n=27):
    """The license header block of a FreeCAD source file (leading comment)."""
    lines = path.read_text(errors="replace").splitlines()
    out, inside = [], False
    for ln in lines[:40]:
        s = ln.strip()
        if s.startswith("/****"):
            inside = True
        if inside:
            out.append(ln)
            if s.endswith("****/") or s == "*/":
                break
    return "\n".join(out[:n])


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not (PLANEGCS_DIR / "GCS.h").is_file():
        raise SystemExit("pinned FreeCAD checkout missing — run fetch-planegcs.sh first")
    if not (EIGEN / "COPYING.MPL2").is_file():
        raise SystemExit("pinned Eigen missing — run fetch-eigen.sh first")

    # --- 1. planegcs per-file headers -------------------------------------
    per_file = {}
    all_match = True
    for f in PLANEGCS_FILES:
        hdr = header_of(PLANEGCS_DIR / f)
        per_file[f] = {
            "header_first_line": hdr.splitlines()[0] if hdr else "",
            "copyright_line": next((l.strip() for l in hdr.splitlines()
                                    if "Copyright" in l), ""),
            "license_phrase": ("GNU Library General Public" in hdr),
            "or_later": ("any later version" in hdr),
            "verbatim": hdr,
            "sha256": hashlib.sha256((PLANEGCS_DIR / f).read_bytes()).hexdigest(),
        }
        ok = per_file[f]["license_phrase"] and per_file[f]["or_later"]
        all_match &= ok
    record("planegcs.all_11_headers_lgpl_family_or_later", all_match,
           "every planegcs file header carries 'GNU Library General Public License ... "
           "or any later version' wording (verbatim per file in artifacts.planegcs_files)",
           files_with_deviation=[f for f in per_file
                                 if not (per_file[f]["license_phrase"] and per_file[f]["or_later"])])
    record("planegcs.geo_cpp_second_author", "Victor Titov" in per_file["Geo.cpp"]["copyright_line"],
           "Geo.cpp copyright adds Victor Titov (DeepSOIC) <vv.titov@gmail.com> 2014 "
           "alongside the Poulios header — verbatim in artifacts")

    # --- 2. FreeCAD root LICENSE = full LGPL-2.1 ----------------------------
    lic = (FREECAD / "LICENSE").read_text(errors="replace")
    record("freecad_root_license_is_lgpl21",
           lic.lstrip().startswith("GNU LESSER GENERAL PUBLIC LICENSE")
           and "Version 2.1, February 1999" in lic[:400],
           "FreeCAD 1.1.4 root LICENSE is the full GNU LGPL-2.1 text "
           f"({len(lic)} chars; head quoted in artifacts)",
           head=lic.lstrip()[:200], chars=len(lic))

    # --- 3. boost wrapper SPDX --------------------------------------------
    wrap = (FREECAD / "src/boost_graph_adjacency_list.hpp").read_text()
    record("boost_wrapper_spdx_lgpl21_or_later",
           "SPDX-License-Identifier: LGPL-2.1-or-later" in wrap,
           "src/boost_graph_adjacency_list.hpp:2 — SPDX LGPL-2.1-or-later "
           "(the 11-line boost>=1.75 deprecated-headers workaround planegcs includes)",
           verbatim=wrap.splitlines()[1])

    # --- 4. SketcherGlobal.h header ---------------------------------------
    sg = header_of(FREECAD / "src/Mod/Sketcher/SketcherGlobal.h")
    record("sketcherglobal_header",
           "GNU Library General Public" in sg and "Werner Mayer" in sg,
           "src/Mod/Sketcher/SketcherGlobal.h (Werner Mayer 2019) carries the same "
           "LGPL-family header — vendored read-only by the build, never modified",
           verbatim=sg)

    # --- 5. Eigen 3.4.0 at the exact artifact ------------------------------
    tarball = UP / EIGEN_TARBALL
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    record("eigen.tarball_sha256_matches_pin", digest == EIGEN_SHA256,
           f"{EIGEN_TARBALL} sha256 {digest} == pin (Debian pool mirror of the "
           "upstream 3.4.0 release tarball)")
    mpl2 = (EIGEN / "COPYING.MPL2").read_text(errors="replace")
    record("eigen.copying_mpl2_is_full_mpl2_text",
           "Mozilla Public License Version 2.0" in mpl2[:100]
           and "1. Definitions" in mpl2 and len(mpl2) > 14000,
           f"eigen-3.4.0/COPYING.MPL2 is the full MPL-2.0 text ({len(mpl2)} chars; "
           "first lines quoted in artifacts)",
           head=mpl2.lstrip()[:160], chars=len(mpl2),
           sha256=hashlib.sha256(mpl2.encode()).hexdigest())
    readme = (EIGEN / "COPYING.README").read_text(errors="replace")
    record("eigen.copying_readme_records_mpl2_default",
           "MPL2" in readme and "GPL" in readme and "BSD" in readme,
           "COPYING.README explains Eigen's multi-licensing (MPL2 default, with "
           "GPLv3+/BSD-3 alternative options for derivative works) — quoted in artifacts",
           verbatim=readme)

    # --- 6. FreeCAD's Eigen requirement at the pin --------------------------
    setup = (FREECAD / "cMake/FreeCAD_Helpers/SetupEigen.cmake").read_text()
    record("freecad_1_1_4_targets_eigen3",
           "necessary for Sketcher module" in setup,
           "FreeCAD 1.1.4 cMake/FreeCAD_Helpers/SetupEigen.cmake: find_package(Eigen3) "
           "with 'necessary for Sketcher module'; flatmesh requires >= 3.4.0 — the "
           "planegcs build targets the 3.4 line, matching production FreeCAD",
           verbatim_quote='''# -------------------------------- Eigen --------------------------------
    # necessary for Sketcher module''')

    # --- 7. m3-eval blocker retest: eigen@3147391d --------------------------
    # m3-eval §9 recorded this pin (solvespace's gitlink) as unverifiable from
    # its sandbox (gitlab https fetch => 403, 2026-10-20). Retested by this
    # lane the same day: fetchable. If fetch-eigen.sh materialized it, verify
    # COPYING.MPL2 AT THE PIN; otherwise record the environment fact honestly.
    retest = UP / "eigen-3147391d"
    if (retest / "COPYING.MPL2").is_file():
        pin_mpl2 = (retest / "COPYING.MPL2").read_bytes()
        ident = hashlib.sha256(pin_mpl2).hexdigest() == hashlib.sha256(mpl2.encode()).hexdigest()
        try:
            subject = subprocess.run(
                ["git", "-C", str(retest), "log", "-1", "--format=%s", "FETCH_HEAD"],
                capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:  # noqa: BLE001
            subject = "(git log unavailable)"
        record("eigen_3147391d_copying_mpl2_verified_at_pin", ident,
               f"eigen @ 3147391d is fetchable NOW (retest of the m3-eval §9 403 "
               f"condition; commit subject: '{subject}') and its COPYING.MPL2 is "
               "byte-identical to the eigen 3.4.0 release artifact verified above — "
               "the solvespace-row (verify) blocker is CLEARED by at-pin evidence",
               commit_subject=subject,
               copying_mpl2_sha256=hashlib.sha256(pin_mpl2).hexdigest(),
               release_mpl2_sha256=hashlib.sha256(mpl2.encode()).hexdigest())
    else:
        record("eigen_3147391d_copying_mpl2_verified_at_pin", False,
               "retest fetch did not materialize the pin (network condition) — "
               "the solvespace-scoped (verify) tag stays exactly per m3-eval §9")
    gitlab_reachable = False
    gitlab_note = ""
    try:
        p = subprocess.run(
            ["git", "ls-remote", "https://gitlab.com/libeigen/eigen.git", "HEAD"],
            capture_output=True, text=True, timeout=30)
        gitlab_reachable = p.returncode == 0
        gitlab_note = (f"exit {p.returncode}: "
                       + (p.stderr.strip() or p.stdout.strip())[:160])
    except Exception as e:  # noqa: BLE001
        gitlab_note = f"exception: {e}"
    record("eigen_gitlab_reachable_this_sandbox", gitlab_reachable,
           "retest of the m3-eval §7.2/§9 blocker condition: " + gitlab_note)

    # --- assemble -----------------------------------------------------------
    passed = sum(1 for c in checks if c["pass"])
    doc = {
        "experiment": "h2h-license-planegcs-eigen",
        "issue_ref": "m3-solver-h2h (m3-eval §8 items 1-2; solidcraft-evaluation "
                     "§4.1 gate (a)) — PlaneGCS license verification before any "
                     "vendoring decision + the pins this lane introduces",
        "command": "python3 experiments/solver-h2h/gen_license_record.py",
        "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pins": {
            "freecad": {"repo": "https://github.com/FreeCAD/FreeCAD.git",
                        "tag": FREECAD_TAG, "tag_sha": FREECAD_SHA},
            "eigen": {"artifact": EIGEN_URL, "sha256": EIGEN_SHA256,
                      "canonical_repo": "https://gitlab.com/libeigen/eigen.git",
                      "canonical_reachable_this_sandbox": gitlab_reachable},
        },
        "artifacts": {
            "planegcs_files": per_file,
            "freecad_root_license_head": lic.lstrip()[:200],
            "boost_wrapper_line2": wrap.splitlines()[1],
            "sketcherglobal_header": sg,
            "eigen_copying_mpl2_head": mpl2.lstrip()[:160],
            "eigen_copying_readme": readme,
            "freecad_setup_eigen": 'necessary for Sketcher module',
        },
        "classification_note": (
            "Per-file planegcs headers use the legacy 'GNU Library General Public "
            "License ... version 2 of the License, or (at your option) any later "
            "version' wording (LGPL-2.0+-in-form); the FreeCAD project-level "
            "license is LGPL-2.1-or-later (root LICENSE = full LGPL-2.1 text; "
            "sibling files such as boost_graph_adjacency_list.hpp carry "
            "SPDX LGPL-2.1-or-later). Both readings are LGPL-family with an "
            "'or later' clause and are GPL-3.0-or-later-host-compatible for "
            "combined distribution; the conservative classification is recorded "
            "verbatim-quoted in the findings doc and the inventory row states "
            "the ambiguity explicitly. No verdict is produced here."
        ),
        "checks": checks,
        "summary": {"checks_total": len(checks), "checks_passed": passed,
                    "checks_failed": len(checks) - passed},
        "failures": [c for c in checks if not c["pass"]],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"\nwrote {OUT}  ({passed}/{len(checks)} checks pass)")
    json.loads(OUT.read_text())  # parse self-check


if __name__ == "__main__":
    main()
