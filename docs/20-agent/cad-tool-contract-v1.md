# CAD Tool Contract v1 (`cad-tool-contract/v1`)

- **Status:** Binding M0 specification — all items `planned`; nothing is implemented at M0
- **Owner:** W3 — Agent & skills (adapter lives in module `agent`)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)

## 1. Identity and versioning

- **Contract id:** `cad-tool-contract/v1`. All tool IDs are `cad.<ns>.<verb>` over exactly the 13 namespaces of glossary §6: `cad.doc, cad.select, cad.geometry, cad.edit, cad.layers, cad.blocks, cad.annotate, cad.layouts, cad.io, cad.view, cad.calc, cad.skills, cad.system`.
- **Semver policy:** additive changes (new tools, new optional fields) = **minor** (v1.1, advertised via `cad.system.capabilities.version`); any schema change, removal or semantic change = **major → v2**. v2 requires an announcement at least one product release ahead; the v1 adapter is maintained for ≥ 12 months after v2 availability and through two minor product releases (final window fixed by ADR at v2 time; (verify) with TL).
- **Transport:** the CAD application exposes an **MCP server** (module `agent`); the agent runtime sidecar is an **MCP client** (see `zcode-adaptation-plan.md` §2–3). An equivalent **JSON-RPC 2.0** method mapping (method name = tool id) is normative for in-process and test use; MCP is the wire format of record. Tools not advertised by `cad.system.capabilities` return method-not-found at transport level.
- **Session auth:** every request carries a session-scoped `session_token` (string) issued at agent-session start, bound to session identity, mode and permission grants, revocable by the user at any time. Examples below omit it for brevity.
- **Capability discovery:** `cad.system.capabilities` (§6.13) is the single source of truth for available tools, their transactional flag, permissions and contract version.

## 2. Conventions

- Every tool has a request and response **JSON Schema** (published by module `agent`, drift-checked in CI; they are the source of truth if this prose disagrees).
- **Geometry is in document units and the document WCS unless a field explicitly states otherwise.** Angles are decimal degrees, CCW about +Z (or about `normal` when given).
- **Identity:** entities have stable **UUIDs** assigned at creation and never reused; styles, layers, blocks and layouts are addressed by **name** (unique within their collection).
- **Pagination:** every list-valued tool accepts `limit` (int, default 100, max 1000) and returns `next_cursor` (opaque string; absent when exhausted) to be passed back as `cursor`.
- **Envelope:** every response carries `status` (`"ok" | "error"`) and `doc_version` (int, the version after the call — read calls echo the current version):

```json
{"status": "ok", "doc_version": 43, "result": { … }}
{"status": "error", "doc_version": 43, "error": {"code": "…", "message": "…", "details": {…}, "retryable": false}}
```

- Standard types: `point3 = [x, y, z]` numbers; `vec3` direction; `uuid` entity id; `name` string; `angle` degrees; `path` absolute file path string; `digest` `sha256:<hex>`.

Request envelope (all requests):

```json
{"tool": "cad.geometry.create", "session_token": "st-…", "args": { … per-tool fields below … }}
```

`base_doc_version` is a per-tool request field (transactional tools), not an envelope field. Errors use `status: "error"` with the structured `error` object — never prose-only responses.

## 3. Error model

| Code | Meaning | `retryable` | Agent guidance |
|---|---|---|---|
| `CAD_E_DOC_VERSION_CONFLICT` | `base_doc_version` precondition failed; nothing was applied | true (after re-read) | re-read, re-plan, re-preview |
| `CAD_E_PERMISSION_DENIED` | permission class not granted / revoked, or mode below minimum | false | request permission or stop |
| `CAD_E_VALIDATION` | request failed schema or semantic validation | false | fix arguments |
| `CAD_E_ENTITY_NOT_FOUND` | referenced id unknown or deleted | false | re-query |
| `CAD_E_KERNEL_FAILURE` | geometry kernel raised; transaction rolled back | true (once) | retry once; report if persistent |
| `CAD_E_UNSUPPORTED_ENTITY` | operation not valid for the entity type | false | choose a different operation |
| `CAD_E_TIMEOUT` | tool exceeded its time budget | true (once) | retry once or narrow the request |
| `CAD_E_INTERNAL` | unexpected internal failure; transaction rolled back | false | report as a defect |

