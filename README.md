# Blender CAD

A complete CAD & engineering application built on Blender — AutoCAD-familiar
drafting UX, a precise geometry kernel (OCCT), DWG/DXF interoperability, BIM,
specialist toolsets, and an integrated agent + skill ecosystem.

> **Status honesty:** M0 — architecture handoff. **No feature code exists yet;
> every feature in the inventory is `planned`.** The only thing green at M0 is
> the repo-consistency CI suite. See
> [docs/30-process/completion-graph-m0.md](docs/30-process/completion-graph-m0.md).

## What this repository is — and is NOT

**Is:** the **canonical source of truth** for Blender CAD — engineering
architecture, feature inventory, API contracts, module packaging, tests and
release manifests. The bulk of the CAD engine, toolsets and agent integration
lives HERE, not in Blender's tree (glossary §2).

**Is NOT:**

- **not** the Blender fork → [`github.com/payswapdotorg/blender`](https://github.com/payswapdotorg/blender)
  (fork of `blender/blender`; host application: build, packaging, minimal patch surface)
- **not** the ZCode fork → [`github.com/payswapdotorg/ZCode`](https://github.com/payswapdotorg/ZCode)
  (fork of `zai-org/ZCode`; tracked upstream dependency for the agent runtime)

## Product requirements (three, equally important)

1. **Engineering feature parity** — drafting, precise geometry, documentation,
   interchange, automation and specialist toolsets per the feature inventory.
2. **AutoCAD-familiar usability** — experienced AutoCAD users work naturally:
   commands, keyboard conventions, palettes, drafting behavior.
3. **Integrated agentic operation** — ZCode-derived agents usable inside the
   CAD app, plus skill authoring/execution/publishing.

## M0 deliverables (11)

| # | Deliverable | Files |
|---|---|---|
| 1 | Repos & upstream pins | `release-manifests/manifest-0.1.0.json`, `patches/README.md`, `docs/00-architecture/repo-and-upstream-sync.md` |
| 2 | Binding glossary & repo map | `docs/GLOSSARY.md` |
| 3 | Document model & geometry kernel architecture | `docs/00-architecture/document-model-and-geometry-kernel.md` |
| 4 | Component adoption matrix & license inventory | `docs/00-architecture/component-adoption-matrix.md`, `license-inventory.md`, `LICENSE-NOTES.md` |
| 5 | ADR series 0001–0006 | `docs/30-process/adr/0001` … `0006` |
| 6 | Feature-parity inventory (14 areas) | `data/inventory/*.yaml`, `docs/10-product/feature-parity-inventory.md`, `docs/10-product/inventory-tables.md` (generated) |
| 7 | File compatibility matrix | `docs/10-product/file-compatibility-matrix.md` |
| 8 | UX specification & usability validation plan | `docs/10-product/ux-specification.md`, `usability-validation-plan.md` |
| 9 | Agent & skills design | `docs/20-agent/*.md` |
| 10 | Process suite: test plan, upstream CI, milestone plan | `docs/30-process/test-plan.md`, `upstream-update-ci.md`, `milestone-plan.md`, `completion-graph-m0.md` |
| 11 | Repo scaffolding & executable CI | `modules/`, `scripts/`, `tests/`, `.github/workflows/`, `requirements-dev.txt` |

## Repository map

| Component | Repository | Upstream pin (2026-10-19) |
|---|---|---|
| Blender fork (host) | `payswapdotorg/blender` | `blender/blender` main @ `bf200615b83252a7be951aed5593d068f0f2438a` |
| ZCode runtime fork | `payswapdotorg/ZCode` | `zai-org/ZCode` main @ `0a1fc56d279fd1001f78387bd81aec1c26767411` |
| CAD extension (**this repo**) | `payswapdotorg/blender-cad` | canonical source of truth |

Pins never silently change: a re-pin requires a release-manifest version bump
(glossary §8), enforced socially via review + CI drift alerts.

## Repository layout

```text
blender-cad/
├── docs/                  # GLOSSARY.md (binding) + 00-architecture/, 10-product/, 20-agent/, 30-process/
├── data/
│   └── inventory/         # 14 YAML files — the feature-parity inventory source of truth
├── modules/               # 13 modules: document, kernel, drafting, parametric, drawings,
│   │                     #   interchange, bim, toolsets, commands, agent, skills, shell, testing
│   ├── modules.json       # module graph: owners, dependencies, fp_areas (machine-checked)
│   └── <module>/README.md # one README per module (PLANNED CONTRACTS, boundaries)
├── patches/               # canonical copies of the Blender-fork patch series (currently EMPTY)
├── release-manifests/    # manifest-*.json — pins, components, dependencies (validated)
├── scripts/               # render_inventory.py, validate_manifest.py,
│                         #   check_module_boundaries.py, check_upstream_drift.py
├── tests/                # test_repo_consistency.py — the M0 acceptance suite (TP-CAT-00)
├── .github/workflows/     # ci.yml, upstream-blender-drift.yml, upstream-zcode-audit.yml
├── requirements-dev.txt   # pyyaml, pytest
└── README.md
```

## Running the checks locally

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests/ -q                 # the repo-consistency suite (what CI runs)
python3 scripts/render_inventory.py --check # generated inventory tables in sync?
python3 scripts/validate_manifest.py        # release manifests valid (glossary §8)?
python3 scripts/check_module_boundaries.py  # module graph valid, no cycles?
python3 scripts/check_upstream_drift.py --component blender  # needs network; GITHUB_TOKEN optional
python3 scripts/check_upstream_drift.py --component zcode
```

## CI

[![M0 repo consistency](https://github.com/payswapdotorg/blender-cad/actions/workflows/ci.yml/badge.svg)](https://github.com/payswapdotorg/blender-cad/actions/workflows/ci.yml)
[![Upstream drift — Blender](https://github.com/payswapdotorg/blender-cad/actions/workflows/upstream-blender-drift.yml/badge.svg)](https://github.com/payswapdotorg/blender-cad/actions/workflows/upstream-blender-drift.yml)
[![Upstream audit — ZCode](https://github.com/payswapdotorg/blender-cad/actions/workflows/upstream-zcode-audit.yml/badge.svg)](https://github.com/payswapdotorg/blender-cad/actions/workflows/upstream-zcode-audit.yml)

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` — repo consistency + unit batteries | push (all branches), pull_request, manual | TP-CAT-00 (`tests/`) **plus all bpy-free module suites** (`pytest modules tests`, 440 tests), byte-compiles scripts+packages, builds and checks the extension package, asserts generated tables in sync, uploads the built zip artifact |
| `patch-apply-check.yml` | weekly cron `0 5 * * 1` + manual | clones the Blender fork's `product/main`, applies the canonical `patches/blender` series (currently empty — asserts product/main == pin); canonical-side decision recorded in upstream-update-ci.md §7 |
| `upstream-blender-drift.yml` | weekly cron `0 6 * * 1` + manual | compares the pinned Blender ref with `blender/blender@main`; on drift opens/comments a deduped `upstream-drift` issue |
| `upstream-zcode-audit.yml` | monthly cron `0 6 2 * *` + manual | same for the pinned ZCode ref vs `zai-org/ZCode@main` |

Details: [docs/30-process/upstream-update-ci.md](docs/30-process/upstream-update-ci.md).

## Status honesty

- **M2 (2026-10-19): drafting core IMPLEMENTED and test-verified** — on top of
  the M1 baseline: the precision-input engine (7 osnap modes, running + one-shot,
  ORTHO, grid snap, direct distance entry, full coordinate grammar — mouse
  input resolves, typed input never does), the full layer/block model
  (properties, states with enforcement, blocks + INSERT + redefinition), the
  annotation engine (associative DIMLINEAR/DIMALIGNED with units-aware
  formatting, TEXT/MTEXT, styles), layouts + viewports (model vs paper space,
  MSPACE/PSPACE), and 20 drafting-core commands (PLINE, POLYGON, ELLIPSE,
  MIRROR, OFFSET, ARRAYRECT, BREAK, JOIN, EXPLODE, STRETCH, MATCHPROP,
  selection modes…). The extension (`dist/blender_cad-0.2.0.zip`) installs
  into **Blender 5.2.2 LTS** through Blender's extension system and all of it
  is exercised there. Evidence:
  `modules/testing/blender/acceptance_m2_result.json` (59/59),
  M1 acceptance re-run 30/30, TP-CAT-06 `result-m2.json` (zero native
  regressions), shell driver 44/44 + 53/53, **1127 pytest tests**.
  See [docs/30-process/completion-graph-m2.md](docs/30-process/completion-graph-m2.md)
  and [ADR-0008](docs/30-process/adr/0008-m2-scope-rebaseline.md) for the
  explicit deferred list (TRIM/EXTEND/FILLET/CHAMFER/PEDIT/HATCH/SPLINE are
  M3 kernel work — deliberately not claimed here).
- **M1 (2026-10-19): walking skeleton IMPLEMENTED and test-verified** — the
  extension builds (`scripts/build_extension.py` → `dist/blender_cad-0.2.0.zip`),
  installs into **Blender 5.2.2 LTS** through Blender's extension system, opens
  the CAD workspace, runs LINE/CIRCLE/ARC and MOVE/COPY/ROTATE/SCALE/ERASE
  through the command interface, persists documents across .blend save/reopen,
  round-trips DXF via ezdxf, and leaves native Blender functions untouched
  (TP-CAT-06 baseline). Evidence:
  `modules/testing/blender/acceptance_m1_result.json` (30/30),
  `modules/testing/blender-regression/result-m1.json`,
  `modules/shell/tests/blender_driver_result.json` (53/53).
  See [docs/30-process/completion-graph-m1.md](docs/30-process/completion-graph-m1.md).
- **Inventory truth:** 561 entries across 17 areas — **55 verified**, **25 partial**
  (explicit notes on what remains), **481 planned**. The remaining M3+ scope —
  the kernel-bound drafting commands, xrefs, DWG write, IFC/BIM, QTO, reality
  capture, the live agent sidecar — is `planned` and none of it is claimed.
- **M0: architecture handoff** (2026-10-19, earlier the same day) — all 11
  deliverables; at that point every feature was `planned`.
- A feature status flips only with a test id + recorded evidence artifact
  (glossary §5). Completion graphs tick only test-passed items.
- Do not count mocks, placeholder panels, dead buttons or agent-generated
  claims as delivered features (glossary §1).

## Trademark disclaimer

*Blender is a registered trademark of the Blender Foundation. AutoCAD,
Autodesk and Procore are trademarks of their respective owners. This project
is an independent work, not affiliated with or endorsed by any of them.*

## License

This repository's code is **GPL-3.0-or-later** (ADR-0005 — compatible with
the GPL-2.0-or-later Blender host via "or later"). The Blender upstream is
GPL-2.0-or-later (verify: blender.org/license; GitHub reports NOASSERTION —
both recorded, glossary §9); the ZCode runtime is Apache-2.0. Third-party
component licenses and confidence tags: see `LICENSE-NOTES.md` and
`docs/00-architecture/license-inventory.md`. Uncertain facts are tagged
`(verify)` and re-verified at the adoption gate.
