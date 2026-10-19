# Module: drawings

- **Status:** planned (no code at M0)
- **Owner:** W1
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M2 (annotations/layouts/publish — glossary §11)

## Purpose

Technical documentation on top of the model: annotation objects (text,
dimensions, tables, hatches), layouts and viewports, dimension/text/table
styles, annotation scale, and plot/publish. The module that turns a model into
a drawing package.

## Owns

- Annotation objects and their associativity to model geometry
- Layouts, viewports and layout tabs semantics
- Dimension/text/table/hatch style system and annotation scale
- Regeneration: annotation stays correct when model geometry changes
- Plot and publish (including PDF output)

## Does NOT own

- Model geometry (`kernel`, `drafting`)
- Layer/block organization semantics (`document`, `drafting`)
- UI hosting of layout tabs (`shell`)

## FP areas

- ANN — annotation (text, dims, tables, hatches)
- LAY — layouts, viewports, plot/publish

## Allowed dependencies

- `document`, `drafting`, `kernel`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `AnnotationFactory` — create text/dimension/table/hatch entities with styles
- `RegenerationEngine` — recompute annotation state after model edits (idempotent)
- `LayoutModel` / `ViewportModel` — layouts, viewports, scale and visibility
- `StyleManager` — dimension/text/table styles; annotation scale policy
- `PlotPublisher` — plot/publish pipeline with reproducible output (PDF)

## Tests

- docs/30-process/test-plan.md: TP-CAT-03 (drawing regeneration & technical
  documentation). Suite home once code lands: `modules/drawings/tests/`.
