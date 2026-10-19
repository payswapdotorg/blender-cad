"""pytest bootstrap for modules/shell/tests (TP-CAT-01, shell side).

Puts every module package directory on sys.path (contract §2 import model —
the same top-level names the extension uses). bcshell itself imports bpy
LAZILY (only ops/ui/handlers touch it at module level), so the pure helpers
in pick/session/sync and the run_scripted entry point are testable under
plain pytest WITHOUT Blender.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_DIR = REPO_ROOT / "modules"

for _sub in ("shell", "commands", "drafting", "document", "interchange", "agent"):
    _dir = str(MODULES_DIR / _sub)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)


import pytest  # noqa: E402


@pytest.fixture()
def shell_session():
    """An isolated bcshell session: fresh document + registry, cleaned after.

    The session module keeps module-level state; this fixture resets it so
    tests never leak documents into each other (same discipline the driver
    gets by running in a fresh Blender process).
    """
    import bcshell.session as session

    session.reset_session()
    yield session
    session.reset_session()
