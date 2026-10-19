# Usability Validation Plan — Comparative Usability (TP-CAT-10)

- **Status:** Active plan — measurement-program specification. No results exist at M0; this document defines how results will be produced and judged, and records none.
- **Owner:** W1 (UX & command systems), run with TL oversight (`testing` module owner, glossary §10)
- **Date:** 2026-10-19
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)
- Companion spec: [ux-specification.md](ux-specification.md)

## 1. Purpose & binding rules

**Purpose.** Produce measured evidence for mission criterion 2 (glossary §1): experienced AutoCAD users work naturally in Blender CAD. This program is the comparative usability category **TP-CAT-10** of [../30-process/test-plan.md](../30-process/test-plan.md); behaviors under test are specified in the UX specification.

**Binding rules:**

1. **Measured results, not screenshots.** Acceptance evidence = numeric results extracted from recorded sessions (§7). Screenshots and videos are supporting artifacts, never substitutes.
2. **No self-certification.** Participants are external AutoCAD users, not project members. Results are recorded as measured — including failures, verbatim.
3. **Failures drive the backlog.** A task that misses a threshold becomes a UX-backlog item (§8). The response to failure is fixing the product (or rescoping the feature with a recorded decision) — never redefining success.
4. **Honesty alignment.** "Verified" usability claims require test IDs + recorded artifacts (glossary §1, §5). Any familiarity claim in release notes must link recorded runs.
5. **Scope honesty.** Tasks run only against features present in the tested build; features at declared support levels are tested as such; otherwise the task is marked **deferred** with a reason — never silently dropped.

## 2. Participants

**Population — experienced AutoCAD users.** Screening requires all of:

- ≥ 2 years professional drafting with AutoCAD (recent releases), currently active (drafting at least weekly).
- No prior exposure to Blender CAD builds (transfer must be measured, not learned adaptation). Prior Blender exposure is recorded as a potential confound.
- Windows workstation fluency (baseline platform).

**Sample sizes:** pilot **N ≥ 5** (protocol shakeout) → formal **N ≥ 12 target** (recruit ~15 for attrition).

**Screening questionnaire items (draft):**

1. Years of professional AutoCAD use (must be ≥ 2).
2. AutoCAD versions used (recent-release familiarity; 2027 exposure recorded if any).
3. Industry: architecture / mechanical / MEP / other.
4. Role title and drafting share of work time.
5. Weekly drafting hours (must be active, ≥ weekly).
6. Keyboard- vs ribbon-heavy self-profile — including "do you type command aliases? which ones?".
7. Prior exposure to this product or to Blender (recorded confound; must not have used our builds).
8. Windows workstation fluency (baseline platform).
9. Consent to screen + input recording.
10. Availability for two sessions on separate days.

Screening answers are stored against the participant code; the AutoCAD-version profile is reported with results so "2027 familiarity" claims are inspectable.

**Representativeness:** the formal cohort spans at least architecture, mechanical and MEP (≥ 3 participants each), with a recorded mix of command-line-heavy and ribbon-heavy users. Demographics beyond industry/role/tenure are not collected (not needed for representativeness).

**Ethics / consent / compensation:**

- Informed consent covering data use and the right to withdraw without penalty; separate explicit consent for screen + input recording.
- Compensation at fair market rate for professional time, fixed per session, paid regardless of performance.
- Anonymization: participants referenced by codes (P01…); results are not shared with employers; recording access is limited (§7).
- Checklist-based internal ethics review before recruiting (jurisdiction-specific requirements reviewed at study launch — (verify)).

## 3. Baseline protocol

