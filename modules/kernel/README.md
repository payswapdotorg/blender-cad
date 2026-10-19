# Module: kernel

- **Status:** planned (no code at M0)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M3 (OCCT integration live); OCCT bindings evaluation enters at M1 (glossary §11)

## Purpose

The precise geometry engine: OCCT-based B-rep and analytic geometry, 2D/3D
construction operations, and tessellation-for-display. Everything that needs
mathematically exact geometry calls this module; everything that only needs to
*draw* consumes its tessellated output.

## Owns

- B-rep solids, surfaces, curves and analytic primitives
- Construction and modification operations (booleans, fillets, offsets, trims)
- Tessellation for display (triangulation with adaptive tolerance)
- Precision/tolerance policy (the kernel epsilon policy cited by TP-CAT-02)
- The 3D modeling functional area (P3D)

## Does NOT own

- Storage, transactions, undo (`document`)
- Constraint solving (`parametric`)
- Rendering, materials, viewports — Blender-native + `shell`/`drawings`
- Any file-format mapping (`interchange`)

## FP areas

- P3D — 3D modeling (per glossary §5 map).

## Allowed dependencies

- `document` (geometry attaches to entities via the document model).

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `ShapeFactory` — create primitives (line/arc/circle sketches, solids, surfaces)
- `BRepOps` — boolean and modification operations on shapes
- `AnalyticGeometry` — exact curve/surface interrogation (points, tangents, intersections)
- `Tessellator` — display-mesh generation with tolerance input
- `TolerancePolicy` — the kernel-wide precision policy object
- `KernelSession` — OCP/OCCT bindings lifecycle wrapper (the M1 evaluation seam)

## Tests

- docs/30-process/test-plan.md: TP-CAT-02 (precise geometry & constraint
  solver). Suite home once code lands: `modules/kernel/tests/`.
