# M1 Module Contracts — cross-worker binding implementation spec

- **Status:** Binding for M1 implementation (walking skeleton). Supersedes nothing; specializes glossary §4 + document-model doc §3 to the v0 API surface.
- **Owner:** TL (integration); implementations owned per glossary §10
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding; §15 amendment)

## 1. Why this document exists

M1 is built by parallel workers (W1 commands/shell/drafting, W2 document/interchange,
W3 agent). Every cross-package name, signature and data shape used across package
boundaries is pinned HERE. If code disagrees with this file, this file wins until the
TL amends it. Amendments are appended to §14, never silently rewritten.

## 2. Package layout (source of truth = module directories)

The extension is ASSEMBLED from module-owned packages (never hand-edited in build/):

| Package | Source dir (repo root) | Owner | bpy dependency |
|---|---|---|---|
| `bcdoc` | `modules/document/bcdoc/` | W2 | NONE (pure Python — importable under pytest and in Blender) |
| `bccmd` | `modules/commands/bccmd/` | W1 | NONE |
| `bcdraft` | `modules/drafting/bcdraft/` | W1 | NONE |
| `bcshell` | `modules/shell/bcshell/` | W1 | bpy (Blender operators, UI, display sync) |
| `bcio` | `modules/interchange/bcio/` | W2 | NONE |
| `bcagent` | `modules/agent/bcagent/` | W3 | NONE (operates on `bcdoc` only — security boundary §10) |
| extension entry | `modules/shell/ext/blender_cad/` | TL | bpy |

Assembly: `scripts/build_extension.py` copies each package into
`build/blender_cad/` plus the extension entry files and writes
`dist/blender_cad-<version>.zip` (Blender extension archive: `blender_manifest.toml`
at zip root). Built artifacts are never committed (`.gitignore`).

Import model (binding):

- Packages import each other as TOP-LEVEL names (`from bcdoc import document`), never relative across packages.
- In Blender: the extension `__init__` inserts its own directory into `sys.path` (deduped) so top-level imports resolve.
- Under pytest: repo-root `conftest.py` inserts every `modules/*/` directory into `sys.path`.
- `bcdoc`, `bccmd`, `bcdraft`, `bcio`, `bcagent` MUST NOT import `bpy` — enforced by `scripts/check_module_boundaries.py --imports` (M1 addition) and by tests importing them outside Blender.
- `bcshell` may import `bpy` and all other packages.

## 3. `bcdoc` — document model v0 (W2)

Module files: `entities.py`, `document.py`, `transaction.py`, `undo.py`, `selection.py`, `serialize.py`, `units.py`, `__init__.py`.

### 3.1 Entities (all dataclass-like, plain Python)

```python
class Entity:  # base
    id: str            # uuid4 hex, generated at creation, immutable, never reused
    handle: int        # per-document monotonic handle (DWG-style); assigned by Document on add
    layer: str = "0"
    color: int | None = None     # ACI index; None = ByLayer
    linetype: str = "ByLayer"
    @property kind -> str        # "line" | "circle" | "arc"

class Line(Entity):   p1: tuple[float,float,float]; p2: tuple[float,float,float]
class Circle(Entity): center: tuple; radius: float
class Arc(Entity):    center: tuple; radius: float; start_angle: float   # degrees, CCW about +Z
                      end_angle: float
```

- Geometry is stored in document/world coordinates, meters-free "drawing units" (v0 has no unit conversion; units metadata is display-only).
- Entities are immutable-ish: transforms create/apply in place inside transactions only (Document APIs are the only legal mutation path).

### 3.2 Document

