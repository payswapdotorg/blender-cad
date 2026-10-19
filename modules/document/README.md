# Module: document

- **Status:** in-progress — **M1 status: implemented (bcdoc v0)**; the pure-Python document model v0 is coded and green under plain pytest. Nothing beyond the v0 scope (blocks, checkpoints, entity kinds past line/circle/arc…) is implemented or claimed.
- **Owner:** W2
- **Date:** 2026-10-19 (UTC; M1 implementation added same date)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M1 (document model v0 — glossary §11); spec: docs/00-architecture/m1-module-contracts.md §3 (binding)

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

## M1 public API — IMPLEMENTED (bcdoc, `modules/document/bcdoc/`)

Pure Python, no `bpy` (enforced by tests and `scripts/check_module_boundaries.py --imports`);
importable as the top-level package `bcdoc` under pytest (repo-root `conftest.py`), in the
extension host and in the agent sidecar.

| Name | Summary (exact contract: m1-module-contracts.md §3) |
|---|---|
| `Document(name="Untitled", units=None)` | authoritative model: `doc_version` (monotonic, bumped by every COMMITTED transaction), `layers` (always contains `"0"`), `next_handle`, `selection`, `on_change`/`on_select` callback lists |
| `Document.transaction(label) -> Transaction` | context manager; clean exit → commit (undo group pushed, version+1, on_change fired); exception → FULL rollback (serialize()-bit-identical restore) |
| `Document.add_entity(e, handle=None) -> Entity` | only inside a transaction (else `errors.NoOpenTransaction`); assigns monotonic handle (`errors.DuplicateHandle` on explicit-handle collision); optional `handle=` preserves foreign (DXF) handles |
| `Document.get(eid)` / `remove(eid)` / `entities()` / `count_by_kind()` | lookup, journaled removal (insertion position preserved through undo), insertion-ordered list, kind counts |
| `Document.update_entity(eid, **changes)` | journaled in-transaction field changes (layer/color/linetype + kind geometry fields; auto-creates unknown layers, undo reverts both) — the transform path drafting (W1) uses |
| `Document.add_layer(name)` | journaled layer-table append (used by bcio import) |
| `Document.undo() -> bool` / `redo() -> bool` / `undo_depth()` / `redo_depth()` | undo/redo re-apply journals as NEW committed transactions (version bumps — monotonicity rule); False when the stack is empty; new mutation clears redo |
| `Document.serialize() -> str` / `Document.load(text)` | stable JSON, schema `bcdoc/1` exactly (name, units, doc_version, next_handle, layers, entities in insertion order, undo journal, redo stack, selection ids+epoch); byte-stable round-trip; `load` raises `errors.SerializationError` on any other schema |
| `Entity` / `Line(p1, p2)` / `Circle(center, radius)` / `Arc(center, radius, start_angle, end_angle)` | `id` (uuid4 hex, immutable), `handle`, `layer="0"`, `color=None` (ACI or ByLayer), `linetype="ByLayer"`, `kind` property ("line"/"circle"/"arc"); geometry = world-coords 3-float tuples in drawing units |
| `SelectionState` | `epoch` (bumps on every change), `ids` frozenset, `set/add/remove/clear`; NEVER bumps `doc_version` |
| `Transaction` / `UndoGroup` | committed flag; one committed transaction's reversal (label, doc_version, reversed-op journal) |
| `bcdoc.errors` | `NoOpenTransaction`, `SerializationError`, `EntityNotFound`, `DuplicateEntity`, `DuplicateHandle`, `InvalidHandle`, `InvalidEntityField`, `DuplicateLayer`, `TransactionAlreadyOpen`, `JournalConflict`, `BcdocError` |

### How to run the tests

```
cd <repo root>
/home/z/.venv/bin/python3 -m pytest modules/document/tests -q      # contract suite + no-bpy guarantee
```

No Blender required (plain pytest; the suite asserts `bpy` is absent both by
source scan and by importing the package in a clean subprocess). The
`modules/document/__init__.py` / `tests/__init__.py` package markers exist so
the mandated `test_no_bpy.py` file name can also be used by other module
suites without pytest module-name collisions; the shipped package is
`bcdoc` only.

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
  checkpoint rollback). M1 suite (implemented, green):
  `modules/document/tests/` — `test_document.py` (creation defaults,
  commit/rollback bit-identity, NoOpenTransaction, undo/redo geometry +
  doc_version monotonicity, handle monotonicity, selection epochs, serialize
  round-trip equality + schema rejection, event ordering) and
  `test_no_bpy.py` (source scan + runtime + clean-subprocess no-bpy).
- Cross-module: `modules/testing/roundtrip/` (TP-CAT-04 precursor) exercises
  bcdoc through bcio DXF round-trips.
