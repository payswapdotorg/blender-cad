# Test Plan — Executable Acceptance & Regression Program

- **Status:** Active — M0 handoff baseline; TP-CAT-00 is live in CI, all other categories activate with their milestones
- **Owner:** TL (per-category owners listed below, per glossary §10)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)

## 1. Purpose and honest scope

This is the executable test plan for Blender CAD. It defines twelve fixed
assurance categories (TP-CAT-01 … TP-CAT-12), each with purpose, suite
location, fixtures, tools, pass criteria, owner and blocking milestone —
plus the three acceptance gates and the evidence-artifact policy governing
when a feature inventory entry may flip status.

**Honest scope at M0 (binding).** Nothing in the product is implemented at
M0. The only executable suite is the repository-consistency suite,
**TP-CAT-00**: `ci.yml` running `tests/test_repo_consistency.py` — the M0
acceptance evidence (glossary §11). Every other category below is a *plan*,
not a suite: its suite is created where its subject matter lands.

## 2. Category register (fixed numbering)

| ID | Category | Owner | Suite home | Blocking from |
|---|---|---|---|---|
| TP-CAT-00 | Repo consistency (M0 acceptance) | TL | `tests/` | M0 (now) |
| TP-CAT-01 | Drafting & command-system functional | W1 (W2: drafting geometry side) | `modules/commands/tests/`, `modules/drafting/tests/`, `modules/shell/tests/` | M1–M2 window |
| TP-CAT-02 | Precise geometry & constraint-solver | W2 | `modules/kernel/tests/`, `modules/parametric/tests/` | M1–M2 window (solver sections at M3 entry) |
| TP-CAT-03 | Drawing regeneration & technical documentation | W1 | `modules/drawings/tests/` | M2–M4 window |
| TP-CAT-04 | DWG/DXF import/export round-trip conformance | W2 | `modules/interchange/tests/` + `modules/testing/roundtrip/` | M2–M4 window (full suite at M4) |
| TP-CAT-05 | BIM, QTO/asset & specialist toolset | W2 (bim, qto, asset), W1 (toolsets) | `modules/bim/tests/`, `modules/qto/tests/`, `modules/asset/tests/`, `modules/toolsets/tests/` | M4 (BIM); M5–M6 (QTO/asset sections) |
| TP-CAT-06 | Native Blender regression | TL (+ W2) | `modules/testing/blender-regression/` | M1 onward, every release |
| TP-CAT-07 | Agent tool correctness, state-sync, conflict, rollback | W3 | `modules/agent/tests/` + `modules/testing/agent-contract/` | M5 |
| TP-CAT-08 | Skill creation, portability, versioning, validation | W3 | `modules/skills/tests/` | M6 |
| TP-CAT-09 | Skill security, permissions, dependency-integrity | W3 | `modules/skills/tests/security/` + `modules/testing/security/` | M6 |
| TP-CAT-10 | Comparative AutoCAD usability | W1 program, TL gate | `modules/testing/usability/` | M7 |
| TP-CAT-11 | Blender & ZCode upstream-update | TL | `.github/workflows/` + `modules/testing/upstream/` | Continuous from M1 |
| TP-CAT-12 | End-to-end packaged application | TL | `modules/testing/e2e/` | M7 |

"Blocking from" marks the window in which sections activate as their subject
matter lands; a section whose subject lands later is reported `not-applicable`
until then — never silently skipped.

## 3. Conventions

- **Suite locations.** Module-owned suites: `modules/<module>/tests/`,
  authored by the module owner (glossary §10). Cross-module suites:
  `modules/testing/` (TL). Root suite: `tests/` — TP-CAT-00, the M0 gate.
- **Naming and traceability.** pytest-style `test_*.py`. Feature inventory
  `test:` fields reference a TP-CAT id, optionally with suite path + test
  name. A `verified` status requires the `test` field plus a recorded
  evidence artifact (§7) — no id, no artifact, no flip.
- **CI wiring.** `ci.yml` runs TP-CAT-00 on every push and pull request (the
  merge gate) and grows as categories activate; the headless `bpy` job
  appears at M1. The two `upstream-*` workflows implement the automated half
  of TP-CAT-11 (docs/30-process/upstream-update-ci.md).

## 4. Tools and frameworks

- **pytest** — unit and contract tests; the default framework for all suites.
- **Headless Blender (`bpy`) container** — integration and UI-touching tests
  from M1; one pinned image per release manifest; no display needed.
