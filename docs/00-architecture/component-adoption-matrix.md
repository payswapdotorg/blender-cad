# Component adoption matrix

- **Status:** M0 planning baseline — **nothing is adopted at M0**. Every row below is `candidate` or `evaluate` and carries an explicit adoption gate.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## 1. Preamble: listing ≠ integrated

Appearance in this matrix is **not** an integration decision. It means the component is on the radar with a defined role, risks and gate. A row moves to `adopted` in the release manifest (`dependencies[].status`) only when its gate criteria are met with recorded evidence (test IDs + artifacts, per the glossary §5 evidence rule), its license-inventory row is verified at that date, and the TL signs the release-manifest change.

At handoff the release manifest records `dependencies: []` — **zero adoptions**. The matrix is maintained by the TL and changes only through review. Rows failing a gate are never silently dropped: the failure is recorded and the row stays `candidate`/`evaluate`.

Honest gap stated up front: **dynamic-block semantics (ORG area) have no open-source implementation** and must be built in-product; no row below supplies them.

Status vocabulary for this matrix:

- `candidate` — planned for adoption behind a named gate; may appear in glossary §5 `dep` codes for feature authors.
- `evaluate` — under consideration; may be excluded without a gate failure (the exclusion itself is recorded with a reason).
- `adopted` — forbidden at M0; only reachable via the §3 gate process with recorded evidence.
- `rejected` — terminal state with a recorded reason; rejected rows stay in the manifest history, never silently deleted.

The matrix is re-baselined at each milestone gate calendar event (§7); rows never change status outside a reviewed change.

## 2. Column definitions

| Column | Semantics |
|---|---|
| Role in product | The capability the component would provide. Written as a plan, not a claim. |
| Target module | The module (of the 13, glossary §4) that would own the integration. |
| License (confidence) | License + glossary §9 confidence tag; `(verify)` items are unresolved until their gate. |
| Integration path | How the component would reach the product (pip dep, native lib, sidecar, study-only, fixture-only). |
| Status | `candidate` (planned for adoption behind a gate) or `evaluate` (under consideration; may be excluded). **No row may say `adopted` at M0.** |
| Rationale | Why this component is on the list. |
| Key risks | The honest failure modes, including licensing, maturity and packaging risks. |
| Adoption gate criteria | The concrete, checkable conditions required before the release-manifest status changes. |
| ADR | The architecture decision that governs the row, where one exists. |
| Notes | Extra facts that must not be lost (pins, exclusions, hard rules). |

## 3. Status lifecycle and gate process

```mermaid
stateDiagram-v2
    [*] --> evaluate : listed with a role
    evaluate --> candidate : use-case confirmed, gate defined
    evaluate --> rejected : excluded, reason recorded
    candidate --> adopted : gate criteria met + license verified + manifest entry
    candidate --> rejected : gate failed or superseded
    adopted --> candidate : re-gate triggered (upstream event, license change)
    rejected --> [*]
```

Gate process (how a row becomes `adopted`):

1. Gate criteria from §4 are met; evidence recorded with test IDs + artifacts (the glossary §5 evidence rule applied to components).
2. The component's license-inventory.md row is verified at that date (confidence tag refreshed; `(verify)` items resolved, or the row stays candidate).
3. The release manifest gains/updates a `dependencies[]` entry with `status: adopted` (schema per glossary §8; `module` must exist in `modules/modules.json`).
4. TL sign-off in the same reviewed change; rejection is recorded as `status: rejected` with a one-line reason.

## 4. Matrix

