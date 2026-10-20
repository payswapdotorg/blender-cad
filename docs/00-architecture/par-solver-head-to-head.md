# PAR-area solver head-to-head — TL decision record

- **Status:** Head-to-head gate COMPLETE (m3-eval §8 items 1–3 + the TL
  decision record §8 item 5; SolidCraft-evaluation §4.1 gate (a)). **No
  component is adopted by this record; no release-manifest change; no product
  code touched.** Every measured claim below is backed by committed,
  reproducible evidence under `experiments/solver-h2h/` (this lane).
- **Owner:** TL1 (evaluation track); TL owns the product consequences
- **Date:** 2026-10-20 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)
- **Candidates measured (same corpus, same class of sandbox):**
  - **SolidCraft-solver** = `tangency-labs/solidcraft` `crates/sketch` @
    `3b4db52c10279251a068cfca5eb7447068bc28e7` (v0.16.2) — **TL2's exact pin**
  - **PlaneGCS** = FreeCAD `src/Mod/Sketcher/App/planegcs/` at tag
    `1.1.4` → `4fd3bf320d9566a27e60069fc8387448aaa3a094`, built standalone
    against eigen 3.4.0 (sha256-pinned release artifact)
  - **slvs** (SolveSpace) = the REJECTED baseline, quoted from m3-eval's
    committed envelope for reference columns only
- **Corpus:** `experiments/cad-sketcher/fixtures/solver/cases.json` — the
  canonical 23-case fixture set (17 W1-identical + 6 PAR coverage probes),
  consumed READ-ONLY by both harnesses; both transcriptions machine-verified.

## 1. Executive decision

**SolidCraft-solver is recommended as the PAR-area constraint solver** —
integrated behind the experiment-B seam (bcdoc-first, stateless compute
service, journaled apply-back — design-locked by the m3-eval record §4.3) —
**and PlaneGCS is not the primary.** This closes the head-to-head gate that
BOTH prior decision records named (m3-eval §8 item 1; SolidCraft-evaluation
§4.1 gate (a)) and endorses TL2's provisional recommendation with the gate
now measured. Concretely:

| # | Candidate | Decision | One-line basis |
|---|---|---|---|
| 1 | **SolidCraft-solver (crates/sketch)** | **RECOMMEND** — the PAR-area solver behind the seam, gated on the remaining non-conformance gates | the ONLY candidate that reproduces TL2's full W1 record AND solves+names the exactly-redundant fixture that rejected slvs (rect: dof 0, exact corners, redundant=[k8] + implied-by); 0.48 ms @ N=200 (~220× faster than PlaneGCS on the identical staircase); native value mutation with deterministic continuations; bitwise determinism both modes; 12-crate permissive closure, zero GPL, no native code |
| 2 | **PlaneGCS (FreeCAD 1.1.4)** | **NOT the primary — fallback + REFERENCE** | license verification PASSED (the (verify) is resolved — this lane), but conformance failed where it counts: the W1 slot lands at ~2.5e-5 (4 position checks fail at 1e-6) with a formulation-dependent diagnosis (dof 0 vs 2 vs 4 across probes on the SAME fixture), the exactly-redundant rect does not solve even through FreeCAD's full 4-step chain (SQP-augmented included), and a structurally-clean numerical failure carries NO named-constraint diagnostics; ~106 ms @ N=200 |
| 3 | slvs / SolveSpace | REJECTED (unchanged) | m3-eval §4.1 stands; with a measured winner the re-review conditions are moot for the primary slot; nothing here waives them |
| 4 | The experiment-B seam | **Integration architecture either way** (design-locked) | bcdoc stays the single authoritative store; the solver is a stateless service with journaled apply-back; this record changes the seam's TARGET, not its design |
| 5 | Kernel (ADR-0002 OCCT/OCP) | UNAFFECTED | no kernel claim arises from constrained-sketch results; PlaneGCS's LGPL notice obligations are now recorded facts, not blockers |

**What this record does NOT do:** adopt anything (the SolidCraft-solver's
remaining gates below are the adoption path), change the kernel direction,
touch bcdoc, adopt any SolidCraft UI/document-model/kernel component (TL2's
record governs those candidates; this record covers the SOLVER CRATE only),
or waive any recorded (verify).

## 2. The measured evidence (all committed under `experiments/solver-h2h/`)