```python
class Document:
    name: str
    units: dict            # {"length": "mm", "angle": "deg"} (display metadata only)
    doc_version: int       # monotonic; bumped by every COMMITTED transaction (glossary §6)
    selection: SelectionState
    layers: list[str]      # existing layer names; "0" always present
    def add_entity(e) -> Entity          # assigns handle, stores; requires open transaction
    def get(eid) -> Entity
    def remove(eid) -> Entity
    def entities() -> list[Entity]        # insertion order
    def count_by_kind() -> dict
    def transaction(label: str) -> Transaction   # context manager
    def undo() -> bool; def redo() -> bool      # one committed tx each; False when empty
    def undo_depth() -> int; def redo_depth() -> int
    def serialize() -> str               # stable JSON (§3.5 schema)
    @staticmethod load(text: str) -> Document
```

- `Document()` starts with layer "0" and `doc_version == 0`.
- Mutating APIs called OUTSIDE a transaction raise `bcdoc.errors.NoOpenTransaction` (enforces "transactions only" invariant).

### 3.3 Transaction + undo journal

```python
class Transaction:   # context manager from Document.transaction(label)
    @property committed: bool
    # on __exit__(no exception): apply journal to undo stack, doc_version += 1, push UndoGroup
    # on exception: full rollback (entity store restored), doc_version unchanged
class UndoGroup: label: str; doc_version: int; entries: list[Op]   # reversed-op journal
```

- Undo re-applies the reversed journal as a NEW committed transaction (doc_version bumps — monotonicity rule) and pushes the redo group.
- Every committed transaction emits a `bcdoc.events` callback list (see §3.6).

### 3.4 Selection (document-owned session state)

```python
class SelectionState:
    epoch: int                 # selection_epoch; bumps on every change (glossary §6)
    ids: frozenset[str]
    def set(ids); def add(ids); def remove(ids); def clear()
```

Selection changes NEVER bump doc_version.

### 3.5 Serialization schema (stable, versioned)

`serialize()` → JSON: `{"schema": "bcdoc/1", "name": …, "units": {...}, "doc_version": int,
"next_handle": int, "layers": [...], "entities": [{"kind", "id", "handle", "layer", "color",
"linetype", ...geometry...}], "undo": {...}}`. `load()` accepts exactly `bcdoc/1` (raises
`bcdoc.errors.SerializationError` otherwise). Round-trip identity is byte-stable for
untouched documents (entity order preserved). Undo/redo journals are serialized too
(documents survive save/reopen with undo depth intact — M1 nicety, not a hard M0 doc
requirement; if journal serialization proves bulky, v0 may persist undo depth as empty
and it is recorded as a loss).

### 3.6 Events

`document.on_change: list[callable]` — called after every committed transaction with
`("doc", doc_version)`; `document.on_select: list[callable]` with `("select", epoch)`.
bcshell subscribes for display sync; bcagent subscribes for event plumbing.

## 4. `bccmd` — command registry + prompt state machine (W1)

Module files: `spec.py` (command spec + prompt model), `state.py` (machine), `registry.py`, `input.py` (parsing), `history.py`, `__init__.py`.

### 4.1 Input model — three sources, one machine

The state machine consumes `InputValue`s from any provider (interactive shell operator, scripted tests, agent adapter later):

```python
@dataclass
class Point:  x: float; y: float; z: float = 0.0
@dataclass
class InputValue:      # one resolved user input
    kind: str          # "point" | "distance" | "angle" | "keyword" | "string" | "selection"
    value: object      # Point | float | str | list[str] (selection ids)
    raw: str = ""      # original text, for history
class Request:         # what the machine asks the provider for next
    kind: str          # same kinds
    prompt: str        # display text, e.g. "LINE Specify first point:"
    options: list[str] # accepted keywords, e.g. ["Close", "Undo"]
    default: object | None
class Cancelled(Exception)      # user aborted (Esc) — machine returns cleanly
```

### 4.2 Command spec

