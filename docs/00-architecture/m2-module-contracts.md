# M2 Module Contracts — cross-worker binding implementation spec

- **Status:** Binding for M2 implementation (drafting core). Extends
  `m1-module-contracts.md` (still binding for unchanged surfaces); where the
  two disagree, THIS file wins for M2 scope and §14 of the M1 document wins
  for M1 scope. Amendments are appended to §15 here, never silently rewritten.
- **Owner:** TL (integration); implementations owned per glossary §10
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding; §15)

## 0. M2 scope (operator-directed acceptance)

M2 delivers, with executable evidence (handoff §2 + ADR-0008):

- **A. Precision input** — coordinate grammar integrated into real command
  execution, numeric distance/angle entry with validation, cancellation and
  error recovery; direct-distance entry; ORTHO; grid snap; running + one-shot
  osnaps for the P0 mode set (ENDPOINT, MIDPOINT, INTERSECTION, CENTER,
  QUADRANT, TANGENT, PERPENDICULAR); UNITS settings.
- **B. Layers and blocks** — full layer table (properties, states, current
  layer), entity property overrides, block definitions + INSERT references,
  redefinition, transforms/selection/persistence consistency.
- **C. Annotations and dimensions** — DIMLINEAR, DIMALIGNED, dimension
  associativity, DIMSTYLE, TEXT, MTEXT, STYLE with units-aware formatting.
- **D. Layouts** — layout management, model vs paper space, MSPACE/PSPACE,
  viewport creation, persistence + DXF subset for the supported set.
- **Drafting core additions** (TP-CAT-01 P0 subset, analytically
  implementable without the M3 kernel): PLINE (+arc segments, +width),
  RECTANG, POLYGON, POINT, XLINE, RAY, ELLIPSE, CIRCLE 2P/3P, MIRROR, OFFSET,
  ARRAYRECT, BREAK, JOIN, EXPLODE, STRETCH, MATCHPROP, SELECT modes,
  noun-verb selection, repeat-last, SETVAR/GETVAR, autocomplete suggestions.

Explicitly deferred with reasons (ADR-0008): TRIM/EXTEND/FILLET/CHAMFER,
PEDIT, HATCH, SPLINE, grip-mode cycling, transparent commands, right-click
modes, xrefs, PDF publish — kernel/GUI-bound or P1/P2 per inventory.

## 1. Package layout (M2 additions)

| Package | Source dir | Owner | bpy |
|---|---|---|---|
| `bcdoc` v2 | `modules/document/bcdoc/` | W2 (B1) | none |
| `bccmd` v2 | `modules/commands/bccmd/` | W1 (A) | none |
| `bcdraft` v2 | `modules/drafting/bcdraft/` | W1 (A: precision; D: drafting core) | none |
| `bcdraw` **NEW** | `modules/drawings/bcdraw/` | W1 (C) | none |
| `bcio` v2 | `modules/interchange/bcio/` | W2 (B2) | none |
| `bcshell` v2 | `modules/shell/bcshell/` | W1 (S) + TL | bpy |
| `bcagent` v2 | `modules/agent/bcagent/` | W3 surface kept honest by TL | none |

Dependency direction (binding; enforced by `scripts/check_module_boundaries.py`):

- `bcdoc` imports nothing product-internal.
- `bccmd` imports `bcdoc` only.
- `bcdraft` imports `bcdoc`, `bccmd`.
- `bcdraw` imports `bcdoc`, `bccmd`, `bcdraft`.
- `bcio` imports `bcdoc` (ezdxf optional at runtime).
- `bcagent` imports `bcdoc`, `bcio` only.
- `bcshell` imports everything.

Import model unchanged: top-level names; pytest via root `conftest.py`;
in Blender via the extension `sys.path` bootstrap. `bcdraw` is added to
`scripts/build_extension.py` `PACKAGES` (before `bcshell`).

## 2. `bcdoc` v2 (W-B1) — document model upgrade

New module files: `layers.py`, `blocks.py`, `layouts.py`, `settings.py`,
`styles.py`. Existing files extended: `entities.py`, `document.py`,
`transaction.py`, `undo.py`, `serialize.py`, `errors.py`, `__init__.py`.

### 2.1 Entity framework generalization

`PROPERTY_FIELDS = ("layer", "color", "linetype", "lineweight", "space")`.

`Entity` base gains:

- `lineweight: float | None = None` — millimeters; `None` = ByLayer.
- `space: str = "MODEL"` — `"MODEL"` or a layout name (paper space).
- color semantics: `None` = ByLayer, `0` = ByBlock (valid only for entities
  inside block definitions; resolved against the insert at display/interchange).

Geometry fields become per-kind with explicit coercers (single registry in
`entities.py`, used by `set_field`, `to_json_dict` and `serialize`):

