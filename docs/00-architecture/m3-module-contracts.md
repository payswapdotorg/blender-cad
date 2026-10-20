# M3 Module Contracts — bcdoc/3 schema (constrained-sketch content)

- **Status:** Binding for the bcdoc/3 schema work (M3, first product-code lane
  of the milestone). Extends `m2-module-contracts.md` (still binding for
  unchanged surfaces); where the two disagree, THIS file wins for the
  bcdoc/3 scope and the M2 file wins for everything else. Amendments to
  either are appended (§8 here / §15 there), never silently rewritten.
- **Owner:** TL1 (schema + implementation, this lane); the parametric-module
  integration contracts (M3 §6 items 1–2 of `par-solver-head-to-head.md`)
  are owned by the integration lane and are NOT bound here.
- **Date:** 2026-10-20 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)
- **Provenance of every design decision below:** the m3-eval seam record
  (`cad-sketcher-evaluation.md` §4.3 + `experiments/cad-sketcher/findings/bcdoc-seam.md`
  §2/§4 — the demonstrated gap list), the head-to-head decision record
  (`par-solver-head-to-head.md` §6 item 3 — "bcdoc/3 schema work —
  unchanged and independent of this decision"), and the bcdoc/2 baseline
  (`m2-module-contracts.md` §2.7/§2.8). The seam design (bcdoc-first,
  stateless solver service, journaled apply-back) is design-locked by the
  m3-eval record and is NOT reopened here; this contract defines the
  DOCUMENT CONTENT that seam stores, and nothing else.

## 0. Scope (operator-directed)

This document binds exactly one deliverable: **the bcdoc/3 schema — the
document-side records a constrained sketch needs to be first-class document
content** (m3-eval §8 item 4; the seam record's gap list items 1, 2, 4, 5,
6). Concretely:

1. a **`SketchTable`** of `SketchRecord`s — constraints as journaled,
   serialized, undoable document content (gap 1);
2. **junction identity** — an id-stable per-sketch junction map (gap 2,
   the "per-sketch junction map" option; the "Point entity references"
   option is recorded as rejected in §7);
3. a **workplane record** per sketch (gap 4);
4. **driving-dimension records** with the reference-dimension gating flag
   as a first-class field (gap 5);
5. **solve-report records** — the session-state shape for solver
   diagnostics (gap 6).

NOT in scope (binding exclusions, §7): any parametric-module code, any
solver integration, any kernel/UI work, the seam itself. Gap 3 (per-entity
solver-param persistence) is explicitly NOT implemented — the m3-eval
record rejected it for the stateless-seam design and this contract keeps
that decision.

**Nothing here adopts a component.** bcdoc is first-party product code;
no adoption-matrix row, no license-inventory consequence, no kernel
direction (ADR-0002 unaffected), no release-manifest change arises from
this contract.

## 1. Records (`modules/document/bcdoc/sketches.py`)

### 1.1 `Workplane`

A deterministic description of the plane a sketch lives in (seam record
§2.2: "origin + basis, or later a named UCS" — v3 pins the origin+basis
form; named-UCS workplanes remain open for a later revision):

```python
Workplane(origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0))  # XY@origin
```

- `origin`, `x_axis`, `y_axis`: 3-float tuples (`normalize_point`
  semantics: 2D input gains `z=0.0`).
- Validation: `x_axis` and `y_axis` must be non-zero and non-parallel
  (cross product ≠ the zero vector — an exact check, no epsilon; the
  workplane is a stored description, not enforced geometry, and the
  adapter owns the math).
- The plane normal is DERIVED (`x_axis × y_axis`) by consumers; it is
  not stored (single source of truth).
- JSON form (pinned key order): `{"origin": [x, y, z], "x_axis":
  [x, y, z], "y_axis": [x, y, z]}`.

### 1.2 `ConstraintRecord`

One constraint, addressing bcdoc entities **by entity id** (plus an
endpoint slot for lines — the seam record §2.2 ref model, verbatim):

```python
ConstraintRecord(c_id="d1", kind="distance",
                 refs=[{"entity": l1.id, "slot": 0}, {"entity": l2.id, "slot": 1}],
                 value=50.0, driven=False)
```

- `c_id: str` — stable per-sketch identity for addressing and
  diagnostics. Caller-supplied when the caller wants readable labels
  (the corpus pattern: `k1…kN`, `d1…dN`); auto-generated (uuid4 hex,
  like entity ids) when omitted. Unique within a sketch. Immutable.
- `kind: str` — CLOSED vocabulary of 15 kinds, split by arity
  (refs count, exact) and class:

  | kind | refs | class | `value` |
  |---|---|---|---|
  | `coincident` | 2 point refs | geometric | None |
  | `coincident_origin` | 1 point ref | geometric | None |
  | `horizontal` | 1 line ref | geometric | None |
  | `vertical` | 1 line ref | geometric | None |
  | `parallel` | 2 line refs | geometric | None |
  | `perpendicular` | 2 line refs | geometric | None |
  | `tangent` | 2 curve refs | geometric | None |
  | `concentric` | 2 circle/arc refs | geometric | None |
  | `midpoint` | 2 refs | geometric | None |
  | `symmetric` | 3 refs (2 points + symmetry ref) | geometric | None |
  | `distance` | 2 point refs | dimensional | required |
  | `length` | 1 line ref | dimensional | required |
  | `radius` | 1 circle/arc ref | dimensional | required |
  | `diameter` | 1 circle/arc ref | dimensional | required |
  | `angle` | 2 line refs | dimensional | required |

  The vocabulary is exactly the kinds exercised by the committed
  evidence (the 23-case canonical corpus + the seam demonstration +
  the h2h adapter notes); anything else fails construction. Additive
  growth is a schema revision, not a runtime string.

- `refs: tuple[dict, …]` — each ref is exactly one of
  `{"entity": "<id>"}` (a whole entity), `{"entity": "<id>", "slot":
  0|1}` (a line endpoint: slot 0 = `p1`, slot 1 = `p2`), or
  `{"junction": "<junction_id>"}` (a junction point, §1.3).
  Line-kind enforcement for slot refs happens at the table layer
  (§5) where the document is in hand; the record validates FORM and
  ARITY only.
- `value: float | None` — the dimension value. Required and finite for
  dimensional kinds; must be `None` for geometric kinds.
- `driven: bool` — **the reference-dimension gating flag, first-class**
  (seam gap 5; CAD Sketcher's reference-dimension gating,
  `curve_solver.py:335-352`, becomes a record field). `False` =
  driving (the constraint participates in the solve system);
  `True` = reference-only (measured FROM the current geometry, never
  constraining). Legal ONLY on dimensional kinds — a geometric
  constraint with `driven=True` fails construction. The solver service
  gates reference dimensions out of the system exactly as CAD Sketcher
  does; bcdoc stores the flag, it does not police the solver.
- JSON form (pinned key order, all keys always present):
  `{"c_id": …, "kind": …, "refs": [...], "value": …, "driven": …}`.

### 1.3 `JunctionRecord`

A named "same point" grouping of line endpoints (seam record §2.5: the
value-endpoint nuance — bcdoc lines carry endpoint VALUES, so a "shared
vertex" is coincident-by-value; the junction record gives that merged
point a stable identity without forcing a second geometry store or extra
document entities):

```python
JunctionRecord(junction_id="j1",
               members=[{"entity": l1.id, "slot": 1}, {"entity": l2.id, "slot": 0}])
```

- `junction_id: str` — stable per-sketch identity (caller-supplied or
  uuid4-hex auto). Unique within a sketch. Immutable.
- `members: tuple[dict, …]` — one or more `{"entity", "slot"}` line
  endpoint refs. ≥1 members is legal (a 1-member junction is a named
  point; the adapter materializes it as one solver point — tolerant by
  design, because drawing tools create the junction with the first line
  and grow it as lines connect).
- Semantics: the listed endpoints ARE one point. The solve enforces it;
  the record does not (no stored coordinates — the point's position is
  derived from member geometry per solve).
- JSON form (pinned key order): `{"junction_id": …, "members": [...]}`.
- Constraints may address a junction through a `{"junction": …}` ref
  (e.g. `distance` between two junctions — the natural corner-to-corner
  dimensional UX).

### 1.4 `SketchRecord`

One sketch — the container the gap list proposed (§2.2 of the seam
record), with the junction map added (gap 2):

```python
SketchRecord(sketch_id="sk1", name="Frame", workplane=Workplane(),
             junctions=[...], constraints=[...])
```

- `sketch_id: str` — non-empty, unique in the table, immutable (the
  addressing key; there is deliberately NO rename op in v3 — `name`
  is the display field, not the key).
- `name: str` — display name; defaults to `sketch_id`.
- `workplane: Workplane` — §1.1; defaults to XY@origin (the seam's
  demonstrated default).
- `junctions: [JunctionRecord]` and `constraints: [ConstraintRecord]`
  — §1.3/§1.2; c_ids and junction_ids unique within the sketch
  (enforced at every mutation and at load).
- JSON form (pinned key order, all keys always present):
  `{"sketch_id": …, "name": …, "workplane": {...}, "junctions":
  [...], "constraints": [...]}` — junctions before constraints
  (definitional order: constraints may address junctions).

### 1.5 `SolveReport` + the session-state holder

The diagnostics shape (seam gap 6: "a solve_report session record …
explicitly NOT a SolidCraft-style full diagnosis"; the h2h record:
"the three candidates' diagnostics surfaces are all rich enough to
feed them; SolidCraft's is the richest and is the one the seam will
see"):

```python
SolveReport(sketch_id="sk1", solver="solidcraft-solver@3b4db52",
            status="solved", dof=0,
            redundant=("k8",), conflicting=(), failed=(), detail="")
```

- `status: "solved" | "failed"` (the corpus envelope vocabulary,
  exact).
- `dof: int >= 0`; `redundant` / `conflicting` / `failed`: tuples of
  c_id strings — the named-constraint diagnostics lists, **as reported
  by the solver service** (empty lists are HONEST: PlaneGCS's
  structurally-clean numerical failure carries no named diagnostics —
  the report must not synthesize any).
- `solver: str` — the producing service's identity string (so a report
  is always attributable); `detail: str` — human-readable, may be
  empty.
- JSON form (pinned key order): `{"sketch_id", "solver", "status",
  "dof", "failed", "redundant", "conflicting", "detail"}`.
- **Session state, like selection** (binding): reports live in
  `doc.solve_reports` (a `SolveReports` holder: `set(report)`,
  `get(sketch_id)`, `all()`, `clear()`), are NEVER serialized, NEVER
  journaled, NEVER bump `doc_version`, and are NOT part of the
  transaction snapshot/rollback. A loaded document always starts with
  an empty report set. There are NO change events for reports in v3
  (the caller that ran the solve holds the return value; §7 records
  the limitation).

## 2. The `SketchTable` (journaled, like layers/blocks/layouts)

`doc.sketches` → `SketchTable`. Mutating methods require the open
transaction and journal their ops (the m2 §2.8 rules verbatim: full
reverse info, replay-safe, serializable). Reads are always legal.

| API | journal op | payload |
|---|---|---|
| `add(sketch_id, name=None, workplane=None)` | `add_sketch` | `{sketch_id, record}` (full record) |
| `remove(sketch_id)` | `remove_sketch` | `{sketch_id, record, index}` (the record + its position — the inverse re-adds byte-exactly AT THE SAME POSITION) |
| `set_props(sketch_id, name=…, workplane=…)` | `mutate_sketch` | `{sketch_id, changes}` (PRIOR values — the API records prior, so the pure inverse is the op itself) |
| `add_constraint(sketch_id, kind, refs, value=None, driven=False, c_id=None)` | `add_constraint` | `{sketch_id, constraint}` (full record) |
| `set_constraint(sketch_id, c_id, **changes)` | `mutate_constraint` | `{sketch_id, c_id, changes}` (PRIOR values; `value`, `driven`, `refs`, `kind` are all settable — every change is validated before any is applied, no partial apply) |
| `remove_constraint(sketch_id, c_id)` | `remove_constraint` | `{sketch_id, c_id, constraint, index}` (the record + its list position, for the inverse) |
| `add_junction(sketch_id, members, junction_id=None)` | `add_junction` | `{sketch_id, junction}` |
| `set_junction(sketch_id, junction_id, members=…)` | `mutate_junction` | `{sketch_id, junction_id, changes}` (PRIOR members — identity survives member growth, which is the point of the record) |
| `remove_junction(sketch_id, junction_id)` | `remove_junction` | `{sketch_id, junction_id, junction, index}` |

The remove ops' `index` (and the add ops' optional `index` on replay)
follow the M1 ENTITY-add precedent, not the layer/block one: insertion
order is serialization CONTENT for sketches, constraints and junctions
(no "0 first" convention to restore it implicitly), so undo of a
removal restores the record at its recorded position — undo must never
reorder content.

