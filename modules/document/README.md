# Module: document

- **Status:** in-progress — **M2 status: implemented (bcdoc v2)**: the M1 v0 surface (entities line/circle/arc, transactions, undo/redo, selection) is green, and the M2 v2 additions (full layer table, blocks, layouts/spaces, settings/sysvars, text/dim styles, 10 new entity kinds, bcdoc/2 serialization with deterministic bcdoc/1 upgrade) are implemented and green under plain pytest. Nothing beyond that scope (per-viewport layer overrides, annotative scales, dynamic blocks…) is implemented or claimed.
- **Owner:** W2 (W-B1 for the M2 document-model upgrade)
- **Date:** 2026-10-19 (UTC; M1 v0 + M2 v2 implemented same date)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Target milestone:** M2 (document model v2 — glossary §11); spec: docs/00-architecture/m2-module-contracts.md §2 (binding), m1-module-contracts.md §3 for the unchanged M1 surface (§14 amendments)

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

Pure Python, no `bpy` (enforced by tests; `scripts/check_module_boundaries.py --imports` is a TL-owned M2 addition), stdlib only; importable as the top-level package `bcdoc` under pytest (repo-root `conftest.py`), in the extension host and in the agent sidecar.

| Name | Summary (exact contract: m1-module-contracts.md §3) |
|---|---|
| `Document(name="Untitled", units=None)` | authoritative model: `doc_version` (monotonic, bumped by every COMMITTED transaction), `layers` (always contains `"0"`), `next_handle`, `selection`, `on_change`/`on_select` callback lists |
| `Document.transaction(label) -> Transaction` | context manager; clean exit → commit (undo group pushed, version+1, on_change fired); exception → FULL rollback (serialize()-bit-identical restore) |
| `Document.add_entity(e, handle=None) -> Entity` | only inside a transaction (else `errors.NoOpenTransaction`); assigns monotonic handle (`errors.DuplicateHandle` on explicit-handle collision); optional `handle=` preserves foreign (DXF) handles |
| `Document.get(eid)` / `remove(eid)` / `entities()` / `count_by_kind()` | lookup, journaled removal (insertion position preserved through undo), insertion-ordered list, kind counts |
| `Document.update_entity(eid, **changes)` | journaled in-transaction field changes (layer/color/linetype + kind geometry fields; auto-creates unknown layers, undo reverts both) — the transform path drafting (W1) uses |
| `Document.add_layer(name)` | journaled layer-table append (used by bcio import) — **M2**: thin compat wrapper creating a default `LayerRecord` via `doc.layers.add` |
| `Document.undo() -> bool` / `redo() -> bool` / `undo_depth()` / `redo_depth()` | undo/redo re-apply journals as NEW committed transactions (version bumps — monotonicity rule); False when the stack is empty; new mutation clears redo |
| `Document.serialize() -> str` / `Document.load(text)` | stable JSON — **schema `bcdoc/2` as of M2** (pinned key order; `settings`/`layers`(records)/`current_layer`/`text_styles`/`dim_styles`/`blocks`/`layouts` keys added; entities carry `lineweight` + `space`); byte-stable round-trip; `load` accepts `bcdoc/1` (deterministic upgrade) AND `bcdoc/2`, raises `errors.SerializationError` otherwise |
| `Entity` / `Line(p1, p2)` / `Circle(center, radius)` / `Arc(center, radius, start_angle, end_angle)` | `id` (uuid4 hex, immutable), `handle`, `layer="0"`, `color=None` (ACI, ByLayer; **0 = ByBlock as of M2**), `linetype="ByLayer"`, `lineweight=None` (mm; ByLayer), `space="MODEL"` (**M2**), `kind` property; geometry = world-coords 3-float tuples in drawing units |
| `SelectionState` | `epoch` (bumps on every change), `ids` frozenset, `set/add/remove/clear`; NEVER bumps `doc_version` |
| `Transaction` / `UndoGroup` | committed flag; one committed transaction's reversal (label, doc_version, reversed-op journal) |
| `bcdoc.errors` | `NoOpenTransaction`, `SerializationError`, `EntityNotFound`, `DuplicateEntity`, `DuplicateHandle`, `InvalidHandle`, `InvalidEntityField`, `DuplicateLayer`, `TransactionAlreadyOpen`, `JournalConflict`, `BcdocError` (+ the v2 classes listed above) |

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

