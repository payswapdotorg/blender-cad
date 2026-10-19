# Skill Package Format v1 (`skill-format/v1`)

- **Status:** Binding M0 specification — all items `planned`; nothing is implemented at M0
- **Owner:** W3 — Agent & skills (modules `skills`, `agent`)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)

## 1. Package layout

```
<skill-id>/
├── skill.yaml          # manifest — binding schema §2
├── workflow.yaml       # declarative steps — DSL §3
├── tests/
│   ├── fixtures/       # sample input documents + input sets (never production data)
│   └── assertions.yaml # expected outcomes per fixture
├── docs/               # usage, changelog, sample inputs/outputs
├── scripts/            # OPTIONAL — sandboxed scripts; exceptional (ADR-0006)
├── assets/             # OPTIONAL — block libraries, templates, style files
└── SHA256SUMS          # digest manifest over ALL files (§4.4)
```

Invariants: `skill.yaml` and `workflow.yaml` are mandatory; `tests/` is mandatory for `team`/`public` tiers (local drafts may omit it until publication); every file is listed in `SHA256SUMS`; `docs/` and `assets/` are data only — executable code lives exclusively in `scripts/` and must be declared per-script in the manifest.

## 2. `skill.yaml` manifest schema

| Field | Type | Required | Description |
|---|---|---|---|
| `format` | const `skill-format/v1` | yes | Format grammar version (independent of package semver) |
| `id` | string | yes | Globally unique id, reverse-DNS style (e.g. `com.payswapcad.drafting.generate-title-block`) |
| `name` | string | yes | Short invocation name (unique in the registry) |
| `description` | string | yes | What it does for the user, in task language — not implementation detail |
| `author` | `{name, contact?}` | yes | Author identity |
| `version` | semver | yes | Package version |
| `inputs` | JSON Schema | yes | User inputs with typed validation (drives the auto-generated form) |
| `tools` | `[{tool, min_contract}]` | yes | Required CAD tools by id + contract versions (`cad.*` registry) |
| `compatibility` | `{product, cad_tool_contract[], kernel[], app_matrix[]}` | yes | Product version range (semver), contract versions, required kernel capabilities, verified-product matrix |
| `permissions` | `{doc-edit, filesystem[], network[], terminal, dependencies[], publish}` | yes | Declared permission classes; every value is justified in `docs/` |
| `preconditions` | assertion list | yes | Declarative entry conditions, checked in the `validate` state (may be `[]`) |
| `postconditions` | assertion list | yes | Declarable exit conditions, checked in the `verify` state |
| `outputs` | `{expected, artifacts[]}` | yes | Expected outputs + artifact kinds/patterns |
| `error_handling` | `{policy, checkpoints[], on_limit_exceeded}` | yes | Failure policy (`abort \| rollback \| continue-with-report`), declared checkpoint names, limit-violation behavior |
| `limits` | `{max_steps, max_time_s, tool_allowlist[]}` | yes | Execution limits; `tool_allowlist` ⊆ `tools`; registry caps: `max_steps ≤ 500`, `max_time_s ≤ 3600` |
| `docs` | `{usage, samples[]}` | yes | Usage doc + sample input/output sets |
| `license` | SPDX id | yes | Package license (OSI license required for `public` tier) |
| `attribution` | string | yes | Attribution/notice text (may be empty) |
| `provenance` | `{source, recorded_by, generalized_by, reviewed_by}` | team/public | Origin of the recorded procedure and its review chain |
| `integrity` | `{algorithm, digest, signature?}` | computed | `sha256` digest over `SHA256SUMS`; optional signature `{key_id, algorithm}` |
| `publication` | `{tier, registry?, categories[], min_product_verified}` | registry-managed | Trust tier, registry, task tags, lowest product version CI-verified |

## 3. `workflow.yaml` DSL

Step types (exactly these ten — glossary §7; declarative-first per ADR-0006):

| Step type | Required fields | Semantics |
|---|---|---|
| `tool_call` | `id, tool, args` | Invoke a `cad.*` tool; `args` validated against the contract schema; `base_doc_version` is injected by the executor (workflows never carry it); result bound to `$steps.<id>` |
| `set` | `id, var, value \| expr` | Assign a typed variable; expressions must be pure (below) |
| `branch` | `id, when, then[], else[]` | Conditional paths; nesting allowed |
| `foreach` | `id, over, as, steps[], max_iterations` | Iterate a list; **`max_iterations` REQUIRED**; exceeding it is a failure |
| `while` | `id, while, steps[], max_iterations` | Loop while expression holds; **`max_iterations` REQUIRED** |
| `try` | `id, steps[], on_error, checkpoint?` | Scoped error handling — rollback restores the **named checkpoint** if given, else the run-start checkpoint |
| `validate` | `id, assertions[]` | Assert expressions; optional fixture comparisons (`expected` refs `tests/`); failure → failure policy |
| `checkpoint` | `id, name` | Create a named checkpoint (`cad.doc.checkpoints`) |
| `prompt_user` | `id, prompt, input_schema, timeout_s` | Typed runtime input request; renders from the JSON Schema; timeout → failure policy |
| `call_skill` | `id, skill, inputs` | Invoke a sub-skill (version pinned in the manifest); nested limits inherit caps |