- **Baseline tool:** AutoCAD 2027 on Windows, on hardware matched to the Blender CAD test machine (same CPU/GPU class, same input devices; one machine class per session pair; deviations recorded).
- **Licensing note:** baseline seats must be legitimately licensed ((verify) procurement before scheduling). If 2027 is unobtainable, the comparison runs on the nearest licensed release and the deviation is recorded in the report — never silently substituted.
- **Task files:** identical fixtures in both tools, authored by us (DXF-based where possible, ADR-0003; no Autodesk sample content).
- **Design:** **within-subjects where feasible.** The suite is split into two fixed halves (Half A: T1–T6; Half B: T7–T12, balanced for common/advanced mix). Each participant performs the **same half in both tools**, tool order counterbalanced across participants (half AutoCAD-first), sessions ≥ 48 h apart (fatigue/carryover). Halves rotate across the cohort so every task accumulates both-tool data from ≥ 6 participants. If scheduling forces otherwise: **between-subjects** with matched cohorts (industry × experience strata), full suite per participant in one tool. The design actually used is reported per participant.
- **Session agenda (per session = one tool block):**

| Slot | Duration | Content |
|---|---|---|
| Intake (session 1 only) | 15 min | consent, screening verification, think-aloud briefing |
| Warm-up | ~30 min | scripted exercise; excluded from timing (§6) |
| Task block | 60–90 min | assigned half, tasks in fixed order |
| Debrief | 15 min | SUS + TLX-lite + familiarity items; session 2 adds an open interview |
- **Warm-up excluded:** the first 30 minutes per tool block are excluded from timing thresholds (familiarization allowance, aligned with §6); a scripted warm-up exercise precedes each tool block and is not a task.
- **Think-aloud:** a subset verbalizes while working (all pilot participants; ≥ 4 in the formal runs). Moderators follow a neutral script — no feature pitching. Utterances feed the complaint register (§5) verbatim.
- **Moderator help policy:** every intervention is logged and marks the task **aided** (feeds the unaided-completion metric, §5–§6).

## 4. Task suite (12 tasks)

Notation per task: **Fixtures / Instructions / Success criteria / Timing checkpoints / Allowed tools.** "Common" tasks exercise P0 drafting-core behaviors (UX spec §11); "advanced" tasks exercise P1 features at their declared support levels. Suite composition is fixed; tasks run against the features their build contains.

### T1 — Dimensioned floor plan from scratch (common)
- **Fixtures:** empty template; authored target-plan PDF brief; fixture block library (door/window blocks); layer-schedule handout.
- **Instructions:** set units (decimal, mm), create the layer schedule, draw exterior/interior walls to the given dimensions, insert door/window blocks, hatch walls, dimension per the brief, save.
- **Success criteria:** wall geometry within ±1 mm of the dimension sheet; layers/properties correct; dimensions associated to geometry; hatch associative; file saves.
- **Timing checkpoints:** units+layers set; walls complete; blocks placed; annotation complete.
- **Allowed tools:** everything (ribbon, command line, palettes).

### T2 — Modify an existing plan built on xrefs (common)
- **Fixtures:** sheet drawing referencing a base plan via xref; revised base-plan file supplied mid-task.
- **Instructions:** reload the revised base plan, apply an xref clip to the sheet, freeze selected layers of the xref in this sheet, move a door block, update affected dimensions, save.
- **Success criteria:** reloaded revision visible; clip boundary applied; layer overrides correct; edits within tolerance; dimensions update.
- **Timing checkpoints:** reload; clip; edits; dimension update.
- **Allowed tools:** everything.

### T3 — Mechanical part: dims + title block + layout + PDF publish (advanced)
- **Fixtures:** authored part brief (dimensioned orthographic sketch); title-block block with attributes; layout template.
- **Instructions:** draw the part (mm), dimension it, fill the title block via attributes, set up a layout viewport at the given scale, plot to PDF.
- **Success criteria:** part within tolerance; dimensions correct; title-block attributes populated; viewport scale correct; PDF opens with correct page size and scale.
- **Timing checkpoints:** views drawn; dimensioned; layout; PDF published.

