"""bcshell v2 shell-logic tests — pure, no Blender.

Covers the headless core of the v2 shell additions (contract §7 + the
task's pinned cross-worker glue):

* :mod:`bcshell.panel_ops` — the REAL mutation logic behind the new panel
  operators (layers / spaces / settings / osnap bits), including the
  journaled-transaction + undo behavior and every error path;
* :func:`bcshell.session.resolve_cmdline_token` — the v2 command-line
  behavior (empty = repeat-last, unknown = suggestions via W-A's
  ``Registry.suggestions`` — feature-detected with a stub registry);
* :func:`bcshell.session.mouse_point_input` — the mouse-source InputValue
  glue (works pre-W-A via the attribute fallback, activates unchanged
  when W-A adds the ``source`` field);
* :func:`bcshell.session.panel_state` — the N-panel data snapshot;
* the on_change chain contract (refresh dims FIRST, then sync, exactly
  once per commit, reentrancy-absorbed).

The W-A input-model fields (``InputValue.source``, ``CommandContext.pointer``
/ ``pending_osnap``, ``Registry.suggestions``) are pinned by hasattr
activation checks that SKIP until W-A lands (green now, live at TL
integration).
"""

import pytest

import bcshell.session as session
import bcshell.sync as sync
from bcshell import panel_ops


# ---------------------------------------------------------------------------
# panel_ops — layers
# ---------------------------------------------------------------------------

def test_set_current_layer_sets_clayer(shell_session):
    doc = shell_session.active_document()
    with doc.transaction("layer"):
        doc.layers.add("WALLS")
    ok, message = panel_ops.set_current_layer(doc, "WALLS")
    assert ok and "WALLS" in message
    assert doc.current_layer == "WALLS"


def test_set_current_layer_error_paths(shell_session):
    doc = shell_session.active_document()
    ok, message = panel_ops.set_current_layer(doc, "NOPE")
    assert not ok and "not found" in message.lower()
    ok, message = panel_ops.set_current_layer(doc, "")
    assert not ok


def test_toggle_layer_prop_is_journaled_and_undoable(shell_session):
    doc = shell_session.active_document()
    with doc.transaction("layer"):
        doc.layers.add("WALLS")
    depth = doc.undo_depth()
    ok, message = panel_ops.toggle_layer_prop(doc, "WALLS", "on", False)
    assert ok and "off" in message
    assert doc.layers.get("WALLS").on is False
    assert doc.undo_depth() == depth + 1        # journaled group committed
    assert doc.undo()
    assert doc.layers.get("WALLS").on is True  # undo restores the flag


def test_toggle_layer_prop_idempotent_message(shell_session):
    doc = shell_session.active_document()
    ok, message = panel_ops.toggle_layer_prop(doc, "0", "on", True)
    assert ok and "already" in message


def test_toggle_layer_prop_rejects_unknown(shell_session):
    doc = shell_session.active_document()
    assert not panel_ops.toggle_layer_prop(doc, "0", "sparkly", True)[0]
    assert not panel_ops.toggle_layer_prop(doc, "NOPE", "on", False)[0]


# ---------------------------------------------------------------------------
# panel_ops — spaces / layouts
# ---------------------------------------------------------------------------

def test_activate_model_space_resets_tilemode(shell_session):
    doc = shell_session.active_document()
    with doc.transaction("layout"):
        doc.add_layout("Sheet1")
    panel_ops.activate_space(doc, "Sheet1")
    assert doc.current_space == "Sheet1"
    assert doc.settings.get("TILEMODE") == 0
    assert doc.active_layout == "Sheet1"
    ok, message = panel_ops.activate_space(doc, "MODEL")
    assert ok
    assert doc.current_space == "MODEL"
    assert doc.settings.get("TILEMODE") == 1
    assert doc.active_layout is None


def test_activate_space_unknown_layout(shell_session):
    doc = shell_session.active_document()
    ok, message = panel_ops.activate_space(doc, "GHOST")
    assert not ok and "not found" in message.lower()


def test_new_layout_creates_and_activates(shell_session):
    doc = shell_session.active_document()
    ok, message = panel_ops.new_layout(doc, "Sheet1")
    assert ok
    assert "Sheet1" in doc.layouts()
    assert doc.current_space == "Sheet1"
    assert doc.active_layout == "Sheet1"
    ok, _ = panel_ops.new_layout(doc, "Sheet1")
    assert not ok                                   # duplicate refused
    ok, _ = panel_ops.new_layout(doc, "MODEL")
    assert not ok                                   # MODEL is not a layout
    ok, _ = panel_ops.new_layout(doc, "   ")
    assert not ok                                   # empty name refused


# ---------------------------------------------------------------------------
# panel_ops — settings / osnap bits
# ---------------------------------------------------------------------------