- **Golden-file comparison** — TP-CAT-04 round-trip conformance and TP-CAT-03
  published-output checks: normalize → serialize → byte-compare; deviations go
  to the loss ledger; regeneration is always a reviewable diff.
- **Mocked model providers** — TP-CAT-07/08/09 agent tests run against
  deterministic scripted model responses; **real OpenRouter runs are optional,
  non-blocking experiments** and never acceptance evidence.
- **Scripted harness** — TP-CAT-12 packaged-app E2E on clean OS images.

## 5. Category definitions

### TP-CAT-00 — Repo consistency (M0 acceptance)

- **Purpose:** the repository is internally consistent: inventory YAML valid per glossary §5 and rendered tables in sync; manifests valid per §8; module graph valid per §4; every feature id cited in docs traceable; no secrets.
- **Suites:** `tests/test_repo_consistency.py` (six tests), run by `ci.yml`.
- **Fixtures:** the repository itself; no external fixtures.
- **Tools:** pytest, PyYAML, subprocess to the validation scripts.
- **Pass criteria:** all six tests green; exit 0 from every script.
- **Owner:** TL. **Blocking from:** M0 — this is the M0 exit gate (glossary §11).

### TP-CAT-01 — Drafting & command-system functional

- **Purpose:** command registry, aliases, prompt state machine, dynamic input, entity creation and modify behavior, selection, grips behave as specified (command-system, 2D-entities, modify, precision-input, organization areas).
- **Suites:** `modules/commands/tests/`, `modules/drafting/tests/`, `modules/shell/tests/`; cross-module walkthroughs in `modules/testing/functional/` (from M2).
- **Fixtures:** small synthetic documents; recorded command transcripts (inputs → expected entities); scripted UI sessions.
- **Tools:** pytest; from M1 the headless `bpy` container for UI-touching tests.
- **Pass criteria:** suite green; at M2 exit every P0 drafting/command-system inventory command has at least one automated test.
- **Owner:** W1 (commands, drafting UX, shell); W2 co-owns drafting geometry-side tests. **Blocking from:** M1–M2 window — skeleton sections block M1 exit; the full category blocks M2 exit.

### TP-CAT-02 — Precise geometry & constraint-solver

- **Purpose:** numerical correctness of the geometry kernel (B-rep and analytic ops, tessellation tolerances) and constraint-solver behavior (satisfaction, convergence, parametric-edit stability).
- **Suites:** `modules/kernel/tests/`, `modules/parametric/tests/`.
- **Fixtures:** golden B-rep dumps; solver benchmark sets; tolerance vectors.
- **Tools:** pytest with tolerance-based numerical assertions; golden-geometry comparison; solver timing budgets.
- **Pass criteria:** assertions within the documented kernel epsilon policy; benchmarks converge within budget; nothing skipped without a recorded `not-applicable` reason.
- **Owner:** W2. **Blocking from:** M1–M2 window for precision/geometry sections; solver sections at M3 entry; full category blocks M3 exit.

### TP-CAT-03 — Drawing regeneration & technical documentation

- **Purpose:** annotation (text, dimensions, tables, hatches) stays associated and correct when model geometry changes; layouts, viewports, annotation scale; plot/publish output is reproducible.
- **Suites:** `modules/drawings/tests/`.
- **Fixtures:** reference drawings with expected annotation state; expected published PDFs for structural comparison.
- **Tools:** pytest; PDF text/vector extraction (structural checks, not fragile pixel diffs).
- **Pass criteria:** regeneration idempotent after edits; associativity rules hold; published output structurally matches the golden artifacts.
- **Owner:** W1. **Blocking from:** M2–M4 window — annotation sections block M2 exit; layout/plot sections at M3–M4; full category by M4.

### TP-CAT-04 — DWG/DXF import/export round-trip conformance

- **Purpose:** files in → files out preserve engineering content: load a fixture, save it, reload it, compare (geometry + properties). Every loss is recorded in the loss ledger; nothing degrades silently.
- **Suites:** `modules/interchange/tests/` (engine-level) plus the golden corpus suite `modules/testing/roundtrip/`.
- **Fixtures:** licensing-clean DWG/DXF corpus (self-authored or redistribution-permitted, per-file license recorded) with round-trip expectations per fixture.
- **Tools:** pytest golden-file comparison; ezdxf audit (DXF); LibreDWG (DWG); normalized serialization before byte-compare.
- **Pass criteria:** declared round-trip matrix green; corpus processed without crashes; every deviation ledgered.
- **Owner:** W2. **Blocking from:** M2–M4 window — DXF sections from M2, DWG-read from M3; full round-trip conformance blocks M4 exit.

