# CAD Sketcher upstream audit — M3-eval phase 1

- **Status:** evaluation record. No component adopted; nothing here is product code.
- **Owner:** E1 (m3-eval phase 1); TL owns the product decision
- **Date:** 2026-10-20 (UTC)
- **Pin (binding):** `hlorus/CAD_Sketcher` release tag `v0.32.1` — annotated tag object
  `6a5a34001efcdec05381b6f419cc4d0394a24ab5`, commit
  `e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4`, 2026-09-28 13:07:37 +0200,
  subject "Changelog for 0.32.1 (#759)", tagged by David Friedli <david@friedli-be.ch>.
  All file/line references below were read from `fetch-upstream.sh`'s checkout of
  exactly this commit (`.upstream/CAD_Sketcher`, gitignored, never committed).

## 1. Release facts (verified at the pin)

| Fact | Value | Evidence |
|---|---|---|
| Latest versioned release tag | `v0.32.1` (2026-09-28), tag object `6a5a340…` → commit `e7db7e6…` | `git tag -l`; `git cat-file -p v0.32.1` |
| Moving tag `latest` | points at main HEAD `efd255190f17e953786f29f22023d1a928a6a42e` ("Merge pull request #796 from jlitewski/perf/solver-and-draw") | `git show latest --no-patch --format='%H %D'` |
| Manifest version at tag | `version = "0.32.1"` (HEAD already carries dev `0.32.2`) | `blender_manifest.toml:4` at the pin |
| Prior tags | v0.31.1, v0.32.0 (…); `v0.32.1` is the newest `v*` tag | `git tag -l` |
| CHANGELOG v0.32.1 | two fixes: (1) "Adding a coincident or midpoint constraint no longer crashes Blender", (2) "Constraint labels and icons draw in the viewport you are working in, instead of in a single view of a quad view" | `CHANGELOG.md` §0.32.1 |
| CHANGELOG v0.32.0 (summary) | major release: **parts and assemblies** (part = geometry a sketch makes + its sketches/workplanes; groups, instances, outliner), sketch result is a **real mesh object** (modifiers/export/mesh tools), per-part XY/XZ/YZ workplanes, revolve around part axes, endpoint-arc tool, center/3-point rectangles, chained drawing across tools, auto-constraints while drawing (tangent/perpendicular/parallel at joints), re-pickable constraint entities, curve-resolution prefs, **Exact vs Manifold boolean solver choice**, circular/linear arrays (mesh-edge or sketch-line axes), change-sketch-workplane, opt-out of auto-boolean on extrude, Alt+D linked copy, drag-to-draw; perf: "much faster hovering, dragging and drawing in large sketches", "under-constrained sketches no longer drift slightly on every solve" | `CHANGELOG.md` §0.32.0 |

### 1.1 Why v0.32.1 is the pin

`latest` is a moving tag on main (rebuilt every push); main's manifest is the dev
version `0.32.2` (unreleased). v0.32.1 is the newest **versioned release** — the
newest thing a user can install from the stable channel — and it is what the
GitHub release + extensions.blender.org pipeline published. Phase 2+ experiments
stay on this pin unless TL re-pins.

## 2. blender_manifest.toml (at the pin, verbatim facts)

```toml
schema_version = "1.0.0"
id = "CAD_Sketcher"
version = "0.32.1"
name = "CAD Sketcher"
tagline = "Parametric, constraint-based geometry sketcher"
maintainer = "hlorus <dave19924@gmail.com>"
type = "add-on"
website = "https://www.cadsketcher.com/"
tags = ["3D View", "Modeling", "Mesh", "Object"]
blender_version_min = "5.0.0"
license = ["SPDX:GPL-3.0-or-later"]
platforms = ["windows-x64", "macos-x64", "macos-arm64", "linux-x64"]
```

- `wheels = [...]` — 10 wheels, all `./wheels/slvs-3.2-*`: cp311 × {macosx_10_12_x86_64,
  macosx_11_0_arm64, manylinux_2_17_x86_64, musllinux_1_2_x86_64, win_amd64} and the
  same five for cp313 (macosx_10_13 for cp313 x86_64). **No cp312 wheel is shipped**;
  the doc statement below about "3.11, 3.12 and 3.13" refers to PyPI availability
  for source installs, not the bundled set — the bundled set exactly matches the
  Python versions embedded in official Blender builds (3.11 ≤ 5.1, 3.13 ≥ 5.2).
