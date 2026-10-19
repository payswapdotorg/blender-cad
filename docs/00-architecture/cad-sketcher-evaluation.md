# CAD Sketcher evaluation — decision record (m3-eval)

- **Status:** Evaluation complete. **No component is adopted; no release-manifest change; no product code touched.** Every decision below is evidence-backed by committed, reproducible experiments under `experiments/cad-sketcher/` (isolation rules per that lane's README, mirroring the TL2 SolidCraft lane). The decisions in §1/§4 and the license verdicts in §5 were **made and signed by the TL**; the evaluation worker (E1) transcribed them faithfully and supplied the evidence.
- **Owner:** evaluation worker E1 (Task ID m3-eval); **TL owns the decisions + license verdicts (signed)**
- **Date:** 2026-10-20 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)
- **Upstream evaluated:** `hlorus/CAD_Sketcher` @ release tag `v0.32.1` (tag object `6a5a340…` → commit `e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4`, 2026-09-28; the moving `latest` tag points at main `efd2551` and is never used as a pin). **Solver binary:** the in-repo wheel `slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` at the pin (sha256 `9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80`), byte-identical to the PyPI `slvs` 3.2 file; **solver source:** solvespace/solvespace @ `477d4c8` (proven via the sdist's embedded git refs; the solvespace `v3.2` tag drifted post-upload).
- **Experiment lane:** `tl1/cad-sketcher-evaluation` off main `a6a46f1` (M2 complete); commits `78f160d`, `bc4919d`, `7e487e7`, `0bf5ce7` + this record's phase-3 commit.

## 1. Executive decision

CAD Sketcher is a **well-engineered Blender-native parametric sketcher whose solver
diagnostics, edit model and supply chain do not meet our document model's M3
requirements, whose seam architecture we demonstrably reproduce better against `bcdoc`,
and whose UI/persistence stack is a second CAD application we must not adopt.** The
per-candidate dispositions (TL, verbatim):

| # | Candidate | Decision | One-line basis |
|---|---|---|---|
| 1 | CAD Sketcher (the add-on) as a product component | **REJECT** | It is a complete second CAD application: its own PropertyGroup persistence layer (a second document model — mission boundary), Blender-curves-as-entity-store (upstream implementation detail; bcdoc stays authoritative), a full UI stack (stateful_operator framework, gizmos, panels) that must not be ported, and a headless-fragile operator surface (3/16 workflow steps cannot run headless; one crashes in its UI tail). Nothing is adopted or bundled; the runtime manifest is untouched. |
| 2 | slvs/SolveSpace solver binary (the bundled wheel) as the in-product PAR-area solver | **REJECT (evidence-backed)** | Measured grounds in §4.1: decisive diagnostics failure on exactly-redundant systems; no mutation API / no incremental solving (every edit = full rebuild + re-solve, ~O(N^2.2) scaling); one-sided underconstrained motion; a defective supply chain (MIT-classifier-vs-GPLv3 trap, committed-binary reproducibility, tag drift, stale .pyi, broken distance_proj, unexported mark_dragged, Beta-declared binding); linux-aarch64 platform gap; GPLv3-or-later with NO linking exception (license acceptable-but-costly for our GPL-3.0-or-later extension — NOT the functional reason for rejection). |
| 3 | SolidCraft solver crate | **UNCHANGED: adapt/port, gated** (TL2's candidate 1 record stands; its gates: PlaneGCS comparison on identical fixtures; Rust-cdylib packaging review; unicode-ident verification; FFI-vs-port decision) | Not re-decided by this evaluation. |
| 4 | PlaneGCS | **remains the incumbent candidate (ADR-0002); INSUFFICIENT EVIDENCE today** on the identical-fixture comparison | That head-to-head run is the remaining M3-entry gate work for the solver decision. |
| 5 | CAD Sketcher as reference material | **ADAPT (design) / REFERENCE (specific patterns)** — design-level only, no code | The bcdoc-first seam demonstrated in experiment B (adapt into the M3 parametric design); curve_solver's failed-constraint marking + float32-compare-before-write-back, the deferred needs_solve update path, workplane math, the source/body split with live GN modifiers, auto-constraint UX as future research (reference); the implied-redundancy gating workaround (issue #674) recorded as a DIAGNOSTIC lesson, NOT adopted as a pattern. Details in §4.3. |

**Recommended solver path (TL, verbatim):** Reject CAD Sketcher/SolveSpace as a
dependency. Continue the M3-entry solver decision between the two remaining candidates
behind explicit gates: (a) PlaneGCS vs SolidCraft-solver head-to-head on the
W1-identical fixture corpus (now committed as
`experiments/cad-sketcher/fixtures/solver/cases.json` — the canonical shared fixtures);
(b) PlaneGCS license verification (LGPL row, license-inventory); (c) packaging review of
each candidate's distribution path (PlaneGCS vendored C++/LGPL vs SolidCraft Rust
cdylib) under the still-unverified extension-platform policy — the same gate that
constrains OCCT/OCP; (d) then a TL decision record choosing the PAR-area solver, with
the experiment-B seam as the integration architecture either way. OCCT/OCP kernel work
(ADR-0002) proceeds independently and is NOT affected by this evaluation. No
AutoCAD-parity claim is made or implied from constrained-sketch success.

## 2. Source audit summary

Full detail in `experiments/cad-sketcher/findings/{audit-upstream,
license-supply-chain}.md` (+ machine-readable `results/upstream-audit.json`,
`results/license-supply-chain.json`); summary:

- **Release facts:** pin = newest versioned release `v0.32.1` (tag `6a5a340` → `e7db7e6`;
  `latest` = moving pointer at main `efd2551`, never a pin). Release pipeline:
  ruff gate → tag/manifest check → `blender --command extension validate` →
  `extension build --split-platforms` → per-platform ZIPs to GitHub Releases +
  extensions.blender.org (moderator) + self-hosted `stable/latest` index.json channels.
  **Wheels are never rebuilt by CI** — all 10 slvs wheels are committed in-repo and are
  byte-identical (sha256) to the PyPI `slvs` 3.2 files (10/10 verified). Manifest:
  GPL-3.0-or-later, blender_version_min 5.0.0, platforms windows-x64/macos-x64/
  macos-arm64/linux-x64, wheels cp311+cp313 only.
- **Structure map:** `model/` (constraint classes + the dual entity/curve data model),
  `curve_solver.py` (the solver seam — rebuild-every-solve), `operators/` +
  `stateful_operator/` framework, its own `serialize.py` + `SlvsEntities`/`SlvsConstraints`
  PropertyGroups (a **second document model**), draw units (`drawing/`, `gizmos/`).
  Zero per-file SPDX/copyright headers; exactly one vendored module (`units.py` from
  MeasureIt_ARCH, GPL block dropped — upstream hygiene finding, recorded).
- **License/supply chain (the decisive license fact):** SolveSpace is **GPLv3-or-later
  with NO linking exception** — verified from the wheel's own `licenses/COPYING.txt`
  (plain GPLv3; the "exception"-looking text is standard GPL §7 template language, not a
  grant) + upstream `README.md:356` / `CONTRIBUTING.md:20-21` @ `477d4c8`. The wheel
  **METADATA claims "License :: OSI Approved :: MIT License"** while shipping the GPLv3
  text — a formal inconsistency recorded as a scanner trap; METADATA treated as
  unreliable. Binary composition: solver + headerless Cython wrapper + Eigen (MPL-2.0 @
  `3147391d`, license text **unverifiable from this sandbox — explicit (verify)
  blocker**) + mimalloc (MIT @ `f81bf1b`, verified). Provenance policy: solvespace's
  `v3.2` tag moved AFTER the PyPI upload — take slvs provenance from the sdist's
  embedded `.git` refs (= `477d4c8`), never from tags.

## 3. Experiments run (all under `experiments/cad-sketcher/`, reproducible via the lane's fetch scripts + one-command drivers)

| Experiment | Mission requirement | Result headline | Evidence | Reproduce |
|---|---|---|---|---|
| A — solver conformance (phase 2a) | constraints, DOF, dimensions, convergence, failure, determinism, scale | 17 W1-identical fixtures (9 identical / 8 adapted, per-case equivalence marks) + 6 PAR-coverage probes: 115 checks, **112 pass / 3 fail** — the 3 failures are the honest redundancy finding (the exposed solver FAILS exactly-redundant systems); bitwise determinism in-process 5× and cross-process 3×; failure leaves geometry bit-identical (copy-solve); scale medians 0.19/0.84/3.05/16.1 ms @ N=10/50/100/200 (~O(N^2.2)); PAR-12 coverage matrix (8 direct, tangent endpoint-only, concentric/radius/distanceX-Y derived) | `results/solver-conformance.json`, `fixtures/solver/cases.json` (the canonical shared fixtures), `findings/solver-conformance.md` | `PYTHONPATH=… python3.13 scripts/gen_solver_cases.py` |
| B — bcdoc seam (phase 2b) | authoritative-document mapping without a second store / identity / undo-redo / persistence / untracked mutations / dependency integrity | **26/26 checks on the REAL bcdoc** (read-only): stateless solver service; apply-back via real journaled transactions; undo bit-exact; ids/handles/selection stable; save→fresh load digest-equal; dimension edit on reopened doc exact; failed solve writes NOTHING; 6-item bcdoc gap list (proposed bcdoc/3 SketchTable) | `results/bcdoc-seam.json`, `findings/bcdoc-seam.md` | `python3.13 scripts/gen_bcdoc_seam.py` |
| C — parametric workflow (phase 2b) | workplanes, dimensions, sketch updates, extrusion/revolution, dependent rebuilds; separate reusable from UI | 16 recorded steps, 13 headless-ok (3 viewport-event steps recorded headless-impossible incl. one UI-tail crash); exact solve + exact dimension-edit→dependent-rebuild via the addon's own model APIs; extrude MECHANISM headless-proven (GN group 85 nodes + body + modifier → 6 verts/5 faces); reusable-vs-UI separation table | `results/parametric-workflow.json`, `findings/parametric-workflow.md` | `BLENDER_USER_RESOURCES=<scratch> blender --background --python scripts/runtime/parametric_workflow_probe.py` |
| D — runtime & distribution (phase 2b) | platform availability, ABI, size, native deps, startup, error handling, distribution obligations | 10/10 checks: **linux-aarch64 missing** (4/5 of our target platforms); cp311+cp313 (no cp312 — fine); release ZIP 13,968,966 B; 10 wheels 14,880,583 B; installed 17,022,892 B (16.2 MiB); `ldd` = standard glibc runtime only (Eigen/mimalloc compiled in; manylinux_2_17 → glibc ≥ 2.17); startup +0.125 s median (phase 1); error + obligations records | `results/runtime-distribution.json`, `findings/runtime-distribution.md` | `python3 scripts/gen_runtime_distribution.py` |
| Phase 1 — upstream + license + runtime compat | audit + supply chain + pinned-runtime compatibility | 11+11+6 checks all green: pin verified, 10/10 wheel PyPI identity, single-vendored-module finding, license record with verbatim quotes, cp313 import + smoke solve exact on Blender 5.2.2's Python 3.13.13, official ZIP installs+enables 6/6, startup +0.125 s | `results/upstream-audit.json`, `results/license-supply-chain.json`, `results/runtime-compat.json`, `findings/{audit-upstream,license-supply-chain}.md` | lane fetch scripts + `scripts/gen_*.py` |
| E — regression (phase 3) | no M2 regression | **1127 passed / 0 failed** (`/home/z/.venv/bin/python3 -m pytest modules tests -q`); package check green; repo-consistency 6/6; Blender battery NOT re-run (zero production-facing files changed — §10) | §10 below | §3.1 commands |

## 4. Candidate scorecard

### 4.1 slvs/SolveSpace solver binary (the bundled wheel) as the in-product PAR-area solver → **REJECT (evidence-backed)**

Measured grounds (TL, verbatim from the decision text; each cites the result file):

- **Diagnostics (decisive):** the exposed solver FAILS exactly-redundant systems
  (REDUNDANT_DIDNT_CONVERGE) instead of solving-and-naming — measured on the
  W1-identical fixture (`results/solver-conformance.json`:
  `rect_redundant_duplicate_dimension`, 3 checks failed honestly); the addon itself must
  gate implied-redundant constraints to avoid it (issue #674, `curve_solver.py:335-352`).
  Our document-model §3.8 requires over/under-constrained diagnostics reported to the
  user; SolidCraft's evidence (TL2 w1) demonstrated superior diagnostics (redundant list
  + determined_by + failing names + solves-anyway). Also: bad-list granularity is
  failure-point reporting, not conflict diagnosis (measured: triangle_edit_unsolvable
  names only d2 where SolidCraft names k3+k4+k5; coincident_plus_distance names only d1).
- **No mutation API / no incremental solving:** every edit = full system rebuild + full
  re-solve (the addon's own path, `curve_solver.py`); measured ~O(N^2.2) scaling (16.1 ms
  median @ N=200 entities, 2-CPU sandbox; warm re-solve not cheaper —
  `results/solver-conformance.json` scale_performance); document-model §3.8 wants
  "incremental solves over dirty subgraphs".
- **Underconstrained motion semantics:** one-sided closure
  (`line_horizontal_only` closes onto y=1.0 via the substitution path,
  `system.cpp:481-483`) vs SolidCraft's least-motion ~0.5/0.5 split — less predictable
  editing UX; a semantic divergence, not a defect (recorded as comparison datum).
- **Supply chain:** wheel METADATA claims MIT while shipping GPLv3 COPYING.txt (scanner
  trap — verified, `results/license-supply-chain.json`); wheels are committed in-repo and
  never rebuilt by CI (reproducibility relies on committed binaries); solvespace v3.2 tag
  drifted post-upload (provenance must come from sdist-embedded .git refs = `477d4c8`);
  stale `.pyi` (declares result members the binary never returns); `distance_proj`
  aborts the process; `mark_dragged` unexported; binding self-declared Beta
  (Development Status :: 4 classifier).
- **Platform gap:** no linux-aarch64 wheel (4/5 of our target platforms;
  `results/runtime-distribution.json`).
- **License:** GPLv3-or-later, NO linking exception (verified from the wheel + upstream
  COPYING). NOT a compatibility blocker for our GPL-3.0-or-later extension (ADR-0005) —
  but a real obligation set for any hypothetical distribution (corresponding source:
  solvespace@`477d4c8` + Eigen@`3147391d` + mimalloc@`f81bf1b`; license texts; notices),
  and the Eigen-at-pin license text remains unverifiable from this sandbox (open
  blocker). The mission's "no GPL adoption until reviewed" boundary is hereby SATISFIED
  as a review — the GPL is acceptable-but-costly; the functional evidence is what
  rejects the candidate.
- **Honesty note (TL):** 16 ms @ 200 entities is not slow in absolute terms; the
  rejection rests primarily on diagnostics + no-incremental + supply-chain + platform,
  with the performance shape as supporting evidence.

**What is genuinely good and recorded** (fairness, from experiment A): exact
fully-constrained solves (1e-6 bar incl. analytic triangle branches, slot exactly),
bitwise determinism in- and cross-process, transactional failure semantics (copy-solve,
write-back-only-on-success — geometry bit-identical on every failure, same observable as
SolidCraft's explicit restore), a direct API for 8/12 PAR kinds, and 38 total exposed
constraint types with a raw escape hatch.

**Next action if ever revisited (no adoption path unless §1's condition holds):** the
blockers above must be re-reviewed, not waived — i.e. only if PlaneGCS AND SolidCraft
both fail their gates; the required fixes would include an aarch64 Linux wheel, a
corrected METADATA classifier, a redundancy-solving path with proper diagnostics, and an
incremental-solve story.

### 4.2 CAD Sketcher (the add-on) as a product component → **REJECT**

It is a complete second CAD application: its own PropertyGroup persistence layer
(`model/group_*.py` + `serialize.py` — a second document model; mission boundary),
Blender-curves-as-entity-store with 128-bit UUID attribute machinery
(`utilities/curve_data.py` — upstream implementation detail; bcdoc stays authoritative),
a full UI stack (`stateful_operator/` 3.2k LOC framework, `gizmos/`, `drawing/`, `ui/`,
keymaps) that must not be ported, and a headless-fragile operator surface (3/16 workflow
steps cannot run headless; `slvs_add_sketch_on_plane` crashes in its UI tail —
`operators/utilities.py:190`; `results/parametric-workflow.json`). Nothing is adopted or
bundled; the runtime manifest is untouched.

### 4.3 CAD Sketcher as reference material → **ADAPT (design) / REFERENCE (specific patterns)** — design-level only, no code

- **Adapt into the M3 parametric design:** the bcdoc-first seam DEMONSTRATED in
  experiment B (`results/bcdoc-seam.json`, 26/26; `findings/bcdoc-seam.md`): bcdoc
  authoritative; solver = stateless compute service; mutate-only apply-back via real
  journaled transactions; write-nothing-on-failure; ids/selection stable; save/reopen
  digest-equal. **The seam is solver-agnostic by construction — it binds whichever
  solver wins the M3 gate.** The bcdoc gap list (constraint/SketchTable, junction
  identity, workplane record, driving-dimension records incl. reference-dim gating,
  solve-report records) becomes the M3 schema work items.
- **Reference:** `curve_solver.py`'s failed-constraint marking
  (`curve_solver.py:329-361`) + float32-compare-before-write-back
  (`curve_solver.py:44-54,494-530`); the deferred `needs_solve` update path
  (`handlers.py:186-206` + `refresh_curve_geometry`); workplane math
  (`curve_solver.py:90-138`); the source/body split with live GN modifiers (their 3D
  answer at 0.32.1 — `utilities/body.py:1-9` — informative for our kernel-bound M3 3D
  work, not a commitment); auto-constraint UX (0.32 feature) as future research.
- The implied-redundancy gating workaround (issue #674) is recorded as a **DIAGNOSTIC
  lesson (what our solver must do better), NOT adopted as a pattern** — a solver that
  must be shielded from redundant input by policy is a diagnostics defect in our
  document-model terms.

**Context rows (not re-decided here):** SolidCraft solver crate — UNCHANGED
adapt/port, gated (TL2 record stands: PlaneGCS comparison on identical fixtures,
Rust-cdylib packaging review, unicode-ident verification, FFI-vs-port decision).
PlaneGCS — remains the incumbent candidate (ADR-0002); INSUFFICIENT EVIDENCE today on
the identical-fixture comparison; that head-to-head run is the remaining M3-entry gate
work for the solver decision.

## 5. License and supply-chain record (input rows for license-inventory; verdicts TL-signed)

Rows are added in `license-inventory.md` §2.2; the SolveSpace row is refreshed there.
Summary of the TL-signed verdicts (this session):

- **CAD Sketcher addon:** GPL-3.0-or-later verified (manifest SPDX + LICENSE at
  v0.32.1 @ `e7db7e6`) — compatible with our extension context (ADR-0005), **NOT
  adopted**. `units.py` MeasureIt_ARCH vendored-with-license-block-dropped = upstream
  hygiene finding, recorded, irrelevant to adoption.
- **slvs 3.2 wheel terms:** GPLv3-or-later (COPYING.txt + upstream
  README/CONTRIBUTING @ `477d4c8`); the wheel METADATA MIT classifier is
  WRONG-or-at-best-partial (the author's wrapper contribution at most) — recorded as a
  formal inconsistency, METADATA treated as unreliable. Compatible-with-extension fact
  recorded, but the candidate is REJECTED on functional evidence (not license).
  Obligations for any hypothetical distribution: corresponding source pins
  (solvespace@`477d4c8` + Eigen@`3147391d` + mimalloc@`f81bf1b`), license texts,
  notices.
- **SolveSpace row refreshed:** GPLv3-or-later verified at `477d4c8`, no linking
  exception — supersedes the old "(verify)" tag.
- **Eigen @ `3147391d`:** MPL-2.0 — stays an explicit **(verify) BLOCKER** (text
  unverifiable from this sandbox; MPL-2.0 is known GPL-3-compatible in general, but the
  pin-specific text stays unverified).
- **mimalloc @ `f81bf1b`:** MIT verified.

Verification-log lines (license-inventory §7 protocol) are recorded in §2.2 of the
inventory: 2026-10-20 · wheel dist-info METADATA vs licenses/COPYING.txt + addon
manifest/LICENSE at the pin + solvespace@477d4c8 COPYING/README/CONTRIBUTING + mimalloc
LICENSE @ f81bf1b · file reads (TL verified the decisive facts directly from the
artifacts this session) · TL · as per the signed verdicts above.

## 6. Limitations of the evaluation itself

1. Single 2-CPU sandbox host; all timing evidence is shape-within-host (recorded per
   case; the scale curve is the finding, never absolute ms; the 16 ms @ N=200 number is
   host-specific — the honesty note in §4.1 stands).
2. Python-call overhead: solver timing wraps only the `solve_sketch` call, but the slvs
   binding is Cython-over-C while TL2's SolidCraft evidence ran in-process Rust —
   cross-solver absolute timings are NOT comparable and were never used as checks.
3. **No PlaneGCS head-to-head** — that is the M3-entry gate (§1 recommended path),
   not this evaluation's; the fixture corpus is committed to make it runnable.
4. 3 of 16 workflow steps are headless-blocked (viewport-event tools) — each recorded
   with its exact error and a working non-UI equivalent (model APIs / mechanism probes).
5. Constraint-kind exercise: the conformance harness exercised 8 direct + 5
   derived/observed of the 38 exposed slvs types (the PAR-12 plus tangency/redundancy
   paths); no cubic/spline/3D-heavy or hostile-input corpora — recorded for any future
   re-review.
6. The slvs API surface measured is the *exposed binding*, not SolveSpace's internal
   GUI solver paths (which differ, e.g. allowRedundant); conclusions bind to the
   shipped binary any integration would use.
7. Blender 5.2.2 acceptance battery not re-run — zero production-facing files changed
   (§10); the battery's standing committed evidence remains authoritative.

## 7. Answers to the mission's questions

- **Could a constrained sketch map into bcdoc without a second store / identity /
  undo-redo / persistence / mutation / dependency problems?** **Yes — demonstrated**
  (experiment B, 26/26): bcdoc stays the single authoritative store; the solver is a
  stateless service; apply-back rides real transactions; undo/redo/persistence/edit
  integrity all verified, with ids/selection stable and failure writing nothing. The
  gaps are schema items (constraint records, junction identity), not architectural
  blockers.
- **Which upstream workflow parts are useful?** The solver-seam design,
  failed-constraint marking, float32 compare-before-write-back, deferred update
  triggering, workplane math, and the source/body split with live GN modifiers
  (experiment C's separation table); the full UI, stateful-operator framework and the
  PropertyGroup persistence layer are **not** useful to us — they are the second
  application we exclude.
- **Runtime/distribution facts?** 4/5 target platforms (linux-aarch64 missing);
  cp311+cp313 ABI matching Blender-embedded Pythons; 16.2 MiB installed; standard
  glibc-only native deps; +0.125 s startup; GPLv3-or-later obligations with the
  METADATA-MIT trap (experiment D).
- **Is the solver a fit for the PAR area?** No (§4.1) — on diagnostics,
  no-incremental, supply chain, platform; performance shape and license obligations as
  supporting evidence; the seam and fixtures transfer to the remaining candidates.

## 8. Recommended next actions (M3-entry work items — no dependency adoptions)

1. **The head-to-head gate:** PlaneGCS vs SolidCraft-solver on the committed
   W1-identical fixture corpus (`experiments/cad-sketcher/fixtures/solver/cases.json`)
   — both solvers, same fixtures, recorded envelopes.
2. **PlaneGCS license verification** (LGPL row, license-inventory) — the (verify) tag
   must be resolved before any vendoring decision.
3. **Packaging reviews** of both remaining candidates (PlaneGCS vendored C++/LGPL vs
   SolidCraft Rust cdylib) under the still-unverified extension-platform policy (the
   same gate that constrains OCCT/OCP).
4. **The bcdoc/3 schema items** from experiment B's gap list (constraint/SketchTable,
   junction identity, workplane record, driving-dimension records incl. reference-dim
   gating as a first-class flag, solve-report records) — M3 schema work, reviewable
   independently of the solver choice.
5. **TL decision record choosing the PAR-area solver** after (1)–(3), with the
   experiment-B seam as the integration architecture either way.

## 9. Explicitly excluded (with reasons)

- **The CAD Sketcher add-on wholesale** — second document model + full UI stack +
  Blender-curves-as-store (mission boundaries; §4.2).
- **Its PropertyGroup persistence layer and serialize.py** — a second authoritative
  store; bcdoc stays authoritative (experiment B's whole point).
- **The slvs/SolveSpace wheel as a dependency** — §4.1 (re-review, never waiver, and
  only if both remaining candidates fail).
- **Any kernel implication** — ADR-0002 (OCCT/OCP) proceeds independently and is NOT
  affected by this evaluation; no kernel claim arises from constrained-sketch success,
  and no AutoCAD-parity claim is made or implied.

## 10. Regression evidence (phase 3, experiment E)

- `/home/z/.venv/bin/python3 -m pytest modules tests -q` at the branch tip:
  **1127 passed, 0 failed** (identical to the M2 record; 369 warnings, pre-existing).
- `python3 scripts/build_extension.py --check`: **green** ("check OK:
  blender_cad-0.2.0.zip up to date (67 entries)").
- `python3 -m pytest tests/test_repo_consistency.py -q`: **6 passed**.
- Blender 5.2.2 acceptance battery: **NOT re-run — no production-facing file was
  touched**: `git diff main..HEAD --stat` (at commit time) =
  `experiments/cad-sketcher/**` + the four docs added by this record + the lane README
  edit only (actual stat: 28 files +11,414 insertions before phase 3; phase 3 adds only
  the docs listed). The batteries' standing committed evidence remains authoritative.
- Product tree untouched: `git diff main -- modules/` is empty; the 1127-test
  collection is unchanged.

## 11. References

- The m3-eval task lane: `experiments/cad-sketcher/README.md` (isolation +
  reproduction + ownership), `results/*.json` (envelope schema mirroring TL2),
  `fixtures/solver/cases.json` (canonical fixtures), `findings/*.md` (audit + 4
  experiment analyses).
- `docs/00-architecture/component-adoption-matrix.md` §4.3 (the new CAD Sketcher row),
  `docs/00-architecture/license-inventory.md` §2.2 (evaluation rows + SolveSpace
  refresh), `docs/30-process/completion-graph-cad-sketcher-evaluation.md`
  (ticks-with-evidence).
- TL2's record this lane mirrors: `docs/00-architecture/solidcraft-evaluation.md`
  (branch `origin/tl2/solidcraft-evaluation`, read-only reference).
- ADR-0002 (kernel — unaffected), ADR-0005 (extension licensing), ADR-0008 (M3 scope
  re-baseline), document-model-and-geometry-kernel.md §3.8 (PAR requirements).
