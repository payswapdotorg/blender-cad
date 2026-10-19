# Milestone Plan — M0 … M7

- **Status:** Active — sequencing committed at M0; no calendar promises (see §12)
- **Owner:** TL
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)

## 1. How to read this plan

Milestones M0–M7 expand the glossary §11 one-liners. Each entry has: Objective,
Entry criteria, Exit criteria (test-backed — every exit cites TP-CAT-NN from
docs/30-process/test-plan.md), Deliverables, Owner split (glossary §10),
Risks, and Dependencies. A milestone exits when its criteria are met — not
when a date passes.

## 2. Milestone map

```mermaid
graph LR
    M0[M0 handoff] --> M1[M1 walking skeleton]
    M1 --> M2[M2 drafting core]
    M2 --> M3[M3 precision and parametrics]
    M3 --> M4[M4 interop and toolsets]
    M4 --> M5[M5 agent integration]
    M5 --> M6[M6 skills]
    M6 --> M7[M7 usability and hardening]
```

---

## 3. M0 — Handoff & architecture (this commit)

- **Objective:** establish the three repos with pinned upstreams, the binding
  vocabulary, the full M0 document set (architecture, inventory, UX, agent &
  skills, process), module scaffolding, and an executable repo-consistency CI.
- **Entry criteria:** repos exist under `payswapdotorg`; mission brief
  received; upstream pins verified against live upstreams (2026-10-19).
- **Exit criteria:** all M0 deliverables merged; **TP-CAT-00 repo-consistency
  suite green** (the only suite that exists at M0); generated inventory tables
  committed and in sync. Recorded in docs/30-process/completion-graph-m0.md.
- **Deliverables:** the 11 initial deliverables (README.md §"M0 deliverables"):
  repos & pins, glossary, architecture docs, adoption matrix + license
  inventory, ADRs 0001–0006, feature-parity inventory (14 areas), file
  compatibility matrix, UX specification + usability validation plan, agent &
  skills design, process suite (this plan, test plan, upstream CI, completion
  graph), module scaffolding + executable CI.
- **Owner split:** TL — glossary, integration, LICENSE, final gates; W1 — UX &
  command-side docs; W2 — core engineering docs (document model, kernel,
  adoption matrix); W3 — agent & skills docs; process/scaffold docs (this set)
  by the doc-engineer under TL direction.
- **Risks:** document drift against the glossary (mitigated: glossary is
  binding, CI vocabulary checks); inventory id collisions (mitigated: global
  uniqueness check in CI); parallel-author collisions (mitigated: glossary §12
  file map — each task writes only its listed files).
- **Dependencies:** none.

## 4. M1 — Walking skeleton

> **Status (2026-10-19): M1 EXITED** — all acceptance requirements verified with
> test evidence; per-item status, deviations and the honest not-done list in
> [completion-graph-m1.md](completion-graph-m1.md).

- **Objective:** the extension loads in Blender; the CAD workspace shell exists;
  the command-line state machine works; LINE/CIRCLE/ARC plus basic modify
  operations run; document model v0 with DXF read/write via ezdxf.
- **Entry criteria:** M0 exit; **Actions enabled on the Blender fork** (patch
  apply-check); headless `bpy` container image buildable; ezdxf and OCCT
  bindings (OCP) adoption gates passed per the component adoption matrix.
- **Exit criteria:** TP-CAT-01 skeleton sections green (command registry,
  prompt state machine, basic entity creation/modify); **TP-CAT-06 first
  native-Blender regression baseline green**; TP-CAT-11 drift workflows live;
  document-model unit tests green; DXF read/write smoke round-trip green
  (precursor sections of TP-CAT-04).
- **Deliverables:** `document` v0 (entities, transactions, undo journal);
  `commands` registry + prompt state machine + aliases; `shell` v0 (command-line
  dock, status bar, minimal palettes); `drafting` LINE/CIRCLE/ARC + basic
  modify; `interchange` DXF R/W on ezdxf; kernel bindings evaluation concluded
  (OCCT/OCP decision recorded per the adoption matrix); fork apply-check
  workflow (workflow_dispatch) live.
- **Owner split:** W2 — document model, DXF R/W, kernel bindings evaluation;
  W1 — commands, shell, drafting UX; W3 — sidecar interface spike (ADR-0004
  seam), security design notes (non-blocking); TL — integration gates,
  TP-CAT-06 baseline, upstream CI.
