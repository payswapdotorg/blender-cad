# Module: agent

- **Status:** planned (no code at M0)
- **Owner:** W3
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M5 (sidecar + contract v1 live — glossary §11)

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
