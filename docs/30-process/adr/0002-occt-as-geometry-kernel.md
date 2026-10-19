# ADR-0002: OCCT as the geometry kernel

- **Status:** Proposed — OCCT is the leading candidate and the planning baseline; the binding-strategy sub-decision is explicitly deferred to M3 entry.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## Context

- The `kernel` module (glossary §4) must provide exact B-rep solids/surfaces, analytic 2D/3D geometry, booleans, fillets/chamfers, projections, and STEP/IGES I/O — the backbone for the 3D modeling (P3D area), parametric constraints (PAR area) and interchange (IO area) work.
- At M0 nothing is implemented; the kernel is a plan with a candidate dependency.
- Candidate ecosystem: OCCT (via bindings: OCP, pythonocc-core, or an in-tree pybind11 extension), the SolveSpace kernel (evaluate-only), FreeCAD components (reference/study).
- Packaging reality: Blender extensions historically ship as Python-level add-ons; the platform's policy on bundled native libraries is the open question the binding evaluation must answer (verify at the first packaging milestone).

## Decision

1. **OCCT is the leading candidate** for the precise geometry kernel (LGPL-2.1 with exception; license confidence high per glossary §9).
2. **Binding strategy is deferred to M3 entry**, evaluated against: (a) performance on hot paths (entity create/modify, booleans, tessellation); (b) packaging under Blender extension-platform constraints (verify policy on bundled native libraries at the first packaging milestone); (c) Python-bindings stability across OCCT upgrades; (d) coverage of required OCCT modules. Options and trade-offs are recorded in `docs/00-architecture/document-model-and-geometry-kernel.md` §5.2 (OCP wheels — Apache-2.0; pythonocc-core — LGPL (verify); in-tree pybind11 extension — MIT).
3. **PlaneGCS is the candidate 2D constraint solver** (LGPL, confidence medium — (verify)) for the PAR area; FreeCAD's integration is studied as the reference implementation.
4. **Adoption gates** (before any `adopted` status in the release manifest): binding evaluation recorded; benchmark evidence with test IDs (TP-CAT-02 geometry/constraints); LGPL compliance recheck in `license-inventory.md`; accepted packaging plan.

Binding-evaluation criteria (the M3-entry decision record must fill in every row):

| Criterion | Measure | Pass bar (planning) | Method |
|---|---|---|---|
| performance | entity create/modify, boolean ops, tessellation | within the performance budgets of the document-model doc §8 | benchmark suite, evidence with test IDs |
| packaging | wheel/binary size; extension-platform acceptance | platform policy verified (verify); size budget accepted | packaging dry-run |
| binding stability | breakage across one OCCT minor upgrade | no breaking change without a documented migration path | upgrade test |
| coverage | required OCCT modules reachable | all kernel capabilities (§5.1 of the document-model doc) available | kernel capability matrix |

## Consequences

- The kernel API is designed **document-first** (document-level entity types; kernel-agnostic) so the binding choice stays contained behind the `kernel` module boundary.
- Packaging risk (large native binaries) remains open until the M3-entry evaluation; extension-platform policy verification is a first-packaging-milestone item.
- PlaneGCS license verification is a gate item before any vendoring; the FreeCAD study path needs per-copy license review if code is copied.
- Fallback: if no prebuilt binding passes the packaging gate, the in-tree pybind11 extension is the fallback with a deliberately reduced OCCT surface — recorded in the M3-entry decision record rather than improvised.
- OCCT version pin policy: the kernel module records the OCCT version in the release manifest `dependencies[]` when adopted; OCCT upgrades re-run the binding-stability test before any bump.
- SolveSpace stays evaluate-only as a comparison baseline for PlaneGCS conformance results — no adoption path at M0.

## Alternatives

1. **Build a kernel from scratch** — rejected: multi-year effort inconsistent with the milestone plan and with honesty about delivery risk.
2. **SolveSpace's kernel** — evaluate-only: smaller ecosystem and B-rep coverage gaps versus AutoCAD-class needs (verify).
3. **Mesh-first modeling (no B-rep)** — rejected: violates the precision guarantees (exact analytic representation persists; tessellation is display-only).
4. **CGAL-based CSG approach** — rejected: not a B-rep kernel; boolean/precision model mismatch for CAD documentation work (verify).
