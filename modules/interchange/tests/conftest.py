"""pytest bootstrap for the interchange module suite.

Puts ``modules/document`` (bcdoc — a declared dependency) and
``modules/interchange`` (bcio) on ``sys.path`` per the M1 import model
(m1-module-contracts.md §2).
"""

import sys
from pathlib import Path

_MODULES = Path(__file__).resolve().parents[2]

for _pkg in ("document", "interchange"):
    _path = str(_MODULES / _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)