**Loop bounds are REQUIRED and enforced** by the executor: exceeding `max_iterations` triggers the failure policy (default: rollback) — an unbounded loop cannot be expressed.

**Expressions** are read-only dotted paths over `$inputs`, `$vars`, `$steps.<id>.result.…` (constant integer indexes allowed, e.g. `$steps.layouts.result.layouts[0]`) plus **allowlisted pure functions**: `length, sum, min, max, round, abs, format, upper, lower, contains`. **No eval. No side-effect expressions. No host access.** Variables are typed from the manifest `inputs` schema.

**Step ids** are unique within the workflow; failures report the failing step id. **Failure policies:** per-step `on_error: abort | rollback | continue-with-report` (workflow default: `abort`); limit violations always `rollback`; `continue-with-report` requires an explicit `validate` of the partial outcome before the run may complete.

## 4. Worked example — `generate-title-block`

### 4.1 `skill.yaml` (complete)

```yaml
format: skill-format/v1
id: com.payswapcad.drafting.generate-title-block
name: generate-title-block
description: "Insert the standard title block into the current layout and fill its project attributes from user inputs."
author: {name: "W3 drafting standards", contact: "w3@example.invalid"}
version: 1.0.0
inputs:
  type: object
  properties:
    sheet_size: {type: string, enum: [A1, A2, A3, A4], default: A3}
    project_name: {type: string, minLength: 1}
    project_number: {type: string, pattern: "^[A-Z0-9-]{3,16}$"}
    drawn_by: {type: string, minLength: 1}
    scale: {type: string, default: "1:100"}
    revision: {type: string, default: "-"}
  required: [sheet_size, project_name, project_number, drawn_by]
tools:
  - {tool: cad.layouts.list, min_contract: v1}
  - {tool: cad.layers.list, min_contract: v1}
  - {tool: cad.layers.create, min_contract: v1}
  - {tool: cad.blocks.insert, min_contract: v1}
  - {tool: cad.blocks.manage_attributes, min_contract: v1}
  - {tool: cad.geometry.transform, min_contract: v1}
  - {tool: cad.geometry.query, min_contract: v1}
  - {tool: cad.doc.checkpoints, min_contract: v1}
  - {tool: cad.system.preview, min_contract: v1}
  - {tool: cad.system.commit, min_contract: v1}
  - {tool: cad.view.screenshot, min_contract: v1}
compatibility:
  product: ">=0.6.0 <2.0.0"        # skill engine ships at M6
  cad_tool_contract: ["v1"]
  kernel: []                      # analytic 2D only; no kernel capability required
  app_matrix: [{product: "0.6.0", verified: false}]   # set by TP-CAT-08 CI on release
permissions:
  doc-edit: true                  # the ONLY class this skill needs
  filesystem: []
  network: []
  terminal: false
  dependencies: []
  publish: false
preconditions:
  - "cad.layouts.list returns at least one layout"
  - "no existing block named 'std-title-block-*' is present in the current layout"
postconditions:
  - "exactly one title-block instance exists in the current layout"
  - "the instance origin is at the layout paper origin within 0.01 document units"
  - "every attribute in $vars.attrs is non-empty on the inserted reference"
outputs:
  expected: "Title block inserted on layer TITLEBLOCK with all attributes filled; one agent undo group."
  artifacts: []
error_handling:
  policy: rollback
  checkpoints: [pre-insert, placed]
  on_limit_exceeded: rollback
limits:
  max_steps: 40
  max_time_s: 60
  tool_allowlist: [cad.layouts.list, cad.layers.list, cad.layers.create, cad.blocks.insert,
                   cad.blocks.manage_attributes, cad.geometry.transform, cad.geometry.query,
                   cad.doc.checkpoints, cad.system.preview, cad.system.commit, cad.view.screenshot]
docs:
  usage: docs/usage.md
  samples: [docs/samples/default-a3.json, docs/samples/a1.json]
license: MIT
attribution: "Block geometry from the project standard block library (project-internal)."
provenance:
  source: "internal drafting standards procedure (recorded 2026-09-30)"
  recorded_by: "W1 drafting lead"
  generalized_by: "agent-assisted, expert-edited"
  reviewed_by: "W3"
integrity: {algorithm: sha256, digest: "<sha256 of SHA256SUMS>", signature: null}
publication: {tier: team, registry: "https://skills.example.invalid", categories: [drafting, layout, standards], min_product_verified: "0.6.0"}
```