- **Risks:** `bpy` container complexity (mitigation: pin the image in the
  manifest; headless-first test design); ezdxf version/feature mapping
  (mitigation: DXF-first strategy, ADR-0003); fork patch pipeline friction
  (mitigation: patch series is empty at M0 and expected to stay minimal).
- **Dependencies:** adoption gates for ezdxf, OCP; fork Actions enablement.

## 5. M2 — Drafting core parity

- **Objective:** osnap/ortho/polar/tracking/dynamic input; layers/blocks; dims
  & annotations; layouts + PDF publish; xrefs (DXF).
- **Entry criteria:** M1 exit; P0 inventory entries for the drafting areas
  groomed into suite plans (each P0 item mapped to at least one test).
- **Exit criteria:** **TP-CAT-01 full category green** (all P0 commands
  exercised); TP-CAT-02 precision/geometry sections green; TP-CAT-03
  annotation sections green; TP-CAT-04 DXF round-trip sections green;
  TP-CAT-06 green on the M2 build.
- **Deliverables:** precision-input engine (osnap/ortho/polar/tracking,
  dynamic input); layer/block organization behaviors; annotation engine v1
  (text, dimensions, tables, hatches); layouts, viewports, PDF publish; DXF
  xrefs; grip editing and selection refinement.
- **Owner split:** W1 — precision input UX, layers/blocks UX, annotation UX,
  layouts/publish; W2 — constraint-ready document semantics, xref engine,
  drafting geometry side; TL — milestone gate, regression re-run, drift triage.
- **Risks:** annotation associativity complexity (mitigation: TP-CAT-03
  regeneration tests from the start, not retrofitted); scope creep beyond P0
  (mitigation: inventory priorities are the contract; P1/P2 items are tracked,
  not silently pulled in).
- **Dependencies:** M1 document model stability; PDF publish tooling decision
  (Blender-native vs library — recorded as needed).

## 6. M3 — Precision & parametrics

- **Objective:** OCCT integration live; constraints (PlaneGCS); 3D solids;
  parametric edits; DWG read (LibreDWG).
- **Entry criteria:** M2 exit; OCCT/OCP packaging gates passed (performance
  and packaging per the adoption matrix); PlaneGCS license verification done
  (`(verify)` tags resolved at the adoption gate).
- **Exit criteria:** TP-CAT-02 full category green (kernel accuracy + solver
  convergence); TP-CAT-04 DWG-read sections green; TP-CAT-03 layout/plot
  sections green as they land; TP-CAT-06 green.
- **Deliverables:** `kernel` live (precise B-rep + tessellation); 3D modeling
  operations; `parametric` constraint solver + parametric editing; DWG read
  via LibreDWG; STEP exploration begins (per interchange strategy, ADR-0003).
- **Owner split:** W2 — kernel integration, constraints, DWG read; W1 — 3D
  modeling UX, parametric editing UX; TL — gates, upstream churn triage
  (weekly drift expected), packaging builds.
- **Risks:** OCP packaging/performance (mitigation: M1 entry evaluation,
  fallback candidates evaluated and recorded per the adoption matrix);
  PlaneGCS licensing (mitigation: verify before adoption, no unverified
  adoption); DWG reader edge cases (mitigation: loss ledger + corpus).
- **Dependencies:** OCCT binding adoption; LibreDWG adoption; M2 drafting core.

## 7. M4 — Interop conformance & toolsets scaffold

- **Objective:** DWG write + round-trip suite; IFC/BIM bridge; toolset
  libraries begin (mechanical/electrical/MEP…).
- **Entry criteria:** M3 exit; DWG write path functional in development
  builds; IfcOpenShell + Bonsai adoption gates passed.
- **Exit criteria:** **TP-CAT-04 full round-trip conformance green**;
  **TP-CAT-05 green** (IFC validation + toolset smoke suites); TP-CAT-03
  complete (technical documentation); TP-CAT-06 green.
- **Deliverables:** DWG write; round-trip golden corpus + loss ledger in CI;
  `bim` bridge (Bonsai + IfcOpenShell); **BIM architecture workflows begin
  (element modeling through the bim module per FP-BIM P1 items —
  scope-expansion-m1.md §2)**; first toolset libraries with mutually
  independent sub-packages; TS inventory P1/P2 grooming.
- **Owner split:** W2 — DWG write, IFC/BIM bridge, BIM architecture
  workflows; W1 — toolset libraries;
  TL — conformance gates, corpus licensing review.
