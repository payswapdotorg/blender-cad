# Blender CAD — Authoritative Glossary & M0 Planning Map

- **Status:** Active — binding for all M0 documents
- **Owner:** Technical Lead (TL)
- **Date:** 2026-10-19 (UTC)
- **Rule:** If any document contradicts this file, this file wins. Record the conflict in your worklog entry and follow this file.

---

## 1. Mission (condensed)

Build a complete CAD & engineering application **on top of Blender**, targeting AutoCAD 2027 core functionality plus applicable specialist toolsets, while **retaining all Blender capabilities**. Three equally-important acceptance criteria:

1. **Engineering feature parity** — drafting, geometry, documentation, interchange, automation, specialist toolsets, per the feature inventory.
2. **AutoCAD-familiar usability** — experienced AutoCAD users work naturally (commands, keyboard conventions, workflows, palettes, drafting behavior).
3. **Integrated agentic operation** — ZCode-derived agents usable from inside the CAD app, plus skill authoring/execution/publishing.

**Honesty rules (binding):**
- Do NOT claim AutoCAD parity until the declared feature inventory, file compatibility and usability benchmarks demonstrate it.
- At M0, **nothing is implemented**. Every feature entry is `status: planned`. Never mark anything `verified` without a test ID + recorded evidence artifact.
- Do not count mocks, placeholder panels, dead buttons or agent-generated claims as delivered features.
- The product UI must look and behave like OUR CAD application — familiar AutoCAD interaction patterns are allowed; copying proprietary Autodesk assets or implying we are Autodesk software is forbidden. Likewise do not misrepresent the product as the ZCode IDE or stock Blender.

## 2. Repository map (facts fixed at handoff, 2026-10-19)

| Component | Repository | Role |
|---|---|---|
| Blender fork | `https://github.com/payswapdotorg/blender` | Fork of `blender/blender` (default branch `main`). Host application: build, packaging, launch config, minimal native patch set. Upstream pin: `bf200615b83252a7be951aed5593d068f0f2438a` (blender/blender main, 2026-10-19T09:56Z). License: GPL-2.0-or-later per blender.org — GitHub reports `NOASSERTION` (record both, see §9). |
| ZCode runtime fork | `https://github.com/payswapdotorg/ZCode` | Fork of `zai-org/ZCode` (Apache-2.0, v3.16.1, default branch `main`). Tracked upstream dependency for the agent runtime. Upstream pin: `0a1fc56d279fd1001f78387bd81aec1c26767411` (zai-org/ZCode main, 2026-10-19T02:34Z). Note: GitHub created this fork under the name "Gen" (network-root name cache) and it was renamed to `ZCode` — cosmetic only; parent verified = zai-org/ZCode. |
| CAD extension (this repo) | `https://github.com/payswapdotorg/blender-cad` | **Canonical source of truth**: engineering architecture, feature inventory, API contracts, module packaging, tests, release manifests. The bulk of the CAD engine, toolsets and agent integration live HERE, not in Blender's tree. |

Organization note: repos live under the `payswapdotorg` account at handoff; migration to a dedicated org is a documented non-blocking option.

## 3. Product naming

- Working name: **Blender CAD**. Final product naming is open (ADR-0001); any name must not imply Autodesk affiliation.
- Required disclaimer (use verbatim where licensing/naming is discussed): *"Blender is a registered trademark of the Blender Foundation. AutoCAD, Autodesk and Procore are trademarks of their respective owners. This project is an independent work, not affiliated with or endorsed by any of them."*

## 4. Modules (13) — boundaries, ownership, allowed dependencies

Independently packageable modules live in `modules/`. A module may depend ONLY on modules in its `depends_on` list (checked by `scripts/check_module_boundaries.py`). **No toolset may depend on another toolset's internals**; shared code goes down, not sideways.

