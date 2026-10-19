# Module: drawings

- **Status:** in-progress — M2 status: implemented (bcdraw v0: annotations + layouts)
- **Owner:** W1 (M2 implementation: W-C)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)
- **Binding spec:** docs/00-architecture/m2-module-contracts.md §5 (this module IS the
  §5 `bcdraw` row); §10 test matrix row `modules/drawings/tests/`

## Purpose

Technical documentation on top of the model: annotation objects (text,
dimensions, tables, hatches), layouts and viewports, dimension/text/table
styles, annotation scale, and plot/publish. The module that turns a model into
a drawing package.

## M2 implemented surface (bcdraw v0)

Shipped package: `modules/drawings/bcdraw/` (pure Python, no bpy; imports
bcdoc + bccmd + bcdraft per the contract §1 dependency direction). Files:
`__init__.py`, `formats.py`, `dims.py`, `regen.py`, `commands_ann.py`,
`commands_layout.py`.

### Dimension engine (`dims.py` — the core deliverable)

| API | exact signature | notes |
|---|---|---|
| `DimensionGeometry` | dataclass, pinned field order | measurement, dim_line_p1/p2, ext1/ext2 (point pairs), arrow1/arrow2 ([tip, wing, wing]), text_point, text_value |
| `linear_geometry` | `linear_geometry(p1, p2, angle_deg, offset_point, style, settings) -> DimensionGeometry` | measurement = \|projection of (p2-p1) on the axis at `angle_deg\`; dim line through `offset_point` parallel to the axis |
| `aligned_geometry` | `aligned_geometry(p1, p2, offset_point, style, settings) -> DimensionGeometry` | axis = p1 -> p2 direction |
| `resolve_dimension` | `resolve_dimension(dim, doc) -> (DimensionGeometry, str)` | associativity (FP-ANN-015): live LINE endpoints when `measured_id` resolves; stored points otherwise; `text_position`/`text_override` honored; missing style -> Standard fallback |
| `style_for` | `style_for(doc, name) -> DimStyleRecord` | Standard-fallback dim style resolution (bcdoc does not guard dims against removed styles) |

Construction rules: extension lines start `dimexo` off the measured point and
end `dimexe` past the dim line (scaled by `dimscale`); arrows are 3-point
chevrons of length `dimasz`, tips on the dim-line ends, wings folded back,
wing half-spread `0.25 * dimasz` (documented presentation choice — the
contract pins only the length); text sits `dimtxt * 0.5` along the LEFT
normal of the q1->q2 travel direction. 2D-only (XY plane; z is carried, never
measured).

### Regeneration (`regen.py`)

`refresh_document(doc) -> {"refreshed": n}` — resolves every dim entity and
updates the cached `measurement` (definition points + `measured_id` are
authoritative and never touched). `n` counts the dims whose cached value
actually changed (idempotent). The cache write is deliberately UN-journaled
(derived state, like selection) so the shell sync hook can run it after
every committed transaction without flooding the undo stack; DIMREGEN is the
command face. Called by: `DIMREGEN` + bcshell's post-transaction sync hook
(contract §7 — W-S: `bcdraw.regen.refresh_document(doc)`).

### Formatting (`formats.py`)

`format_length(value, settings) -> str` (LUNITS/LUPREC),
`format_angle(value_deg, settings) -> str` (AUNITS/AUPREC). Decimal-only at
M2 (other LUNITS/AUNITS codes accepted, formatted decimal — documented
limit); Python format-string rounding (round-half-even over the binary
double), precision clamped [0, 12], negative zero normalized, non-finite
rejected.

### Commands (all names NEW; no collisions with bccmd/bcdraft)

| command | aliases | flow (W-C letter-pinned) |
|---|---|---|
| `DIMLINEAR` | — | first ext origin or Enter -> "Select line to dimension:" (first LINE entity; PICKFIRST preselection included; missing/non-line selection -> feedback re-ask), second origin, location with [Horizontal/Vertical/Rotation] (plain placement auto-picks H/V: dominant offset direction, tie -> horizontal) |
| `DIMALIGNED` | — | same entity-select path; axis = p1 -> p2; no Rotation option |
| `DIMSTYLE` | — | [?List/New/Set]: List = one feedback line per record; New = name + dimscale/dimtxt/dimasz/dimexo/dimexe prompts (defaults = current style); Set = validates then sets the DIMSTYLE setting |
| `DIMREGEN` | — | prompt-free; runs `regen.refresh_document`, feedback count |
| `TEXT` | — | start point or [Justify] -> LEFT/CENTER/RIGHT, height (default = current style), rotation (default 0), content |
| `MTEXT` | — | corner, positive width, content (literal `\n` -> newline) |
| `STYLE` | — | [?List/New/Set] for text styles (height, width_factor) |
| `LAYOUT` | — | [?List/New/Copy/Delete/Rename/Set/Move]; Copy clones the record AND the source space's entities (fresh ids/handles; viewports clone too); Delete refuses non-empty spaces, fixes dangling session pointers; New refuses the reserved name "MODEL" |
| `MSPACE` | — | in MODEL -> note; else `set_current_space("MODEL")` keeping `active_layout` as the viewing tab (TILEMODE 1) |
| `PSPACE` | — | requires `active_layout` (clear feedback otherwise); `set_current_space(active_layout)` (TILEMODE 0) |
| `MVIEW` | `MV`, `VIEWPORT` | paper space only (clear refusal in MODEL); two corners (normalized, must differ in X and Y), then view center or [Fit] <Fit>; Fit = MODEL entities bbox center/height (empty model -> honest note + center (0,0), height 100); explicit center asks a positive height |

All commands: one transaction per run, invalid input -> feedback + re-prompt,
Cancelled -> no partial state, created entities land on the current layer in
the current space (`doc.current_space`), `Register` via
`bcdraw.register_all(registry)`.

## Honest M2 limits (documented, not claimed)

- Decimal-only length/angle display (LUNITS 1/3/4/5, AUNITS 1-4 stay planned;
  contract §2.5 + §13)
- Only "linear" + "aligned" dims (radius/diameter/angular/ordinate are
  P1+; FP-ANN-003..012); associated entities must be LINEs (polyline-segment
  picks need shell-side pick resolution; contract §5.2 note)
- Measurement cache refresh is un-journaled derived state (definition points
  are the undoable content); text is never cached (computed on demand)
- MVIEW Fit matches bbox height only (aspect-aware fitting is GUI work);
  bbox is conservative for arcs (center ± radius) and skips xline/ray/dims
- MTEXT is a single string prompt (no in-place editor, FP-ANN-022 planned);
  content starting with a number AND containing spaces cannot be typed
  through the M1 bccmd parser (bccmd-owned grammar limit, recorded for TL)
- Not claimed (contract §13): annotative scales, per-viewport layer
  overrides, plot/publish (FP-LAY-008+ stays planned), page setups

## Still planned (M0 sketch kept for M3+)

- `AnnotationFactory`, `RegenerationEngine` as richer subsystems; `PlotPublisher`
  (PDF output); DIMRADIUS/DIMDIAMETER/DIMANGULAR; MLEADER; tables; fields;
  page setup manager; viewport clipping/locking controls.

## Owns / Does NOT own / FP areas

- Owns: annotation objects + associativity, layouts/viewports semantics,
  text/dim styles, annotation regeneration.
- Does NOT own: model geometry (`kernel`, `drafting`), layer/block
  semantics (`document`, `drafting`), UI hosting of layout tabs (`shell`).
- FP areas: ANN (annotation), LAY (layouts, viewports, plot/publish).
- Allowed dependencies: `document`, `drafting`, `kernel` (bcdraw imports
  bcdoc/bccmd/bcdraft; the `commands` edge is transitive via `drafting` —
  contract §9 asks TL to add it to modules.json).

## Tests

```
python3 -m pytest modules/drawings/tests -q     # 121 tests
python3 -m compileall modules/drawings/bcdraw -q
```

Suite home `modules/drawings/tests/` (contract §10 W-C row): dimension
geometry golden values (hand-computed horizontal/vertical/reversed/below/
rotated-30°/aligned-45°/dimscale), exact format strings, associativity
end-to-end through the combined bcdraft+bcdraw registry (LINE -> DIMLINEAR
select-object path -> scripted MOVE/SCALE -> DIMREGEN), free-dim stability,
TEXT/MTEXT/STYLE/DIMSTYLE scripted flows, persistence (serialize -> load
keeps dims/text/mtext/viewports/styles/layouts/settings; byte-stable),
LAYOUT flows (new/copy-clones-entities/delete-refusal/rename-reroute/
reorder), MSPACE/PSPACE/TILEMODE transitions, MVIEW (rect normalization,
Fit exact bbox, empty-model note, refusal in model space), space routing,
invalid-input recovery + cancellation per command, no-bpy guarantees
(source scan + in-process + clean-subprocess), registration/alias surface.
