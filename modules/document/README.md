# Module: document

- **Status:** planned (no code at M0)
- **Owner:** W2
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1 (document model v0 — glossary §11)

## Purpose

The authoritative CAD document model: entities, layers, blocks, properties,
units, transactions, the undo journal and named checkpoints. Every mutation
of engineering state — user, command or agent — goes through this module's
transaction mechanisms (glossary §6 runtime principle).

## Owns

- Entity storage, identity and lookup; entity property system
- Layer and block tables; organizational structures
- Unit system and document metadata
- Transaction begin/commit/abort semantics; the `doc_version` counter
- Undo journal and named checkpoints (rollback points)

## Does NOT own

- Geometry mathematics and tessellation (`kernel`)
- Any UI or command behavior (`shell`, `commands`)
- File formats and persistence beyond the native model (`interchange`)
- Agent permission policy (`agent`)

## FP areas

- None directly — `document` underpins the areas owned by dependent modules.

## Allowed dependencies

- None (leaf module).

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `EntityStore` — create/query/delete entities by id and type
- `EntityRef` / `EntityId` — stable identity handles across transactions
- `LayerTable` / `BlockTable` — organization tables with change notification
- `PropertyBag` — typed per-entity properties
- `UnitSystem` — document units, conversions, display formatting
- `Transaction` — begin/commit/abort; bumps `doc_version` on commit
- `UndoJournal` — replayable journal feeding undo/redo
- `CheckpointManager` — named checkpoints (agent rollback points)

## Tests

- docs/30-process/test-plan.md: TP-CAT-01/02 (functional baselines),
  TP-CAT-07 (shared-document semantics: `doc_version`, `entity_lock`,
  checkpoint rollback). Suite home once code lands: `modules/document/tests/`.
