# ADR-0001: Product naming and positioning

- **Status:** Proposed — binding for M0 artifacts; a rename gate is mandatory before any public marketing.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## Context

- The mission (glossary §1) requires a distinct product identity: "the product UI must look and behave like OUR CAD application" — familiar AutoCAD interaction patterns are allowed; copying proprietary assets or implying that we are Autodesk software is forbidden, and the product must not be misrepresented as stock Blender or as the ZCode IDE.
- Trademark landscape: "Blender" — Blender Foundation; "AutoCAD"/"Autodesk" — Autodesk. The working name "Blender CAD" is already used across repositories, the manifest `product` field (`blender-cad`) and all M0 documents.
- Honesty rules apply to positioning as well as features: no endorsement implications, no false association.
- The glossary disclaimer (§3) also covers Procore (third-party mark, no relation to this project) — it is used verbatim and never edited, so its wording is part of this decision.
- Mission criterion 2 (AutoCAD-familiar usability) is about interaction patterns, not identity: commands, keyboard conventions, palettes and drafting behavior may be familiar; branding and product identity must be ours.

## Decision

1. **Working name "Blender CAD"** for all internal artifacts through M0–M2. Machine identifiers (repository name `blender-cad`, release-manifest `product: "blender-cad"`) are stable identifiers, deliberately decoupled from display naming.
2. **Rename gate before public marketing**: the final public-facing name is chosen before any public marketing or release surface goes live. Gate criteria: trademark clearance search for the chosen name (verify — professional clearance before launch), domain/handle availability, review against the disclaimer, and a rename checklist (UI strings, documentation, packaging metadata — machine identifiers may remain untouched).
3. **Verbatim disclaimer wherever licensing or naming is discussed** (glossary §3): *"Blender is a registered trademark of the Blender Foundation. AutoCAD, Autodesk and Procore are trademarks of their respective owners. This project is an independent work, not affiliated with or endorsed by any of them."*
4. **No implied endorsement**: product materials never imply endorsement by Autodesk, the Blender Foundation or Z.ai; materials never present the product as AutoCAD, as stock Blender, or as the ZCode IDE.
5. **Rename-gate checklist** (all items must hold before the chosen name appears on any public surface):

| Item | Owner |
|---|---|
| trademark clearance search for the chosen name (verify — professional clearance) | TL |
| domain/handle availability confirmed | W1 |
| UI string audit — all user-facing surfaces updated in one change set | W1 |
| documentation + packaging metadata updated | W1/W2 |
| machine identifiers confirmed stable (repo name, manifest `product` field) | TL |
| disclaimer placement re-audit (every licensing/naming surface) | TL |

## Consequences

- All M0 documents use "Blender CAD"; a future rename is a planned, checklist-driven event rather than an emergency.
- Descriptive-name risk: "Blender CAD" references another party's mark and has weak distinctiveness for trademark purposes (verify with counsel before any public use — the rename gate exists for this reason).
- Machine identifiers stay stable across a rename; the release-manifest `product` field is schema-fixed and not user-facing, so a rename does not invalidate manifests.
- The rename gate is a scheduled task on the pre-marketing critical path, not an optional cleanup: launching public surfaces without it is a process violation and gets recorded as one.
- Public technical discussion before the gate uses "Blender CAD (working name)" with the glossary §3 disclaimer traveling alongside.

## Alternatives

1. **Decide the final product name now** — rejected: premature; no trademark clearance has been performed at M0.
2. **A name implying AutoCAD lineage** (e.g. an "Auto…" compound) — rejected: implies affiliation, violates the honesty rules and creates legal exposure.
3. **Ship under "Blender" alone ("Blender CAD mode")** — rejected: misrepresents the product as stock Blender and misuses the Blender mark.
