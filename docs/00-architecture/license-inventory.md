# License inventory

- **Status:** M0 compliance record. All verdicts below are planning verdicts; every adoption re-checks its row. Nothing is adopted at M0.
- **Owner:** TL (Technical Lead)
- **Date:** 2026-10-19
- **Vocabulary:** docs/GLOSSARY.md (binding)

## 1. Purpose and policy

This document is the **compliance record** for ADR-0005: every third-party component the product plans to touch has a row with a license, a source of truth, a compatibility verdict against (a) the extension's GPL-3.0-or-later and (b) the host Blender's GPL-2.0-or-later, plus notice obligations and verification status.

**Merge-gate policy (binding):** any new dependency — including transitive runtime dependencies of adopted components — requires a license-inventory row **and** a compatibility verdict **before merge**. This is a merge-gate checklist item in PR review; a PR adding an unlisted dependency cannot be merged. Uncertain facts carry `(verify)` and are routed through the adoption gate (glossary §9).

Merge-gate checklist (each item must hold before a dependency-bearing PR merges):

1. Dependency named, with version/pin recorded in the PR description.
2. A license-inventory row exists: license, source of truth, verdicts, obligations, verified date.
3. A glossary §9 confidence tag is assigned; `(verify)` is allowed only with a gate that will resolve it before shipping.
4. Compatibility verdicts are written for both the extension (GPL-3.0-or-later) and the host (GPL-2.0-or-later) contexts.
5. The release manifest gains its `dependencies[]` entry when adoption happens (not before).
6. The component-adoption-matrix row carries the gate criteria this dependency must pass.

Verdict vocabulary used in the table:

| Verdict term | Meaning |
|---|---|
| `compatible` | usable and distributable under the stated GPL context as licensed today |
| `compatible (… path)` | compatible via the named distribution path (e.g. "or later" combined distribution) |
| `pending verification` | expected compatible; the row stays candidate until its source is checked at the gate |
| `not applicable` | component never distributed with the product (fixture-only tooling) |
| `— (host)` | the row is the host itself; the vs-host column does not apply |

Scope of the inventory:

- **In scope**: runtime Python dependencies, vendored source, bundled native libraries, sidecar-bundled code (ZCode-derived), and dev tools that touch the product's supply chain (the ODA File Converter row exists for traceability even though it never ships).
- **Out of scope**: the Python standard library; Blender's own bundled dependencies (host territory, covered by the host row); operating-system packages (documented at packaging milestones if the product requires specific system libraries).

Conditional rows (pybind11, pythonocc-core) exist because ADR-0002's binding decision has not been made; when the decision records an option as not-taken, that option's row is removed.

## 2. Inventory

