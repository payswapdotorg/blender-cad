# Module: bim

- **Status:** planned (no code at M0)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M4 (IFC/BIM bridge — glossary §11)

## Purpose

BIM workflows through Bonsai (BlenderBIM) and IfcOpenShell: carry CAD
documents into IFC projects and back, with schema validation — the bridge
between drafting-world files and building-information models.

## Owns

- BIM project mapping from/to the CAD document model
- IFC schema validation and round-trip discipline (with `interchange`)
- Bonsai integration surface and lifecycle
- BIM-specific classification/property mappings

## Does NOT own

- IFC file-level I/O machinery (`interchange`)
- Geometry (`kernel`) or document state (`document`)
- UI workbenches (`shell`)

## FP areas

- IO — interchange & file compatibility (BIM entries per glossary §5 map)

## Allowed dependencies

- `document`, `kernel`, `interchange`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `BimProject` — BIM project state bound to a CAD document
- `IfcSyncSession` — push/pull changes between document model and IFC store
- `BonsaiBridge` — lifecycle + interop with the Bonsai toolset integration
- `ClassificationMap` — BIM classification and property-set mapping
- `IfcValidationReport` — validation results consumed by TP-CAT-05

## Tests

- docs/30-process/test-plan.md: TP-CAT-05 (BIM & specialist toolset — BIM
  sections). Suite home once code lands: `modules/bim/tests/`.