`details` is a structured object; for `CAD_E_DOC_VERSION_CONFLICT` it always contains `current_doc_version` and `base_doc_version`.

## 4. Transactional semantics

- Tools marked **`transactional: true`** (§6 tables) require a **`base_doc_version`** (int) precondition — optimistic concurrency. On mismatch the adapter returns `CAD_E_DOC_VERSION_CONFLICT` and **applies nothing**.
- Transactional tools **execute atomically inside the document transaction system** (module `document`): mid-tool failure auto-rolls back; partial states are impossible. A single transactional call commits as **one undo step**.
- **Batch staging:** `cad.system.preview` stages a list of `{tool, args}` calls into one proposed transaction (validated, diffed, entity-locked); `cad.system.commit` applies the whole batch atomically as **one undo step** — one agent transaction group. Read-modify-write sequences must use preview/commit.
- Conflict terms (glossary §6): `doc_version` (monotonic document counter, bumped by every committed transaction), `selection_epoch` (selection change counter), `entity_lock` (advisory per-entity lock during agent transactions), `checkpoint` (named rollback point). Policy for these is defined in `permissions-and-execution-model.md` §5; this contract supplies the mechanics (§7).

Staged batch — one preview, one commit, one undo step:

```json
→ {"tool": "cad.system.commit", "args": {"preview_id": "pv-3a…", "base_doc_version": 45, "approval_id": "ap-9…"}}
← {"status": "ok", "doc_version": 46, "result": {"undo_group": "agent:as-7f3a:generate-title-block"}}
```

## 5. Permission mapping

- The per-tool column "Perms" lists **permission classes required · minimum agent mode** (modes: `read-only | propose | approve | autonomous`; classes: `doc-edit, terminal, filesystem, network, dependencies, skill-install, publish`).
- Non-transactional tools: no class, minimum mode `read-only` (exceptions in the tables: `cad.select.set`, `cad.layouts.set_current`).
- `doc-edit` tools: minimum mode `propose`; whether a commit additionally needs user approval is governed by mode, per `permissions-and-execution-model.md`.
- `cad.io` exports need class `filesystem` (they write files) and work in `read-only` mode; imports and xref attach also need `doc-edit` + `filesystem`.
- `cad.skills.run` requires the **union of the target skill's declared permission classes**, checked before the run starts; its minimum mode is the highest declared by any tool the skill uses.
- Class `publish` is never required by `cad.*` tools directly (registry/shell actions carry it).

## 6. Namespaces — tool registry

v1 registers **62 tools** across the 13 namespaces: 27 always-transactional, 3 conditionally transactional (`cad.blocks.manage_attributes` set, `cad.io.xref` mutating ops, `cad.skills.run` when the skill declares `doc-edit`), 32 non-transactional (read / session-state). The initial ~45-tool planning estimate was exceeded to cover the enumerated namespace requirements; the registry grows only via minor versions.

### 6.1 `cad.doc` — document state

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.doc.info` | Document metadata | — | `name: string`, `units: {length, angle}`, `coordinate_systems: object[]`, `app_version: string` | no | — · read-only |
| `cad.doc.status` | Counts + modified state | — | `entity_counts: object`, `modified: bool`, `undo_depth: int`, `selection_epoch: int` | no | — · read-only |
| `cad.doc.checkpoints` | List/create named checkpoints | `action: list\|create`, `name?: string` | `checkpoints: [{name, doc_version, ts}]`, `created?: {name, doc_version}` | no | doc-edit · propose (create) |
| `cad.doc.restore` | Restore to checkpoint | `name: string`, `base_doc_version: int` | `restored_doc_version: int`, `checkpoint: name` | **yes** | doc-edit · propose (high-impact: explicit approval regardless of mode) |

```json
→ {"tool": "cad.doc.status"}
← {"status": "ok", "doc_version": 43, "result": {"entity_counts": {"line": 212, "arc": 34}, "modified": true, "undo_depth": 6, "selection_epoch": 128}}
```

### 6.2 `cad.select` — selection (session state; bumps `selection_epoch`, never `doc_version`)

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.select.get` | Current selection | — | `entities: uuid[]`, `selection_epoch: int`, `digest: string` | no | — · read-only |
| `cad.select.set` | Replace/add/remove selection | `ids: uuid[]`, `mode: replace\|add\|remove` | `entities: uuid[]`, `selection_epoch: int` | no | — · propose |
| `cad.select.count` | Selection size | — | `count: int`, `selection_epoch: int` | no | — · read-only |
| `cad.select.filter` | Query ids by predicate | `by_type?: enum[]`, `by_layer?: name[]`, `query?: string`, `limit`, `cursor` | `ids: uuid[]`, `total: int`, `next_cursor?` | no | — · read-only |

