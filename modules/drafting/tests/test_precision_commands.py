"""Precision/settings command tests — the sysvar command surface through the
REAL registry + ScriptedProvider (m2 contracts §4 + §10, drafting row W-A).

The snap engine itself (candidates, resolve chain, dde) is covered by
``test_precision.py``; this file drives the COMMAND surface end-to-end:

* SETVAR — bare Enter / typed ``?`` list every SETTING_DEFS entry with its
  type + current value, value prompts parse per type, unknown names and
  invalid values re-ask, Enter keeps the shown default, record settings
  (CLAYER) must name an existing table entry, cancellation mid-command
  leaves settings unchanged (sysvars are persisted but never journaled);
* GETVAR, OSNAP (bit-set mode lists, none/off, bare Enter shows current,
  invalid modes re-ask), ORTHO/SNAP/GRID (0<->1 toggles), DYN/DYNAMICINPUT
  (DYNMODE 3<->0), UNITS (guided LUNITS/LUPREC/AUNITS/AUPREC/INSUNITS walk
  with defaults shown + Enter-accepted, invalid values re-ask, deferred
  apply so Esc mid-walk changes nothing);
* precision-in-command regressions: typed points never resolve through a
  real LINE (relative polar stays EXACT with grid/ortho/running osnaps ON),
  typed DDE numbers through LINE, invalid-input diagnostics recover
  end-to-end, and Cancelled commands leave doc_version untouched.
"""

import math

import pytest

from bcdoc.settings import SETTING_DEFS
from bcdraft.precision import OSMODE_BITS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class RecordingProvider:
    """Scripted string provider that records every Request it serves (used
    to pin prompt texts, kinds, options and shown defaults)."""

    def __init__(self, ctx, items):
        from bccmd.input import parse

        self._parse = parse
        self._ctx = ctx
        self._items = list(items)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        item = self._items.pop(0)
        return self._parse(item, request, self._ctx.last_point)


# ---------------------------------------------------------------------------
# SETVAR
# ---------------------------------------------------------------------------

def test_setvar_bare_enter_lists_every_def_with_type_and_value(
        run, make_context, document):
    snapshot = document.settings.to_json()
    ctx = make_context()
    result = run(ctx, "SETVAR", ["", "GRIDMODE", "1"])
    assert result.status == "ok"
    assert document.settings.get("GRIDMODE") == 1
    # every SETTING_DEFS entry appears as "NAME (type) = value" feedback
    for name, definition in SETTING_DEFS.items():
        expected = f"{name} ({definition['type']}) = {snapshot[name]}"
        assert expected in ctx.feedback_messages
    assert len(ctx.feedback_messages) == len(SETTING_DEFS) + 1
    assert "SETVAR: GRIDMODE = 1" in ctx.feedback_messages


def test_setvar_typed_question_mark_lists_then_reprompts(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "SETVAR", ["?", "SNAPMODE", "1"])
    assert result.status == "ok"
    # the typed "?" listed the registry (contract §4 "? lists all") ...
    assert "OSMODE (int) = 55" in ctx.feedback_messages
    assert "CLAYER (str) = 0" in ctx.feedback_messages
    # ... then re-asked the NAME prompt (SNAPMODE accepted afterwards)
    assert document.settings.get("SNAPMODE") == 1
    assert "SETVAR: SNAPMODE = 1" in ctx.feedback_messages


def test_setvar_value_prompt_parses_typed_values_per_type(
        run, make_context, document):
    cases = [
        ("GRIDMODE", "1", 1),            # int
        ("APERTURE", "0.75", 0.75),       # float
        ("SNAPUNIT", "2.5", 2.5),         # float
        ("CLAYER", "0", "0"),             # str (layer 0 exists)
    ]
    for name, typed, expected in cases:
        ctx = make_context()
        result = run(ctx, "SETVAR", [name, typed])
        assert result.status == "ok"
        assert document.settings.get(name) == expected
        assert f"SETVAR: {name} = {expected}" in ctx.feedback_messages


def test_setvar_enter_at_value_prompt_keeps_shown_default(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "SETVAR", ["LUPREC", ""])
    assert result.status == "ok"
    assert result.summary == "SETVAR: LUPREC unchanged (4)"
    assert document.settings.get("LUPREC") == 4
    assert "SETVAR: LUPREC = 4" in ctx.feedback_messages


