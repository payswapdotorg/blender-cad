"""bcshell M2 smoke driver — scripted sessions against the LIVE command set.

Collected by plain pytest under modules/shell/tests (headless: the
``bcshell.run_scripted`` machinery — the SAME registry + prompt state
machine the modal UI uses — needs no Blender). Named blender_driver_m2.py
per the task letter; unlike blender_driver.py this one does NOT run a
Blender process — the in-Blender evidence battery is
modules/testing/blender/acceptance_m2.py (TL-run after integration).

Sections (task letter): LAYER new/set, LINE on layer, BLOCK/INSERT,
DIMLINEAR, TEXT, LAYOUT new + MVIEW — every section first probes the
registry and ``pytest.skip``s while its commands are absent, so the suite
is green before integration and ACTIVATES automatically when the parallel
commands land (verified: DIMLINEAR/TEXT/LAYOUT/MVIEW already run live
against the W-C bcdraw of this tree).

Honest note for TL (pinned in the worklog too): the scripted inputs for
sections whose commands have NOT landed yet (LAYER, BLOCK/INSERT) follow
the AutoCAD-familiar prompt flows pinned in contracts §0/§10 (LAYER New →
name → …; BLOCK name → base point → selection; INSERT name → insertion
point → scale → rotation). If the landed flows differ, only the scripted
input lists need adjusting — the doc-state assertions stay.
"""

import pytest

import bcshell.session as session
from bcshell import panel_ops


def _registry():
    return session.get_registry()


def _require(*names):
    """pytest.skip unless every named command is registered."""
    registry = _registry()
    missing = [name for name in names if registry.lookup(name) is None]
    if missing:
        pytest.skip(f"requires W-D/W-C integration: "
                    f"command(s) {', '.join(missing)} not registered")


def _doc():
    return session.active_document()


# ---------------------------------------------------------------------------
# section: LAYER new/set (+ the LINE-on-layer flow)
# ---------------------------------------------------------------------------

def test_section_layer_new_and_set_current(shell_session):
    _require("LAYER", "-LAYER")
    doc = _doc()
    registry = _registry()
    layer_command = "LAYER" if registry.lookup("LAYER") else "-LAYER"
    # W-D flow (commands_organization.py): an option loop — New -> name list,
    # Set -> name; a trailing Enter ends the loop
    result = session.run_scripted(
        layer_command, ["New", "WALLS", "Set", "WALLS", ""])
    assert result.ok, result.summary
    assert "WALLS" in doc.layers
    assert doc.current_layer == "WALLS"


def test_section_line_runs_on_current_layer(shell_session):
    # this half is live already: a layer made through the document API +
    # the panel's set-current-layer logic, then LINE must honor CLAYER
    doc = _doc()
    with doc.transaction("layer"):
        doc.layers.add("WALLS", color=1)
    ok, _ = panel_ops.set_current_layer(doc, "WALLS")
    assert ok
    result = session.run_scripted("LINE", ["0,0", "3,0", ""])
    assert result.ok and result.created, result.summary
    line = doc.get(result.created[0])
    assert line.layer == "WALLS"


# ---------------------------------------------------------------------------
# section: BLOCK / INSERT
# ---------------------------------------------------------------------------

def test_section_block_then_insert(shell_session):
    _require("BLOCK", "INSERT")
    doc = _doc()
    source = session.run_scripted("LINE", ["0,0", "1,0", ""])
    assert source.ok and source.created, source.summary
    from bccmd import selection_input

    # AutoCAD-familiar flow: BLOCK name -> base point -> select objects;
    # INSERT name -> insertion point -> scale -> rotation
    result = session.run_scripted(
        "BLOCK", ["MYBLOCK", "0,0", selection_input(list(source.created)),
                  ""])
    assert result.ok, result.summary
    assert "MYBLOCK" in doc.blocks()

    result = session.run_scripted(
        "INSERT", ["MYBLOCK", "10,0", "1", "0"])
    assert result.ok and result.created, result.summary
    insert = doc.get(result.created[0])
    assert insert.kind == "insert" and insert.name == "MYBLOCK"
    assert insert.position == (10.0, 0.0, 0.0)
    assert doc.block_ref_ids("MYBLOCK") == [insert.id]


# ---------------------------------------------------------------------------
# section: DIMLINEAR
# ---------------------------------------------------------------------------

def test_section_dimlinear_creates_dimension(shell_session):
    _require("DIMLINEAR")
    doc = _doc()
    # flow (W-C, live): first ext origin, second origin, placement point
    # (auto-picks Horizontal/Vertical from the placement direction)
    result = session.run_scripted("DIMLINEAR", ["0,0", "10,0", "5,5"])
    assert result.ok and result.created, result.summary
    dim = doc.get(result.created[0])
    assert dim.kind == "dim" and dim.dim_type == "linear"
    assert dim.measurement == pytest.approx(10.0)
    # display: ONE multi-spline curve + ONE font spec, both tagged with the
    # dim's id (contract §7)
    from bcshell import sync as bcshell_sync

    specs = bcshell_sync.display_specs(dim, doc)
    assert len(specs) == 2
    assert specs[0]["kind"] == "curve" and specs[0]["role"] == "dim"
    assert specs[1]["kind"] == "font" and specs[1]["role"] == "dim-text"
    assert all(spec["bcdoc_id"] == dim.id for spec in specs)
    # the formatted measurement is the font body (LUPREC default 4)
    assert specs[1]["body"].replace("-", "").replace(".", "").isdigit()
    assert "10" in specs[1]["body"]


