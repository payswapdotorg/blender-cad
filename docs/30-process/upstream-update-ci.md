# Upstream Update & CI — Workflows, Drift Alerts, Local Commands

- **Status:** Active — workflows committed at M0; Blender drift check and ZCode audit run on schedule; patch-apply CI planned for M1
- **Owner:** TL (upstream sync is a TL responsibility, glossary §10)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)

## 1. Why this exists

Blender CAD stands on two living upstreams: `blender/blender` (the host
application fork) and `zai-org/ZCode` (the agent runtime). Upstream pins are
policy, not convenience: **pins never silently change; a re-pin requires a
release-manifest version bump** (glossary §8). Three CI workflows enforce that
discipline — one always-on, one weekly, one monthly.

## 2. The three workflows

| Workflow | File | Trigger | Purpose |
|---|---|---|---|
| M0 repo consistency | `.github/workflows/ci.yml` | push (all branches), pull_request, workflow_dispatch | run the TP-CAT-00 repo-consistency suite (merge gate) |
| Upstream drift — Blender | `.github/workflows/upstream-blender-drift.yml` | schedule `0 6 * * 1` (Mondays 06:00 UTC) + workflow_dispatch | compare the pinned Blender ref with `blender/blender@main` |
| Upstream audit — ZCode | `.github/workflows/upstream-zcode-audit.yml` | schedule `0 6 2 * *` (2nd of the month 06:00 UTC) + workflow_dispatch | compare the pinned ZCode ref with `zai-org/ZCode@main` |

### 2.1 `ci.yml` — M0 repo consistency

Installs `requirements-dev.txt`, runs `python -m pytest tests/ -q` (the six
repo-consistency tests) and byte-compiles `scripts/` with
`python -m compileall scripts -q`. Green = merge gate passed (test-plan §6.1).

### 2.2 `upstream-blender-drift.yml` — weekly Blender drift

Runs `python scripts/check_upstream_drift.py --component blender` with
`GITHUB_TOKEN` from the workflow environment. The script loads the latest
`release-manifests/manifest-*.json`, takes the pinned
`components.blender.upstream_ref`, and compares it with the sha of
`blender/blender@main` via the GitHub API.

- In sync → exit 0, log says `in sync (<sha>)`, workflow green.
- Drift → exit 2, log says `DRIFT: pinned <a> vs upstream <b>`, workflow red.
- API/rate-limit error → exit 1 with a clear message (check whether `GITHUB_TOKEN` is set / rate limits were hit).

### 2.3 `upstream-zcode-audit.yml` — monthly ZCode audit

Same mechanics for `--component zcode` against `zai-org/ZCode@main`, monthly.
Special case: if the pinned ref starts with `pending:` the script prints an
audit notice and exits 0 — the human API-surface review (§6) is still
outstanding and no automated comparison is possible.

## 3. Drift-alert issue policy

Both scheduled workflows end with an `actions/github-script@v7` step that runs
`if: failure()`:

- Label: **`upstream-drift`**.
- **Dedupe by title:** the step searches open issues with that label; if an
  issue titled `Upstream drift: blender/blender` (resp.
  `Upstream drift: zai-org/ZCode`) exists, it **comments** on it with the new
  run link; otherwise it **creates** the issue. One tracking issue per
  upstream, never a pile of duplicates.
- The issue body links the failed run and the update procedure; the run log
  distinguishes real drift (exit 2) from an API error (exit 1).
- The issue is closed by the pull request that lands the re-pin (which must
  bump the manifest version). An open upstream-drift issue does not block the
  merge gate, but it does block the **milestone gate** (test-plan §6.2: drift
  is either green or consciously triaged).
- The scheduled workflows carry `permissions: contents: read, issues: write` —
  the least privilege needed to file triage issues. No other secrets are used;
  `GITHUB_TOKEN` is the ephemeral workflow token.

## 4. Local commands

