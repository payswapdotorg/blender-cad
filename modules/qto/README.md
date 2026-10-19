# Module: qto

- **Status:** planned (no code at M1 — added by the M1 scope expansion, glossary §4)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding); scope record: docs/10-product/scope-expansion-m1.md
- **Target milestone:** M5 window (QTO/BOQ/estimating core per FP-QTO P1 — glossary §11, scope-expansion §3)

## Purpose

Construction quantity takeoff from models and 2D geometry, bill-of-quantities
(BOQ) structuring, rate/cost item libraries, estimate rollups and variant
comparison, plus estimate exports (CSV/PDF). Reads element and classification
data through the `bim` module and 2D geometry through `drafting`.

## Owns

- Model-based and 2D-geometry quantity takeoff workflows (area QTO, FP-QTO-*)
- Quantity categories, unit rules and measurement rule templates
- BOQ structure, element-to-item mapping, cost codes, rate libraries
- Estimate assembly: rollups, variants, reconciliation, export

## Does NOT own

- Element geometry and classification data (`bim`, `kernel`)
- 2D entity creation and snap mechanics (`drafting`)
- Schedule table objects and publishing (`drawings`)
- File-level IFC exchange (`interchange`)

## FP areas

- QTO — quantity takeoff, BOQ & estimating (`data/inventory/qto.yaml`, 18 entries)

## Allowed dependencies

- `document`, `kernel`, `drafting`, `drawings`, `bim`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `TakeoffSession` — scoped takeoff run over an element set or 2D selection
- `QuantityRuleSet` — category/unit rules and deduction rules per element class
- `BoqModel` — sections, trades, items, part-sets with units
- `RateLibrary` — rate/cost items with unit rates, waste factors, tax classes
- `Estimate` — rollups, variants, cost codes, contingencies
- `EstimateExporter` — CSV (documented schema) and PDF (via drawings publish)

## Tests

- docs/30-process/test-plan.md: TP-CAT-05 (BIM & specialist toolset — QTO
  sections: takeoff accuracy). Suite home once code lands:
  `modules/qto/tests/`. Estimate exports map to a TP-CAT-04-style round-trip
  check when they land (scope-expansion-m1.md §3).
