# Agent Permissions & Shared-Document Execution Model

- **Status:** Binding M0 specification — all items `planned`; nothing is implemented at M0
- **Owner:** W3 — Agent & skills (modules `agent`, `skills`)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)

## 1. Agent modes

Modes escalate capability: `read-only | propose | approve | autonomous` (glossary §6).

| Mode | Document capability | Approval burden | Typical use |
|---|---|---|---|
| `read-only` | Query/read tools only (non-transactional `cad.*`); no mutation previews | None — no mutations occur | "What is the total wall length on layer WALLS?" |
| `propose` | May build staged proposals with entity-level reviewable diffs (`cad.system.preview`) | **Every commit** approved by the user via an approval prompt | "Draft a title-block revision" |
| `approve` | Executes a user-approved **plan** without per-step prompts; deviations or high-impact ops re-prompt | One plan-level approval; per-step prompts suppressed within plan scope | Reviewed batch operations |
| `autonomous` | Auto-executes `doc-edit` within granted session scope; a checkpoint precedes every agent transaction group | None for in-scope doc-edit; every other permission class and all high-impact ops still prompt | Long, trusted, multi-step procedures |

**Defaults (binding):** every session starts in `read-only`; read tools are free in every mode; `doc-edit` behaves as `propose` unless the user explicitly escalates; `autonomous` is entered **only by explicit user action** (never agent-initiated), with a visible status indicator and a one-click stop.

**Transitions:** user-controlled only. An agent may *request* escalation; the request surfaces as a plain-language prompt and **denial is final for the session** — the same request is never re-prompted. Modes are **per-session** (agent session), not per-document, and are listed in `cad.system.permissions`.

**Persistence policy:** none by default — modes reset to `read-only` on application restart. A per-project "remember mode" option exists for `propose`/`approve` only; `autonomous` is never persisted across restarts (whether it is ever offered persistently will be decided from TP-CAT-10 usability results at M7).

**Mode indicators (binding):** the status bar shows the current mode at all times while a session is open (mode chip: `read-only` / `propose` / `approve` / `autonomous`); `autonomous` additionally colors the agent-area header and shows the one-click stop control. TP-CAT-10 validates that experienced CAD users can identify the mode in ≤ 2 s.

**Mode escalation request flow (binding):**

1. Agent calls a tool above its mode → adapter returns `CAD_E_PERMISSION_DENIED`; nothing is applied.
2. The agent may issue **one** escalation request per class per session; it surfaces as a plain-language prompt: "The agent wants to move from read-only to propose to draft these changes. [Show plan] [Allow] [Deny]".
3. Allow → mode changes for this session only; the change is recorded in the activity log (`approved_by: user:local`) and the status-bar indicator updates.
4. Deny → denied for the session; repeated requests for the same class are suppressed — no nagging.

## 2. Permission classes (7)

| Class | Plain meaning | Example prompt fragment |
|---|---|---|
| `doc-edit` | Change drawing/document content | "…wants to edit your drawing" |
| `terminal` | Run commands on your machine (project-scoped) | "…wants to run terminal commands in this project" |
| `filesystem` | Read/write files outside the document | "…wants to write /home/me/reports/out.pdf" |
| `network` | Network and browser access | "…wants to reach the web to look up the DIN standard" |
| `dependencies` | Install/update software packages | "…wants to install 2 Python packages" |
| `skill-install` | Install a skill package | "…wants to install skill *generate-title-block* (public tier)" |
| `publish` | Publish drawings, files or skill packages to others | "…wants to publish the sheet set to the team space" |

**Mission rule:** permissions must be comprehensible **before** execution. Every prompt uses the plain meanings above plus WHAT (grouped by class), WHICH files/entities, HOW BIG (counts), and WHAT CHANGES (diff/preview). Jargon-only prompts are a defect.

Standard prompt content (install or execute), rendered from the manifest/plan:

```json
{"kind": "skill-execute", "skill": "generate-title-block", "version": "1.0.0", "trust_tier": "team",
 "wants": [{"class": "doc-edit", "what": "insert 1 block, fill 6 attributes", "entities": {"added": 1, "changed": 0, "removed": 0}}],
 "files": [], "network": [], "packages": [],
 "diff": "preview:pv-3a…", "size": {"steps": 15, "max_steps": 40, "max_time_s": 60},
 "plain": "This skill edits your drawing only. No files, no network, no installs."}
```

Install-time variant (registry → local machine — shown before anything is installed or executed):

```json
{"kind": "skill-install", "skill": "generate-title-block", "version": "1.0.0", "trust_tier": "public",
 "validation": {"schema": "pass", "permission_review": "pass", "static_analysis": "pass", "integrity": "pass"},
 "declared_permissions": ["doc-edit"], "plain": "This skill edits drawings. Nothing else."}
```

## 3. Classes × modes matrix — who grants what

| Class | `read-only` | `propose` | `approve` | `autonomous` | Who grants |
|---|---|---|---|---|---|
| `doc-edit` | denied | propose-only; commits need per-transaction approval | plan-scoped auto-execution | session-scoped auto-execution + checkpoint per group; high-impact still gated | User (mode escalation) |
| `terminal` | per-action approval | per-action approval | per-action approval | per-action approval | User |
| `filesystem` | per-action; optional session pre-grant | same | same | same | User |
| `network` | per-action; optional session pre-grant | same | same | same | User |
| `dependencies` | per-action only | per-action only | per-action only | per-action only | User |
| `skill-install` | per-action only | per-action only | per-action only | per-action only | User |
| `publish` | per-action only | per-action only | per-action only | per-action only | User |

Binding rules:

- **Only `doc-edit` is mode-governed.** The other six classes **always require explicit approval regardless of mode** — including `autonomous`.
- Optional session pre-grants (stronger confirmation, visible indicator, revocable at any time) exist only for `filesystem` and `network`. `terminal`, `dependencies`, `skill-install` and `publish` are **always per-action**.
- **High-impact/destructive operations always require explicit approval regardless of mode:** bulk delete or bulk property edits affecting ≥ 20 entities (default threshold; configurable per project), purge-style operations, `cad.doc.restore` (discards post-checkpoint work), any file overwrite, publishing, terminal commands, dependency installs.
- Drawing edits, terminal, filesystem, browser/network, dependencies, skill install and publication are **separate permissions** — no bundling ("allow all"), no implied grants. Granting one never grants another.
- The permission authority is the CAD application (module `agent`); the sidecar only *receives* grants (see `zcode-adaptation-plan.md` §2). Grants are visible in a permission panel and **revocable mid-session with immediate effect**: new tool calls are denied; in-flight staged commits are re-checked at `cad.system.commit`.
- **Grant lifecycle** (all classes): `prompted → granted (per-action | session) → exercised (logged) → expired/revoked (logged)`. Every exercise writes an activity record even when pre-granted; every revocation writes an incident record. `terminal`/`dependencies`/`skill-install`/`publish` never survive a restart (per-action anyway); `filesystem`/`network` session pre-grants survive only as re-prompted preferences.

## 4. Shared-document execution model