Semantics:

- **Removing a sketch leaves the geometry.** Sketch removal deletes the
  constraints and junctions (the sketch's own content); the referenced
  bcdoc entities are untouched document content. The M3 UX layer
  composes sketch-remove + entity-remove transactions when it wants
  CAD Sketcher's delete-sketch-deletes-geometry behavior; bcdoc does
  not decide that for it.
- **The dimension edit is the first-class operation** (the seam's
  demonstrated parametric loop): `set_constraint(sketch_id, "d1",
  value=40.0)` is ONE journal op whose undo restores exactly the prior
  value — undo granularity is per-constraint, never per-sketch.
- **Undo/redo/rollback** follow the m2 machinery exactly: snapshot
  restore covers the sketch table (bit-identical failed-transaction
  rollback), committed transactions push reversed-journal UndoGroups,
  and undo/redo themselves are committed transactions (doc_version
  bumps). Journal replay raises `JournalConflict` on any
  state mismatch (§5 guards apply in replay too, belt-and-braces).

## 3. Serialization — schema `bcdoc/3`

`serialize()` ALWAYS writes `bcdoc/3` (the v1→v2 precedent: the write
schema moves at the schema release; `load` keeps every older reader).
`load()` accepts `bcdoc/1`, `bcdoc/2` AND `bcdoc/3`; anything else raises
`SerializationError`.

- **v3 key order** (pinned; byte-stability contract unchanged —
  `load(serialize(doc)) → serialize()` is byte-identical, and v1/v2
  files upgrade deterministically): `schema, name, units, doc_version,
  next_handle, settings, layers, current_layer, text_styles,
  dim_styles, blocks, layouts, sketches, entities, undo, redo,
  selection` — `sketches` slots between `layouts` and `entities`
  (tables before entity content, like `blocks`).
- **v2 → v3 upgrade** (deterministic, in-place): `sketches = []`.
  Nothing else changes; a v2 file re-saves as v3 and v3→load→serialize
  cycles are byte-stable from the first upgrade. v1 files ride the
  existing v1→v2 upgrade and then gain `sketches = []`.
- **Journal op vocabulary grows by the nine sketch ops** (§2) — the
  serialized undo/redo stacks carry them; journal shape validation
  (the `_validate_group` rules) grows the nine op shapes with the
  same mandatory-key discipline as the existing ops. Older journals
  never contained sketch ops, so replay tolerance rules are
  unaffected.
- **Parse-time integrity (new, blocks-handle-collision precedent):**
  the sketches section is cross-validated against the payload's
  entity list — every `{"entity": …}` ref (constraints and junction
  members alike) must exist in `entities`, and slot refs must address
  line-kind entities. A payload referencing an absent entity fails
  `load` with `SerializationError`. This is safe to require because
  the table layer (§5) refuses dangling refs at every mutation, so no
  serialized v3 document from this implementation can carry one.
- The `_OP_KINDS` set, `SCHEMA` constant and required-keys tuple move
  with the schema; `SCHEMA = "bcdoc/3"` is the single write-source.

## 4. Document wiring

- `Document.sketches` → the `SketchTable` (property, like `layers`).
- `Document.solve_reports` → the `SolveReports` session holder (§1.5).
- `_snapshot_state` gains `sketches` (record copies) and `_restore_state`
  restores the table wholesale — the failed-transaction invariant
  ("content serialize()-bit-identical") covers sketches.
- `_rebuild` (the load path) adopts the parsed sketch records.
- The M1 `remove_entity` API gains a guard (§5.3) — the only M1/M2
  surface change in this contract.

## 5. Guards and integrity

1. **Dangling refs refused at mutation time.** Every table op that adds
   or rewrites refs (`add_constraint`, `set_constraint`,
   `add_junction`, `set_junction`) validates each `{"entity": …}` ref
   against the live document: unknown entity →
   `errors.DanglingSketchRef`; slot ref on a non-line entity →
   `ValueError`. Junction refs (`{"junction": …}`) must address a
   junction in the same sketch → `errors.JunctionNotFound`.
2. **Duplicate keys refused**: `DuplicateSketch` / `DuplicateConstraint`
   / `DuplicateJunction` (per-sketch uniqueness for the latter two).
   Missing keys: `SketchNotFound` / `ConstraintNotFound` /
   `JunctionNotFound`.
3. **`remove_entity` refuses while referenced** (BlockInUse precedent,
   composition rule): removing an entity that any constraint ref or
   junction member addresses raises `errors.EntityInUse`. The M3 UX
   layer composes remove-constraint-then-remove-entity (or
   remove-sketch) transactions; bcdoc never silently deletes
   constraints. The same guard fires as `JournalConflict` on the
   journal-replay remove path (corrupted/edited journals fail loudly;
   legal LIFO undo sequences never hit it — the constraint-removing
   group is always undone first).

## 6. Contract amendments (M1/M2 surfaces this changes)

- **m2 §2.7** — `serialize()` emits `bcdoc/3` (was: `bcdoc/2`);
  `load()` accepts `bcdoc/1`, `bcdoc/2`, `bcdoc/3` (was: 1 + 2). The
  pinned key order grows `sketches` after `layouts`. Byte-stability
  rules unchanged.
- **m2 §2.8** — the journal vocabulary gains the nine sketch op kinds
  (§2); all existing kinds unchanged.
- **m1 §3.2/§3.3 (as amended)** — `remove_entity` gains the
  `EntityInUse` guard (§5.3); no other entity-surface change.
- **m2 §15 (versioning)** — the extension version moves to `0.3.0`
  (manifest toml + the bcshell/bcio/bcagent/bcdoc package versions),
  preserving the exact pairing the prior contracts established
  ("Extension `0.2.0`; serialization `bcdoc/2`" — m2 §14; now
  "extension `0.3.0`; serialization `bcdoc/3`"). Release manifests are
  NOT touched by this lane (milestone releases own the
  `manifest-*.json` series).
- A pointer line goes into the m2 contract's §15 amendment log (the
  chain stays discoverable in both directions).

