# W1 — sketch constraint solver (experiment A)

- **Experiment:** `w1-sketch` (results: [`results/w1-sketch.json`](../results/w1-sketch.json),
  upstream conformance: [`results/w1-upstream-tests.json`](../results/w1-upstream-tests.json))
- **Owner:** W1 sketch-solver worker, Task ID 97, issue #1 candidate **#1 (sketch solver +
  constraint representation)**
- **Provenance note (honest):** the harness and both result JSONs were built by a predecessor
  agent that died before documenting. This completion pass **independently re-ran everything**
  (§4) and wrote this document. The predecessor's measured data is preserved verbatim in the
  result JSON; the rerun evidence is in its `verification_rerun` block. No result was
  hand-edited except appending that block (per TL2 instruction).
- **Source audited:** upstream pin `tangency-labs/solidcraft` @
  `3b4db52c10279251a068cfca5eb7447068bc28e7` (v0.16.2), consumed as a **path dependency**
  through `../.upstream/crates/sketch` with upstream's `[patch.crates-io]` replicated — i.e.
  behavioral evidence is at the **pinned source**, not the 80-commits-behind release binary
  (that distinction matters for W2/W3; here harness and audit use the same SHA).
- **Verdict in one line:** a clean-room, dependency-light, bitwise-deterministic 2D constraint
  solver with exact constructive seeding, per-entity DOF/redundancy/conflict diagnostics and
  all-or-nothing failure semantics — 85/85 harness checks green, reproduced exactly on rerun;
  recommend **adopt the constraint representation + adapt the solver crate** for candidate #1
  (§8).

---

## 1. Upstream solver architecture (source-backed)

All paths relative to `/home/z/solidcraft-upstream/crates/sketch/src/`. Line numbers are of
the pinned SHA. The crate is self-declared clean-room with literature citations
(`lib.rs:1-15`: "our own clean-room implementation", referencing `plan/architecture.md`).

### 1.1 Data model — `model.rs`

- **Points carry the unknowns.** `SPoint { id, pos, fixed, link }` (`model.rs:48-56`). A
  `Sketch::new()` always contains point 0 = a fixed `origin`. Curves reference points **by
  index**; arcs/circles synthesize `<id>.start/.end/.center` point ids (`model.rs:728`).
- **Curve kinds** (`model.rs:60-85`): `Line { a, b }`, `Circle { c, r }`,
  `Arc { c, a, b }` — *counter-clockwise, radius derived as |a−c|, with a solver block
  keeping |b−c| equal to it* — plus `Ellipse`, `Spline` (fit/control/periodic), `Conic`.
  Per-curve flags (`model.rs:151-177`): `construction`, `reversed` (clockwise-drawn arc keeps
  as-drawn `.start`/`.end` meaning), `link` (projected reference geometry: points fixed),
  `centerline`, `fixed` (locked), `infinite`.
- **Constraints** (`model.rs:183-344`, inventory in §2) plus the `Constraint` wrapper
  (`model.rs:528-546`): string `id` (k1, k2…), `param` (driving dimension's model parameter,
  e.g. `d1`), `driven` flag — a *driven (reference) dimension measures, it does not
  constrain* — and a dimension-text placement field.
- **Bounds against hostile input:** `MAX_POINTS=20_000`, `MAX_CONSTRAINTS=40_000`,
  `MAX_COORD=1e9` (`model.rs:7-13`).

### 1.2 Variable layout and residuals — `solver.rs`

- **Unknowns = coordinates of every non-fixed point + radius of every circle/ellipse**
  (`solver.rs:1-9`). Arc radii are *not* variables (the `Block::Arc` equality does that);
  circles/ellipses get an explicit radius variable (`layout`, `solver.rs:156-195`). Held/
  locked/linked points become constants. This is exactly what the harness's `bare_*` cases
  measured: line=4, circle=3, arc=5 DOF.
- Every constraint contributes **residual functions in millimetres** (comparable row scale,
  `solver.rs:3-5`); driven dimensions and `OffsetDistance` are excluded from the system
  (`build_blocks`, `solver.rs:1427-1435`). Blocks = curve-own relations (arc equality,
  periodic-spline closure) then user constraints **in insertion order** (deterministic).
- **Jacobians are local central differences** with `h = 1e-7·max(|x|,1)`
  (`accumulate`, `solver.rs:1283`), built per connected component.