## M2 public API — IMPLEMENTED (bcdoc v2 additions, `modules/document/bcdoc/`)

Everything below is pure Python (no `bpy`, stdlib only), journaled and
undoable per the transactional rules unless noted. Spec: m2-module-
contracts.md §2 (binding).

### Entity framework (§2.1)

| Name | Summary |
|---|---|
| `PROPERTY_FIELDS` | `("layer", "color", "linetype", "lineweight", "space")` — `lineweight` is mm (`None` = ByLayer), `space` is `"MODEL"` or a layout name; color `0` = ByBlock (members of block definitions; resolved at display/interchange) |
| `Point(position)` | new kind; `position` point |
| `Polyline(vertices, bulges=None, widths=None, closed=False)` | vertices are 3-tuples; bulge = AutoCAD `tan(Δ/4)`, CCW positive, one per vertex (`bulges[i]` for the segment leaving vertex i); `widths[i] = [start, end]` for that same segment; length mismatches raise `ValueError` |
| `Ellipse(center, major_axis, ratio, start_angle=0.0, end_angle=360.0)` | full ellipse by default |
| `Xline(p1, p2)` / `Ray(p1, p2)` | construction lines (display clips) |
| `Text(position, height=2.5, rotation=0.0, content="", style="Standard", justification="LEFT")` | justification ∈ LEFT/CENTER/RIGHT |
| `Mtext(position, width=0.0, content="", style="Standard")` | embedded newlines respected |
| `Dim(dim_type, p1, p2, angle=0.0, offset_point=(0,0,0), measured_id="", measurement=0.0, text_override="", style="Standard", text_position=None)` | `dim_type` ∈ "linear"/"aligned"; `measured_id` = associativity target; `measurement` cached (regen refreshes); `text_position=None` = auto placement |
| `Insert(name, position, scale=(1,1,1), rotation=0.0)` | references a block BY NAME |
| `Viewport(center, view_height, p1, p2, locked=False)` | lives in a LAYOUT's space; center/view_height describe the MODEL view, p1/p2 the paper rect |
| per-kind coercer registry | `bcdoc.entities.GEOMETRY_FIELDS` / `GEOMETRY_COERCERS` / `COERCERS` — single validation + wire-form source used by `set_field`, `to_json_dict` and `serialize`; `to_json_dict` emits common properties in the pinned order (kind, id, handle, layer, color, linetype, lineweight, space) then geometry in registry order |

### Layer table (§2.2)

| Name | Summary |
|---|---|
| `Document.layers` | `LayerTable` (ordered; "0" first, always present). M1 call sites keep working: `name in doc.layers`, `len()`, iteration over names, `doc.layers == ["0", …]` |
| `LayerRecord` | `name, color=7 (ACI), linetype="Continuous", lineweight=None (mm), on=True, frozen=False, locked=False, plot=True`; `to_dict()` key order `{name, color, linetype, lineweight, on, frozen, locked, plot}` (pinned) |
| `doc.layers.add(name, **props)` / `set_props(name, **changes)` / `remove(name)` | require an open transaction; journal `add_layer {name, props}` / `mutate_layer {name, changes}` / `remove_layer {name, record}` |
| guards | `remove("0")` → `errors.ProtectedRecord`; removing a layer with entities → `errors.LayerNotEmpty`; unknown layer → `errors.LayerNotFound`; bad props → `ValueError` (no partial apply) |
| `Document.add_layer(name)` | thin M1 compat wrapper (bcio): default record; returns the name |
| `Document.current_layer` | reads the `CLAYER` setting, falls back `"0"` when it references a missing layer |
| flag semantics (on/frozen/locked) | stored here, ENFORCED at consumers (commands/sync/osnap) per contract §2.2 |