```python
class CommandSpec:
    name: str                    # canonical, upper-case, e.g. "LINE"
    aliases: list[str]           # e.g. ["L"]; global alias map must stay collision-free
    run: callable(ctx: CommandContext, run: Runner) -> CommandResult
class CommandContext:           # provided by the host
    document: bcdoc.document.Document
    view: ViewBridge | None      # None in headless tests
    history: History
    feedback: callable(str)      # host message sink (command line / status bar)
class Runner:                   # the prompt-loop driver passed INTO run()
    def ask(req: Request) -> InputValue      # blocks for next input (raises Cancelled)
    def ask_until(req, validate) -> InputValue
class CommandResult:
    status: str                 # "ok" | "cancelled"
    summary: str                # one-line English result for history/feedback
    created: list[str]          # entity ids
    modified: list[str]
    removed: list[str]
```

Binding rule: **commands mutate the document ONLY through `ctx.document`
transactions** — same rule as agents (glossary §6).

### 4.3 Registry

```python
class Registry:
    def register(spec: CommandSpec) -> None    # duplicate name/alias raises
    def lookup(token: str) -> CommandSpec | None   # name-or-alias, case-insensitive
    def names() -> list[str]
    def run_command(ctx, name, provider: callable|None) -> CommandResult
```

`provider` supplies `Request -> InputValue` (tests script it; bcshell feeds it from
modal-operator events). The skills registration hook (glossary §4 inversion note) is a
`register_hook(name, callable)` on the registry — present but unused at M1.

### 4.4 Input parsing (`bccmd.input`) — AutoCAD-familiar text forms

- `"12,34"` → absolute Point(12, 34, 0); `"12,34,5"` → 3D
- `"@3,4"` → relative to the last point (ctx tracks `last_point`)
- `"@5<30"` → polar: distance 5 at 30° from last point
- `"42"` in a distance request → 42 drawing units; in an angle request → 42 degrees
- keyword matching is prefix-insensitive per AutoCAD convention where unambiguous (e.g. `C` = Close, `U` = Undo within LINE)

## 5. `bcdraft` — drafting commands (W1)

Implements (M1 scope): `LINE` (chained, `Close`/`Undo` options), `CIRCLE` (`Radius`/
`Diameter`), `ARC` (3-point; Start-Center-End), `ERASE` (selection), `MOVE`, `COPY`,
`ROTATE`, `SCALE` (base point + typed/mouse displacement), `UNDO`/`REDO` (document
stack), `LAYER`? — NO: layer management is M2; M1 only reads layer "0"/current-layer
metadata. Each command is a `CommandSpec` in `modules/drafting/bcdraft/commands_*.py`,
registered through `bcdraft.register_all(registry)`.

Geometry updates go through `ctx.document.transaction(...)`. Transforms:
move/rotate/scale recompute entity geometry in place (line endpoints, circle center,
arc center+angles) — analytic, no kernel dependency (kernel adoption is M3; ADR-0002).

## 6. `bcshell` — Blender integration (W1)

### 6.1 Extension lifecycle (entry `modules/shell/ext/blender_cad/__init__.py`, TL-owned)

`register()`: sys.path bootstrap → import bcshell → `bcshell.register()` (imports all
packages, registers operators/UI/keymaps/handlers, ensures session document).
`unregister()`: reverse, no leftover draw handlers or keymaps (TP-CAT-06 clean
unload). Extension id: `blender_cad`; schema version 1 manifest with
`blender_version_min = "5.2.0"` (tested build: Blender 5.2.2 LTS — pinned in the M1
manifest).

### 6.2 Session + display sync

```python
def active_document() -> bcdoc.document.Document   # one Document per session (v0)
def ensure_workspace() -> bpy.types.Workspace      # workspace "BlenderCAD", created if absent
def sync_display(doc)                              # rebuild collection "BlenderCAD" display
```