### TP-CAT-05 — BIM, QTO/asset & specialist toolset

- **Purpose:** BIM workflows through Bonsai + IfcOpenShell produce valid IFC; QTO takeoff and estimate workflows reproduce reference quantities within documented unit rules; asset (RCM) records stay referentially intact (registry links, defect markers, work-order export round-trip); toolset libraries (mechanical, electrical, MEP, plant, civil, GIS, raster) behave correctly and stay mutually independent.
- **Suites:** `modules/bim/tests/`, `modules/qto/tests/` (takeoff accuracy), `modules/asset/tests/` (asset records integrity), `modules/toolsets/tests/` (per-toolset sub-suites); IFC conformance in `modules/testing/bim/`.
- **Fixtures:** sample IFC files; known-quantity takeoff models and 2D drawings; asset-record sample sets with defect/grading history; per-toolset corpora (symbol libraries, part lists, geospatial samples).
- **Tools:** pytest; IfcOpenShell validation; quantity comparison against reference tallies; record-integrity assertions; boundary checks assert no cross-toolset coupling.
- **Pass criteria:** IFC validation clean on the fixture set; takeoff quantities match references within the documented unit-rule tolerances; asset record sets re-import with zero record loss; toolset smoke suites green; the no-toolset-to-toolset rule holds.
- **Owner:** W2 (bim, qto, asset), W1 (toolsets). **Blocking from:** M4 (BIM sections — scope-expansion-m1.md §2); QTO sections at M5 and asset/RCM sections at M5–M6 (scope-expansion-m1.md §3–§4; milestone-plan §8–§9). The category count stays 12; the scope-expansion areas extend this category, they do not add a new one.

### TP-CAT-06 — Native Blender regression

- **Purpose:** the extension and the fork's patch series must not break stock Blender — glossary §1 requires *retaining all Blender capabilities*.
- **Suites:** `modules/testing/blender-regression/`.
- **Fixtures:** minimal `.blend` files; benchmark scenes with recorded baselines.
- **Tools:** headless `bpy` container: load extension, open default scene, run common native operations; verify no crash and no startup regression beyond the declared budget.
- **Pass criteria:** zero regressions vs the recorded baseline for the pinned Blender build; clean load AND unload of the extension.
- **Owner:** TL (+ W2 build/packaging support). **Blocking from:** M1 onward — re-run at every milestone gate and every release.

### TP-CAT-07 — Agent tool correctness, state-sync, conflict, rollback

- **Purpose:** the `cad.*` tool contract behaves as specified; shared-document terms (`doc_version`, `selection_epoch`, `entity_lock`, `checkpoint`) hold under concurrent agent/user activity; rollback restores state.
- **Suites:** `modules/agent/tests/` plus contract conformance in `modules/testing/agent-contract/`.
- **Fixtures:** scripted agent transcripts; concurrency scenarios (two writers, stale `doc_version`, checkpoint rollback); deterministic mocks.
- **Tools:** pytest with mocked model providers; real OpenRouter optional, non-blocking.
- **Pass criteria:** contract conformance 100%; invariants hold under scripted concurrency; rollback restores documented-equivalent state.
- **Owner:** W3. **Blocking from:** M5.

### TP-CAT-08 — Skill creation, portability, versioning, validation

- **Purpose:** the record→generalize authoring pipeline, skill package format v1, semver versioning/resolution, and portability across documents/installs.
- **Suites:** `modules/skills/tests/`.
- **Fixtures:** sample skills across pipeline states (draft → published); version matrices; portability packs.
- **Tools:** pytest; the package validator; the execution engine in sandboxed mode.
- **Pass criteria:** format conformance 100%; version resolution correct across the matrix; portability suite green.
- **Owner:** W3. **Blocking from:** M6.

### TP-CAT-09 — Skill security, permissions, dependency-integrity

- **Purpose:** sandbox containment, permission-class enforcement, dependency and provenance integrity (SHA-256), registry poison resistance.
- **Suites:** `modules/skills/tests/security/` + `modules/testing/security/`.
- **Fixtures:** an in-house-authored malicious skill corpus (escape attempts, permission probes, tampered manifests, dependency substitution).
- **Tools:** pytest; sandboxed execution harness; integrity validator.
- **Pass criteria:** zero escapes on the corpus; every permission class denies by default and requires explicit approval; tampered dependencies rejected.
- **Owner:** W3. **Blocking from:** M6 — this suite must be green before any public registry work is declared usable.

