"""bcshell.session — the per-session CAD application state.

One :class:`bcdoc.Document` per session (contract §6.2, v0). Everything the
shell needs lives here: the active document (lazily created on first use and
subscribed to its on_change events), the command registry (bcdraft commands
registered through ``bcdraft.register_all``), the session command history,
the feedback message sink and the prompt/dynamic-overlay text the N-panel
status line renders.

The v2 document (M2, bcdoc/2; writes bcdoc/3 since the m3 schema lane) adds
layers/blocks/layouts/settings/styles (and, at bcdoc/3, constrained-sketch
content) —
:func:`panel_state` exposes them to the N-panel sections and
:func:`resolve_cmdline_token` implements the v2 command-line behavior
(empty token = repeat last, unknown token = suggestions when W-A's
``Registry.suggestions`` has landed — feature-detected).

Persistence (the M1 save/reopen gate): after EVERY committed transaction
the document serializes into the ``bpy.data.texts`` block
``"blender_cad_document.json"`` (bcdoc/3; ``Document.load`` still upgrades
legacy bcdoc/1/bcdoc/2 files) — native ``Ctrl+S`` therefore persists CAD
documents inside the .blend. The ``load_post`` handler (handlers.py)
restores the document on reopen; ``save_pre`` flushes right before saving.
The on_change chain refreshes DIMENSION caches first
(:func:`bcshell.sync.refresh_document_dims`, feature-detected bcdraw)
then rebuilds the display (contract §7: dims stay current after MOVE).

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
#: reentrancy guard for the on_change chain (the bcdraw dim regen mutates
#: document state; a nested on_change must not re-enter flush+sync)
_handling_change: bool = False


# ---------------------------------------------------------------------------
# active document
# ---------------------------------------------------------------------------

def _new_document():
    from bcdoc.document import Document

    return Document(name=DEFAULT_DOC_NAME)


def _on_doc_change(event) -> None:
    """Fires after every committed transaction: persist, refresh dim
    caches (bcdraw, feature-detected — contract §7), resync display.

    Reentrancy-guarded: the bcdraw regen itself mutates document state
    (stored dim measurements); the resulting nested on_change is absorbed
    so flush+regen+sync run exactly ONCE per committed transaction."""
    global _handling_change
    if _doc is None or _handling_change:
        return
    _handling_change = True
    try:
        try:
            flush()
        except Exception:
            pass  # persistence must never break the command that committed
        try:
            from . import sync

            # dims first (contract §7: refresh_document before sync so the
            # display shows current measurements), then the rebuild
            sync.refresh_document_dims(_doc)
            sync.sync_display(_doc)
        except Exception:
            pass  # display is derived data — regenerate later (doc §7 rule 3)
    finally:
        _handling_change = False


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
    ``bcdraft.register_all`` — plus the M2 annotation/layout commands
    through ``bcdraw.register_all`` (feature-detected: present since W-C
    landed, absent cleanly before) — the SAME interface the UI drives (§5
    + contracts §7: the command line exposes DIMLINEAR/TEXT/LAYOUT/…)."""
    global _registry
    if _registry is None:
        import bcdraft
        from bccmd import Registry

        _registry = bcdraft.register_all(Registry())
        try:
            import bcdraw  # annotations + layouts (contracts §5)

            bcdraw.register_all(_registry)
        except ImportError:
            pass  # feature-detected: bcdraw absent pre-integration
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

    Mouse-sourced picks use :func:`mouse_point_input` so scripted sessions
    exercise the SAME precision-resolution chain the modal operator feeds
    (typed strings stay typed — AutoCAD rule, contracts §3).
    """
    from bccmd import ScriptedProvider

    ctx = command_context()
    registry = get_registry()
    provider = ScriptedProvider(ctx, list(inputs or []))
    return registry.run_command(ctx, command_name, provider=provider)


# ---------------------------------------------------------------------------
# v2 command-line resolution (pure; ops.BCSHELL_OT_cmdline dispatches on it)
# ---------------------------------------------------------------------------

#: how many autocomplete suggestions the cmdline shows (contract §7: up to 5)
SUGGESTION_LIMIT = 5


def resolve_cmdline_token(token: str) -> Dict:
    """Pure resolution of one command-line entry (v2 behavior).

    Returns an action dict the cmdline operator dispatches on:

    * ``{"action": "run", "command", "preset", "message"}`` — run a
      resolved command (message = the "Command: NAME" echo);
    * ``{"action": "repeat", "command", "message"}`` — EMPTY token with a
      known last command: repeat ``History.last_command()`` (ux-spec §3.2;
      message = "Repeat: NAME");
    * ``{"action": "message", "message"}`` — EMPTY token without history
      (the M1 "(empty)" behavior) or an unknown token: the message carries
      "did you mean: ..." suggestions when the registry exposes W-A's
      ``Registry.suggestions(prefix, limit)`` (feature-detected; without
      it the message is the M1 unknown-command text).
    """
    stripped = str(token).strip()
    if not stripped:
        last = get_history().last_command()
        if last is None:
            return {"action": "message", "message": "Command: (empty)"}
        return {"action": "repeat", "command": last,
                "message": f"Repeat: {last}"}
    parts = stripped.split(None, 1)
    registry = get_registry()
    spec = registry.lookup(parts[0])
    if spec is None:
        suggest = getattr(registry, "suggestions", None)
        names: List = []
        if callable(suggest):
            try:
                names = [str(name) for name, _help
                        in suggest(parts[0], SUGGESTION_LIMIT)]
            except TypeError:  # pre-limit signature fallback
                names = [str(name) for name, _help in suggest(parts[0])]
            names = names[:SUGGESTION_LIMIT]
        if names:
            message = (f"Unknown command {parts[0]!r} — did you mean: "
                       + ", ".join(names) + "?")
        else:
            message = f"Unknown command: {parts[0]!r}"
        return {"action": "message", "message": message}
    preset = parts[1] if len(parts) > 1 else ""
    return {"action": "run", "command": spec.name, "preset": preset,
            "message": f"Command: {spec.name}"}


# ---------------------------------------------------------------------------
# mouse-sourced input construction (W-A §3 feature-detected glue)
# ---------------------------------------------------------------------------

def mouse_point_input(x: float, y: float, z: float = 0.0):
    """A point :class:`bccmd.InputValue` marked as MOUSE-sourced.

    The pinned v2 input model (contracts §3) adds
    ``InputValue.source: str = "typed"`` with "mouse" meaning a viewport
    pick (mouse input ALWAYS passes through osnap/ortho/grid resolution;
    typed input NEVER does). This helper constructs with the pinned
    ``source`` kwarg when ``bccmd.input.point_input`` supports it and falls
    back to plain construction + attribute assignment otherwise — BOTH
    paths yield ``value.source == "mouse"`` so the glue is live now and
    activates W-A's resolution chain the moment it lands. Used by the modal
    operator's click path AND scripted precision tests."""
    from bccmd import point_input

    try:
        return point_input(x, y, z, source="mouse")
    except TypeError:
        value = point_input(x, y, z)
        value.source = "mouse"
        return value


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