def test_setvar_unknown_name_feedback_then_reask(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "SETVAR", ["NOSUCHVAR", "GRIDMODE", "1"])
    assert result.status == "ok"
    assert "SETVAR: Unknown system variable: 'NOSUCHVAR'" in ctx.feedback_messages
    assert document.settings.get("GRIDMODE") == 1


def test_setvar_non_integer_for_int_setting_feedback_then_reask(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "SETVAR", ["GRIDMODE", "abc", "1"])
    assert result.status == "ok"
    assert "SETVAR: GRIDMODE expected an integer, got 'abc'" in ctx.feedback_messages
    assert document.settings.get("GRIDMODE") == 1


def test_setvar_choices_violation_feedback_then_reask(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "SETVAR", ["GRIDMODE", "5", "1"])
    assert result.status == "ok"
    assert any("expected one of [0, 1]" in m for m in ctx.feedback_messages)
    assert document.settings.get("GRIDMODE") == 1  # re-ask accepted the fix


def test_setvar_clayer_must_name_existing_layer(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "SETVAR", ["CLAYER", "GHOST", "0"])
    assert result.status == "ok"
    assert "SETVAR: layer 'GHOST' does not exist" in ctx.feedback_messages
    assert document.settings.get("CLAYER") == "0"
    # an existing custom layer is accepted
    with document.transaction("layer"):
        document.layers.add("WALL")
    ctx = make_context()
    result = run(ctx, "SETVAR", ["CLAYER", "WALL"])
    assert result.status == "ok"
    assert document.settings.get("CLAYER") == "WALL"


def test_setvar_cancel_before_value_prompt_leaves_settings_unchanged(
        run, make_context, document):
    document.settings.set("OSMODE", 1)          # a prior, non-default value
    ctx = make_context()
    result = run(ctx, "SETVAR", ["OSMODE"])      # queue ends at the value prompt
    assert result.status == "cancelled"
    assert document.settings.get("OSMODE") == 1
    assert document.settings.get("GRIDMODE") == 0


# ---------------------------------------------------------------------------
# GETVAR
# ---------------------------------------------------------------------------

def test_getvar_known_variable_value_feedback(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "GETVAR", ["OSMODE"])
    assert result.status == "ok"
    assert "OSMODE = 55" in ctx.feedback_messages
    assert result.summary == "GETVAR: OSMODE = 55"


def test_getvar_unknown_variable_error_feedback_reasks(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "GETVAR", ["NOPE", "AUNITS"])
    assert result.status == "ok"
    assert "GETVAR: Unknown system variable: 'NOPE'" in ctx.feedback_messages
    assert "AUNITS = 0" in ctx.feedback_messages


# ---------------------------------------------------------------------------
# OSNAP
# ---------------------------------------------------------------------------

def test_osnap_mode_list_sets_osmode_bits(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "OSNAP", ["END,MID"])
    assert result.status == "ok"
    assert document.settings.get("OSMODE") == \
        OSMODE_BITS["ENDPOINT"] | OSMODE_BITS["MIDPOINT"] == 3
    assert "OSNAP: running modes ENDPOINT, MIDPOINT" in ctx.feedback_messages


def test_osnap_short_and_full_names_via_os_alias(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "os", ["qua,tan"])          # alias + short names
    assert result.status == "ok"
    assert document.settings.get("OSMODE") == \
        OSMODE_BITS["QUADRANT"] | OSMODE_BITS["TANGENT"] == 1040
    ctx = make_context()
    result = run(ctx, "osnap", ["CENTER"])        # full names too
    assert document.settings.get("OSMODE") == OSMODE_BITS["CENTER"]


def test_osnap_none_and_off_clear_running_modes(run, make_context, document):
    ctx = make_context()
    assert run(ctx, "OSNAP", ["none"]).status == "ok"
    assert document.settings.get("OSMODE") == 0
    assert "OSNAP: off" in ctx.feedback_messages
    document.settings.set("OSMODE", 55)
    ctx = make_context()
    assert run(ctx, "OSNAP", ["off"]).status == "ok"
    assert document.settings.get("OSMODE") == 0


def test_osnap_bare_enter_shows_current_modes_without_changing(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "OSNAP", [""])
    assert result.status == "ok"
    assert document.settings.get("OSMODE") == 55     # unchanged
    assert "OSNAP: running modes ENDPOINT, MIDPOINT, CENTER, QUADRANT, " \
           "INTERSECTION" in ctx.feedback_messages
    document.settings.set("OSMODE", 0)
    ctx = make_context()
    result = run(ctx, "OSNAP", [""])
    assert result.status == "ok"
    assert "OSNAP: off (no running modes)" in ctx.feedback_messages


