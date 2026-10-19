# Module: testing

- **Status:** planned (no code at M0) — test-only module
- **Owner:** TL (glossary §10)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** continuous (exists from M0; grows every milestone — glossary §11)

## Purpose

Cross-module assurance: regression, interop, usability and security suites
plus the shared fixture corpora. Module-internal tests stay with their module
owners (`modules/<module>/tests/`); everything that spans modules lives here.
The module produces test code only — no production code, ever.

## Owns

- Cross-module suites: round-trip conformance corpus
  (`modules/testing/roundtrip/`), native-Blender regression
  (`blender-regression/`), agent-contract conformance (`agent-contract/`),
  security corpus (`security/`), usability harness (`usability/`),
  upstream batteries (`upstream/`), packaged-app E2E (`e2e/`)
- Shared, licensing-clean fixture libraries (per-file license notes)
- The golden-file corpora and their regeneration discipline (reviewable diffs)

## Does NOT own

- Any production code or shipped behavior
- Module-internal unit/contract tests (module owners own those)
- The root repo-consistency suite (`tests/`, TP-CAT-00 — TL-owned at repo root)

## FP areas

- None (test-only).

## Allowed dependencies

- All twelve modules (test-only exemption from cycle checks, glossary §4 —
  nothing may depend on `testing`).

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `SuiteRunner` — uniform run/report entry for the cross-module suites
- `FixtureLibrary` — indexed, license-noted fixture access
- `GoldenCorpus` — golden files with explicit regeneration workflow
- `UsabilityHarness` — task batteries, session recording, scoring sheets
- `SecurityCorpus` — the in-house malicious-skill corpus and probes
- `E2EPlaybook` — install→launch→open→workflow→save→uninstall scripts

## Tests

- This module *is* tests. It owns TP-CAT-06, -10, -11, -12 and the
  cross-module sections of the other categories — see
  docs/30-process/test-plan.md. The repo-consistency suite (TP-CAT-00) is the
  M0 acceptance evidence.
