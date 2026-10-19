# SolidCraft evaluation — TL2 decision record

- **Status:** Evaluation complete (issue #1 acceptance gates). **No component is adopted; no release-manifest change; no product code touched.** Every decision below is evidence-backed by committed, reproducible experiments under `experiments/solidcraft/`.
- **Owner:** TL2 (evaluation track); TL owns the product consequences
- **Date:** 2026-10-19 (UTC) — experiments 17:20–18:21 UTC per result-envelope timestamps; decision record committed as `467eaba` (2026-10-19 18:47 UTC); station re-verification `685f7c4` (2026-10-19 20:07 UTC); close-out sync with main `a6a46f1` (M2) on 2026-10-20
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)
- **Upstream evaluated:** `tangency-labs/solidcraft` @ `3b4db52c10279251a068cfca5eb7447068bc28e7` (v0.16.2, commit date 2026-10-19); official release binary v0.16.2 (tag `5de48e9`, **80 commits behind the pin** — measured, recorded in every behavioral result envelope)
- **Experiment lane:** `tl2/solidcraft-evaluation`, originally branched off main `a4b0d7a` (M1 walking skeleton) — **synced with main `a6a46f1` (M2) via merge `df378b3` at close-out; all M2 implementation, acceptance artifacts and inventory changes preserved, zero conflicts, nothing reverted** (verified: the PR diff vs main touches only `experiments/solidcraft/` + these evaluation docs)

## 1. Executive decision

SolidCraft is a **high-quality reference implementation whose architecture we should
learn from in four places, whose sketch-constraint design we should adapt, and whose
runtime, kernel, UI and document model we should not adopt.** Every "adapt" verdict below
is a **provisional, evidence-backed recommendation for product review** — nothing in this
record constitutes adoption: no product dependency, solver, kernel, document-model or
schema change exists or is authorized by this document (§9). Concretely:

| # | Candidate | Decision | One-line basis |
|---|---|---|---|
| 1 | Sketch solver + constraint representation | **Adapt/port (provisional recommendation)** — representation design now; solver crate only behind a gate | 32 constraint kinds covering our full PAR list; DOF/redundancy/conflict diagnostics with named causes; bitwise-deterministic; 85/85 harness checks; 235/0/3 upstream tests; near-isomorphic to `bcdoc` entities; 12-crate closure, zero GPL, no native code |
| 2 | Parametric feature history + incremental recompute | **Adapt (design) / reference (implementation)** | Fingerprint prefix-reuse recompute contract verified (edit → exactly the dependent features re-run); per-feature failure with frozen state; loud write-gating — but their in-process state-digest cache does not map onto our UUID/`doc_version` model |
| 3 | Persistent topology naming + reference stability | **Adapt (behavior contract) / reference (mechanism)** | Graded name lookup, failure-over-silent-retarget, unverified-matches-announce-themselves — all behaviorally verified; the kernel mechanism is truck-specific (vendored `history.rs` provenance), OCCT `Modified`/`Generated` is our equivalent |
| 4 | `truck` kernel vs OCCT/OCP | **Reject as kernel replacement; adapt kernel-agnostic patterns** | OCCT is 1–2 orders faster on curved-curved booleans in release config; truck's internal measurement is tessellated (~1.5e-4 rel) where OCCT integrates exactly (≤8e-9); one truck STEP-import anomaly (st5, +4.1% volume, closed, no warnings); packaging — truck's one win — is already a priced-in cost of ADR-0002 |
| 5 | Typed command registry / operation interfaces | **Adapt (metadata patterns)** | Their `CommandSpec` metadata (enabled/undoable/effects/param-docs, catalog-as-documentation, nearest-match error quality) is excellent; their generic `execute`-over-394-commands waist is weaker than our typed `cad.*` boundary — keep ours |
| 6 | MCP/CLI/control + transaction/rollback techniques | **Adapt (wire/protocol patterns) / reference (checkpoints)** | Their stdio JSON-RPC framing, two-layer error split, batch failure envelope, and default-deny bounded-filesystem rules are verified excellent (58 probes × 2 runs); their undo-history-restoring checkpoints are a strong pattern; their **absence of optimistic concurrency** confirms our `base_doc_version` design |
| 7 | Skills / automation patterns | **Reference (content) + adapt (doc-test concept)** | Verification-first loops, parameter-range walks, trap catalogs, executable `test_facts` doc-tests — content patterns for our skill-format-v1, which stays authoritative |

