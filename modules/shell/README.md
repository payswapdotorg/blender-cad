# Module: shell

- **Status:** in-progress — M1 status: implemented (bcshell v0) — workspace, session persistence, display sync, modal command operator + scripted headless path, N-panel UI, keymap, .blend save/reopen all verified inside Blender 5.2.2 headless by the driver (both phases PASS)
- **Owner:** W1
- **Date:** 2026-10-19 (UTC); M1 implementation update appended below
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1–M2 (workspace shell at M1; full workspace at M2 — glossary §11)

## Purpose

The CAD application shell: ribbon, palettes, status bar, command-line dock
and layout tabs, integrated into Blender without breaking native Blender
workflows. The module that makes the product look and behave like OUR CAD
application with familiar AutoCAD interaction patterns (glossary §1).

## Owns

- Workspace composition: ribbon tabs/panels, dockable palettes, status bar
- The command-line dock (hosting `commands`' prompt session)
- Layout tabs (hosting `drawings` layouts), workspace profiles/save-state
- Agent/skill surfaces in the workspace (hosting `agent`/`skills` UI hooks)
- The workspace's AutoCAD-familiar interaction conventions (UX area)

## Does NOT own

- Command sequencing and prompt logic (`commands`)
- Entity behaviors (`drafting`) or annotation semantics (`drawings`)
- Toolset content (`toolsets`)
- Native Blender UI regression baselines (owned by `testing`/TP-CAT-06)

## FP areas

- UX — AutoCAD-familiar interface conventions

## Allowed dependencies

- `commands`, `drafting`, `drawings`, `toolsets`, `agent`, `skills`, `document`

## M1 implemented surface (bcshell v0, contract §6 of m1-module-contracts.md)

Package: `modules/shell/bcshell/` — the ONLY package allowed to import bpy
(contract §2). bpy is imported LAZILY: `pick`/`session`/`sync`/`workspace`/
`keymaps` and the package `__init__` import under plain pytest (bpy never
enters the process — asserted by `modules/shell/tests/test_shell_headless.py`);
`ops`/`ui`/`handlers` are the bpy side, validated inside Blender by the driver.

| File | Contents |
|---|---|
| `session.py` | one lazy `bcdoc.Document` per session; persists to the `bpy.data.texts["blender_cad_document.json"]` block after EVERY committed transaction (`on_change`); the registry (bcdraft via `register_all`), command history, feedback ring, prompt/dynamic overlay text; `run_scripted(command_name, inputs)` — the headless path through the SAME `Registry.run_command` machinery (deliberately bpy-free so TP-CAT-01 shell tests run under plain pytest) |
| `workspace.py` | `ensure_workspace()` — "BlenderCAD" workspace + top orthographic view. Blender 5.2 has NO `bpy.data.workspaces.new` (verified: AttributeError); creation uses `bpy.ops.workspace.duplicate()` + rename, which works in `--background` (verified); activation is attempted only when a window exists |
| `sync.py` | one-way document → scene rebuild into collection "BlenderCAD"; line → polyline, circle → cyclic 4-point curve, arc → sampled curve; display objects carry `bcdoc_id`; display deletions never touch the document (verified in-driver). Full-rebuild v0 budget: fine ≤ ~200 entities; incremental sync is M2 |
| `ops.py` | `bcshell.command_run` (modal: holds a `bccmd.StepDriver`; mouse-move → rubberband + dynamic distance/angle; LEFTMOUSE → z=0 point via pick; typed chars accumulate; ENTER → `bccmd.input.parse`; ESC → Cancelled → clean finish). Background-mode fact (verified 5.2.2): `--background` routes INVOKE_DEFAULT to `execute()` and rejects invoke-only operators — so `execute()` drives the scripted path. Also: `bcshell.workspace_open`, `bcshell.cmdline` (token + preset dispatch), `bcshell.dxf_import`/`dxf_export`, `bcshell.doc_save_json`/`doc_load_json`, `bcshell.undo`/`bcshell.redo`, `bcshell.doc_info` |
| `pick.py` | `bpy_extras.view3d_utils` ray ∩ z=0 (`ray_plane_z0`, parallel-safe), dynamic `<distance> <angle>` readout, gpu `POLYLINE_UNIFORM_COLOR` rubberband added POST_PIXEL on start and removed on finish ALWAYS (try/finally) + swept on unregister |
| `ui.py` | N-panel "BlenderCAD" (View3D sidebar, `bl_category="BlenderCAD"`): prompt/dynamic line, document info (name, doc_version, counts, undo/redo depth), buttons for every operator above, feedback echo |
| `keymaps.py` | Ctrl+Space in the extension-owned "BlenderCAD Window" keymap → `bcshell.cmdline`; keymap removed on unregister (degrades to no-op when no addon keyconfig exists headless) |
| `handlers.py` | `load_post` restores the document on .blend reopen; `save_pre` flushes before native save; @persistent; registered/removed as an exact pair |

Verified inside Blender 5.2.2 (headless driver, evidence:
`modules/shell/tests/blender_driver_result.json`): registration surface +
10 operators + panel; workspace creation; scripted LINE/CIRCLE/ARC/MOVE/
COPY/ERASE/UNDO/REDO with exact geometry; cmdline operator dispatch; display
sync + `bcdoc_id` props; display-deletion regeneration; native ops
(coarse `primitive_cube_add`) still work; DXF round-trip inside Blender;
.blend save → FRESH process reopen → document identical (entities +
doc_version); clean unload (operators/keymap/handlers gone; twice-safe).

Honest headless limits (not verified without a GUI): real mouse events,
pixel rendering of the rubberband, the cmdline dialog layout, and keymap
key-press dispatch — no window event loop under `--background`.

Startup restriction (verified): extensions enabled at Blender startup
register under `_RestrictData` (no `bpy.data.texts`); bcshell.register()
therefore stays off bpy.data and the session materializes lazily / via
`load_post`.

## Planned public API sketch — M2+ (not yet implemented)

- `WorkspaceShell` — workspace lifecycle: enter/leave CAD workspace cleanly
- `RibbonModel` — tabs/panels/buttons bound to commands
- `PaletteHost` — dockable palette registration and layout persistence
- `CommandLineDock` — the command-line surface hosting the prompt session
- `StatusBarHost` — toggles/modes/coordinates readout
- `WorkspaceProfiles` — named workspace layouts and save/restore

## Tests

- docs/30-process/test-plan.md: TP-CAT-01 (functional UX sections; shell
  suite under plain pytest) and TP-CAT-06 (native Blender regression —
  clean unload sections; driver inside Blender).
- `modules/shell/tests/test_pure_helpers.py`, `test_shell_headless.py` —
  pure pytest, no Blender: pick ray/readout math, display specs, session
  ring/status, lazy-bpy discipline, `run_scripted` end-to-end.
  Run: `python3 -m pytest modules/shell/tests -q` (add `-k` excludes or
  pass `--ignore` for driver files; the driver is NOT a pytest file).
- `modules/shell/tests/blender_driver.py` — the in-Blender evidence driver
  (TP-CAT-01/06). Run BOTH phases from the repo root:

  ```
  BLENDER=/home/z/runtime/blender-5.2.2-linux-x64/blender
  $BLENDER --background --factory-startup --python modules/shell/tests/blender_driver.py
  $BLENDER --background --factory-startup --python modules/shell/tests/blender_driver.py -- --phase reopen
  ```

  It prints `PASS:`/`FAIL:` lines, merges evidence into
  `modules/shell/tests/blender_driver_result.json` and exits non-zero on
  any failure. Extension packaging is exercised separately via
  `python3 scripts/build_extension.py` (+ `--check`) and the supported
  headless installer
  `blender --command extension install-file -r user_default -e dist/blender_cad-<v>.zip`.