### T4 — Parametric edit (advanced; requires M3 features)
- **Fixtures:** constrained bracket drawing (geometric + dimensional constraints); a dynamic-block-like fixture block at its declared support level (ORG area).
- **Instructions:** change the driving dimension (plate length 120 → 160) and verify the solve; change the fixture block's width parameter and verify the update.
- **Success criteria:** geometry re-solves with no constraint failures; block updates without manual geometry repair.
- **Timing checkpoints:** each solve.

### T5 — Precision drawing exercise (common)
- **Fixtures:** target-figure sheet defining points by coordinates, offsets, and tangencies, with an explicit method list (osnaps, FROM, relative/polar entry, direct distance, tracking).
- **Instructions:** reproduce the figure using the listed methods.
- **Success criteria:** 12 checkpoint coordinates match within ±0.01 units; construction leftovers erased; mis-snap count logged.
- **Timing checkpoints:** per segment group.

### T6 — Missing-xref recovery and repair (advanced)
- **Fixtures:** drawing with deliberately broken xref paths (reference files relocated).
- **Instructions:** identify the missing references, repath to the supplied folder, reload, verify integrity (audit).
- **Success criteria:** all references resolved; audit clean; no lost geometry; steps recorded.
- **Timing checkpoints:** identification; repath; verification.

### T7 — Attribute/data extraction to a table (advanced)
- **Fixtures:** drawing with attributed equipment blocks; ground-truth data table (authored).
- **Instructions:** extract block attributes to a drawing table; format per spec (columns, sort); place on the sheet; export the same data to CSV.
- **Success criteria:** table values match ground truth exactly; formatting per spec; CSV complete.
- **Timing checkpoints:** extraction configured; table placed; CSV exported.

### T8 — 3D solid modeling + 2D drawing views (advanced; requires M3 features)
- **Fixtures:** authored orthographic part description.
- **Instructions:** model the part (extrude/revolve, booleans, fillets), create base + projected 2D views in a layout at the given scale, annotate one view.
- **Success criteria:** key solid dimensions match; views aligned at correct scale; annotation correct.
- **Timing checkpoints:** solid complete; views created; annotated.

### T9 — Command-line-only speed run (common)
- **Fixtures:** prepared drawing + printed list of 20 named operations (line sequences, offset, trim, array, layer switches, block inserts, dimensions).
- **Instructions:** complete the list using the keyboard for all command entry and values; mouse permitted for pointing/picking only; ribbon and toolbars hidden during the run.
- **Success criteria:** all 20 operations complete and correct; per-operation timings from telemetry.
- **Timing checkpoints:** per operation.

### T10 — Error recovery drill (common)
- **Fixtures:** drawing + scripted mistake sequence: erased set to restore with OOPS; chain of bad edits to walk back with U / UNDO Mark/Back; a named checkpoint to restore.
- **Instructions:** recover the drawing to the specified target states using the undo tools.
- **Success criteria:** each target state matches the checkpoint sheet; recovery step counts logged.
- **Timing checkpoints:** per recovery step.

### T11 — Layer & block organization (common)
- **Fixtures:** messy drawing (entities on wrong layers; unused blocks; no filters).
- **Instructions:** create property + group layer filters, move entities to correct layers, purge unused blocks, save a layer state and restore it.
- **Success criteria:** layer assignment correct per schedule; purged items gone; layer state restores exactly.
- **Timing checkpoints:** filters; reassignment; purge; state round-trip.

### T12 — Viewport & annotation-scale task (advanced)
- **Fixtures:** model-space drawing with annotative text and dimensions; empty layout.
- **Instructions:** create two viewports at specified scales, set the annotation scale per viewport, align views, lock viewports, run plot preview.
- **Success criteria:** viewport scales correct; annotative objects at correct plotted size in both viewports; locks engaged; preview passes.
- **Timing checkpoints:** viewports; scales; lock.

**Suite notes.** Common = T1, T2, T5, T9, T10, T11. Advanced = T3, T4, T6, T7, T8, T12. Tasks whose features are not yet shipped (initially T4 and T8; others per build) are marked **deferred** and run as soon as their milestone ships; removing a task from the suite requires a recorded decision in the milestone report.

