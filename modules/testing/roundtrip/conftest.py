"""pytest bootstrap for the cross-module round-trip suite (TP-CAT-04
precursor). Puts every package this suite needs on ``sys.path`` (bcdoc,
bcio) plus the fixtures helper directory (m1-module-contracts.md §2)."""

import sys
from pathlib import Path

_MODULES = Path(__file__).resolve().parents[2]
_ROUNDTRIP = Path(__file__).resolve().parent

for _pkg in ("document", "interchange"):
    _path = str(_MODULES / _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)

_fixtures = str(_ROUNDTRIP / "fixtures")
if _fixtures not in sys.path:
    sys.path.insert(0, _fixtures)