### Blocks (§2.3)

| Name | Summary |
|---|---|
| `BlockDefinition` | `name, base_point, handle, entities` — owned COPIES, never in the doc entity store; `to_dict()` = `{name, base_point, handle, entities}` (pinned) |
| `doc.add_block(name, base_point, entities)` | tx; deep-copies members (`entity.copy()`), strips their `space` to `MODEL`, keeps layer/color/linetype/lineweight (ByBlock 0 legal); definition handle comes from the document handle space |
| `doc.block(name)` / `doc.blocks()` / `doc.block_names()` | lookup (`errors.BlockNotFound`), names in definition order, alias |
| `doc.redefine_block(name, entities, base_point=None)` | tx; every insert reference updates automatically (by-name references); `base_point=None` keeps the current one |
| `doc.remove_block(name)` | tx; `errors.BlockInUse` while `insert` references exist |
| `doc.block_ref_ids(name)` | insert entity ids referencing the block, store order |
| journal ops | `add_block`/`remove_block`/`redefine_block` with full entity-dict snapshots (replay + save/load rebuild definitions; restored members are equal copies, no identity contract) |

### Layouts + spaces (§2.4)

| Name | Summary |
|---|---|
| `LayoutRecord` | `name, page_width=420.0, page_height=297.0, paper_units="mm"`; `to_dict()` = `{name, page_width, page_height, paper_units}` (pinned) |
| `doc.add_layout(name, page_width=420.0, page_height=297.0, paper_units="mm")` / `doc.layout(name)` / `doc.layouts()` / `doc.rename_layout(old, new)` / `doc.remove_layout(name)` / `doc.reorder_layout(name, index)` | tx-gated + journaled (`add_layout`/`remove_layout`/`rename_layout {old,new}`/`reorder_layout {name, old_index}`); rename RE-ROUTES entities in that space (they never reference a missing layout) |
| guards | `errors.DuplicateLayout`, `errors.LayoutNotFound`, `errors.LayoutNotEmpty` (entities still live in the space) |
| `doc.current_space` | SESSION state ("MODEL" default; NOT serialized, NOT journaled); `doc.set_current_space(name)` validates `name ∈ {"MODEL"} ∪ layout names` (`errors.InvalidSpace`) and maintains `TILEMODE` (1 in MODEL, 0 in paper) |
| `doc.active_layout` | SESSION state (`str | None`; which layout tab is viewed); managed by the layout commands (bcdraw), not by bcdoc |
| `doc.last_selection_ids` | SESSION state (the "Previous" selection mode for §4 selection helpers) |
| `doc.entities_in_space(name)` | live entities with `space == name`; `doc.add_entity` validates `space` ∈ {"MODEL"} ∪ layout names (`errors.InvalidSpace`) |

### Settings / sysvars (§2.5)

| Name | Summary |
|---|---|
| `SETTING_DEFS` / `Settings` | the 19-setting registry (CLAYER, OSMODE, ORTHOMODE, SNAPMODE, SNAPUNIT, GRIDMODE, GRIDUNIT, APERTURE, DYNMODE, PICKFIRST, TILEMODE, INSUNITS, LUNITS, LUPREC, AUNITS, AUPREC, TEXTSTYLE, DIMSTYLE, LTSCALE) with exact defaults; typed `get`/`set` (+ `doc.settings["OSMODE"]` subscript style), `to_json`/`from_json` |
| errors | unknown name → `errors.UnknownSetting`; bad type/choices → `errors.InvalidSettingValue` (ints reject bools; floats accept ints; non-finite rejected; ORTHOMODE/SNAPMODE/GRIDMODE/PICKFIRST/TILEMODE restricted to 0/1) |
| **UNDO exception (binding)** | settings are **persisted in serialization but NOT journaled and NOT rolled back** — UNDO does not revert sysvars (AutoCAD precedent for out-of-command changes); a failed transaction leaves settings changes applied while all CONTENT rolls back bit-identically |