**Fixture authoring rules.** All fixtures, briefs and block libraries are authored by the project, checked into the `testing` module fixtures area, versioned per run, and verified by scripts wherever geometric tolerances apply (tolerance checks automated where possible). Fixtures never contain third-party sample content (UX spec §1.3). Fixture versions are recorded in every result (§8).

**Task-to-spec traceability.** Each task names the UX-spec sections it exercises; failures route to backlog items for those sections:

| Task | UX-spec sections exercised | Inventory areas |
|---|---|---|
| T1 | §2 layout/ribbon/status, §3 commands + precision | DRAW, MOD, ORG, ANN, UX |
| T2 | §3.5 selection, §2.6 palettes, xref UX (IO area) | MOD, ORG, IO, UX |
| T3 | §4.8 plot flow, §5 layouts | ANN, LAY, UX |
| T4 | §2.2.4 parametric panels, constraint UX | PAR, ORG, UX |
| T5 | §3.4 osnaps, §3.9 precision aids | PREC, UX |
| T6 | xref recovery UX, §2.6 palettes | IO, UX |
| T7 | §4 dialogs (tables), attribute UX | ORG, ANN, UX |
| T8 | §2.2.5 3D navigate, §5 viewports | P3D, LAY, UX |
| T9 | §3.1–§3.3 command interaction, §3.6 keyboard | CMD, UX |
| T10 | §3.10 undo/redo + checkpoints | CMD, UX |
| T11 | §2.6 Layer Properties Manager, §4.6 layer states | ORG, UX |
| T12 | §5 layouts, annotation scale | LAY, ANN, UX |

## 5. Metrics

| Metric | Definition | Source |
|---|---|---|
| Task success rate | binary per task: success criteria met without moderator intervention | task sheets |
| Workflow correctness rubric | 0–3 per task: 3 = clean familiar workflow; 2 = correct with detours; 1 = completed with aid/errors; 0 = failed or gave up | trained coder; 20% double-coded |
| Per-operation completion times | named common ops: 3-segment LINE sequence; OFFSET+TRIM pattern; dimension placement (linear + continue); layer switching; block insert with rotation | telemetry timestamps + video coding |
| Keyboard/mouse step counts | keystrokes, clicks, drags per task | input recording + command log |
| Error + recovery counts | invalid inputs, mis-snaps, re-selections, undo events, help requests | command log + video coding |
| SUS | System Usability Scale, collected per tool block | questionnaire |
| NASA-TLX-lite | reduced TLX set (mental demand, effort, frustration, performance) | questionnaire |
| Familiarity Likert | 7-point items per interface area ("the command line behaved as I expected", "selection behaved as I expected", "palettes were where I expected", …) | questionnaire |
| Spontaneous complaint register | verbatim utterance + timestamp + task, categorized post-hoc | think-aloud + recordings |

**Rubric coding procedure:** two trained coders; 20% of sessions double-coded; raw inter-rater agreement target ≥ 80%; disagreements adjudicated by the TL with the resolution documented; coder notes feed §8 reporting.

**Baseline asymmetry note:** AutoCAD-side timings and step counts come from screen/input recording only (no internal telemetry is available to us). Comparisons use the common denominator (video coding); our command log enriches only our side and never replaces video coding.

## 6. Pass thresholds (proposal — reviewed at M7 entry)

| # | Threshold | Applies to |
|---|---|---|
| 1 | ≥ 90% task success | common tasks (T1, T2, T5, T9, T10, T11) |
| 2 | ≤ 1.5× AutoCAD baseline **median** time per common operation (§5), after familiarization allowance (first 30 min per tool block excluded) | common operations |
| 3 | ≥ 70% first-attempt unaided completion | all tasks |
| 4 | SUS ≥ 70 | our tool's session |
| 5 | No measured value regresses below the previous run without a UX-backlog entry | re-runs |

