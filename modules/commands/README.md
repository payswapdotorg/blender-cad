# Module: commands

- **Status:** in-progress — M1 status: implemented (bccmd v0) — registry + prompt state machine + input parsing + history, all green under plain pytest and exercised end-to-end inside Blender by the shell driver
- **Owner:** W1
- **Date:** 2026-10-19 (UTC); M1 implementation update appended below
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

## M1 implemented surface (bccmd v0, contract §4 of m1-module-contracts.md)

Package: `modules/commands/bccmd/` — pure Python, NO bpy (enforced by
`modules/commands/tests/test_no_bpy.py`: source scan + in-process
sys.modules walk + fresh-subprocess import).

| File | Contents |
|---|---|
| `spec.py` | `Point`, `InputValue`, `Request`, `Cancelled`, `CommandResult`, `CommandContext` (host-provided: document/view/history/feedback/`last_point`), `Runner.ask()/ask_until()`, `run_steps` (steps-generator → contract `run(ctx, runner)`), `CommandSpec` |
| `state.py` | `PromptMachine` (ux-spec §3.2 states idle → command_active → collecting → preview → commit → idle; illegal transitions raise `StateError`) and `StepDriver` (drives a steps-generator one InputValue at a time — what the modal viewport operator and agents use) |
| `registry.py` | `Registry.register/lookup/names/run_command(ctx, name, provider)`; duplicate name/alias → `DuplicateCommand`; unknown → `UnknownCommand`; `register_hook(name, callable)` (skills hook — present, unused at M1) |
| `input.py` | AutoCAD-familiar parsing (contract §4.4): `"12,34"`, `"12,34,5"`, `"5<30"`, `"@3,4"`, `"@5<30"`, `"@"`, plain numbers per request kind, prefix-insensitive unambiguous keyword matching with significant-uppercase shortcuts, `InputParseError` (never aborts — diagnostic + re-ask), `ScriptedProvider` |
| `history.py` | `History`/`HistoryEntry` — bounded session transcript with raw inputs, summary, ISO-8601 UTC timestamp |

Key behaviors (all covered by `modules/commands/tests/`):

- Commands mutate documents ONLY through `ctx.document` transactions
  (contract §4.2 binding rule); bccmd never touches a document itself.
- One input model, three sources: the blocking `Runner` (tests/agents),
  the `StepDriver` (modal viewport operator), and the shell's scripted
  path all execute the SAME steps-generators — command logic exists once.
- Invalid input NEVER aborts: parse errors and wrong-kind inputs sink a
  diagnostic and re-ask the same Request (ux-spec §3.2/§3.3).
- `Registry.run_command` drives the full machine discipline
  (begin → collect → commit → finish, or cancel on `Cancelled`), records
  history with raw inputs, and leaves the machine idle after errors.
- `test_document_contract.py` verifies bccmd's expectations against the
  REAL bcdoc (15/15; the doubles in `doubles_document.py` remain only as a
  contract-verification fallback when bcdoc is absent).

## Planned public API sketch — M2+ (not yet implemented)

- `AliasTable` — user alias overrides (acad.pgp-style import, ux-spec §6.1)
- `DynamicInputBinding` — wire dynamic input from `drafting` into prompts
- Transparent commands (`'ZOOM`-style), implied preselection plumbing
- `SkillHook` consumers (skills package, M6)

## Tests

- docs/30-process/test-plan.md: TP-CAT-01 (drafting & command-system
  functional; command sections). Suite: `modules/commands/tests/`
  (registry, input parsing, state machine, prompt loop + scripted
  providers, history, no-bpy, bcdoc contract) — run with
  `python3 -m pytest modules/commands/tests -q` from the repo root
  (repo-root conftest.py bootstraps sys.path; Blender is NOT needed).