| kind | class | geometry fields (order = serialization order) |
|---|---|---|
| line (M1) | `Line` | p1, p2 |
| circle (M1) | `Circle` | center, radius |
| arc (M1) | `Arc` | center, radius, start_angle, end_angle |
| point | `Point` | position |
| polyline | `Polyline` | vertices (point-list), bulges (float-list), widths (width-list), closed (bool) |
| ellipse | `Ellipse` | center, major_axis (point), ratio, start_angle, end_angle (full ellipse: 0, 360) |
| xline | `Xline` | p1, p2 (infinite through both) |
| ray | `Ray` | p1, p2 (infinite beyond p2) |
| text | `Text` | position, height, rotation, content (str), style (str), justification (str: "LEFT"\|"CENTER"\|"RIGHT") |
| mtext | `Mtext` | position, width, content (str), style (str) |
| dim | `Dim` | dim_type (str "linear"\|"aligned"), p1, p2, angle, offset_point, measured_id (str), measurement (float), text_override (str), style (str), text_position (point or None) |
| insert | `Insert` | name (str), position, scale (point, default (1,1,1)), rotation |
| viewport | `Viewport` | center, view_height, p1, p2, locked (bool) |

Coercer kinds: `point` (normalize_point), `float`, `str`, `bool`,
`point_list`, `float_list`, `width_list` (list of `[start, end]` float pairs).
`to_json_dict` emits geometry in the fixed field order above; lists of tuples
become lists of lists. `entity_from_dict` validates per coercer.

`polyline` bulge convention (binding): AutoCAD bulge = `tan(Δ/4)`, positive =
CCW arc from vertex i to vertex i+1; `widths[i] = [start_width, end_width]`
for the segment leaving vertex i. Polyline vertices are 3-tuples.

### 2.2 Layer table (`layers.py`)

```python
class LayerRecord:
    name: str
    color: int = 7            # ACI
    linetype: str = "Continuous"
    lineweight: float | None = None   # mm; None = default
    on: bool = True           # False = hidden (still hit-testable)
    frozen: bool = False       # excluded from regen + hit-testing
    locked: bool = False      # visible, selectable, NOT modifiable
    plot: bool = True

class LayerTable:              # ordered; "0" first, always present
    names() -> list[str]
    get(name) -> LayerRecord | None
    add(name, **props) -> LayerRecord            # requires open tx (journaled)
    set_props(name, **changes) -> LayerRecord    # requires open tx (journaled)
    remove(name)                                 # tx; guards: != "0", no entities on it
```

- `Document.layers` changes type `list[str]` → `LayerTable` (M1 call sites in
  bcio/bcagent are refactored by W-B1/W-B2; `update_entity` layer auto-create
  keeps working through `layers.add`).
- Current layer is the `CLAYER` setting (§2.5); `Document.current_layer`
  property reads it with fallback `"0"` if missing.
- Semantics enforcement is at consumers (commands/sync/osnap): OFF ⇒ hidden
  but selectable/snappable is permitted headlessly; FROZEN ⇒ hidden AND
  excluded from selection + osnap; LOCKED ⇒ modify commands reject with a
  clear prompt error ("N entity(ies) on locked layer — skipped").

### 2.3 Blocks (`blocks.py`)

```python
class BlockDefinition:
    name: str; base_point: tuple; handle: int
    entities: list[Entity]     # owned copies; NOT in the doc entity store

class Document:
    blocks() -> list[str]
    add_block(name, base_point, entities) -> BlockDefinition   # tx; copies entities
    block(name) -> BlockDefinition          # KeyError -> errors.BlockNotFound
    redefine_block(name, entities, base_point=None)            # tx; refs update by name
    remove_block(name)                                         # tx; errors.BlockInUse if refs
    block_ref_ids(name) -> list[str]                           # insert entity ids
```

- `add_block` COPIES the passed entities (deep copy via `entity.copy()`),
  strips their `space` (set to `"MODEL"` inside the definition), keeps
  layer/color/linetype/lineweight (ByBlock color 0 allowed for members).
- The definition handle comes from the document handle space (low handles
  reserved for tables are respected by the existing allocator).
- Undo journal ops: `add_block`, `remove_block`, `redefine_block` (with full
  entity dict snapshots — journal replay rebuilds definitions).
- Serialization: `"blocks": [{"name", "base_point", "handle", "entities": [..]}]`.

`insert` entities reference definitions BY NAME; redefinition therefore
updates every reference automatically (display regenerates; round-trips keep
handles on references).

### 2.4 Layouts (`layouts.py`)

```python
class LayoutRecord:
    name: str; page_width: float = 420.0; page_height: float = 297.0
    paper_units: str = "mm"

class Document:
    layouts() -> list[str]
    add_layout(name, page_width=420.0, page_height=297.0) -> LayoutRecord  # tx
    layout(name) -> LayoutRecord                 # errors.LayoutNotFound
    rename_layout(old, new) / remove_layout(name) / reorder_layout(name, index)   # tx
    current_space: str                            # "MODEL" | layout name (SESSION state)
    set_current_space(name)                       # validates; "MODEL" resets to model space
    entities_in_space(name) -> list[Entity]        # MODEL or a layout name
```

