# W3 (lane a) — MCP agent-interface PoC: driving the real SolidCraft server headlessly

- **Experiment:** `w3-mcp` (results: [`results/w3-mcp.json`](../results/w3-mcp.json))
- **Owner:** W3 lane-a worker, Task ID **99 (retry — the first attempt died without leaving
  artifacts; this run started from Task-96/98 context only)**, issue #1 candidates
  **#5 (typed command registry)**, **#6 (MCP/CLI/control + transactions/rollback)**,
  **#7 (skills/automation)**
- **Behavioural evidence:** the checksum-verified official release binary
  `solidcraft-cli 0.16.2` (tag commit `5de48e9`, **80 commits behind the source pin
  `3b4db52c10279251a068cfca5eb7447068bc28e7`** — measured by W2; 3 of the 80 commits touch
  `crates/mcp`, 3 the CLI app), driven by `python3.12 experiments/solidcraft/python/mcp_client_probe.py`
  (stdlib only). Source audit uses the pin. **58 probe cases × 2 runs: 54 pass / 0 fail /
  4 info / 0 blockers; run 2 byte-identical to run 1** after normalising paths, pids and the
  engine's self-reported `"ms"` step timings (geometry and all error strings compared exactly).
- **Verdict in one line:** their MCP surface is a small, hard, honest envelope (15 tools over a
  394-command engine registry, two-layer validation, bounded filesystem, checkpoint rollback)
  that works exactly as documented — recommend **adapt the wire protocol + envelopes +
  bounded-FS rules (candidate #6), adapt the CommandSpec metadata model (#5), reference the
  skills' verification-first content patterns while keeping our own format (#7)** — §6.

---

## 1. MCP architecture (source + behaviour)

All source paths relative to `/home/z/solidcraft-upstream/`, line numbers at the pin.

**Framing.** JSON-RPC 2.0 over the server's stdio, one message per line
(`crates/mcp/src/server.rs:69-112`): one line in → at most one line out; notifications get no
reply (verified: `notifications/initialized` produced no output, probe H3); JSON-RPC arrays
are answered with one array line (probe H5); empty array → `-32600 "empty batch"` (H9);
oversized lines → `-32600 "request too large"` (`MAX_LINE`, server.rs:98); malformed lines →
`-32700` **and the server keeps serving** (H7: ping answered right after a parse error —
server.rs:74-79). stdout carries only protocol; diagnostics (including the startup scope
listing) go to stderr — captured verbatim per session in the result JSON.

**Lifecycle.** `initialize` negotiates the protocol version (server.rs:139-147): an asked-for
version in {2025-06-18, 2025-03-26, 2024-11-05} is echoed (H1/H2b); anything else falls back
to the server's newest, 2025-06-18 (H2, verbatim observed). The reply carries
`serverInfo {name, title, version}`, `capabilities {tools, resources}` and — notable — a
modelling **`instructions`** string written *for the agent* (a compressed usage manual:
command shapes, the model-like-a-person workflow, which tools verify). The `initialized` flag
exists (server.rs:125-130) but **nothing enforces it**: `tools/list` and `ping` answer before
any handshake (probes P1/P2, separate process). Lenient, not a security issue here (stdio,
same user), but a divergence from MCP client expectations we should not copy.

**Two backends, one tool set** (`crates/mcp/src/backend.rs:14-29`): every tool call becomes a
control-channel method (`engine.execute`, `document.inspect`, `ui.render`, …) answered either
by a **`Headless`** in-process session (what we drove; CPU rasterizer, no window) or a
**`Remote`** bridge to the running desktop app over loopback TCP with a per-launch token
(`crates/engine/src/control_auth.rs`). The remote path has carefully-engineered failure
semantics: `engine.batch` is never sent twice (backend.rs:153-162, fresh connection, write
errors final because the app may have run it); a lost app mid-session returns a *tool error*
that says "inspect the design before sending a change again" rather than pretending.

**Tools** (`crates/mcp/src/tools.rs`): 15 tools, each a thin wrapper over engine commands
(tools.rs:378-440: `undo`→`edit.undo`, `save`→`file.save`, `measure`→`inspect.measure`, …).
Each tool declares an **`Effect`** (tools.rs:30-39: ReadOnly / Edits / Replaces / Files) that
becomes MCP **annotations** (`readOnlyHint`, `destructiveHint`, `openWorldHint`,
`idempotentHint`; tools.rs:41-55) — "for clients that ask before running tools (or
auto-approve on these hints). Clients … must not be told less than the truth (#205)". This is
client-side approval data, honestly labelled — the mirror image of our server-side permission
classes (§4b).

**Batch semantics** (tools.rs:511-578): steps run in order; on the first failure the reply is
`{ok:false, completed, failed:{index, command, error}, rolled_back, undone, results:[…]}` and
the server restores an **engine checkpoint** taken before step 0 (`edit.checkpoint` /
`edit.restore_checkpoint`, tools.rs:462-507) — the design, the active sketch *and the undo
history* return exactly; older apps fall back to depth-counted undos. `rollback:false` keeps
the completed steps (verified: probe TR5 left the box body behind; TR6 showed one `undo`
removes it — batch steps are individually undoable). 10 000 steps max (tools.rs:13).
`verbose:false` compacts replies (tools.rs:621-634) — created ids and body deltas stay.

**Resources:** `solidcraft://design` (inspect JSON) and `solidcraft://commands` (catalog);
unknown URI → `-32002` (probe R3).

## 2. Tool inventory (probes T1/T2)

15 MCP tools, by declared effect class:

| Class (Effect) | Tools |
|---|---|
| read-only (5) | `list_commands`, `inspect_design`, `measure`, `body_topology`, `crash_reports` |
| edits (3) | `set_parameter`, `undo`, `redo` |
| replaces (1) | `new_design` |
| files — read/write/overwrite/delete (6) | `execute`, `batch`, `screenshot`, `export`, `open`, `save` |

Behind them: **394 engine commands** (probe T2, `engine.commands` via `list_commands`), top
prefixes: `sketch.*` 105, `solid.*` 35, `timeline.*` 21, `surface.*` 19, `construct.*` 19,
`component.*` 17, `inspect.*` 16, `joint.*` 16, `parameters.*` 13, `sheet.*` 12, `motion.*` 10,
`render.*` 10, `file.*` 9 … The MCP layer is a **narrow waist**: one generic `execute`
(command id + params object) plus five convenience tools; all modelling knowledge lives in the
engine registry and is *served to the agent as documentation* (`list_commands` → id, label,
tab/panel, shortcut, one-line parameter docs, enabled-now + disabled-reason).

## 3. Probe narrative (verbatim evidence in `results/w3-mcp.json`)

### 3.1 The CAD chain — modelled like the docs' "typical session", verified analytically

`set_parameter` ×3 (width 40, height 30, depth 20 mm; each reply `errors: []`) → one `batch`
of 10 steps: `sketch.create {plane:XY}` → `sketch.line {points:[4 corners], closed:true}`
(created ids: curves `l1..l4`, points, auto-coincident `k1`) → 4 ×
`sketch.constraint.horizontal_vertical` → 2 × `sketch.dimension` (values are **expressions
naming the parameters**: `"width"`, `"height"`) → `sketch.finish` → `solid.extrude
{distance:"depth"}` (feature id 2, `created_bodies: ["Body1"]`).

- **Volume: 24000.0 mm³, rel_err 0.0** vs analytic 40×30×20 (probe C3; total area 5200 mm²,
  6 faces / 12 edges / 8 vertices, mass 30.96 g).
- **Sketch fully constrained: `dof: 0`, `status: "solved"`** via `inspect_design` (C4); 4
  curves, 7 constraints (4 HV + auto-coincident + 2 dimensions as constraints), 2 dimensions.
- Second sketch with `sketch.arc.three_point` + `sketch.circle.center` (C5): created
  `a1`/`c1` curve ids; **bodies unchanged** (no profile consumed) — line/arc/circle element
  coverage without perturbing the analytic check.
- **Parameter edit `width` 40→50** (C6): reply `recomputed: 3, errors: []`; volume
  **30000.0 mm³ (rel_err 0.0)** = 50×30×20. `parameters.list` at the end shows the wiring:
  `d1 {expression: "width", uses: ["width"]}`, `d2`, `d3` — every sketch dimension and feature
  input is already a parameter, so parametric recompute is one call.

### 3.2 Transactions / rollback (probes TR1–TR6, SV1)

- `undo` after the parameter edit → `{"undone": "Change Parameters"}`; volume back to
  24000.0; **undo depth 16→15** (`inspect_design` exposes `undo`). `redo` → 30000.0
  (`{"redone": "Change Parameters"}`), undo again → 24000.0.
- **Failing batch with rollback** (TR3): `[solid.box 10³ ok, solid.fillet {edges:[[999,999,999]]}
  fails]` → verbatim reply:

  ```json
  {"ok": false, "completed": 1,
   "failed": {"index": 1, "command": "solid.fillet",
              "error": "invalid parameters for `solid.fillet`: no edge at [999, 999, 999]: the nearest edge is 1678.417 mm away"},
   "rolled_back": true, "undone": 1, "results": [ …box result… ]}
  ```

  State fingerprint (volume, area, face/edge counts, body names, undo depth) **identical
  before/after**. Single failing `execute` (TR4): tool error, state identical — "failures
  leave the design unchanged" holds at both granularities (engine snapshot restore,
  `crates/engine/src/lib.rs:671-676, 707-716`).
