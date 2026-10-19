# Scope Expansion at M1 Entry — BIM / QTO / RCM Capability Groups

- **Status:** Active — the repository-owned record of the M1 scope expansion per glossary §15 (M1 amendment). **All content is `planned`; nothing is implemented at M1.**
- **Owner:** TL (record); module ownership W2 (glossary §10)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding — §4 modules as amended, §5 areas as amended, §15 amendment record). If this document conflicts with the glossary, the glossary wins.

## 1. What changed at M1 entry

Three capability groups were added to the product scope (glossary §15 M1
amendment; module table and area table already amended in glossary §4/§5):

| Group | New area | New module | Inventory file | Entries |
|---|---|---|---|---:|
| Architecture & BIM workflows (Archicad/Revit-comparable) | `BIM` | `bim` (existing module, now also owns area BIM) | `data/inventory/bim.yaml` | 30 |
| Construction quantity takeoff, BOQ & estimating | `QTO` | `qto` (new) | `data/inventory/qto.yaml` | 18 |
| Reality capture, defect diagnostics, repair planning & maintenance records | `RCM` | `asset` (new) | `data/inventory/rcm.yaml` | 20 |

Plus four explicit interop-limitation carriers in the IO area:
`FP-IO-028` … `FP-IO-031` (§5 below). Total inventory grows 489 → **561
entries across 17 areas**; the three new areas carry **no P0** entries (P0
remains reserved for the M2 drafting core, per the priority interpretation
policy in [feature-parity-inventory.md](feature-parity-inventory.md) §3.6).

**Honesty rule (binding):** every entry in the three new areas is
`status: planned`, `test: ""` at M1. Nothing in this document is a claim of
implementation. Naming: BIM/QTO/RCM workflows are comparable to the relevant
Archicad/Revit-class capabilities by behavior; this product is not Archicad,
not Revit, and makes no certification or compatibility claim (glossary §3
disclaimer applies).

## 2. BIM — Architecture & BIM workflows

- **Capability statement:** model architectural elements (walls with joins,
  hosted doors/windows, stairs, railings, roofs, slabs, columns, beams,
  shaft openings) as IFC-mappable objects; spaces with net/gross area
  computation; zones; element and door/window schedules; classification
  reference mapping; Pset-style property and material management; IFC export
  validation; story/level management; model-generated plan/section/elevation
  views. Renovation filters, clash checks, model checker, BCF issue
  workflow and COBie-style handover export are explicit P2.
- **Feature-ID range:** `FP-BIM-001` … `FP-BIM-030`.
- **Priorities:** 24 × P1, 6 × P2, 0 × P0.
- **Target module:** `bim` (owner W2; fp_areas `IO`, `BIM`).
- **Dependency components:** `ifcopenshell`, `bonsai`, `occt`, `shapely`,
  `blender-native` (adoption gates per glossary §9 / component adoption
  matrix; Bonsai license `(verify)` at the gate).
- **Test IDs:** TP-CAT-05 — BIM sections; suites in `modules/bim/tests/`
  once code lands; IFC conformance in `modules/testing/bim/` (test-plan §2,
  §5 as amended).
- **Milestone ownership:** **M4 window** (IFC/BIM bridge is the entry —
  milestone-plan §7), with depth through **M6**. BIM architecture workflows
  begin at M4 per the M4 deliverables line "BIM architecture workflows begin
  (element modeling through the bim module per FP-BIM P1 items)".
- **Acceptance criteria (testable, honest):** *Delivered* means — (1) the
  element commands produce IFC-valid entities on the fixture set (TP-CAT-05
  IFC validation clean); (2) schedules recompute after element edits;
  (3) generated plan/section/elevation views regenerate on model change;
  (4) every IFC exchange gap lands in the loss ledger (ADR-0003). Until the
  corresponding TP-CAT-05 suites are green with recorded artifacts, all
  `FP-BIM-*` entries remain `planned` — no partial capability may be
  advertised.

## 3. QTO — Quantity takeoff, BOQ & estimating

- **Capability statement:** model-based quantity takeoff by element and
  classification; 2D-geometry takeoff (lengths/areas from drawing entities)
  with on-screen boundary picking; quantity categories with unit rules and
  formulas; BOQ structure (sections, trades, items, part-sets);
  element-to-item mapping; rate/cost item libraries; estimate rollups,
  variants and cost codes; CSV and PDF estimate export; measurement rule
  templates, reconciliation, work packages and contingencies as P2.
- **Feature-ID range:** `FP-QTO-001` … `FP-QTO-018`.
- **Priorities:** 14 × P1, 4 × P2, 0 × P0.
- **Target module:** `qto` (new; owner W2; depends on document, kernel,
  drafting, drawings, bim).
- **Dependency components:** `ifcopenshell`, `occt`, `shapely`, `ezdxf`
  (2D takeoff reads entities through the drafting/ezdxf paths).
- **Test IDs:** TP-CAT-05 — QTO sections; suites in `modules/qto/tests/`
  (takeoff accuracy against known-quantity fixtures). Estimate exports
  (`FP-QTO-013`, `FP-QTO-014`) additionally map to a TP-CAT-04-style
  round-trip check (export → re-read → compare) when they land.
- **Milestone ownership:** **M5 window** (milestone-plan §8 deliverable
  "QTO/BOQ/estimating core (FP-QTO P1)"); P2 items may extend into M6.