### Styles (§2.6)

| Name | Summary |
|---|---|
| `TextStyleRecord` | `name, height=2.5, width_factor=1.0` |
| `DimStyleRecord` | `name, dimscale=1.0, dimtxt=2.5, dimasz=2.5, dimexo=0.625, dimexe=1.25` |
| `doc.text_styles()` / `add_text_style(name, **props)` / `text_style(name)` (+ dim equivalents) | "Standard" always present in both tables; current style = the `TEXTSTYLE`/`DIMSTYLE` setting (set via `doc.settings` only) |
| `doc.set_text_style_props(name, **changes)` / `remove_text_style(name)` (+ dim equivalents) | journaled `mutate_*`/`remove_*` ops; removing "Standard" → `errors.ProtectedRecord` |

### Serialization — schema `bcdoc/2` (§2.7)

`doc.serialize()` always writes `bcdoc/2` with the pinned key order
`(schema, name, units, doc_version, next_handle, settings, layers,
current_layer, text_styles, dim_styles, blocks, layouts, entities, undo,
redo, selection)`. `Document.load(text)` accepts **both** `bcdoc/1`
(deterministic upgrade: layer names → default records, settings defaults,
entities gain `lineweight=None` + `space="MODEL"`, no blocks/layouts/
styles) and `bcdoc/2`; anything else raises `errors.SerializationError`.
Byte-stability holds for v2 round-trips and across repeated v1-upgrade
cycles; M1 journals with bare `{"op": "add_layer", "name": …}` replay
with default records.

### Journal op vocabulary (§2.8)

M1 ops (`add`/`remove`/`mutate`/`add_layer`/`remove_layer`) plus:
`mutate_layer`, `add_block`/`remove_block`/`redefine_block`,
`add_layout`/`remove_layout`/`rename_layout`/`reorder_layout`,
`add_text_style`/`remove_text_style`/`mutate_text_style`,
`add_dim_style`/`remove_dim_style`/`mutate_dim_style`.
`_snapshot_state`/`_restore_state` cover all new tables (atomic rollback
for failed transactions; settings + session state deliberately excluded —
see the exception above).

### New error classes (v2)

`LayerNotFound`, `LayerNotEmpty`, `ProtectedRecord`, `BlockNotFound`,
`DuplicateBlock`, `BlockInUse`, `LayoutNotFound`, `DuplicateLayout`,
`LayoutNotEmpty`, `InvalidSpace`, `UnknownSetting`, `InvalidSettingValue`,
`StyleNotFound`, `DuplicateStyle` — all `bcdoc.errors.BcdocError`
subclasses with the established message style.

## Planned public API sketch — PLANNED CONTRACTS, not implementations

- `EntityRef` / `EntityId` — stable identity handles across sessions
- `UnitSystem` — document units, conversions, display formatting
- `CheckpointManager` — named checkpoints (agent rollback points)
- Per-viewport layer overrides, annotative scales — deferred past M2

## Tests

- docs/30-process/test-plan.md: TP-CAT-01/02 (functional baselines),
  TP-CAT-07 (shared-document semantics: `doc_version`, `entity_lock`,
  checkpoint rollback). M2 suite (implemented, green):
  `modules/document/tests/` — `test_document.py` (the M1 contract suite;
  schema assertions updated to bcdoc/2 per m2 contracts §14 — intent kept),
  `test_document_v2.py` (new kinds, layer table, blocks, layouts/spaces,
  settings, styles, bcdoc/2 byte-stability + v1 upgrade + journal replay)
  and `test_no_bpy.py` (source scan + runtime + clean-subprocess no-bpy).
- Cross-module: `modules/testing/roundtrip/` (TP-CAT-04 precursor) exercises
  bcdoc through bcio DXF round-trips (schema references updated to
  bcdoc/2; test logic unchanged).
