"""Scripted command flows for bcdraw annotations (contracts §5.2; §10 row).

Everything runs through the REAL registry with a ScriptedProvider (the
exact modal-operator/acceptance-battery interface) against the REAL bcdoc.
Exact geometry + entity fields are asserted; invalid input -> feedback +
re-prompt; Cancelled -> no partial state; one transaction per command run.
"""

import math

import pytest

from bccmd import Cancelled, selection_input
from bcdoc.entities import Circle, Line


def _messages(ctx):
    return "\n".join(ctx.feedback_messages)


# ---------------------------------------------------------------------------
# DIMLINEAR
# ---------------------------------------------------------------------------

def test_dimlinear_explicit_points_auto_horizontal(run, make_context, document):
    result = run(make_context(), "DIMLINEAR", ["0,0", "10,0", "5,3"])
    assert result.status == "ok"
    dim = document.get(result.created[0])
    assert dim.kind == "dim"
    assert dim.dim_type == "linear"
    assert dim.angle == 0.0            # auto-picked: dominant vertical offset
    assert dim.p1 == (0.0, 0.0, 0.0)
    assert dim.p2 == (10.0, 0.0, 0.0)
    assert dim.offset_point == (5.0, 3.0, 0.0)
    assert dim.measured_id == ""
    assert dim.measurement == 10.0
    assert dim.style == "Standard"
    assert dim.layer == "0" and dim.space == "MODEL"
    assert "10.0000" in result.summary
    assert document.doc_version == 1 and document.undo_depth() == 1


def test_dimlinear_auto_vertical_from_placement(run, make_context, document):
    result = run(make_context(), "DIMLINEAR", ["0,0", "0,10", "3,5"])
    dim = document.get(result.created[0])
    assert dim.angle == 90.0
    assert dim.measurement == 10.0


def test_dimlinear_keyword_vertical(run, make_context, document):
    result = run(make_context(), "DIMLINEAR",
                 ["0,0", "10,0", "V", "3,5"])
    dim = document.get(result.created[0])
    assert dim.angle == 90.0
    # vertical projection of a horizontal line: 0 up to the cos(90°) residue
    assert dim.measurement == pytest.approx(0.0, abs=1e-12)


def test_dimlinear_keyword_horizontal_then_location(run, make_context, document):
    result = run(make_context(), "DIMLINEAR",
                 ["0,0", "0,10", "H", "3,5"])
    dim = document.get(result.created[0])
    assert dim.angle == 0.0
    assert dim.measurement == 0.0     # horizontal projection of a vertical line


def test_dimlinear_rotation_option(run, make_context, document):
    result = run(make_context(), "DIMLINEAR",
                 ["0,0", "10,0", "R", "30", "5,3"])
    dim = document.get(result.created[0])
    assert dim.angle == 30.0
    assert dim.measurement == pytest.approx(10.0 * math.cos(math.radians(30.0)))
    assert "8.6603" in result.summary


def test_dimlinear_select_object_path_sets_associativity(run, make_context, document):
    ctx = make_context()
    line_result = run(ctx, "line", ["0,0", "10,0", ""])
    line_id = line_result.created[0]

    result = run(ctx, "DIMLINEAR", ["", selection_input([line_id]), "5,3"])
    assert result.status == "ok"
    dim = document.get(result.created[0])
    assert dim.measured_id == line_id
    assert dim.p1 == (0.0, 0.0, 0.0) and dim.p2 == (10.0, 0.0, 0.0)
    assert dim.measurement == 10.0
    assert "10.0000" in result.summary


def test_dimlinear_select_object_uses_preselection(run, make_context, document):
    ctx = make_context()
    line_result = run(ctx, "line", ["2,2", "12,2", ""])
    line_id = line_result.created[0]
    document.selection.add([line_id])   # PICKFIRST preselection

    result = run(ctx, "DIMLINEAR", ["", "5,7"])
    dim = document.get(result.created[0])
    assert dim.measured_id == line_id
    assert dim.p1 == (2.0, 2.0, 0.0) and dim.p2 == (12.0, 2.0, 0.0)