- **Risks:** DWG write fidelity (register risk R1, §10); toolset scope sprawl
  (R8); corpus licensing (mitigation: per-file license notes, self-authored
  fixtures preferred).
- **Dependencies:** LibreDWG write maturity; IfcOpenShell/Bonsai adoption; M3.

## 8. M5 — Agent integration

- **Objective:** ZCode runtime sidecar; CAD tool contract v1 live; permissions;
  shared-document conflict model.
- **Entry criteria:** M4 exit; **ZCode source audit completed** (glossary §6 —
  may re-scope runtime candidates; any re-scoping recorded as an ADR
  amendment); pinned audited ZCode ref (no `pending:` refs remain in the
  manifest).
- **Exit criteria:** **TP-CAT-07 green** — cad.* contract conformance,
  state-sync invariants (`doc_version`, `selection_epoch`, `entity_lock`),
  conflict handling, checkpoint rollback; TP-CAT-06 green; TP-CAT-11 current.
- **Deliverables:** sidecar runtime (ADR-0004 seam: `packages/rpc`-derived
  versioned interface); `cad.*` tool contract v1 server; permission broker
  (modes + permission classes, glossary §6); activity log; MCP adapter;
  **QTO/BOQ/estimating core (FP-QTO P1 — scope-expansion-m1.md §3)**.
- **Owner split:** W3 — sidecar, contract, permissions, conflict model; W2 —
  document lock/version hardening; W1 — shell agent surfaces; TL — audit gate,
  integration.
- **Risks:** ZCode API drift (R4); agent security incidents (R7 — mitigated by
  permission classes, transactions, rollback, and the fact that agents mutate
  documents only via the contract).
- **Dependencies:** audited ZCode pin; M4 document model maturity.

## 9. M6 — Skills

- **Objective:** record→generalize authoring; skill format v1 engine;
  registry/publishing MVP.
- **Entry criteria:** M5 exit; skill format v1 spec frozen (ADR-0006;
  docs/20-agent/skill-format-v1.md).
- **Exit criteria:** **TP-CAT-08 green** (creation, portability, versioning,
  validation) and **TP-CAT-09 green** (security, permissions, dependency
  integrity — including the malicious-skill corpus); TP-CAT-06 green.
- **Deliverables:** authoring pipeline (draft → recorded → generalized →
  tested → published); package format engine (skill.yaml, workflow.yaml,
  typed inputs, provenance + SHA-256); sandboxed execution; registry client +
  publishing MVP; command-line skill registration hook live (glossary §4
  inversion note); **reality capture + defect/repair/maintenance records
  (FP-RCM P1 — scope-expansion-m1.md §4)**.
- **Owner split:** W3 — skills end-to-end; W1 — command-line/UX integration of
  the skill hook; TL — security gate before registry MVP is declared usable.
- **Risks:** sandbox escape (R7); skill portability overkill (mitigation:
  declarative-first DSL, ADR-0006, scripts exceptional and gated).
- **Dependencies:** M5 contract; format v1 freeze.

## 10. M7 — Usability validation & hardening

- **Objective:** AutoCAD-user comparative testing program; regression fixes;
  release gates for 1.0.
- **Entry criteria:** M6 exit; packaged installers exist; usability thresholds
  frozen in docs/10-product/usability-validation-plan.md.
- **Exit criteria:** **Release gate (test-plan §6.3): all twelve TP categories
  green**; TP-CAT-10 thresholds met; TP-CAT-12 packaged E2E green on all
  supported platforms; every inventory flip in the cycle carries evidence.
- **Deliverables:** comparative usability program results + reports; regression
  fixes; 1.0 release manifests; packaged, signed artifacts; final completion
  graph for 1.0.
- **Owner split:** W1 — usability program execution; W2/W3 — hardening fixes in
  their modules; TL — release gates, manifest, packaging sign-off.
- **Risks:** late usability-gap discovery (R6 — mitigated by formative
  sessions from M2 onward per the usability plan); release pressure vs honesty
  rules (mitigated: statuses flip only with evidence; glossary §1 wins).
- **Dependencies:** all prior milestones; packaging pipeline.

## 11. Integration & regression gates between milestones

At every milestone boundary (M1→M2, …, M6→M7), before the next milestone's
scope opens:

1. **Native-Blender regression (TP-CAT-06)** re-run on the milestone build —
   zero regressions vs the recorded baseline.
2. **Cumulative suite re-run:** every category activated so far is green
   (suites never rot — a previously-green category that went red is a
   milestone-blocking defect, not a footnote).