- **`rollback:false`** (TR5): same batch → box survives (volume 25000, 2 bodies, depth 16);
  one `undo` removes it (TR6).
- **Serial/version fields** (SV1): persisted `document.json` (zip container) — `format
  "solidcraft/27"`, `next_id` 1 → 4, feature ids `[1,2,3]` (Sketch1, Extrude1, Sketch2);
  `document.inspect` additionally exposes a `revision` counter (1 on the untouched base
  design) and `undo`/`redo` depths — but **no optimistic-concurrency precondition anywhere**
  (§4c).

### 3.3 Schema validation — which layer answers (probes SC1–SC9)

Two distinct layers, exactly as documented (docs/mcp.md "Errors"):

| Probe | Input | Layer + verbatim reply |
|---|---|---|
| SC1 | `body_topology {}` | JSON-RPC **-32602**: `body_topology: missing required argument `body`` |
| SC2 | `body_topology {body: 5}` | -32602: `body_topology: argument `body` must be of type "string"` |
| SC3 | `screenshot {source: "sideways"}` | -32602: `screenshot: `source` must be one of ["window","model"]` |
| SC4 | unknown tool `warp_drive` | -32602: `unknown tool `warp_drive`` |
| SC5 | `measure {bodeez}` | -32602: `measure: unknown argument `bodeez`` |
| SC6 | `execute {command: 42}` | -32602: `execute: argument `command` must be of type "string"` |
| SC7 | `execute solid.extrude {distance: "twenty"}` | **tool result isError**: `invalid parameters for `solid.extrude`: distance: expression: unknown parameter `twenty`` |
| SC8 | `solid.extrude {operation: "explode"}` | isError: `unknown operation `explode` (new, join, cut, intersect)` |
| SC9 | `execute solid.warp_drive` | isError: `unknown command `solid.warp_drive`` |

