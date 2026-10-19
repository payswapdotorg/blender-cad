"""Pytest bootstrap for module ``agent`` tests.

m1-module-contracts §2 (import model, binding): under pytest a repo-root
``conftest.py`` inserts every ``modules/*/`` directory into ``sys.path`` so packages
import as TOP-LEVEL names (``from bcdoc import document``, ``import bcagent``).
That root file is TL-owned; this local conftest performs the same bootstrap for
``modules/agent`` runs (idempotent, deduped) so this module's tests are runnable
standalone before the root file lands — and harmless afterwards.

bcdoc/bcio are owned by worker 3-b (parallel M1 wave). Until they land, tests that
import them are expectedly RED at collection/run time — recorded in the worklog;
the TL re-runs this suite after integration.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]  # modules/agent/tests -> repo root

for _module_dir in (
    _REPO_ROOT / "modules" / "document",       # bcdoc
    _REPO_ROOT / "modules" / "interchange",    # bcio
    _REPO_ROOT / "modules" / "agent",          # bcagent
):
    _path = str(_module_dir)
    if _module_dir.is_dir() and _path not in sys.path:
        sys.path.insert(0, _path)