def test_section_dimlinear_associative_regen_after_move(shell_session):
    _require("DIMLINEAR")
    doc = _doc()
    from bccmd import selection_input

    line = session.run_scripted("LINE", ["0,0", "10,0", ""])
    assert line.ok and line.created
    # entity-select path: Enter at the origin prompt -> select the line
    result = session.run_scripted(
        "DIMLINEAR", ["", selection_input(list(line.created)), "5,5"])
    assert result.ok and result.created, result.summary
    dim = doc.get(result.created[0])
    assert dim.measured_id == line.created[0]
    assert dim.measurement == pytest.approx(10.0)

    # associativity: stretching the measured ENDPOINT (the STRETCH-style
    # journaled mutation) — a rigid MOVE never changes a line's length —
    # must refresh the dim cache through the bcshell on_change chain
    # (refresh_document_dims -> sync fires on the committed transaction)
    with doc.transaction("stretch the measured endpoint"):
        doc.update_entity(line.created[0], p2=(15.0, 0.0, 0.0))
    assert dim.measurement == pytest.approx(15.0), (
        "the on_change chain did not refresh the associated dim")
    # already current: an explicit regen pass refreshes nothing further
    from bcshell import sync as bcshell_sync

    assert bcshell_sync.refresh_document_dims(doc) == 0


# ---------------------------------------------------------------------------
# section: TEXT
# ---------------------------------------------------------------------------

def test_section_text_creates_font_entity(shell_session):
    _require("TEXT")
    doc = _doc()
    # flow (W-C, live): start point, height, rotation, content string
    result = session.run_scripted("TEXT", ["2,2", "1", "0", "HELLO"])
    assert result.ok and result.created, result.summary
    text = doc.get(result.created[0])
    assert text.kind == "text"
    assert text.content == "HELLO"
    assert text.position == (2.0, 2.0, 0.0)
    # display: ONE font spec (body == content, size == height)
    from bcshell import sync as bcshell_sync

    specs = bcshell_sync.display_specs(text, doc)
    assert len(specs) == 1
    assert specs[0]["kind"] == "font"
    assert specs[0]["body"] == "HELLO"
    assert specs[0]["size"] == 1.0


# ---------------------------------------------------------------------------
# section: LAYOUT new + MVIEW
# ---------------------------------------------------------------------------

def test_section_layout_new_set_and_mview(shell_session):
    _require("LAYOUT", "MVIEW")
    doc = _doc()
    # give the model space a bbox for MVIEW's Fit default
    seed = session.run_scripted("LINE", ["0,0", "20,0", ""])
    assert seed.ok, seed.summary

    # flow (W-C, live): option New -> name -> page width <420> -> height <297>
    result = session.run_scripted("LAYOUT", ["New", "Sheet1", "", ""])
    assert result.ok, result.summary
    assert "Sheet1" in doc.layouts()

    result = session.run_scripted("LAYOUT", ["Set", "Sheet1"])
    assert result.ok, result.summary
    assert doc.current_space == "Sheet1"
    assert doc.active_layout == "Sheet1"
    assert doc.settings.get("TILEMODE") == 0

    # MVIEW: two corners + Enter accepts the <Fit> default
    result = session.run_scripted("MVIEW", ["10,10", "110,90", ""])
    assert result.ok and result.created, result.summary
    viewport = doc.get(result.created[0])
    assert viewport.kind == "viewport"
    assert viewport.space == "Sheet1"
    assert viewport.p1 == (10.0, 10.0, 0.0)
    assert viewport.p2 == (110.0, 90.0, 0.0)
    assert viewport.view_height > 0.0          # fit to the model bbox

    # display: the viewport frame routes to the LAYOUT collection
    from bcshell import sync as bcshell_sync

    spec = bcshell_sync.display_specs(viewport, doc)[0]
    assert spec["role"] == "viewport-frame"
    assert bcshell_sync.space_collection_name(spec["space"]) == \
        "BlenderCAD/Layout Sheet1"


def test_section_layout_new_refuses_model_and_duplicates(shell_session):
    _require("LAYOUT")
    doc = _doc()
    assert session.run_scripted("LAYOUT", ["New", "Sheet1", "", ""]).ok
    duplicate = session.run_scripted("LAYOUT", ["New", "Sheet1", "", ""])
    assert duplicate.status == "cancelled" or "exists" in duplicate.summary
    assert doc.layouts().count("Sheet1") == 1
