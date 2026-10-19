# Documentation Index

- **Status:** Active — M0 handoff document set complete
- **Owner:** TL
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)

**Read `docs/GLOSSARY.md` first.** It is the binding vocabulary; every other
document defers to it. Suggested reading order after the glossary:

1. Root `README.md` — mission, repo map, honest M0 status.
2. `docs/00-architecture/` — how the system is built, synced and licensed.
3. `docs/10-product/` — what we are building (inventory, compatibility, UX).
4. `docs/20-agent/` — agent runtime, tool contract, skills.
5. `docs/30-process/` — how we verify and deliver.

## Index

| Path | One-liner |
|---|---|
| `GLOSSARY.md` | **Binding vocabulary**: mission, repo map, modules, inventory schema, agent/skill terms, manifest schema, workers, milestones (read first, always) |
| `00-architecture/repo-and-upstream-sync.md` | The three-repo layout, upstream pins, and the full upstream update procedure |
| `00-architecture/document-model-and-geometry-kernel.md` | CAD document model (entities, transactions, undo, checkpoints) and the OCCT-based kernel design |
| `00-architecture/component-adoption-matrix.md` | Candidate components (OCCT, ezdxf, LibreDWG, …) with adoption gates, alternatives and decisions |
| `00-architecture/license-inventory.md` | License facts with confidence tags; the GPL-compliance record |
| `10-product/feature-parity-inventory.md` | Inventory methodology: areas, priorities, status/evidence rules (hand-authored) |
| `10-product/inventory-tables.md` | **Generated** feature tables from `data/inventory/*.yaml` — do not edit by hand |
| `10-product/file-compatibility-matrix.md` | Which file formats/versions we read, write and round-trip, and how losses are ledgered |
| `10-product/ux-specification.md` | AutoCAD-familiar interface specification: command line, ribbon, palettes, drafting behavior |
| `10-product/usability-validation-plan.md` | Comparative usability program: participants, task batteries, thresholds, evidence |
| `20-agent/zcode-adaptation-plan.md` | How the ZCode runtime becomes our agent sidecar (candidate/excluded packages, seams) |
| `20-agent/cad-tool-contract-v1.md` | The `cad.*` tool namespaces, versioned contract v1 |
| `20-agent/permissions-and-execution-model.md` | Agent modes, permission classes, execution pipeline states, shared-document terms |
| `20-agent/skill-format-v1.md` | Skill package format: skill.yaml, workflow.yaml, tests/, typed inputs, provenance |
| `20-agent/skill-execution-and-publishing.md` | Skill pipeline (draft→published), sandboxing, trust tiers, registry |
| `30-process/adr/0001`–`0006` | Architecture decision records: naming, OCCT kernel, DXF-first, ZCode interface-first, GPL strategy, declarative skills |
| `30-process/test-plan.md` | Executable test plan: TP-CAT-00…12, gates, evidence policy |
| `30-process/upstream-update-ci.md` | The three CI workflows, drift-alert issue policy, local commands, audit checklist |
| `30-process/milestone-plan.md` | M0–M7 objectives, entry/exit criteria, risk register, estimation honesty |
| `30-process/completion-graph-m0.md` | The M0 completion graph — ticks with TP-CAT-00 evidence only |

## Conventions

- Every document starts with a status block (status / owner / date / glossary
  link) per glossary §13.
- Features are cited by name + area; concrete feature ids are forbidden in
  hand-authored docs (a CI test enforces traceability).
- Generated files (`10-product/inventory-tables.md`) are never edited by
  hand; regenerate with `python3 scripts/render_inventory.py`.

## M1 additions (2026-10-19)

- `10-product/scope-expansion-m1.md` — product-scope expansion record (BIM, QTO, RCM areas; interop limitations)
- `00-architecture/m1-module-contracts.md` — binding cross-worker implementation contracts for M1
- `00-architecture/kernel-bindings-evaluation-m1.md` — OCCT/OCP kernel binding evaluation record
- `20-agent/zcode-runtime-spike-m1.md` — ZCode runtime compatibility spike at the pinned tree
- `30-process/adr/0007-zcode-fork-realignment.md` — ZCode fork realignment decision
- `30-process/completion-graph-m1.md` — M1 completion graph (test-backed)

## TL2 SolidCraft evaluation additions (2026-10-19 UTC, issue #1)

- `00-architecture/solidcraft-evaluation.md` — **TL2 decision record**: source audit, seven-candidate scorecard with gates, limitations, next-PR scope (all recommendations provisional — nothing adopted)
- `30-process/completion-graph-solidcraft-evaluation.md` — evaluation completion graph (ticks with committed evidence only)
- `experiments/solidcraft/` — isolated experiment lane (not product code): reproducible harnesses/drivers/fixtures/results + per-lane findings docs + close-out regression tests for the comparison normalizer