- **Acceptance criteria (testable, honest):** *Delivered* means — (1)
  takeoff of a fixture model reproduces reference quantities within the
  documented unit rules (TP-CAT-05 takeoff-accuracy suite green); (2) BOQ
  rollups are reproducible from the estimate file; (3) CSV export re-imports
  into the estimate with zero loss of items. Until those suites exist and
  pass, all `FP-QTO-*` entries remain `planned`.

## 4. RCM — Reality capture, defects, repair & maintenance

- **Capability statement:** point-cloud import (LAS/LAZ/E57) and scan
  registration with residual-error reports; photogrammetry ingest;
  scan-to-mesh; deviation analysis against design models; defect markers
  with classification (cracks, spalling, corrosion, dents) and domain
  libraries covering **buildings, machines, vehicles and electronics**
  explicitly (`FP-RCM-007`, `FP-RCM-015` … `FP-RCM-019`); condition grading
  and history timelines; inspection sessions; repair-plan drawing
  generation; maintenance records and schedules; work-order export; asset
  registry linking model elements to asset IDs.
- **Feature-ID range:** `FP-RCM-001` … `FP-RCM-020`.
- **Priorities:** 12 × P1, 8 × P2, 0 × P0.
- **Target module:** `asset` (new; owner W2; depends on document, kernel,
  drafting, drawings, interchange, bim).
- **Dependency components:** `pdal`, `gdal`, `shapely`, `occt`,
  `blender-native`, `ezdxf` (repair-plan drawings publish through the
  drawings/ezdxf path).
- **Test IDs:** TP-CAT-05 — asset sections; suites in `modules/asset/tests/`
  (asset records integrity: registry links, record/defect references,
  work-order export round-trip).
- **Milestone ownership:** **M5–M6 window** (milestone-plan §9 deliverable
  "reality capture + defect/repair/maintenance records (FP-RCM P1)").
- **Acceptance criteria (testable, honest):** *Delivered* means — (1) a
  licensing-clean sample cloud imports, registers and produces a residual
  report (TP-CAT-05 asset suite green); (2) defect markers survive document
  save/reopen with classification intact; (3) work-order export re-imports
  with zero record loss; (4) deviation analysis reproduces reference
  statistics within documented tolerances on the fixture set. Until those
  suites exist and pass, all `FP-RCM-*` entries remain `planned`.

## 5. Interoperability limitations (explicit, binding)

The product does **NOT** claim lossless native Archicad (`.pln`/`.pla`) or
Revit (`.rvt`) project round-tripping. This implements the glossary §4
interop honesty rule and the loss-ledger policy of ADR-0003.

| Path | Carrier | Declared level |
|---|---|---|
| Archicad `.pln`/`.pla` import | `FP-IO-028` (P2) | No native `.pln`/`.pla` round-trip; IFC-based exchange only with recorded loss ledger (ADR-0003) |
| Revit `.rvt` import | `FP-IO-029` (P2) | No native `.rvt` round-trip; IFC-based exchange only with recorded loss ledger (ADR-0003) |
| Archicad/Revit export via IFC | `FP-IO-030` (P1, `ifcopenshell`) | The supported exchange path; property sets without a CAD-document counterpart are SEMANTIC-LOSS until mapped (file-compatibility-matrix §5/§11) |
| BCF issue exchange | `FP-IO-031` (P2) | Topics, viewpoints, comments only; model-side workflow is `FP-BIM-029` |
| Point clouds LAS/LAZ/E57 | `FP-RCM-001` (P1, `pdal`) | Reality-capture ingestion only; no AutoCAD RCP/RCS compatibility claim |

Exchange with those ecosystems is via **IFC (and DXF/DWG where applicable)**
with every gap recorded in the loss ledger (`FP-IO-026`; ADR-0003; the
per-format rows live in [file-compatibility-matrix.md](file-compatibility-matrix.md) §11).

## 6. Milestone ownership summary and honest status

| Group | Window | Depth |
|---|---|---|
| BIM architecture workflows | M4 (bridge entry, milestone-plan §7) | through M6 |
| QTO / BOQ / estimating | M5 (milestone-plan §8) | P2 items may extend to M6 |
| Reality capture / defect / repair / maintenance | M5–M6 (milestone-plan §9) | P1 at M6 exit; P2 tracked, not promised |

Risk posture (milestone-plan §13 R8 as amended): the specialist scope is
now broader — seven toolsets **plus** BIM/QTO/RCM — for the same capacity
(TL + 3 workers, glossary §10); the mitigation is unchanged and strict:
priority-gated sequencing (no P0 in these areas), M4–M6 windows behind the
conformance core, and status flips only with TP-ID + evidence (glossary §5).

**At M1, none of this is implemented.** There is no BIM command, no takeoff
engine, no point-cloud reader in the codebase. All 72 new entries (68 area
entries + 4 IO carriers) are `status: planned`, `test: ""`. The generated
tables ([inventory-tables.md](inventory-tables.md)) are the machine-checked
rendering of that plan.

## 7. Maintenance

1. This record is the scope truth for the three groups; inventory YAML
   remains the per-feature source of truth. Keep both in step.
2. New entries take the next free `NNN` per area and require re-review
   (feature-parity-inventory.md §7 rules 1–3).
3. Milestone reports cite `FP-BIM-*` / `FP-QTO-*` / `FP-RCM-*` items by ID
   from M1 onward (feature-parity-inventory.md §5 citation rule).
4. Priority/status flips follow glossary §5 evidence rules — no exceptions
   for these areas, however specialist.