- Entity `space` field routes entities: `"MODEL"` or a layout name. Entities
  referencing a removed layout are an invariant violation — `remove_layout`
  refuses while entities live in that space (clear error message).
- `current_space` is SESSION state (like selection): NOT serialized, NOT
  journaled; documents always load in `"MODEL"`. Documented divergence from
  DXF (which persists active layout) — recorded in the loss ledger on export.
- Viewports are `viewport` entities whose `space` is the layout they belong
  to. `center`/`view_height` describe the MODEL view; `p1`/`p2` the paper
  rect corners.

### 2.5 Settings / system variables (`settings.py`)

```python
SETTING_DEFS: dict[str, {"type", "default", "help", "choices"?}]
class Settings:            # typed dict; unknown name raises errors.UnknownSetting
    get(name); set(name, value)   # type-validated + choices-validated
    to_json() / from_json()
Document.settings: Settings
```

M2 registry (names are binding — they mirror AutoCAD sysvars):

| name | type | default | notes |
|---|---|---|---|
| CLAYER | str | "0" | current layer (must exist when used) |
| OSMODE | int | 55 | bitmask: 1 END, 2 MID, 4 CEN, 16 QUA, 32 INT, 128 PER, 1024 TAN; 0 = none |
| ORTHOMODE | int | 0 | 0/1 |
| SNAPMODE | int | 0 | grid snap on/off |
| SNAPUNIT | float | 1.0 | rectangular grid snap spacing (drawing units) |
| GRIDMODE | int | 0 | display grid toggle (shell-side) |
| GRIDUNIT | float | 10.0 | display grid spacing |
| APERTURE | float | 0.5 | osnap aperture in DRAWING units (zoom-scaled presentation is later GUI work) |
| DYNMODE | int | 3 | dynamic input toggle (3 on, 0 off) |
| PICKFIRST | int | 1 | noun-verb selection |
| TILEMODE | int | 1 | 1 = model space active |
| INSUNITS | int | 0 | machine units, DXF $INSUNITS codes (0 unitless, 1 inches, 2 feet, 4 mm, 5 cm, 6 m …) |
| LUNITS | int | 2 | length display format (2 decimal) — M2 formats decimal; other codes accepted, formatted decimal (documented) |
| LUPREC | int | 4 | length display precision |
| AUNITS | int | 0 | angle display format (decimal) — same note |
| AUPREC | int | 0 | angle display precision |
| TEXTSTYLE | str | "Standard" | current text style |
| DIMSTYLE | str | "Standard" | current dimension style |
| LTSCALE | float | 1.0 | linetype scale (stored; display application is M3) |

Undo policy exception (binding, documented): **settings are document state
that is persisted but NOT journaled** — UNDO does not revert sysvars (matches
AutoCAD for out-of-command changes). Everything else (entities, layers,
blocks, layouts, styles) stays transactional + journaled.

### 2.6 Styles (`styles.py`)

```python
class TextStyleRecord: name; height: float = 2.5; width_factor: float = 1.0
class DimStyleRecord:
    name; dimscale: float = 1.0; dimtxt: float = 2.5; dimasz: float = 2.5
    dimexo: float = 0.625; dimexe: float = 1.25
class Document:
    text_styles() / add_text_style(name, ...) / text_style(name)
    dim_styles() / add_dim_style(name, ...) / dim_style(name)
    # "Standard" always present in both; current style = TEXTSTYLE / DIMSTYLE setting
```

Style table changes are journaled ops (`add_text_style`, `mutate_text_style`,
`remove_text_style`, same for dim styles); serialized as
`"text_styles": [...]`, `"dim_styles": [...]`.

### 2.7 Serialization — schema `bcdoc/2`

`serialize()` emits `bcdoc/2`:

```json
{"schema": "bcdoc/2", "name", "units", "doc_version", "next_handle",
 "settings": {...}, "layers": [{name, color, linetype, lineweight, on, frozen, locked, plot}],
 "current_layer": "...", "text_styles": [...], "dim_styles": [...],
 "blocks": [{"name", "base_point", "handle", "entities": [...]}],
 "layouts": [{"name", "page_width", "page_height", "paper_units"}],
 "entities": [{..., "lineweight": null, "space": "MODEL"}],
 "undo": {...}, "redo": {...}, "selection": {...}}
```

- `load()` accepts BOTH `bcdoc/1` (upgrade path: layer names → default records,
  settings defaults, no blocks/layouts/styles, entities get
  `lineweight=None`, `space="MODEL"`) and `bcdoc/2`. Anything else raises
  `SerializationError`.