## 7. Explicitly out of scope (with reasons)

- **Any parametric-module code or solver integration** — M3 §6 items
  1–2 of the head-to-head record; gated on port-vs-FFI + the open
  (verify) gates; owned by the integration lane. The
  `modules/parametric` README gains a status pointer only.
- **Point-entity references as junction identity** (the seam gap-2
  alternative) — rejected: it would add solver-derived entities to the
  document store (display-sync surface) while lines still carry
  endpoint values, so sharing would remain coincident-by-value PLUS a
  redundant point entity. The junction map shares nothing and forces
  nothing.
- **Per-entity solver-param persistence** (seam gap 3) — explicitly
  NOT wanted per the m3-eval record; if incremental solving ever
  becomes real, a `param_ids` map INSIDE the SketchRecord (never on
  entities) is the recorded direction.
- **Kind vocabulary beyond the 15** (§1.2) — additive only, by a
  schema revision with evidence; not a runtime string.
- **A sketch rename op** — `sketch_id` is immutable and `name` is the
  display field; nothing in the demonstrated workflows needs identity
  rename, and it would touch every ref/journal payload for no
  measured gain.
- **Solve-report change events** — no `on_solve` callbacks in v3; the
  solve's caller holds the return value (§1.5). Recorded as a known
  limitation for the integration lane to revisit if polling proves
  insufficient.
- **Named-UCS workplanes, per-sketch entity sets, 3D-on-surface
  constraints** — later revisions, each with evidence; none is
  demonstrated by the committed record.

## 8. Amendment log

- (none yet)