- **Live sync:** the agent always works against the current committed document state. The sidecar receives `doc.version_changed` and `selection.changed` (schemas in `cad-tool-contract-v1.md` §7) and must not rely on long-lived caches without revalidation.
- **Agent transactions are grouped undo/redo units:** one committed `cad.system.preview` batch = **one undo step**, labeled `agent:<session>:<skill>` in the undo journal. One Ctrl+Z removes the whole agent group.
- **Previews + reviewable diffs:** every proposal produces an entity-level before/after diff (added/removed/changed) attached to the approval prompt; diffs are exportable.
- **Atomic-or-recoverable:** batches apply atomically; a mid-batch failure auto-rolls back — partial application is impossible by construction (module `document` transaction system). Named checkpoints (`cad.doc.checkpoints`) are available to skills and to the user.
- **Conflict detection rules (each defined precisely):**
  - **R1 — `doc_version` precondition:** every transactional call carries `base_doc_version`; on mismatch → `CAD_E_DOC_VERSION_CONFLICT`, nothing applied. The agent must re-read and re-plan; **blind retry of the same batch is forbidden** (re-preview required).
  - **R2 — `selection_epoch`:** selection-parameterized operations capture the epoch at preview time; if the user's selection changed by commit time → conflict, the agent re-selects.
  - **R3 — `entity_lock`:** previews acquire advisory per-entity locks (lapse after 600 s default, or at session end). A user editing a locked entity sees "the agent is working on this" and the pending preview is invalidated.
  - **R4 — user edits during plan:** any `doc.version_changed` invalidates that session's pending previews; the user gets an "agent is re-planning" notification; the agent re-validates against the new version before anything is presented for approval.
  - **R5 — incomplete-task reporting:** a run ends in exactly one state — `completed | failed-rolled-back | stopped-by-user | awaiting-input (timeout)`. **Never silent partial application.** Every failure produces a plain-language report: what was attempted, that nothing (or exactly one committed group) was applied, the checkpoint to recover from, and next options (retry, rollback, keep checkpoint).

**Hard prohibitions** (enforced by the adapter, tested in TP-CAT-07): the agent may not (a) write outside a transaction, (b) modify entities outside an approved preview during `approve`-mode plan execution, (c) bypass pagination with unbounded list requests, (d) call `cad.doc.restore` or bulk-delete tools without the high-impact approval, (e) touch the undo journal of other sessions.

**Worked conflict scenario (rules in action):**

1. User asks the agent (mode `propose`) to "annotate all beams".
2. Agent reads `cad.select.filter` → 34 ids at `doc_version` 50; builds a batch; `cad.system.preview {base_doc_version: 50}` → diff + locks on 34 entities.
3. The user meanwhile moves a wall → `doc_version` 51 → `doc.version_changed` fires.
4. The approval prompt is invalidated ("the drawing changed — the agent is re-planning"); notification shown (R4).
5. The agent re-reads the 34 entities at v51 — one beam was deleted by the wall move; it re-previews a 33-entity batch (R1).
6. New approval prompt with the updated diff; user approves; commit applies as ONE undo group labeled `agent:as-7f3a:annotate-beams`.

## 5. Activity and audit

Activity log = JSONL, one record per tool call (fields are binding):

```json
{"ts": "2026-10-19T09:15:32Z", "agent_session": "as-7f3a", "tool": "cad.geometry.transform",
 "request_digest": "sha256:9f2c…", "result_status": "ok", "doc_version_after": 46,
 "approved_by": "user:local", "mode": "propose"}
```

- `request_digest` = SHA-256 of the canonical request JSON (size-bounded, no raw secrets). Skill runs additionally keep a step-level **execution log** (`run_id`, `step_id`, tool, args digest, status, ts).
- **User-visible activity panel:** every record appears as a timeline entry (time, tool, outcome, doc version, mode); clicking opens the diff or undo group. The panel is the primary "what did the agent do to my drawing" surface.
- **Retention:** project-local, rolling 90-day default (configurable); exportable as JSONL/CSV from the panel; execution logs are bundled into incident reports.
- Security-relevant events (denials, revocations, quarantines, detected sandbox violations) are duplicated into an append-only, hash-chained **incident log** (`prev_digest` field; exportable).

Activity panel mapping (log record → UI) and an incident record:

| Field | Panel rendering |
|---|---|
| `ts`, `tool` | timeline row |
| `result_status` | outcome icon; click-through to the diff or undo group |
| `doc_version_after` | document-version badge |
| `mode`, `approved_by` | authority context ("auto (autonomous)" vs "approved by you") |