- Byte-stability: v2 round-trip `load(serialize(doc))` → `serialize()` is
  byte-identical (v1 files upgrade deterministically: v1→load→serialize is
  byte-stable across repeated cycles).
- Undo/redo journals serialize the new op kinds; v1 journals (add_layer by
  bare name) replay tolerantly (missing props → defaults).

### 2.8 Transaction / journal extensions

New journal op kinds (each journaled with full reverse info, replay-safe,
serializable): `add_layer {name, props}`, `remove_layer {name, record}`,
`mutate_layer {name, changes}`, `add_block`, `remove_block`, `redefine_block`,
`add_layout`, `remove_layout`, `rename_layout {old, new}`,
`reorder_layout {name, old_index}`, `add_text_style`/`remove_text_style`/
`mutate_text_style`, `add_dim_style`/`remove_dim_style`/`mutate_dim_style`.

`Document._snapshot_state`/`_restore_state` cover all new tables (atomic
rollback for failed transactions).

## 3. `bccmd` v2 (W-A) — input model additions

- `InputValue.source: str = "typed"` — `"typed"` (keyboard/script) vs
  `"mouse"` (viewport pick). Typed input NEVER passes through osnap/ortho/
  grid resolution (AutoCAD rule); mouse input ALWAYS does.
- `CommandContext.pointer: Point | None = None` — last known cursor position
  (updated by bcshell); consumed by DDE + ortho direction when no drag
  vector exists.
- `parse()` gains, for `request.kind == "point"` ONLY, in the not-numeric
  branch, AFTER command-option matching:
  **osnap one-shot tokens** — `END|ENDP→ENDPOINT, MID→MIDPOINT, CEN→CENTER,
  QUA→QUADRANT, INT→INTERSECTION, TAN→TANGENT, PER→PERPENDICULAR`
  (comma-lists allowed, e.g. `"END,MID"`) → `InputValue(kind="keyword",
  value="osnap:ENDPOINT", ...)`. `_common.ask_point` consumes the keyword,
  records the pending one-shot on `ctx.pending_osnap` (new field) and re-asks.
- `parse()` gains, for `request.kind == "point"` with a plain number token:
  `InputValue(kind="distance", ...)` is returned when `ctx.last_point`
  exists (direct distance entry); `require_point`/`ask_point` convert it via
  `bcdraft.precision.dde_point` (see §4). Without a last point it stays an
  error ("A point needs two coordinates").
- `Registry.suggestions(prefix, limit=8) -> list[tuple[str, str]]` —
  `(name, help)` pairs matching name or alias (case-insensitive prefix
  match; exact-prefix matches first, then contains); used by autocomplete +
  tests.
- Empty command token at the shell entry repeats the last command
  (`History.last_command()`, ux-spec §3.2): implemented in bcshell's cmdline
  path + `bcshell.session.run_command` (not in Registry.run_command).

## 4. `bcdraft` v2 — precision input engine (W-A)

New files: `precision.py`, `commands_precision.py` (settings/sysvar
commands). Extended: `_common.py` (resolution hook), `geometry.py` (shared
2D math only — W-D co-owns geometry.py for drafting math; W-A adds snap math
in `precision.py`).

```python
#: mode name -> OSMODE bit (subset of the AutoCAD bit layout, binding)
OSMODE_BITS = {"ENDPOINT": 1, "MIDPOINT": 2, "CENTER": 4, "QUADRANT": 16,
               "INSERTION": 64, "PERPENDICULAR": 128, "TANGENT": 1024}
OSMODE_NONE = 0

def parse_osnap_tokens(text) -> list[str]     # [] when nothing matches
def running_modes(doc) -> list[str]           # from doc.settings["OSMODE"]

@dataclass
class SnapResult:
    point: Point; mode: str | None; entity_id: str | None

def snap_candidates(doc, modes, cursor: Point, aperture: float,
                    from_point: Point | None = None) -> list[SnapResult]
    # per mode: compute ALL candidates, then rank by |candidate - cursor|;
    # entities on FROZEN layers and entities in OTHER spaces than
    # doc.current_space are excluded; insert entities contribute their
    # TRANSFORMED members (ByBlock members resolve against the insert);

def resolve_point(doc, raw: Point, last_point: Point | None = None,
                  one_shot: list[str] | None = None,
                  pointer: Point | None = None) -> SnapResult
    # chain (binding order): grid snap -> ortho -> osnap.
    # grid: SNAPMODE on -> nearest GRIDUNIT lattice point (both axes) to raw
    # ortho: ORTHOMODE on and last_point -> project raw onto the H/V axis
    #       through last_point; direction taken from pointer when raw == last_point
    # osnap: one_shot (single use) else running_modes; aperture from settings;
    #       TANGENT/PERPENDICULAR use last_point as the from-point
    # marker data (mode/entity_id) is returned for UI presentation.

def dde_point(last_point: Point, distance: float, pointer: Point | None,
              doc) -> Point
    # direct distance entry: direction = last_point -> pointer (angle 0 when
    # pointer is None); ORTHOMODE snaps the direction to the nearest 90°.
```