- Workspace "BlenderCAD": 3D viewport area in top orthographic view + command dock (N-panel + command-line operator) + status-bar prompt line. Created by operator `bcshell.ops.workspace_open` (id `bcshell.workspace_open`) — NOT at register time (register stays side-effect-free for clean unload).
- Display sync is one-way derived (document → scene) per the binding invariant; display objects carry `["bcdoc_id"] = entity.id`. Collection name `"BlenderCAD"`.
- Persistence: the document is stored as JSON in `bpy.data.texts["blender_cad_document.json"]` (updated on every committed transaction); `load_post` handler restores the document on file reopen. Native save (`Ctrl+S`) therefore persists CAD documents — no custom file format at M1.
- Mouse point input: viewport click → ray ∩ XY plane (z=0) via `bcshell.pick.point(event, context)`; rubberrband previews via `gpu` draw-handler during the modal command operator.
- Command line UX: operator `bcshell.cmdline` (id `bcshell.cmdline`) opens the typed command entry; keymap: `Ctrl+Space` (Blender main window, all spaces) — removable in extension preferences. Status bar (workspace header) shows the active prompt + doc status.
- Modal command operator `bcshell.command_run` wraps the registry runner: feeds mouse/keyboard events into the provider, renders rubberrband, `Esc` cancels (Cancelled), typed text triggers coordinate/keyword parsing.

### 6.3 Blender-side operators (M1)

`bcshell.workspace_open`, `bcshell.cmdline`, `bcshell.command_run`, `bcshell.dxf_import` (invoke file selector → bcio), `bcshell.dxf_export`, `bcshell.doc_save_json`, `bcshell.doc_load_json`, `bcshell.undo`, `bcshell.redo`, `bcshell.doc_info` (panel refresh).

## 7. `bcio` — DXF import/export (W2)

- In-product writer/reader: `bcio.dxf_minimal` — pure-Python **DXF R12 ASCII** for the v0 entity set (LINE/CIRCLE/ARC + LAYER table + ACI colors + preserved handles via group code 5). No third-party dependency inside the shipped extension.
- Conformance oracle: `bcio.ezdxf_bridge` — when `import ezdxf` succeeds (test env / user site), import/export through ezdxf and audit. `bcio.export_dxf(path, doc)` prefers the ezdxf bridge, falls back to dxf_minimal; `bcio.import_dxf(path)` likewise.
- Handle rule (document-model doc §3.1): handles read from DXF are preserved into the document's per-document handle space; export maps back; collisions re-allocate.
- Round-trip loss ledger (ADR-0003): every unsupported in-file entity is recorded in `bcio.loss_ledger.LossLedger` entries (kind, dxf_type, reason) — import NEVER silently drops content.
- API: `export_dxf(path: str, doc) -> dict` (stats), `import_dxf(path: str, doc=None) -> (Document, dict)`.

## 8. `bcagent` — CAD tool adapter v0 (W3)

Implements the in-process half of `cad-tool-contract/v1` (JSON-RPC mapping is
normative for in-process use — contract §1):

```python
class CadToolAdapter:
    CONTRACT_VERSION = "cad-tool-contract/v1"
    def capabilities() -> dict            # ONLY tools actually implemented (honest advertisement)
    def dispatch(request: dict) -> dict   # {"tool", "session_token", "args"} -> envelope
class SessionManager: modes read-only|propose|approve|autonomous; permission classes (glossary §6); tokens
```

M1 tool subset (each returns the contract §2 envelope, honors `base_doc_version`,
transactional tools commit as one undo step):
`cad.doc.info`, `cad.doc.status`, `cad.doc.checkpoints(list)` (read-only at M1),
`cad.select.get/set/count/filter`, `cad.geometry.create` (line/circle/arc),
`cad.geometry.get`, `cad.geometry.query` (length/radius/area basics),
`cad.geometry.transform` (move/rotate/scale), `cad.layers.list`,
`cad.io.export_dxf`, `cad.io.import_dxf`, `cad.system.capabilities`.
Error model per contract §3 (`CAD_E_*` codes). `cad.system.preview`/`commit`
batching: NOT advertised at M1 (honest capabilities) — planned M5.