def test_toggle_bool_settings(shell_session):
    doc = shell_session.active_document()
    assert doc.settings.get("ORTHOMODE") == 0
    ok, message = panel_ops.toggle_setting(doc, "ORTHOMODE")
    assert ok and "ORTHOMODE: 1" in message
    assert doc.settings.get("ORTHOMODE") == 1
    panel_ops.toggle_setting(doc, "ORTHOMODE")
    assert doc.settings.get("ORTHOMODE") == 0


def test_toggle_dynmode_flips_3_and_0(shell_session):
    doc = shell_session.active_document()
    assert doc.settings.get("DYNMODE") == 3
    panel_ops.toggle_setting(doc, "DYNMODE")
    assert doc.settings.get("DYNMODE") == 0
    panel_ops.toggle_setting(doc, "DYNMODE")
    assert doc.settings.get("DYNMODE") == 3


def test_toggle_setting_rejects_non_toggle(shell_session):
    doc = shell_session.active_document()
    ok, message = panel_ops.toggle_setting(doc, "CLAYER")
    assert not ok
    ok, _ = panel_ops.toggle_setting(doc, "NOSUCH")
    assert not ok


def test_toggle_osnap_bit_xors_running_mask(shell_session):
    doc = shell_session.active_document()
    assert doc.settings.get("OSMODE") == 55          # END+MID+CEN+QUA+INT
    ok, message = panel_ops.toggle_osnap_bit(doc, 1, "ENDPOINT")
    assert ok and "enabled" not in message           # bit 1 was ON -> now off
    assert doc.settings.get("OSMODE") == 54
    ok, message = panel_ops.toggle_osnap_bit(doc, 1, "ENDPOINT")
    assert ok and "enabled" in message
    assert doc.settings.get("OSMODE") == 55
    ok, message = panel_ops.toggle_osnap_bit(doc, 128, "PERPENDICULAR")
    assert ok and "enabled" in message
    assert doc.settings.get("OSMODE") == 55 | 128


def test_toggle_osnap_bit_validation(shell_session):
    doc = shell_session.active_document()
    assert not panel_ops.toggle_osnap_bit(doc, 0)[0]
    assert not panel_ops.toggle_osnap_bit(doc, -4)[0]
    assert not panel_ops.toggle_osnap_bit(doc, "x")[0]


# ---------------------------------------------------------------------------
# session.resolve_cmdline_token — the v2 command-line behavior
# ---------------------------------------------------------------------------

def test_cmdline_empty_without_history_is_m1_message(shell_session):
    resolution = session.resolve_cmdline_token("")
    assert resolution["action"] == "message"
    assert resolution["message"] == "Command: (empty)"


def test_cmdline_empty_with_history_repeats_last(shell_session):
    shell_session.run_scripted("LINE", ["0,0", "3,0", ""])
    resolution = session.resolve_cmdline_token("   ")
    assert resolution["action"] == "repeat"
    assert resolution["command"] == "LINE"
    assert resolution["message"] == "Repeat: LINE"


def test_cmdline_resolves_alias_with_preset(shell_session):
    resolution = session.resolve_cmdline_token("line 1,1 2,2")
    assert resolution["action"] == "run"
    assert resolution["command"] == "LINE"
    assert resolution["preset"] == "1,1 2,2"
    assert resolution["message"] == "Command: LINE"


def test_cmdline_unknown_without_suggestions_keeps_m1_text(shell_session):
    resolution = session.resolve_cmdline_token("FROBNICATE")
    assert resolution["action"] == "message"
    assert resolution["message"] == "Unknown command: 'FROBNICATE'"


def test_cmdline_unknown_with_suggestions_names_candidates(shell_session):
    from bccmd import Registry

    class SuggestingRegistry(Registry):
        """Stub with W-A's pinned suggestions API (contracts §3) so the
        glue is exercised before W-A lands."""

        def suggestions(self, prefix, limit=8):
            return [("LINE", "creates lines"), ("LINETYPE", "linetypes")]

    session._registry = SuggestingRegistry()
    resolution = session.resolve_cmdline_token("lin")
    assert resolution["action"] == "message"
    assert resolution["message"] == (
        "Unknown command 'lin' — did you mean: LINE, LINETYPE?")


def test_cmdline_suggestions_capped_at_limit(shell_session):
    from bccmd import Registry

    class ManySuggestingRegistry(Registry):
        def suggestions(self, prefix, limit=8):
            return [(f"CAND{i}", "") for i in range(20)]

    session._registry = ManySuggestingRegistry()
    resolution = session.resolve_cmdline_token("zzz")
    named = resolution["message"].split("did you mean: ")[1]
    assert len(named.split(", ")) == session.SUGGESTION_LIMIT


# ---------------------------------------------------------------------------
# session.mouse_point_input — mouse-source glue (live pre-W-A)
# ---------------------------------------------------------------------------

