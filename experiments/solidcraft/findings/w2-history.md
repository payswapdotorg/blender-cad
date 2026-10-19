# W2 (lane a) — feature history, incremental evaluation & persistent naming

- **Experiment:** `w2-history` (results: [`results/w2-history.json`](../results/w2-history.json))
- **Owner:** W2 lane-a worker, Task ID 98, issue #1 candidates **#2 (feature history /
  incremental recompute)** and **#3 (persistent naming)**
- **Source audited:** upstream pin `3b4db52c10279251a068cfca5eb7447068bc28e7` (v0.16.2) —
  behavioural evidence: the checksum-verified **official release binary**
  `solidcraft-cli 0.16.2` (tag commit `5de48e9`, **80 commits behind the source pin** —
  50 first-parent, both dated 2026-10-19; 35 of the 80 touch `crates/doc|engine|kernel`, 3
  the CLI app, 3 `crates/mcp`; the Task-96 briefing's "8 commits behind" figure is wrong,
  measured with `git rev-list` on the full clone; every result file says so). Driver:
  `python3.12 python/w2_history_runner.py`.
- **Verdict in one line:** the audited subsystems are real, tested, and behaviourally verified
  through the official CLI; recommend **reference + selective adapt** for candidate #2 and
  **adapt (design-level) + reference (kernel-level)** for candidate #3 — details in §7.

---

## 1. Source audit

All paths relative to `/home/z/solidcraft-upstream/`. Line numbers are of the pinned SHA.

### 1.1 How incremental evaluation decides what to recompute

`crates/doc/src/eval.rs` (`Model::evaluate`, line 1202):

1. **Prefix reuse by chained fingerprints.** Every feature gets a fingerprint
   `chain_fingerprint` (line 934) = hash of *(previous feature's fingerprint, rolled-back
   flag, design length unit, the feature's serialized definition, and the bit-exact values +
   units of every parameter the feature references)* (`fingerprint`, line 783; referenced
   names from `param_names`, line 776). The chain includes `prev`, so an edit anywhere
   invalidates every downstream fingerprint. `evaluate` walks the timeline reusing each prior
   result while `old.id == f.id && old.fingerprint == fp && !old.stale` (line 1251) — reuse
   stops at the first mismatch (`reuse = false`, line 1275) and everything after it is
   recomputed. Verified behaviourally: editing `len` reported `recomputed: 4` = exactly the
   sketch + 3 downstream features (scenario 2).
2. **Cross-cutting result cache by (feature, state) key.** Beyond prefix reuse, an
   `EvalCache` (line 632; bounded: 4096 entries / 64 MiB, LRU by insertion order, line 649)
   stores whole post-feature `ModelState`s keyed by `cache_key` (line 1004) =
   hash(feature id, local fingerprint, doc context digest, **`state.digest()`**, chain
   fingerprint for patterns/mirrors). `state.digest()` (line 498) hashes bodies by
   *(name, content key, creating feature, component, transferred)*, sketches by solved-key,
   plus body counter / threads / sheets. This is what makes **undo/redo, edit-set-back and
   configuration rows cheap**: the same (feature, resulting state) pair reappears and the
   cached result is restored (`last_restored`, line 758). Command results even report it:
   `parameters.change`/`timeline.edit` return `recomputed` and `restored` counts (command
   registry).
3. **Body-level identity for the cache.** A `ModelBody` carries a `key: u64` "identity of
   this body's content for the evaluation cache: the key of the evaluation that produced it
   (kept while later features pass it through unchanged)" (eval.rs line 42) — bodies passed
   through untouched keep the producing feature's key, so the digest of an unaffected
   downstream state stays equal.