| Module | Owner | Depends on | Purpose (one line) |
|---|---|---|---|
| `document` | W2 | (none) | CAD document model: entities, layers, blocks, properties, units, transactions, undo journal, checkpoints. The authoritative engineering model. |
| `kernel` | W2 | document | OCCT-based precise B-rep/analytic geometry + 2D/3D construction ops + tessellation-for-display. |
| `drafting` | W1 | document, kernel | 2D entities, precision-input engine (osnap/ortho/polar/tracking), selection, grips, layers/blocks editing UX. |
| `parametric` | W2 | document, kernel, drafting | Geometric + dimensional constraints, constraint solver, parametric edits. |
| `drawings` | W1 | document, drafting, kernel | Layouts, viewports, dimension/text/table styles, annotation scale, plot/publish. |
| `interchange` | W2 | document, kernel, drafting, drawings | DXF/DWG/IFC/STEP I/O, xrefs, round-trip conformance, loss ledger. |
| `bim` | W2 | document, kernel, interchange | BIM workflows through Bonsai + IfcOpenShell. |
| `toolsets` | W1 | document, drafting, drawings, parametric, kernel | Specialist toolsets: mechanical, electrical, mep, plant, civil, gis, raster (sub-packages, mutually independent). |
| `commands` | W1 | document, drafting, drawings, parametric, interchange, toolsets | Command registry, aliases, prompt state machine, command history, dynamic input. |
| `agent` | W3 | document | CAD tool contract (`cad.*` tools), MCP adapter, runtime sidecar bridge, activity/permissions plumbing. |
| `skills` | W3 | agent, document, commands | Skill authoring (record→generalize), package format, execution engine, registry client. |
| `shell` | W1 | commands, drafting, drawings, toolsets, agent, skills, document | CAD application shell: ribbon, palettes, status bar, command-line dock, workspace integration with Blender. |
| `testing` | TL | (all — test-only, exempt from cycle rules) | Regression, interop, usability and security suites + fixtures. |

**Recorded decision (dependency inversion):** `commands` does NOT depend on `skills`. Skills depend on commands (a skill step may invoke a command through the registry). The command line exposes installed skills through a **registration hook**: `skills` registers itself into `commands` at load time. This keeps the graph acyclic (skills→commands, not commands→skills) while preserving the familiar "type a skill name in the command line" UX.

## 5. Feature-parity inventory vocabulary

### Areas (14) — each has one YAML file `data/inventory/<area>.yaml`

| Area | Title | Owning module (use in YAML `module:`) | File |
|---|---|---|---|
| CMD | Command system | commands | cmd.yaml |
| DRAW | 2D drawing entities | drafting | draw.yaml |
| MOD | Modify operations | drafting | mod.yaml |
| PREC | Precision input & snaps | drafting | prec.yaml |
| ORG | Layers, blocks, organization | drafting | org.yaml |
| ANN | Annotation (text, dims, tables, hatches) | drawings | ann.yaml |
| LAY | Layouts, viewports, plot/publish | drawings | lay.yaml |
| P3D | 3D modeling | kernel | p3d.yaml |
| PAR | Parametric constraints | parametric | par.yaml |
| IO | Interchange & file compatibility | interchange | io.yaml |
| TS | Specialist toolsets | toolsets | toolsets.yaml |
| UX | AutoCAD-familiar interface conventions | shell | ux.yaml |
| AGT | Integrated agent operation | agent | agent.yaml |
| SKL | Skills & automation | skills | skills.yaml |

### ID scheme

`FP-<AREA>-<NNN>` (e.g. `FP-DRAW-001`). Unique across ALL areas. IDs are permanent — never renumber.

### Status enum + evidence rule

`planned | in-progress | partial | blocked | verified`
- At M0 EVERY entry is `planned` with `test: ""`.
- `verified` requires a non-empty `test` referencing a `TP-*` test-plan ID AND a recorded evidence artifact (test run log/screenshot link).

### Priority definitions

- **P0** — core baseline: routine professional drafting; absence blocks M2 exit (drafting core).
- **P1** — common professional workflows (documentation, layouts, common interop).
- **P2** — advanced/specialist (toolset-specific, dynamic blocks, rare interop paths).

### YAML schema (EXACT — all M0 authors follow this)

```yaml
area: DRAW
title: 2D drawing entities
module: drafting
entries:
  - {id: FP-DRAW-001, name: LINE, desc: "Two-point line with chained continuation; Close/Undo options", p: P0, dep: [], status: planned, test: "", note: ""}
```