`query` is a restricted property-query subset: comparisons (`==`, `!=`, `<`, `>`) on `type`, `layer`, `color`, `linetype` and geometric properties, combined with `&&` only. Example: `type == "line" && layer == "WALLS" && length > 100`.

```json
→ {"tool": "cad.select.filter", "args": {"query": "type == \"line\" && layer == \"WALLS\" && length > 100", "limit": 50}}
← {"status": "ok", "doc_version": 43, "result": {"ids": ["e-7f2c…", "e-81bd…"], "total": 2}}
```

### 6.3 `cad.geometry` — creation, inspection, transformation

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.geometry.create` | Create typed entities | `type: enum`, `params: object` (below), `layer?: name` | `ids: uuid[]`, `entities: object[]` | **yes** | doc-edit · propose |
| `cad.geometry.get` | Entity data by id | `id: uuid`, `include_refs?: bool` | `entity: object` | no | — · read-only |
| `cad.geometry.query` | Geometric/engineering properties | `ids: uuid[]`, `properties: enum[]` | `items: [{id, properties: object}]` | no | — · read-only |
| `cad.geometry.transform` | Move/rotate/scale/mirror/offset/array | `ids: uuid[]`, `op: enum`, `params: object`, `base_doc_version` | `ids: uuid[]`, `entities: object[]` | **yes** | doc-edit · propose |
| `cad.geometry.edit` | Fillet/chamfer/trim/extend/break/join/explode | `op: enum`, `target: uuid`, `boundary: uuid[]`, `params: object`, `base_doc_version` | `ids: uuid[]`, `removed: uuid[]` | **yes** | doc-edit · propose |
| `cad.geometry.validate` | Geometry integrity checks | `ids: uuid[]`, `checks: enum[]` | `issues: [{id, check, severity, message}]` | no | — · read-only |

`create` → `type` / `params` (document units, WCS): `line {from: point3, to: point3}`; `circle {center, radius, normal?}`; `arc {center, radius, start_angle, end_angle, normal?}`; `polyline {vertices: point3[], closed: bool}`; `ellipse {center, major_axis: vec3, major_radius, ratio}`; `point {at: point3}`; `spline {fit_points: point3[] | control_points: point3[] + degree, closed}`; `hatch {boundary_ids: uuid[], pattern: string, scale, angle}`; `solid-from-profile {profile_ids: uuid[], height, direction?: vec3}`.
`transform` ops: `move {delta: vec3}`; `rotate {axis: point3/vec3, angle}`; `scale {about: point3, factors: [x,y,z]}`; `mirror {plane: {point, normal}}`; `offset {distance, side}`; `array {kind: rect\|polar, count, spacing\|angle}`.
`query` properties: `length, area, volume, perimeter, centroid, bbox {min, max}, distance, radius, angle, mass_properties` (what is computable depends on entity type; unavailable → omitted, never faked).

```json
→ {"tool": "cad.geometry.create", "base_doc_version": 43, "params": {"type": "line", "from": [0,0,0], "to": [120,0,0], "layer": "WALLS"}}
← {"status": "ok", "doc_version": 44, "result": {"ids": ["e-7f2c…"], "entities": [{"id": "e-7f2c…", "type": "line", "layer": "WALLS", "from": [0,0,0], "to": [120,0,0]}]}}
```

### 6.4 `cad.edit` — property updates

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.edit.set_properties` | Entity property updates | `ids: uuid[]`, `properties: {color?, layer?, linetype?, lineweight?, custom?}`, `base_doc_version` | `updated: int` | **yes** | doc-edit · propose |
| `cad.edit.bulk_set_properties` | Bulk edit by predicate | `filter: object` (as `cad.select.filter`), `properties: object`, `base_doc_version` | `updated: int`, `matched: int` | **yes** | doc-edit · propose (high-impact when ≥ 20 entities) |
| `cad.edit.match_properties` | Copy properties source→targets | `source: uuid`, `targets: uuid[]`, `properties?: string[]`, `base_doc_version` | `updated: int` | **yes** | doc-edit · propose |