### 1.3 The constructive seed — `construct.rs` + `decompose.rs`

Before any iteration, points the constraints pin down are **placed exactly**
(`lib.rs:9-15`):

- **Propagation** (`construct.rs:1-39`): a point with two loci anchored on already-placed
  points goes to their intersection (loci = circles, rows/columns, lines through placed
  points, offsets from placed lines, tangency, midpoints, mirrors, coincidence).
- **Cluster decomposition** (`decompose.rs:1-56`): Owen 1991 §3 / Fudos–Hoffmann 1997
  bottom-up reduction — two-point clusters from dimensions, triangle merges over shared
  points (circle ∩ circle), rigid reassembly, *oriented* clusters for H/V + DistanceX/Y,
  hinge steps (circle ∩ axis). **Branches follow Owen's rule §2.4.3/§5: every constructed
  triangle keeps the orientation it had before the solve** — this is why a dimension edit
  doesn't fold the sketch into a mirrored solution (`construct.rs:18-21`).
- Free/pinned clusters get a reference-pose (least-squares) *guess* that "LM starts from …
  builds nothing on it" (`decompose.rs:41-49`). Bounds: `MAX_ROUNDS=16`
  (`construct.rs:52`), `MAX_CLUSTERS=20_000`, `MAX_WORK=20_000_000` (`decompose.rs:68-71`).
- **The seed is only a start**: LM still verifies every constraint; the rank analysis still
  decides DOF. Upstream *tests* enforce this — every solve is repeated without the seed and
  `assert_same_outcome` requires identical status/DOF/determined-flags
  (`solver.rs:1465-1503`). Measured effect in our harness: the seeded triangle and
  L-bracket solve with **0 LM iterations, residual 0.0** (exact construction); the slot
  leaves a tangency remainder → 4 iterations, residual 7.0e-13.

### 1.4 Numerical layer — LM per connected component — `solver.rs` + `linalg.rs`

- Components come from a **union-find over block variables** (`solver.rs:1930-1966`,
  `union_find.rs:6-26`), processed in variable-index order; the Jacobian is block-diagonal
  so ranks add up (`solver.rs:2087-2088`).
- **Damped Gauss–Newton (Levenberg–Marquardt)** on normal equations `JᵀJ + λW`
  (`lm_capped_with_budget`, `solver.rs:958-1051`): λ₀=1e-3, ÷3 on success (floor 1e-12),
  ×4 on rejection (cap 1e12, ≤30 inner attempts), ≤`MAX_ITERS=500` outer. Converged at
  `TOL=1e-9`, accepted at `ACCEPT=1e-6` (`solver.rs:32-42`). Damping is **by distance
  moved, not the diagonal** (comment `solver.rs:1004-1009`) — of equally-fitting steps it
  takes the shortest → **least-motion behaviour for underconstrained geometry** (our
  `line_horizontal_only` case: the 1 mm gap is split ~evenly). Points held on curves get
  `SLIDE_WEIGHT=0.01` so they slide rather than drag the curve (`solver.rs:43-45`).
- **Linear algebra is their own** (`linalg.rs`): row-major dense `Mat`, Gaussian
  elimination with partial pivoting (`solve`, lines 40-83), RREF for rank
  (`rref`, 86-128). No BLAS/LAPACK/ndarray dependency at all.
- **Exact pinning elision**: unknowns the constraints pin down one-after-another from
  constants are eliminated *exactly* without dense matrices (`pinned`,
  `solver.rs:1191-1271`; Gram matrix full-rank check `full_rank` with `PIN_RANK=1e-8`,
  `PIN_CONDITION=1e-8`, lines 1107-1316; `Pin::Floating` handles translation-invariant
  components by rank-preserving column removal, doc at 1183-1190). LM then only solves the
  remainder.
- **Value edits** (`solve_after_value_edit`, `solver.rs:1369-1383`): a component the one-jump
  solve leaves unsolved or *folded* is re-solved by **continuation** — stepping the changed
  driving values old→new in 64 substeps (`SUBSTEPS=64`, `solver.rs:1563`), angles stepping
  the short way round. Orientation flips are detected and reported as `folded` (a solve
  that solves-but-flips is *refused* for commands, shown with a warning in evaluation —
  `SolveReport::keeps_orientation`, `solver.rs:94-97`).