Integration (binding): `bcdraft/_common.py::ask_point` — for every accepted
point `InputValue` with `source == "mouse"`, run
`resolve_point(ctx.document, value.value, ctx.last_point, ctx.pending_osnap,
ctx.pointer)` and use the resolved point (one-shot consumed here). For
`value.kind == "distance"` at a point request with `ctx.last_point`, run
`dde_point`. Typed points pass through UNCHANGED (deterministic scripted
tests). This single hook applies to every M1+M2 command without touching each
command body.

`commands_precision.py` registers: `SETVAR` (`?` lists all defs+values;
`NAME` + value prompt), `GETVAR`, `OSNAP` (`"none"|"off"` clears; mode list
sets running OSMODE; bare Enter shows current), `ORTHO` (toggle), `SNAP`
(toggle), `GRID` (toggle), `UNITS` (walks LUNITS/LUPREC/AUNITS/AUPREC/
INSUNITS with prompts + defaults), `DYNAMICINPUT` (alias `DYN`, toggles
DYNMODE 3/0).

Selection helpers (W-D, in `_common.py` or `selection.py`):

- `select_ids` extension — selection prompts now accept keyword options
  `["All", "Previous", "Window", "Crossing", "Last"]`:
  - `All` = every entity in the current space on selectable layers
    (not frozen, not locked-layer for modify);
  - `Previous` = the last non-empty selection used by a command
    (`ctx.document.last_selection_ids` — new document session state,
    updated by `select_ids`);
  - `Window`/`Crossing` = two corner picks (point prompts) → geometry
    containment (`window`: fully inside; `crossing`: bbox intersects rect)
    over current-space entities;
  - `Last` = most recently created entity in the current space.
- Noun-verb: existing `select_ids` preselection path IS PICKFIRST
  (verified by tests at M2).
- Frozen-layer entities are never returned by selection; locked-layer
  entities are returned but modify commands skip them with feedback.

## 5. `bcdraw` (W-C) — annotations + layouts

New package `modules/drawings/bcdraw/`: `__init__.py` (`register_all`,
`refresh_document`), `dims.py`, `text_ann.py`, `regen.py`,
`commands_ann.py`, `commands_layout.py`, `formats.py`.

### 5.1 Dimension engine (`dims.py`)

```python
def linear_geometry(p1, p2, angle_deg: float, offset_point, style: DimStyleRecord,
                    ) -> DimensionGeometry   # dataclass below
def aligned_geometry(p1, p2, offset_point, style) -> DimensionGeometry
@dataclass
class DimensionGeometry:
    measurement: float        # projected |p2-p1| on the measurement axis
    dim_line_p1: tuple; dim_line_p2: tuple      # dimension line endpoints
    ext1: tuple[tuple, tuple]                   # extension line 1 (from p1)
    ext2: tuple[tuple, tuple]                   # extension line 2 (from p2)
    arrow1: list[tuple]  # 3 points: [tip, wing, wing] of the arrow head
    arrow2: list[tuple]
    text_point: tuple     # auto placement above the dim line, centered
    text_value: str       # formatted measurement (formats.py)

def resolve_dimension(dim: Dim, doc) -> tuple[DimensionGeometry, str]
    # associativity (FP-ANN-015): when dim.measured_id is set and the entity
    # exists, p1/p2 come FROM THE LIVE ENTITY (line -> its endpoints); the
    # stored dim.measurement is refreshed to the current value; returns
    # (geometry, formatted text). Free dims (measured_id "") use stored points.
```

Rules: linear `angle` = measurement direction (0 = horizontal, 90 = vertical);
measurement = projection of `p2-p1` on that axis; the dimension line passes
through `offset_point` offset along the axis normal; extension lines run from
measured points to a point `dimexe` beyond the dimension line, starting
`dimexo` off the measured points; arrows (closed filled style approximated by
a 3-point chevron of length `dimasz`) sit at the dim-line ends; text is placed
`dimtxt*0.5` above the dim line center (or at `text_position` when set);
`dimscale` multiplies all sizes. Aligned: axis = p1→p2 direction.

`formats.py`:

```python
def format_length(value: float, settings: Settings) -> str   # LUNITS/LUPREC (decimal at M2)
def format_angle(value_deg: float, settings: Settings) -> str # AUNITS/AUPREC (decimal)
```

### 5.2 Commands (`commands_ann.py`)

- `DIMLINEAR` — first ext origin (or Enter → "Select entity" → line/polyline
  segment pick uses its endpoints and sets `measured_id`), second origin,
  placement point with options `[Horizontal/Vertical/Rotation]` (auto-picks
  H/V from placement when no option given; Rotation asks angle).