### 6.5 `cad.layers` — layer management

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.layers.list` | List layers (current drawing order irrelevant; alphabetical) | `cursor?` | `layers: [{name, state: {on, frozen, locked}, color, linetype, lineweight, entity_count}]`, `names: string[]`, `next_cursor?` | no | — · read-only |
| `cad.layers.create` | Create layer | `name: string`, `color?`, `linetype?`, `lineweight?`, `base_doc_version` | `name` | **yes** | doc-edit · propose |
| `cad.layers.set_state` | On/off/freeze/lock | `names: string[]`, `state: {on?, frozen?, locked?}`, `base_doc_version` | `updated: int` | **yes** | doc-edit · propose |
| `cad.layers.set_properties` | Color/linetype/lineweight | `name: name`, `properties: object`, `base_doc_version` | `name` | **yes** | doc-edit · propose |
| `cad.layers.move_entities_to` | Move entities to layer | `ids: uuid[] \| filter: object`, `layer: name`, `base_doc_version` | `moved: int` | **yes** | doc-edit · propose |

### 6.6 `cad.blocks` — block definitions and references

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.blocks.list` | List definitions | `cursor?` | `blocks: [{name, base_point: point3, attribute_defs: object[], instance_count}]`, `next_cursor?` | no | — · read-only |
| `cad.blocks.create` | Create definition from selection | `name: string`, `from_selection: bool \| ids: uuid[]`, `base_point: point3`, `base_doc_version` | `name` | **yes** | doc-edit · propose |
| `cad.blocks.insert` | Insert reference with attributes | `name: string`, `position: point3`, `scale?: [x,y,z]`, `rotation?: angle`, `attributes?: {tag: value}`, `layer?: name`, `base_doc_version` | `id: uuid` | **yes** | doc-edit · propose |
| `cad.blocks.redefine` | Redefine definition | `name: string`, `from_selection \| ids`, `base_point`, `base_doc_version` | `updated_instances: int` (high-impact: all instances change) | **yes** | doc-edit · propose |
| `cad.blocks.manage_attributes` | Get/set reference attributes | `block_ref: uuid`, `action: get\|set`, `attributes?: {tag: value}`, `base_doc_version?` (set) | `attributes: {tag: value}` | set: **yes** | doc-edit · propose |

```json
→ {"tool": "cad.blocks.insert", "args": {"name": "std-title-block-A3", "position": [0,0,0], "attributes": {"SHEET": "A3"}, "layer": "TITLEBLOCK", "base_doc_version": 46}}
← {"status": "ok", "doc_version": 47, "result": {"id": "e-c31f…"}}
```

### 6.7 `cad.annotate` — annotation entities and styles

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.annotate.dimension` | Create typed dimension | `type: linear\|aligned\|radius\|diameter\|angular\|ordinate`, `params: object`, `style?: name`, `layer?`, `base_doc_version` | `id: uuid` | **yes** | doc-edit · propose |
| `cad.annotate.text` | Single-line text | `text: string`, `at: point3`, `height: number`, `style?`, `rotation?`, `layer?`, `base_doc_version` | `id: uuid` | **yes** | doc-edit · propose |
| `cad.annotate.leader` | Leader / multileader | `points: point3[]`, `content?: string \| object`, `style?`, `base_doc_version` | `id: uuid` | **yes** | doc-edit · propose |
| `cad.annotate.table` | Create/fill table | `op: create\|fill`, create: `{at, rows, cols, style?}`; fill: `{id, cells: [{r, c, text}]}`, `base_doc_version` | `id: uuid` | **yes** | doc-edit · propose |
| `cad.annotate.hatch` | Hatch existing boundaries | `boundary_ids: uuid[]`, `pattern: string`, `scale?`, `angle?`, `layer?`, `base_doc_version` | `id: uuid` | **yes** | doc-edit · propose |
| `cad.annotate.set_style` | Create/update dimension or text style | `kind: dimension\|text`, `name: string`, `properties: object`, `base_doc_version` | `name` | **yes** | doc-edit · propose |

`dimension` params by type: linear `{p1, p2, offset}`; aligned `{p1, p2, offset}`; radius `{entity: uuid, angle?}`; diameter `{entity: uuid}`; angular `{p1, vertex, p2, offset}`; ordinate `{origin, feature: point3, axis: x\|y}`. Placement points are in WCS; `offset` positions the dimension line.

```json
→ {"tool": "cad.annotate.dimension", "base_doc_version": 44, "params": {"type": "aligned", "p1": [0,0,0], "p2": [120,0,0], "offset": 15}, "style": "ISO-25"}
← {"status": "ok", "doc_version": 45, "result": {"id": "e-91ab…"}}
```

### 6.8 `cad.layouts` — layouts, pagesetups, viewports

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.layouts.list` | List layouts (current first) | — | `layouts: [{name, paper_size, pagesetup, viewport_count, current, paper_origin: point3}]` | no | — · read-only |
| `cad.layouts.create` | Create layout | `name: string`, `paper_size?`, `base_doc_version` | `name` | **yes** | doc-edit · propose |
| `cad.layouts.set_pagesetup` | Assign pagesetup | `layout: name`, `pagesetup: {paper_size, orientation, scale, pdf_options?}`, `base_doc_version` | `name` | **yes** | doc-edit · propose |
| `cad.layouts.create_viewport` | Create viewport in layout | `layout: name`, `region: {x, y, w, h}`, `scale: number`, `lock?: bool`, `base_doc_version` | `viewport_id: uuid` | **yes** | doc-edit · propose |
| `cad.layouts.set_current` | Switch current layout (session state) | `layout: name` | `current: name` | no | doc-edit · propose |