- **Oversize guard**: a component over `MAX_COMPONENT_VARS=4_000` (128 MB matrix) is
  reported failed rather than attempting the allocation (`solver.rs:33-38, 2094-2097`).

### 1.5 DOF, redundancy, conflict — `solver.rs` + `redundancy.rs`

- **DOF = variables − rank**, rank = Σ per component (pinned count + dense rank of the
  remainder via `determined_vars(j, 1e-7)` RREF, `solver.rs:2123-2135`, `2267-2274`;
  `linalg.rs:132-152`). Per-entity diagnostics: `point_determined` (fixed points count as
  determined), `curve_determined` (`SolveReport`, `solver.rs:58-85`).
- **Redundancy** (`redundancy.rs:1-26, 43-118`): a row-block that **adds no rank** to the
  rows before it (ordered walk, twice-reorthogonalized Gram—Schmidt, `DEPENDENT=1e-6`) is
  dependent; only checked for components ≤ `MAX_REDUNDANCY_VARS=400`. A redundant
  constraint whose **residual ≈ 0 is implied, not conflicting** (`CONSISTENT=1e-6`,
  `constraint_residual`, `redundancy.rs:124-135`). `determined_by` additionally returns
  *which* constraints imply it (least-squares combination, `redundancy.rs:141-171`) — our
  rect case: duplicate Vertical `k8` implied by `k3`.
- **Conflict/failure**: status `Failed` iff any residual ≥ `ACCEPT` (`solver.rs:2225`);
  `failing` lists the violated constraint ids (`solver.rs:2098-2109`). **On failure the
  geometry is written back from the pre-solve snapshot `x0` verbatim**
  (`solver.rs:1872-1873, 2231`: `use_x = Solved ? x : x0`) and arc-orientation swaps are
  reverted (`solver.rs:2250-2260`) — the bitwise restore our harness verified. Driven
  dimensions are re-measured after the solve (`refresh_driven_dimensions`,
  `solver.rs:2291-2302`).

### 1.6 Determinism — designed-in, not incidental

- **No randomness anywhere** in the crate (no `rand` dependency; grep over `solver.rs`
  finds no RNG). Fixed LM schedule (§1.4). Iteration orders are structural: blocks in
  insertion order (`solver.rs:1414-1445`), components in variable-index order
  (`solver.rs:1941`), `DrivingValues` is a `BTreeMap` (`solver.rs:1361`); the one
  `HashMap` (`solver.rs:1940`) is lookup-only, never iterated.
- **Work budgets are deterministic units, explicitly not wall-clock deadlines**
  (`solver.rs:956-957` "Deterministic work units … they are not a wall-clock deadline";
  `decompose.rs:78-80` same for the frame budget). Upstream chose work-unit budgets over
  timeouts *so that solves stay reproducible*.
- Empirical confirmation: §3.16-3.17 and §4 (bitwise, in-process 5×, cross-process).

### 1.7 API surface the harness maps onto — `lib.rs`

The harness (`harness/src/bin/w1_sketch.rs:33-38`) uses only the public API:
`Sketch` (construction: `add_point/add_line/add_line_pts/add_arc/add_circle`,
`point_index`, `radius`, `segs`), `ConstraintKind` (§2), `solve` / `solve_after_value_edit`
(+ `Sketch::driving_values`), `SolveReport` fields, and the diagnostics
`constraint_residual` / `determined_by` / `CONSISTENT` (`lib.rs:42-70`). The experiment
cases mirror upstream oracle recipes 25/19/20 (triangle, L-bracket, slot) and upstream
`tests.rs` shapes (fully-constrained rectangle, under-constrained DOF reporting) —
cross-referenced per case in the JSON's `inspired_by` fields.

## 2. Constraint-type inventory (`model.rs:183-344`)

32 `ConstraintKind` variants. Values in mm (angles radians). Indices refer to
`Sketch::points` (p, q) or `Sketch::curves` (l, c, a, b).

