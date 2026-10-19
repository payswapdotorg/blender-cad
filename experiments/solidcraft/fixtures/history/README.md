# History/naming fixtures (experiment `w2-history`)

- **Author:** TL2-W2 (history/naming lane worker), date 2026-10-19.
- **License:** same as this repo (experiments tree) — all files here are **self-authored**
  command scripts; the command ids and parameter shapes were discovered from
  `solidcraft-cli commands` (official v0.16.2 release binary) and the upstream test
  conventions (`tests/action_matrix/designs/*.json`, MIT OR Apache-2.0, read for format only).
  `s3b-shell-*.json` re-uses the *idea* (not the numbers) of upstream engine test
  `aee47fc`-era `crates/engine/src/naming_history_tests.rs::a_shell_fillet_does_not_follow_a_gone_edge_onto_a_smooth_seam`;
  this is stated in each file's `provenance` block.
- **Consuming experiment:** `python/w2_history_runner.py` → `results/w2-history.json`
  (findings: `findings/w2-history.md`).

| File | Role |
|---|---|
| `s1-baseline.json` | baseline parametric chain (params `len`/`h` → sketch → extrude → fillet → hole → faces + measure) |
| `s2-edit-len.json` | edit script run with `--in` the design saved from `s1-baseline.json` (`len` 40→50) |
| `s2-full-control.json` | the same final model built from scratch (pick points at the new coordinates) |
| `s3b-shell-baseline.json` | plate → corner fillets → inside shell → inner-corner fillets (named-edge references) |
| `s3b-shell-edit.json` | `timeline.edit` Shell 5→2 mm: removes the named edges → must fail loudly |
| `s3c-stale-pick.json` | imperative script with a stale fillet pick point → must refuse |
| `s4-bad-fillet.json` | unbuildable fillet radius (200 mm on a 10 mm edge) |
| `s6-big-upstream.json` | expensive features upstream (fillet + 8-hole pattern) of a param-driven pocket |
| `s6-edit-slot.json` | `--in` edit of `slot_x`/`slot_w` only (incrementality probe) |
| `s6-full-control.json` | the same final model from scratch (cross-path equality) |
| `s6-marginal-tangency.json` | slot wall placed exactly on a hole axis (marginal-geometry observation) |

Regenerate results: `python3.12 python/w2_history_runner.py` (from `experiments/solidcraft/`).