```json
{"ts": "…", "kind": "permission-revoked", "class": "filesystem", "agent_session": "as-7f3a",
 "prev_digest": "sha256:…", "digest": "sha256:…", "details": "revoked by user mid-run"}
```

## 6. Approval UX

- **Non-blocking:** approval prompts appear in the agent area with a status-bar badge; the drawing view stays fully usable while a prompt is pending (conflicts are handled by R1–R4, not by freezing the user).
- **Diff attached:** every transaction approval shows the entity-level diff from `cad.system.preview`.
- **Timeout + deny:** default 300 s (configurable per project); timeout = deny, recorded as `approved_by: "timeout-deny"`. The agent is told to abandon that branch.
- **Approval history:** per-session list of approvals/denials with timestamps and diffs, exportable; approvals are attributed (`user:local`).

**Prompt rendering rules:** (1) diff-first — the entity-level diff is the primary content, prose secondary; (2) numbers before adjectives ("34 entities", not "many entities"); (3) every prompt names the permission class in plain language (§2 table); (4) one decision per prompt — no "approve all future steps" shortcuts; (5) prompts never steal focus from the drawing view.

```mermaid
sequenceDiagram
    participant A as Agent (sidecar)
    participant P as Permission authority (app)
    participant U as User
    A->>P: cad.system.preview {batch}
    P-->>U: approval.requested (badge + diff; drawing view stays usable)
    U->>P: approve / deny / ignore (300 s timeout = deny)
    alt approved
        P-->>A: approval.resolved {granted: true, approval_id}
        A->>P: cad.system.commit {preview_id, approval_id}
        P->>P: re-check grants + doc_version, apply → one undo group
    else denied or timeout
        P-->>A: approval.resolved {granted: false}
        Note over A: abandon branch; report
    end
```

## 7. Security model

Defense-in-depth order (each layer assumes the previous may fail):

1. **Never expose:** tools outside the session's effective allowlist are not callable at all (transport-level method-not-found).
2. **Decline:** the adapter checks mode + class per call (`CAD_E_PERMISSION_DENIED`).
3. **Confirm:** high-impact/destructive operations require explicit approval (§3).
4. **Contain:** script/terminal scopes are declared and (best-effort) confined — labels below.
5. **Observe:** everything is activity-logged; GUI automation is watchable live.
6. **Recover:** checkpoints, undo groups, revocation, quarantine.

- **Least privilege:** sessions start `read-only` with zero classes granted; every grant is scoped (per-action default; session pre-grant only for `filesystem`/`network`); revocation is immediate.
- **Permission review at skill install:** the manifest's declared permissions are shown in plain language before install; unvalidated third-party skills are never auto-granted (`skill-execution-and-publishing.md` §4).
- **Destructive-op confirmation:** the high-impact list in §3.
- **Sandboxing, honestly labeled** (no security theater — every claim carries one label):

