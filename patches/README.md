# Blender Fork Patch Series

- **Status:** policy active — series currently EMPTY (zero core patches at M0)
- **Owner:** TL (upstream sync is a TL responsibility, glossary §10)
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** docs/GLOSSARY.md (binding)

This directory holds the **canonical copies** of the native patch series applied
to the Blender fork (`https://github.com/payswapdotorg/blender`, branch
`product/main`). The extension repo is the source of truth for the series: a
patch that is not mirrored here does not exist.

## Patch-series policy

1. **Provenance.** Patches are produced with `git format-patch` against the
   pinned upstream `blender/blender` `main` (pin recorded in the current
   `release-manifests/manifest-*.json`). Never hand-edit generated patch files.
2. **Naming.** Files are named `NNNN-slug.patch` (`0001-...`, `0002-...`),
   numbered in application order; renumbering only at a series rebase, which is
   a reviewable event.
3. **Mirroring.** Every patch applied on the fork's `product/main` branch is
   mirrored here, byte-identical, in the same commit that applies it upstream.
4. **Per-patch documentation.** Each patch is documented in the table below with:
   - **purpose** — what the patch changes and why it cannot live in this repo;
   - **owner** — the responsible worker (glossary §10);
   - **upstream-status** — submitted upstream to blender/blender? If not, a
     written justification is required (upstream-first is the default);
   - **guard test** — the test-plan item (TP-CAT-NN, docs/30-process/test-plan.md)
     that fails if the patch is dropped, so every patch stays load-bearing.
5. **Minimal surface.** The product is engineered so that the bulk of CAD code
   lives in this extension repo. A new core patch requires a written case and a
   guard test before merge — patches are a last resort, not a habit.
6. **Pin discipline.** The upstream pin never silently changes: a re-pin always
   requires a release-manifest version bump (glossary §8) and drift-issue
   triage (docs/30-process/upstream-update-ci.md).

## Planned CI apply-check (M1)

A `workflow_dispatch` workflow will live **in the Blender fork** (not in this
repo) that clones upstream `blender/blender` at `main` HEAD and applies this
series with `git apply --check` / `git am`. The series must apply clean on
upstream HEAD at all times; a failure is a red workflow in the fork and must be
triaged like an upstream-drift alert. **Actions must be enabled on the fork**
for this to run — this is an M1 entry criterion (docs/30-process/milestone-plan.md).

## Current series

| Patch | Purpose | Owner | Upstream status | Guard test |
|---|---|---|---|---|

**CURRENT STATE (honest):** the series is **EMPTY** — zero core patches exist at
M0. No Blender core modifications are required by the M0 architecture; the CAD
engine, toolsets and agent integration all live in this repo. When the first
patch lands, the table above gains a row and the guard test must already exist.

## See also

- `docs/00-architecture/repo-and-upstream-sync.md` — the full update procedure; `docs/30-process/upstream-update-ci.md` — drift CI, issue policy, local commands.
- `release-manifests/manifest-0.1.0.json` — the current upstream pin.
