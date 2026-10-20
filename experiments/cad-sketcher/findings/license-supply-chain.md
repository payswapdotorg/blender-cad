# CAD Sketcher license & solver supply-chain record — M3-eval phase 1

- **Status:** evaluation evidence record. **No compatibility verdict is made here** —
  the verdict is TL-owned (license-inventory.md row process). Unresolved items are
  recorded as explicit blockers below (§7), never resolved by assumption.
- **Owner:** E1 (m3-eval phase 1)
- **Date:** 2026-10-20 (UTC)
- **Pins (binding):** CAD_Sketcher `v0.32.1` = tag `6a5a340…` → commit `e7db7e6…`;
  solver source = solvespace/solvespace @ `477d4c87ca51b9727fbc0765cbd94253c3968b8b`;
  solver binary = in-repo wheel `slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`
  (sha256 `9ee04ff5…79399e`), byte-identical to the PyPI `slvs` 3.2 wheel.
- **License-inventory context:** our extension is GPL-3.0-or-later (ADR-0005);
  the SolveSpace row in component-adoption-matrix.md is `evaluate` with
  "GPL-3.0 (verify)"; this document supplies that verification's raw evidence.

## 1. Provenance table (every evaluated artifact)

| Artifact | Version / pin | Where obtained | sha256 / size |
|---|---|---|---|
| CAD_Sketcher source | tag `v0.32.1` → `e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4` (2026-09-28) | github.com/hlorus/CAD_Sketcher (fetch-upstream.sh, gitignored checkout) | tag object `6a5a34001efcdec05381b6f419cc4d0394a24ab5` |
| Official release ZIP (linux_x64) | 0.32.1 | releases/download/v0.32.1/CAD_Sketcher-0.32.1-linux_x64.zip | `c679cccd8ae955c440787e6be4a8eaebfb77cb1909eb8de04ffc182e97774541`, 13,968,966 bytes |
| slvs wheel (evaluated binary) | 3.2 cp313 manylinux x86_64 | in-repo `wheels/…cp313…whl` at the pin | `9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80`, 2,861,309 bytes |
| slvs wheels (all 10 in-repo) | 3.2 | in-repo at the pin | **10/10 byte-identical to PyPI `slvs` 3.2 files** (digests cross-checked, results/license-supply-chain.json) |
| slvs sdist (license/source evidence) | 3.2 | pypi.org (slvs-3.2.tar.gz) | `cf7c00fb17a2d100df7cfa80db5e04c7ec16e6093b3d9a74402f001043550a9b`, 7,204,982 bytes |
| SolveSpace source (of the solver) | commit `477d4c87ca51b9727fbc0765cbd94253c3968b8b` (2026-03-16, Paul Kahler, "Update CHANGELOG.md") | embedded in the sdist via `.git/HEAD` (pyproject `sdist.include = [".git/HEAD", ".git/refs"]`); provenance confirmed by `git fetch --depth 1` of that SHA from solvespace/solvespace | — |
| Eigen (statically compiled into the .so) | gitlink `3147391d946bb4b6c68edd901f2add6ac1f31f8c` at solvespace 477d4c8 | submodule `extlib/eigen` → gitlab.com/libeigen/eigen | license text **NOT verified at pin** — blocker (§9) |
| mimalloc (statically linked into the .so) | gitlink `f81bf1b31af819a31195e08f9546dc80f8931587` at solvespace 477d4c8 | submodule `extlib/mimalloc` → github.com/microsoft/mimalloc | LICENSE fetched at that SHA: MIT |
| Blender runtime (host) | 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15) | /home/z/runtime/blender-5.2.2-linux-x64 | bundled Python 3.13.13 |

## 2. The addon (hlorus/CAD_Sketcher v0.32.1) — license evidence

1. `blender_manifest.toml:12`: `license = ["SPDX:GPL-3.0-or-later"]`.
2. `LICENSE` (repo root, 674 lines): the full **GNU GPL v3** text. It contains no
   "version 3 only" restriction and no "or later" grant of its own — the grant is
   the manifest's SPDX expression. (Byte-differs from the solver's COPYING.txt only
   in the FSF-URL variant; both are canonical GPLv3 texts.)
