"""pytest bootstrap for modules/drawings/tests (m2-contracts §10, W-C row).

Puts every consumed module package directory on sys.path (contract §2
import model — the repo-root conftest does the same; this local bootstrap
keeps the suite runnable on its own), and provides the shared fixtures:
a fresh REAL bcdoc document per test, a feedback-capturing CommandContext
factory, and a Registry with EVERY bcdraft AND bcdraw command registered
(the real integration registry — the associativity walkthrough drives
LINE/MOVE from bcdraft and DIMLINEAR/DIMREGEN from bcdraw through it).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_DIR = REPO_ROOT / "modules"

for _sub in ("drawings", "drafting", "commands", "document"):
    _dir = str(MODULES_DIR / _sub)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

import pytest  # noqa: E402


@pytest.fixture()
def document():
    """A fresh REAL bcdoc document (W-B1's v2 model, hard requirement)."""
    from bcdoc.document import Document

    return Document(name="DrawTest")


@pytest.fixture()
def make_context(document):
    """CommandContext factory with a captured feedback sink."""

    def factory(doc=None):
        from bccmd import CommandContext

        messages = []

        def sink(message):
            messages.append(str(message))

        ctx = CommandContext(document=doc if doc is not None else document,
                             feedback=sink)
        ctx.feedback_messages = messages  # test hook
        return ctx

    return factory


@pytest.fixture()
def registry():
    """Registry with every bcdraft + bcdraw command (UI-equivalent)."""
    from bccmd import Registry
    import bcdraft
    import bcdraw

    reg = Registry()
    bcdraft.register_all(reg)
    bcdraw.register_all(reg)
    return reg


@pytest.fixture()
def run(registry):
    """Run a command through the registry with scripted inputs.

    ``run(ctx, "dimlinear", ["0,0", "10,0", "5,3"])`` — the exact
    interface the modal operator and the acceptance battery use
    (registry.run_command with a ScriptedProvider).
    """

    def factory(ctx, name, inputs, provider=None):
        from bccmd import ScriptedProvider

        if provider is None:
            provider = ScriptedProvider(ctx, inputs)
        return registry.run_command(ctx, name, provider=provider)

    return factory
