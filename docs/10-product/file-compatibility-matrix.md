# File Compatibility Matrix — AutoCAD 2027 Baseline

- **Status:** Active — M0 PLAN. Every support level in this document is a declared plan, not an implemented capability. Nothing is implemented at handoff.
- **Owner:** W2 (Interchange module)
- **Date:** 2026-10-19
- **Binding vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md); inventory: [feature-parity-inventory.md](feature-parity-inventory.md) plus `data/inventory/*.yaml`. If anything conflicts with the glossary, the glossary wins.

## 1. Purpose and honesty policy

This matrix defines which file formats the product commits to reading and writing, at which support tier, and under which conformance evidence a tier may be called "supported". It exists so that interop claims are falsifiable.

Binding rule: **an importer is not complete because it produces a visible drawing.** Completeness is measured by the round-trip fidelity classes (§5) and the TP-CAT-04 fixture corpus (§13), not by screenshots.

## 2. Target baseline

Target baseline is AutoCAD 2027's file formats. The DWG version code for the AutoCAD 2027 release is **unknown until release — (verify on release)**; it must not be guessed into docs or code.

| AutoCAD release | DWG version code | Confidence |
|---|---|---|
| R12 | AC1009 | high |
| 2000 | AC1015 | high |
| 2004 | AC1018 | high |
| 2007 | AC1021 | high |
| 2010 | AC1024 | high |
| 2013 | AC1027 | high |
| 2018 | AC1032 | high (also used by later releases through 2026) |
| 2027 | **unknown — (verify on release)** | none at M0 |

DXF has no magic code, but the 2027 DXF schema is likewise pending release — all 2027 rows below are `(verify)` until the format is published and fixture files exist.

## 3. DXF support matrix (PLAN)

ASCII and binary DXF are both in scope. Tiers: **P0** = drafting-core tier (blocks M2 exit), **P1** = common interop tier, **P2** = advanced/rare paths. All rows are PLAN at M0.

| DXF version | Read (plan) | Write (plan) |
|---|---|---|
| R12 | P0 — core subset | P0 — core subset |
| 2000 | P0 | P0 |
| 2004 | P1 | P1 |
| 2007 | P1 | P1 |
| 2010 | P1 | P1 |
| 2013 | P1 | P1 |
| 2018 | P0 | P0 |
| 2027 | (verify) pending format availability | (verify) pending format availability |

Implementation anchor: `ezdxf` (MIT). The P0 write tiers target 2018 + 2000 + R12 subset; older-entity warnings are surfaced to the user on version conversion (`FP-IO-003`).

## 4. DWG: read via LibreDWG, write conformance-gated

- **DWG read:** target milestone **M3**, via LibreDWG (GPL-3.0). Conformance-gated: reading is declared per version only when TP-CAT-04 fixtures for that version pass (`FP-IO-004`).
- **DWG write:** target milestone **M4**, via LibreDWG, **conformance-gated before enablement** — the write path ships dark until round-trip suites pass for the declared version tier (`FP-IO-005`).
- **ODA File Converter** is **dev-fixture tooling only** — used to generate reference fixtures for the conformance corpus. It is never a shipped dependency, runtime requirement, or user-facing import path. This is recorded to avoid accidental adoption of non-redistributable tooling.
- Known risk areas carried into planning: 3D solids internals (§9), custom/proxy objects (§6, §13), fonts (§7).

## 5. Round-trip fidelity classes and the loss ledger

Every importer and exporter records what it does not preserve. Classes:

| Class | Meaning |
|---|---|
| **GEOMETRY-EXACT** | Geometry round-trips with exact coordinates, types and parameters. |
| **VISUAL-EQUIVALENT** | Geometry is visually equivalent within tolerance (e.g. tessellated display of an analytic curve) but not parameter-identical. |
| **SEMANTIC-LOSS** | Data is dropped, approximated or restructured (properties, styles, history, constraint links). |

**Loss ledger format** — every importer/exporter run against the conformance corpus appends entries:

| Field | Content |
|---|---|
| `format` | format + version + operation (read/write) |
| `entity` | entity type or named object |
| `class` | GEOMETRY-EXACT / VISUAL-EQUIVALENT / SEMANTIC-LOSS |
| `detail` | what deviates: dropped properties, geometric approximation, semantic loss |
| `fixture` | TP-CAT-04 fixture id reproducing the case |
| `roundtrip` | pass/fail of the re-export comparison |

The ledger is a first-class product artifact (`FP-IO-026`), aggregated by CI, and feeds the per-format support-level declarations (§14). A format tier may not be promoted while SEMANTIC-LOSS entries lack either a fix or a documented user-facing note.

## 6. Entity coverage by tier (reference)

Entity coverage is **not duplicated** here; the inventory areas own it — DRAW (`data/inventory/draw.yaml`), ORG (`org.yaml`), ANN (`ann.yaml`), P3D (`p3d.yaml`). Reference grouping:

| Group | Tier (plan) | Contents (representative) |
|---|---|---|
| A — core 2D | P0 | LINE, ARC, CIRCLE, LWPOLYLINE, POINT, TEXT, MTEXT, XLINE/RAY, INSERT + block tables, LAYER/LTYPE tables, core dimension types, HATCH |
| B — documentation | P1 | full dimension family, MLEADER, TABLE, ELLIPSE, SPLINE, REGION, REVCLOUD, WIPEOUT, images, PDF underlays, xref structures |
| C — 3D | P1/P2 | 3DSOLID, surfaces, meshes, HELIX, 3DPOLY, solid history |
| D — limited/preserved | P2 | dynamic blocks (limited tier), MLINE (limited tier), proxy entities (round-trip preservation), unknown custom entities |

Every Group D claim carries a note in its inventory entry and an expected loss-ledger signature.

## 7. Xrefs and dependencies

- **Attach vs overlay** semantics (`FP-ORG-021`), **bind/insert** (`FP-ORG-022`), **detach/unload/reload** (`FP-ORG-023`).
- **Path types:** full, relative and no-path; repathing UI in the XREF manager (`FP-ORG-024`). Missing-dependency reporting is mandatory, not optional.
- **Nested xrefs:** tree display, depth handling, cycle detection — fixture category §13.10.
- **Images and PDF underlays:** attach/clip/fade (`FP-IO-007`, `FP-IO-008`, `FP-MOD-031`, `FP-MOD-032`).
- **Fonts:** TrueType handled natively; SHX font rendering uses a substitution mapping — `(verify)`; glyph-level SHX fidelity is not promised at M0. Font dependencies are included in eTransmit-like packaging (`FP-LAY-016`).

## 8. Layouts and plot

- Page setups per layout + import from other drawings (`FP-LAY-003`); viewports incl. clip/lock/maximize (`FP-LAY-004/005`); viewport layer overrides (`FP-LAY-006`).
- Plot styles: color-dependent **CTB** and named **STB** tables, attach per layout (`FP-LAY-009`).
- PDF publishing: page-setup-driven single-layout PDF (`FP-LAY-011`, engine `FP-IO-006`) and batch publish to one multi-page or separate PDFs (`FP-LAY-012`). Sheet-set data format is a P2 honest tier (`FP-IO-020`).
- OLE: excluded from embedding; rasterized fallback only (`FP-IO-009`).

## 9. 3D solids risk (honest statement)

DWG stores 3D solids in **proprietary SAT/ASM internals** (Autodesk ShapeManager lineage). LibreDWG's reconstruction of solid geometry varies by release and entity vintage. Consequences, recorded honestly:

1. Full-fidelity DWG solid round-trip is treated as **high-risk** and is not a P0/P1 claim; every solid import/export fixture run records its fidelity class in the loss ledger.
2. **STEP and IGES are the declared neutral exchange paths** for solid geometry (`FP-IO-012..014`).
3. Direct SAT import is `(verify)` — feasibility and licensing to be assessed at the adoption gate, never promised.
4. `FP-P3D-033` (solid history) additionally depends on preserving boolean chains; §13.13 covers the fixture side.

## 10. Scripts, macros and automation support levels