- Thresholds may be **tightened** freely. **Loosening** requires a documented rationale + TL sign-off recorded in the milestone report (anti-gaming clause).
- Thresholds are release-gate inputs, not automatic passes: the M7 gate review weighs them with the feature inventory and file-compatibility evidence (glossary §1, §11).

## 7. Instrumentation

- **Screen recording** per session (consent §2).
- **Input recording:** key/mouse events, timestamped, anonymized; free-text fields reviewed for personal data and redacted at ingest.
- **Product telemetry — command log:** per session: command invocations, option choices, cancels, error re-prompts, undo events, timings; keyed by participant code; opt-out honored.
- **AutoCAD side:** video + input recording only (see §5 asymmetry note).
- **Privacy/retention:** raw recordings and logs encrypted; access limited to the research team + TL; retained 12 months after the release they inform, then deleted; anonymized aggregates retained; no third-party sharing; participant deletion requests honored within the retention window.
- **Evidence store:** all artifacts are indexed in the testing evidence store and referenced by test IDs — no "verified" status anywhere without an artifact (glossary §5).

## 8. Reporting

**Per-task result template:** task ID; build + fixture versions; participant code; design arm (order); rubric score; success (aided/unaided); per-operation timings; step counts; error/recovery counts; verbatim notes; video index of key moments.

**Milestone report format:** aggregate tables per metric vs thresholds (§6); per-task pass/fail; regression deltas vs previous runs; complaint-register digest (frequency-ranked); UX-backlog intake list (severity-ranked); deferred-task list with reasons; protocol deviations.

**Regression policy (binding):** any UX change affecting a benchmarked task **requires re-measurement** of that task before the affected release. "Benchmarked" = every suite task once measured.

**UX backlog intake:** every complaint/error cluster with ≥ 2 occurrences, or any single blocker, becomes a backlog entry (owner W1; severity = user impact × frequency), triaged against [../30-process/milestone-plan.md](../30-process/milestone-plan.md).

## 9. Schedule

| Event | Timing | Notes |
|---|---|---|
| Internal dry run | before the pilot | fixtures/timing validated by team members; **internal runs never count as data** (§1, rule 2) |
| Pilot | during M5–M6 | N ≥ 5; fixtures, timing, instrumentation shakeout; report before M7 entry |
| Formal runs | M7, before the 1.0 release gate | N ≥ 12; full suite per feature availability; deferred tasks recorded |
| Targeted re-runs | any release after a benchmarked-task UX change | per §8 regression policy |
| Full re-run | every major release | maintained for as long as familiarity claims appear in release notes |

**Program risks & mitigations:**

| Risk | Mitigation |
|---|---|
| Recruiting shortfall for N ≥ 12 | recruit ~15, rolling admission; extend the window before reducing scope (any reduction recorded) |
| Baseline licensing unobtainable (verify) | nearest licensed AutoCAD release; deviation recorded in the report (§3) |
| Feature gaps in the tested build | task marked deferred (§1, rule 5); never silently dropped |
| Novelty / Hawthorne effects | warm-up excluded; counterbalancing; identical instructions and fixtures in both tools |
| Think-aloud distorts speed measurement | T9 is excluded from the think-aloud subset; speed tasks are timed silently |
| Fixture circulation between participants | single-use content variants where leakage is plausible; confidentiality clause in consent |

## 10. Honesty clause (binding)

- **Results are recorded even when they fail thresholds.** Failures drive the UX backlog — they are never reinterpreted, rescored, or accompanied by a redefinition of success.
- No usability claim reaches release notes without a test ID + recorded artifact (glossary §1, §5). If the program cannot run (baseline licensing, recruiting failure, feature gaps), the familiarity criterion remains **unmet** and the release notes say exactly that. Internal anecdotes are not a substitute.
- At M0 this document is a plan: no measurements exist yet, and nothing in it may be cited as evidence of product quality.
