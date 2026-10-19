"""bcshell.session — the per-session CAD application state.

One :class:`bcdoc.Document` per session (contract §6.2, v0). Everything the
shell needs lives here: the active document (lazily created on first use and
subscribed to its on_change events), the command registry (bcdraft commands
registered through ``bcdraft.register_all``), the session command history,
the feedback message sink and the prompt/dynamic-overlay text the N-panel
status line renders.

Persistence (the M1 save/reopen gate): after EVERY committed transaction
the document serializes into the ``bpy.data.texts`` block
``"blender_cad_document.json"`` — native ``Ctrl+S`` therefore persists CAD
documents inside the .blend. The ``load_post`` handler (handlers.py)
restores the document on reopen; ``save_pre`` flushes right before saving.

bpy is imported lazily inside the Blender-facing functions so this module
imports under plain pytest for the pure status helpers.
"""

from __future__ import annotations

from typing import Dict, List, Optional

#: bpy Text-block name carrying the serialized document inside the .blend
TEXT_BLOCK_NAME = "blender_cad_document.json"

#: session default document name
DEFAULT_DOC_NAME = "Untitled"

#: feedback ring size (the command line dock shows the tail)
FEEDBACK_LIMIT = 200

# -- module session state ----------------------------------------------------
_doc = None                     # the active bcdoc.Document
_registry = None                # bccmd.Registry with bcdraft registered
_history = None                 # bccmd.History (session transcript)
_feedback: List[str] = []       # feedback ring (oldest first)

#: current prompt line text (the pending Request or "Command:")
prompt_text: str = "Command:"
#: dynamic overlay text (distance < angle while the mouse moves)
dynamic_text: str = ""


# ---------------------------------------------------------------------------
# active document
# ---------------------------------------------------------------------------

def _new_document():
    from bcdoc.document import Document

    return Document(name=DEFAULT_DOC_NAME)


def _on_doc_change(event) -> None:
    """Fires after every committed transaction: persist + resync display."""
    if _doc is None:
        return
    try:
        flush()
    except Exception:
        pass  # persistence must never break the command that committed
    try:
        from . import sync

        sync.sync_display(_doc)
    except Exception:
        pass  # display is derived data — regenerate later (doc §7 rule 3)


def _subscribe(doc) -> None:
    if doc is not None and _on_doc_change not in doc.on_change:
        doc.on_change.append(_on_doc_change)


def _unsubscribe(doc) -> None:
    if doc is not None:
        try:
            while _on_doc_change in doc.on_change:
                doc.on_change.remove(_on_doc_change)
        except (AttributeError, ValueError):
            pass


def active_document():
    """The session document — created lazily on first use and subscribed to
    its own on_change events (contract §6.2)."""
    global _doc
    if _doc is None:
        _doc = _new_document()
        _subscribe(_doc)
    return _doc


def set_active(doc) -> None:
    """Replace the session document (doc_load_json, restore-on-reopen)."""
    global _doc
    _unsubscribe(_doc)
    _doc = doc
    _subscribe(_doc)
    try:
        flush()
    except Exception:
        pass
    from . import sync

    sync.sync_display(_doc)


def reset_session() -> None:
    """Drop all session state (unregister path; keeps no document ref so a
    reloaded bcshell starts fresh). Does NOT delete saved text blocks."""
    global _doc, _registry, _history
    _unsubscribe(_doc)
    _doc = None
    _registry = None
    _history = None
    _feedback.clear()


# ---------------------------------------------------------------------------
# persistence (bpy Text blocks — lazy bpy)
# ---------------------------------------------------------------------------

def flush(doc=None) -> None:
    """Serialize the document into ``bpy.data.texts[TEXT_BLOCK_NAME]``.

    Called after every committed transaction and by the save_pre handler
    (native Ctrl+S persists CAD documents — contract §6.2)."""
    import bpy

    target = doc if doc is not None else _doc
    if target is None:
        return
    text = bpy.data.texts.get(TEXT_BLOCK_NAME)
    if text is None:
        text = bpy.data.texts.new(TEXT_BLOCK_NAME)
    text.clear()
    text.write(target.serialize())


def restore_on_load() -> bool:
    """load_post hook: rebuild the session document from the text block.

    Returns True when a document was restored. A file without the text
    block resets the session to a fresh document (opening a foreign/new
    .blend must not leak the previous session's CAD content)."""
    import bpy

    text = bpy.data.texts.get(TEXT_BLOCK_NAME)
    if text is None:
        reset_session()
        set_active(_new_document())
        return False
    from bcdoc.document import Document

    set_active(Document.load(text.as_string()))
    return True