### 4.2 `workflow.yaml` (excerpt; 15 steps)

```yaml
defaults: {on_error: rollback}
steps:
  - id: in_ok
    type: validate
    assertions:
      - "$inputs.sheet_size in [A1, A2, A3, A4]"
      - "length($inputs.project_number) >= 3"
  - id: layouts
    type: tool_call
    tool: cad.layouts.list
  - id: layout                       # contract guarantee: current layout is first
    type: set
    var: layout
    value: "$steps.layouts.result.layouts[0]"
  - id: ck_pre
    type: checkpoint
    name: pre-insert
  - id: layers
    type: tool_call
    tool: cad.layers.list
  - id: ensure_layer
    type: branch
    when: "contains($steps.layers.result.names, 'TITLEBLOCK') == false"
    then:
      - id: mk_layer
        type: tool_call
        tool: cad.layers.create
        args: {name: TITLEBLOCK, color: 7}
  - id: insert
    type: tool_call
    tool: cad.blocks.insert
    args:
      name: "std-title-block-$inputs.sheet_size"   # from the standard block library
      position: [0, 0, 0]
      layer: TITLEBLOCK
  - id: attrs
    type: set
    var: attrs
    value: {SHEET: "$inputs.sheet_size", PROJECT: "$inputs.project_name",
            NUMBER: "$inputs.project_number", DRAWN_BY: "$inputs.drawn_by",
            SCALE: "$inputs.scale", REV: "$inputs.revision"}
  - id: fill                          # fill attributes per field
    type: tool_call
    tool: cad.blocks.manage_attributes
    args: {block_ref: "$steps.insert.result.id", action: set, attributes: "$vars.attrs"}
  - id: place                          # place at layout origin
    type: tool_call
    tool: cad.geometry.transform
    args: {ids: ["$steps.insert.result.id"], op: move, params: {delta: "$steps.layout.paper_origin"}}
  - id: got
    type: tool_call
    tool: cad.blocks.manage_attributes
    args: {block_ref: "$steps.insert.result.id", action: get}
  - id: bbox
    type: tool_call
    tool: cad.geometry.query
    args: {ids: ["$steps.insert.result.id"], properties: [bbox]}
  - id: verify
    type: validate
    assertions:
      - "$steps.got.result.attributes.SHEET == $inputs.sheet_size"
      - "length($steps.got.result.attributes.PROJECT) > 0"
      - "abs($steps.bbox.result.items[0].properties.bbox.min[0] - $steps.layout.paper_origin[0]) < 0.01"
      # y-coordinate assertion is analogous; omitted for brevity
  - id: shot                           # visual evidence attached to the run report
    type: tool_call
    tool: cad.view.screenshot
    args: {target: layout, width: 800}
  - id: ck_post
    type: checkpoint
    name: placed
```

### 4.3 `tests/`

- `fixtures/fixture-01/`: empty A3 layout document with the standard block library attached + `inputs.json` (A3, full field set). `fixtures/fixture-02/`: A1 layout with existing content and an existing TITLEBLOCK layer (idempotence path) + `inputs.json`.
- `assertions.yaml` (per fixture): exactly one block instance inserted; attributes equal the fixture inputs; `bbox` at paper origin within 0.01 units; layer `TITLEBLOCK` exists; the undo journal gained **exactly one** agent group; `doc_version` advanced by exactly one transaction; no entity outside the title block changed (diff is empty elsewhere).

### 4.4 Integrity digest procedure

1. Package time: hash every file except `SHA256SUMS` (`sha256`, paths sorted, format `<digest>  <path>` per line) → `SHA256SUMS`.
2. `manifest.integrity.digest` = SHA-256 over `SHA256SUMS` itself.
3. Optional signature: sign `SHA256SUMS` with the author key → `SHA256SUMS.sig`; `manifest.integrity.signature.key_id` records the key.
4. Verification (install, publish, every run start): recompute steps 1–2, compare; verify signature when present. Mismatch → refuse to load; report `integrity-mismatch` in the incident log.

## 5. Versioning and migration

- **Format version** (`skill-format/v1`) = grammar of manifest + workflow; it versions independently of each package's **semver** (`version`).
- **Compatibility matrix semantics:** `compatibility.product` = declared product range the skill targets; `cad_tool_contract` = required contract versions (executor refuses mismatch); `kernel` = named kernel capabilities required at run; `app_matrix` = per-product verification records maintained by CI (TP-CAT-08).
- **Migration policy:** `skill-format/v2` may only **add** fields and step types — never silently break v1 packages. A package needing v2 features must declare `format: skill-format/v2`; the v1 reader is maintained for ≥ 12 months after v2's announcement, and a registry sunset for v1 (if ever) is announced at least two product releases ahead. Un-announced breaking changes to the format are a defect.
