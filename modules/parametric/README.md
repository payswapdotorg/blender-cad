# Module: parametric

- **Status:** planned (no module code yet; the DOCUMENT-side data model it
  consumes is landed — bcdoc/3 SketchTable/ConstraintRecord/JunctionRecord/
  SolveReport per docs/00-architecture/m3-module-contracts.md; integration
  gated on the port-vs-FFI decision + the open (verify) gates, per
  par-solver-head-to-head.md §4/§6)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M3 (constraints live — glossary §11)

## Purpose

Geometric and dimensional constraints on top of the kernel's geometry: a
constraint graph, a solver (PlaneGCS candidate, subject to the adoption
matrix), and parametric editing so dimensions drive geometry.

## Owns

- Constraint graph over drafting entities (coincidence, tangency, parallelism, …)
- Dimensional constraints and the driving-parameter relationship
- Constraint solving (re-solve on edit) and solver reporting
- Parametric edit workflows (change a dimension, geometry follows)

## Does NOT own

- Entity storage (`document`) or exact geometry ops (`kernel`)
- Drafting UX behaviors (`drafting`); annotation rendering (`drawings`)
- Any UI panels (`shell`)

## FP areas

- PAR — parametric constraints

## Allowed dependencies

- `document`, `kernel`, `drafting`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `ConstraintGraph` — constraints over entity references; add/remove/query
- `ConstraintSolver` — solve/re-solve with convergence report (PlaneGCS-backed candidate)
- `DimensionalConstraint` — driving dimensions bound to geometry parameters
- `ParametricEdit` — apply a parameter change and re-solve atomically
- `SolverReport` — convergence status, residuals, violated constraints
- `SolverBenchmarkSet` — hooks used by TP-CAT-02 benchmark fixtures

## Tests

- docs/30-process/test-plan.md: TP-CAT-02 (solver sections become blocking at
  M3 entry). Suite home once code lands: `modules/parametric/tests/`.