| Surface | Declared level | Notes |
|---|---|---|
| `.scr` script files | declared subset | batched command input as registered commands support it (`FP-CMD-018`); no LISP-in-scr |
| LISP-like API | declared subset, conformance-tested | command-invocation + entity-data-access subset (`FP-IO-022`). **Never claimed as full AutoLISP.** |
| `.pgp` alias files | supported | import into the command registry (`FP-CMD-004`) |
| CUIx | partial — `(verify)` | limited import scope (`FP-UX-019`) |
| Python CAD API | our own documented product API | **explicitly NOT the AutoCAD .NET API**; no false compatibility claim (`FP-IO-023`) |
| Action recorder | limited tier at M0 | record/replay command macros (`FP-IO-021`) |

## 11. BIM / IFC

- **IFC4** via IfcOpenShell + Bonsai through the `bim` module (`FP-IO-010`, `FP-IO-011`); import and export are both P1 targets.
- Entity mapping tiers are recorded through the loss ledger; IFC property sets that have no CAD-document counterpart are SEMANTIC-LOSS by default until mapped.
- Licensing note: Bonsai license history — `(verify)` at the adoption gate (glossary §9).

## 12. Manufacturing exchanges

- **STEP / IGES:** kernel-level (OCCT) — `FP-IO-012`, `FP-IO-013`, `FP-IO-014`.
- **STL / OBJ:** via the Blender-native bridge — `FP-IO-015` (P1), `FP-IO-016` (P2).
- **DXF for CAM downstream:** the P0/P1 DXF write tiers (§3) are the committed path; no CAM-specific dialect is promised beyond entity fidelity.

## 13. Edge-case fixture categories (TP-CAT-04 conformance corpus)

The interchange conformance suite must include fixtures in each category; a format tier cannot be promoted with empty categories:

1. **Spline fit data** — fit points vs control points, knots, weights, fit tolerance, closed splines.
2. **Hatch associativity** — boundary links, islands, associative updates after geometry edits.
3. **Dynamic blocks** — parameters, actions, visibility states (limited-tier expectations; see §6 Group D).
4. **MTEXT formatting codes** — stacked fractions, columns, inline codes, embedded fields.
5. **Dimension associativity** — definition points, style overrides, re-association after edits.
6. **Proxy entities** — unknown custom entity classes preserved for round-trip.
7. **Missing xrefs** — unresolved paths, notification behavior, partial open.
8. **Unicode text** — CJK, right-to-left scripts, combining marks, mixed encodings.
9. **Extreme coordinates** — 1e12-scale magnitudes, near-zero deltas, precision boundaries.
10. **Xref nesting** — depth ≥ 3, cycle detection, cross-overlay combinations.
11. **Linetype scaling** — LTSCALE / PSLTSCALE / CELTSCALE combinations across model/paper space.
12. **Annotative scaling** — multi-scale representations, per-viewport scale lists.
13. **3D solid boolean history** — chained booleans, post-boolean grip edits, history loss.

## 14. Support-level declaration policy

1. A format, version or dialect may be called **supported** only when the claim cites its conformance suite status: a `TP-*` test-plan ID, the passing fixture categories (§13), and recorded artifacts.
2. Support levels mirror the inventory status enum (`planned | in-progress | partial | blocked | verified`); the per-format carrier entries are `FP-IO-001..027`, and their `test` fields fill only with evidence.
3. The loss ledger (§5) is the running conformance record; CI aggregates it and blocks promotion of tiers with unrecorded losses.
4. `(verify)` tags in this document are re-verification obligations routed through the component adoption gate (glossary §9) — the 2027 DWG code (§2), SHX substitution (§7), SAT import (§9), CUIx scope (§10) and the DST-like format (§8) are the open items at M0.
5. Any change to a declared tier is a re-review: update this matrix, the inventory entries, and regenerate `docs/10-product/inventory-tables.md` in the same change. Drift is a CI failure.

Related: [feature-parity-inventory.md](feature-parity-inventory.md) (methodology, index, limited-tier declarations), `docs/30-process/test-plan.md` (TP registry, task 1-d), `docs/00-architecture/component-adoption-matrix.md` and `docs/00-architecture/license-inventory.md` (task 1-a).