- `DIMALIGNED` — same entity-select path; axis always p1→p2.
- `DIMSTYLE` — options `[?List/New/Set]`: List prints names+values, New
  prompts name + values, Set sets the DIMSTYLE setting.
- `DIMREGEN` — calls `regen.refresh_document(doc)`.
- `TEXT` — start point, height (style default), rotation (default 0),
  content string, justification option `[Justify]` (LEFT/CENTER/RIGHT).
- `MTEXT` — corner point, width, content (multi-line string prompt).
- `STYLE` — `[?List/New/Set]` like DIMSTYLE (height, width factor).

### 5.3 Regeneration (`regen.py`)

```python
def refresh_document(doc) -> dict   # {"refreshed": n}
    # for every dim entity: resolve_dimension -> update stored measurement +
    # text geometry (the DEFINITION POINTS + measured_id are authoritative;
    # cached measurement updates). Called by bcshell after every committed
    # transaction (display path) and by DIMREGEN.
```

### 5.4 Layout commands (`commands_layout.py`)

- `LAYOUT` — options `[?List/New/Copy/Delete/Rename/Set/Move]`: New
  (name), Copy (source, new name), Delete (guards non-empty spaces),
  Rename, Set (activates + sets current_space + TILEMODE 0), Move
  (layout, before-layout → reorder).
- `MSPACE` — requires current_space != "MODEL"? No: sets current_space
  "MODEL" keeping the active layout as the VIEWING layout
  (`doc.active_layout` session state, new) — editing flows to model space.
- `PSPACE` — sets current_space back to the active layout's paper space.
- `MVIEW` (alias `VIEWPORT`) — two paper-corner picks → viewport entity in
  the ACTIVE layout's space; view center/height prompts default to the
  current model extents bbox center/height; `Fit` keyword sizes the view to
  the model extents. Requires current_space != "MODEL" (clear error).

`doc.active_layout: str | None` — session state (which layout tab is being
viewed; `MODEL` view = active_layout None). `set_current_space` maintains
the TILEMODE setting (1 in MODEL, 0 in paper).

## 6. `bcio` v2 (W-B2) — interchange for the M2 set

- **ezdxf bridge** (preferred engine, R2010):
  - export: full layer table (color/linetype/lineweight/frozen/on/locked),
    blocks (`doc.blocks` → ezdxf block definitions; members transformed
    ByBlock color 0), INSERTs, all M2 entity kinds (LWPOLYLINE with bulges +
    widths, POINT, ELLIPSE, XLINE, RAY, TEXT, MTEXT, DIMENSION via the ezdxf
    dimension factory, VIEWPORT), one paper-space layout per doc layout
    (entities by `space`; viewport view center/height mapped), header sysvars
    ($CLAYER, $INSUNITS, $LUNITS, $LUPREC, $AUNITS, $AUPREC, $ORTHOMODE,
    $OSMODE, $LTSCALE, $DIMSTYLE→ is it header? — only write what ezdxf
    exposes; anything absent is a ledgered loss, not a silent drop).
  - import: the reverse mapping; dimension import reads definition points +
    type from the DIMENSION entity (linear/aligned via dimtype bits; unknown
    dim types → loss ledger + skip); layouts from paper spaces; viewports
    back to viewport entities; unknown entities → loss ledger (M1 rule).
  - M1 handle-preservation rule extends to all new kinds + table records
    (blocks keep definition handles).
  - PROBE FIRST: the exact ezdxf APIs (add_viewport/add_dimension attribute
    names, layer flags, LWPOLYLINE width format) must be verified against the
    installed ezdxf (1.4.3 dev / 1.4.5 Blender) with small probe scripts
    before writing the bridge — no assumed APIs.
- **dxf_minimal** (pure-Python R12 fallback, no third-party): keeps
  LINE/CIRCLE/ARC/LAYERS(+color,frozen flag if writable in R12 tables) and
  adds TEXT; every other M2 kind is skipped WITH a loss-ledger entry
  (kind, dxf_type, reason). Polyline via minimal engine is written as LINE
  segments (degradation ledgered — arcs/bulges lost; round-trip compare for
  polylines through the minimal engine is expected to FAIL by design and is
  excluded with a ledger note; the ezdxf engine is the conformance path).
- Round-trip compare (M1 rule: kind+handle+geometry) extends to: entity
  kinds above, layer table (name+props), block definitions (name, base
  point, member geometry), layout set (names, page size), entity space
  routing, settings subset. Loss ledger records: current space (not a file
  concept), active layout, session state, LUNITS non-decimal formatting,
  anything ezdxf can't express for our subset.
- API unchanged: `export_dxf(path, doc) -> stats`, `import_dxf(path, doc=None)
  -> (Document, stats)`; stats now include per-kind counts for new kinds +
  ledger summary.

