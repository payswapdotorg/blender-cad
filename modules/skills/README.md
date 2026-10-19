# Module: skills

- **Status:** planned (no code at M0)
- **Owner:** W3
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M6 (authoring, engine, registry MVP — glossary §11)

## Purpose

The skill system: record→generalize authoring, the versioned package format
(ADR-0006, declarative-first), sandboxed execution, and the registry client.
Skills automate CAD work through commands and the `cad.*` contract — never
around them.

## Owns

- Authoring pipeline states: draft → recorded → generalized → tested → published
- Package format v1: `skill.yaml`, `workflow.yaml` (declarative steps),
  `tests/`, `docs/`, optional sandboxed `scripts/`
- Execution engine (step types: tool_call, set, branch, foreach, while, try,
  validate, checkpoint, prompt_user, call_skill)
- Registry client, publishing, trust tiers (local | team | public)
- Provenance + SHA-256 integrity validation of packages and dependencies

## Does NOT own

- The command registry or prompt machine (`commands` — skills depend on it,
  per the recorded inversion; see modules/README.md §4)
- Agent runtime or the `cad.*` contract (`agent`)
- Document state (`document`)

## FP areas

- SKL — skills & automation

## Allowed dependencies

- `agent`, `document`, `commands`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `SkillAuthor` — record→generalize authoring pipeline
- `SkillPackage` — load/validate the package format; typed inputs
- `SkillExecutor` — run workflows (declarative-first) in the sandbox
- `IntegrityValidator` — provenance + SHA-256 dependency verification
- `SkillRegistryClient` — publish/fetch/version-resolve; trust tiers
- `SkillSandboxPolicy` — permission gates for exceptional scripts

## Tests

- docs/30-process/test-plan.md: TP-CAT-08 (creation, portability, versioning,
  validation) and TP-CAT-09 (security, permissions, dependency integrity).
  Suite home once code lands: `modules/skills/tests/`.
