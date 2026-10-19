# Module: asset

- **Status:** planned (no code at M1 — added by the M1 scope expansion, glossary §4)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding); scope record: docs/10-product/scope-expansion-m1.md
- **Target milestone:** M5–M6 window (reality capture + defect/repair/maintenance records per FP-RCM P1 — glossary §11, scope-expansion §4)

## Purpose

Reality capture ingestion (point clouds LAS/LAZ/E57, photogrammetry), scan
registration and deviation analysis against design models, defect markers
with domain classification (buildings, machines, vehicles, electronics),
condition grading, repair-plan drawing generation, maintenance records and
schedules, work-order export, and the asset registry linking model elements
to asset IDs. Area RCM (FP-RCM-*).

## Owns

- Reality capture ingest and registration pipelines (area RCM, FP-RCM-*)
- Defect markers, classification and condition grading data
- Asset registry, maintenance records/schedules, work orders
- Deviation analysis against design models and repair-plan drawing generation

## Does NOT own

- Element geometry and BIM semantics (`bim`, `kernel`)
- 2D entity creation and snap mechanics (`drafting`)
- Sheets, annotation styles and publishing (`drawings`)
- File-level exchange beyond reality-capture formats (`interchange`)

## FP areas

- RCM — reality capture, defects, repair & maintenance (`data/inventory/rcm.yaml`, 20 entries)

## Allowed dependencies

- `document`, `kernel`, `drafting`, `drawings`, `interchange`, `bim`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `PointCloudSource` — LAS/LAZ/E57 ingest (PDAL-backed, planned)
- `ScanRegistration` — target/cloud-to-cloud registration with residual report
- `DeviationAnalysis` — as-built vs design deviation maps and statistics
- `DefectMarker` / `DefectClassifier` — domain defect classes and severity scales
- `ConditionRecord` — grading history per asset and element
- `AssetRegistry` — asset IDs linked to model elements, domains, locations
- `MaintenanceRecord` / `WorkOrderExporter` — records, schedules, CSV/PDF export

## Tests

- docs/30-process/test-plan.md: TP-CAT-05 (BIM & specialist toolset — asset
  sections: asset records integrity). Suite home once code lands:
  `modules/asset/tests/`.