- `[build] paths_exclude_pattern` excludes dev/docs/test cruft
  (`/testing/`, `/docs/`, `/scripts/`, `/experiments/`, `/notes/`, …) — the
  release ZIP ships only the runtime add-on.
- Doc statement (for reference): `docs/content/installation.md:51` — "CAD Sketcher
  heavily depends on the [solvespace python module](https://pypi.org/project/slvs/)
  and won't be functional without it. When installed as an Extension the module
  ships bundled as a wheel…"; `:53` — wheels for Python "3.11, 3.12 and 3.13 …
  the versions embedded in official blender.org builds (3.11 up to Blender 5.1,
  3.13 from 5.2)"; recommends Blender 5.2 LTS; `docs/content/code_docs.md:9+`
  describes the addon's own data model (entity PropertyGroups, `slvs_index`).

## 3. Release pipeline (`.github/workflows/release.yaml`, 440 lines, at the pin)

1. `lint` job: `ruff check --select F` over the whole tree (gate for undefined names —
   comment cites a 0.31.0-rc.1 escape that "reached the extensions.blender.org reviewer").
2. `release` job (on `tags: ["v*"]`):
   - tag-vs-manifest version check, incl. legacy `bl_info` agreement;
   - **validate**: `blender --background --command extension validate` (Blender 5.0 via `moguri/setup-blender@v1`);
   - **build**: `blender --background --command extension build --split-platforms --output-dir dist`
     → `dist/CAD_Sketcher-<version>-<platform>.zip`, one ZIP per declared platform;
   - CHANGELOG notes prepended (missing entry = warning, not error);
   - publish via `softprops/action-gh-release@v2` with `files: dist/*.zip`.
   - **Wheels are NOT built or downloaded by the workflow** — the only wheel
     mentions are comments (`release.yaml:87,167`); the wheels are committed
     in-repo (`wheels/`, ~14.6 MB) and Blender's `extension build` bundles the
     platform-matching wheel(s) into each split ZIP. We verified all 10 committed
     wheels are byte-identical (sha256) to the PyPI `slvs` 3.2 files of the same
     names — the addon simply re-distributes the PyPI release (§5 of
     license-supply-chain.md).
3. `submit-blender` job: builds again `--split-platforms`, POSTs each ZIP to
   `extensions.blender.org/api/v1/extensions/<slug>/versions/upload/`
   (human moderator approval; release notes capped at 1024 chars, trimmed to 850+link).
4. `publish-stable` job: rebuilds `stable/index.json` over the last 200 non-prerelease
   GitHub releases via `blender --command extension server-generate --repo-dir zips`,
   rewrites `archive_url`s at the release assets, pushes to
   `hlorus/CAD_Sketcher-extensions` (self-hosted stable channel).
5. `bump-version` job: after a final tag, bumps manifest (and legacy `bl_info`) on
   main to the next patch (0.32.2 in our case — what main HEAD shows).

Observed stable-channel artifact names (release `v0.32.1`, HTML asset listing):
`CAD_Sketcher-0.32.1-{linux_x64,macos_x64,macos_arm64,windows_x64}.zip`.
The `linux_x64` ZIP (13,968,966 bytes, sha256
`c679cccd8ae955c440787e6be4a8eaebfb77cb1909eb8de04ffc182e97774541`) contains
272 entries incl. `blender_manifest.toml`, `LICENSE`, and **four** linux wheels
(cp311+cp313 × manylinux+musllinux — one "linux-x64" package serves both libcs).

## 4. Addon license & source-header survey (at the pin)

- `LICENSE` = the full GNU GPL v3 text (674 lines; FSF URL variant
  `https://fsf.org`), **no "version 3 only"/"or later" wording of its own**; the
  "or later" comes from `blender_manifest.toml` `license = ["SPDX:GPL-3.0-or-later"]`.
- **No SPDX/copyright headers exist anywhere in the addon's Python sources** —
  `git grep -iE "copyright|SPDX|code from|taken from|borrowed" -- '*.py'` finds exactly
  one provenance header: `units.py:1` (see below). Sampled: `registration.py`,
  `curve_solver.py:1-5` (docstring "Solver that reads/writes native curve data
  directly."), `serialize.py`, `model/coincident.py`, `base/__init__.py` — all
  header-less.
- **One vendored third-party file family**: `units.py:1-2` —
  `# Code from MeasureIt_ARCH, see:` /
  `# https://github.com/kevancress/MeasureIt_ARCH/blob/development/measureit_arch_units.py`.
  The whole 179-line module (unit formatting: imperial precision enums, length
  formatting) is copied from MeasureIt_ARCH `measureit_arch_units.py`. The
  upstream file carries `##### BEGIN GPL LICENSE BLOCK #####` (GPL **v2 or later**
  per its block); MeasureIt_ARCH's repo LICENSE states "Copyright (C) 2020 Kevan
  Cress, Antonio Vazquez … GNU General Public License … version 3 … or later".
  The copy in CAD_Sketcher **drops the GPL license block**, keeping only the URL
  comment — a notice/attribution gap (GPL-2.0+ content is GPL-3.0-or-later
  compatible, so it is a compliance nit upstream, not a blocker for studying it).
- `stateful_operator/` (stateful-operator framework, 3,210 LOC + `docs.md`) and
  `gizmos/` (viewport gizmos, 1,589 LOC) contain **no foreign copyright headers**
  and no copied-code markers — nothing in-tree indicates external provenance;
  nothing contradicts the project's own GPL statement.
- `exposed/`-style leftovers: none. No bundled `.so`/`.dylib`/`.dll` besides the
  slvs wheels.

## 5. Addon structure map (pin `e7db7e6`; 356 Python files, 483 tracked files)

| Unit | Role (with evidence) |
|---|---|
| `__init__.py` | entry point; **no legacy `bl_info`** — "blender_manifest.toml is the source of truth for name/version" (`__init__.py:4-6`) |
| `registration.py` + `utilities/register.py` | module registry ("base", "handlers", "model", … `registration.py:3-20`) |
| `base/` | preferences (`preferences.py`), theme, "what's new" dialog |
| `model/` (39 files, 7,623 LOC) | the **document-like layer**: entity classes (`SlvsPoint2D`, `SlvsLine2D`, `SlvsArc`, `SlvsCircle`, `SlvsWorkplane`, `SlvsNormal2D/3D`, 3D variants; `categories.py`), constraint classes (one file per kind: `coincident.py`, `horizontal.py`, `vertical.py`, `parallel.py`, `perpendicular.py`, `tangent.py`, `equal.py`, `midpoint.py`, `symmetry.py`, `ratio.py`, `distance.py`, `diameter.py`, `angle.py`; base in `base_constraint.py`), collections (`group_entities.py` `SlvsEntities`, `group_constraints.py` `SlvsConstraints`, `group_sketcher.py`), and the **new native-curve sketch model** (`sketch_ref.py`, `curve_ref.py` ~1,000 LOC). `model/sketch.py:26` stores per-sketch `dof: IntProperty(name="Degrees of Freedom", max=6)`; `model/base_constraint.py:114` `failed: BoolProperty(name="Failed")` |
| `curve_solver.py` (757 LOC) | **the slvs integration seam (current)**: `CurveSolver` — "Solver that operates on native curve data" (`:57`); `import slvs` lazily at `:67`; builds the workplane exactly as a sketch's empty (`_init_workplane()`, `:90-138`: `add_point_3d` origin + `add_normal_3d` quaternion + `add_workplane` in `group_fixed=1`); builds entities from curve attributes (`_init_geometry()`, `:140-246`: points→lines→arcs/circles passes, bulk UUID reads for perf, issue #342); constraints create themselves via `create_slvs_data_from_curves(solvesys, handle_map, wp, group)` (`model/coincident.py:37-53`); `_write_results()` (`:494`) writes solved positions back comparing at float32 storage precision; failed constraints are marked `c.failed = True` for the UI (`:329-361`, issue #674); `solve_sketch_from_curves` / `solve_system` module functions (`:735-757`) |
| `utilities/solver.py` | needs-solve marking callbacks (deferred to `depsgraph_update_post`) |
| `operators/` (60 files, 11,733 LOC) | all UI operators: `add_point_2d.py` … `add_sketch.py`, `add_geometric_constraints.py`, `delete_*`, `solve.py` (`View3D_OT_slvs_solve` → `curve_solver.solve_system`, "sketches are marked with solvestate" `solve.py:24`), `tweak*.py`, `offset.py`, `trim.py`, part/assembly ops, `solver_state.py`; idnames in `declarations.py` (`view3d.slvs_add_point2d`, `view3d.slvs_add_sketch`, …) |
| `stateful_operator/` (3,210 LOC) | reusable state-machine operator framework (`state_machine.py`, `logic.py`, `state.py`, `docs.md` documents the method contract) |
| `serialize.py` (146 LOC) | **its own persistence**: `scene_to_dict`/`scene_from_dict`/`update_scene_from_dict` snapshotting `SKETCHER_SNAPSHOT_PROPS = ["entities", "constraints"]` PropertyGroups (`serialize.py:29`) — a test/persistence-level serialization, separate from .blend storage |
| draw units | `draw_handler.py`, `drawing/` (8 modules: overlay, picking, snap, render_data, frame_cache, constraint_icons, selection, reference_pick), `gizmos/` (10 modules), `shaders.py` |
| `wheels/` | the 10 committed slvs wheels (§ license doc) |
| `testing/` | `live_harness.py`, `gui_smoke.py`, `test_*.py` + fixtures (excluded from the release build) |
| `docs/` | user + code docs (excluded from the release build) |

### 5.1 Dual data-model observation (M3-relevant)

v0.32.x is mid-migration: the older **Solvespace-style entity layer**
(`SlvsEntities`/`SlvsConstraints` PropertyGroups, still persisted per-scene and
serialized by `serialize.py`) now coexists with a **native-curve sketch model**
(sketched geometry lives in a mesh's curve attributes; the solver reads/writes
those attributes directly). `docs/content/code_docs.md:12-16` states the entity
layer "is still" used for pointer matching (`SlvsPoint2D`…`types=(SlvsPoint2D,)`
matching in state pointers). Any M3 decision about "what a sketch document looks
like" must engage with the fact that upstream itself moved away from a
standalone entity collection toward host-native geometry + constraint overlay.

### 5.2 Constraint inventory vs our PAR-area list (first cut; deep comparison is experiment A)

Our list (document-model-and-geometry-kernel.md §3.8): geometric — coincident,
parallel, perpendicular, tangent, horizontal, vertical, concentric, equal,
symmetric; dimensional — distance, angle, radius.

| Ours | CAD_Sketcher v0.32.1 | Notes |
|---|---|---|
| coincident | ✅ `model/coincident.py` (`SlvsCoincident`) | point/point, point/line, point/circle, point/workplane signatures (`coincident.py:30-31`) |
| parallel / perpendicular | ✅ `parallel.py` / `perpendicular.py` | |
| tangent | ✅ `tangent.py` | |
| horizontal / vertical | ✅ `horizontal.py` / `vertical.py` | |
| equal | ✅ `equal.py` (lengths/radii) | SolveSpace `EQUAL_LENGTH_LINES`/`EQUAL_RADIUS` |
| symmetric | ✅ `symmetry.py` | |
| concentric | ⚠️ no dedicated constraint | composed as coincident centers (+ equal radius) — SolveSpace has no primitive "concentric" |
| distance | ✅ `distance.py` (`SlvsDistance`; point/point, point/line variants; aligned-distance handling `distance.py:45`) | |
| angle | ✅ `angle.py` | |
| radius | ✅ via `diameter.py` (`SlvsDiameter`) | radius = diameter/2 preset; no separate radius kind |
| — (beyond our list) | `midpoint.py`, `ratio.py`, 3D constraints (`model/native_3d.py`, point/line 3D entities) | beyond-PAR capabilities to scope in experiment A |

Diagnostics surface (for experiment A): SolveSpace result flags exposed by the
binding — `OKAY, INCONSISTENT, DIDNT_CONVERGE, TOO_MANY_UNKNOWNS, REDUNDANT_OKAY`
(`slvs/solvespace.pyi` `ResultFlag`), DOF returned by `solve_sketch`, per-constraint
`failed` marking, per-sketch `dof` property.

## 6. Startup hygiene observation (from the phase-1 runtime runs)

Enabling the extension on Blender 5.2.2 emits one Python `SyntaxWarning` from the
addon: `utilities/bpy.py:65: SyntaxWarning: invalid escape sequence '\['`
(`match = re.match("(.*)\[\d*\]", path)`) — cosmetic, but it is a startup-visible
code-hygiene fact (results/runtime-compat.json records it verbatim).

## 7. Reproduction

```bash
./experiments/cad-sketcher/fetch-upstream.sh     # pinned tag -> .upstream/CAD_Sketcher
python3 experiments/cad-sketcher/scripts/gen_upstream_audit.py   # -> results/upstream-audit.json
```

Every claim above was read from the pinned checkout; the generator re-verifies the
tag/commit SHAs, manifest fields, wheel inventory (sha256 vs PyPI), and the
no-foreign-headers grep, and fails loudly if any pinned fact drifted.
