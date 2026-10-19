"""pytest bootstrap for modules/drafting/tests (TP-CAT-01, drafting side).

Puts every module package directory on sys.path (contract §2 import model)
and provides the fixtures the drafting tests share: a fresh REAL bcdoc
document per test and a bcdraft-registered registry.

The REAL bcdoc (modules/document/bcdoc, W2) is a hard requirement here — the
contract double in modules/commands/tests/doubles_document.py is a bccmd
contract-verification fallback only and is never used in this suite.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES_DIR = REPO_ROOT / "modules"

for _sub in ("drafting", "commands", "document"):
    _dir = str(MODULES_DIR / _sub)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

import pytest  # noqa: E402


@pytest.fixture()
def document():
    """A fresh REAL bcdoc document."""
    from bcdoc.document import Document

    return Document(name="DraftTest")


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
    """A Registry with every bcdraft command registered (UI-equivalent)."""
    from bccmd import Registry
    import bcdraft

    return bcdraft.register_all(Registry())


@pytest.fixture()
def run():
    """Run a command through the registry with scripted inputs.

    ``run(ctx, "line", ["0,0", "10,0"])`` — the exact interface the modal
    operator and the acceptance battery use (registry.run_command with a
    ScriptedProvider).
    """

    def factory(ctx, name, inputs, registry=None, provider=None):
        from bccmd import ScriptedProvider
        from bcdraft import register_all
        from bccmd import Registry

        reg = registry if registry is not None else None
        if reg is None:
            reg = register_all(Registry())
        if provider is None:
            provider = ScriptedProvider(ctx, inputs)
        return reg.run_command(ctx, name, provider=provider)

    return factory
