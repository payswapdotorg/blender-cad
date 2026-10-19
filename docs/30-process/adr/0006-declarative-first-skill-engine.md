# ADR-0006: Declarative-first skill engine

- **Status:** Proposed — binding design baseline for the `skills` module (M6).
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## Context

- Skill pipeline (glossary §7): `draft → recorded → generalized → tested → published`; the authoring path is record-then-generalize, which needs a reviewable intermediate representation.
- Trust tiers `local | team | public`: third-party skills are untrusted until validated — the execution format must be reviewable and analyzable **without executing it**.
- Permission classes (glossary §6) govern high-impact actions; the skills engine must enforce them. Skills invoke commands through the command registry (dependency inversion: skills → commands, glossary §4).

## Decision

1. **Declarative workflow DSL first.** Step types (v1, glossary §7): `tool_call`, `set`, `branch`, `foreach`, `while`, `try`, `validate`, `checkpoint`, `prompt_user`, `call_skill`.

   | Step type | Semantics | Permission interaction |
   |---|---|---|
   | `tool_call` | invoke a `cad.*` tool or command via the registry | inherits the invoked tool's permission class |
   | `set` | assign a typed variable | none |
   | `branch` | conditional edge | none |
   | `foreach` / `while` | bounded iteration | loop bounds required — no unbounded loops |
   | `try` | error containment with a required failure branch | none |
   | `validate` | assertion against document state | read-only |
   | `checkpoint` | create a named rollback point (glossary §6) | `doc-edit` |
   | `prompt_user` | request explicit user input | pauses execution |
   | `call_skill` | invoke another versioned skill | callee's permissions re-checked |

2. **Scripts are exceptional**: the optional `scripts/` package exists for cases the DSL cannot express, but scripts are **sandboxed, permission-gated and never the default authoring path** — each script step carries an explicit permission grant in the skill manifest, and script use is flagged in skill review.
3. **Static analyzability is a requirement**: the DSL graph is inspectable (which tools, which permissions, which checkpoints) without running the skill. Typed JSON-schema-compatible inputs; semver versioning; provenance + SHA-256 integrity (glossary §7).
4. **The recorder targets the DSL**: recording emits DSL steps (draft state); generalization edits DSL steps, not opaque action blobs or scripts.

## Consequences

- Security review of third-party skills is tractable: tier `public` requires validation before use; skill security testing is covered by TP-CAT-09, creation/versioning by TP-CAT-08.
- Skills are portable across runtime versions: declarative steps survive ZCode-side upgrades behind the versioned interface (ADR-0004) better than imperative scripts would.
- Cost: the DSL is maintained and extended deliberately; every unexpressible need pressures the script escape hatch — governed by permission gating and sandboxing, not by DSL sprawl.
- `checkpoint` steps bind into the document model's named checkpoints (glossary §6), giving skills honest rollback semantics.

## Alternatives

1. **Script-first (arbitrary Python) skills** — rejected: untrusted third-party code is not reviewable at scale; portability and sandboxing costs dominate.
2. **Pure macro replay (recorded action lists only)** — rejected: insufficient control flow for real engineering workflows.
3. **Visual node graphs as the storage format** — deferred: a possible later authoring surface; the DSL remains the storage format either way.
