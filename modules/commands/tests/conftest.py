"""pytest bootstrap for modules/commands/tests (TP-CAT-01).

Puts every module package directory on sys.path (contract §2 import model —
the same top-level names the extension uses), and installs the bcdoc
contract double ONLY when the real ``modules/document/bcdoc`` is absent.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_DIR = REPO_ROOT / "modules"

for _sub in ("commands", "drafting", "document", "shell"):
    _dir = str(MODULES_DIR / _sub)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

try:
    import bcdoc  # noqa: F401  (real W2 package)
    BCDOC_REAL = True
except ImportError:
    from doubles_document import install_as_bcdoc

    install_as_bcdoc()
    BCDOC_REAL = False


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture()
def document():
    """A fresh bcdoc document (real when W2's package lands, else the double)."""
    from bcdoc.document import Document

    return Document(name="TestDoc")


@pytest.fixture()
def make_context(document):
    """CommandContext factory with a captured feedback sink."""

    def factory(doc=None, feedback=None):
        from bccmd import CommandContext

        messages = []

        def sink(message):
            messages.append(str(message))

        ctx = CommandContext(
            document=doc if doc is not None else document,
            feedback=feedback or sink,
        )
        ctx.feedback_messages = messages  # test hook
        return ctx

    return factory