| # | Constraint | Fields | Class | Notes |
|---|---|---|---|---|
| 1 | `Coincident` | p, q | geometric | two points identical |
| 2 | `PointOnCurve` | p, c | geometric | point lies on any curve kind |
| 3 | `Horizontal` | l | geometric | line horizontal |
| 4 | `Vertical` | l | geometric | line vertical |
| 5 | `HorizontalPoints` | p, q | geometric | two points on a row |
| 6 | `VerticalPoints` | p, q | geometric | two points on a column |
| 7 | `Parallel` | a, b | geometric | two lines |
| 8 | `Perpendicular` | a, b | geometric | two lines |
| 9 | `Collinear` | a, b | geometric | two lines |
| 10 | `Tangent` | a, b | geometric | curve–curve (incl. at shared endpoints) |
| 11 | `Equal` | a, b | geometric | equal lengths / radii |
| 12 | `Concentric` | a, b | geometric | circles/arcs/ellipses |
| 13 | `Midpoint` | p, l | geometric | p at the middle of line l |
| 14 | `Symmetric` | p, q, l | geometric | p, q mirror about line l |
| 15 | `Fix` | p | geometric | p constant for the solver |
| 16 | `Distance` | p, q, value | dimension | point–point |
| 17 | `DistanceX` | p, q, value | dimension | oriented (signed along +X) |
| 18 | `DistanceY` | p, q, value | dimension | oriented (signed along +Y) |
| 19 | `PointLineDistance` | p, l, value | dimension | normal distance to a line |
| 20 | `Length` | l, value | dimension | line length |
| 21 | `Radius` | c, value | dimension | circle/arc radius |
| 22 | `Diameter` | c, value | dimension | |
| 23 | `Angle` | a, b, value, flip | dimension | line→line, CCW; `flip` = +180° (any of the 4 angles) |
| 24 | `LineAngle` | l, value | dimension | signed angle from sketch +X |
| 25 | `ArcSweep` | c, value | dimension | signed logical sweep (CW/major preserved) |
| 26 | `ArcLength` | c, value | dimension | length along the arc |
| 27 | `SlotOverallLength` | a, b, value | dimension | cap-centre distance + both cap radii |
| 28 | `LinearDiameter` | p, l, value | dimension | 2× point–line distance about a centerline |
| 29 | `Smooth` | a, b | geometric (G2) | curvature continuity at a shared end |
| 30 | `OffsetDistance` | output, value, reverse | dimension (associative) | normal distance of an offset; side kept on edit |
| 31 | `PatternPoint` | p, q, center, angle, offset, directions | pattern | rigid transform of a seed point |
| 32 | `PatternRadius` | a, b | pattern | patterned circle radius follows its seed |

Coverage of our document-model §3.8 PAR list (coincident, parallel, perpendicular, tangent,
horizontal, vertical, concentric, equal, symmetric, distance, angle, radius): **12/12
present**, plus 20 more. Notably absent vs. some CAD solvers: no *point-on-midpoint-of-arc*,
no 3D constraints (2D-only by design — matches our PAR scope), no ellipse-axis dimension
(ellipse is seeded/analytic, `curves.rs:14-25`).

## 3. Experiment narrative — 17 cases (`results/w1-sketch.json`)

Command: `cargo run --bin w1_sketch -j 1` (harness dev profile: bin opt-level 1, deps
opt-level 2, debug-assertions off — upstream dev-profile fidelity; **no wall-clock claims**
in the JSON). Check tolerance 1e-6 = upstream's `ACCEPT`. **85 checks / 85 passed / 0
failed.**

### Group 1 — mapping (bare entities)

| Case | Setup | Result |
|---|---|---|
| `bare_line` | 1 line, no constraints | Solved, **dof 4**, geometry untouched (no constraints → nothing moves) |
| `bare_circle` | 1 circle, no constraints | Solved, **dof 3** (centre 2 + radius variable 1), `curve_determined=[false]` |
| `bare_arc` | 1 CCW arc, no constraints | Solved, **dof 5** (3 points = 6 coords − 1 arc-radius-equality block); radius **derived** = 5.0 ✓ — the arc has *no radius variable* |

### Group 2 — fully constrained (oracle-recipe mirrors)