The split: **envelope/schema problems are JSON-RPC errors before the engine runs**
(`check_arguments`, tools.rs:302-335 — required, unknown-arg, type, enum, top level only);
**engine semantics are tool results with `isError: true`** the model can read and correct.
The engine messages carry *allowed values* and *nearest-match distances* — the actionable-
error quality bar our `CAD_E_VALIDATION` messages should meet.

### 3.4 Filesystem security — every documented rule, verified behaviourally (FS0–FS10)

Server started with `--in designs/base.solidcraft`, **no `--allow-path`**, cwd = the run
folder; stderr at startup: `solidcraft mcp: files limited to /home/z/.local/share/solidcraft/recovery,
/tmp/solidcraft-mcp-<pid>-<seed> and the open design's folder (--allow-path DIR adds one,
--allow-any-path lifts the limit)`. Every refusal is a tool error
`<path>: outside the folders this agent may use (<roots>); allow another folder with
`--allow-path DIR`` and **nothing was written** (existence checked on disk after each probe):

| Probe | Attempt | Observed |
|---|---|---|
| FS0 | save to the **cwd** (run folder) | refused — "The working folder the server was started in does not count by itself" |
| FS1 | save `/etc/w3-mcp-leak.solidcraft` | refused, file absent |
| FS2 | **open `/etc/passwd`** | refused: `/etc/passwd: design container: /etc/passwd: outside the folders…` |
| FS3 | export `/etc/w3-mcp-leak.step` | refused, file absent |
| FS4 | save `~/.config/w3-mcp-leak.solidcraft` (hidden) | refused, file absent |
| FS5 | `designs/../escaped.step` (**`..` escape**) | refused (path printed unresolved, compared resolved), file absent |
| FS6 | `designs/.env` (hidden **file** in design folder) | refused — design-folder roots never reach hidden entries |
| FS7 | `designs/.hidden/x.solidcraft` (hidden **folder**, pre-created) | refused |
| FS8 | `designs/noexist/x.solidcraft` (missing folder) | `its folder does not exist (nothing exists below <designs>); create the folder first` — reported missing, **not created**, and not a reason to widen scope |
| FS9 | symlink `designs/lnk-to-etc → /etc`, save through it | refused (resolved before comparison — "saving through a link writes the file it points to") |
| FS10 | save `designs/w3-probe.solidcraft` (positive) | ok, 363-byte container written |
| S0B | hidden file inside a **`--allow-path` root** (setup session) | **allowed** — "A folder named here is reached in full, hidden files included" |

