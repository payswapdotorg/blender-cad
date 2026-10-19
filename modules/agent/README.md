# Module: agent

- **Status:** in-progress (M1: adapter v0 + tests + runtime spike landed; sidecar itself remains M5)
- **Owner:** W3
- **Date:** 2026-10-19 (UTC; M1 update by W3)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M5 (sidecar + contract v1 live — glossary §11); M1 delivers the
  in-process adapter subset + the pinned-runtime compatibility spike

## Purpose

Integrated agentic operation: the `cad.*` tool contract, the MCP adapter, the
ZCode-runtime sidecar bridge (ADR-0004: interface-first, versioned seam), and
the activity/permission plumbing. Agents change drawings ONLY through this
contract via the document's transaction mechanisms (glossary §6).

## Owns

- The `cad.*` tool contract server (namespaces `cad.doc`, `cad.select`,
  `cad.geometry`, `cad.edit`, `cad.layers`, `cad.blocks`, `cad.annotate`,
  `cad.layouts`, `cad.io`, `cad.view`, `cad.calc`, `cad.skills`,
  `cad.system`)
- Contract versioning (v1; breaking changes require v2 + adapter window)
- The sidecar runtime bridge to the ZCode fork (pinned, audited)
- MCP adapter wiring; agent mode/permission enforcement points
- Activity log and shared-document state plumbing (`doc_version`,
  `selection_epoch`, `entity_lock`)

## Does NOT own

- Document state itself (`document`)
- Skill authoring/format/execution (`skills`)
- Any UI (`shell`) — though the shell hosts agent surfaces

## FP areas

- AGT — integrated agent operation

## Allowed dependencies

- `document`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `CadToolServer` — serves the `cad.*` v1 contract (tool ids `cad.<ns>.<verb>`)
- `SidecarBridge` — lifecycle + versioned RPC seam to the ZCode runtime
- `McpAdapter` — expose the contract over MCP
- `PermissionBroker` — modes (read-only/propose/approve/autonomous) × permission classes
- `DocSync` — `doc_version`/`selection_epoch`/`entity_lock` bookkeeping for agents
- `ActivityLog` — auditable record of agent actions (plan→preview→approve→execute→verify)

## Tests

- docs/30-process/test-plan.md: TP-CAT-07 (tool correctness, state-sync,
  conflict, rollback) — with mocked model providers. Suite home once code
  lands: `modules/agent/tests/` + `modules/testing/agent-contract/`.

## M1 state — what has LANDED (tested, not claimed beyond evidence)

- `bcagent/` — the in-process CAD tool adapter v0 (pure Python; m1-module-contracts §8):
  `contract.py` (envelope + the 8 `CAD_E_*` codes), `sessions.py` (opaque `st-` tokens,
  default-DENY), `permissions.py` (mode × class broker), `adapter.py` (`dispatch()` →
  contract §2 envelope; R1 `base_doc_version` precondition; one undo step per
  transactional call), `tools/` (per-namespace modules), `runtime_interface.py`
  (agent-runtime-interface/v1 handshake/event/spawn DESIGN — **no process at M1**).
- Implemented tool subset (advertised == dispatchable, `version: "1.0-m1"`):
  `cad.doc.{info,status}`, `cad.select.{get,set,count,filter}`,
  `cad.geometry.{create,get,query,transform}`, `cad.layers.list`,
  `cad.io.{export_dxf,import_dxf}`, `cad.system.capabilities`.
- `tests/` — `test_adapter.py` (envelope, error model, R1 conflict, atomicity,
  permission matrix, tokens, capabilities honesty) and `test_security_boundary.py`
  (source scan: no `bpy`/`bcshell`/`eval`/`exec`/`subprocess` in bcagent; deny-before-
  execute; io confinement). 153 tests green under plain pytest (no Blender).
- `docs/20-agent/zcode-runtime-spike-m1.md` — pinned-tree install/build/run evidence
  (TP-CAT-11 companion): scoped pnpm install exit 0, tsup + tsc builds exit 0,
  headless `--version`/`status` runs exit 0 at `0a1fc56d27…`; RPC seam surface
  recorded for ADR-0004.
- Still planned (honest): live sidecar process, MCP wire transport, event stream,
  preview/commit batching, `cad.edit`/`blocks`/`annotate`/`layouts`/`view`/`calc`/
  `skills` namespaces, skills module — all M5/M6 per glossary §11.