## 7. `bcshell` v2 (W-S) — display, panels, autocomplete

- **sync v2**: `entity_display_spec` dispatch extends to ALL kinds:
  - point → 4-segment cross (0.25-unit arms, cyclic=False, two short lines?)
    — implement as a small 8-point non-cyclic polyline (X shape);
  - polyline → vertices (+bulge sampling per segment at 16 segments/sweep),
    cyclic per `closed`; width is NOT rendered (centerline display;
    documented);
  - ellipse → sampled 48 points (cyclic for full);
  - xline/ray → segment clipped to ±1000 units around p1/p2 (display only);
  - text → Blender FONT curve object (body=content, size=height, rotation;
    justification shifts the object origin);
  - mtext → FONT object with body (embedded \n respected; wrapping NOT
    rendered — documented);
  - dim → ONE curve object with multiple POLY splines (ext lines, dim line,
    arrow chevrons) + ONE FONT object for the value, both tagged with the
    dim's bcdoc_id; geometry comes from `bcdraw.dims.resolve_dimension`;
  - insert → member display specs transformed (position/scale/rotation,
    base_point respected), each tagged with the INSERT's bcdoc_id (one id,
    many objects — selecting any selects the reference);
  - viewport → rectangle polyline (not cyclic), drawn in its layout's space
    collection.
- **Spaces**: collection `"BlenderCAD"` = MODEL space;
  `"BlenderCAD/Layout <name>"` per layout. Non-current spaces' collections
  are hidden (`hide_viewport` + collection hide). Sync regenerates all
  spaces (cheap at M2 scale).
- **Layers**: per-object display honors layer state — `on=False` or
  `frozen=True` ⇒ `hide_viewport=True`; entity `color=None` ⇒ object color =
  layer ACI mapped through the same palette table used by bcio; `lineweight`
  is not rendered (documented).
- **Panels (N-panel "CAD")**: sections Layers (list, current selector, on/
  freeze/lock toggles), Layouts (list, activate, new), Snaps (endpoint,
  midpoint, center, quadrant, intersection, perpendicular, tangent,
  ortho, grid — checkboxes bound to OSMODE bits/settings), Document (M1
  info + current space). Every control is a working operator — no dead UI.
- **Autocomplete**: the cmdline operator shows up to 5 suggestions in the
  feedback line while typing (`Registry.suggestions`) and TAB completes the
  top suggestion (headless logic tested; the visual popup is GUI-verified
  later per M1 precedent).
- **Repeat-last**: empty cmdline token re-runs `History.last_command()`.
- **Pointer tracking**: the modal operator records `ctx.pointer` on mouse
  moves (DDE + ortho direction data source).
- `bcshell` calls `bcdraw.regen.refresh_document(doc)` in its on_change
  handler before syncing display (dims stay current after MOVE).

## 8. `bcagent` honesty updates (TL)

`cad.layers.list` reports the full layer table; a new `cad.layers.set_props`
tool (propose/autonomous gated) joins the honest set. `cad.doc.info` gains
block/layout/style counts. Capabilities bump `"1.1-m2"`. Nothing else is
advertised (dims/layouts commands stay unadvertised until W3 adds them at
M5 with tests).

## 9. Extension + build

- `scripts/build_extension.py` `PACKAGES` gains `"bcdraw": modules/drawings/bcdraw`.
- Manifest `blender_manifest.toml`: version → `0.2.0`.
- `scripts/check_module_boundaries.py` import rules updated (bcdraw allowed
  imports; drawings module depends_on gains `"commands"`, drops nothing).
- Byte-compile list in ci.yml gains `modules/drawings/bcdraw`.

## 10. Test matrix (binding)

| suite | owner | covers |
|---|---|---|
| `modules/document/tests/` | W-B1 | new kinds, tables, settings, serialization v1↔v2, journal ops, undo/redo of table mutations, byte-stability, v1 upgrade |
| `modules/interchange/tests/` + `modules/testing/roundtrip/` | W-B2 | M2 kinds round-trip (ezdxf + minimal fallback + ledger), layers/blocks/spaces round-trip, header vars |
| `modules/commands/tests/` | W-A | source flag, suggestions, osnap tokens, DDE parsing, sysvar commands, repeat-last logic |
| `modules/drafting/tests/` | W-A + W-D | every snap mode + aperture + frozen exclusion, ortho, grid, DDE, one-shot/running; every new draw/modify command; selection modes; layer/block commands; noun-verb; validation/cancel/undo per command |
| `modules/drawings/tests/` | W-C | dimension geometry (golden values), measurement formatting, associativity refresh, TEXT/MTEXT/STYLE, LAYOUT/MSPACE/PSPACE/MVIEW, persistence |
| `modules/shell/tests/` | W-S | display specs for all kinds, space/layer display rules (pure parts), suggestions wiring |
| `modules/testing/functional/` | TL | cross-module walkthroughs: precision+layers+blocks+dims+layouts scripted sessions |
| `modules/testing/blender/acceptance_m2.py` | TL + W-S | in-Blender battery §11 |
| `modules/testing/blender-regression/` | TL | TP-CAT-06 re-run on the M2 build |

