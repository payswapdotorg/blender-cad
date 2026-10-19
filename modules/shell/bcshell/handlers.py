"""bcshell.handlers — .blend load/save persistence hooks (contract §6.2).

``load_post``: restore the session document from the
``blender_cad_document.json`` text block (save/reopen gate); ``save_pre``:
flush the document right before Blender writes the .blend so native Ctrl+S
persists CAD content. Both handlers are @persistent (they must survive file
loads — verified headless on the 5.2.2 build: non-persistent handlers are
dropped on load without firing).
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent


@persistent
def _on_load_post(_dummy=None):
    try:
        from . import session

        session.restore_on_load()
        from . import sync

        sync.sync_display(session.active_document())
    except Exception:
        # Persistence must never break file loading — a broken text block
        # degrades to a fresh document (recorded in the command history).
        try:
            from . import session

            session.reset_session()
        except Exception:
            pass


@persistent
def _on_save_pre(_dummy=None):
    try:
        from . import session

        session.flush()
    except Exception:
        pass


def register_handlers():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)


def unregister_handlers():
    """Remove exactly our handlers (idempotent, twice-safe)."""
    for lst, handler in (
        (bpy.app.handlers.load_post, _on_load_post),
        (bpy.app.handlers.save_pre, _on_save_pre),
    ):
        try:
            while handler in lst:
                lst.remove(handler)
        except (ValueError, AttributeError):
            pass


def installed():
    """Diagnostics + tests: True when both handlers are installed."""
    return (
        _on_load_post in bpy.app.handlers.load_post
        and _on_save_pre in bpy.app.handlers.save_pre
    )
