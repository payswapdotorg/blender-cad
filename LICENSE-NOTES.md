# LICENSE-NOTES

- **Status:** M0 summary — authoritative detail lives in `docs/00-architecture/license-inventory.md`. The `LICENSE` file at the repo root (added by the TL) is authoritative for code.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## 1. Code licensing

This repository's code is licensed **GPL-3.0-or-later** (SPDX: `GPL-3.0-or-later`), per ADR-0005.

Rationale:

- Blender, the host application, is GPL-2.0-or-later (per blender.org; GitHub reports `NOASSERTION` — both recorded). Code distributed with/inside Blender must be GPL-compatible.
- **"Or later" unification**: distributing the combined work under GPL-3.0-or-later terms admits Apache-2.0 components (Apache-2.0 is compatible with GPL-3.0-or-later, not with GPL-2.0-only).
- GPL-3.0 components (LibreDWG) and the extension license align directly, avoiding dual-licensing gymnastics.

### 1.1 Source-file header

Source files in this repository carry the standard SPDX identifier:

```text
SPDX-License-Identifier: GPL-3.0-or-later
```

## 2. Documentation and fixtures

Text documentation, schemas and test fixtures in this repository are documentation, not code. For simplicity they carry the same GPL-3.0-or-later header notice; this choice is revisited before any external reuse (e.g. publishing documentation under a Creative Commons license). No external-reuse commitments are made at M0.

## 3. Third-party components

Third-party components are **not** relicensed by this repository. Their license and notice obligations are recorded and preserved per `docs/00-architecture/license-inventory.md` (the compliance record, ADR-0005). In short:

- **Apache-2.0** (ZCode runtime, OCP, build123d, CadQuery): upstream `NOTICE` and third-party notices preserved; modifications stated per Apache-2.0 §4(d).
- **MIT / BSD** (ezdxf, shapely, pybind11, GDAL/PDAL pending verification): copyright and permission notices retained.
- **LGPL family** (OCCT with exception, FreeCAD components, IfcOpenShell, PlaneGCS pending verification): retained as libraries with their own license texts and boundaries.
- **GPL-3.0** (LibreDWG): license text shipped and source availability obligations honored for distributed binaries.
- **ODA File Converter**: proprietary dev-fixture tooling only — never distributed with the product.

## 4. Trademark disclaimer (verbatim, glossary §3)

> Blender is a registered trademark of the Blender Foundation. AutoCAD, Autodesk and Procore are trademarks of their respective owners. This project is an independent work, not affiliated with or endorsed by any of them.

This disclaimer is used verbatim wherever licensing or naming is discussed (see ADR-0001).

## 5. Fork repositories

| Repository | License | Notes |
|---|---|---|
| `https://github.com/payswapdotorg/blender` | GPL-2.0-or-later (per blender.org; GitHub shows `NOASSERTION`) | Blender fork; upstream pin at handoff `bf200615b83252a7be951aed5593d068f0f2438a`; patch policy in `docs/00-architecture/repo-and-upstream-sync.md` |
| `https://github.com/payswapdotorg/ZCode` | Apache-2.0 | ZCode runtime fork (created as "Gen", renamed `ZCode` — cosmetic; parent verified `zai-org/ZCode`); upstream pin at handoff `0a1fc56d279fd1001f78387bd81aec1c26767411`; audit policy in ADR-0004 |

## 6. Where notices live

- Per-component license and notice details: `docs/00-architecture/license-inventory.md` (the compliance record, ADR-0005).
- Vendored third-party code, when it first appears, keeps its upstream `LICENSE`/`NOTICE` files in place beside the vendored source; the inventory row records the location.
- Release notices (the bundled third-party listing shown to users) are generated from the release manifest's `dependencies[]` at packaging milestones (planned; owner: TL).

Related records: full license inventory + verdicts — `docs/00-architecture/license-inventory.md`; adoption status + gates — `docs/00-architecture/component-adoption-matrix.md`; naming — ADR-0001; extension licensing decision — ADR-0005.