3. No per-file SPDX/copyright headers exist in the addon's Python sources
   (grep over all 356 files finds none — see audit-upstream.md §4).
4. One copied third-party module: `units.py:1-2` — "Code from MeasureIt_ARCH, see:
   https://github.com/kevancress/MeasureIt_ARCH/blob/development/measureit_arch_units.py".
   - Upstream file header (fetched at branch `development`): "##### BEGIN GPL
     LICENSE BLOCK ##### … GNU General Public License … version 2 … or (at your
     option) any later version." → **GPL-2.0-or-later**.
   - MeasureIt_ARCH repo `LICENSE`: "MeasureIt_ARCH Copyright (C) 2020 Kevan Cress,
     Antonio Vazquez … GNU General Public License … version 3 … or (at your
     option) any later version." → repo-level GPL-3.0-or-later.
   - The copy shipped in CAD_Sketcher **drops the GPL license block**, keeping only
     the URL comment. GPL-2.0+ code is compatible with the addon's GPL-3.0+; the
     dropped notice is upstream's compliance gap (and an obligation we inherit if
     we ever derive from that file).

**Factual statement:** the addon distributes as GPL-3.0-or-later (manifest SPDX +
GPLv3 LICENSE file); the units.py content is GPL-2.0-or-later-derived and remains
GPL — attribution/gap noted.

## 3. The solver binary — supply chain, step by step

### 3.1 The PyPI `slvs` package has no visible source repo — identified from its own sdist

`pypi.org/pypi/slvs/json` → `info.project_urls: null`, `home_page: None`,
`author_email: "Koen Schmeets <koen@schmeets.de>"`, summary "SolveSpace solver
wrapped with Cython". Release 3.2 uploaded 2026-03-23 (48 wheels for cp37…cp313 +
sdist). **No project-URL pointer to source.**

The sdist **deliberately embeds git provenance** — `pyproject.toml`:

```toml
[tool.scikit-build]
sdist.include = [".git/HEAD", ".git/refs"]
```

and inside the sdist:

```
slvs-3.2/.git/HEAD           = 477d4c87ca51b9727fbc0765cbd94253c3968b8b
slvs-3.2/.git/refs/tags/v3.2 = 477d4c87ca51b9727fbc0765cbd94253c3968b8b
```

`git fetch --depth 1 origin 477d4c8…` from **solvespace/solvespace** succeeds:
commit exists upstream, author `Paul Kahler <14852918+phkahler@users.noreply.github.com>`,
2026-03-16 14:16:51 -0400, "Update CHANGELOG.md". The sdist tree IS the solvespace
repo layout (`src/`, `exposed/`, `include/slvs.h`, `python/`, `CMakeLists.txt`,
README "This repository contains the source code of SolveSpace…").

**Conclusion (factual):** the `slvs` PyPI project's source is **upstream
solvespace/solvespace itself**, at `477d4c8`, with the Python binding maintained
in-tree (`python/slvs/` + `src/slvs/lib.pyx`, built by `.github/workflows/python.yml`).
It is not a third-party fork; Koen Schmeets (the PyPI author-email) is a solvespace
committer — he created the commit that the `v3.2` tag points to today.

**Tag drift (recorded):** solvespace's `v3.2` tag currently resolves to
`27b6a080c8b669421bd4d444650c3b8eddec5687` ("fix windows single_core paths",
Koen Schmeets, 2026-03-26) — created **after** the 2026-03-23 PyPI upload;
`477d4c8` is an ancestor of `27b6a08` (verified `git merge-base --is-ancestor`).
The PyPI artifacts correspond to **477d4c8**; the sdist's embedded refs prove the
tag pointed there at build time.

