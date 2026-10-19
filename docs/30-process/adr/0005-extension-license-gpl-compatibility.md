# ADR-0005: Extension licensing — GPL compatibility

- **Status:** Proposed — binding; the TL adds the repository `LICENSE` file (GPL-3.0-or-later).
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## Context

- Host: Blender is GPL-2.0-or-later per blender.org (GitHub shows `NOASSERTION` — both facts recorded; blender.org is the cited source).
- Blender extension distribution requires GPL-compatible licensing; the current extension-platform policy must be verified at the first packaging milestone (verify).
- Planned dependency spread (component-adoption-matrix.md): permissive (MIT, Apache-2.0, BSD), LGPL family (OCCT with exception, FreeCAD components, IfcOpenShell (verify), PlaneGCS (verify)) and GPL-3.0 (LibreDWG).
- Fork-side obligation: the Blender fork preserves upstream license headers and its patches add no additional restrictions (repo-and-upstream-sync.md §5).
- The extension repository also hosts documentation and fixtures, whose licensing needed a simple default at M0.
- ZCode's Apache-2.0 NOTICE and third-party-notice preservation is an explicit obligation of runtime reuse (ADR-0004; license-inventory §4).

## Decision

1. **The CAD extension's code is GPL-3.0-or-later** (SPDX: `GPL-3.0-or-later`). Repository summary: `LICENSE-NOTES.md`.
2. **Rationale**: (a) required for distribution with/inside Blender (GPL-2.0-or-later host); (b) "or later" unification — the combined work distributes under GPL-3.0-or-later terms, which admits Apache-2.0 components (incompatible with GPL-2.0-only); (c) direct alignment with GPL-3.0 components (LibreDWG).
3. **`license-inventory.md` is the compliance record**: every dependency carries a license row, a glossary §9 confidence tag, a compatibility verdict and notice obligations. **Any new dependency requires a license-inventory row + compatibility verdict before merge** (merge-gate checklist item):
   1. dependency named, with version/pin recorded in the PR description;
   2. inventory row added (license, source of truth, verdicts, obligations, verified date);
   3. confidence tag assigned — `(verify)` allowed only with a gate that resolves it before shipping;
   4. compatibility verdicts written for both extension and host contexts;
   5. release manifest gains its `dependencies[]` entry at adoption time (not before);
   6. the PR is blocked until every item above holds.
4. Third-party notices are preserved — components are never relicensed by this repository. Documentation and fixtures carry the same license header for simplicity, revisited before external reuse.

## Consequences

- Contributions to this repository are under GPL-3.0-or-later; permissive dependencies keep their own licenses.
- LGPL components must retain library boundaries (no static relicensing into a single extension binary without compliance work).
- If extension-platform policy verification at the first packaging milestone surfaces stricter requirements, this ADR is amended through review — recorded, never improvised at packaging time.
- Dev-fixture tooling (ODA File Converter) is outside distribution and therefore raises no GPL question; its inventory row exists for supply-chain traceability only.
- Obligations per license family are summarized in license-inventory.md §6; the per-row details are binding over the summary, and the recheck schedule is tied to the milestone calendar (license-inventory.md §5).
- No trademark licenses are granted by this ADR; trademark handling is ADR-0001's scope.
- The extension's GPL-3.0-or-later applies to our code; the Blender fork's GPL-2.0-or-later is upstream's choice and is not altered by us.
- Trademark disclaimer applies wherever licensing/naming is discussed (ADR-0001, glossary §3).

## Alternatives

1. **GPL-2.0-only** — rejected: incompatible with Apache-2.0 components (OCP, ZCode, build123d, CadQuery).
2. **Permissive license for the whole repo (MIT/Apache)** — rejected: incompatible with Blender's distribution requirements for extension code.
3. **Mixed per-file licensing** — rejected: error-prone at this scale; a single verdict plus a maintained inventory is auditable.