Binding format rules:
- One entry per line, flow-style map as shown. **Double-quote** every `desc`, `test`, `note` value (colons inside values must not break YAML).
- `name` — AutoCAD command name where the entry is a command (e.g. `LINE`); otherwise a short feature name (e.g. `Ribbon - Home tab`). Unquoted single-word names allowed.
- `desc` — concise AutoCAD-behavior summary, ≤ ~14 words. Behavior, not marketing.
- `p` — `P0|P1|P2`. `status` — enum above. `test`/`note` — `""` when empty.
- `dep` — list of component codes, subset of: `occt, ocp, freecad, planegcs, build123d, cadquery, ezdxf, libredwg, ifcopenshell, bonsai, gdal, pdal, shapely, blender-native, zcode-runtime`. Empty `[]` means pure product code.
- **TS entries only:** additionally include `toolset: mechanical|electrical|mep|plant|civil|gis|raster`.
- Rendering: `docs/10-product/inventory-tables.md` is **GENERATED** by `scripts/render_inventory.py` (run by CI; drift-checked). Hand-authored methodology lives in `docs/10-product/feature-parity-inventory.md`.

## 6. Agent vocabulary

- **Modes:** `read-only | propose | approve | autonomous` (escalating capability; defaults and transitions specified in the permissions doc).
- **Permission classes:** `doc-edit, terminal, filesystem, network, dependencies, skill-install, publish`. Destructive/high-impact actions require explicit approval per class.
- **CAD tool namespaces (contract v1):** `cad.doc, cad.select, cad.geometry, cad.edit, cad.layers, cad.blocks, cad.annotate, cad.layouts, cad.io, cad.view, cad.calc, cad.skills, cad.system` — tool IDs are `cad.<ns>.<verb>`. The contract is versioned (`v1`); breaking changes require `v2` + adapter support window.
- **Execution pipeline states:** `plan → preview → approve → execute → verify`.
- **Shared-document terms:** `doc_version` (monotonic document counter, bumped by every committed transaction), `selection_epoch` (selection change counter), `entity_lock` (advisory per-entity lock during agent transactions), `checkpoint` (named rollback point).
- **Runtime principle (binding):** agents change drawings ONLY through the CAD document's transaction mechanisms via the `cad.*` tool contract — never by mutating Blender scene data behind the document model. ZCode's UI packages are NOT merged into Blender; the runtime runs as a **sidecar** with a versioned interface (ADR-0004).

### ZCode upstream evidence (facts fixed at handoff — use these real names)