**Not the same thing:** PyPI `py-slvs` 1.0.6 (project URL realthunder/slvs_py,
author "Zheng, Lei") is a **different, older binding** — CAD_Sketcher's
`docs/content/code_docs.md` references it historically ("the Python binding of
[py-slvs]"), but nothing in v0.32.1 ships or imports `py_slvs`; the shipped module
is `slvs` 3.2. Recorded to prevent conflating the two packages.

### 3.2 Binary composition of `slvs/…/solvespace.so` (9,834,944 bytes)

Built by the in-tree workflow (`.github/workflows/python.yml` +
`[tool.scikit-build] cmake.define`): `ENABLE_GUI=OFF`, `ENABLE_CLI=OFF`,
`ENABLE_TESTS=OFF`, `FORCE_VENDORED_Eigen3=ON`, `ENABLE_LTO=ON`,
`ENABLE_PYTHON_LIB=ON`; wheel generator "scikit-build-core 0.12.2"
(dist-info WHEEL), tags `cp313-cp313-manylinux_2_17_x86_64` +
`manylinux2014_x86_64`.

| Component | License (evidence) | How it enters the .so |
|---|---|---|
| SolveSpace solver core (`src/*.cpp`: `system.cpp`, `constraint.cpp`, `entity.cpp`, `expr.cpp`, …) | GPL-3.0-or-later (§3.3) | compiled in |
| Exposed C API (`src/slvs/lib.cpp`, `include/slvs.h`) | same (file headers: `include/slvs.h:9` "Copyright 2009-2013 Jonathan Westhues", no exception text) | compiled in |
| Cython binding (`src/slvs/lib.pyx`, module name `solvespace`) | **no per-file license header** (`lib.pyx:1` is `#cython: language_level=3`); repo license applies; the pyproject MIT classifier is the only contrary claim (§3.4) | compiled in |
| Eigen | MPL-2.0 (Eigen's own licensing; **text not verified at pin** — §9 blocker) | header-only, compiled in: solvespace `CMakeLists.txt:243-245` — "Using in-tree Eigen" → `EIGEN3_INCLUDE_DIRS ${CMAKE_SOURCE_DIR}/extlib/eigen`, forced by pyproject `FORCE_VENDORED_Eigen3=ON` |
| mimalloc | MIT — `LICENSE` at pin `f81bf1b…`: "MIT License / Copyright (c) 2018-2025 Microsoft Corporation, Daan Leijen" | statically linked: `src/slvs/CMakeLists.txt` — `target_link_libraries(slvs-interface INTERFACE slvs-solver mimalloc-static)`; built in-tree (`CMakeLists.txt:218-236` "Using in-tree mimalloc", `MI_OVERRIDE OFF`, `add_subdirectory(extlib/mimalloc EXCLUDE_FROM_ALL)`) |

GUI-side third-party components (Bitstream Vera font — the only entry of
`THIRD_PARTIES.txt`; 3Dconnexion SpaceWare SDK headers `extlib/si/…` incl.
`siapp.lib`; ANGLE, cairo, freetype, libpng, pixman, zlib, libdxfrw submodules) are
**excluded from the wheel build**: every consumer sits under `if(ENABLE_GUI …)` /
`if(ENABLE_GUI OR ENABLE_CLI)` in `CMakeLists.txt` (SpaceWare: lines 351-384; the
wheel sets GUI=CLI=OFF).

### 3.3 SolveSpace's actual license terms (verbatim, at `477d4c8`)

`README.md:355-356` (## License):

> SolveSpace is distributed under the terms of the [GPL v3](COPYING.txt) or later.

`CONTRIBUTING.md:20-21`:

> SolveSpace is licensed under the GPLv3 or later and any contributions
> must be made available under the terms of that license.

`COPYING.txt` = the full GNU GPL v3 text (675 lines; title block:

```
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc. <http://fsf.org/>
```

) with **no appended exception or permission-of-any-kind clause** — the file ends
with the standard GPL how-to-apply section ("…use the GNU Lesser General Public
License instead of this License."). A grep for "special exception|as a special"
across `src/`, `exposed/`, `include/`, `python/` finds **no linking exemption
anywhere** (the single hit, `src/style.cpp:353`, is a comment about entity styles).
Per-file headers are bare copyright notices, e.g. `src/system.cpp:5`:
"Copyright 2008-2013 Jonathan Westhues."

**This answers the "GPLv3 with special exception?" question: NO exception exists in
the files.** Unlike OCCT (LGPL + exception), linking the SolveSpace solver into a
larger work places the combined work under the GPL. This is the single most
consequential licensing fact for the M3 constraint-solver decision.

### 3.4 The METADATA-vs-COPYING inconsistency (explicit record)

The wheel's own metadata contradicts its own bundled license text:

| Source | Says | Path |
|---|---|---|
| Wheel METADATA | `Classifier: License :: OSI Approved :: MIT License` | `slvs-3.2.dist-info/METADATA` (from `pyproject.toml:15` classifier of the same text — the pyproject has **no** `license` field, so the classifier is the only machine-readable license claim) |
| Wheel license file | the **GPLv3 full text**, byte-identical to solvespace's `COPYING.txt` (sha256 `ca372a7d92560b1fa9f6d832b440e8bcd62d9adfa8870c98287deab66d98310e`) | `slvs-3.2.dist-info/licenses/COPYING.txt` |
| Wrapped code | "GPL v3 … or later" (§3.3 quotes) | solvespace `README.md:356`, `CONTRIBUTING.md:20` |
| sdist PKG-INFO | same MIT classifier | `PKG-INFO:7` |

Factual reading (presented as evidence, verdict TL-owned): the .so is a compiled
derivative of GPLv3-or-later solver code, with no linking exception; the artifact
itself ships the GPLv3 text as its license; therefore **distribution of this wheel
is governed by GPL-3.0-or-later for the solver-derived whole** (MPL-2.0 Eigen and
MIT mimalloc are GPL-compatible contributions to that combined work). The MIT
classifier cannot govern the solver portion and is contradicted by the wheel's own
`licenses/COPYING.txt`; it is best explained as a metadata error by the binding
maintainer (the pyproject carries the same classifier). We treat the METADATA
classifier as unreliable and the COPYING.txt + source-repo statements as governing
evidence. Because the classifier exists, we record the discrepancy itself as a
**standing risk** (blocker §9): a downstream automated license scan (pip metadata
tooling) would report MIT.

### 3.5 What CAD_Sketcher re-distributes

The 10 wheels committed at `wheels/` are **byte-identical copies of the PyPI slvs 3.2
files** (10/10 sha256 match — verified, see results/license-supply-chain.json §checks).
The release pipeline never rebuilds wheels (release.yaml has no wheel step; the
manifest `wheels = [...]` makes Blender's `extension build` bundle them). Therefore
any distribution of the CAD_Sketcher extension distributes these GPL-3.0-or-later
binaries — consistent with the addon's own GPL-3.0-or-later manifest, and equally
binding on anyone else who distributes it.

## 4. Verification log (license-inventory.md §7 protocol)

- `2026-10-20 · CAD_Sketcher v0.32.1 LICENSE + blender_manifest.toml (pinned checkout) · license file read + manifest read · E1 (m3-eval) · GPL-3.0-or-later (high)`
- `2026-10-20 · solvespace/solvespace @477d4c8 COPYING.txt/README.md:355-356/CONTRIBUTING.md:20-21 (from slvs-3.2 sdist, sha256-verified against PyPI) · license file read + repo statements · E1 (m3-eval) · GPL-3.0-or-later (high); NO linking exception (verified by full read + grep)`
- `2026-10-20 · slvs-3.2 wheel dist-info METADATA vs licenses/COPYING.txt (pinned wheel) · metadata vs license-file comparison · E1 (m3-eval) · INCONSISTENT: classifier MIT vs shipped GPLv3 text (high confidence in the inconsistency itself)`
- `2026-10-20 · solvespace/solvespace @477d4c8 .gitmodules + CMakeLists.txt + src/slvs/CMakeLists.txt (sdist) · build-wiring read · E1 (m3-eval) · wheel .so = solver + Eigen (MPL-2.0) + mimalloc (MIT), statically linked (high)`
- `2026-10-20 · mimalloc LICENSE @f81bf1b (github.com/microsoft/mimalloc raw file at SHA) · license file read · E1 (m3-eval) · MIT (high)`
- `2026-10-20 · eigen COPYING.MPL2 @3147391d · NOT VERIFIED — gitlab raw endpoint Cloudflare-blocked in this sandbox; GitHub mirrors lack the commit · E1 (m3-eval) · MPL-2.0 unverified ((verify) blocker)`
- `2026-10-20 · MeasureIt_ARCH measureit_arch_units.py GPL block + repo LICENSE (branch development, raw files) · license file read · E1 (m3-eval) · units.py content GPL-2.0-or-later-derived; notice block dropped by upstream (high)`

Validity scope: verifications hold for the pinned versions exactly; upstream
changes (including solvespace's already-moved `v3.2` tag) invalidate them and
require re-verification (license-inventory.md §5/§7).

## 5. Host/extension context (facts only)

Our extension is GPL-3.0-or-later (ADR-0005); the host Blender is GPL-2.0-or-later
(blender.org). The SolveSpace row (component-adoption-matrix.md) is `evaluate`:
"Reference/alternative constraint solver … evaluate-only; no integration planned",
license "GPL-3.0 (verify)". This document supplies the verification evidence: the
solver is **GPL-3.0-or-later with NO linking exception** (§3.3) — the license
families differ materially from the PAR-area candidate PlaneGCS (LGPL, library
boundary possible). The TL-owned M3-entry comparison must weigh exactly that.

## 6. Reproduction

```bash
./experiments/cad-sketcher/fetch-solver.sh   # verifies the wheel digest at the pin
# solver source license evidence: download the PyPI sdist (fetch-solver.sh records
# its URL + sha256), or re-read from the pinned solvespace commit:
git init /tmp/ssprobe && git -C /tmp/ssprobe fetch --depth 1 \
  https://github.com/solvespace/solvespace.git 477d4c87ca51b9727fbc0765cbd94253c3968b8b
python3 experiments/cad-sketcher/scripts/gen_license_record.py  # -> results/license-supply-chain.json
```

## 7. OPEN QUESTIONS / BLOCKERS (none resolved by assumption)

1. **[BLOCKER — classification] slvs wheel METADATA says MIT, artifact ships GPLv3.**
   Evidence recorded (§3.4). Any adoption/derivation would need the discrepancy
   resolved with upstream (clarify the binding files' license, fix the classifier)
   before our license-inventory row can be written. Automated pip-metadata scanners
   would mis-report MIT — a supply-chain trap worth noting even for evaluate-only.
2. **[BLOCKER — verification] Eigen's license text was not verifiable at its pinned
   SHA** (gitlab.com/libeigen/eigen raw endpoint Cloudflare-blocked in this sandbox;
   GitHub mirrors do not contain commit `3147391d`). Eigen's MPL-2.0 status is
   universally documented but per §7 protocol the row needs the file read at the
   pin. Must be completed before any decision that ships the wheel.
3. **[OPEN — scope] The binding layer's own copyright status**: `src/slvs/lib.pyx`
   and `python/slvs/__init__.py` carry no copyright/license headers; if upstream
   ever clarifies that the *wrapper only* is MIT (as the classifier suggests), the
   .so would still be GPLv3+ as a combined work — but the per-file status matters
   for anyone extracting wrapper code patterns. Ask upstream / read future commits.
4. **[OPEN — drift] solvespace's `v3.2` tag moved after the PyPI upload**
   (477d4c8 → 27b6a08, 2026-03-26). The PyPI artifacts pin to 477d4c8 via the
   embedded `.git` refs; a future slvs release may re-tag the same way — provenance
   must always be taken from the embedded refs, not the tag.
5. **[NOTED — upstream compliance nit] CAD_Sketcher's `units.py` re-distributes
   MeasureIt_ARCH GPL-2.0-or-later code without the original license block**
   (only a URL comment remains). No action needed for evaluate-only work; if we
   ever adapt that file, the GPL block and attribution must be restored.

## 8. What we could NOT determine (and why) — honesty list

- **Eigen license text at the exact pin** — network-blocked (§7.2).
- **Whether Koen Schmeets' own wrapper contributions are intended as MIT** — no
  per-file headers exist; the only signal is the (contradicted) classifier; would
  need an upstream statement.
- **The license of `slvs` 3.2rc1** (the only other PyPI release) — not evaluated;
  irrelevant to the pin.
- **The solve-space.com website's license page** — not needed; the repo files govern
  and were read directly.