This is the documented model (docs/mcp.md "Which files the agent can reach") implemented in
`crates/io/src/vfs.rs`: `PathScope` roots (recovery + private `/tmp/solidcraft-mcp-<pid>`
scratch, 0700, `crates/mcp/src/lib.rs:53-68`) + the open design's folder **only when strictly
inside home (or temp), not hidden, not home itself** (`design_folder_refusal`, vfs.rs:160-184;
`with_design`, vfs.rs:201-212; hidden components excluded even inside design roots,
vfs.rs:258-261); paths resolved (symlinks, `..`) **before** comparison (vfs.rs:225-255);
missing folders reported as missing only when the nearest existing folder is already in scope
(so the message can't probe the disk, vfs.rs:266-290); the scope is installed per tool call
via a thread-local (`vfs::scoped`, server.rs:159-161) that even the sketch-text font loader
honours (vfs.rs:410-422). Default-deny, escalation by explicit `--allow-path`.

### 3.5 Rendering, resources, shutdown, reproducibility

- **Screenshot headless without GPU** (G1): *worked* — content blocks `[image, text]`,
  `renderer: "cpu"`, verbatim warning: "drawn by the CPU rasterizer (no GPU adapter
  qualified, or SOLIDCRAFT_GPU=cpu): surface analysis colours, highlights and legends are not
  drawn; `solidcraft-cli gpu` lists the adapters". 13 741-byte PNG at 96×64. Measurement —
  not pixels — remains the verification path (as our briefing requires).
- `crash_reports` (R4): `{"dir": "/home/z/.local/share/solidcraft/crashes", "reports": []}`.
- **Clean shutdown** (S0X/PX/X1): closing stdin → the server exits **code 0 in 0.0 s**, no
  orphan process (pid re-check after reap). The full 58-probe suite runs in **0.5 s** per run
  (native binary, tiny geometry) — the whole double-run PoC completes in ~1 s.
- **Reproducibility (run 2)**: all 58 cases re-run in a fresh tree of fresh processes;
  pass flags, geometry values and every error string **identical**. The only byte-level
  variance anywhere is the engine's self-reported per-step `"ms"` timing fields (isolated in
  a dedicated determinism check: two processes, same 10-step batch → identical except
  `"ms": 1.021429` vs `"ms": 0.876684`) — matching W2's finding for `solidcraft-cli run`.
- **Temp-path variance, classified (close-out)**: the comparison normalizer redacts
  run-dir paths and the engine's scratch pid-seed folder names before diffing. At the pin,
  the runtime form is always `solidcraft-mcp-<pid>-<seed-hex>` (`crates/mcp/src/lib.rs`:
  `format!("solidcraft-mcp-{}-{:x}", std::process::id(), seed)`; pid is a u32 decimal, never
  empty), so the digit-less variant `solidcraft-mcp--<seed-hex>` cannot occur — residual
  temp-path variance is an **environment-only difference**, never affecting any recorded
  outcome. The normalizer nonetheless also accepts the digit-less form (defensive coverage
  for future pins; upstream churn is a recorded risk) and this is now **regression-tested**
  in `tests/test_mcp_normalizer.py` (11 checks: both forms collapse to one token,
  upstream test-fixture-style names stay untouched, geometry is never redacted, a real
  geometry difference still diffs, and the committed `w3-mcp.json` envelope re-normalizes
  to its recorded identical/no-diffs verdict under the hardened normalizer). The
  determinism claim is scoped to exactly this normalized comparison — pass flags plus
  normalized verbatim evidence with geometry and error strings compared exactly — and is
  not a claim of byte-identical raw transcripts.

## 4. Mapping onto our contracts (READ-ONLY analysis)

### (a) Their MCP tools ↔ our `cad-tool-contract/v1` (62 tools, 13 namespaces)

Direct counterparts (ours ↔ theirs):

| Our tool | Their surface | Fit |
|---|---|---|
| `cad.doc.info` / `cad.doc.status` | `inspect_design` | theirs richer (timeline, sketches, DOF, undo depth; ours has entity_counts + undo_depth — the undo-depth-in-status idea already matches) |
| `cad.calc.measure`, `cad.calc.mass_properties` | `measure` (bodies) + `measure {items}` | strong; theirs adds min/max/center-distance/angle/slot per pick pair |
| `cad.geometry.query` | `measure {items}`, `body_topology` | partial (theirs is pick/point based, ours id based) |
| `cad.view.screenshot` | `screenshot` | near-identical shape (b64 image + text info block) |
| `cad.io.export_*` | `export` (step/3mf/stl/obj/urdf) | counterpart; format sets disjoint (3D part vs 2D drawing) |
| `cad.system.capabilities` | `tools/list` + `list_commands` | theirs = MCP discovery + engine catalog; ours is one typed registry |
| `cad.system.rollback` | `undo`/`redo` + `edit.checkpoint`/`edit.restore_checkpoint` | theirs is step-wise + exact-snapshot; ours is group-wise + named checkpoints |
| `cad.system.preview`/`commit` | `batch` | **semantic split**: theirs executes immediately (rollback on failure); ours stages for approval — same atomicity, different trust flow |
| `cad.doc.checkpoints`/`restore` | `edit.checkpoint`/`edit.restore_checkpoint` (engine cmds) | direct |
| `cad.skills.*` | — | no counterpart (their skills live in the agent, not the app) |
| `cad.system.events` (SSE) | — | **no counterpart at all** — pure request/response |

