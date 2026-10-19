# Solver conformance — experiment A (m3-eval phase 2a)

- **Status:** evaluation record. No component adopted; nothing here is product code; the
  kernel direction (ADR-0002) is untouched. Evidence: [`results/solver-conformance.json`](../results/solver-conformance.json)
  (23 cases, 115 named checks, **112 pass / 3 fail** — the failures are genuine solver-behavior
  findings, recorded honestly, fixtures never tuned to pass), fixtures:
  [`fixtures/solver/cases.json`](../fixtures/solver/cases.json) (generated, never hand-edited).
- **Owner:** E1 (m3-eval); TL owns the product decision.
- **Binary measured:** the exact wheel CAD Sketcher v0.32.1 bundles —
  `slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`, sha256
  `9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80` (byte-identical to
  PyPI; source = solvespace/solvespace @ `477d4c8`), driven directly via the scratch
  extraction (`scripts/slvs_loader.py`, digest verified at load). Solved group conventions
  mirror the addon's own `CurveSolver` (`curve_solver.py:59-61` group_fixed=1 /
  group_sketch=3; workplane built like `_init_workplane()`, `curve_solver.py:90-138`).
- **Fixtures:** 17 W1-identical transcriptions from
  `tl2/solidcraft-evaluation @ 685f7c45…` `experiments/solidcraft/harness/src/bin/w1_sketch.rs`
  (read-only) + 6 new coverage probes. Equivalence marks: **9 identical / 8 adapted**
  (adapted reasons are binding and per-case: angle formulation, unsigned DistanceX/Y →
  signed PROJ, radius → diameter, tangency argument order, edits via rebuild — the slvs API
  has no constraint-value mutation). Every adaptation keeps TL2's expected values unchanged.

## 1. The slvs result surface (measured, source-cited)

From the pinned wheel at runtime + solvespace source at `477d4c8`:

- `solve_sketch(g, with_bad)` returns `{result, dof, nbad}`; with `with_bad=True` a
  **tuple** `(result, bad_handles)`. Result flags (`include/slvs.h:199-203`):
  `0 OKAY, 1 INCONSISTENT, 2 DIDNT_CONVERGE, 3 TOO_MANY_UNKNOWNS, 4 REDUNDANT_OKAY`.
- **Exposed flag 1 is overloaded**: it maps from the internal `REDUNDANT_DIDNT_CONVERGE`
  (`src/slvs/lib.cpp:917-920`), i.e. it means *failed AND rank-deficient* — not
  "inconsistent rank analysis only". Name-collision risk vs SolidCraft's `Inconsistent`
  status is called out in §2.
- **bad list semantics differ by path** (`src/system.cpp:439-552`): on convergence with a
  failing rank test → `FindWhichToRemoveToFixJacobian` suggestions (redundant removal
  candidates); on non-convergence → constraints **unsatisfied at Newton's final internal
  iterate** (which is not necessarily the set of logically conflicting constraints — §4).
- **No residual, iteration-count, or per-param-determined surface.** TL2 measured
  `iterations`, `max_residual`, `constraint_residual`, `point_determined`/`curve_determined`;
  none are exposed by slvs. We probed determined-ness instead via perturbed re-solves
  (dof-0 systems whose perturbed re-solve reproduces the solution are determined in TL2's
  sense) and marked those checks `adapted`.
- **No constraint mutation API**: no delete/re-value; only `set_param_value` (geometry
  params). Dimension edits therefore require a **full system rebuild** seeded from the
  previous solution — exactly CAD Sketcher's own edit path (`curve_solver.py` rebuilds the
  whole slvs system on every solve).