### 6.9 `cad.io` — interchange and external references

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.io.export_dxf` | Export DXF | `path: string`, `version?: enum(R12…R2024)` | `path`, `bytes: int`, `warnings: string[]` | no | filesystem · read-only |
| `cad.io.export_dwg` | Export DWG | `path`, `version?` | `path`, `bytes`, `warnings` | no | filesystem · read-only |
| `cad.io.export_pdf` | Publish layout to PDF | `layout: name`, `pagesetup?: name`, `path?` | `path`, `pages: int` | no | filesystem · read-only |
| `cad.io.export_ifc` | Export IFC (module `bim`) | `path`, `schema?`, `mapping?: object` | `path`, `warnings` | no | filesystem · read-only |
| `cad.io.import_dxf` | Import DXF | `path`, `into: current\|new`, `options?: object`, `base_doc_version` | `imported: {counts: object}` | **yes** | doc-edit + filesystem · propose |
| `cad.io.import_dwg` | Import DWG | as `import_dxf` | as `import_dxf` | **yes** | doc-edit + filesystem · propose |
| `cad.io.xref` | Attach/detach/reload/bind/clip/list | `op: enum`, `name?`, `path?` (attach), `clip_boundary?: uuid[]`, `base_doc_version?` (mutating ops) | op-dependent | mutating: **yes** | mutating: doc-edit + filesystem |

DXF tooling precedes DWG per ADR-0003 (DXF-first interop strategy); `export_dwg` availability follows the interchange milestones.

```json
→ {"tool": "cad.io.export_dxf", "args": {"path": "/home/me/out/pump-house.dxf", "version": "R2018"}}
← {"status": "ok", "doc_version": 43, "result": {"path": "/home/me/out/pump-house.dxf", "bytes": 184320, "warnings": ["2 custom properties not representable in R2018"]}}
```

### 6.10 `cad.view` — view state and visual checks

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.view.zoom` | Zoom window/extents/entity | `to: window {p1, p2} \| extents \| entity {ids}` | `view_state: object` | no | — · read-only |
| `cad.view.screenshot` | Preview render for agent visual checks | `target?: view \| layout: name`, `width?`, `height?`, `format?: png` | `image_b64: string`, `ts`, `view_state` | no | — · read-only |
| `cad.view.list` | List saved views | — | `views: [{name, state: object}]` | no | — · read-only |

`cad.view.screenshot` exists so agents can *look*; it is never a mutation path (mission rule: never rely solely on screenshot clicking where a typed API exists — `zcode-adaptation-plan.md` §6).

