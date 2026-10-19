"""bcshell — Blender integration shell for Blender CAD (milestone M1).

The only package in the extension allowed to import bpy (contract §2). It
hosts: the per-session bcdoc document + persistence (session.py), the
"BlenderCAD" workspace (workspace.py), one-way document→scene display sync
(sync.py), the modal command operator + scripted headless path (ops.py),
the N-panel UI (ui.py), the Ctrl+Space keymap (keymaps.py), viewport picking
+ rubberband (pick.py) and the load/save handlers (handlers.py).

``register()`` imports everything, registers bpy classes / UI / keymaps /
handlers and ensures the session document; ``unregister()`` removes ALL of
it — classes, keymap, handlers, live draw handlers (TP-CAT-06 clean
unload), and is twice-safe.

This ``__init__`` deliberately imports NOTHING at module level (bpy-free
import for pytest of the pure helpers): everything heavy happens inside
register()/unregister()/run_scripted().
"""

from __future__ import annotations

#: True once register() succeeded (contract §6.1 lifecycle flag)
registered: bool = False

#: bpy classes registered by register() (operators + panels)
classes = ()

__version__ = "0.1.0"


def register() -> None:
    """Register operators, UI, keymap and handlers; ensure the session."""
    global registered, classes

    import bpy

    from . import handlers, keymaps, ops, session, ui

    classes = tuple(ops.classes) + tuple(ui.classes)
    for cls in classes:
        bpy.utils.register_class(cls)
    keymaps.register_keymaps()
    handlers.register_handlers()
    session.ensure_session()
    registered = True


def unregister() -> None:
    """Remove everything register() added (twice-safe, TP-CAT-06)."""
    global registered, classes

    import bpy

    from . import handlers, keymaps, pick, session

    # live modal draw handlers go first — no orphan draw callbacks
    pick.cleanup_all()
    keymaps.unregister_keymaps()
    handlers.unregister_handlers()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass  # already unregistered — twice-safe
    classes = ()
    session.reset_session()
    registered = False


def run_scripted(command_name, inputs=None):
    """Headless/test entry point: run a command through the SAME registry +
    prompt state machine the UI uses (implementation: bcshell.session.run_scripted
    — deliberately bpy-free so it imports under plain pytest, TP-CAT-01)."""
    from .session import run_scripted as _run_scripted

    return _run_scripted(command_name, inputs)


__all__ = [
    "register",
    "unregister",
    "run_scripted",
    "registered",
    "classes",
]
