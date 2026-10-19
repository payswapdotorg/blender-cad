"""bcshell headless discipline tests (TP-CAT-01 + TP-CAT-06 prerequisites).

bcshell is the ONLY package allowed to import bpy (contract §2) — but it
must do so LAZILY: these tests pin the boundary:

1. the pure modules (``bcshell``/__init__, ``pick``, ``session``, ``sync``,
   ``workspace``, ``keymaps``) import under plain pytest and bpy NEVER
   enters ``sys.modules``;
2. those modules contain no MODULE-LEVEL bpy import (AST scan);
3. ``bcshell.run_scripted`` drives a real command through the session
   registry WITHOUT Blender — proving the scripted path shares the pure
   machinery (no reimplementation, no bpy dependence);
4. the operator/UI modules (``ops``, ``ui``, ``handlers``) are the bpy
   side — asserted present but NOT importable here (they are validated by
   modules/shell/tests/blender_driver.py inside Blender).
"""

import ast
import sys
from pathlib import Path

import pytest

import bcshell  # noqa: F401  (must import without bpy)

PACKAGE_DIR = Path(bcshell.__file__).resolve().parent

#: modules that must stay importable (and bpy-free) under plain pytest
#: (v2 additions: colors.py — the ACI palette, panel_ops.py — the pure
#: mutation logic behind the panel operators)
PURE_MODULES = ("bcshell", "bcshell.pick", "bcshell.session",
                "bcshell.sync", "bcshell.workspace", "bcshell.keymaps",
                "bcshell.colors", "bcshell.panel_ops")

#: modules that legitimately import bpy at module level (Blender GUI side)
BPY_MODULES = ("bcshell.ops", "bcshell.ui", "bcshell.handlers")


def test_all_pure_modules_import_without_bpy():
    for name in PURE_MODULES:
        __import__(name)
    leaked = [m for m in sys.modules if m == "bpy" or m.startswith("bpy.")]
    assert not leaked, f"bpy leaked into the pytest process: {leaked}"


def test_pure_modules_have_no_module_level_bpy_import():
    """AST scan: ``import bpy`` may appear only INSIDE functions (top-level
    statements only — function bodies are the lazy-by-design discipline)."""
    offenders = []
    for rel in ("__init__.py", "pick.py", "session.py", "sync.py",
                "workspace.py", "keymaps.py", "colors.py",
                "panel_ops.py"):
        path = PACKAGE_DIR / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # top-level statements ONLY
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = ([alias.name for alias in node.names]
                         if isinstance(node, ast.Import) else [node.module or ""])
                if any(n == "bpy" or n.startswith("bpy.") for n in names):
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, "module-level bpy imports in pure modules: " + str(offenders)


def test_bpy_side_modules_exist_and_declare_the_boundary():
    for rel in ("ops.py", "ui.py", "handlers.py"):
        assert (PACKAGE_DIR / rel).is_file(), f"missing bpy-side module {rel}"
    # the bpy side must import bpy somewhere at module level (the boundary is
    # explicit, not accidental) — and those imports are exactly why the
    # Blender driver, not pytest, validates them.
    ops_source = (PACKAGE_DIR / "ops.py").read_text(encoding="utf-8")
    assert "import bpy" in ops_source


def test_bpy_side_modules_are_not_importable_under_plain_pytest():
    for name in BPY_MODULES:
        with pytest.raises(ImportError):
            __import__(name)


def test_session_registry_exposes_every_bcdraft_command(shell_session):
    registry = shell_session.get_registry()
    names = set(registry.names())
    expected = {"LINE", "CIRCLE", "ARC", "ERASE", "MOVE", "COPY",
                "ROTATE", "SCALE", "UNDO", "REDO"}
    assert expected <= names, f"missing commands: {expected - names}"
    # aliases resolve exactly like the typed command line resolves them
    for alias, canonical in (("l", "LINE"), ("c", "CIRCLE"), ("a", "ARC"),
                             ("co", "COPY"), ("m", "MOVE"), ("ro", "ROTATE"),
                             ("sc", "SCALE"), ("u", "UNDO")):
        assert registry.lookup(alias).name == canonical


def test_run_scripted_creates_geometry_without_blender(shell_session):
    """The SAME registry + prompt state machine the UI uses, driven
    headless with no bpy anywhere in the process."""
    result = bcshell.run_scripted("LINE", ["0,0", "10,0", ""])
    assert result.status == "ok"
    assert len(result.created) == 1
    doc = shell_session.active_document()
    line = doc.get(result.created[0])
    assert (line.p1, line.p2) == ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    # the session prompt line was driven to Idle by the run
    assert shell_session.prompt_text == "Command:"
    leaked = [m for m in sys.modules if m == "bpy"]
    assert not leaked


def test_run_scripted_unknown_command_raises(shell_session):
    from bccmd import UnknownCommand

    with pytest.raises(UnknownCommand):
        bcshell.run_scripted("NOSUCHCOMMAND", [])