### 6.11 `cad.calc` — measurement and conversion

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.calc.measure` | Distance/angle/area between ids or points | `kind: distance\|angle\|area`, `args: {ids?: uuid[], points?: point3[]}` | `value: number`, `unit: string` | no | — · read-only |
| `cad.calc.units_convert` | Unit conversion | `value: number`, `from: string`, `to: string` | `value: number` | no | — · read-only |
| `cad.calc.mass_properties` | Mass properties for entity set | `ids: uuid[] \| filter: object` | `area, volume, centroid, moments, bbox` | no | — · read-only |

```json
→ {"tool": "cad.calc.measure", "args": {"kind": "distance", "args": {"ids": ["e-7f2c…", "e-81bd…"]}}}
← {"status": "ok", "doc_version": 43, "result": {"value": 1250.0, "unit": "mm"}}
```

### 6.12 `cad.skills` — skill registry and execution

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.skills.search` | Registry query (task language) | `query: string`, `limit`, `cursor` | `skills: [{id, name, version, description, trust_tier}]`, `next_cursor?` | no | — · read-only |
| `cad.skills.describe` | Manifest + inputs schema | `id: string`, `version?: semver` | `manifest: object`, `inputs_schema: object`, `tools: string[]`, `permissions: string[]` | no | — · read-only |
| `cad.skills.run` | Execute skill | `id`, `version?`, `inputs: object`, `base_doc_version?` | `run_id`, `status: enum`, `report: object`, `doc_version_after?` | if skill declares doc-edit | union of skill's declared classes · per skill |
| `cad.skills.validate` | Dry-run skill on fixture | `id`, `inputs?`, `fixture?: name` | `checks: [{name, status, message}]` | no | — · read-only |

### 6.13 `cad.system` — capabilities, permissions, activity, transactions, events

| Tool | Summary | Request | `result` fields | Txn | Perms |
|---|---|---|---|---|---|
| `cad.system.capabilities` | Contract/discovery | — | `contract_version`, `product_version`, `tools: [{id, transactional, permissions, version_added}]`, `limits: {max_batch, timeout_default_s}`, `events: string[]` | no | — · read-only |
| `cad.system.permissions` | Query granted state | — | `session`, `mode`, `granted: string[]`, `pending: [{approval_id, kind, timeout_s}]` | no | — · read-only |
| `cad.system.activity` | Query activity log | `since?: ts`, `limit`, `cursor` | `entries: object[]`, `next_cursor?` | no | — · read-only |
| `cad.system.preview` | Build reviewable diff for a proposed transaction batch | `batch: [{tool, args}]`, `base_doc_version` | `preview_id`, `diff: {added, removed, changed: [{id, before, after}]}`, `entity_locks: uuid[]`, `warnings` | no (staged) | doc-edit · propose |
| `cad.system.commit` | Apply approved batch | `preview_id: string`, `base_doc_version`, `approval_id?` (required when mode = propose) | `doc_version`, `undo_group: string` | **yes** | doc-edit · propose |
| `cad.system.rollback` | Undo an agent transaction group | `undo_group: string \| to_checkpoint: name`, `base_doc_version` | `doc_version` | **yes** | doc-edit · propose (agent may roll back only its own groups; user-initiated rollback is unrestricted) |
| `cad.system.events` | Subscribe/unsubscribe to event stream (SSE) | `action: subscribe\|unsubscribe`, `types: string[]`, `since_seq?: int` | `subscription_id`, `transport: "sse"` | no | — · read-only |

```json
→ {"tool": "cad.system.preview", "base_doc_version": 45, "batch": [{"tool": "cad.edit.set_properties", "args": {"ids": ["e-7f2c…"], "properties": {"color": "red"}}}]}
← {"status": "ok", "doc_version": 45, "result": {"preview_id": "pv-3a…", "diff": {"added": [], "removed": [], "changed": [{"id": "e-7f2c…", "before": {"color": "bylayer"}, "after": {"color": "red"}}]}, "entity_locks": ["e-7f2c…"], "warnings": []}}
```

## 7. State sync — events and shared-document rules

Event envelope (SSE stream; `seq` is monotonic per session for gap detection):

```json
{"event": "doc.version_changed", "seq": 1041, "ts": "2026-10-19T09:15:32Z", "session": "as-7f3a", "payload": {"doc_version": 46, "cause": "user|agent:<session>", "transaction_id": "t-41", "undo_group": "agent:as-7f3a:skill-x"}}
{"event": "selection.changed", "seq": 1042, "ts": "…", "session": "as-7f3a", "payload": {"selection_epoch": 131, "count": 3, "digest": "sha256:…", "cause": "user"}}
{"event": "approval.requested", "seq": 1043, "ts": "…", "session": "as-7f3a", "payload": {"approval_id": "ap-9…", "kind": "transaction|permission|high-impact", "preview_id": "pv-3a…", "summary": "3 entities: color → red", "timeout_s": 300, "mode": "propose"}}
{"event": "activity.appended", "seq": 1044, "ts": "…", "session": "as-7f3a", "payload": {"activity_id": "ac-77…", "tool": "cad.edit.set_properties", "result_status": "ok", "doc_version_after": 46, "approved_by": "user:local"}}
```

