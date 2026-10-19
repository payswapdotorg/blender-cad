# Module: commands

- **Status:** planned (no code at M0)
- **Owner:** W1
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1–M2 (registry + prompt state machine at M1; full drafting command surface at M2 — glossary §11)

## Purpose

The command system: a registry of commands with aliases, the prompt state
machine that sequences prompts the AutoCAD-familiar way, command history and
dynamic input. This is the keyboard-first heart of the UX acceptance
criterion.

## Owns

- Command registry (register, resolve by name/alias, dispatch)
- Alias table (user-remappable)
- Prompt state machine (options, defaults, keyword branches)
- Command history and repeat/redo-from-command-line behaviors
- The skill registration hook (see the inversion note below)

## Does NOT own

- Skill execution (`skills` — see inversion note in modules/README.md §4:
  `commands` does NOT depend on `skills`; skills register into `commands`)
- Entity behaviors (`drafting`), annotation (`drawings`), toolset content (`toolsets`)
- UI hosting of the command line (`shell`)

## FP areas

- CMD — command system

## Allowed dependencies

- `document`, `drafting`, `drawings`, `parametric`, `interchange`, `toolsets`

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `CommandRegistry` — register commands; resolve by name or alias; dispatch
- `PromptSession` — the prompt state machine: prompts, keywords, defaults, undo-of-input
- `AliasTable` — alias storage with user overrides
- `CommandHistory` — session history powering repeat ("Enter = last command")
- `DynamicInputBinding` — wire dynamic input from `drafting` into prompts
- `SkillHook` — the registration point by which `skills` exposes skill names in the command line

## Tests

- docs/30-process/test-plan.md: TP-CAT-01 (drafting & command-system
  functional; command sections). Suite home once code lands:
  `modules/commands/tests/`.
