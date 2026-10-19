# Blender CAD — extension entry (bl_ext.<repo>.blender_cad)
# TL-owned per docs/00-architecture/m1-module-contracts.md §2/§6.1.
#
# Responsibilities (and nothing else):
#   1. Top-level package bootstrap: insert the extension directory into sys.path
#      so the module packages (bcdoc, bccmd, bcdraft, bcshell, bcio, bcagent)
#      resolve as top-level imports (same model as the repo-root conftest.py).
#   2. Register/unregister the CAD shell (bcshell.register / bcshell.unregister).
#   3. Keep load side-effect-light and unload CLEAN (TP-CAT-06).
#
# The engineering code lives in modules/<module>/<pkg>/ in the canonical repo and
# is assembled into this package by scripts/build_extension.py — never hand-edited
# inside build/ or dist/.

bl_info = {
    "name": "Blender CAD",
    "author": "Blender CAD project (payswapdotorg)",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar (N) > BlenderCAD, Ctrl+Space command line",
    "description": "AutoCAD-familiar CAD workspace: command line, drafting, DXF interchange. "
                  "Blender is a trademark of the Blender Foundation; AutoCAD is a trademark of "
                  "Autodesk. Independent work — not affiliated with or endorsed by either.",
    "warning": "M1 walking skeleton — early development",
    "doc_url": "https://github.com/payswapdotorg/blender-cad",
    "category": "Object",
}

import os
import sys

_EXTENSION_DIR = os.path.dirname(os.path.realpath(__file__))
_BOOTSTRAPPED = False


def _bootstrap_paths():
    """Insert the extension dir into sys.path (deduped) for top-level imports."""
    global _BOOTSTRAPPED
    if _EXTENSION_DIR not in sys.path:
        sys.path.insert(0, _EXTENSION_DIR)
    _BOOTSTRAPPED = True


def register():
    _bootstrap_paths()
    import bcshell  # noqa: E402  (imports bcdoc/bccmd/bcdraft/bcio on demand)
    bcshell.register()


def unregister():
    import bcshell  # noqa: E402
    bcshell.unregister()