# ---------------------------------------------------------------------------
# v2 panel state (Layers / Layout-Space / Precision sections — pure)
# ---------------------------------------------------------------------------

def panel_state() -> Dict:
    """Snapshot for the v2 N-panel sections (contract §7). Pure — the
    panel draw reads this, the headless tests pin its shape:

    * ``layers``: ``[{name, color, on, frozen, locked, plot, current}]`` in
      table order ("0" first); the UI caps the visible list;
    * ``layouts``: layout names in table order; ``current_space`` /
      ``active_layout`` are the session space pointers;
    * ``osmode``: the running OSMODE bitmask (the Precision checkboxes
      toggle bits 1/2/4/16/32/128/1024 — ENDPOINT..TANGENT);
    * ``settings``: the bool-style toggles {ORTHOMODE, SNAPMODE,
      GRIDMODE, DYNMODE} the panel maps to its operator buttons.
    """
    doc = _doc
    state = {
        "has_document": doc is not None,
        "current_layer": None,
        "layers": [],
        "layouts": [],
        "current_space": None,
        "active_layout": None,
        "osmode": 0,
        "settings": {},
    }
    if doc is None:
        return state
    try:
        state["current_layer"] = doc.current_layer
    except Exception:
        pass
    try:
        current = doc.current_layer
        state["layers"] = [
            {
                "name": record.name,
                "color": record.color,
                "on": bool(record.on),
                "frozen": bool(record.frozen),
                "locked": bool(record.locked),
                "plot": bool(record.plot),
                "current": record.name == current,
            }
            for record in doc.layers.records()
        ]
    except Exception:
        pass
    try:
        state["layouts"] = list(doc.layouts())
    except Exception:
        pass
    state["current_space"] = getattr(doc, "current_space", None)
    state["active_layout"] = getattr(doc, "active_layout", None)
    try:
        state["osmode"] = int(doc.settings.get("OSMODE"))
    except Exception:
        pass
    for name in ("ORTHOMODE", "SNAPMODE", "GRIDMODE", "DYNMODE"):
        try:
            state["settings"][name] = int(doc.settings.get(name))
        except Exception:
            pass
    return state