4. **Meshes/plans are shared, lazily computed cells** (`Arc<OnceLock<Arc<Mesh>>>`, line 38;
   comment at line 35: "Timeline snapshots are cloned before meshes are requested. Share the
   cell itself so meshing any snapshot also warms every unchanged copy of this body").
5. **Cost guardrails are tested:** `eval_cost_tests.rs` ("the features before the edit are
   reused, so the edit's cost must not grow with the bodies and imported files the design
   already holds") counts bodies moved into frames and STEP texts digested per edit.
6. **Command→evaluate seam:** every mutating command ends in `Session::refresh()` →
   `model.evaluate(&doc)` (`crates/engine/src/lib.rs` line 573); the CLI's `--timings` wraps
   each command and `--profile` splits the kernel's share (`crates/engine/src/timing.rs`
   line 1: `boolean_ms`, `tessellate_ms`, `other_ms` captured via `profile::capture`).

### 1.2 What identity a feature carries

`crates/doc/src/document.rs` line 2231:

```rust
pub struct Feature {
    pub id: u64,                 // monotonic per document (Document::next_id)
    pub name: String,
    pub suppressed: bool,
    pub body_names: Vec<String>, // names for bodies it creates
    pub param_names: Vec<String>,// dN model parameters of its inputs
    pub component: u64,
    pub edge_refs: Vec<EdgeRef>, // where each picked edge SAT when picked (bbox + dir)
    pub edge_names: Vec<String>, // PERSISTENT names of the picked edges (resolved first)
    pub face_names: Vec<String>, // PERSISTENT names of the faces at its face points
    ...
}
```

Feature references to other features/sketches/bodies are **plain names/ids**
(`crates/doc/src/names.rs`: `BodyName`/`FeatureName` are newtypes over `String`,
`SketchId` over `u64`); the reference graph is walked generically via the `#[derive(Walk)]`
machinery (`walk.rs`, `feature_refs.rs`, `feature_geometry.rs`) — `remap_refs`/`remap_bodies`
rewrite them on copy/rename, `input_sketches` drives delete cascades (exposed as
`timeline.dependents`; verified: deleting sketch `S` would delete `Block`, and `Round` +
`Hole` "would fail").

### 1.3 What identity faces/edges carry after booleans — the naming stack

Four layers, bottom-up:

**Layer 0 — vendored kernel boolean provenance (their kernel-level persistent naming).**
`vendor/truck-shapeops/src/transversal/history.rs` (NEW file added by SolidCraft, see
`vendor/README.md` truck-shapeops entry): during a boolean, a `Lineage` maps live truck
topology addresses (`FaceID`/`EdgeID` — addresses of shared data, valid only while the
entity lives, per the module doc) to **origins in operand terms** —
`FaceOrigin { operand, face, kept }` and `EdgeOrigin::{Edge{operand,edge}, Meet{a,b}}`.
It is recorded *by the code that builds each face/edge as it goes* (`face_piece`,
`edge_piece`, `meet` — called from `divide_face`, `loops_store`), "never reconstructed from
geometry". `and_with_history`/`or_with_history` return `(Solid, Option<History>)`; `None`
where anything went unrecorded. A dead entity's reused address is *overwritten* by the new
entity's record (`set()` removes stale entries) — no dangling-id hazard. The same vendor
patch also makes **the result's shells and faces keep the order of the shell they come
from** (truck's hash-order face iteration used to shuffle faces between runs — a
determinism fix the naming layer leans on).

**Layer 1 — kernel `History` composition.** `crates/kernel/src/history.rs` re-exports a
richer `History { operands, faces: Vec<FaceProv>, edges: Vec<EdgeProv> }` (line 128):
`FaceOrigin::{Face, Profile(segment), Cap(end), Edge, Offset}` + `Change::{Kept, Modified,
Split, Merged, Generated}` (lines 24–51). `History::substitute` (line 224) composes an
operation with the operation that made operand `k` (this is lineage *algebra*: transplanted
origins, renumbered operands, `Meet` sides expanded through merges) and **fails cleanly**
("an offset of a face the inner operation generated or merged") rather than guessing.
`History::check` validates every origin against operand face/edge counts. Faces with an
exact history also get durable face *attachments* for free (`FaceCertificate::Lineage`,
module doc line 13; `docs/face-attachments.md`).

**Layer 2 — document lineage.** `crates/doc/src/lineage.rs` composes kernel histories of the
several operations one feature may run into a `Lineage` over `Operand`s that names can be
read from: `Body(name)` / `Copy{body, instance}` / `Inner(body)` / `Made(roles)` /
`CopiedTool{roles, feature, instance}` / `Stage(...)` (line 22). `Lineage::step` (line 69)
substitutes input lineages; on composition failure the result is named from geometry and
**flagged unverified**. `lineage.rs` also gives role vocabularies for built bodies
(`side:<curve>` from the sketch curve a swept segment lies on **exactly** —
`ExactSketchCurves::find_along`; caps `start/top/bottom/end`; `+x…-z` for boxes; `blend:<edge>`
for fillets; `inner:<face>` for shells, lines 186–412).

**Layer 3 — names, minting and lookup.** `crates/doc/src/naming.rs` (module doc, lines
1–16) is the readable summary: *faces inherited from input faces keep their names; new
faces are named by role; pieces of a split face are told apart by the faces around them
(`F2:top#[F2:side:l4,F4:side:l4]`); edges are named by the faces they separate
(`<face A>|<face B>`, `~k` when several run between the same two).* Names are **lazily
computed and cached per body** (`NameCell` + `OnceLock`, lines 38–77; `MAX_DEPTH` 400
bounds recursion). Two minting paths:

- **exact** (`history_names.rs::derive`, line 81): follows the lineage; if any face can't be
  named exactly it falls back to geometric naming **marked unverified** (`verified: false`
  in `FaceInfo`, line 35). Verifiedness is *per face* and observable via `model.faces`
  (`exact: true/false`).
- **geometric fallback** (`naming.rs::geometric_from`, line 276): up to 9 triangle-centroid
  sample points per face are voted onto the input bodies' faces (majority vote, `vote()`
  line 441; pattern copies matched through instance transforms; sheet folds through
  `point_before`). Names resolved this way are unverified, and **references resolved through
  them say so** ("face `X` was found by geometry, not exact history; check it").