**What the next integration PR should make** (§8) and **what stays excluded** (§9) follow
from these decisions. The product's kernel direction (ADR-0002: OCCT via a binding) is
**affirmed, not changed**; the document model, CAD tool contract and extension packaging
are untouched by this evaluation.

## 2. Source audit (summary — full detail in the findings docs)

Audited at the pinned SHA with source-level evidence (paths + line numbers in each
findings doc). License facts were verified **from the actual license files**, not README
claims (W3-b):

- **License:** `MIT OR Apache-2.0` dual license confirmed per-crate (workspace root +
  `license.workspace = true` in every crate we would consume). MIT holder: "2026
  SolidCraft contributors". `NOTICE`, `ATTRIBUTION.md`, `THIRD-PARTY-LICENSES.txt`
  present and substantive. Release-binary license files byte-identical to the pin's.
- **Vendored, locally-patched crates** (the kernel SolidCraft actually ships — NOT stock
  truck): `truck-shapeops` 0.4.0 (adds a whole new `transversal/history.rs`
  face/edge-provenance mechanism — their persistent-naming foundation), `truck-geometry`
  0.5.0 (three fixes incl. a second-derivative math bug #763 and intersection perf #1038),
  `truck-stepio` 0.3.0 (writer fixes: duplicate entity ids, revolved-surface sense),
  `truck-meshalgo` 0.4.0 (a large bounded-work/robustness series against hostile files),
  `matext4cgmath` 0.1.0 (Newton-refinement hang fix), `egui-wgpu` 0.36.2 (UI — excluded
  from every reuse path). All Apache-2.0 © RICOS Co. Ltd. (egui-wgpu: MIT OR Apache-2.0);
  every change marked `SolidCraft:` in source — **129 markers counted** (W3-b).
- **Reuse closures audited for license risk** (the dependency sets we would actually
  ship if a gated candidate were ever approved): closure 1 (sketch solver) = **12 crates**, all
  permissive, zero GPL, no native code; closure 2 (kernel+doc) = **136 crates**, 15
  SPDXs, all permissive, zero GPL; `zstd-sys` and the `cadmpeg` codec family are outside
  both closures (io/engine excluded from every reuse path). The only pre-ship `(verify)`
  item for candidate #1 is `unicode-ident`'s Unicode-3.0 term FSF listing.
- **Upstream maturity:** v0.16.2 released 2026-10-19. Two upstream statements exist at the
  pin and are reported distinctly (evidence below): the pinned **README status line** says
  "75 of 76 public reference parts match … the other is a tracked bug", while the pinned
  **generated oracle record** (`docs/oracle.md`) says "83 / 83 cases pass; sources: 62
  analytic, 21 freecad; 0 known failure(s)". We verified the machine-checkable side at
  `3b4db52`: `tests/oracle/` contains exactly **83 case directories** and the `docs/oracle.md`
  table has exactly **83 rows, all `pass`, 0 `fail`**. Upstream git history explains the gap:
  the README line was last set at upstream commit `e12758ff` (2026-10-12), when the oracle
  corpus was 76 cases with 1 tracked failure (`docs/oracle.md` then read "75 / 76 cases
  pass; 55 analytic, 21 freecad; 1 known failure"); the corpus has since grown to 83 cases
  and the tracked failure was fixed, but the hand-maintained README line was never updated.
  Our evidence uses the **generated** oracle record (83/83 at the pin, 62 analytic +
  21 FreeCAD-computed — FreeCAD is an *independent* oracle, not a dependency), cross-checked
  by our own 10/10 oracle-fixture agreement between the release binary and pin-level paths
  (experiment C). 235 sketch-crate tests pass at the pin; upstream CI runs per-PR license
  generation and scheduled cargo-deny advisories.

## 3. Experiments run (all under `experiments/solidcraft/`, reproducible)

| Experiment | Issue #1 requirement | Result headline | Evidence |
|---|---|---|---|
| A — sketch solver (W1, Task 97) | constraints, DOF, dimensions, convergence, failure, determinism | 17 cases, **85/85 checks green**; deterministic bitwise in-process (5×) and cross-process (5 separate runs); failure restore bitwise; rerun leaf-identical | `results/w1-sketch.json`, `results/w1-upstream-tests.json` (235/0/3), `findings/w1-sketch.md` |
| B — feature history & naming (W2-a, Task 98) | upstream edit → downstream recompute, reference stability, failure propagation, determinism | 10 scenarios: 9 pass + 1 honest observation (coincident-wall marginal geometry diverges across evaluation paths); recompute prefix-reuse verified; face-name stability verified; destroyed topology fails loudly; determinism byte-identical except wall-clock ms | `results/w2-history.json`, `fixtures/history/`, `findings/w2-history.md` |
| C — kernel benchmark (W2-b, Task 100) | booleans, fillet/chamfer, shell, STEP, tolerances, failure rates, timing, memory, packaging | 16 fixtures (10 oracle-derived + 6 self-authored): both kernels 15/15 within oracle tolerance; 1 honest refusal each; OCCT 1–2 orders faster on curved booleans; STEP cross-read 15/15 with one truck-side import anomaly; full re-run reproduced (0 substantive diffs) | `results/w2-kernel.json`, `results/w2-kernel-verification.json`, `findings/w2-kernel.md` |
| D — agent interface (W3-a, Task 99) | real CAD op through the integration seam, validation, permissions, rollback | 58 probes × 2 runs: 54 pass / 0 fail / 4 info; full CAD chain exact (40×30×20 → 24000 mm³, rel_err 0.0; edit → 30000 exactly; undo/redo verified); 11/11 filesystem refusals (default-deny, resolve-before-compare); failing batch → exact-snapshot rollback incl. undo history | `results/w3-mcp.json`, `findings/w3-mcp.md` |
| E — regression (TL2, Task 102) | product pure-Python suite + package check stay green | 440 passed (identical to the M1 record); extension build check green; **zero production files changed** (git diff vs main = experiments/ + docs/ only) | PR body + §10 below |

Sandbox constraints recorded honestly (they bound the evidence, and are documented in
`experiments/solidcraft/README.md`): the harness links only the upstream crates that
compile inside the 4 GiB cgroup (`cadmpeg-ir` codegen exceeds it — measured), so
behavioral MCP evidence uses the checksum-verified official release binary (80 commits
behind the pin; the drift is recorded in every envelope and mitigated by 10/10 oracle
agreement between binary and pin-level paths).

## 4. Candidate scorecard (decisions with gates)

Each candidate carries: decision, exact upstream SHA + source paths, tested version,
license status, target product module, integration design, packaging/runtime impact,
test results, limitations, and a **measurable adoption gate** — a gate is the precondition
for any future status change, not an authorization to change it. Full detail per candidate
lives in the findings docs; this is the decision layer.

### 4.1 Candidate 1 — sketch solver + constraint representation → **Adapt/port**

- **Source:** `crates/sketch/src/{model.rs, solver.rs, decompose.rs, redundancy.rs, dims.rs, curves.rs, linalg.rs, union_find.rs}` @ `3b4db52`; solver = constructive seed (loci propagation + Owen/Fudos-Hoffmann cluster decomposition) then damped Gauss-Newton/LM per union-find component, own dense GE/RREF, **zero external math deps**.
- **Coverage:** 32 `ConstraintKind` variants (17 geometric + 15 dimensional) — covers all 12 PAR-area constraint kinds in our document-model doc §3.8, plus 20 more.
- **Mapping to our model:** near-isomorphic — `Line`/`Circle` 1:1 with `bcdoc`; `Arc` needs an angle↔point adapter (the harness already does both directions). No schema change required.
- **License:** MIT OR Apache-2.0 (verified from files); closure 1 = 12 crates, zero GPL, no native code.
- **Test evidence:** 85/85 harness checks; 235/0/3 upstream tests; bitwise determinism verified in- and cross-process.
- **Limitations:** no head-to-head conformance suite vs PlaneGCS (our incumbent candidate); no large-sketch scale/perf evidence; harness exercised 12/32 constraint kinds.
- **Gate (measurable) before any `candidate` status change:** (a) PlaneGCS comparison suite on our PAR feature list (same fixtures, both solvers, recorded); (b) packaging review of a Rust cdylib in the extension (Blender-extension native-lib policy — the same unverified policy that gates OCCT); (c) resolve `unicode-ident` Unicode-3.0 FSF listing `(verify)`; (d) decision on FFI vs port (port cost est. from the 12-crate closure; FFI cost from the packaging review).

### 4.2 Candidate 2 — feature history + incremental recompute → **Adapt design / reference implementation**

- **Source:** `crates/doc/src/{eval.rs, eval_more.rs, params.rs, expr.rs}` @ `3b4db52`; chained per-feature fingerprints; prefix reuse on edit (verified: `recomputed: 4/8` then `3/8` — exactly the dependent suffix); per-feature error caching with frozen pre-failure state; write-gating (failed run writes nothing).
- **What we adapt:** the *contract* — fingerprint-prefix reuse, per-feature failure semantics, loud write-gating — into our M3 parametric module design over `bcdoc` transactions.
- **What we don't:** their Rust evaluator and in-process state-digest cache; our identity model (UUID/handle/`doc_version`) is authoritative and not interchangeable with their feature ids (W2-a findings §4 documents the four translation seams).
- **Gate:** none needed (design-level); the M3 parametric design doc must cite this record.

### 4.3 Candidate 3 — persistent topology naming → **Adapt behavior contract / reference mechanism**

- **Source:** `crates/doc/src/{naming.rs, history_names.rs, lineage.rs, piece_names.rs, name_lookup.rs}` + vendored `truck-shapeops/src/transversal/history.rs` (face/edge provenance recorded *during* construction, never reconstructed) @ `3b4db52`.
- **Behavior verified:** graded lookup (Exact > Alias > Piece > Stem); destroyed references fail loudly naming what's gone; stale picks refused with nearest-match distance; geometric-vote fallbacks announce themselves as unverified.
- **Mechanism:** truck-specific; our equivalent information source is OCCT's `BRepBuilderAPI` `Modified`/`Generated` history — a design reference, not portable code.
- **Gate:** none needed (design-level); the M3 parametric design *should* adopt this behavior
  contract (provisional recommendation, subject to that design's own review).

### 4.4 Candidate 4 — `truck` vs OCCT/OCP → **Reject as replacement; adapt patterns**

- **Evidence (release-config timing, N=5):** curved-curved booleans OCCT 1–2 orders faster (k15 intersect: 29.3 ms OCP vs 1041.8 ms truck; k14 cut: 3.4 vs 298.7 ms); planar/shell parity. Exactness: OCP integrates to ≤8e-9 rel; truck's internal measurement is tessellated (~1.5e-4 rel; its exported B-rep is exact — OCP reads analytic values back from truck-written STEP). Robustness: both refuse the unbuildable fillet with clear errors; one truck STEP-import anomaly (st5 near-tangent union, +4.1% volume, closed body, no warnings). Memory: neither dominates outright. Packaging: OCP 152 MiB installed/wheel-set vs truck pure-Rust 64 MiB binary — real, but ADR-0002 already accepts OCCT's packaging cost.
- **Patterns worth adapting regardless of kernel:** `boolean_guard.rs` result verification (closure + volume monotonicity + outside-tool-box invariance); refusal semantics and error-message quality bar (allowed values, nearest-match); construction-time provenance as the persistent-naming design reference; oracle-style analytic benchmark discipline (their 83-case suite is the model for our kernel TP-CAT-02 evidence).
- **Decision:** ADR-0002 (OCCT) is **affirmed**. A kernel change would require a separately reviewed ADR with scale parity, hostile-input and own-STEP-import reliability, packaging/ABI, topology-identity and regression evidence — none is proposed.

### 4.5 Candidate 5 — typed command registry → **Adapt metadata patterns**

- **Source:** `crates/engine/src/cmd/` + `solidcraft-cli commands` catalog (394 commands with enabled/disabled reasons, param docs, effects) @ pin + binary.
- **Adapt into `bccmd`:** `CommandSpec` metadata enrichment (undoability, effects advertisement, param documentation, catalog-as-documentation, disabled-with-reason) — keeping our typed schema boundary (their generic `execute` waist is weaker than our 62 typed `cad.*` tools).
- **Gate:** design note in the M2 commands work; no dependency.

### 4.6 Candidate 6 — MCP/CLI/control + transactions → **Adapt wire patterns / reference checkpoints**

- **Source:** `crates/mcp/src/{server.rs, tools.rs, backend.rs}` + `docs/{mcp.md, control-protocol.md}` @ pin; behavior verified on the release binary.
- **Adapt:** stdio JSON-RPC framing (one line per message), initialize-with-instructions handshake, two-layer error split (JSON-RPC `-32602` vs engine tool errors), batch failure envelope `{ok, completed, failed:{index, command, error}, rolled_back}`, default-deny bounded-filesystem `PathScope` rules (resolve-before-compare; hidden files only inside named `--allow-path` roots) — for a **future Blender-CAD MCP/control surface speaking cad-tool-contract/v1**.
- **Reference:** exact-snapshot checkpoints that restore the undo history itself.
- **Keep ours:** `base_doc_version` optimistic concurrency (their counter is decorative — verified), permission classes, events, R1–R4 pipeline.
- **Gate:** an MCP-surface design note at M5 planning; no dependency now.

### 4.7 Candidate 7 — skills/automation → **Reference content + adapt doc-tests**

- **Source:** `skills/solidcraft-{checking,editing,mechanisms,modeling}/SKILL.md` @ pin.
- **Reference:** verification-first agent loops, parameter-range walks, trap catalogs.
- **Adapt:** the executable `test_facts` doc-test concept into skill-format-v1 evolution (ADR-0006 stays authoritative).
- **Gate:** skill-format-v1.1 proposal at the skills milestone.

## 5. License and supply-chain record (input to license-inventory.md)

Verified from files (W3-b, `results/w3b-supply-chain.json`): dual license standard-text
confirmed; per-crate inheritance confirmed; vendored truck family Apache-2.0 © RICOS with
the `SolidCraft:` marker convention verified (129 markers); both reuse closures zero-GPL;
`solidcraft-cli licences` output captured (16,441 lines); upstream CI runs per-PR license
generation. **Dual-license election recommendation: Apache-2.0** (explicit patent grant;
uniform pipeline with the truck family which is Apache-2.0-only; NOTICE/state-changes
machinery already exists for ZCode/OCP). Inventory rows are added in
`license-inventory.md` §2.1 with `(verify)` items left as explicit blockers — nothing
ships from this evaluation, so no verdict is exercised yet.

## 6. Limitations of the evaluation itself

1. Single 2-CPU sandbox host; timing evidence is comparative within one host and config,
   not absolute (recorded per-case in the result envelopes).
2. Behavioral MCP evidence ran on the release binary (tag `5de48e9`, 80 commits behind
   the pin) because `cadmpeg-ir` cannot compile inside the sandbox's 4 GiB cgroup; the
   drift is mitigated (oracle agreement 10/10 between binary and pin-level paths) and
   recorded in every envelope.
3. 16 kernel fixtures are small; no scale, spline-heavy, or hostile-corpus coverage —
   recorded as open items for any future kernel ADR.
4. The sketch-solver lane exercised 12/32 constraint kinds; no PlaneGCS comparison yet
   (that is candidate 1's gate, not this evaluation's).
5. Experiments never touched the Blender 5.2.2 runtime (no production-facing files
   changed), so the pinned acceptance battery was not re-run — the pure-Python suite and
   package check were (§10), matching the issue's conditionality.

## 7. Answers to the issue's success questions

- **Which SolidCraft capabilities would materially accelerate our CAD roadmap?** The
  constraint taxonomy + solver diagnostics (PAR area, M3), the parametric-recompute
  contract and naming behavior contract (parametric module design), registry metadata
  patterns (commands, M2), and the MCP wire/security patterns (agent surface, M5). All
  are design-level accelerations; one is a potential code-level adaptation behind a gate
  (candidate 1).
- **Which components are suitable for direct reuse, adaptation or reference-only?**
  §4: nothing qualifies for *direct* reuse as shipped today; candidate 1's solver crate
  is the only gated code-reuse path; the rest is adapt-design or reference.
- **Does `truck` offer a credible advantage over OCCT/OCP for any defined workload?**
  No, after fidelity, robustness and packaging are considered (§4.4): OCCT wins the
  boolean hot path by 1–2 orders in release config, integrates exactly, and imports its
  own STEP robustly; truck's packaging win is already a priced-in OCCT cost. ADR-0002
  stands.
- **How can agent automation patterns fit our existing operation and security
  contracts?** As an MCP/control *surface* speaking cad-tool-contract/v1 with their
  framing/error/bounded-FS patterns and our concurrency/permission core (§4.6).
- **Which changes should the next integration PR make, and which remain excluded?**
  §8 and §9.

## 8. Recommended next integration PR (scoped, no new dependencies)

> All five items are **provisional design recommendations** for product review — none is
> adopted, authorized or scheduled by this evaluation; each lands only through the normal
> reviewed-PR path, and the product owner may accept, amend or reject each independently.

1. **PAR-area constraint taxonomy + diagnostics design update** (document-model doc
   §3.8 / parametric module README): adopt the 32-kind inventory structure, DOF =
   vars − rank reporting, redundancy with `determined_by` naming, conflict failure
   semantics — as our design baseline, citing this record.
2. **Parametric-module design contracts** (M3 prep): fingerprint-prefix recompute,
   per-feature failure with frozen state, loud write-gating, graded reference lookup
   with failure-over-silent-retarget.
3. **`bccmd` CommandSpec metadata enrichment** (M2 prep): undoable/effects/param-docs
   fields, catalog generation, disabled-with-reason.
4. **MCP-surface design note** (M5 prep): cad-tool-contract/v1 over their wire patterns
   (framing, two-layer errors, batch envelope, PathScope rules).
5. **skill-format-v1.1 proposal**: executable doc-tests (`test_facts` pattern).

Each item is docs/design-only in product terms, individually reviewable, and cites the
experiment evidence. **No runtime dependency, no vendored code, no kernel change, no
schema change.**

## 9. Explicitly excluded (with reasons)

- **The SolidCraft application/runtime as a whole** — second authoritative document
  model (issue boundary #4); rejected.
- **`truck` as the production kernel** — §4.4; ADR-0002 affirmed.
- **egui/wgpu UI** — issue boundary #3; our UI is Blender-hosted.
- **`cadmpeg` codec family / io / engine crates** — outside every reuse closure,
  unbuildable in our sandbox, and a future io-layer question only.
- **Their skills format, session/undo semantics as replacement** — our
  skill-format-v1, `base_doc_version` and permission classes stay authoritative.

## 10. Regression evidence (experiment E)

Two records, both green, exactly one command set each:

- **At the original M1-baseline tip `685f7c4` (2026-10-19):** `python3 -m pytest -q`
  at the repo root → **440 passed** (identical to the M1 completion-graph record);
  `python3 scripts/build_extension.py --check` → green; zero product files modified
  (`git diff a4b0d7a..HEAD` = `experiments/solidcraft/**` + the docs added by this record).
- **At the close-out sync with M2 main `a6a46f1` (merge `df378b3` + close-out fixes):**
  `python3 -m pytest tests/ -q` → **6 passed** (TP-CAT-00 repo-consistency);
  `python3 -m pytest modules tests -q` → **1127 passed** (the M2 unit batteries —
  unchanged by this PR, matching main);
  `python3 -m pytest -q` (root-wide, now also collecting the lane's 11 normalizer
  regression tests) → **1138 passed, 0 failed, 0 errors**;
  `python3 -m compileall scripts modules/document/bcdoc modules/interchange/bcio
  modules/commands/bccmd modules/drafting/bcdraft modules/drawings/bcdraw
  modules/agent/bcagent -q` → rc 0;
  `python3 scripts/build_extension.py` → built `blender_cad-0.2.0.zip` (67 files,
  250,274 bytes; **zero experiments/solidcraft entries** in the package) and
  `python3 scripts/build_extension.py --check` → green;
  `python3 scripts/render_inventory.py --check` → in sync.
  These are exactly the five checks the repo CI workflow ("Repo consistency and unit
  batteries") runs; the close-out head SHA and CI run URLs are recorded in the PR.
- Blender 5.2.2 acceptance battery: **not re-run — no production-facing file was
  touched** (the issue requires it only in that case); the standing in-Blender evidence
  remains main's `modules/testing/blender/acceptance_m2_result.json` (59/59, plus the
  M1 battery re-run 30/30 recorded in the same M2 commit).
- A dev-host pytest hazard found and fixed at close-out: re-running the MCP probe
  leaves mode-000 permission-fixture directories under the gitignored `scratch/`,
  which broke root-wide pytest *collection* on the authoring host (6 PermissionErrors,
  never on a clean checkout). The lane now carries `experiments/solidcraft/conftest.py`
  (pytest scope guard: scratch/.upstream/.release/harness excluded from collection) —
  the recorded root-wide command works identically on clean checkouts and re-run hosts.

## 11. References

- Issue #1 (canonical task) and the PR from `tl2/solidcraft-evaluation`.
- `experiments/solidcraft/README.md` (isolation + reproduction), `results/README.md`
  (envelope schema).
- Findings: `experiments/solidcraft/findings/{w1-sketch, w2-history, w2-kernel,
  w3-mcp, w3b-supply-chain}.md`.
- `docs/00-architecture/component-adoption-matrix.md` §4.2 (SolidCraft row + gates),
  `docs/00-architecture/license-inventory.md` §2.1 (evaluation rows),
  `docs/30-process/completion-graph-solidcraft-evaluation.md` (ticks-with-evidence).
- ADR-0002 (kernel — affirmed), ADR-0004 (agent sidecar — unaffected),
  ADR-0006 (skills — v1 stays authoritative).
