# Module: drafting

- **Status:** in-progress — M1 status: implemented (bcdraft v0) — LINE/CIRCLE/ARC/ERASE/MOVE/COPY/ROTATE/SCALE/UNDO/REDO command set + analytic transforms, all green under plain pytest (real bcdoc) and exercised end-to-end inside Blender by the shell driver
- **Owner:** W1 (UX side) / W2 (geometry side) — glossary §10
- **Date:** 2026-10-19 (UTC); M1 implementation update appended below
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

## M1 implemented surface (bcdraft v0, contract §5 of m1-module-contracts.md)

Package: `modules/drafting/bcdraft/` — pure Python, NO bpy (enforced by
`modules/drafting/tests/test_no_bpy.py`).

Every command is a `bccmd.CommandSpec` (a steps-generator driven by the
SAME `bccmd` state machine the modal operator and scripted tests use) and is
registered through `bcdraft.register_all(registry)`:

| Command | Aliases | Behavior (asserted in tests) |
|---|---|---|
| LINE | L | chained segments; one committed transaction PER segment (one undo step each); `Undo` removes the last segment of THIS run (document undo), `Close` closes back to the first point; Enter ends |
| CIRCLE | C | center + radius; `Diameter` option; point entry at the radius prompt = distance from center |
| ARC | A | 3-point (default; CCW representation passing through the mid point) and Start-Center-End (keyword-selected); collinear points re-ask |
| ERASE | E | selection ids (Enter ends; stale/duplicate ids ignored) → remove in ONE transaction; removed ids dropped from document selection |
| MOVE | M | base → second point (in place, journaled `update_entity`); `Displacement` option |
| COPY | CO | duplicate with fresh ids + new handles, display properties preserved; keeps prompting for additional placements with `Exit`/`Undo` (one committed transaction PER placement) |
| ROTATE | RO | base point + angle (CCW about +Z); point entry = angle from base |
| SCALE | SC | base point + factor; `Reference` length-ratio method; point entry = distance from base |
| UNDO / REDO | U / — | document.undo()/redo() + feedback (zero-prompt; run headless without any provider) |

- All mutations go through `ctx.document.transaction(...)` ONLY (contract
  §4.2 binding rule); transforms recompute entity geometry analytically via
  `geometry.py` (`move_changes`/`rotate_changes`/`scale_changes` applied
  through the journaled `Document.update_entity`, so UNDO restores geometry —
  direct attribute writes are preview-only and never touch document entities).
- `geometry.py` also holds the analytic helpers: 3-point circumcircle/arc
  (CCW sweep selection), point transforms about +Z, and polyline samplers
  (`arc_points`, `circle_points`) used by the shell's display sync.
- Selection prompts honor PICKFIRST-style preselection (ux-spec §3.5):
  preselected document entities pass straight into the command.
- Layer management stays M2: M1 commands read layer "0"/current metadata
  only (contract §5).

Boundary note: bcdraft imports `bccmd` because the commands ARE
`bccmd.CommandSpec` objects; the edge is strictly one-way (bcdraft → bccmd),
no package cycle. The glossary §4 `drafting` depends_on row (document,
kernel) predates the M1 command contract and is flagged for the TL to amend.

## Planned public API sketch — M2+ (not yet implemented)

- `DraftEntityFactory` — 2D entity creation with drafting defaults
- `SnapEngine` — osnap resolution, ortho/polar/tracking constraints
- `PrecisionInputParser` — keyboard/coordinate entry (dynamic input syntax)
- `SelectionModel` — selection sets, filters, hit-testing hooks
- `GripEditor` — grip modes and grip-driven modification
- `ModifyOpsRegistry` — more modify behaviors (offset/trim/mirror/…)

## Tests

- docs/30-process/test-plan.md: TP-CAT-01 (drafting & command-system
  functional; drafting sections). Suite: `modules/drafting/tests/`
  (`test_draw_commands.py`, `test_modify_commands.py`,
  `test_doc_commands.py`, `test_geometry.py`, `test_no_bpy.py`) — every
  command is driven through `Registry.run_command` with scripted providers
  (the exact interface the UI uses) against the REAL bcdoc, asserting
  exact coordinates, undo granularity and round-trips. Run with
  `python3 -m pytest modules/drafting/tests -q` from the repo root
  (Blender is NOT needed).
