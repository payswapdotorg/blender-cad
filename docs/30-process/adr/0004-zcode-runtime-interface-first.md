# ADR-0004: ZCode runtime — interface-first sidecar

- **Status:** Proposed — binding for the agent runtime architecture; adoption is gated by the M5-entry source audit.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## Context

- Mission criterion 3: integrated agentic operation — ZCode-derived agents usable inside the CAD app, plus skill authoring/execution/publishing.
- Upstream facts fixed at handoff (2026-10-19): `zai-org/ZCode` — Apache-2.0, version **v3.16.1**, TypeScript pnpm monorepo, "Z.ai's coding agent harness."; pinned at `0a1fc56d279fd1001f78387bd81aec1c26767411` (zai-org/ZCode main, 2026-10-19T02:34Z). Product fork: `payswapdotorg/ZCode` — GitHub created the fork under the name **"Gen"** (network-root name cache) and it was renamed to `ZCode`; cosmetic only; parent verified = `zai-org/ZCode`.
- Mission rule: ZCode's own desktop/web/mobile UIs are NOT merged into Blender. Runtime principle (glossary §6): agents change drawings only through the CAD document's transaction mechanisms via the `cad.*` tool contract.

## Decision

1. **Sidecar runtime**: the ZCode-derived runtime executes as a separate process communicating with the CAD application through a **versioned interface** — `packages/rpc` is the natural seam. The extension hosts an adapter; no ZCode UI code enters the product.
2. **No UI merge**: excluded packages per glossary §6 — `packages/web`, `packages/ui`, `packages/web-share`, `packages/share-ui`, `packages/desktop`, `packages/android` (ZCode's own UIs) and `packages/formal-proof`, `packages/stream-animate`, `packages/e2e-report` (unrelated infrastructure).
3. **Reuse scope (candidates only)**: `packages/server`, `packages/zcode-server-cli` (headless server runtime), `packages/rpc`, `packages/provider`, `packages/provider-node`, `packages/model-option-map`, `packages/services`, `packages/zcode-cua`, `packages/client`, `packages/shared`, and the `.agents/skills` + `skills-lock.json` skill-loading conventions.
4. **Audit checklist before adoption (M5 entry gate)**: (a) full source audit of every reused package — any re-scoping is recorded as an ADR amendment (glossary §6); (b) Apache-2.0 compliance: preserve NOTICE and third-party notices, state changes (§4(d)); (c) security review of the headless runtime (sandboxing, network egress, secret handling); (d) pin discipline: quarterly audits, no silent bumps (`repo-and-upstream-sync.md`); (e) RPC contract versioning plan (v1 → v2 with an adapter-support window); (f) `cad.*` tool contract v1 conformance tests (TP-CAT-07).

Reuse scope at a glance (glossary §6; candidates only — the M5-entry audit may re-scope):

| Included (candidates) | Purpose in the sidecar |
|---|---|
| `packages/server`, `packages/zcode-server-cli` | headless server runtime |
| `packages/rpc` | the versioned interface seam |
| `packages/provider`, `packages/provider-node`, `packages/model-option-map` | model providers |
| `packages/services` | shared services |
| `packages/zcode-cua` | computer-use agent capabilities (terminal/browser/computer use) |
| `packages/client`, `packages/shared` | client/shared contracts |
| `.agents/skills` + `skills-lock.json` | skill loading conventions (skills module, M6) |
| Excluded | Reason |
| `packages/web`, `ui`, `web-share`, `share-ui`, `desktop`, `android` | ZCode's own UIs — mission rule |
| `packages/formal-proof`, `stream-animate`, `e2e-report` | unrelated infrastructure |
| other `apps/` content beyond the `zcode-cli` harness entry | in-scope determination deferred to the M5-entry source audit (the glossary §6 candidates list is package-level) |

## Consequences

- Upstream upgrades are isolated behind the versioned interface: ZCode can move fast without destabilizing the CAD application, and vice versa.
- The sidecar adds process-management and packaging surface; accepted for the isolation and security benefits.
- The M5-entry audit may re-scope the package list; that outcome is expected to be recorded (ADR amendment), not avoided.

## Alternatives

1. **Merge ZCode's UI/runtime into Blender** — rejected: mission rule; unbounded integration surface; security exposure; license notice sprawl.
2. **Re-implement an agent harness from scratch** — rejected: discards a proven runtime and its skill conventions; large duplicated cost with no upstream leverage.
3. **Track upstream HEAD continuously** — rejected: violates pin discipline (glossary §8); unpinned dependency risk; unauditable.
4. **MCP-only integration without ZCode** — deferred, not chosen: loses the skill-loading conventions (`skills-lock.json`) that the skills module (M6) is designed around.