Shared-document rules (mechanics here; policy in `permissions-and-execution-model.md` §5):

- **R1 — `doc_version` precondition:** every transactional call carries `base_doc_version`; mismatch → `CAD_E_DOC_VERSION_CONFLICT`, nothing applied.
- **R2 — `selection_epoch`:** operations parameterized by the current selection capture the epoch at preview time; if the selection changed by commit time → conflict, re-select required.
- **R3 — `entity_lock`:** previews acquire advisory locks on affected entities (held until commit/rollback/lapse); user edits to locked entities raise a visible warning and invalidate the pending preview (re-preview required).
- **R4 — user edits during plan:** any `doc.version_changed` invalidates that session's pending previews; the runtime must re-validate and re-preview against the new version (never blind-retry).

Event obligations (consumer side is binding — an agent that ignores events is non-conformant):

| Event | Producer | Consumer obligation |
|---|---|---|
| `doc.version_changed` | document transaction system | invalidate caches/previews; re-validate plans |
| `selection.changed` | selection service | re-read selection before selection-based operations |
| `approval.requested` | permission authority | surface to user; no execution before resolution |
| `activity.appended` | adapter | append to activity log / UI timeline |

```mermaid
sequenceDiagram
    participant A as Agent (sidecar)
    participant C as CAD app (adapter + document)
    participant U as User
    A->>C: cad.doc.status → doc_version 42
    A->>A: plan edits (entities read at v42)
    U->>C: user edit (trim a line) → commit v43
    C-->>A: doc.version_changed {doc_version: 43}
    A->>C: cad.system.preview {batch, base_doc_version: 42}
    C--xA: CAD_E_DOC_VERSION_CONFLICT (current 43; nothing staged)
    Note over A: pending plan marked stale
    C-->>U: notification "agent is re-planning"
    A->>C: re-read affected entities (v43)
    A->>C: cad.system.preview {batch, base_doc_version: 43}
    C-->>A: preview_id + entity-level diff
    C-->>U: approval.requested (diff attached)
    U->>C: approve
    A->>C: cad.system.commit {preview_id}
    C->>C: apply atomically → ONE undo group, v44
    C-->>A: ok {doc_version: 44, undo_group: "agent:as-7f3a:…"}
```

## 8. Authoritative-write rule (binding)

**Agents change drawings ONLY through the CAD document's transaction mechanisms via this `cad.*` tool contract — never by mutating Blender scene data behind the document model.** The adapter is the single write path into module `document`'s transaction system. The Blender scene is a derived, display-only, one-way projection; any agent-side code writing scene data directly is out of contract and a defect. The adapter additionally enforces: tool allowlist per capabilities, mode minimums, permission classes, and `base_doc_version` preconditions. Tamper tests in TP-CAT-07 attempt scene writes through every exposed path and must fail.

## 9. Testability

- **Every tool requires a contract test** (TP-CAT-07): happy path, validation error, permission denial, version conflict where transactional, pagination where list-valued.

Contract-test matrix (per tool category):

| Category | Required cases |
|---|---|
| Read tools | happy path; pagination (`next_cursor` walk); `CAD_E_ENTITY_NOT_FOUND` |
| Transactional tools | happy path; version conflict (R1); permission denial; atomic rollback on induced failure |
| Selection tools | epoch bump on `cad.select.set`; stale-epoch conflict at commit |
| `cad.system.preview/commit` | multi-tool batch = one undo group; lock acquire/lapse; re-preview after R3/R4 |
| `cad.io` exports/imports | fixture round-trip + warnings surfaced; filesystem denial |
| `cad.skills.*` | search/describe schemas; run against fixture; limit enforcement |

- The JSON examples in this document must be **runnable against the headless document fixture** of module `testing` from M1 onward; fixture corpus and expected outputs are checked in with the tests.
- Schemas are generated from the published JSON Schema files (module `agent`); CI drift-checks this prose against them — on conflict, the schemas win and this document is amended.