Tools of ours with **no typed counterpart** on their MCP surface but reachable through their
generic `execute` (394 commands): `cad.geometry.create/transform/edit` (sketch.*/solid.*),
`cad.edit.set_properties` (appearance.assign, browser.visibility), `cad.select.*`
(select.*), `cad.layers.*` (no layers in a 3D part CAD; browser.visibility is the cousin),
`cad.blocks.*` (component.create/insert — semantic cousin), `cad.annotate.*`
(sketch.dimension/sketch.text), `cad.layouts.*` (2D-only, absent), imports
(file.insert_step/mesh). Two of ours have no analogue anywhere in their design:
`cad.select.filter`'s predicate query language, and pagination (`limit`/`cursor`) — their
catalog and inspect replies are unbounded single JSON blobs (they manage size with
`verbose:false` compaction instead). Conversely, theirs has **`set_parameter`** — a first-class
parametric driver with `recomputed`/`restored` reporting — for which our v1 contract has
**no namespace at all**; if we ever grow parametrics, that tool shape (and its per-dimension
auto-parameters `d1…dn` that make "make it parametric" a one-call edit) is the reference.

The deepest structural difference: **they expose 1 generic `execute` + self-describing
catalog; we expose 62 typed tools.** Their boundary schema is deliberately thin (`params:
object` passthrough — check_arguments validates only the wrapper), pushing validation into
the engine where the error messages are excellent but *not machine-checkable*. Our per-tool
JSON Schemas + `CAD_E_VALIDATION` give a checkable contract at the cost of 62× schema
maintenance (CI drift-check already planned). For candidate #5 this is the central data
point: the *registry metadata* (their `CommandSpec`) and the *boundary schemas* (our design)
are complementary, not competing.

### (b) Their permission/bounded-FS model vs our session modes + permission classes

They have **no in-server permission authority**: no modes, no classes, no approval flow, no
activity log. Three mechanisms instead:

1. **Bounded filesystem (server-enforced, default-deny)** — `PathScope` + vfs checks,
   behaviourally verified above. This is the *containment* layer of our
   permissions-and-execution-model §7 ("Contain"), implemented at the only layer a headless
   server can actually enforce. Our `filesystem` permission class (per-action approval,
   optional session pre-grant) is *consent*; their scope is *containment*; the two compose —
   an approval to write should still only ever write inside an allowed root. Their design
   details worth stealing: resolve-before-compare, hidden-always-outside design-folder roots,
   named-roots-reach-hidden (explicit > implicit), missing-folder-not-probeable, per-pid
   0700 scratch, `--allow-any-path` as an explicit, documented escape hatch.