| Component | License | Source of truth | Verdict vs extension (GPL-3.0-or-later) | Verdict vs host (Blender, GPL-2.0-or-later) | Notice / attribution obligations | Verified | Adoption-gate recheck |
|---|---|---|---|---|---|---|---|
| Open CASCADE (OCCT) | LGPL-2.1 with exception | OCCT repository license files | compatible (library use) | compatible (LGPL-2.1 works with GPL-2+) | retain LGPL-2.1 text + exception notice; keep library boundary | high — 2026-10-19 | recheck at M3-entry binding decision |
| OCP (CadQuery's OCCT bindings) | Apache-2.0 | OCP repository LICENSE/NOTICE | compatible (GPL-3.0-or-later path) | NOT compatible with GPL-2.0-**only**; fine via "or later" combined distribution | retain LICENSE + NOTICE; state changes if modified | high — 2026-10-19 | recheck with binding decision |
| FreeCAD components | LGPL-2.1+ (per-module exceptions) | per-module license files | compatible (library / studied-source use) | compatible | per-module notices if code is copied; attribution in docs | high — 2026-10-19 | per-copy review at adoption gate |
| PlaneGCS | LGPL (used by FreeCAD) | PlaneGCS upstream license file | compatible (library use) — pending verification | compatible — pending verification | retain license text; library boundary | medium — **(verify)** at gate | blocking: verify before vendoring |
| build123d | Apache-2.0 | repository LICENSE | compatible | compatible via GPL-3.0-or-later path | retain LICENSE + NOTICE; state changes | high — 2026-10-19 | recheck if adopted |
| CadQuery | Apache-2.0 | repository LICENSE | compatible | compatible via "or later" path | retain LICENSE + NOTICE; state changes | high — 2026-10-19 | recheck if adopted |
| ezdxf | MIT | repository LICENSE | compatible | compatible | retain copyright + permission notice | high — 2026-10-19 | recheck at M1 adoption |
| LibreDWG | GPL-3.0 | repository LICENSE | **compatible directly** (GPL-3.0-or-later) | combined work distributes under GPL-3.0-or-later terms ("or later" of the host) | ship license text; source availability for shipped binaries | high — 2026-10-19 | recheck at M3 (read) and M4 (write) gates |
| ODA File Converter | proprietary freeware **(verify)** | vendor terms | **not applicable — never distributed with the product**; dev-fixture tooling only | same — never shipped | no product obligations; usage documented in testing module | unverified — must remain fixture-only | hard rule: never bundled/linked/shipped |
| SolveSpace | GPL-3.0 **(verify)** | repository LICENSE | compatible if ever adopted (evaluate-only today) | same | license text if shipped | unverified — evaluate-only, no shipping planned | verify only if evaluation escalates |
| Bonsai (BlenderBIM) | **(verify — license history has changed)** | upstream repository | **pending — row stays candidate until verified** | pending | to be determined at verification | must verify at adoption gate | **blocking** at bim integration gate |
| IfcOpenShell | LGPL-3.0-or-later | repository license | compatible (library use) — pending verification | compatible via "or later" | retain LGPL-3.0-or-later text; library boundary | medium — **(verify)** at gate | recheck at M4 bim bridge |
| GDAL | MIT/X11-style (MIT-style permissive) | repository LICENSE | compatible — pending verification | compatible — pending verification | retain license + notice | medium — **(verify)** at gate | recheck at gis toolset gate |
| PDAL | BSD-style permissive | repository LICENSE | compatible — pending verification | compatible — pending verification | retain notice; BSD non-endorsement clause | medium — **(verify)** at gate | recheck at gis toolset gate |
| shapely | BSD-3-Clause | repository LICENSE | compatible | compatible | retain notice; no endorsement of derived works | high — 2026-10-19 | recheck if adopted |
| pybind11 *(conditional — only if in-tree binding chosen, ADR-0002)* | MIT | repository LICENSE | compatible | compatible | retain copyright + permission notice | high — 2026-10-19 | add row permanently if chosen at M3 |
| pythonocc-core *(conditional binding option, ADR-0002)* | LGPL **(verify)** | repository license | compatible pending verification | compatible pending verification | retain license text; library boundary | unverified | verify if chosen at M3 |
| Blender (host) | GPL-2.0-or-later per blender.org; GitHub shows `NOASSERTION` | blender.org/license (record both) | extension (GPL-3.0-or-later) is distributable with the host via the host's "or later" | — (is the host) | preserve upstream license headers in the fork; no additional restrictions | high — 2026-10-19, cite blender.org | recheck at first packaging milestone |
| ZCode (zai-org/ZCode) | Apache-2.0 | repository LICENSE + NOTICE; GitHub API (verified 2026-10-19) | compatible (GPL-3.0-or-later path) | compatible via "or later" path | **preserve NOTICE and THIRD-PARTY-NOTICES from upstream; state changes (Apache-2.0 §4(d))** | high — verified via GitHub API 2026-10-19 | recheck at M5-entry audit (ADR-0004) |

Rows are keyed by component; where a component appears in multiple roles (OCCT as kernel, OCP as binding) the row records the single governing verdict. Fork-specific provenance (payswapdotorg/ZCode created-as-"Gen"-then-renamed) is recorded in `repo-and-upstream-sync.md` §2.1 and ADR-0004, not duplicated per row.

## 3. Blender GPL nuance

Blender is GPL-2.0-or-later **per blender.org**; the GitHub repository reports `NOASSERTION` — both facts are recorded and the blender.org page is the cited source of truth. Blender extension distribution requires GPL-compatible licensing; the current **extension-platform policy must be verified at the first packaging milestone** (verify), because platform rules (e.g. on bundled native libraries, binary size, metadata licensing fields) constrain both ADR-0002's binding choice and this inventory's shipping obligations. If verification surfaces stricter requirements, ADR-0005 and this document are amended through review — never improvised at packaging time. Fork-side obligation: the Blender fork preserves upstream license headers, and its patches add no additional restrictions beyond GPL terms (repo-and-upstream-sync.md §5).

## 4. ZCode (Apache-2.0) obligations

The ZCode runtime (pinned `0a1fc56d279fd1001f78387bd81aec1c26767411`, upstream v3.16.1) and any adaptation shipping in the sidecar must: (a) preserve upstream `NOTICE` and third-party notice files verbatim where applicable; (b) carry a prominent statement that files were modified (Apache-2.0 §4(d)); (c) retain the Apache-2.0 license text; (d) list ZCode in the product's third-party notices. The sidecar interface-first design (ADR-0004) keeps ZCode-derived code process-separated, which simplifies notice scoping but does not remove the obligations.

## 5. Recheck schedule (milestone → rows re-verified)

| Milestone / trigger | Rows re-verified | Output |
|---|---|---|
| M1 — DXF adoption | ezdxf | refreshed row + manifest `dependencies[]` entry |
| M3 entry — kernel binding decision | OCCT; chosen binding row (OCP or pythonocc-core or pybind11); PlaneGCS | refreshed rows; conditional rows resolved or removed |
| M3 — DWG read gate | LibreDWG (read path) | refreshed row + read-gate evidence |
| First packaging milestone | Blender (host row); extension-platform policy (verify) | ADR-0005 amendment if policy differs; notice-bundling plan |
| M4 — DWG write / IFC / BIM | LibreDWG (write), IfcOpenShell, Bonsai | refreshed rows; **Bonsai verdict mandatory** before bim integration |
| gis toolset milestone | GDAL, PDAL, shapely | refreshed rows |
| M5 — agent integration | ZCode (NOTICE + third-party notices preserved) | refreshed row + audit record (ADR-0004) |
| Quarterly + before any ZCode pin change | ZCode | audit record per repo-and-upstream-sync.md §6.1 |
| Any Blender pin change (monthly update windows) | Blender (host row) | new release manifest; host row refreshed in the same reviewed change (pin change = version bump, glossary §8) |
| Any new dependency, any time | new row | row + verdict **before merge** (merge gate, §1) |

## 6. License-family obligations summary

| Family | Components | Obligations when shipped |
|---|---|---|
| MIT / BSD / MIT-style | ezdxf, shapely, pybind11, GDAL (verify), PDAL (verify) | retain copyright + permission notices; BSD non-endorsement clauses |
| Apache-2.0 | ZCode, OCP, build123d, CadQuery | retain LICENSE + NOTICE; state changes (§4(d)) |
| LGPL (2.1 / 3.0) | OCCT (with exception), FreeCAD components, PlaneGCS (verify), IfcOpenShell (verify), pythonocc (verify) | retain license texts; keep library boundaries; LGPL-3.0-or-later permits GPL-3.0+ combined distribution |
| GPL-3.0 | LibreDWG, SolveSpace (verify) | ship license; source availability for distributed binaries; compatible with GPL-3.0-or-later |
| Proprietary freeware | ODA File Converter | never shipped — dev fixtures only; no product obligation |

## 7. Verification logging protocol

Every verification recorded in the "Verified" column follows this format:

`<ISO date> · <source checked: URL or file path> · <method: license file read / GitHub API / blender.org> · <recorder> · <resulting confidence tag>`

Examples: `2026-10-19 · zai-org/ZCode license via GitHub API · TL · Apache-2.0 (high)`; `2026-10-19 · blender.org/license · TL · GPL-2.0-or-later (high; GitHub NOASSERTION recorded)`.

A verification is only valid for the pinned version it was performed against; upstream version changes invalidate it and trigger the recheck schedule (§5). Verifications are recorded by the TL or a delegated gate owner, never asserted without a checkable source.

## 8. Verdict summary

- Everything currently listed is **compatible or verifiable**: permissive licenses and the LGPL family are compatible with the GPL-3.0-or-later extension; LibreDWG's GPL-3.0 aligns directly; the host's "or later" clause admits Apache-2.0 and GPL-3.0 components into combined distribution.
- Reasoning chain recorded for reviewers: extension (GPL-3.0-or-later) + host (GPL-2.0-or-later via "or later") → combined distribution under GPL-3.0-or-later terms; Apache-2.0 (ZCode, OCP) enters through that GPL-3.0+ path; LGPL components remain bounded libraries; LibreDWG's GPL-3.0 matches the extension directly. Verdicts are per pinned version — upstream upgrades re-verify (§5, §7).
- The single hard incompatibility risk — Apache-2.0 components vs a GPL-2.0-only product — is eliminated by ADR-0005's "or later" choice.
- Anything unresolved (Bonsai license, PlaneGCS/GDAL/PDAL/IfcOpenShell/SolveSpace/pythonocc verifications, extension-platform policy) **stays `candidate` until its row is verified**; no unverified component ships.
- Trademark disclaimer (applies wherever licensing/naming is discussed, glossary §3): *Blender is a registered trademark of the Blender Foundation. AutoCAD, Autodesk and Procore are trademarks of their respective owners. This project is an independent work, not affiliated with or endorsed by any of them.*

## 9. References

- ADR-0005 (extension licensing), ADR-0002 (kernel bindings), ADR-0003 (fixture policy), ADR-0004 (ZCode audit).
- `docs/00-architecture/component-adoption-matrix.md` — adoption status, gates, milestone calendar.
- `LICENSE-NOTES.md` (repo root) — repo licensing summary; `docs/GLOSSARY.md` §9 — confidence tags and verification rule.
- `docs/00-architecture/repo-and-upstream-sync.md` §6.1 — ZCode audit procedure that feeds row re-verification.
