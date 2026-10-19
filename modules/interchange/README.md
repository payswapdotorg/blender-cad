# Module: interchange

- **Status:** planned (no code at M0)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1 (DXF read/write via ezdxf); M3–M4 (DWG read, then write; IFC/STEP — glossary §11)

## Purpose

File compatibility: DXF/DWG/IFC/STEP import and export, external references
(xrefs), round-trip conformance, and the loss ledger that records every
fidelity deviation instead of hiding it (ADR-0003, DXF-first strategy).

## Owns

- DXF read/write (ezdxf candidate) — the first-class interchange path
- DWG read then write (LibreDWG candidate; license gate per adoption matrix)
- IFC and STEP bridges (with `bim` for IFC workflows)
- Xrefs (attach/reload/overlay semantics)
- Round-trip conformance machinery and the loss ledger

## Does NOT own

- Document persistence semantics (`document`)
- Geometry evaluation (`kernel`)
- BIM workflow semantics (`bim`)
- Any UI (`shell`)

## FP areas

- IO — interchange & file compatibility

## Allowed dependencies

- `document`, `kernel`, `drafting`, `drawings`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `DxfIO` — read/write DXF with entity mapping tables (ezdxf-backed)
- `DwgIO` — DWG read (M3) then write (M4) via LibreDWG
- `IfcBridge` / `StepBridge` — schema mapping in/out
- `XrefManager` — attach/reload/clamp external references
- `RoundTripHarness` — the load→save→reload→compare machinery used by TP-CAT-04
- `LossLedger` — recorded deviations per file, queryable by test and review

## Tests

- docs/30-process/test-plan.md: TP-CAT-04 (round-trip conformance; engine
  suites here, golden corpus in `modules/testing/roundtrip/`). Suite home
  once code lands: `modules/interchange/tests/`.