| Mechanism | What it does | Label |
|---|---|---|
| Declarative engine tool allowlist | Skill steps may call only manifest-declared `cad.*` tools; per-call permission + mode check | **enforced** (in-process, adapter-side) |
| Expression sandbox | Read-only dotted paths + allowlisted pure functions; no eval, no side effects, no host access | **enforced** (interpreter has no host bindings) |
| Script subprocess (skill `scripts/`) | Declared interpreter only; scrubbed environment (secrets removed unless declared); filesystem limited to declared dirs; network off unless declared **and** granted | **best-effort** (OS-level; per-platform gaps below) |
| Terminal tool | Project-scoped cwd; per-action approval; full activity logging | **best-effort** (commands run with the user's OS rights) |
| GUI/computer-use automation | Permission-gated; observable (live view + log); checkpoints + pause/abort | **advisory + procedural** (cannot be technically confined) |

- **What we cannot fully sandbox today (explicit):** (1) OS-level process, file and network confinement for scripts and terminal commands is best-effort and differs per platform — Linux namespaces give strong isolation; Windows/macOS equivalents are weaker or different (per-platform matrix delivered at M5, (verify) per platform); (2) GUI automation and terminal commands run **with the user's OS rights** — they are permission-gated, observable and revocable, not sandboxed, and our UI must not imply otherwise; (3) a malicious native dependency can escape process-level confinement — dependency installs stay explicit-approval and provenance-checked, but we do not claim kernel-grade isolation.

Script declarations are machine-checked against actual use (static analysis gate at install/publish):

```json
{"scripts": [{"file": "scripts/export_bom.py", "interpreter": "python3",
              "filesystem": [{"mode": "read", "path": "assets/bom"}, {"mode": "write", "path": "out/"}],
              "network": [], "env_allowed": ["PROJECT_ROOT"]}]}
```

Per-platform confinement status (final labels delivered at M5 per platform; each row (verify) then):

- **Linux:** namespaces/seccomp-backed sandbox for script subprocesses — target label **best-effort**, trending to enforced for declared scopes.
- **Windows:** no namespace equivalent; confinement = restricted token + declared-path ACLs — **best-effort with documented gaps**.
- **macOS:** system sandbox profiles exist but break declared-file workflows in ways we will document before release — **best-effort**; GUI automation remains unconfinable everywhere.

## 8. Failure taxonomy and user-facing reporting

| Failure | Detection | User-facing report | Recovery |
|---|---|---|---|
| Tool error (contract error code) | tool response `status: "error"` | plain message + code + tool | agent retries/adjusts per `retryable` |
| Version conflict | `CAD_E_DOC_VERSION_CONFLICT` | "The drawing changed while the agent worked; it will re-plan" | re-preview against the new version |
| Kernel failure | `CAD_E_KERNEL_FAILURE` | "The geometry engine failed; nothing was changed" | auto-rollback; retry once; report if persistent |
| Limit exceeded (steps/time/loop bounds) | executor counters | "The skill exceeded its declared limits; stopped and rolled back to checkpoint" | rollback; fix skill or explicitly raise limits |
| Permission denied / revoked | permission check | "Permission denied (revoked during the run)" | stop branch; ask the user |
| Sidecar crash | process watch | "The agent runtime stopped; your drawing is safe" | restart + resync; session marked `interrupted` |
| Partial application | impossible by atomicity — if ever observed it is a **defect** | defect report | restore named checkpoint |

**Recovery drills (binding):** TP-CAT-07 drills cover conflict/rollback paths (user edits during plan, crash during commit, undo of agent groups); TP-CAT-09 drills cover security paths (mid-run revocation, sandbox escape attempt from a script, quarantined skill handling). Drills run scripted in CI per release and results are recorded as milestone evidence.

Every failure report renders this structure (plain language first, detail on demand):

```json
{"what": "The title-block skill could not place the block.", "state": "failed-rolled-back",
 "applied": "nothing", "checkpoint": "pre-insert",
 "reason": {"code": "CAD_E_DOC_VERSION_CONFLICT", "plain": "the drawing changed while it worked"},
 "options": ["retry against the new version", "keep checkpoint and stop", "undo everything"]}
```

Incident reporting: any detected sandbox violation, revocation or quarantine event produces an incident record (§5) and, for confirmed security incidents, follows the registry policy in `skill-execution-and-publishing.md` §6 (report → quarantine → revoke). Release notes must list every new known platform gap discovered by drills — hiding a gap is a process violation, not an engineering choice.

## 9. Cross-references

- Tool mechanics, envelopes and event schemas: `cad-tool-contract-v1.md` (§4, §7).
- Sidecar architecture, providers, GUI-automation path: `zcode-adaptation-plan.md` (§2, §3, §6).
- Skill manifests, declared permissions, workflow limits: `skill-format-v1.md` (§2, §3).
- Skill execution state machine and registry gates: `skill-execution-and-publishing.md` (§1, §4).
- Drills and suites: TP-CAT-07 (tools/sync/conflict/rollback), TP-CAT-09 (security), TP-CAT-10 (usability).
