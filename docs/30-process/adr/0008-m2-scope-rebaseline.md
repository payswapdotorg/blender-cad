# ADR-0008: M2 scope re-baseline — operator-directed acceptance core, kernel-bound drafting commands rescheduled

- **Status:** Accepted (2026-10-19)
- **Owner:** TL
- **Context:** milestone-plan.md §5 (committed at M0) defines M2 as "drafting
  core parity" with deliverables spanning precision input, layers/blocks,
  annotation engine v1, layouts + PDF publish, DXF xrefs, and grip editing,
  and an exit criterion of "TP-CAT-01 full category green (every P0 drafting
  command exercised)". The operator M2 directive (handoff TL1) narrows the
  immediate acceptance scope to four areas — A precision input, B layers and
  blocks, C annotations and dimensions, D layouts — and instructs: "If the
  existing repository defines a different M2 order or scope, follow the
  repository and update the plan with evidence", plus "Do not expand the
  scope indiscriminately."

## Decision

1. **M2 acceptance = the operator's four areas plus the drafting-core P0
   subset that is analytically implementable without the geometry kernel**
   (PLINE, RECTANG, POLYGON, POINT, XLINE, RAY, ELLIPSE, CIRCLE 2P/3P,
   MIRROR, OFFSET, ARRAYRECT, BREAK, JOIN, EXPLODE, STRETCH, MATCHPROP,
   SELECT modes, noun-verb selection, repeat-last, SETVAR/GETVAR, autocomplete
   suggestions, dynamic-input toggle). This is codified in
   `docs/00-architecture/m2-module-contracts.md` §0.
2. **Kernel-bound P0 commands are rescheduled to M3** (TRIM, EXTEND, FILLET,
   CHAMFER, PEDIT, HATCH, SPLINE): their robust implementations require
   curve intersection/trimming, boundary detection and NURBS machinery that
   this repository deliberately schedules with the OCCT kernel at M3
   (ADR-0002). M2 ships the analytic subset (BREAK/JOIN/STRETCH/OFFSET) and
   the osnap intersection point math — the kernel work composes on top.
3. **GUI-bound P0 items stay planned with headless-honest notes**
   (grip-mode cycling, right-click menus, visual autocomplete popup):
   pixel-level interaction is not headless-verifiable (M1 completion graph
   §7 precedent); the bpy-free logic underneath each is implemented and
   unit-tested where it exists.
4. **P1 items named by the milestone plan move to their inventory-priority
   slot** (xrefs, PDF publish/plot pipeline, WBLOCK, PURGE, annotative
   scales): they remain `planned`, now targeted at M3 (plot pipeline +
   xrefs with the interop window) rather than silently dropped.
5. **TP-CAT-01 "full category green" is NOT claimed at M2 exit.** The
   category activates per-section; the M2 exit record lists exactly which P0
   sections are green, which are partial, and which are rescheduled (3 of
   the 8 DRAW P0s and 4 of the 18 MOD P0s move to M3 with reasons).

## Consequences

- M2 remains independently buildable and testable; no capability is claimed
  without an automated test + evidence artifact (glossary §11 unchanged).
- The milestone plan §5 receives an evidence-based status note (like M1's
  §4) and the M2 completion graph records per-item status.
- The kernel decision (ADR-0002) is untouched: OCCT adoption still gates at
  M3 entry.
- Product risk accepted: users cannot TRIM at M2; BREAK/STRETCH/OFFSET cover
  the common editing paths. This is the smallest coherent, honest scope.
