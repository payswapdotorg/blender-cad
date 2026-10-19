"""pytest scope guard for the SolidCraft experiment lane (close-out fix).

Why this exists: `python -m pytest -q` at the repo root (the E-experiment
regression command recorded in docs/00-architecture/solidcraft-evaluation.md
§10) walks the whole tree. On a dev host that has re-run the experiments, the
gitignored `scratch/` directory contains permission-probe artifacts including
mode-000 fixture directories (`lnk-to-etc/credstore`, `ssl/private`, …) which
make pytest's collector raise PermissionError — six collection errors that
have nothing to do with any test. A clean checkout is unaffected (scratch is
gitignored), but the recorded command must work in both states.

This conftest is EXPERIMENT-LANE-ONLY infrastructure (no production file is
touched — the repo-root conftest.py belongs to the product and stays as-is).
It keeps pytest out of the regenerable/external state while still collecting
the lane's own regression tests under tests/.
"""

collect_ignore = [
    "scratch",     # regenerable run artifacts incl. mode-000 permission fixtures
    ".upstream",   # external clone at pinned SHA (fetch-upstream.sh) — huge tree
    ".release",    # external release binary tree (fetch-release.sh)
    "harness",     # Rust harness (cargo target/ build tree)
    "fixtures",    # JSON fixtures — not python tests
    "findings",    # markdown findings
    "results",     # committed result envelopes (JSON)
    "python",      # experiment drivers (imported by tests/, not collected)
]