| dimension | SolidCraft | PlaneGCS | slvs (baseline) |
|---|---|---|---|
| corpus checks | **131: 127 pass** / 4 (2 declared DOF + 2 extra rank diagnostics — all one root cause, §3.2) | 121: 112 pass / **9** | 115: 112 / 3 |
| W1-17 reproduction | **17/17** vs TL2's record (dofs, exact branches, failure surfaces) | 16/17 (slot at ~2.5e-5, not 1e-6) | documented (m3-eval) |
| rect_redundant (rejected slvs) | **SOLVED + named [k8] + implied-by** | failed (correct diagnosis [k6]/dof 0 — the attribution slvs could not make — but no solve through the full 4-step chain) | failed + misattributed |
| scale @ N=10/50/100/200 (staircase medians, 5 fresh processes) | **0.076 / 0.17 / 0.27 / 0.48 ms** | 0.21 / 2.2 / 11.8 / **106.3 ms** | 0.19 / 0.84 / 3.05 / 16.1 ms |
| determinism | bitwise 5× in-process + 3× cross-process (TL1 re-verified) | bitwise 5× + 3× | bitwise (m3-eval) |
| value mutation (no rebuild) | native (`set_value` + `solve_after_value_edit`, continuations ≤64; model.rs:370-389, solver.rs:1369-1371) | native (caller-owned `double*` datums; landed on exact analytic branches) | NONE (rejection pillar 2) |
| diagnostics | residuals, iteration counts, DOF+determined, implied-by, folds | DOF + conflict/redundant tags + dependent-params — but formulation/order-dependent on seamed systems (slot probes recorded) and empty on structurally-clean numerical failures | flag + bad list (often misattributed) |
| failure semantics | bitwise restore | bitwise restore (copy-solve, applySolution-on-Success) | bitwise restore |
| license (verified at pins) | **MIT OR Apache-2.0**, 12-crate closure, zero GPL, no native code (TL2 W3-b + this lane's re-cite) | LGPL-2.1-family (verbatim per-file record) + Eigen **MPL-2.0 verified at BOTH pins** (this lane cleared the m3-eval §9 blocker) + boost at pack time | GPLv3 — rejected on function |

Envelopes: `results/solidcraft-conformance.json`,
`results/planegcs-conformance.json`, `results/head-to-head.json` (the join),
`results/license-planegcs-eigen.json`; analyses in `findings/*.md`; the
comparison reading in `findings/head-to-head.md`.

## 3. Why PlaneGCS is not the primary (the honest failures, all measured)

1. **The exactly-redundant fixture does not solve.** With FreeCAD's complete
   fallback chain implemented verbatim (DogLeg → BFGS → LM → the
   SQP-augmented last resort, Sketch.cpp:4795-4905), every step returns
   Converged (minimized-not-zeroed): no write-back, corners stay at the rough
   input. SolidCraft solves the same fixture exactly and names the duplicate.
   PlaneGCS's DIAGNOSIS is the best of the three on this fixture (correct
   [k6], dof 0) — the diagnosis quality is real and is recorded as reference
   value — but diagnosis does not solve sketches.
2. **The W1 slot converges only to ~2.5e-5** under the corpus tolerance
   (1e-6), with a formulation-dependent diagnosis: the same fixture yields
   dof 0 (AngleViaPoint form, one addition order), dof 2 + 4 flagged
   (curve-level tangent form), dof 4 + 10 flagged (corpus order) — all three
   probe records are committed in the envelope. Its endpoint-tangency form
   (AngleViaPoint) additionally has a degenerate manifold (r→0 collapse)
   that the rough W1 seed falls into. The robust formulation (curve-level
   Line-Arc tangent + structural endpoint sharing) is what the envelope
   records.
3. **A structurally-clean numerical failure carries no diagnostics.** On
   triangle_edit_unsolvable (d1=55, discriminant<0), the diagnosis is clean
   (correct — no structural conflict exists), the solve fails, geometry is
   restored bitwise — and nothing names the violated constraints. slvs named
   its final-iterate violators; SolidCraft names k3/k4/k5 from its failure
   surface. For user-facing constraint diagnostics this is a real gap.
4. **Scale:** 106.3 ms vs 0.48 ms at N=200 on the identical staircase — the
   most one-sided dimension of the gate (SolidCraft decomposes via union-find
   over constraint blocks with block-diagonal Jacobians; planegcs re-runs
   full-system dense Newton with re-partitioning on every solve).

**PlaneGCS's retained value (recorded as REFERENCE):** the correct redundancy
attribution on the rect fixture (better than slvs, the actual rejection
evidence), the FreeCAD 1.1.4 translation patterns this lane documented with
citations (Sketch.cpp's endpoint-tangency formulation, the 4-step solver
chain, applySolution-on-Success, the Difference/P2PSymmetric/4-point-L2LAngle
mappings), and its status as the NAMED FALLBACK should SolidCraft's remaining
gates fail. The m3-eval §4.1 slvs re-review conditions continue to apply
unchanged if BOTH paths were ever to fail.

## 4. SolidCraft-solver's remaining gates (from TL2 §4.1 (b)–(d); NOT waived)

- **(a) head-to-head — CLOSED by this record** (won on every measured
  dimension).
- **(b) packaging review** — DONE as evidence
  (`findings/packaging-review.md`): the Rust cdylib path is administratively
  lighter (permissive closure, no boundary duties) and the extension-platform
  policy (verify) binds BOTH candidates equally (it binds the OCCT binding
  too — license-inventory §3). **The platform policy (verify) itself remains
  the shared, open gate at the first packaging milestone.**