def test_osnap_invalid_mode_feedback_then_reask(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "OSNAP", ["bogus", "END"])
    assert result.status == "ok"
    assert any("unknown mode(s)" in m for m in ctx.feedback_messages)
    assert document.settings.get("OSMODE") == OSMODE_BITS["ENDPOINT"]


# ---------------------------------------------------------------------------
# ORTHO / SNAP / GRID / DYN — zero-prompt toggles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command,setting,label", [
    ("ORTHO", "ORTHOMODE", "Ortho"),
    ("SNAP", "SNAPMODE", "Snap"),
    ("GRID", "GRIDMODE", "Grid"),
])
def test_ortho_snap_grid_toggle_roundtrip(
        run, make_context, document, command, setting, label):
    version = document.doc_version
    ctx = make_context()
    result = run(ctx, command, [])               # no prompts: runs headless
    assert result.status == "ok"
    assert document.settings.get(setting) == 1
    assert f"{label} on" in ctx.feedback_messages
    ctx = make_context()
    result = run(ctx, command.lower(), [])
    assert result.status == "ok"
    assert document.settings.get(setting) == 0
    assert f"{label} off" in ctx.feedback_messages
    # toggles are settings writes — persisted but never journaled
    assert document.doc_version == version


def test_dynamicinput_dyn_alias_toggles_dynmode_3_0(
        run, make_context, document):
    assert document.settings.get("DYNMODE") == 3
    ctx = make_context()
    result = run(ctx, "DYN", [])                  # alias resolves
    assert result.status == "ok"
    assert document.settings.get("DYNMODE") == 0
    assert "Dynamic input off" in ctx.feedback_messages
    ctx = make_context()
    result = run(ctx, "dynamicinput", [])
    assert result.status == "ok"
    assert document.settings.get("DYNMODE") == 3
    assert "Dynamic input on" in ctx.feedback_messages


# ---------------------------------------------------------------------------
# UNITS — guided walk, defaults shown + Enter accepted, deferred apply
# ---------------------------------------------------------------------------

def test_units_walks_five_prompts_with_defaults_shown_and_enter_accepted(
        run, make_context, document):
    ctx = make_context()
    provider = RecordingProvider(ctx, ["", "", "", "", ""])
    result = run(ctx, "UNITS", [], provider=provider)
    assert result.status == "ok"
    requests = provider.requests
    assert [r.kind for r in requests] == ["string"] * 5
    by_marker = [
        ("LUNITS", "length units format"),
        ("LUPREC", "length precision"),
        ("AUNITS", "angle units format"),
        ("AUPREC", "angle precision"),
        ("INSUNITS", "insertion scale units"),
    ]
    defaults = dict(document.settings.items())
    for request, (name, marker) in zip(requests, by_marker):
        assert marker in request.prompt
        assert f"<{defaults[name]}>" in request.prompt   # default SHOWN
        assert request.default == defaults[name]
    # Enter everywhere accepted every default — nothing changed
    assert defaults == document.settings.to_json()
    assert "UNITS: length 2/4, angle 0/0, insertion units 0" \
        in ctx.feedback_messages


def test_units_each_variable_settable(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "UNITS", ["1", "3", "1", "2", "4"])
    assert result.status == "ok"
    assert (
        document.settings.get("LUNITS"),
        document.settings.get("LUPREC"),
        document.settings.get("AUNITS"),
        document.settings.get("AUPREC"),
        document.settings.get("INSUNITS"),
    ) == (1, 3, 1, 2, 4)
    assert "UNITS: length 1/3, angle 1/2, insertion units 4" \
        in ctx.feedback_messages


def test_units_invalid_value_feedback_then_reask(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "UNITS", ["xyz", "1", "3", "0", "0", "0"])
    assert result.status == "ok"
    assert "UNITS: LUNITS expected an integer, got 'xyz'" in ctx.feedback_messages
    assert document.settings.get("LUNITS") == 1


def test_units_cancel_mid_walk_changes_nothing(run, make_context, document):
    before = document.settings.to_json()
    ctx = make_context()
    # LUNITS=1 and LUPREC=3 entered and validated — then Esc at AUNITS
    result = run(ctx, "UNITS", ["1", "3"])
    assert result.status == "cancelled"
    assert document.settings.to_json() == before   # deferred apply held