`piece_names.rs` is the grammar of piece qualifiers (never panics on hostile names);
`history_names.rs::qualify` (line 269) disambiguates same-name faces by adjacency sets;
`matches()` (line 370) grades a stored name against a current face as
`Exact > Alias (merged-into) > Piece > Stem`. Lookup (`name_lookup.rs`): `locate_face`
(line 262) / `locate_edge` (line 51) / `locate_one` (line 398) find the face/edge, follow
splits (nearest piece + `split: true`), merges (`Alias`), and **report how sure they are**
(`FaceHit::note`, line 204: "was split; using the piece nearest the picked point" /
"was merged into another face" / "found by geometry, not exact history"). Legacy names from
before format 14 carry a `?` mark and are re-found the way old builds found them
(`LEGACY_MARK`, line 23). Determinism of piece numbering was itself a tracked bug
(solidcraft#569 — pieces swapping numbers between runs; fixed by bucketed sorting,
`naming.rs` lines 514–536 + tests at 847).

**Layer 2.5 — face anchoring.** `face_anchor.rs` (line 1: "Missing identities never invoke a
proximity fallback") + `anchor_frame.rs`: a sketch attached to a face stores a
`FaceAnchor { target: ConfigFaceTarget, component, path, coordinates, x_axis }` with a
**certificate** naming the producing feature — the attachment resolves by identity, not by
searching for a nearby face.

### 1.4 What happens to downstream references when an upstream feature edits

- Parameter edit → chained fingerprints change from the first affected feature on → those
  features re-run; their `edge_names`/`face_names` are **re-resolved against the rebuilt
  model** (the pick *point* is only the tie-breaker for split pieces — the name decides).
  Verified: `len` 40→50 moved the filleted edge from x=40 to x=50; the stored name
  `F2:side:l2|F2:top` still resolved (scenario 2/3a).
- Face split → nearest piece + loud note; faces merged → alias match + note; topology gone →
  **hard error naming every gone reference** (scenario 3b: "edge `F4:inner:…` no longer
  exists and was skipped").
- Stale *pick points* (no names) fail loudly with the distance to the nearest candidate
  (scenario 3c: "no edge at [40, 15, 10]: the nearest edge is 10.000 mm away").
- `ModelState` also carries `blend_edges`/`fitted`/`tapered` (eval.rs lines 507–520): the
  edges a fillet *found* in this evaluation, so **patterns replay those** rather than the
  original pick points ("which a parameter change may have moved off the edges").

### 1.5 How failures propagate through the timeline

- A failing feature gets `error: Some(...)` on its `FeatureResult`; **the state stays as it
  was before the feature** and evaluation *continues* (eval.rs lines 1340–1402: on `Err`,
  `state` is not advanced; the error + the pre-failure state are cached too).
- The CLI gates writes on this: `timeline_ok` (apps/solidcraft-cli/src/main.rs line 315)
  fails the run ("N timeline feature(s) failed, so nothing was written") unless
  `--allow-errors`, which writes the pre-failure bodies **with the feature errors still
  visible** in `eval` output (scenario 3b/4).
- Command-level errors (invalid params, unbuildable geometry) stop the script at that step —
  `--allow-errors` cannot rescue those (scenario 4).
- Skipped/suppressed/rolled-back features are marked `skipped` and keep the previous state.

---

## 2. Experiment scenarios and outcomes

Driver: `python3.12 python/w2_history_runner.py` (plain python3.12; fixtures under
`fixtures/history/`; all outputs in `results/w2-history.json`; scratch in gitignored
`scratch/w2-history/`). Full result: **10 cases — 9 pass, 1 recorded observation, 0
fabricated.**

| # | Scenario (fixture) | What was measured | Outcome |
|---|---|---|---|
| 1 | Baseline parametric chain (`s1-baseline.json`) | volume vs analytic; face names + `exact` flags | **pass** — V = 11 777.908211 mm³ vs analytic 11 777.9082 (rel err < 1e-6); 9 faces, **all names exact** (`F2:start`, `F2:side:l1..l4`, `F2:top`, `F3:blend:F2:side:l2\|F2:top`, `F4:bore:side:0/1`); fillet 18.9 ms, hole 98.6 ms of 178 ms script |
| 2 | Upstream edit → downstream recompute (`s2-edit-len.json`, `--in` saved design) | `parameters.change` result; volume vs analytic; cross-path equality | **pass** — `recomputed: 4` (sketch + extrude + fillet + hole), `restored: 0`; V = 14 777.908211 mm³ (analytic 14 777.9082; exactly baseline + 3 000 mm³); from-scratch control differs by **7.3e-12 mm³ (rel 4.9e-16)** with identical topology (8 faces / 17 edges) |
| 3a | Reference stability, topology preserved (same run) | face-name sets before/after; per-feature error/warning | **pass** — face-name sets **identical** across the edit; no feature errors, no warnings; `timeline.dependents`: delete `S` → deletes `Block`, `Round`+`Hole` "would fail" |
| 3b | Reference stability, topology destroyed (`s3b-shell-*.json`) | exit code, saved-file existence, error text; `--allow-errors` contrast | **pass** — shell 5→2 mm removes the named inner edges; run **fails (rc 1), writes nothing**, error names all 4 gone edges ("no longer exists and was skipped"); `--allow-errors` writes the pre-failure bodies (V = 20 493.10 mm³, 19 faces) with `InnerCorners`' error still listed in `eval` |
| 3c | Stale pick point in an imperative script (`s3c-stale-pick.json`) | exit code, file existence | **pass** — refuses: "no edge at [40, 15, 10]: the nearest edge is 10.000 mm away", rc 1, no file — **no silent nearest-edge retarget** (contrast: the saved design survives the same edit via stored names) |
| 4 | Unbuildable fillet (`s4-bad-fillet.json`) | exit code, file existence, `--allow-errors` | **pass** — "the blend is larger than the neighbouring faces; the largest radius that fits is 10 mm", rc 1, **no file**; `--allow-errors` also writes nothing (script stops at the command; only *timeline-feature* failures are rescuable) |
| 5 | Determinism (`s1-baseline.json` × 3 processes) | byte compare; timing-stripped compare | **pass** — outputs **byte-identical except the three per-command `ms` fields** (`[6]/ms`, `[7]/ms`, `[8]/ms`); after stripping wall-clock fields, content digests identical across all 3 runs. All geometry, names, pick points, volumes bitwise stable |
| 6 | Incrementality (`s6-*` fixtures) | `recomputed`/`restored`; per-command ms + kernel share; cross-path equality | **pass** — edit of `slot_x`/`slot_w` recomputed **exactly 3 features** (Slot, Pocket, LateHole) twice; incremental cost 680 ms total (boolean_ms ≈ 648 of it) vs 1 315 ms for the upstream extrude+fillet+hole+pattern that were **not** re-run (full-run downstream pocket+hole alone = 378 ms, so the edit pays only downstream work); cross-path volume equality rel **2.8e-15**, topology identical (24 faces / 54 edges) |
| 6-obs | Marginal tangency (`s6-marginal-tangency.json`) | topology + volume of the two paths | **recorded observation** — slot wall placed exactly on hole (45,32)'s axis: full rebuild 24 faces / V = 44 381.020097 mm³ vs incremental 25 faces / V = 44 341.756581 mm³ (**ΔV = 39.2635 mm³ ≈ half a Ø5 bore over 4 mm**). Coincident-wall marginal geometry is not stable across evaluation paths — a generic B-rep hazard, honestly recorded, not a headline number |
| 7 | Identity model (`--save` + `timeline.export_script` + `eval`) | container structure; feature identity fields | **pass** — see §4 |

### 2.1 Determinism (scenario 5), precisely

Same script, three separate CLI processes: the `--results` JSON is **byte-identical except
the `ms` timing fields of the three geometry commands** (extrude, fillet, hole). Every
geometric and semantic field — volume to the last bit, face names, `exact` flags, the pick
points `model.faces` reports (roomiest-triangle incentres, i.e. tessellation-derived) — is
bitwise stable. Source corroborates why this is deliberate: the vendored truck-shapeops patch
that keeps face order deterministic, the bucketed piece-numbering fix for solidcraft#569,
and `total_cmp`-based comparators. Cross-*path* equality (full rebuild vs incremental edit
of the same final model) holds to 2.8e-15 relative (scenario 6) and 4.9e-16 (scenario 2) —
float summation-order noise — **except** at deliberately coincident geometry (6-obs).

### 2.2 Incrementality evidence (scenario 6), precisely

Design: plate extrude (1.2 ms) → 4-edge fillet (53 ms) → hole (120 ms) → rectangular
pattern of it, 8 holes total (1 142 ms) → param-driven pocket (163 ms) → late hole (216 ms).
Edit run (`--in` design + `parameters.change`): `recomputed: 3` features, 326 ms for the
final `parameters.change` (kernel boolean share 311 ms) — consistent with the 378 ms the
same three features cost when built from scratch, and **half** the 1 315 ms the upstream
features cost; nothing upstream re-ran (its cost is invisible in the edit run's command
timings). The `restored` counter (cache hits of previously-seen (feature, state) pairs)
was 0 in these runs — as expected for a novel parameter value; it is the undo/redo path.
Per-command `--profile` splits show the recompute is genuinely kernel work
(`boolean_ms` ≈ 95 % of each edit command).

---

## 3. Answers to the four audit questions

- **(a) Feature identity:** monotonic `u64` id per document (`Document::next_id`, persisted),
  a mutable display `name`, per-feature `param_names` (its inputs exposed as model params
  `dN`), plus the *stored persistent topology names* (`edge_names`, `face_names`) and pick
  provenance (`edge_refs`). No UUIDs, no per-feature hashing: identity is document-local and
  positional (timeline order is part of the model).
- **(b) Face/edge identity after booleans:** no stable per-face ids at all — the vendored
  `*_with_history` booleans return, per result face/edge, its **origin in operand terms**
  (which operand face it is a region of / which operand edge or face-pair meeting it came
  from), recorded during construction. The document layer *composes* those origins into
  **string names** (`F<feature>:<role>`, pieces `#[...]`, edges `A|B`) that are what
  features actually store. Unverifiable faces fall back to geometry-sampled names **marked
  unverified**, and consumers are told.
- **(c) Downstream references on upstream edit:** re-resolved by name first (point only
  breaks ties between pieces); splits → nearest piece + warning; merges → alias + warning;
  gone → loud error; sketches on faces additionally have certified anchors that never
  proximity-fallback. Patterns replay the *found* blend edges, not the original picks.
- **(d) Failure propagation:** per-feature `error` with the state frozen at the pre-failure
  model; evaluation continues; the CLI refuses to write anything unless `--allow-errors`
  (which writes the pre-failure bodies and keeps the errors visible); command-level errors
  stop the script immediately.

---

## 4. Identity-model comparison — SolidCraft vs our `bcdoc`

Read-only audit of `modules/document/bcdoc/entities.py`, `document.py`,
`docs/00-architecture/m1-module-contracts.md` §3.

| Aspect | SolidCraft (design `.solidcraft`, format `solidcraft/27`) | our `bcdoc` (`bcdoc/1` JSON) |
|---|---|---|
| Container | ZIP: `document.json` + `container.json` (`solidcraft-container/1`) | single JSON (Blender text block at M1) |
| Entity identity | **none per entity** — features have `id: u64` (monotonic, `next_id` persisted) + display `name` | per-entity **UUID4 hex** (immutable, never reused) + per-document **monotonic handle** (DWG-style, starts 0x1001) |
| Topology identity | **strings minted from lineage** (`F3:blend:F2:side:l2\|F2:top`, `F4:bore:side:0`), stored per feature; split pieces distinguished by neighbouring faces; edges by the faces they separate | none — v0 entities are drawing primitives (LINE/CIRCLE/ARC), no B-rep, no topology names |
| Mutation model | commands mutate a `Document`; every mutation re-runs the whole **timeline evaluation** (incrementally); undo = journal of feature edits | transactions only; every commit bumps **`doc_version`** (monotonic); undo re-applies reversed journal as a *new* transaction |
| Referential integrity | names looked up through the naming stack with graded matches (`Exact/Alias/Piece/Stem`) + loud failures | entity ids in fields; no parametric references at M1 |
| Derived state | evaluated `ModelState` per feature (cached, content-keyed); meshes shared lazily | Blender scene is a one-way derived display |
| Cross-process determinism | verified (§2.1) | byte-stable round-trip identity (per contracts doc §3) |

**These identity systems are NOT interchangeable.** A literal bridge would have to
translate, at minimum:

1. **Feature ids ↔ nothing.** bcdoc has no timeline; importing a SolidCraft design as bcdoc
   would have to *flatten* the evaluated `ModelState` into primitives (losing history) or
   introduce a new feature-table construct (out of scope for M1's document model).
2. **Topology names ↔ entity UUIDs.** A name like `F2:top#[F2:side:l4,F4:side:l4]` is
   *structural and regenerable* (recomputed on every rebuild, valid only inside the design
   that minted it); a bcdoc UUID is *opaque and never reused*. Mapping name→UUID per
   rebuild would need a stable correlation table maintained by the recompute step — and
   names legitimately *change* when topology splits/merges (with warnings), while UUIDs
   never do. The honest translation is: bcdoc keeps UUIDs for *its* entities; any adopted
   feature history needs its *own* reference vocabulary (names or ids) internal to the
   feature subsystem, mapped to bcdoc entity UUIDs only at the flattening boundary.
3. **`doc_version` ↔ evaluation.** bcdoc's monotonic version is commit-granular; SolidCraft's
   fingerprint/cache machinery is content-granular (per feature, per state digest). An
   integration must not conflate them: a doc_version bump says "the document changed", not
   "which features are stale".
4. **Units/coordinates:** SolidCraft is mm, Z-up, expressions carry units; bcdoc v0 is
   unit-free drawing units in world coordinates — a unit policy must be chosen at the seam.

---

## 5. Limitations of this evaluation

- Behavioural evidence comes from the **release binary** (tag `5de48e9`), 80 commits (50
  first-parent) behind the audited pin `3b4db52` — same day, but the gap includes timeline/
  MCP API work (`fb82ccb` "Timeline/MCP API: suppress lists, dotted edit keys,
  set_parameter expression"), chamfer/fillet geometry fixes (`3115c50`, `b4e049f`) and more;
  the commands this experiment uses (`parameters.change`, `timeline.edit`, `model.faces`,
  `solid.*`) all exist and behaved as documented in the binary, but pin-vs-binary drift is
  real and recorded, not waved away.
- Timing numbers are wall-clock on a 2-CPU/4-GiB container, single process each; they show
  *relative* structure (which commands re-ran), not benchmarkable absolutes (experiment C,
  W2-b, owns kernel benchmarking).
- `recomputed`/`restored` counts are self-reported by the engine; the timing decomposition
  corroborates them (edit cost ≈ downstream-only cost), but we did not instrument the
  evaluator itself (the harness cannot link `solidcraft-engine` — documented cadmpeg-ir
  OOM blocker).
- The marginal-tangency divergence (6-obs) is a single constructed case; it characterises a
  hazard class, not a rate.
- We did not test undo/redo restoration (`restored`) behaviourally — the CLI has `edit.undo`
  but it was out of the scenario list; the mechanism is source-verified only.

## 6. What a product integration would actually consume

- **Directly referenceable (docs + code reading):** the naming *vocabulary* and the
  four-layer architecture (boolean provenance → composed lineage → string names → graded
  lookup with loud failures) as the design to aim at; the engine tests
  (`naming_history_tests.rs`, `face_name_tests.rs`, `boolean_history_tests.rs`,
  `history_names_tests.rs`) are the best available executable specification of the
  behaviour contracts.
- **Adaptable (design-level):** chained-fingerprint prefix reuse + content-keyed result
  cache over *any* feature graph; stored persistent names + pick points as tie-breakers;
  per-feature error-with-frozen-state semantics; `recomputed`/`restored` counters in the
  API surface.
- **Not portable as-is:** the vendored truck-shapeops history (tied to truck's topology
  addresses and their boolean pipeline — meaningless atop OCCT); string names as *the*
  identity (they are regenerable, order- and adjacency-dependent, and legitimately change);
  the design container (a second document format, out of bounds per issue #1).

## 7. Recommendation input for TL2 (candidates #2 and #3)

**Candidate #2 — feature history / incremental recompute: ADAPT (design) + REFERENCE
(implementation).** The mechanism is real, tested, and measured here (edit recomputes 3/8
features at ~½ the full-build cost; determinism bitwise). What to adapt: the *evaluation
contract* — (i) monotonic feature ids, (ii) chained content fingerprints for prefix reuse,
(iii) per-feature error with frozen pre-failure state, (iv) loud write-gating. What not to
copy: their cache is in-process and state-digest-keyed; our `doc_version`/UUID model means
our reuse unit will be different (per-document transactions). The kernel-independent parts
live in `crates/doc/src/eval.rs` and are readable in isolation. Risk: low (pure design
adoption); effort: significant (a feature table + evaluator for our model).

**Candidate #3 — persistent naming: ADAPT at the document/design level, REFERENCE at the
kernel level.** The *behaviour contract* is exemplary and cheap to adopt: names stored per
feature, re-resolved by name with graded matches, pieces by adjacency, **failure over
silent retarget, unverified-names-announce-themselves** — all four verified behaviourally
here (scenarios 2/3a/3b/3c). The *kernel-level mechanism* (vendored truck-shapeops
`*_with_history` origins) is truck-specific and does not transfer to an OCCT-based product;
its OCCT analogue would be OCCT's own shape history (`BRepBuilderAPI_MakeShape::Modified/
Generated`) — equivalent information exists there, so the layered design transfers even
though the code does not. The geometric-voting fallback is worth knowing about but is
explicitly their second-class path. Risk: medium (naming design must be co-designed with
the kernel binding choice); recommend TL2 treat candidate #3 as *design-adoption now,
mechanism-decision after the kernel benchmark (W2-b)*.

---

## 8. Reproduction

```bash
cd experiments/solidcraft
./fetch-upstream.sh          # pinned 3b4db52 (source audit; not needed to re-run)
# release binary (see README §4) at /home/z/solidcraft-release/... (or $SOLIDCRAFT_CLI)
python3.12 python/w2_history_runner.py     # regenerates results/w2-history.json
```

Result regeneration note: timings vary run-to-run (wall clock); all geometry, names and
verdicts are deterministic per §2.1.

## 9. Files

- `fixtures/history/*.json` — 9 self-authored scripts (provenance headers inside).
- `python/w2_history_runner.py` — the driver (this document's numbers come from its output).
- `results/w2-history.json` — machine-readable results (envelope per `results/README.md`).
- `findings/w2-history.md` — this document.
