# Module: drafting

- **Status:** planned (no code at M0)
- **Owner:** W1 (UX side) / W2 (geometry side) — glossary §10
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1–M2 (skeleton entities at M1; drafting core at M2 — glossary §11)

## Purpose

The 2D drafting experience: entity creation and modification behaviors, the
precision-input engine (osnap, ortho, polar, tracking, dynamic input),
selection, grip editing, and layers/blocks editing UX. This is where the
"feels like AutoCAD" drafting behavior lives.

## Owns

- 2D entity behaviors (line, circle, arc, polyline, … and modify operations)
- Precision-input engine: object snaps, ortho/polar modes, tracking, dynamic input
- Selection model (window/crossing, filters, cycling) and grip editing
- Layers/blocks editing behaviors exposed to the user

## Does NOT own

- Entity persistence and undo (`document`)
- Exact geometry mathematics (`kernel`)
- Annotation objects and layouts (`drawings`)
- Ribbon/palette UI hosting (`shell`)
- Command registration and prompt sequencing (`commands`)

## FP areas

- DRAW — 2D drawing entities
- MOD — modify operations
- PREC — precision input & snaps
- ORG — layers, blocks, organization

## Allowed dependencies

- `document`, `kernel`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `DraftEntityFactory` — 2D entity creation with drafting defaults
- `SnapEngine` — osnap resolution, ortho/polar/tracking constraints
- `PrecisionInputParser` — keyboard/coordinate entry (dynamic input syntax)
- `SelectionModel` — selection sets, filters, hit-testing hooks
- `GripEditor` — grip modes and grip-driven modification
- `ModifyOpsRegistry` — modify behaviors (move/copy/rotate/trim/…) as reusable operations

## Tests

- docs/30-process/test-plan.md: TP-CAT-01 (drafting & command-system
  functional; drafting sections). Suite home once code lands:
  `modules/drafting/tests/`.