def test_mouse_point_input_carries_source_mouse(shell_session):
    value = session.mouse_point_input(1.5, -2.0, 0.0)
    assert value.kind == "point"
    assert (value.value.x, value.value.y, value.value.z) == (1.5, -2.0, 0.0)
    assert getattr(value, "source", None) == "mouse"


def test_typed_point_input_stays_unsourced(shell_session):
    from bccmd import point_input

    value = point_input(1, 2)
    # pre-W-A: no source at all; post-W-A: the "typed" default (contracts §3)
    assert getattr(value, "source", "typed") == "typed"


# ---------------------------------------------------------------------------
# session.panel_state — the N-panel data snapshot
# ---------------------------------------------------------------------------

def test_panel_state_shape_and_content(shell_session):
    doc = shell_session.active_document()
    with doc.transaction("setup"):
        doc.layers.add("WALLS", color=1)
        doc.add_layout("Sheet1")
    panel_ops.set_current_layer(doc, "WALLS")
    state = session.panel_state()
    assert state["has_document"] is True
    assert state["current_layer"] == "WALLS"
    assert [rec["name"] for rec in state["layers"]] == ["0", "WALLS"]
    assert state["layers"][1] == {
        "name": "WALLS", "color": 1, "on": True, "frozen": False,
        "locked": False, "plot": True, "current": True}
    assert state["layouts"] == ["Sheet1"]
    assert state["current_space"] == "MODEL"
    assert state["active_layout"] is None
    assert state["osmode"] == 55
    assert state["settings"]["ORTHOMODE"] == 0
    assert state["settings"]["DYNMODE"] == 3


def test_panel_state_without_document(shell_session):
    state = session.panel_state()
    assert state["has_document"] is False
    assert state["layers"] == []
    assert state["layouts"] == []


# ---------------------------------------------------------------------------
# on_change chain: refresh dims FIRST, then sync — exactly once
# ---------------------------------------------------------------------------

def test_on_change_chain_refreshes_dims_before_sync(shell_session,
                                                    monkeypatch):
    calls = []
    monkeypatch.setattr(sync, "refresh_document_dims",
                        lambda doc: calls.append("refresh") or 1)
    monkeypatch.setattr(sync, "sync_display",
                        lambda doc: calls.append("sync") or {})
    doc = shell_session.active_document()
    with doc.transaction("draw"):
        from bcdoc.entities import Line

        doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    assert calls == ["refresh", "sync"]


def test_on_change_chain_absorbs_reentrancy(shell_session, monkeypatch):
    """A nested on_change (e.g. the bcdraw regen committing a transaction
    while the chain is running) must be absorbed — one chain per commit."""
    calls = []
    doc = shell_session.active_document()

    def fake_sync(target):
        calls.append("sync")
        target.on_change(("doc", target.doc_version))  # nested fire

    monkeypatch.setattr(sync, "refresh_document_dims", lambda doc: 0)
    monkeypatch.setattr(sync, "sync_display", fake_sync)
    with doc.transaction("draw"):
        from bcdoc.entities import Line

        doc.add_entity(Line((0, 0, 0), (1, 0, 0)))
    assert calls == ["sync"]                    # the nested fire was absorbed


# ---------------------------------------------------------------------------
# W-A activation checks — skip until the input-model fields land
# ---------------------------------------------------------------------------

def test_wa_input_value_source_field():
    from bccmd import InputValue
    if not hasattr(InputValue, "__dataclass_fields__") or \
            "source" not in InputValue.__dataclass_fields__:
        pytest.skip("requires W-A integration: InputValue.source")
    value = InputValue(kind="point", value=None)
    assert value.source == "typed"


def test_wa_command_context_pointer_field():
    from bccmd import CommandContext
    fields = getattr(CommandContext, "__dataclass_fields__", {})
    if "pointer" not in fields:
        pytest.skip("requires W-A integration: CommandContext.pointer")
    ctx = CommandContext()
    assert ctx.pointer is None
    ctx.pointer = None  # settable (the modal operator assigns it)


def test_wa_command_context_pending_osnap_field():
    from bccmd import CommandContext
    fields = getattr(CommandContext, "__dataclass_fields__", {})
    if "pending_osnap" not in fields:
        pytest.skip("requires W-A integration: CommandContext.pending_osnap")
    assert CommandContext().pending_osnap is None


def test_wa_registry_suggestions_api():
    from bccmd import Registry
    if not hasattr(Registry, "suggestions"):
        pytest.skip("requires W-A integration: Registry.suggestions")
    registry = Registry()
    from bcdraft import register_all

    register_all(registry)
    matches = registry.suggestions("LI", 8)
    assert matches, "suggestions('LI') must find LINE"
    for name, help_text in matches:           # pinned shape: (name, help)
        assert isinstance(name, str) and isinstance(help_text, str)
    assert any(name == "LINE" for name, _help in matches)