def test_dimlinear_select_rejects_non_line_then_accepts(run, make_context, document):
    ctx = make_context()
    with document.transaction("setup"):
        circle_id = document.add_entity(Circle((5, 5, 0), 3.0)).id
        line_id = document.add_entity(Line((0, 0, 0), (8, 0, 0))).id

    result = run(ctx, "DIMLINEAR",
                 ["", selection_input([circle_id]), selection_input([line_id]),
                  "4,3"])
    assert result.status == "ok"
    assert "no LINE entity" in _messages(ctx)
    dim = document.get(result.created[0])
    assert dim.measured_id == line_id


def test_dimlinear_select_enter_goes_back_to_origin_prompt(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMLINEAR", ["", "", "0,0", "10,0", "5,3"])
    assert result.status == "ok"
    dim = document.get(result.created[0])
    assert dim.measured_id == ""      # explicit path after backing out


def test_dimlinear_invalid_first_token_reasks(run, make_context, document):
    result = run(make_context(), "DIMLINEAR", ["nonsense", "0,0", "10,0", "5,3"])
    assert result.status == "ok"
    assert len(result.created) == 1


def test_dimlinear_coincident_origins_reask_second(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMLINEAR", ["0,0", "0,0", "10,0", "5,3"])
    assert result.status == "ok"
    assert "origins coincide" in _messages(ctx)
    dim = document.get(result.created[0])
    assert dim.p2 == (10.0, 0.0, 0.0)


def test_dimlinear_enter_at_placement_reasks(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMLINEAR", ["0,0", "10,0", "", "5,3"])
    assert result.status == "ok"
    assert "location point or option required" in _messages(ctx)


def test_dimlinear_cancel_mid_command_no_partial_state(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMLINEAR", ["0,0", "10,0", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {}
    assert document.doc_version == 0 and document.undo_depth() == 0


def test_dimlinear_missing_dimstyle_setting_falls_back_with_feedback(
        run, make_context, document):
    document.settings.set("DIMSTYLE", "Ghost")
    ctx = make_context()
    result = run(ctx, "DIMLINEAR", ["0,0", "10,0", "5,3"])
    assert result.status == "ok"
    assert "using 'Standard'" in _messages(ctx)
    dim = document.get(result.created[0])
    assert dim.style == "Standard"


# ---------------------------------------------------------------------------
# DIMALIGNED
# ---------------------------------------------------------------------------

def test_dimaligned_explicit_points(run, make_context, document):
    result = run(make_context(), "DIMALIGNED", ["0,0", "10,10", "12,2"])
    dim = document.get(result.created[0])
    assert dim.dim_type == "aligned"
    assert dim.angle == 45.0          # informational axis angle
    assert dim.measurement == pytest.approx(math.sqrt(200.0))
    assert "14.1421" in result.summary


def test_dimaligned_select_object_path(run, make_context, document):
    ctx = make_context()
    line_result = run(ctx, "line", ["0,0", "0,10", ""])
    result = run(ctx, "dimaligned",
                 ["", selection_input([line_result.created[0]]), "3,5"])
    dim = document.get(result.created[0])
    assert dim.measured_id == line_result.created[0]
    assert dim.dim_type == "aligned"
    assert dim.measurement == 10.0


def test_dimaligned_no_rotation_option(run, make_context, document):
    ctx = make_context()
    # "R" is not an option at the aligned placement prompt -> parse error,
    # feedback, re-ask; the point then places the dim
    result = run(ctx, "DIMALIGNED", ["0,0", "10,0", "R", "5,3"])
    assert result.status == "ok"
    dim = document.get(result.created[0])
    assert dim.offset_point == (5.0, 3.0, 0.0)


def test_dimaligned_cancel_no_partial_state(run, make_context, document):
    result = run(make_context(), "DIMALIGNED", ["0,0", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {}


# ---------------------------------------------------------------------------
# DIMSTYLE / STYLE / DIMREGEN
# ---------------------------------------------------------------------------

def test_dimstyle_list_then_exit(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMSTYLE", ["?", ""])
    assert result.status == "ok"
    messages = _messages(ctx)
    assert "Dim style 'Standard'" in messages
    assert "dimtxt=2.5" in messages
    assert "dimexo=0.625" in messages


def test_dimstyle_new_with_default_values(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMSTYLE",
                 ["New", "Big", "", "", "", "", ""])
    assert result.status == "ok"
    record = document.dim_style("Big")
    assert (record.dimscale, record.dimtxt, record.dimasz) == (1.0, 2.5, 2.5)
    assert (record.dimexo, record.dimexe) == (0.625, 1.25)
    assert document.undo_depth() == 1   # one journaled table mutation


def test_dimstyle_new_with_custom_values(run, make_context, document):
    result = run(make_context(), "DIMSTYLE",
                 ["New", "Big", "2", "5", "3", "0.5", "1"])
    record = document.dim_style("Big")
    assert (record.dimscale, record.dimtxt, record.dimasz) == (2.0, 5.0, 3.0)
    assert (record.dimexo, record.dimexe) == (0.5, 1.0)


def test_dimstyle_new_duplicate_name_feedback_reasks(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMSTYLE",
                 ["New", "Standard", "Mine", "", "", "", "", ""])
    assert result.status == "ok"
    assert "always exists" in _messages(ctx)
    assert "Mine" in document.dim_styles()


def test_dimstyle_new_zero_text_height_rejected_then_valid(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "DIMSTYLE",
                 ["New", "S2", "", "0", "3", "", "", ""])
    assert result.status == "ok"
    assert "value must be positive" in _messages(ctx)
    assert document.dim_style("S2").dimtxt == 3.0


def test_dimstyle_set_missing_name_reasks_then_sets(run, make_context, document):
    ctx = make_context()
    run(ctx, "DIMSTYLE", ["New", "Big", "", "", "", "", ""])
    result = run(ctx, "DIMSTYLE", ["Set", "Nope", "Big"])
    assert result.status == "ok"
    assert "no dim style named 'Nope'" in _messages(ctx)
    assert document.settings.get("DIMSTYLE") == "Big"


def test_dimstyle_set_changes_new_dimension_geometry(run, make_context, document):
    ctx = make_context()
    run(ctx, "DIMSTYLE", ["New", "Big", "", "5", "", "", ""])
    run(ctx, "DIMSTYLE", ["Set", "Big"])
    result = run(ctx, "DIMLINEAR", ["0,0", "10,0", "5,3"])
    dim = document.get(result.created[0])
    assert dim.style == "Big"
    # text lift = dimtxt*0.5 = 2.5 above the dim line (y=3 -> 5.5)
    from bcdraw.dims import resolve_dimension
    geometry, _text = resolve_dimension(dim, document)
    assert geometry.text_point == (5.0, 5.5, 0.0)


# ---------------------------------------------------------------------------
# TEXT / MTEXT / STYLE
# ---------------------------------------------------------------------------

def test_text_full_flow_with_defaults(run, make_context, document):
    result = run(make_context(), "TEXT", ["10,20", "", "", "HELLO WORLD"])
    assert result.status == "ok"
    text = document.get(result.created[0])
    assert text.kind == "text"
    assert text.position == (10.0, 20.0, 0.0)
    assert text.height == 2.5          # default from Standard style
    assert text.rotation == 0.0
    assert text.content == "HELLO WORLD"
    assert text.style == "Standard"
    assert text.justification == "LEFT"
    assert text.layer == "0" and text.space == "MODEL"


def test_text_justify_option_center(run, make_context, document):
    result = run(make_context(), "TEXT",
                 ["J", "C", "10,20", "", "", "Note"])
    text = document.get(result.created[0])
    assert text.justification == "CENTER"
    assert text.position == (10.0, 20.0, 0.0)


def test_text_justify_right_via_prefix(run, make_context, document):
    result = run(make_context(), "TEXT",
                 ["Justify", "R", "0,0", "1", "30", "Title"])
    text = document.get(result.created[0])
    assert text.justification == "RIGHT"
    assert text.height == 1.0 and text.rotation == 30.0


def test_text_height_defaults_from_current_style(run, make_context, document):
    ctx = make_context()
    run(ctx, "STYLE", ["New", "Small", "1", "0.8"])
    run(ctx, "STYLE", ["Set", "Small"])
    result = run(ctx, "TEXT", ["5,5", "", "", "R"])
    text = document.get(result.created[0])
    assert text.height == 1.0 and text.style == "Small"


def test_text_numeric_content_keeps_raw_text(run, make_context, document):
    result = run(make_context(), "TEXT", ["1,1", "", "", "12"])
    text = document.get(result.created[0])
    assert text.content == "12"       # raw text, never "12.0"


def test_text_zero_height_feedback_reask(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "TEXT", ["1,1", "0", "3", "", "hi"])
    assert result.status == "ok"
    assert "value must be positive" in _messages(ctx)
    assert document.get(result.created[0]).height == 3.0


def test_text_cancel_no_partial_state(run, make_context, document):
    result = run(make_context(), "TEXT", ["1,1", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {}


def test_mtext_flow_with_literal_newlines(run, make_context, document):
    # the scripted string contains the LITERAL two characters \ and n
    result = run(make_context(), "MTEXT", ["5,5", "40", "Line1\\nLine2"])
    assert result.status == "ok"
    mtext = document.get(result.created[0])
    assert mtext.kind == "mtext"
    assert mtext.position == (5.0, 5.0, 0.0)
    assert mtext.width == 40.0
    assert mtext.content == "Line1\nLine2"      # real newline
    assert mtext.style == "Standard"


def test_mtext_zero_width_feedback_reask(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "MTEXT", ["5,5", "0", "30", "text"])
    assert result.status == "ok"
    assert "value must be positive" in _messages(ctx)
    mtext = document.get(result.created[0])
    assert mtext.width == 30.0


def test_mtext_cancel_no_partial_state(run, make_context, document):
    result = run(make_context(), "MTEXT", ["5,5", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {}


def test_style_list_new_set(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "STYLE", ["?"])
    assert "Text style 'Standard'" in _messages(ctx)
    assert "height=2.5" in _messages(ctx)

    result = run(ctx, "STYLE", ["New", "Notes", "3.5", "0.8"])
    assert result.status == "ok"
    record = document.text_style("Notes")
    assert record.height == 3.5 and record.width_factor == 0.8

    run(ctx, "STYLE", ["Set", "Notes"])
    assert document.settings.get("TEXTSTYLE") == "Notes"


def test_style_new_duplicate_name_feedback_reasks(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "STYLE", ["New", "Standard", "Mine", "2", "1"])
    assert result.status == "ok"
    assert "always exists" in _messages(ctx)
    assert "Mine" in document.text_styles()


def test_style_set_missing_name_reasks(run, make_context, document):
    ctx = make_context()
    run(ctx, "STYLE", ["New", "Notes", "2", "1"])
    result = run(ctx, "STYLE", ["Set", "Ghost", "Notes"])
    assert result.status == "ok"
    assert "no text style named 'Ghost'" in _messages(ctx)
    assert document.settings.get("TEXTSTYLE") == "Notes"


# ---------------------------------------------------------------------------
# space routing
# ---------------------------------------------------------------------------

def test_text_lands_in_the_active_layout_space(run, make_context, document):
    ctx = make_context()
    run(ctx, "LAYOUT", ["New", "Sheet1", "", ""])
    run(ctx, "LAYOUT", ["Set", "Sheet1"])
    result = run(ctx, "TEXT", ["10,10", "", "", "PAPER"])
    text = document.get(result.created[0])
    assert text.space == "Sheet1"      # routed to the paper layout
    assert document.entities_in_space("Sheet1") == [text]
    assert document.settings.get("TILEMODE") == 0