| Component | Role in product | Target module | License (confidence, glossary §9) | Integration path | Status | Rationale | Key risks | Adoption gate criteria | ADR | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| OCCT | Precise geometry kernel: B-rep, analytic geometry, booleans, fillets, projections, STEP/IGES | kernel | LGPL-2.1 with exception (high) | vendored native library via chosen binding (document-model doc §5.2) | candidate | only credible open-source full B-rep kernel matching AutoCAD-class needs | large binary footprint; packaging; binding maintenance | M3-entry binding evaluation (perf, packaging, binding stability); LGPL compliance recheck; benchmark evidence with test IDs | ADR-0002 | evaluation criteria fixed in ADR-0002 |
| OCP | OCCT Python bindings — candidate binding layer | kernel | Apache-2.0 (high) | pip wheels | evaluate | proven wheels; fastest to stand up | wheel size; OCCT-version coupling | part of the ADR-0002 binding evaluation; extension-platform packaging rules (verify) | ADR-0002 | |
| FreeCAD components | Reference implementations to study (sketcher patterns, importers, PlaneGCS usage) | kernel / parametric / interchange (study) | LGPL-2.1+ per-module exceptions (high) | source study only by default | evaluate | large proven open-source CAD codebase to learn from | per-module license diversity; drift from upstream | per-copy license review + attribution if any code is copied; default = no product dependency | — | study-only default is recorded policy |
| PlaneGCS | 2D geometric constraint solver | parametric | LGPL-2.1-family — **verified 2026-10-20 at FreeCAD 1.1.4 pin** (all 11 planegcs per-file headers verbatim + root LICENSE = full LGPL-2.1 + SPDX tags in sibling files; legacy "Library GPL v2-or-later" wording recorded — high) + Eigen 3.4.0 MPL-2.0 (verified at the release artifact AND at solvespace's `3147391d` gitlink — the m3-eval §9 blocker cleared) | vendor with build (NOT chosen); reference integration only | **fallback + reference** (was candidate) | proven in FreeCAD's sketcher; native 5-DOF arc parameterization; correct redundancy attribution (rect fixture: named the duplicate where slvs misattributed) | **measured in the head-to-head (2026-10-20)**: W1 slot converges to ~2.5e-5 only (4 checks fail at 1e-6) with formulation/order-dependent diagnosis (dof 0/2/4 probes recorded); the exactly-redundant rect does NOT solve even via FreeCAD's full 4-step chain; no named-constraint diagnostics on structurally-clean numerical failures; ~220x slower than SolidCraft at N=200 | head-to-head gate CLOSED — SolidCraft-solver won every measured dimension; PlaneGCS is the named fallback + reference (translation-pattern notes committed) — see [par-solver-head-to-head.md](par-solver-head-to-head.md) | ADR-0002 context; decision record par-solver-head-to-head.md | evidence: experiments/solver-h2h/results/planegcs-conformance.json (121 checks: 112 pass / 9 honest failures) + results/head-to-head.json |
| build123d | Python CAD scripting API — candidate user-facing scripting layer | kernel / scripting | Apache-2.0 (high) | pip dependency if adopted | evaluate | modern API over OCP | overlaps kernel API design; version churn | use-case decision (user scripting API vs internal); API stability review; otherwise exclude | — | |
| CadQuery | Python CAD scripting API — alternative to build123d | kernel / scripting | Apache-2.0 (high) | pip dependency if adopted | evaluate | mature; same OCP base | duplicate dependency vs build123d | same evaluation as build123d; adopt at most one | — | |
| ezdxf | First-class DXF read/write | interchange | MIT (high) | pip dependency | candidate | mature, documented DXF path; M1 DXF read/write depends on it | DXF version/entity coverage gaps become loss-ledger entries | M1 DXF read/write acceptance (TP-CAT-04); performance on large files; vendoring plan | ADR-0003 | every round-trip gap recorded in the loss ledger |
| LibreDWG | DWG read (M3) and write (M4) | interchange | GPL-3.0 (high) | native library bundled with the extension | candidate (gated) | the only open-source DWG library | **write-path maturity** (honest risk); 3D-solids SAT/ASM representation risk | read gate M3: TP-CAT-04 read conformance; write gate M4: write conformance + write-path stability review; GPL-3.0 compliance review | ADR-0003 | STEP is the neutral 3D exchange for solids (OCCT); dynamic-block semantics are NOT provided by any open-source DWG library — built in-product |
| ODA File Converter | Dev-fixture tooling: DWG/DXF version conversion for test fixtures | testing | proprietary freeware (verify) | offline CI/dev tool only | evaluate | produces reference fixtures for TP-CAT-04 without product dependency | proprietary terms (verify); availability; must never leak into the product | usage documented in testing module; hard rule: never bundled, never linked, never shipped | ADR-0003 | **never a product dependency — fixture tooling only** |
| SolveSpace | Reference/alternative constraint solver and small kernel (comparison) | parametric (study) | GPL-3.0-or-later — **verified 2026-10-20 at 477d4c8** (COPYING.txt + README.md:356 + CONTRIBUTING.md:20-21; **no linking exception** — the wheel's COPYING.txt is plain GPLv3; “exception”-looking text is standard GPL §7 template, not a grant) (high) | evaluate-only; no integration planned | evaluate | independent solver to compare against PlaneGCS results | not a drop-in for 2D drafting constraints at scale — **now measured**: fails exactly-redundant systems, no incremental path, linux-aarch64 wheel missing (see cad-sketcher-evaluation.md §4.1) | evaluation note only; no adoption path unless PlaneGCS fails its gate — and then only per the re-review conditions in cad-sketcher-evaluation.md §4.1 (blockers re-reviewed, never waived) | — | evaluate-only; license verified + evaluated via the CAD Sketcher wheel — see §4.3 and [cad-sketcher-evaluation.md](cad-sketcher-evaluation.md) |
| Bonsai (BlenderBIM) | BIM workflows inside Blender (IFC authoring patterns, Blender-integration experience) | bim | (verify — license history has changed) | interop with IfcOpenShell; integration design at M4 | evaluate | proven BIM-in-Blender; community experience | **license must be verified at the gate** (blocking); architecture overlap with our document model | license verification at adoption gate (mandatory); integration review vs document model; TP-CAT-05 conformance plan | — | license "(verify)" is a blocking gate item |
| IfcOpenShell | IFC read/write | bim / interchange | LGPL-3.0-or-later (medium — (verify)) | native library | candidate | de-facto open IFC library | license (verify); large binary; IFC schema breadth | license verification; IFC round-trip conformance (TP-CAT-04/05); version pin policy | — | |
| GDAL | Geospatial raster/vector formats and CRS | toolsets (gis) | MIT/X11-style (medium — (verify)) | native library | candidate | industry-standard geospatial I/O | binary size; license (verify); CRS complexity | license verification; gis toolset requirements defined (TS area); packaging plan | — | |
| PDAL | Point-cloud processing | toolsets (gis) | BSD-style permissive (medium — (verify)) | native library | candidate | point-cloud pipelines | niche; binary size | license verification; toolset requirements defined; packaging plan | — | |
| shapely | 2D planar/geometry operations for civil/gis toolsets | toolsets | BSD-3-Clause (high) | pip dependency | candidate | simple, robust 2D ops | overlaps kernel ops — used only where toolset-specific | toolset requirements defined; version pin | — | |
| Blender (upstream host) | Host application: viewport, UI, file format, Python API | shell (host) | GPL-2.0-or-later per blender.org; GitHub shows NOASSERTION (high, cite blender.org/license) | fork + minimal patch series | candidate (host, pinned) | the platform we extend; mission requires retaining ALL native capabilities | upstream API churn (monthly windows); release-cycle timing | M1 walking skeleton: extension loads in the fork; TP-CAT-06 green; patch-series discipline holds | — | upstream pin at handoff: `bf200615b83252a7be951aed5593d068f0f2438a` |
| ZCode (zai-org/ZCode) | Agent runtime (sidecar) + skill loading conventions | agent | Apache-2.0 (high — verified via GitHub API 2026-10-19) | sidecar process + versioned RPC interface (ADR-0004); pinned fork | candidate | proven agent harness ("Z.ai's coding agent harness.", v3.16.1); skill ecosystem conventions; mission criterion 3 | upstream churn; audit cost; scope of reused packages | M5-entry source audit (ADR-0004 checklist); security review; pin + quarterly audits; TP-CAT-07 conformance | ADR-0004 | fork created as "Gen", renamed `ZCode` (cosmetic; parent verified = zai-org/ZCode); pin at handoff `0a1fc56d279fd1001f78387bd81aec1c26767411`; ZCode UI packages excluded per glossary §6 |
| CAD Sketcher (hlorus/CAD_Sketcher) | Evaluation upstream: SolveSpace-based constraint solver + sketcher patterns (rejected as dependency; seam/workflow patterns adapted at design level) | parametric (study) | addon GPL-3.0-or-later; solver GPLv3-or-later, no linking exception (verified 2026-10-20 from wheel + solvespace@477d4c8 artifacts — high) | none as dependency; design-level adaptation via docs; experiments isolated under experiments/cad-sketcher/ | evaluate | proven Blender-native parametric sketcher; supplied the W1-identical fixture corpus + the bcdoc seam demonstration for the M3 solver decision | rejected as solver dependency on measured grounds (diagnostics, no-incremental, supply chain, aarch64 gap); its PropertyGroup persistence/UI is a second document model (mission boundary) | **rejected as solver dependency (see cad-sketcher-evaluation.md §4.1); no adoption path unless PlaneGCS AND SolidCraft both fail their gates — in which case the blockers in §4.1 must be re-reviewed, not waived** | — | pin: tag v0.32.1 (6a5a340 → e7db7e6, 2026-09-28); solver wheel slvs-3.2 sha256 9ee04ff5… (= solvespace@477d4c8); evidence: experiments/cad-sketcher/results/*.json + decision record cad-sketcher-evaluation.md |

### 4.1 M1 evaluation note — OCCT and OCP rows (2026-10-19, W2)

Distribution-level evidence for the **OCP** row was recorded at M1 in
`docs/00-architecture/kernel-bindings-evaluation-m1.md`: PyPI `cadquery-ocp`
latest 8.0.1.1.0 (uploaded 2026-10-05) ships `cp313` wheels for all five
target platforms — matching the pinned Blender 5.2.2 Python (3.13.13), so
**no version gap exists at the distribution level** — at 45.7–65.0 MB per
platform, license Apache-2.0, `requires_python >=3.11,<3.15`. The binary
weight makes the packaging criterion MORE concrete, not less; the
extension-platform policy on bundled native libraries remains unverified.
**No status change**: OCCT stays `candidate`, OCP stays `evaluate`; the
M3-entry binding decision must still fill in every ADR-0002 criteria row
(performance, packaging, binding stability, coverage).

### 4.3 CAD Sketcher evaluation rows (2026-10-20, TL1 track — m3-eval)

Full decision record: [cad-sketcher-evaluation.md](cad-sketcher-evaluation.md)
(upstream pin `v0.32.1` @ `e7db7e6`; solver = the bundled `slvs-3.2` wheel, byte-identical
to PyPI, source solvespace/solvespace @ `477d4c8`; evidence under
`experiments/cad-sketcher/`). One matrix row is added (above) with status `evaluate`;
the per-candidate dispositions are recorded in the decision record §1/§4 and summarized
here: the add-on as a product component — **REJECT**; the slvs/SolveSpace solver binary
as the in-product PAR-area solver — **REJECT (evidence-backed)** on measured grounds
(diagnostics, no mutation/incremental API, supply chain, aarch64 gap; license
acceptable-but-costly, not the rejection reason); CAD Sketcher as reference material —
**ADAPT (design)** for the solver-agnostic bcdoc seam demonstrated in experiment B,
**REFERENCE** for the specific workflow patterns (decision record §4.3). SolidCraft's
solver-crate disposition is unchanged (TL2's gated record); the identical-fixture
head-to-head — the remaining M3-entry gate named by both records — **ran on the
solver-h2h lane and is decided**: SolidCraft-solver wins every measured dimension
(W1-17 reproduction, the exactly-redundant fixture, ~220x scale, diagnostics);
PlaneGCS is the named fallback + reference, its license (verify) resolved at the
pin, and the m3-eval Eigen@3147391d blocker cleared with at-pin evidence. See
[par-solver-head-to-head.md](par-solver-head-to-head.md). Nothing is adopted; no
release-manifest change; no product dependency exists at any point in the evaluation.

## 5. Honest risk notes (recorded, not hidden)

1. **LibreDWG write-path maturity**: the write path is younger than the read path. DWG write at M4 is explicitly conformance-gated (TP-CAT-04); until that gate passes, DWG is read-only in-product and communications state exactly that.
2. **DWG 3D solids fidelity**: DWG stores ACIS solids as SAT/ASM data; LibreDWG's handling of that representation is a fidelity risk (verify at M3). Therefore **STEP (via OCCT) is the neutral 3D exchange format**; DWG 3D-solids round-trip is a measured-loss item in the loss ledger (ADR-0003), not a silent assumption.
3. **Bonsai license "(verify)"**: license history has changed upstream; verification is a mandatory, blocking item of the adoption gate — no bim-module integration decision is made on an unverified license.
4. **Dynamic blocks**: no open-source implementation exists (LibreDWG included). Parameter/action semantics must be built in-product (ORG area, P2). No parity claim until implemented and tested.
5. **ODA File Converter**: proprietary freeware used offline for fixture generation only (TP-CAT-04 fixtures); it must never appear in shipped artifacts, runtime requirements or product documentation as a dependency.
6. **Native-binary packaging**: OCCT, LibreDWG, IfcOpenShell, GDAL and PDAL all imply native binaries; Blender extension-platform policy on bundled native libraries is unverified (verify at first packaging milestone) and constrains several gates at once.

## 6. Dependency-code mapping (glossary §5 `dep` codes → matrix rows)

The feature inventory's `dep` component codes resolve to rows as follows — this is the single mapping used by `data/inventory/*.yaml` authors (task 1-b1):

| `dep` code | Matrix row(s) | Notes |
|---|---|---|
| `occt` | OCCT | via the chosen binding (ADR-0002) |
| `ocp` | OCP | only if OCP is the chosen binding |
| `freecad` | FreeCAD components | study-only by default |
| `planegcs` | PlaneGCS | 2D constraint solving (PAR area) |
| `build123d` | build123d | only if adopted as scripting layer |
| `cadquery` | CadQuery | only if adopted as scripting layer |
| `ezdxf` | ezdxf | DXF read/write (ADR-0003) |
| `libredwg` | LibreDWG | DWG read (M3) / write (M4) (ADR-0003) |
| `ifcopenshell` | IfcOpenShell | IFC (bim bridge, M4) |
| `bonsai` | Bonsai (BlenderBIM) | BIM workflows (license gate blocking) |
| `gdal` | GDAL | gis toolset |
| `pdal` | PDAL | gis toolset (point cloud) |
| `shapely` | shapely | civil/gis toolsets |
| `blender-native` | Blender (upstream host) | host-provided capability used by an extension feature |
| `zcode-runtime` | ZCode (zai-org/ZCode) | agent runtime (ADR-0004) |

## 7. Milestone gate calendar (planning)

| Milestone | Gates expected to fire | Rows touched |
|---|---|---|
| M1 (walking skeleton) | ezdxf DXF read/write; Blender host (extension loads in fork) | ezdxf, Blender |
| M3 entry (binding decision) | kernel binding evaluation concludes | OCCT, OCP / pythonocc-core / pybind11 (chosen option), PlaneGCS |
| M3 (precision & parametrics) | LibreDWG read conformance | LibreDWG (read only) |
| First packaging milestone | extension-platform policy verification; notice bundling plan | Blender (host row), all native-lib rows (packaging constraints) |
| M4 (interop & toolsets) | LibreDWG write conformance; IFC round-trip; Bonsai integration review | LibreDWG (write), IfcOpenShell, Bonsai |
| gis toolset milestone | license verification + requirements freeze | GDAL, PDAL, shapely |
| M5 (agent integration) | ZCode source audit + security review | ZCode |
| Any new dependency | license-inventory row + verdict **before merge** | (new rows) |

## 8. References

- `docs/GLOSSARY.md` §5 (`dep` component codes), §8 (manifest), §9 (license confidence tags), §11 (milestones).
- `docs/00-architecture/license-inventory.md` — licensing compliance record (ADR-0005).
- `docs/00-architecture/document-model-and-geometry-kernel.md` §5 — kernel binding options and evaluation criteria.
- ADR-0002 (OCCT/PlaneGCS), ADR-0003 (ezdxf/LibreDWG + fixture policy), ADR-0004 (ZCode sidecar + audit).
- Test categories: TP-CAT-02, TP-CAT-04, TP-CAT-05, TP-CAT-07.