# ---------------------------------------------------------------------------
# precision regressions through real commands
# ---------------------------------------------------------------------------

def test_line_typed_relative_polar_never_resolves(run, make_context, document):
    from bcdoc.entities import Line

    with document.transaction("seed"):
        document.add_entity(Line((0, 0, 0), (20, 0, 0)))   # nearby geometry
    # every resolution mode ON — typed input must still pass through EXACT
    document.settings.set("SNAPMODE", 1)
    document.settings.set("SNAPUNIT", 1.0)
    document.settings.set("ORTHOMODE", 1)
    document.settings.set("OSMODE", 55)
    ctx = make_context()
    result = run(ctx, "LINE", ["10,10", "@5<30", ""])
    assert result.status == "ok"
    segment = document.entities()[-1]
    rad = math.radians(30.0)
    want = (10.0 + 5.0 * math.cos(rad), 10.0 + 5.0 * math.sin(rad), 0.0)
    assert tuple(segment.p1) == (10.0, 10.0, 0.0)          # EXACT
    assert tuple(segment.p2) == want                      # EXACT, no snapping


def test_line_typed_number_is_direct_distance_entry_e2e(
        run, make_context, document):
    from bccmd import Point

    ctx = make_context()
    ctx.pointer = Point(0.0, 20.0, 0.0)          # pointer direction +Y
    result = run(ctx, "LINE", ["0,0", "25", ""])
    assert result.status == "ok"
    segment = document.entities()[-1]
    # DDE: last_point (0,0) + 25 along the pointer direction -> (0, 25)
    assert tuple(segment.p1) == (0.0, 0.0, 0.0)
    assert tuple(segment.p2) == (0.0, 25.0, 0.0)


def test_line_typed_dde_relative_then_distance_acceptance_flow(
        run, make_context, document):
    """The acceptance §11.2 walkthrough: relative point then a typed number
    continues the chain +X from the last point (pointer None)."""
    ctx = make_context()
    result = run(ctx, "LINE", ["0,0", "@3,4", "5", ""])
    assert result.status == "ok"
    assert len(result.created) == 2
    first = document.get(result.created[0])
    second = document.get(result.created[1])
    assert tuple(first.p2) == (3.0, 4.0, 0.0)
    assert tuple(second.p1) == (3.0, 4.0, 0.0)
    assert tuple(second.p2) == (8.0, 4.0, 0.0)


def test_circle_bad_distance_diagnostic_then_valid_continues(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "CIRCLE", ["10,10", "1.2.3", "5"])
    assert result.status == "ok"
    assert "Invalid number: '1.2.3'" in ctx.feedback_messages
    circle = document.entities()[-1]
    assert circle.kind == "circle"
    assert tuple(circle.center) == (10.0, 10.0, 0.0)
    assert circle.radius == 5.0


def test_line_invalid_coordinate_diagnostic_then_valid_continues(
        run, make_context, document):
    ctx = make_context()
    result = run(ctx, "LINE", ["12,", "0,0", "10,0", ""])
    assert result.status == "ok"
    assert "Invalid coordinate: '12,'" in ctx.feedback_messages
    segment = document.entities()[-1]
    assert tuple(segment.p1) == (0.0, 0.0, 0.0)
    assert tuple(segment.p2) == (10.0, 0.0, 0.0)


def test_cancelled_commands_leave_doc_version_unchanged(
        run, make_context, document):
    from bcdoc.entities import Line

    with document.transaction("seed"):
        document.add_entity(Line((0, 0, 0), (1, 0, 0)))
    version = document.doc_version
    # LINE cancelled after the first point (no segment committed yet)
    ctx = make_context()
    result = run(ctx, "LINE", ["0,0"])
    assert result.status == "cancelled"
    # CIRCLE cancelled at the radius prompt
    ctx = make_context()
    result = run(ctx, "CIRCLE", ["10,10"])
    assert result.status == "cancelled"
    # ERASE cancelled mid-Window (second corner)
    ctx = make_context()
    result = run(ctx, "ERASE", ["w", "0,0"])
    assert result.status == "cancelled"
    # SETVAR cancelled at the value prompt — settings are not journaled either
    ctx = make_context()
    result = run(ctx, "SETVAR", ["GRIDMODE"])
    assert result.status == "cancelled"
    assert document.doc_version == version
    assert len(document.entities()) == 1
    assert document.settings.get("GRIDMODE") == 0