Binding security boundary: `bcagent` imports `bcdoc` (and `bcio` for cad.io) ONLY — importing `bpy` or `bcshell` is a boundary violation and there is a test asserting it (module-boundary + no-bpy check).

## 9. `modules/testing` — cross-module suites (TL)

- `modules/testing/blender-regression/` — TP-CAT-06: native Blender function battery on the pinned build (load default scene, add/scale/render-lite ops, save/reopen .blend), with and without the extension loaded; asserts zero startup regressions and clean unload.
- `modules/testing/roundtrip/` — TP-CAT-04 precursor: DXF round-trip (document → DXF → document → compare; + ezdxf-written fixtures → import → export → ezdxf re-read).
- `modules/testing/functional/` — TP-CAT-01 cross-module walkthroughs: command-line sessions (scripted provider) creating LINE/CIRCLE/ARC + modify ops through the registry.
- `modules/testing/agent-contract/` — TP-CAT-07 precursor: adapter envelope/error/permission tests (pure Python).
- In-Blender acceptance battery: `modules/testing/blender/acceptance_m1.py` (run via `blender --background --python`) — installs the built extension from `dist/`, opens the workspace, drives LINE/CIRCLE/ARC + modifications through the command interface, saves/reopens, DXF round-trips, native ops still work. Writes `modules/testing/blender/acceptance_m1_result.json`.

## 10. Testability rules (binding)

1. `bcdoc`, `bccmd`, `bcdraft`, `bcio`, `bcagent` tests run under plain pytest WITHOUT Blender (conftest sys.path bootstrap). CI runs them on every push.
2. bpy-touching tests live under `modules/testing/blender*` and `modules/shell/tests/`, are run against the pinned Blender build in the dev environment (and a CI container from M2), and MUST leave evidence artifacts (§9 acceptance result JSON + logs).
3. No test may mutate files outside the repo (`tmp_path` only). DXF fixtures are self-authored (licensing-clean; test-plan §8).

## 11. M1 acceptance mapping (from the operator directive)

| Acceptance requirement | Evidence |
|---|---|
| Extension loads into the selected Blender build | acceptance_m1.py: extension installed via extension-repo from dist/*.zip, enabled, import OK |
| CAD workspace opens | workspace_open operator creates/activates "BlenderCAD" workspace |
| LINE, CIRCLE, ARC work through the command interface | acceptance battery drives bccmd Registry through the SAME prompt state machine the UI uses (scripted provider), asserting resulting entities |
| Basic modifications work | MOVE/ERASE/COPY/ROTATE/SCALE through the same interface |
| Documents survive save/reopen | .blend save (JSON text block) → new Blender process reopens → document identical (doc_version/entities) |
| Real DXF fixture passes initial round-trip | self-authored fixture with line/circle/arc/layers → export → ezdxf audit → import → compare |
| Native Blender functions remain usable | TP-CAT-06 battery: native ops before/after extension load; clean unload |
| Upstream compatibility smoke test now | TP-CAT-11: zcode drift check + the W3 spike (docs/20-agent/zcode-runtime-spike-m1.md) runs the pinned runtime entry points |

## 12. Versioning

Extension version starts `0.1.0` (manifest `blender_manifest.toml` + release manifest
`0.2.0-m1` records it). `bcdoc` serialization schema `bcdoc/1`. cad contract version
string exactly `cad-tool-contract/v1` with advertised `capabilities.version = "1.0-m1"`
(honest: the v1 tool SUBSET is implemented, not all 62 tools — M5 completes it).

## 13. What is explicitly NOT claimed at M1

Precision input (osnap/ortho/polar/tracking), dimensions/text/hatches, layouts,
blocks, xrefs, DWG, IFC, kernel-backed geometry, the live sidecar process, skill
execution — all remain `planned` in the inventory; nothing flips without tests + evidence.

## 14. Amendment log

- (none)