- **Binding defects measured**: `distance_proj()` aborts the process
  (`entityA=E_NONE` → `GetEntity(0)` assertion — the C helper never provides the
  projection vector the equation requires, `constrainteq.cpp:283-292`; we use raw
  `add_constraint(PROJ_PT_DISTANCE, entityA=fixed ±x/±y reference line)` instead — note
  a SolveSpace line's vector is `point[0] − point[1]`, `src/entity.cpp:35-37`); guards call
  `Platform::FatalError` → process abort, not Python exceptions (verified: `add_circle`
  with a non-3D normal, `tangent()` on non-shared endpoints); `solvespace.pyi` is stale
  (declares `rank`/`bad` members the binary never returns; `mark_dragged` exists in the
  compiled module but is not re-exported by `slvs/__init__.py`).

## 2. Status-vocabulary mapping (slvs → TL2 `solved`/`failed`)

| slvs flag | name | TL2 status | note |
|---|---|---|---|
| 0 | OKAY | solved | converged + rank passed |
| 4 | REDUNDANT_OKAY | solved | converged, rank failed (redundancies); bad = removal candidates |
| 2 | DIDNT_CONVERGE | failed | bad = unsatisfied-at-final-iterate constraints |
| 1 | INCONSISTENT (internal REDUNDANT_DIDNT_CONVERGE) | failed | **overloaded name** — failed AND rank-deficient; do not conflate with SolidCraft's "inconsistent" |
| 3 | TOO_MANY_UNKNOWNS | failed | size bound |

The same table is embedded in the envelope (`solve_status_vocabulary`).

## 3. Per-group results

- **mapping** — dof counts identical to TL2: bare line 4, circle 3, arc 5 (slvs arcs enforce
  `|start−c|=|end−c|` with no radius variable; circles carry the radius as a real distance
  param — the same variable/derived split SolidCraft documented). Geometry untouched when
  unconstrained (bitwise).
- **fully constrained** — all exact within 1e-6: circle (center (0,0), r 5),
  triangle (A (0,0), B (50,0), C on the 60° ray at t=25+5√6, the far branch, dof 0 — the
  direction-cosine angle form picks the branch from the seed), l-bracket corners exactly
  `(0,0)(60,0)(60,8)(8,8)(8,40)(0,40)` (dof 0), slot exactly `(0,±6)/(40,∓6)` caps with
  r=6 and dof 0 — **no redundancy report for endpoint tangency at structurally shared
  endpoints** (see §6). Triangle convergence lands ~2e-9 from the analytic values (within
  the 1e-6 bar; SolidCraft's residuals were tighter).
- **value edit** — |AB| 50→40 re-solve from the previous solution: B (40,0), C on the 60°
  ray at t'=(40+√3300)/2, anchored A bit-identical, no orientation fold, dof stays 0.
  Performed by rebuild (no mutation API) — the addon's own path.
- **underconstrained** — dof identical to TL2 (3 for the horizontal-only line, 4 for the
  dim-less L, 2 for radius-only circle); free circle centre bit-identical across the radius
  edit (matches SolidCraft's exact result); motion split differs (§5).
- **redundancy** — the W1 fixture **fails** on SolveSpace (§6): the 3 failed checks live here.
- **conflict/failure** — all three fixtures fail (flags 1/2/1) with the geometry bitwise
  untouched (§4); bad lists: conflicting distances names both dims (like TL2), the other
  two name a subset (§4).
- **determinism** — **bitwise** in-process 5× (identical coordinate bits, digests, status,
  dof) and cross-process 3× (identical `W1_GEOM_HASH` lines; FNV-1a-64 over coordinate
  bits, TL2's digest algorithm applied to this solver's entity layout). Iteration/residual
  equality (TL2's extra determinism dimensions) is not measurable through this API.

## 4. Failure behavior vs SolidCraft — measured, not assumed

Observable result is the same: **geometry bitwise unchanged on failure**, measured on all
three failure fixtures *plus* the redundancy failure (max coordinate delta 0.000e+00 in each).
The mechanism differs and is source-cited: SolidCraft's LM moves geometry then writes back
the pre-solve positions explicitly; SolveSpace copies every param into the system
(`IdList::Add` value-copies, `src/dsc.h:473-483`), Newton mutates only the copies
(`src/system.cpp:308-343`), and the write-back to the sketch's params happens **only on
the success path** (`src/system.cpp:519-530`) — a failed solve never touches the sketch.
Consequence for a bcdoc seam: SolveSpace failure semantics are transactional by
construction (no partial writes ever), and partial progress is discarded rather than
restored.

Bad-list granularity differs: for the same logical fixture,
`conflicting_distances` → both dims named (TL2: k2,k3 — same),
`coincident_plus_distance` → only d1 (TL2: k1 **and** k2),
`triangle_edit_unsolvable` → only d2 (TL2: k3,k4,k5). The bad list is a
*failure-point* report (unsatisfied at Newton's final internal iterate), not a
*diagnosis* of all conflicting constraints — a seam must not treat it as a complete
conflict set.

## 5. Underconstrained motion split (behavioral divergence datum)

`line_horizontal_only` (input y's 0.0 and 1.0): SolveSpace lands both endpoints at
y=1.0 — the entire gap closes onto **one** endpoint, because the exposed path solves by
substitution first (`SolveBySubstitution`, `src/system.cpp:481-483`: with
`forceDofCheck=false` the substitution pass runs and pins one param to the other's current
value). SolidCraft's damped LM splits ~evenly (0.5/0.5, TL2 record). Both are legitimate
underconstrained semantics; the l-bracket-no-dims free corners likewise follow the seed
onto the nearest H/V-consistent configuration (solved corners `(0,0)(57,0)(57,7)(9,7)(9,38)(0,38)`
from the rough seed; a 0.3-magnitude seed perturbation changes the landing by ~0.94 —
seed-following, not a stable attractor). Recorded, no pass/fail.

## 6. Redundancy reporting — the honest failed fixture

The W1 `rect_redundant_duplicate_dimension` fixture (duplicate Vertical on an otherwise
fully-constrained rectangle) **does not solve** on the exposed SolveSpace path:
result flag 1 (REDUNDANT_DIDNT_CONVERGE, exposed as INCONSISTENT), dof 0, geometry left
bitwise at the input, bad list = `d1` (a length constraint unsatisfied at the final
iterate) — **not** the duplicate. Standalone probes confirmed: duplicate-V and duplicate-H
variants both fail identically (bad lists name different removal/unsatisfied candidates
each time); a trivial duplicate-Horizontal on a single line solves OKAY but reports
dof 2 where the rank-accurate count is 3. SolidCraft solves the same fixture, keeps dof 0,
and names the duplicate exactly (TL2 `redundant=['k8']`).

Upstream corroborates that this is a real mode, not our construction error: CAD Sketcher
treats implied redundancy as a failure mode to engineer around — `curve_solver.py:335-352`
(issue #674): "Submitting them consumes a DOF and, when the quantity is already implied,
forces REDUNDANT_OK and flags the group failed" — and gates such constraints out of the
system; the UI still defines a REDUNDANT_OK info state (`global_data.py:96-105`). The
**tangency** variant of the quirk documented in `model/tangent.py:43-46` ("solvespace
reports as redundant" for the helper-point formulation) did **not** trigger for the raw
endpoint-shared formulation the W1 slot uses (nbad=0, flag 0) — the redundancy the addon
avoids is an artifact of its own helper-point construction, which duplicates the
endpoint's implied constraints.

**The 3 failed checks** (`solved_despite_redundancy`, `redundant_listed`,
`w1_corners_expected_but_not_reached`) are this divergence, recorded verbatim in the
envelope with the probe evidence.

## 7. Constraint coverage — PAR 12 vs the slvs API (full table in the envelope)

| PAR kind | slvs | note |
|---|---|---|
| coincident | **direct** | `coincident()`; 2D projected form is 2 equations (`constrainteq.cpp:733-753`) |
| parallel / perpendicular / horizontal / vertical / equal / distance / angle | **direct** | one helper each; angle is the direction-cosine form with an `inverse` flag |
| tangent | **direct** (endpoint form only) | requires (arc,circle/cubic)×(line|curve) pairs with structurally shared endpoints, else process abort; line-line tangency absent; the addon derives it via perpendicular+radius for shared points (`model/tangent.py:118-160`) |
| concentric | **derived** | no primitive among the 38 exposed types; coincident centers (probe passes exactly) |
| symmetric | **direct** about line/plane; **derived** about a point | about-point via AT_MIDPOINT of the connecting segment (probe passes exactly); addon has symmetry **disabled** in v0.32.1 (`model/symmetry.py:1`) |
| radius | **derived** | diameter = 2r (`diameter()`); no radius primitive — the addon's `model/diameter.py` does the same |
| distanceX/Y | **derived** (helper broken) | PROJ_PT_DISTANCE via raw `add_constraint` + fixed axis reference lines; `distance_proj()` aborts |

Exposed surface: 38 `SLVS_C_*` types (`slvs.h:83-119`), 21 binding helper constructors +
the raw `add_constraint` escape hatch. Beyond the PAR list slvs also exposes diameter,
midpoint, ratio, equal-angle, equal-point-to-line, length-difference, same-orientation,
symmetric-H/V, where-dragged, on-line/on-circle (via `coincident`).

## 8. Scale curve (NEW evidence dimension; TL2's w1 had none)

Fresh-process medians of 5 (2-CPU sandbox; **absolute numbers are host-specific — the
shape is the finding**; never a check, never compared to TL2 numbers):

| N segments | build median | solve median |
|---|---|---|
| 10 | 0.10 ms | 0.19 ms |
| 50 | 0.37 ms | 0.84 ms |
| 100 | 0.73 ms | 3.05 ms |
| 200 | 1.63 ms | **16.1 ms** |

All sizes solve to dof 0 with exact unit lengths (err 0.0). Solve cost grows
super-linearly (≈O(N^2.2) on this banded chain — SolveSpace writes and SVD-solves a full
Jacobian per Newton iteration); build is ≈O(N). The N=200 driving-length edit
(1.0→1.5) costs rebuild (1.3 ms) + full re-solve (16.0 ms) — there is **no incremental
solve path exposed**; a warm re-solve of the already-solved system costs the same 15.8 ms
(no caching). A bcdoc seam must therefore budget a full re-solve per edit and batch edits
(CAD Sketcher re-solves on a deferred depsgraph callback for the same reason).

## 9. Honest limitations

- 2-CPU sandbox wall-clock: only shapes/ratios are findings, not absolute times; the
  scale build timings include Python-call overhead (measured separately from the solve).
- Not comparable to SolidCraft by construction: residuals/iterations (absent from this
  API), per-param determined flags (probed differently), the cross-solver geometry digests
  (identical algorithm, different entity layouts — comparable in principle, not in value).
- The bad list's meaning is path-dependent (§1) — comparisons in §4 use TL2's recorded
  `failing`/`redundant` fields from `results/w1-sketch.json` at `685f7c4`.
- The pyi's stale signatures mean IDE-typed consumers would mis-model the API; the
  harness binds to the runtime surface (probe-verified), not the stub.

## 10. Reproduce

```bash
./experiments/cad-sketcher/fetch-upstream.sh   # pinned tag + wheels (digest-verified)
PYTHONPATH=experiments/cad-sketcher/scripts \
  /home/z/runtime/blender-5.2.2-linux-x64/5.2/python/bin/python3.13 \
  experiments/cad-sketcher/scripts/gen_solver_cases.py
# regenerates results/solver-conformance.json + fixtures/solver/cases.json
```

Interpreter must be CPython 3.13 (the wheel is cp313). The scratch extraction lives
outside the repo; nothing is committed but scripts, fixtures and results.