3. **Upstream currency (TP-CAT-11):** drift green or consciously triaged with
   a dated decision on the issue.
4. **Completion graph published:** `docs/30-process/completion-graph-m<N>.md`
   with per-item status; ticks only for test-passed items (§12).
5. **Inventory honesty pass:** every status flip in the milestone's cycle is
   backed by a TP id + evidence artifact; `render_inventory.py --check` green.

## 12. Completion-graph policy

- Every milestone report shows **per-item status** for its deliverables.
- **Ticks (✅) ONLY for items that passed documented acceptance tests** — an
  item with no test has no tick, however "done" it feels.
- M0's graph is `docs/30-process/completion-graph-m0.md` — the tick evidence
  there is the TP-CAT-00 repo-consistency suite, which is the only thing green
  at M0.
- Subsequent milestones publish `completion-graph-m<N>.md` in the same
  directory, citing their TP-CAT evidence per §11 above.

## 13. Program risk register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | **DWG write fidelity** — LibreDWG's write path is younger than its reader; round-trip gaps may surface late (M4) | High — file compatibility is acceptance criterion 1 | DXF-first strategy (ADR-0003); golden round-trip corpus + loss ledger from M2; DWG-write gate at M4 only after corpus passes; gaps are ledgered, never hidden |
| R2 | **OCCT binding performance/packaging** — OCP wheel size, ABI stability, per-platform builds | High — the precise-geometry promise rests on it | M1 entry evaluation with explicit gates (adoption matrix); fallback candidates evaluated and recorded; no silent dependency on an unvetted binding |
| R3 | **Blender upstream churn** — weekly upstream movement breaks fork/extension surfaces | Medium | pinned main + weekly drift CI (deduped issue); minimal-patch policy (series empty at M0); extension code isolated in this repo; re-pin is a versioned, evidenced event |
| R4 | **ZCode upstream API drift** — runtime contract changes under us | Medium | sidecar with versioned interface (ADR-0004); monthly audit = automated sha check + human API-surface review (upstream-update-ci §6); breaking changes open an adapter window before adoption |
| R5 | **GPL compliance discipline** — Blender host is GPL-2.0+; extension must remain compatible; LibreDWG is GPL-3.0 | High — legal | ADR-0005 (GPL-3.0-or-later for this repo); license inventory as the compliance record; per-dependency adoption gates; licensing-clean fixtures only |
| R6 | **Usability gap discovery late** — summative testing only at M7 could reveal deep UX debt | High — acceptance criterion 2 | formative sessions run from M2 per docs/10-product/usability-validation-plan.md; M7 is summative; every failed task becomes a triaged issue, not an anecdote |
| R7 | **Agent security incidents** — a compromised or malicious skill mutating engineering documents | High | permission classes + modes (glossary §6); transactions + checkpoints make every agent action rollback-able; TP-CAT-09 malicious corpus blocking before registry MVP; skills untrusted until validated |
| R8 | **Toolset and specialist scope sprawl** — seven specialist toolsets plus the M1 scope-expansion areas (BIM/QTO/RCM, scope-expansion-m1.md) × deep parity is enormous; more breadth for the same capacity (TL + 3 workers) | High | inventory priorities (P0/P1/P2) gate scope — the new areas carry no P0; toolsets and BIM land after the conformance core (M4+), QTO at M5, RCM at M5–M6; no toolset→toolset coupling (independent sub-packages); per-area exit criteria in the inventory; scope decisions recorded per milestone |
| R9 | **Capacity** — TL + 3 workers for a program of this breadth | High | sequencing-only plan, P0-first ordering; module ownership keeps lanes clean (glossary §10); scope decisions recorded per milestone; no calendar commitments to break |
| R10 | **Sandbox honesty enforcement** — agents (and humans under deadline pressure) produce plausible-but-unverified "done" claims | High — credibility | statuses flip only with TP id + evidence artifact (glossary §5, test-plan §7); CI drift-checks generated tables; completion-graph ticks only for test-passed items; agent claims are never acceptance evidence |

## 14. Estimation honesty

This plan is **sequencing only**. There are no durations, no due dates and no
team-size arithmetic beyond the stated capacity (TL + 3 workers, glossary
§10). Milestones exit on criteria, not on calendars; the only date in this
document is the M0 handoff date. Any calendar estimate belongs to a separate,
clearly-labeled planning exercise and does not modify this file's gates.
