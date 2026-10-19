# Module: shell

- **Status:** planned (no code at M0)
- **Owner:** W1
- **Date:** 2026-10-19 (UTC)
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
- Layout tabs (hosting `drawings`' layouts), workspace profiles/save-state
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

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `WorkspaceShell` — workspace lifecycle: enter/leave CAD workspace cleanly
- `RibbonModel` — tabs/panels/buttons bound to commands
- `PaletteHost` — dockable palette registration and layout persistence
- `CommandLineDock` — the command-line surface hosting the prompt session
- `StatusBarHost` — toggles/modes/coordinates readout
- `WorkspaceProfiles` — named workspace layouts and save/restore

## Tests

- docs/30-process/test-plan.md: TP-CAT-01 (functional UX sections) and
  TP-CAT-10 (comparative usability program — summative at M7). Suite home
  once code lands: `modules/shell/tests/`.
