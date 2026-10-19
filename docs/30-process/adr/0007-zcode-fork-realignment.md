# ADR-0007 — ZCode fork realignment: pinned mirror `main`, `gen/archive` preservation, `cad-adaptation` patch branch

- **Status:** Accepted — M1 entry, 2026-10-19 (UTC)
- **Owner:** TL
- **Vocabulary:** [docs/GLOSSARY.md](../../GLOSSARY.md) (binding; §15 amendment record)
- **Supersedes:** the "fork pristine" statement in docs/GLOSSARY.md §2 (handoff note) and the implicit assumption in docs/20-agent/zcode-adaptation-plan.md §1 that fork `main` tracks the pin — both are corrected here with recorded facts.

## Context

At M0 handoff (2026-10-19) the ZCode runtime pin was recorded as upstream
`zai-org/ZCode` @ `0a1fc56d279fd1001f78387bd81aec1c26767411` (v3.16.1). The
fork `payswapdotorg/ZCode` was assumed to mirror upstream. An audit at M1
entry (2026-10-19, GitHub API + local git) established the actual state:

### Audit facts (recorded 2026-10-19)

| Item | Finding |
|---|---|
| Upstream main HEAD | `0a1fc56` (2026-10-19T02:34Z, "chore: sync ZCode source") — the pin IS the current upstream main head |
| Fork `main` HEAD | `c3cc34f1d01a059517f13d3dea962c48e49fe309` — diverged: 35 commits ahead of the fork base, 2 behind the pin |
| Fork base (merge-base) | `29628c9a` (upstream "feat: update v3.14.3") |
| The 2 upstream commits the fork lacked | `aac4755` (2026-10-10, upstream "feat: update to v3.15.1") and `0a1fc56` (the pin itself) — upstream's own history; no product work lost by realignment |
| The 35 fork-only commits | The complete **"Gen Creative Intelligence OS" program** (2026-10-04 → 2026-10-09): media/editor agent-OS work — provider plane, editor adapters (MLT/FFmpeg/Kdenlive/Natron/LosslessCut/Blender-as-editor), timeline artifact graph, escalation plane, MOS lab/arena, W13–W18 waves. **Unrelated to the ZCode agent runtime** and **unrelated to Blender CAD**; the program is closed (closeout records on `gen/archive`, e.g. "program closeout record W9-W18 … cold-start battery 331/331"). |
| Other fork branches | `w1`–`w8`, `w13`, `w18`, `feat(w13|15|17)` (Gen worker delivery branches, merged into fork main via TL-verified merge commits) and `directive/gen-native-product-ui` (`7ea52fad`, 2026-10-14, docs-only W19 work-order proposal — never executed) |
| Fork tags at audit | none |

### Why this state existed

The `payswapdotorg/ZCode` repository began as the source-of-truth repo of the
prior Gen program (GitHub created it under the network-root cache name "Gen";
it was renamed `ZCode` at M0). The Gen program pushed its history to the
fork's default branch. Blender CAD inherited that repo as its runtime fork at
M0 — so the fork's `main` carried 35 unrelated commits and was NOT a mirror
of the pinned upstream revision.

## Decision

1. **`main` is a pristine pinned mirror of the upstream pin.** Fork `main` is
   reset to exactly `0a1fc56` (verified `identical` against `zai-org/ZCode`
   main: ahead 0, behind 0). Fork `main` must contain **zero product commits**;
   it exists so that the pinned revision is unambiguously present in the org.
2. **`upstream-pin-0a1fc56` is the immutable mirror ref.** An annotated tag on
   the fork at the exact pinned upstream SHA, message referencing the release
   manifest. Tags are immutable under the pin policy (glossary §8): any pin
   change creates a NEW tag + a manifest version bump; this tag is never
   moved.
3. **`gen/archive` preserves the legacy program verbatim.** Branch at
   `c3cc34f` (the legacy main head). All Gen branches (`w1`–`w18`,
   `feat(w13|15|17)`, `directive/gen-native-product-ui`) are left untouched.
   Nothing was deleted; the merge commits that existed only on legacy `main`
   remain reachable through `gen/archive`. The Gen program's records stay
   queryable; they are simply not on the runtime mirror.
4. **`cad-adaptation` is the product patch branch.** Created at the pin
   `0a1fc56` per zcode-adaptation-plan §4.3. Every product patch to the runtime
   lives there, documented in a `PATCHES.md` ledger on that branch; the series
   is empty at M1 entry. `cad-adaptation` is never fast-forwarded from
   upstream; it only advances through reviewed patches on top of the pin, and
   re-pins follow the ADR-0004 audit procedure + manifest bump.
5. **Runtime source of truth = upstream pin, not the fork.** Until this ADR,
   code that said "use the fork" was ambiguous. Binding resolution: the
   runtime is built from `zai-org/ZCode` @ `0a1fc56` (identical to fork `main`
   and the `upstream-pin-0a1fc56` tag — all three name the same tree). Any
   future divergence between those three refs is a defect. Entry-point
   compatibility is tested against this exact tree (see
   docs/20-agent/zcode-runtime-spike-m1.md).

## Consequences

- The GitHub fork banner now reads `main` == upstream (unambiguous); drift
  detection (TP-CAT-11) watches `zai-org/ZCode` main vs the manifest pin as
  before.
- Future ZCode pin changes: fetch upstream, audit (ADR-0004 checklist), move
  `main` + create new `upstream-pin-<sha>` tag + rebase `cad-adaptation` via
  `git range-diff` + manifest version bump. Never silent.
- The Gen program's history remains public and reachable (`gen/archive` + its
  branches); nothing about it is claimed, shipped or audited by Blender CAD.
- Blender fork symmetry: `product/main` created at the pinned upstream ref
  `bf200615` (patch series empty ⇒ branch == pin), mirroring this decision for
  the host application; the apply-check gate runs canonical-side (see
  docs/30-process/upstream-update-ci.md §"apply-check (M1)").

## Alternatives considered

- **Leave `main` as the Gen history and add mirror branches** — rejected:
  "main carries 35 unrelated commits" is exactly the ambiguity this ADR
  removes; every tooling path (Actions default branch, compare banners,
  clones) would keep landing on the wrong tree.
- **Delete the Gen history** — rejected: violates the preservation
  requirement and destroys prior org work.
- **Rebase Gen commits onto the pin** — rejected: meaningless (unrelated
  program) and would rewrite public history that already has closeout records.