## 11. In-Blender acceptance battery (`acceptance_m2.py`)

Same install path as M1 (real extension system, isolated user dir). Sections
(1 check each, JSON evidence `acceptance_m2_result.json`):

1. M1 regression section: extension loads, workspace opens, LINE/CIRCLE/ARC +
   MOVE/COPY/ROTATE/SCALE/ERASE, undo, DXF round-trip, native coexistence.
2. Precision: mouse-source LINE snapping to a prior line's ENDPOINT (exact
   point match), ORTHO-constrained mouse point, typed DDE distance, one-shot
   osnap keyword, invalid input → re-prompt recovery, Esc/cancel mid-command
   leaves document unchanged.
3. Layers: -LAYER create+set+color, entity on layer, layer off → not in
   display, frozen → not snappable/selectable, locked → MOVE rejected with
   feedback; persistence after save/reopen.
4. Blocks: BLOCK from selected geometry, INSERT at point+scale+rotation,
   MOVE the reference, redefine → references update, save/reopen intact,
   DXF round-trip (blocks + INSERT).
5. Annotations: DIMLINEAR (exact measurement value), DIMALIGNED, TEXT, MTEXT,
   MOVE the measured line → dimension measurement updates after refresh,
   DIMSTYLE/STYLE create+set, save/reopen, DXF export/reimport.
6. Layouts: LAYOUT new/set, draw frame in paper space, MVIEW with Fit, MSPACE/
   PSPACE switching, save/reopen (layout + entities + viewport intact), DXF
   export includes paper space + viewport, reimport maps back.
7. Native coexistence + clean unload (M1 section re-run).

Exit: all checks pass, result JSON committed, plus M1 driver battery (53) and
TP-CAT-06 green on the M2 build.

## 12. Versioning

- Extension `0.2.0`; serialization `bcdoc/2` (loads `bcdoc/1`);
  `cad-tool-contract/v1` capabilities `"1.1-m2"`.
- Release manifest `release-manifests/manifest-0.3.0-m2.json` (pins unchanged:
  Blender bf200615 runtime-tested 5.2.2 LTS, ZCode 0a1fc56).

## 13. Explicitly NOT claimed at M2

TRIM/EXTEND/FILLET/CHAMFER, PEDIT, HATCH, SPLINE, grip-mode cycling,
transparent commands, right-click modes, xrefs, WBLOCK, PDF publish/plot,
linetype rendering, width rendering, MTEXT inline formatting, architectural
unit display formats, annotative scales, per-viewport layer overrides,
attribute definitions, dynamic blocks. All stay `planned` with reasons in
the inventory notes + completion graph.

## 14. M1 contract amendments

- §3.2 `Document.layers: list[str]` → `LayerTable` (M2 §2.2); M1 journal
  compat preserved.
- §3.5 serialization schema `bcdoc/1` → writes `bcdoc/2`, loads both.
- §3.1 entity property set gains `lineweight` + `space`; kind set gains the
  M2 kinds.

## 15. Amendment log

- **(M2 integration)** §4 — the chained (option-carrying) point prompts
  (LINE next point and the same pattern) route ALL precision legs through
  `_common.dde_input` (upgraded from the DDE-only helper): osnap one-shot
  arming, DDE and mouse-point resolution each apply. ask_point keeps its
  own copy of the chain for plain point prompts.
- **(M2 integration)** §2.7 — journal deserialization fix:
  `redefine_block` ops validate `name` as present (string) and `new`/`old`
  as dicts (the original loop validated `name` as a dict, breaking every
  document containing a block redefinition on save/reopen).
- **(M2 integration)** §8 — bcagent pattern corrections recorded:
  transactional tools never open their own transaction (adapter-managed,
  `base.ToolSpec` rule) and validation raises contract `ValidationError`
  (plain ValueError maps to CAD_E_INTERNAL).
- **(M2 integration)** §10 — `modules/shell/tests/test_blender_driver_m2.py`
  (renamed from blender_driver_m2.py) is a HEADLESS pytest smoke suite over
  the same registry the UI uses; the in-Blender evidence remains the
  acceptance batteries + TP-CAT-06.
- **(M3 schema lane, 2026-10-20)** this file's §2.7/§2.8 are AMENDED by
  `m3-module-contracts.md` §6 (serialization writes `bcdoc/3` and loads
  1/2/3; the journal vocabulary gains nine sketch op kinds; `remove_entity`
  gains an EntityInUse guard; extension version 0.3.0). The binding text
  for all of that lives in the m3 file; this log line is the pointer.