- **(c) unicode-ident Unicode-3.0 FSF listing (verify)** — still open,
  metadata-level, tracked by TL2's record.
- **(d) port vs FFI** — an integration-time engineering decision; the
  12-crate closure is small enough to port, the cdylib path needs the Rust
  cross-toolchain (incl. linux-aarch64, which Rust covers natively — no
  wheel-gap of the slvs kind).
- **Adapter-level seam notes (recorded for the implementers, from this
  lane's honest failures):** zero-valued `distance_x/y` map to the crate's
  NATIVE `HorizontalPoints`/`VerticalPoints` forms (the literal unsigned
  mapping hides the constraint from rank analysis at dp=0 while the geometry
  still lands — the remedy is probe-verified: dof 0 + exact positions).

## 5. License-inventory consequences (TL-signed; rows updated by this record)

1. **PlaneGCS — (verify) RESOLVED:** LGPL-2.1-family, verified at the
   FreeCAD 1.1.4 pin from the actual files (all 11 per-file headers verbatim;
   the legacy "GNU Library General Public License … version 2 or later"
   wording recorded explicitly alongside the project-level LGPL-2.1 root
   LICENSE and the SPDX tags in sibling files). Compatible-with-shipping
   (library boundary + notice retention); **not the primary solver on
   measured functional grounds** — the license row's "blocking before
   vendoring" condition is satisfied and then mooted by the functional outcome.
2. **Eigen @ `3147391d` — the m3-eval §9 BLOCKER is CLEARED:** the exact
   solvespace gitlink commit is fetchable again (retested this lane after
   m3-eval's 403s — gitlab reachability recorded as intermittent, both
   outcomes committed) and its `COPYING.MPL2` is **byte-identical** to the
   eigen 3.4.0 release artifact's (sha256 `fab3dd6b…`, full MPL-2.0 text).
   The solvespace row's "Eigen-at-pin stays (verify) blocker" note resolves
   to a plain verified fact; the slvs REJECTION and its re-review conditions
   are unchanged (it was never a license rejection).
3. **Eigen 3.4.0 (this lane's build pin)** — MPL-2.0 verified at the release
   artifact (sha256-pinned Debian-pool mirror; the canonical gitlab is
   intermittently unreachable from this sandbox class — recorded).

## 6. Recommended M3 path (the integration work this decision unlocks)

1. `parametric` module: the sketch-crate behind the experiment-B seam
   (stateless service; journaled apply-back; bit-exact undo; digest-equal
   save/reopen; failed solve writes nothing — all proven on the seam by
   m3-eval experiment B), with the adapter notes from §4.
2. Port-vs-FFI decision + the remaining (verify) gates (§4 (c), platform
   policy).
3. **bcdoc/3 schema work — unchanged and independent of this decision**
   (m3-eval §8 item 4): SketchTable, junction identity, workplane record,
   driving-dimension records (incl. reference-dimension gating flag),
   solve-report records (the three candidates' diagnostics surfaces are all
   rich enough to feed them; SolidCraft's is the richest and is the one the
   seam will see).
4. PlaneGCS REFERENCE integration: the translation-pattern notes
   (this lane's driver + findings) are committed reference material; nothing
   further is scheduled.

## 7. Explicitly excluded (with reasons)

- **PlaneGCS as the in-product solver** — §3 (measured; the fallback + note
  remain).
- **slvs / SolveSpace wheel** — m3-eval §4.1 verbatim; re-review conditions
  never waived; with a winner measured, they stay moot for the primary slot.
- **Any SolidCraft component beyond `crates/sketch`** — kernel, doc model, UI,
  MCP/CLI, skills: TL2's record governs each (truck REJECTED as kernel;
  OCCT/OCP proceeds per ADR-0002).
- **Any kernel implication** — ADR-0002 unaffected, exactly as m3-eval §9
  recorded.
- **Any AutoCAD-parity claim** — none arises from constrained-sketch
  results.

## 8. References

- The gate definitions: m3-eval `cad-sketcher-evaluation.md` §8 (items 1–3,
  5); SolidCraft `solidcraft-evaluation.md` §4.1 gates (a)–(d).
- The evidence: `experiments/solver-h2h/` — README (isolation + reproduction),
  `results/*.json` (4 envelopes), `findings/*.md` (6 analyses), both harnesses
  committed (`planegcs-side/`, `solidcraft-side/`), fetch scripts
  (sha-verified pins), evaluation-only compat shims.
- Prior records: m3-eval decision record; TL2's SolidCraft record (the pin
  source and the gate definitions); the bcdoc-seam experiment B record.
- The completion graph for this lane:
  [completion-graph-solver-head-to-head.md](../30-process/completion-graph-solver-head-to-head.md)