| Case | Constraints | Result |
|---|---|---|
| `circle_origin_radius` | centre coincident with fixed origin + Radius 5 | Solved, dof 0, centre=(0,0), r=5, all determined |
| `triangle_constrained` (oracle 25) | A@origin, l1 Horizontal, \|AB\|=50, \|BC\|=45, Angle(l1,l3)=60° flip | Solved, dof 0, **0 LM iterations, residual 0.0** (constructive layer solved it exactly); C matches the analytic far branch t=25+5√6 at 60° |
| `l_bracket_constrained` (oracle 19) | 6-line L outline, H/V, corner@origin, dims 60/8/40/8 | Solved, dof 0, iters 0, all six corners at analytic positions (0,0)(60,0)(60,8)(8,8)(8,40)(0,40) |
| `slot_constrained` (oracle 20) | obround: 2 arcs + 2 lines, 4 tangencies, Equal radii, H, centre@origin, r=6, ΔX=40 | Solved, dof 0, **iters 4**, residual 7.0e-13 (tangency chain leaves a small LM remainder); all 6 canonical points exact, both radii 6 |

### Group 3 — underconstrained (DOF + motion behaviour)

| Case | Result |
|---|---|
| `line_horizontal_only` | dof 3 (x-translation, y-translation, length); horizontalized; **minimal motion**: the 1 mm vertical gap is split ~evenly (damped LM takes the shortest step); nothing determined except the fixed origin |
| `l_bracket_no_dims` | dof 4 — H/V + coincident only: the L can *shear* (2 free x-offsets + 2 y-offsets); `point_determined=[T,T,F,F,F,F,F]` (origin + anchored corner only) |
| `circle_radius_only_edit` | dof 2 (centre free, `point_determined[center]=false`); radius edit 5→8 grows the circle with the **free centre bitwise unchanged** (exact minimal motion: the residual gradient doesn't touch the centre) |

### Group 4 — redundancy

`rect_redundant_duplicate_dimension`: fully-constrained rectangle + duplicate `Vertical` on
the same side. **Solved, dof 0** despite the extra constraint; `redundant=["k8"]`;
`constraint_residual(k8)=0.0` (< CONSISTENT=1e-6 → implied, not conflicting);
`determined_by(k8) = ["k3(Vertical { l: 1 })"]` — the solver names the constraint that
implies the redundant one.

### Group 5 — conflicts and failure modes

| Case | Setup | Failure surface |
|---|---|---|
| `conflicting_distances` | same point pair dimensioned 10 and 20 | Failed, dof 2, failing=[k2,k3], residuals d1=0.0 / d2=10.0 (LM stalls between the two targets), **input geometry restored bitwise** |
| `coincident_plus_distance` | two points coincident AND 5 apart (canonical unsolvable) | Failed, failing=[k1,k2], d1 residual 1.403 (= \|pq\| restored to input √41 ≈ 6.4, minus 5), geometry restored bitwise |
| `triangle_edit_unsolvable` | solved triangle, then d1 50→55 (triangle inequality violated: disc<0) | Failed, failing=[k3,k4,k5], **iters 222**, max_residual 1.194, geometry restored **bitwise to the stored solved state** (no partial write-back) |

### Group 6 — edits & determinism

- `triangle_value_edit` (group `value_edit`): d1 50→40, `solve_after_value_edit` →
  Solved, dof still 0, B=(40,0), C matches analytic t=(40+√3300)/2 at 60°, **anchored
  vertex bitwise unchanged**, `folded` empty (no orientation flip), continuations exercised.
- `determinism_inprocess_5x`: same triangle built+solved 5× in one process — **bitwise
  identical point bits** (max coordinate delta = 0), identical iteration counts
  (all 0), identical residuals (all 0.0), identical FNV-1a geometry digests
  (`0b5ec01b39c194d2` ×5).
- `determinism_crossprocess_3x`: the binary re-executes itself in `hash` sub-mode 3×
  (separate OS processes) — identical stdout
  `W1_GEOM_HASH 0b5ec01b39c194d2 fec63e7881038a4d 5e77e7b8deb94d0a ok=1`,
  all exit codes 0. The digest hashes raw coordinate *bits* (harness lines 77-110), so a
  last-ULP difference would show.

## 4. Verification rerun (this completion pass)

Method: predecessor JSON backed up (`/tmp/w1-sketch.predecessor.json`), binary re-run at the
same pin, leaf-by-leaf JSON tree diff, predecessor file restored, `verification_rerun`
block appended (add-only; original data byte-identical — verified: exactly one top-level key
added).

1. **Full rerun via cargo** (env `HARNESS_COMMIT=9316373`, `RUSTC_VERSION=1.99.1`):
   exit 0, **85/85 checks**, identical per-case table (statuses, DOFs, iterations,
   residuals, digests, failing lists).
   Diff vs predecessor: **exactly 3 differing leaves** — `started_utc`, `finished_utc`,
   `harness_commit` (57a0cc3→9316373; the Task-98 commit landed between the two runs).
   The entire `cases` array and the embedded `upstream_tests` block are **leaf-identical**.
2. **Second full run, direct binary invocation** (separate OS process, no env):
   85/85 again; `cases` leaf-identical to run 1 → cross-process determinism of the *full*
   experiment, not just the hash mode.
3. **Hash mode ×3** (three more separate processes): identical
   `W1_GEOM_HASH 0b5ec01b39c194d2 fec63e7881038a4d 5e77e7b8deb94d0a ok=1`.
4. **Upstream test suite rerun**: `cd /home/z/solidcraft-upstream && cargo test -p
   solidcraft-sketch -j 1` → unittests 226 passed / 0 failed / 3 ignored (79.44 s),
   `tests/cursor_target.rs` 9/0/0, doc-tests 0/0/0 — **235/0/3, all green**, identical to
   the predecessor's `w1-upstream-tests.json` (which recorded 79.32 s).

**Conclusion: the predecessor's artifacts are real and exactly reproducible.** No divergence
beyond envelope timestamps and the harness commit pointer.

## 5. Upstream test conformance

`results/w1-upstream-tests.json` + my rerun: 3 suites, **235 passed / 0 failed / 3
ignored** (lib unittests 226+3, integration `cursor_target.rs` 9, doc-tests 0). Notable
conformance facts read from the test sources: every solve is asserted to give the same
status/DOF/determined-flags with and without the constructive seed
(`solver.rs:1465-1503`); the pinned (exact) rank analysis is cross-checked against the
dense RREF analysis in every test (`assert_dense_agrees`, `solver.rs:1096-1097`); the
crate lints `#![deny(clippy::unwrap_used, …panic…)] #![forbid(unsafe_code)]`
(`lib.rs:16-17`) — no panics, no unsafe in the solving path.

## 6. bcdoc mapping analysis (our model → their model)

Our entities (`modules/document/bcdoc/entities.py:27-31, 139-188`): `Line(p1, p2)`,
`Circle(center, radius)`, `Arc(center, radius, start_angle, end_angle)` — world coords,
drawing units, **angles in degrees, CCW about +Z**, dual identity (UUID4 `id` + monotonic
`handle`), mutation only inside transactions. Our PAR plan
(`docs/00-architecture/document-model-and-geometry-kernel.md` §3.8): geometric +
dimensional constraints as a graph over entity references, solving delegated to PlaneGCS
(**candidate**, ADR-0002), incremental solves over dirty subgraphs, over/under-constrained
diagnostics. Adoption-matrix row for PlaneGCS: *candidate*, gates = license verification
(LGPL, medium), solver conformance suite, packaging decision; FreeCAD = study-only
reference; SolveSpace = evaluate-only.

### 6.1 Entity mapping

| bcdoc entity | SolidCraft `CurveKind` | Mapping cost |
|---|---|---|
| `Line(p1,p2)` | `Line { a, b }` point indices | **trivial** — 1:1; 4 unknowns both sides. bcdoc's z is ignored (2D sketch plane) |
| `Circle(center,radius)` | `Circle { c, r }` | **trivial** — 1:1; 3 unknowns (centre 2 + radius var) |
| `Arc(center,radius,start_angle°,end_angle°)` | `Arc { c, a, b }` (CCW; radius **derived** = \|a−c\|; \|b−c\| enforced) | **moderate** — angle→point on import (a = c + r·(cosθs, sinθs), b likewise), point→angle on export (atan2 of (a−c), (b−c); harness already reads back `derived_start_end_angle_rad` / `derived_sweep_rad`, case `bare_arc`); conventions to reconcile: **degrees vs radians**, CCW both, their `reversed` flag for clockwise-drawn arcs, and our explicit `radius` field must be re-derived from solved points (needs a stated tolerance policy) |
| — (no point entity in bcdoc) | `SPoint` (incl. fixed origin point 0, `<curve>.start/.end/.center`) | adapter keeps bcdoc id/handle → their point-index maps; their string point-id resolution (`model.rs:1523`) is the natural seam |
| — (v0 has none) | `Ellipse`, `Spline`, `Conic` | out of scope now; extension surface already solved upstream |
| `id`/`handle` dual identity | string ids (`l1`, `k8`…) | store our UUID hex as their entity/constraint ids — identity is adapter-level, no geometry impact |

**Net:** near-isomorphic. The one real representational delta is the **arc radius**:
theirs is an invariant maintained by a solver block, ours is stored data — round-tripping
means re-deriving radius (and angles) from solved points, which the harness demonstrated
bitwise-stably.

### 6.2 Candidate comparison (SolidCraft sketch vs PlaneGCS plan)

| Dimension | SolidCraft `solidcraft-sketch` (audited, pin 3b4db52) | PlaneGCS (candidate, ADR-0002 — *not audited in this lane*) |
|---|---|---|
| Constraint coverage | §2 inventory: 12/12 of our §3.8 list + 20 more (incl. G2 `Smooth`, `ArcSweep`, oriented DistanceX/Y, patterns, offsets) | FreeCAD-sketcher scope: our full §3.8 list + ellipse/3D-adjacent extras (literature knowledge, unverified here) |
| DOF diagnostics | numeric `dof`, per-point/per-curve `determined` flags, `redundant` list, `determined_by` (names the implying constraints), `failing` list, `folded` orientation warnings — all machine-readable in `SolveReport` | redundant/conflicting/partially-redundant diagnosis system (its advertised strength; exact surface unverified here) |
| Solver algorithm | exact constructive seed (Owen/Fudos–Hoffmann, orientation-preserving) + exact pinning elision + LM/normal-equations per component + RREF rank analysis; central-difference Jacobians | DogLeg (Gauss-Newton + gradient hybrid) with QR-based rank analysis (literature knowledge) |
| Linear algebra | own ~180-line dense GE/RREF (`linalg.rs`); **zero external math deps** | Eigen (C++) |
| Determinism | **designed-in** (§1.6): no RNG, structural iteration orders, deterministic work-unit budgets; verified bitwise in-/cross-process | not assessed here |
| Failure semantics | all-or-nothing: Failed + named violating constraints + bitwise geometry restore; edit-refusal on orientation flips | not assessed here |
| Language / binding | Rust library crate; would need a cdylib + Python FFI (ctypes/pyo3) from our pure-Python extension | C++; needs vendored CMake build + pybind11 (the matrix's "vendor with build" path) |
| Dependency closure | `solidcraft-geom` (serde + thiserror only) + serde + thiserror + ttf-parser — **no truck, no engine, no C libs**; MIT OR Apache-2.0 (root `Cargo.toml:10`) | LGPL-2.1+ (matrix: "medium — verify"); Eigen dep |
| License friction | **none expected** (dual permissive; NOTICE/attribution files present upstream) | gate #1 of the PlaneGCS row is license verification |
| Incremental solves | per-solve connected-component decomposition + deterministic frame budgets; doc-level `EvalCache` is W2's lane | not assessed here |

### 6.3 Mapping cost conclusion

The adapter is small and one-directional per operation: bcdoc entity graph → `Sketch`
(points/curves/constraints; arc angle↔point conversion + deg/rad) → `solve`/`
solve_after_value_edit` → write the solved positions back into bcdoc **inside a
transaction** (their all-or-nothing failure semantics compose cleanly with our
transactions-only mutation rule: a Failed solve leaves geometry untouched, so the
transaction simply isn't proposed). The design-level deltas to decide at design time: arc
radius/angle re-derivation tolerance, degrees-vs-radians at the adapter boundary, and
whether our "graph over entity references" keeps their per-sketch string ids (recommended:
store bcdoc UUIDs as their ids; keep handle↔index maps in the adapter). No bcdoc schema
change is required by their model — the mapping is representable today.

## 7. Limitations

1. **Pin-fidelity is not an issue for this lane**: both the harness and this audit used the
   pinned source (path dependency on `.upstream` @ 3b4db52, patch table replicated), unlike
   W2/W3 which face the 80-commit release/pin gap. The harness header
   (`w1_sketch.rs:1-12`) records the SHA; the result envelope embeds it.
2. The harness exercised **12 of 32** constraint kinds end-to-end (Coincident, Horizontal,
   Vertical, Distance, DistanceX, DistanceY, Length, Radius, Angle, Tangent, Equal, plus
   the arc's implicit radius-equality block); the remaining 20 are covered by upstream's
   235 tests but not by our scenario cases.
3. No wall-clock performance evidence (dev profile, no timing claims in the JSON) —
   performance/scale belongs to W2-b's kernel benchmark lane if TL2 wants solver timing;
   upstream's own bounds (`MAX_COMPONENT_VARS=4_000`, `MAX_REDUNDANCY_VARS=400`,
   `MAX_WORK=2e7`) are work-unit guards, not measured latencies.
4. Ellipses/splines/conics/patterns/offsets/text were not modelled in the harness
   (`geometry_json` marks them "not modelled in this experiment").
5. PlaneGCS comparison cells marked "literature knowledge" were **not** audited in this
   lane; a head-to-head would be a separate experiment (the adoption matrix already gates
   PlaneGCS on a conformance suite).
6. The `verification_rerun` block in `results/w1-sketch.json` was appended by this pass
   (JSON tooling, not the harness) per TL2 instruction; the predecessor's measured data is
   untouched (verified: exactly one top-level key added).

## 8. Recommendation input for candidate #1 (sketch solver + constraint representation)

> Status note: this is the W1 worker's **provisional recommendation** to the TL2 decision
> record — the binding verdict lives in `docs/00-architecture/solidcraft-evaluation.md` §4.1
> (adapt/port, gated; matrix status stays `evaluate`; nothing is adopted by this lane).

**Recommendation: adopt the constraint representation as the design baseline, and adapt
the solver crate (bind it; don't rewrite).** Concretely:

- **Constraint representation — adopt (as design baseline, provisional on product review).** The 32-variant inventory (§2) is a strict
  superset of our §3.8 PAR list with exactly the diagnostics §3.8 demands
  ("over/under-constrained diagnostics reported to the user" — theirs is richer:
  per-entity determined flags, named redundant + implying constraints, named failing
  constraints). The reference-oracle provenance (recipes 19/20/25) and the mapping
  near-isomorphism (§6.1) make it the lowest-risk design baseline for our constraint
  graph schema.
- **Solver implementation — adapt (bind via FFI), not port.** Verified strengths: exact
  constructive seeding (0-iteration exact solves on the oracle shapes), least-motion
  underconstrained behaviour, redundancy *and* conflict discrimination with named
  constraints, all-or-nothing failure with bitwise restore, designed-in determinism
  verified bitwise in- and cross-process, dependency closure of 4 small Rust crates,
  MIT OR Apache-2.0. Binding it (cdylib + Python FFI) compares favourably with PlaneGCS's
  gate list: license friction disappears (PlaneGCS's gate #1), the C++ build chain is
  replaced by cargo, and the conformance evidence already exists (235/0/3 upstream +
  85/85 harness). The honest gaps vs. PlaneGCS: no head-to-head conformance suite against
  PlaneGCS on *our* PAR feature list, and no scale/performance evidence (§7.2-3).
- **Reference-only is too weak** for this much verified evidence; **reject is
  unsupported** by anything observed; **insufficient-evidence** would only apply to the
  performance-at-scale question, which no lane has measured for *any* candidate.
- **Port (reimplement in pure Python)** is not recommended: the exact-elimination +
  rank-analysis + LM stack is ~5k lines of carefully cross-checked Rust
  (`solver.rs`, `decompose.rs`, `construct.rs`, `redundancy.rs`, `linalg.rs`) whose
  value is precisely its tested numerics; a rewrite would discard the 235-test and
  oracle evidence.
- For TL2's gate process: the license-inventory row and packaging decision (native
  binary per platform in the extension package) are the real remaining gates; both are
  ordinary M3-entry work, and ADR-0002's binding decision (OCCT/OCP + solver) can take
  this crate as the PAR-area answer with PlaneGCS kept as the licensed fallback.

**Evidence trail:** `results/w1-sketch.json` (17 cases, 85/85, `verification_rerun`),
`results/w1-upstream-tests.json` (235/0/3), harness `harness/src/bin/w1_sketch.rs`
(1018 lines), this document. All under `experiments/solidcraft/`; nothing outside it was
touched.