### TP-CAT-10 — Comparative AutoCAD usability

- **Purpose:** experienced AutoCAD users work naturally — measured, not claimed: task batteries, timings, error rates, structured qualitative feedback, per docs/10-product/usability-validation-plan.md.
- **Suites:** `modules/testing/usability/` (harness + protocol artifacts).
- **Fixtures:** task scripts, recording protocol, consent forms; thresholds are defined in the usability validation plan (not restated here).
- **Tools:** moderated test sessions; recorded artifacts (video, logs); scored result sheets.
- **Pass criteria:** the thresholds declared in docs/10-product/usability-validation-plan.md are met; every failed task has a triaged issue.
- **Owner:** W1 (program), TL (gate). **Blocking from:** M7 (summative); formative sessions run earlier per the usability plan and feed fixes.

### TP-CAT-11 — Blender & ZCode upstream-update

- **Purpose:** upstream movement is detected, triaged and adopted deliberately — never silently (glossary §8 pin policy).
- **Suites:** `.github/workflows/upstream-*.yml` (automated sha check) + `modules/testing/upstream/` (post-update regression batteries).
- **Fixtures:** the release manifests (pins); the patch series; upstream snapshots for delta review.
- **Tools:** `scripts/check_upstream_drift.py` in CI; the fork apply-check workflow (M1); post-re-pin runs of TP-CAT-06 + active blocking suites.
- **Pass criteria:** drift checks green or an open triaged issue; apply-check clean (from M1); after any re-pin: manifest version bumped and the post-update regression battery green.
- **Owner:** TL. **Blocking from:** continuous from M1.

### TP-CAT-12 — End-to-end packaged application

- **Purpose:** the packaged application installs, launches and works on clean OS images — the whole product, not the dev tree.
- **Suites:** `modules/testing/e2e/`.
- **Fixtures:** packaged artifacts (per release); sample project corpus.
- **Tools:** scripted harness in clean containers/VMs: install → launch → open sample → golden workflow → save → uninstall.
- **Pass criteria:** golden workflow completes without error; startup within the declared budget; clean uninstall.
- **Owner:** TL. **Blocking from:** M7 (release gate).

## 6. Acceptance gates

### 6.1 Merge gate (every pull request)

CI repo-consistency (TP-CAT-00) green. From M1: the suites of every touched
module are green too. A red merge gate blocks merge — no exceptions, no
"known-red" branches.

### 6.2 Milestone gate

A milestone exits only when: (1) every category mapped blocking for that
milestone (§2) is green; (2) TP-CAT-06 is green on the milestone build; (3)
upstream drift (TP-CAT-11) is green or has an open, triaged issue; and (4)
evidence artifacts (§7) are recorded in the milestone report — the completion
graph (docs/30-process/milestone-plan.md).

### 6.3 Release gate (1.0)

All twelve categories green; TP-CAT-10 usability thresholds met; TP-CAT-12
packaged E2E green on every supported platform; release manifest validated by
`scripts/validate_manifest.py` with pins in sync or consciously re-pinned with
a manifest version bump.

## 7. Evidence artifacts and inventory status flips

- **Artifact kinds:** CI run links, test logs, screenshots and screen
  recordings, usability reports, packaged-artifact checksums.
- **Flip rule (glossary §5, binding):** an inventory entry may move to
  `verified` only when its `test` field references a TP id AND a recorded
  evidence artifact exists, linked in the milestone report — no silent drift.
- **Enforcement:** `scripts/render_inventory.py` enforces the schema
  (`test`/`status` fields and defaults); code review enforces the semantics
  (the artifact must actually exist and actually show the pass).
- **Honesty (glossary §1):** mocks, placeholder panels, dead buttons and
  agent-generated claims are never acceptance evidence for a feature.

## 8. Fixtures and corpus policy

- All fixtures must be licensing-clean (see
  docs/00-architecture/license-inventory.md); no proprietary AutoCAD content
  ships here; corpus files carry a per-file license note. Cross-module corpora
  live under `modules/testing/fixtures/`; module-local fixtures under
  `modules/<module>/tests/fixtures/`.
- Golden files are regenerated deliberately, as reviewable diffs — never
  silently, never by agents without review.

## 9. What this plan does not claim

At M0 there are no product tests: no drafting tests, no geometry tests, no
round-trip corpora, no agent tests. They come into existence with their
milestones, per §2. Until then, "green" means exactly one thing: the
repo-consistency suite is green (TP-CAT-00). See
docs/30-process/completion-graph-m0.md for the honest M0 picture.