Upstream `zai-org/ZCode`: Apache-2.0, version 3.16.1, TypeScript pnpm monorepo, description "Z.ai's coding agent harness." Top-level: `apps/`, `packages/`, `patches/`, `.agents/skills`, `skills-lock.json`, `AGENTS.md`, `DESIGN.md`, `architecture-policy.yaml`, `dependency-graph.mmd`.
- `apps/zcode-cli` — the CLI harness entry.
- Candidate runtime packages for adaptation: `packages/server`, `packages/zcode-server-cli` (headless server runtime), `packages/rpc` (RPC contract — the natural seam for our versioned interface), `packages/provider` + `packages/provider-node` + `packages/model-option-map` (model providers), `packages/services`, `packages/zcode-cua` (computer-use agent: terminal/browser/computer use), `packages/client`, `packages/shared` (client/shared contracts), `.agents/skills` + `skills-lock.json` (skill loading conventions).
- **Excluded from product UI integration:** `packages/web`, `packages/ui`, `packages/web-share`, `packages/share-ui`, `packages/desktop`, `packages/android` (ZCode's own desktop/web/mobile UIs), and `packages/formal-proof`, `packages/stream-animate`, `packages/e2e-report` (unrelated infrastructure) — per the mission's "do not merge ZCode's complete desktop UI into Blender".
- M5 entry gate includes a source audit that may re-scope these candidates; record any re-scoping as an ADR amendment.

## 7. Skill vocabulary

- **Pipeline states:** `draft → recorded → generalized → tested → published`.
- **Workflow DSL step types (v1):** `tool_call, set, branch, foreach, while, try, validate, checkpoint, prompt_user, call_skill`. Declarative-first; scripts are exceptional, sandboxed, and permission-gated (ADR-0006).
- **Trust tiers:** `local | team | public`. Third-party skills are untrusted until validated.
- **Package terms:** `skill.yaml` (manifest), `workflow.yaml` (declarative steps), `tests/` (fixtures + assertions), `docs/`, optional `scripts/`. Versioned semver; provenance + SHA-256 integrity; JSON-schema-compatible typed inputs.

## 8. Release manifest schema (binding for `release-manifests/manifest-*.json`)

Schema version 1. Fields: `schema_version` (=1), `product` (="blender-cad"), `version` (semver, pre-release allowed e.g. `0.1.0-m0`), `created` (ISO date), `status` (e.g. `m0-handoff`), `components` (object with keys `blender`, `zcode_runtime`, `cad_extension`), `dependencies` (array), `notes`.

Validation rules (implemented by `scripts/validate_manifest.py`):
- `components.blender.upstream_ref` — 40-hex SHA. Blender pin at handoff: `bf200615b83252a7be951aed5593d068f0f2438a`.
- `components.zcode_runtime.upstream_ref` — 40-hex SHA OR a string starting with `pending:` (audit pending). ZCode pin at handoff: `0a1fc56d279fd1001f78387bd81aec1c26767411`.
- `components.cad_extension.commit` — hex SHA OR literal `self-at-release` (resolved when the release is tagged).
- Every `dependencies[]` item: `name`, `license`, `role`, `module`, `status` (`candidate|adopted|rejected`); `module` must exist in `modules/modules.json`.
- Blender/ZCode pins must never silently change: a changed pin requires a release-manifest version bump (enforced socially via review + CI drift alerts).

## 9. Licensing quick facts + verification rule

License facts are recorded with a **confidence tag**. Where uncertain, write `(verify)` and route re-verification through the adoption gate. Core facts at handoff:

| Component | License | Confidence |
|---|---|---|
| Blender (host) | GPL-2.0-or-later (per blender.org; GitHub shows NOASSERTION) | high, cite blender.org/license |
| Open CASCADE (OCCT) | LGPL-2.1 with exception | high |
| OCP (CadQuery's OCCT bindings) | Apache-2.0 | high |
| FreeCAD components | LGPL-2.1+ (per-module exceptions) | high |
| PlaneGCS | LGPL (used by FreeCAD) | medium — `(verify)` |
| build123d | Apache-2.0 | high |
| CadQuery | Apache-2.0 | high |
| ezdxf | MIT | high |
| LibreDWG | GPL-3.0 | high |
| IfcOpenShell | LGPL-3.0-or-later | medium — `(verify)` |
| Bonsai (BlenderBIM) | (verify — license history has changed) | must verify at adoption gate |
| GDAL | MIT/X11-style (MIT-style permissive) | medium — `(verify)` |
| PDAL | BSD-style permissive | medium — `(verify)` |
| shapely | BSD-3-Clause | high |
| ZCode (zai-org/ZCode) | Apache-2.0 | high (verified via GitHub API 2026-10-19) |

**Extension licensing (ADR-0005):** code distributed with/inside Blender must be GPL-compatible; the CAD extension repo adopts **GPL-3.0-or-later** for its code (compatible with GPL-2+ Blender via "or later"), with third-party notices preserved and the license inventory as the compliance record. Data fixtures are documentation, not code.

## 10. Workers & ownership

- **TL (Technical Lead):** architecture, contracts, module boundaries, release manifests, upstream sync, integration gates, testing module.
- **W1 — UX & command systems:** `shell`, `commands`, `drafting` (UX side), `drawings` (UX side), `toolsets` (UX + libraries).
- **W2 — Core engineering:** `document`, `kernel`, `parametric`, `interchange`, `bim`, `drafting` (geometry side).
- **W3 — Agent & skills:** `agent`, `skills`, runtime sidecar, security/sandboxing, registry.
- Test ownership: each module's tests are authored by its owner; cross-module conformance suites live in `testing` (TL).

## 11. Milestones (one-liners; detailed in `docs/30-process/milestone-plan.md`)

- **M0 — Handoff & architecture (this commit):** repos, upstreams pinned, all 11 deliverable docs, executable CI. Exit: docs merged, CI green on the repo-consistency suite.
- **M1 — Walking skeleton:** extension loads in Blender; CAD workspace shell; command-line state machine; LINE/CIRCLE/ARC + basic modify; document model v0 with DXF R/W via ezdxf.
- **M2 — Drafting core parity:** osnap/ortho/polar/tracking/dynamic input; layers/blocks; dims & annotations; layouts + PDF publish; xrefs (DXF).
- **M3 — Precision & parametrics:** OCCT integration live; constraints (PlaneGCS); 3D solids; parametric edits; DWG read (LibreDWG).
- **M4 — Interop conformance & toolsets scaffold:** DWG write + round-trip suite; IFC/BIM bridge; toolset libraries begin (mechanical/electrical/MEP…).
- **M5 — Agent integration:** ZCode runtime sidecar; CAD tool contract v1 live; permissions; shared-document conflict model.
- **M6 — Skills:** record→generalize authoring; skill format v1 engine; registry/publishing MVP.
- **M7 — Usability validation & hardening:** AutoCAD-user comparative testing program; regression fixes; release gates for 1.0.

Completion-graph policy: every milestone report shows per-item status with ticks ONLY for items that passed documented acceptance tests.

## 12. M0 file map (collision-avoidance — write ONLY your listed files)

| Task | Files (all under repo root `/home/z/blender-cad/`) |
|---|---|
| **1-a architecture** | `docs/00-architecture/repo-and-upstream-sync.md`, `docs/00-architecture/document-model-and-geometry-kernel.md`, `docs/00-architecture/component-adoption-matrix.md`, `docs/00-architecture/license-inventory.md`, `LICENSE-NOTES.md`, `docs/30-process/adr/0001-product-naming-and-positioning.md`, `0002-occt-as-geometry-kernel.md`, `0003-dxf-first-interop-strategy.md`, `0004-zcode-runtime-interface-first.md`, `0005-extension-license-gpl-compatibility.md`, `0006-declarative-first-skill-engine.md` |
| **1-b1 inventory** | `data/inventory/cmd.yaml`, `draw.yaml`, `mod.yaml`, `prec.yaml`, `org.yaml`, `ann.yaml`, `lay.yaml`, `p3d.yaml`, `par.yaml`, `io.yaml`, `toolsets.yaml`, `ux.yaml`, `agent.yaml`, `skills.yaml`, `docs/10-product/feature-parity-inventory.md`, `docs/10-product/file-compatibility-matrix.md` |
| **1-b2 UX** | `docs/10-product/ux-specification.md`, `docs/10-product/usability-validation-plan.md` |
| **1-c agent+skills** | `docs/20-agent/zcode-adaptation-plan.md`, `docs/20-agent/cad-tool-contract-v1.md`, `docs/20-agent/permissions-and-execution-model.md`, `docs/20-agent/skill-format-v1.md`, `docs/20-agent/skill-execution-and-publishing.md` |
| **1-d process+scaffold** | `README.md`, `docs/README.md`, `modules/README.md`, `modules/modules.json`, `modules/<each of 13>/README.md`, `patches/README.md`, `release-manifests/manifest-0.1.0.json`, `scripts/render_inventory.py`, `scripts/validate_manifest.py`, `scripts/check_module_boundaries.py`, `scripts/check_upstream_drift.py`, `tests/test_repo_consistency.py`, `.github/workflows/ci.yml`, `.github/workflows/upstream-blender-drift.yml`, `.github/workflows/upstream-zcode-audit.yml`, `docs/30-process/test-plan.md`, `docs/30-process/upstream-update-ci.md`, `docs/30-process/milestone-plan.md`, `docs/30-process/completion-graph-m0.md`, `requirements-dev.txt`, `.gitignore` |
| TL (integration, do not write) | `docs/GLOSSARY.md` (this file), `docs/10-product/inventory-tables.md` (generated), `LICENSE` |

## 13. Writing standards (binding for all M0 docs)

- Engineering register: concrete tables, schemas, examples, state machines, IDs. No marketing language.
- Every doc starts with: title, one-line status, owner (TL/W1/W2/W3), date `2026-10-19`, and a link back to `docs/GLOSSARY.md`.
- Cross-reference by stable IDs: `FP-*` (features), `TP-*` (test-plan items), `ADR-*` (decisions), module names, `cad.*` tool IDs.
- Mermaid diagrams where structure helps (`graph`, `sequenceDiagram`, `stateDiagram-v2`).
- Uncertain facts: tag `(verify)`; never assert unverified specifics as fact.
- Dates ISO-8601. Statuses honest (§1).
- No TODO-only sections; every section carries substance.

## 14. Worklog protocol (binding for all M0 agents)

Shared worklog: `/home/z/my-project/worklog.md` (append-only; never modify existing content). After finishing your task, append your record with ONE bash command:

```
cat >> /home/z/my-project/worklog.md <<'EOF'

---
Task ID: <your task id, e.g. 1-a>
Agent: <doc-engineer (area)>
Task: <one line>

Work Log:
- <concrete steps>

Stage Summary:
- <files + line counts + key decisions/assumptions>
EOF
```

Read the worklog tail BEFORE starting (prior context) and append AFTER finishing. Do not commit or push; the TL integrates, commits and pushes centrally.