def ensure_session() -> None:
    """Register-time (side-effect-light) session bootstrap: create the
    document object WITHOUT touching the blend file (no flush until the
    first committed transaction). If a saved text block is already present
    (extension enabled with a CAD file open), restore it.

    Startup-restriction note (verified on Blender 5.2.2): when the extension
    is enabled at Blender STARTUP, ``register()`` runs under a restricted
    ``bpy.data`` (``_RestrictData`` — ``.texts`` access raises AttributeError;
    verified: "Error: '_RestrictData' object has no attribute 'texts'"). In
    that case this returns without creating anything: the document
    materializes lazily on the first :func:`active_document` call, and the
    ``load_post`` handler covers the open-with-CAD-file case. Enabling the
    extension from Preferences at runtime is NOT restricted and gets the
    full path including restore.
    """
    global _doc
    if _doc is not None:
        return
    try:
        import bpy

        texts = bpy.data.texts  # restricted during startup registration
    except ImportError:
        return  # plain pytest (no Blender): lazy creation on first use
    except AttributeError:
        return  # startup _RestrictData: lazy creation + load_post restore
    try:
        has_text = texts.get(TEXT_BLOCK_NAME) is not None
    except AttributeError:
        return
    if has_text:
        restore_on_load()
    else:
        _doc = _new_document()
        _subscribe(_doc)


# ---------------------------------------------------------------------------
# registry + history + feedback
# ---------------------------------------------------------------------------

def get_registry():
    """The session command registry: bcdraft commands registered through
    ``bcdraft.register_all`` — the SAME interface the UI drives (§5)."""
    global _registry
    if _registry is None:
        import bcdraft
        from bccmd import Registry

        _registry = bcdraft.register_all(Registry())
    return _registry


def get_history():
    global _history
    if _history is None:
        from bccmd import History

        _history = History()
    return _history


def feedback_sink(message: str) -> None:
    """CommandContext.feedback sink — bounded ring read by the command-line
    dock / N-panel."""
    _feedback.append(str(message))
    if len(_feedback) > FEEDBACK_LIMIT:
        del _feedback[:-FEEDBACK_LIMIT]


def feedback_messages(n: int = 10) -> List[str]:
    return list(_feedback[-n:])


def command_context():
    """A fresh CommandContext bound to the session document, session
    history and the feedback sink (fresh prompt machine per command run)."""
    from bccmd import CommandContext, PromptMachine

    return CommandContext(
        document=active_document(),
        history=get_history(),
        feedback=feedback_sink,
        machine=PromptMachine(),
    )


def run_scripted(command_name, inputs=None):
    """Run ``command_name`` with scripted inputs through the SAME registry +
    prompt state machine the UI uses (contract §6.2 scripted path).

    ``inputs`` items: ``"12,34"``-style strings (parsed per the pending
    Request), :class:`bccmd.InputValue` objects, or exceptions
    (``Cancelled()``). Lives HERE (not in ops.py) so the scripted path is
    importable and testable WITHOUT Blender (TP-CAT-01) — it is the exact
    ``Registry.run_command`` + ``ScriptedProvider`` machinery the modal
    operator's background fallback drives, never a reimplementation.
    """
    from bccmd import ScriptedProvider

    ctx = command_context()
    registry = get_registry()
    provider = ScriptedProvider(ctx, list(inputs or []))
    return registry.run_command(ctx, command_name, provider=provider)


def set_prompt(text: str, dynamic: str = "") -> None:
    """Status-bar/prompt-line update (modal operator drives this)."""
    global prompt_text, dynamic_text
    prompt_text = str(text)
    dynamic_text = str(dynamic)


def status() -> Dict:
    """Snapshot for the N-panel: document info + prompt + last feedback."""
    doc = _doc
    info = {
        "prompt": prompt_text,
        "dynamic": dynamic_text,
        "feedback": feedback_messages(8),
        "registered_document": doc is not None,
    }
    if doc is not None:
        info.update(
            name=doc.name,
            doc_version=doc.doc_version,
            entities=sum(doc.count_by_kind().values()),
            counts=doc.count_by_kind(),
            undo_depth=doc.undo_depth(),
            redo_depth=doc.redo_depth(),
        )
    return info
