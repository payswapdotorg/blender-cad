"""pytest bootstrap for the document module suite.

The M1 import model (m1-module-contracts.md §2) resolves packages as
TOP-LEVEL names with every ``modules/*/`` directory on ``sys.path``; this
per-suite conftest provides that for standalone runs (the repo-root
conftest does the same when the TL integrates centrally).
"""

import sys
from pathlib import Path

_MODULES = Path(__file__).resolve().parents[2]

for _pkg in ("document",):
    _path = str(_MODULES / _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)