2. **MCP tool annotations (client-enforced)** — the `Effect` → hint mapping is *declaration
   for the client's approval UI* ("must not be told less than the truth"). Our per-tool
   "Perms" columns in cad-tool-contract §6 are the same information, enforced server-side.
   When our MCP transport lands (#6), emitting both is nearly free: server-side classes for
   us, `readOnlyHint`/`destructiveHint`/`openWorldHint` for MCP clients that auto-approve.
   Their 4-class Effect enum (ReadOnly/Edits/Replaces/Files) is a good minimum granularity —
   note `new_design` is separately marked destructive ("Replaces") exactly like our
   high-impact list treats `cad.doc.restore`.
3. **Loopback auth for the bridged case** (`control_auth.rs`): per-launch random token in a
   0600 file under the data folder, constant-time compare, dropped on exit
   (control_auth.rs:11-97). This is transport auth, the analogue of our `session_token`
   (contract §1) — but per-*launch*, not per-*session*, and it carries no mode/grant binding.
   Our token binds identity + mode + grants and is revocable mid-session; theirs protects
   "another local user can't drive your app", nothing more.

Net: their model answers "what can this process touch on disk" and "what may the client
auto-click"; ours additionally answers "what did the user consent to, per session, per class,
with an audit trail". Both are needed; neither subsumes the other.

### (c) Their undo/recovery vs our `base_doc_version` + atomic transactions + undo journal

| Mechanism | SolidCraft (observed + source) | cad-tool-contract/v1 + permissions doc |
|---|---|---|
| atomicity | per-command snapshot restore (`engine lib.rs:671-676`, failure restores `before.doc`); `batch` = checkpoint + rollback of *all* completed steps | one transactional call = one `bcdoc` transaction; `preview`/`commit` batch = one undo group; mid-tool failure auto-rolls back |
| rollback unit | one command / one batch (unnamed `u64` checkpoint; restores undo history + active sketch too) | one undo group labelled `agent:<session>:<skill>`; named checkpoints; `cad.system.rollback` by group or checkpoint |
| concurrency control | **none** — single design per session; staleness surfaces as loud engine errors (W2's s3c: "no edge at [40,15,10]: the nearest edge is 10.000 mm away") and as prose advice ("inspect the design before sending a change again") | `base_doc_version` precondition (R1) + `selection_epoch` (R2) + `entity_lock` (R3) + `doc.version_changed` events (R4) |
| version serials | `document.inspect` exposes `revision` and `undo`/`redo` depths; persisted doc has monotonic `next_id` + feature ids — **displayed, never used as a precondition** | `doc_version` monotonic, echoed in every envelope, *enforced* on every transactional call |
| crash recovery | autosave entries + lock files + orphans (`recovery.rs`); `crash_reports` with replay paths; crash journal records commands for replay | checkpoints + undo journal + activity/incident logs; no replay-from-journal equivalent |

What their design teaches: (i) **exact-snapshot checkpoints are cheap and enough** for
single-actor sessions — `edit.checkpoint`/`edit.restore_checkpoint` restoring *the undo
history itself* is a stronger guarantee than depth-counted undo and is what makes `batch`
rollback correct however long the history is; (ii) **stale-reference errors that carry the
nearest-match distance** are a complete conflict story for one actor, at zero protocol cost —
but they degrade silently to "re-inspect everything" for multi-actor documents, which is
exactly what our R1-R4 rules exist for. Their `revision` counter sitting unused in inspect is
the cautionary mirror: we must keep `doc_version` *load-bearing*, not decorative. Keep our
model; adopt their checkpoint semantics as the implementation bar for `cad.doc.checkpoints`.

### (d) Their skills vs our skill-format/v1 + ADR-0006

Their four skills (`skills/solidcraft-{modeling,editing,checking,mechanisms}/SKILL.md`,
agentskills.io format: frontmatter name+description + workflow prose + `reference.md` +
optional `scripts/`) have **zero runtime machinery**: no manifest schema, no permissions, no
DSL, no executor. The value is entirely in the *content discipline*, which is genuinely
superior to anything we have written down:

- **Verification-first loops everywhere**: "predict, then measure once" against
  self-computed values; "a cut or chamfer that leaves the volume unchanged has missed, even
  though it reported success"; timeline health checks after every stage; the parameter
  *range walk* (drive every driving parameter to both ends of its range and back, requiring
  clean `dof 0` + matching volumes at every state); exact STEP comparison via build123d as an
  **external oracle** ("SolidCraft does not use, link, vendor or ship any of it" — the same
  oracle discipline as our W1/W2 harnesses).
- **A trap catalog**: nine numbered traps with concrete failure modes (zero-dimension
  sketches that mirror silently, boolean retries that leave wrong geometry with only a WARN,
  fractional pattern counts rounding without error…). This is executable-experience writing,
  the thing a `recorded → generalized` pipeline (our glossary §7) is supposed to produce.
- **Executable documentation tests**: `test_facts.py` "checks every trap and convention
  below… After a SolidCraft upgrade, run the tests and fix the text where they fail" —
  documentation that CI keeps honest. Our skill `tests/assertions.yaml` covers outcomes;
  nothing of ours yet covers *the skill text itself*.
- **Batch-economy guidance**: 3-4 large batches, ~10-13 calls per clean build; predictable
  sketch ids so later steps reference `l1…l4` without reading replies; `verbose:false` for
  reply-size control. Token/call economics as a first-class authoring concern.

Our skill-format/v1 (manifest + 10-step DSL + fixtures + SHA256SUMS + trust tiers +
permission declarations) is aimed at a different problem: third-party, untrusted, reviewable
skills. Theirs is first-party knowledge for a trusted agent. ADR-0006's declarative-first
decision stands; what their skills add is the *authoring standard* for workflow content
(verification loops, trap catalogs, call economics, doc-tests) that our DSL steps should
encode and our authoring guide should demand.

### (e) The integration seam for Blender-CAD, without adopting their runtime

A future control surface speaking `cad-tool-contract/v1` over MCP can take these pieces
(their stdio framing and envelopes teach most of the wire design):

1. **Transport**: JSON-RPC 2.0, newline-delimited stdio, one-in/one-out, array batches,
   `MAX_LINE` cap, parse-error-then-keep-serving, stdout protocol-only / stderr diagnostics.
   Cheap, debuggable with a pipe (our whole PoC client is ~300 lines of stdlib Python).
2. **Handshake**: `initialize` version negotiation + **`instructions` for the agent** — we
   should ship contract usage guidance + verification discipline (their instructions embed
   the model's workflow; ours should embed our "typed API over screenshots" mission rule).
   Enforce the initialized gate (they don't — P1).
3. **Two-layer errors, exactly their split**: transport/schema problems → JSON-RPC
   `-32601/-32602` (our method-not-found + envelope validation); domain outcomes → tool
   result with `isError: true` carrying our `CAD_E_*` structured error object in the text
   block. Never domain errors as JSON-RPC errors.
4. **Content-block replies**: text (pretty JSON) + image blocks for `cad.view.screenshot`;
   size caps; `verbose:false`-style compaction for large lists — or, better, our pagination.
5. **Annotations**: emit MCP hints from our Perms columns (readOnlyHint for non-transactional
   read tools, destructiveHint for high-impact, openWorldHint for `cad.io`/`terminal`).
6. **Bounded FS for every file-touching tool**: a `PathScope` equivalent in the adapter
   (default-deny roots + design-folder rule + resolve-before-compare + hidden-exclusion) —
   this is server-side containment our `filesystem` class currently only *consents* to.
7. **Batch envelope**: their `{ok, completed, failed:{index,command,error}, rolled_back,
   undone, results[]}` shape is the right reply for `cad.system.commit` failures (which step,
   what ran, what was undone) — strictly better than a bare error string.
8. **Resources**: `cad://capabilities`, `cad://activity` as MCP resources for client-side
   discovery beyond tools/list.

What not to take: their lack of version preconditions/events (we need multi-actor), the
unbounded replies (we have pagination), the `params: object` passthrough (we want typed
schemas at the boundary).

## 5. Source audit — bounded notes (pin `3b4db52`)

- **`crates/mcp/src/*.rs` (5 files, ~1 550 lines total).** `server.rs` (185): framing +
  lifecycle + dispatch table (§1 above); error codes -32700/-32600/-32601/-32602/-32603/-32002
  (lines 18-23); JSON-RPC arrays ≤ 1000 (line 26). `tools.rs` (751): tool definitions with
  hand-written JSON schemas + Effect annotations (§1); `check_arguments` validates **top level
  only** (302-335); `batch` checkpoint/rollback machinery (462-578); `screenshot` render
  pipeline with scratch-dir writes read back and deleted (639-733); own base64 (736-751).
  `backend.rs` (319): `Backend` trait → control methods; `Remote` (bridged) with never-resend
  `engine.batch` (153-162) and one fresh-connection retry for plain calls (186-189);
  `Headless` with CPU `CpuHost` fallback (229-239) and `ui.render` writing through the vfs
  scope (289-293). `lib.rs` (71): `agent_scope` (recovery + scratch + `--allow-path`s) and
  the 0700 per-pid scratch dir. `tests.rs`: the whole surface is also covered by in-crate
  tests driving sessions "only through MCP" (box → fillet → hole, parameters, batch rollback,
  hostile arguments) — the seam is testable exactly the way our TP-CAT-07 contract tests plan.
- **`crates/engine/src/control_auth.rs` (131)**: per-launch loopback token; 0600 file +
  0700 dir; constant-time compare (44-47); env override for sandboxed clients; token file
  removed on exit (91-97). Auth = "another local user can't drive the app", full stop.
- **`crates/engine/src/recovery.rs` (396)**: one autosave entry per running app
  (`<id>.solidcraft` + `<id>.json` + `<id>.lock` held while running); atomic writes; an
  unlocked entry = a crash (or unsaved close) → offered for recovery at next launch; exposed
  to agents as `doc.recovery_list`/`doc.recover`/`doc.recovery_discard` *inside the default
  scope* (the recovery folder is an agent root — docs/mcp.md).
- **`crates/engine/src/cmd/` registry shape**: every command is a static `CommandSpec`
  (`cmd/mod.rs:98-121`): `id, label, tab, panel, icon, shortcut, params (one-line docs),
  enabled: fn(&Session) -> Result<(),String>, run: fn(&mut Session, &Value) -> Result<Value>,
  undoable, live (gesture frames), reads_model, planned(issue#)`; builder methods
  (123-180); `command_specs()` concatenates ~47 per-file `COMMANDS` slices in toolbar order
  (233-284); `find_command` exact then case-insensitive (286-289); unknown-command errors
  append up to three nearest ids (298+, `solid.extrud` → `solid.extrude` — the typo-suggestion
  behaviour our `CAD_E_ENTITY_NOT_FOUND`-style messages should match). `Session::execute`
  (engine `lib.rs:662-735`): enabled-check → `Snapshot{doc, active_sketch, pending_moves}` →
  `catch_unwind` around `run` (panics become `EngineError::Internal`, design restored) →
  undo push with `MAX_UNDO` trim, redo clear. The `solidcraft-cli commands` JSON (via
  `engine.commands`, `cmd/inspect.rs:44,313`) is the catalog the MCP `list_commands` serves.
- **`apps/solidcraft-cli/src/bench_agent.rs` (239)**: their *agent benchmark* generates a
  ~1 300-body bicycle **in code** (no fixture): frame tubes, two wheels with every spoke and
  nipple placed one by one, patterned chainring teeth, cassette, a chain of individual links,
  cockpit/seat, ~240 three-part fasteners — "built the way an agent builds one over MCP, one
  small command at a time". It times **each command plus the display work a window needs**
  (`world_state().warm_meshes`, line 186) in rolling 100-command windows (mean/max ms, bodies
  so far), then saves and runs `bench-open`. What it measures: per-command latency *including
  interactive display cost* as designs grow — i.e. agent-session ergonomics, not kernel
  throughput (that's the oracle/bench suite W2 covered). The shape is a good template for our
  agent-track benchmark: an agent-realistic workload, statistics per growth window, no
  fixtures.

## 6. Recommendation input for TL2 (candidates #5, #6, #7)

**#5 typed command registry — ADAPT (their CommandSpec metadata) + keep our typed boundary.**
Their registry is the strongest single artifact: static specs with `enabled` predicates,
`undoable`, effect metadata and one-line param docs, exposed as the agent's documentation,
with engine-side validation whose error messages set the quality bar (allowed values inline,
nearest-edge distance, typo-suggested command ids). Our `bccmd.Registry` (name/alias → spec)
is much thinner; our cad-tool-contract schemas are much stronger at the boundary. Adopt into
the registry design: per-command metadata fields (undoable/effects/enabled), catalog-as-
documentation, and the message-quality bar for validation errors. Do not adopt the
`params: object` passthrough — our `CAD_E_VALIDATION` + JSON Schemas stay.

**#6 MCP/CLI/control + transactions/rollback — ADAPT the wire surface; REFERENCE the
transaction internals.** Adapt: stdio JSON-RPC framing, initialize+instructions, two-layer
error split, content-block replies, MCP annotations from our Perms columns, batch failure
envelope, resources, and the bounded-FS `PathScope` rules as server-side containment for the
`filesystem` class (default-deny roots, resolve-before-compare, hidden exclusion, named roots
reach all). Reference: `edit.checkpoint` exact-snapshot semantics (restores undo history —
the bar for `cad.doc.checkpoints`), the never-resend-a-batch rule for any future remote
transport, per-pid scratch hygiene. Keep ours: `base_doc_version`/R1-R4/events (multi-actor),
preview→approval→commit (consent), undo groups. Evidence quality: high — every claim above is
backed by a verbatim probe reply in `results/w3-mcp.json`.

**#7 skills/automation — REFERENCE the content patterns; KEEP skill-format/v1; one ADAPT
candidate.** Their skills prove the payload is workflow knowledge: verification-first loops,
parameter-range walks, DOF-0 discipline, trap catalogs, call/batch economics, and doc-tests
that keep prose honest across engine upgrades. Keep our manifest/DSL/tiers (their format has
no trust model and would not survive third-party distribution). Adapt candidate: ship
first-party "checking" skills in *both* forms — a DSL workflow for the engine plus a prose
skill for the agent runtime — and adopt the executable-doc-test idea (our skill
`tests/assertions.yaml` extended to validate the skill's own guidance text against engine
behaviour, the `test_facts.py` pattern).

## 7. Limitations (honest)

- Behavioural evidence is the **release binary, 80 commits behind the audited pin** (3 of
  those commits touch `crates/mcp`). Observed drift so far: the release's `instructions`
  text ("in the style of Autodesk Fusion") differs from the pin's ("an independent
  parametric 3D CAD app"). No behavioural discrepancy found in any probed rule.
- Single headless backend exercised; the **bridged** (`--connect`) backend, its token lookup
  and app-disconnect error paths were read in source only (no desktop app in the sandbox).
- Single-client, single-session concurrency only — their server serialises naturally
  (stdio); concurrent-client behaviour is untested and unclaimed.
- No GPU: screenshots verified via the CPU rasterizer (with its warning); geometry
  verification used `measure`, as required.
- `undo`-depth trajectory (15-16 at these design sizes) was recorded but not stress-tested
  against `MAX_UNDO` truncation.
- MCP protocol coverage: lifecycle, tools, resources, ping, JSON-RPC error paths; sampling/
  roots/elicitation were not probed (the server does not advertise them).

## 8. Reproduction

```bash
cd /home/z/blender-cad
python3.12 experiments/solidcraft/python/mcp_client_probe.py
# requires the checksum-verified release binary at
#   /home/z/solidcraft-release/solidcraft-0.16.2-linux-x86_64/bin/solidcraft-cli
# writes results/w3-mcp.json (both runs); scratch under experiments/solidcraft/scratch/w3/
```

## 9. Files

- `experiments/solidcraft/python/mcp_client_probe.py` — the PoC driver (stdlib only;
  3 server sessions per run: setup `--allow-path`, no-initialize prelude, main `--in`
  design; 58 probe cases; runs everything twice and diffs).
- `experiments/solidcraft/results/w3-mcp.json` — machine-readable envelope (generator
  command, upstream SHA + binary sha256 + tag/commits-behind, timestamps, host facts,
  verbatim observed replies, run-2 reproducibility record).
- `experiments/solidcraft/findings/w3-mcp.md` — this document.