```bash
# install the dev dependencies (PyYAML, pytest)
python3 -m pip install -r requirements-dev.txt

# the whole repo-consistency suite (what CI runs)
python3 -m pytest tests/ -q

# individual checks
python3 scripts/render_inventory.py --check        # generated tables in sync?
python3 scripts/validate_manifest.py              # release manifests valid?
python3 scripts/check_module_boundaries.py        # module graph valid?

# upstream drift, exactly like CI (GITHUB_TOKEN optional, avoids rate limits)
GITHUB_TOKEN=… python3 scripts/check_upstream_drift.py --component blender
GITHUB_TOKEN=… python3 scripts/check_upstream_drift.py --component zcode
```

Exit codes for the drift script: `0` in sync / audit-pending, `1` HTTP or
manifest error, `2` drift. All other scripts: `0` ok, `1` violations.

## 5. The full update procedure

The authoritative, step-by-step procedure lives in
`docs/00-architecture/repo-and-upstream-sync.md`. Summary of the loop:

1. **Alert** — a scheduled workflow fails; the deduped issue gains a comment.
2. **Assess** — review the upstream delta between the pin and HEAD: release
   notes, API surface touched, breaking changes for the fork and extension.
3. **Decide** — adopt now, adopt at the next milestone boundary, or defer with
   a written reason on the issue. Deferral is legitimate; silence is not.
4. **Re-pin** — rebase the patch series (`patches/`, currently empty) if any;
   run the fork apply-check (from M1, §7).
5. **Verify** — run TP-CAT-06 (native Blender regression) plus the currently
   blocking suites on the re-pinned build.
6. **Record** — update the release manifest: new `upstream_ref` **and a
   manifest version bump** (glossary §8); update `patches/README.md` if the
   series changed; link CI evidence in the milestone report.
7. **Close** — merge; the merge closes the drift issue; the next scheduled run
   goes green (or comments again if HEAD moved meanwhile — expected for
   Blender, which moves weekly).

ZCode re-pins additionally require the §6 audit to be completed first; a
`pending:` ref is resolved by exactly this procedure.

## 6. ZCode audit checklist — automated check vs human review

The monthly workflow only automates the **sha check**. The **API-surface
review** is human (W3 + TL), per this checklist:

- [ ] Diff `packages/rpc` (the RPC contract — our versioned seam, ADR-0004)
      between the pinned ref and the candidate ref; any breaking change means
      the adapter window opens before adoption.
- [ ] Diff `packages/server`, `packages/zcode-server-cli` (headless server
      runtime) for CLI/protocol changes affecting the sidecar bridge.
- [ ] Diff `packages/provider`, `packages/provider-node`,
      `packages/model-option-map` for model-provider surface changes.
- [ ] Re-confirm the candidate/excluded package list from glossary §6
      (e.g. `packages/zcode-cua`, `packages/services`, `.agents/skills`,
      `skills-lock.json`); any re-scoping is recorded as an **ADR amendment**.
- [ ] License check: still Apache-2.0; no new restrictive transitive deps.
- [ ] Record the audit outcome on the drift issue (or a new one if the check
      itself was green but the review found concerns), then pin the audited
      sha with a manifest version bump.

## 7. Planned patch-apply CI in the Blender fork (M1)

**M1 decision (recorded, 2026-10-19): the apply-check runs CANONICAL-side.**
The workflow lives in THIS repo (`payswapdotorg/blender-cad`,
`.github/workflows/patch-apply-check.yml`, workflow_dispatch + weekly): it
clones the fork's `product/main` and applies the `patches/blender` series in
order. Rationale vs the original M0 sketch above (in-fork): a workflow file
committed to the fork is itself a product commit — it would break the "fork
`main` is a pristine upstream mirror" invariant (repo-and-upstream-sync.md
§4/§2.3) and the empty-patch-series state. The canonical-side job exercises
exactly the same gate (series applies cleanly on the pinned fork branch; empty
series asserts `product/main` == pin) without polluting the fork. **Actions
remain enabled on the fork** (verified 2026-10-19) — the M1 entry criterion is
met, and the in-fork option stays open should a patch ever require fork-side
build infrastructure. The canonical copies of the patches and the per-patch
documentation live in `patches/README.md` (current series: empty).

## 8. Honesty note

These workflows detect drift; they do not fix it. Adopting an upstream change
is always a deliberate, evidenced act: manifest bump, regression battery,
recorded review. No automation in this repo may rewrite a pin.
