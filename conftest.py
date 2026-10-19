"""Repo-root pytest bootstrap: make module packages importable as top-level names.

Binding per docs/00-architecture/m1-module-contracts.md §2: packages import each
other as top-level names (``from bcdoc import document``); this conftest inserts
every ``modules/*/`` directory into sys.path for plain-pytest runs. Inside Blender
the extension __init__ performs the equivalent bootstrap.

bcdoc, bccmd, bcdraft, bcio and bcagent must import without bpy — tests assert it.
"""

import sys
from pathlib import Path

_MODULES = Path(__file__).resolve().parent / "modules"

for _d in sorted(_MODULES.iterdir()):
    if _d.is_dir() and not _d.name.startswith((".", "_")):
        _s = str(_d)
        if _s not in sys.path:
            sys.path.insert(0, _s)
