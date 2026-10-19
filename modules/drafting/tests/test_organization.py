"""M2 organization-command tests: LAYER, BLOCK, INSERT (contract §0).

The full -LAYER option loop (?List/Make/Set/New/Color/Ltype/Lineweight/
ON/OFF/Freeze/Thaw/Lock/Unlock/Plot/NoPlot/State?), BLOCK definition copy
semantics + redefinition updating references, INSERT name listing + exact
placement, and current-layer/current-space routing for entities created by
draw commands. Everything runs through ``Registry.run_command`` with a
ScriptedProvider against the REAL bcdoc.
"""

import math

import pytest

from bccmd import selection_input

from bcdoc.entities import Circle, Insert, Line

from bcdraft.geometry import entity_bbox


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed(document, entities):
    with document.transaction("seed"):
        for entity in entities:
            document.add_entity(entity)
    return [entity.id for entity in entities]


# ---------------------------------------------------------------------------
# LAYER — listing
# ---------------------------------------------------------------------------

def test_layer_question_lists_every_record(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("Walls", color=1, linetype="DASHED", lineweight=0.35)
        document.layers.add("Doors", color=5)
    ctx = make_context()
    result = run(ctx, "layer", ["?List", ""])
    assert result.status == "ok"
    assert result.summary == "LAYER: done"
    listed = [m for m in ctx.feedback_messages if m.startswith("LAYER: ")]
    assert len(listed) == 3  # "0" + Walls + Doors
    walls = next(m for m in listed if "Walls" in m)
    assert "color 1" in walls
    assert "DASHED" in walls
    assert "0.35 mm" in walls


# ---------------------------------------------------------------------------
# LAYER — New / Make / Set
# ---------------------------------------------------------------------------

def test_layer_new_comma_list_creates_in_one_transaction(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "layer", ["New", "A,B,C", ""])
    assert result.status == "ok"
    assert any("3 layer(s) created" in m for m in ctx.feedback_messages)
    assert list(document.layers) == ["0", "A", "B", "C"]
    assert document.undo_depth() == 1  # ONE transaction for the whole list


def test_layer_new_existing_name_feedback(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "layer", ["New", "X,X,Y", ""])
    assert result.status == "ok"
    assert "already exists" in "\n".join(ctx.feedback_messages)
    assert list(document.layers) == ["0", "X", "Y"]


def test_layer_new_numeric_name_spelled_exactly(run, make_context, document):
    # typed "3" parses as the number 3.0 — the name must stay "3"
    ctx = make_context()
    result = run(ctx, "layer", ["New", "3", ""])
    assert result.status == "ok"
    assert "3" in document.layers
    assert "3.0" not in document.layers


def test_layer_make_creates_and_sets_current(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "layer", ["Make", "Walls", ""])
    assert result.status == "ok"
    assert any("layer 'Walls' created" in m for m in ctx.feedback_messages)
    assert document.current_layer == "Walls"
    # the new entities follow CLAYER
    run(ctx, "line", ["0,0", "1,0", ""])
    assert document.entities()[-1].layer == "Walls"
    # CLAYER is a SETTING (persisted, not journaled): only the layer add is
    # journaled
    assert document.undo_depth() == 2


def test_layer_make_existing_layer_only_sets_current(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("Walls")
    ctx = make_context()
    run(ctx, "layer", ["Make", "Walls", ""])
    assert document.current_layer == "Walls"
    assert not any(
        "created" in m for m in ctx.feedback_messages
    )
    assert document.undo_depth() == 1  # no add happened


def test_layer_set_existing_and_missing(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("Walls")
    ctx = make_context()
    result = run(ctx, "layer", ["Set", "Nope", "Walls", ""])
    assert result.status == "ok"
    assert any("layer 'Nope' not found" in m for m in ctx.feedback_messages)
    assert any("current layer is 'Walls'" in m for m in ctx.feedback_messages)
    assert document.current_layer == "Walls"


# ---------------------------------------------------------------------------
# LAYER — Color / Ltype / Lineweight
# ---------------------------------------------------------------------------

def test_layer_color_validates_range_then_applies(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("Walls")
    ctx = make_context()
    result = run(ctx, "layer", ["Color", "0", "256", "1.5", "5", "Walls", ""])
    assert result.status == "ok"
    assert sum(
        1 for m in ctx.feedback_messages if "integer 1-255" in m
    ) == 3
    assert document.layers.get("Walls").color == 5
    assert any("applied to 1 layer(s)" in m for m in ctx.feedback_messages)


def test_layer_color_comma_list_applies_to_each(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("A")
        document.layers.add("B")
    run(make_context(), "layer", ["Color", "3", "A,B", ""])
    assert document.layers.get("A").color == 3
    assert document.layers.get("B").color == 3


def test_layer_color_missing_layer_no_false_applied(
    run, make_context, document
):
    ctx = make_context()
    result = run(ctx, "layer", ["Color", "5", "Ghost", ""])
    assert result.status == "ok"
    assert any("not found — skipped" in m for m in ctx.feedback_messages)
    assert not any("applied" in m for m in ctx.feedback_messages)


def test_layer_ltype_stored_as_name(run, make_context, document):
    ctx = make_context()
    run(ctx, "layer", ["Ltype", "DASHED", "0", ""])
    assert document.layers.get("0").linetype == "DASHED"


def test_layer_lineweight_zero_means_default(run, make_context, document):
    ctx = make_context()
    run(ctx, "layer", ["Lineweight", "0.35", "0", ""])
    assert document.layers.get("0").lineweight == 0.35
    # 0 mm maps back to ByLayer/Default (None)
    run(ctx, "layer", ["Lineweight", "0", "0", ""])
    assert document.layers.get("0").lineweight is None


def test_layer_lineweight_negative_reprompts(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "layer", ["Lineweight", "-1", "0.5", "0", ""])
    assert result.status == "ok"
    assert any("zero or positive" in m for m in ctx.feedback_messages)
    assert document.layers.get("0").lineweight == 0.5


# ---------------------------------------------------------------------------
# LAYER — flags
# ---------------------------------------------------------------------------

def test_layer_on_off_lock_unlock_plot_noplot_run_in_one_tx(
    run, make_context, document
):
    with document.transaction("l"):
        document.layers.add("Q")
    ctx = make_context()
    result = run(
        ctx, "layer",
        ["OFF", "Q",
         "Lock", "Q",
         "NoPlot", "Q",
         "ON", "Q",
         "Unlock", "Q",
         "Plot", "Q",
         ""],
    )
    assert result.status == "ok"
    record = document.layers.get("Q")
    assert record.on and not record.locked and record.plot
    # one transaction per flag invocation: 1 (layer add) + 6
    assert document.undo_depth() == 7


def test_layer_freeze_thaw(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("X")
    ctx = make_context()
    run(ctx, "layer", ["Freeze", "X", "Thaw", "X", ""])
    assert document.layers.get("X").frozen is False
    assert any("Freeze applied" in m for m in ctx.feedback_messages)
    assert any("Thaw applied" in m for m in ctx.feedback_messages)


def test_layer_freeze_current_layer_refused(run, make_context, document):
    ctx = make_context()
    run(ctx, "layer", ["Make", "Cur", ""])
    result = run(ctx, "layer", ["Freeze", "Cur", "Thaw", "Cur", ""])
    assert any(
        "cannot freeze the current layer 'Cur'" in m for m in ctx.feedback_messages
    )
    assert document.layers.get("Cur").frozen is False
    # Thaw on an unfrozen layer is legal (no-op state change)
    assert document.layers.get("Cur").frozen is False


def test_layer_flag_missing_layer_skipped(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "layer", ["Lock", "Ghost,0", ""])
    assert any(
        "layer 'Ghost' not found — skipped" in m for m in ctx.feedback_messages
    )
    # the existing name in the same list is still processed
    assert document.layers.get("0").locked is True


def test_layer_state_option_honest_not_supported(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "layer", ["State?", ""])
    assert result.status == "ok"
    assert any("not supported" in m for m in ctx.feedback_messages)


def test_layer_option_loop_runs_until_enter(run, make_context, document):
    # several options in ONE invocation: the loop keeps prompting until Enter
    ctx = make_context()
    result = run(
        ctx, "layer",
        ["New", "A,B", "Color", "7", "A", "Set", "B", ""],
    )
    assert result.status == "ok"
    assert document.current_layer == "B"
    assert document.layers.get("A").color == 7
    assert list(document.layers) == ["0", "A", "B"]


def test_layer_unknown_option_feedback(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "layer", ["frobnicate", "New", "A", ""])
    assert result.status == "ok"
    assert any("unknown option" in m for m in ctx.feedback_messages)
    assert "A" in document.layers


# ---------------------------------------------------------------------------
# BLOCK
# ---------------------------------------------------------------------------

def test_block_definition_stores_copies(run, make_context, document):
    ctx = make_context()
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    result = run(ctx, "block", ["MYBLOCK", "1,0", selection_input(ids)])
    assert result.status == "ok"
    assert "'MYBLOCK' defined with 1 member(s)" in result.summary
    # originals STAY in the drawing (documented v0 divergence, feedback says so)
    assert document.count_by_kind() == {"line": 1}
    assert any("source objects stay" in m for m in ctx.feedback_messages)
    # mutating the original afterwards leaves the definition unchanged
    with document.transaction("mutate"):
        document.update_entity(ids[0], p2=(99, 0, 0))
    definition = document.block("MYBLOCK")
    assert definition.base_point == (1.0, 0.0, 0.0)
    assert definition.entities[0].p1 == (0.0, 0.0, 0.0)
    assert definition.entities[0].p2 == (4.0, 0.0, 0.0)


def test_block_question_lists_definitions(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (1, 0, 0))])
    run(make_context(), "block", ["AAA", "0,0", selection_input(ids)])
    ctx = make_context()
    result = run(ctx, "block", ["?", ""])
    assert result.status == "cancelled" or result.status == "ok"
    assert any("AAA" in m for m in ctx.feedback_messages)


def test_block_empty_listing_is_honest(run, make_context, document):
    ctx = make_context()
    run(ctx, "block", ["?", ""])
    assert any("no block definitions" in m for m in ctx.feedback_messages)


def test_block_no_selection_nothing_defined(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "block", ["MYBLOCK", "0,0", ""])
    assert result.status == "ok"
    assert "nothing defined" in result.summary
    assert document.block_names() == []


def test_block_redefine_updates_references(run, make_context, document):
    line_id, circle_id = _seed(
        document, [Line((0, 0, 0), (4, 0, 0)), Circle((0, 0, 0), 7)]
    )
    run(make_context(), "block", ["B", "0,0", selection_input([line_id])])
    with document.transaction("insert"):
        insert_id = document.add_entity(Insert("B", (10, 10, 0))).id
    # display-independent geometry BEFORE: the insert bbox shows the line
    assert entity_bbox(document.get(insert_id), document) == (
        10.0, 10.0, 14.0, 10.0,
    )
    ctx = make_context()
    result = run(
        ctx, "block", ["B", "0,0", selection_input([circle_id]), ""]
    )
    assert result.status == "ok"
    assert "redefined" in result.summary
    assert any("already exists — redefining" in m for m in ctx.feedback_messages)
    assert any("1 reference(s) updated" in m for m in ctx.feedback_messages)
    assert document.block_ref_ids("B") == [insert_id]
    # display-independent geometry AFTER: the same reference now shows the
    # circle member (radius 7 about the insert position)
    assert entity_bbox(document.get(insert_id), document) == (
        3.0, 3.0, 17.0, 17.0,
    )
    # the redefined members are copies: mutating the source circle later
    # does not change the definition
    with document.transaction("mutate"):
        document.update_entity(circle_id, radius=1)
    assert document.block("B").entities[0].radius == 7


def test_block_redefine_with_new_base_point(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["B", "0,0", selection_input([ids[0]])])
    with document.transaction("insert"):
        insert_id = document.add_entity(Insert("B", (10, 10, 0))).id
    run(make_context(), "block", ["B", "2,0", selection_input([ids[0]]), ""])
    # base (2,0): the member line (0..4) now hangs 2 left of the insertion
    assert entity_bbox(document.get(insert_id), document) == (
        8.0, 10.0, 12.0, 10.0,
    )


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------

def test_insert_missing_name_reasks_then_lists(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "insert", ["NOPE", "?", ""])
    assert result.status == "ok" or result.status == "cancelled"
    assert any(
        "block 'NOPE' not found" in m for m in ctx.feedback_messages
    )
    assert any(
        "no block definitions" in m for m in ctx.feedback_messages
    )


def test_insert_full_flow_exact_placement(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["MYBLOCK", "1,0", selection_input(ids)])
    ctx = make_context()
    result = run(ctx, "insert", ["MYBLOCK", "10,10", "2", "30", ""])
    assert result.status == "ok"
    insert = document.get(result.created[0])
    assert insert.name == "MYBLOCK"
    assert insert.position == (10.0, 10.0, 0.0)
    assert insert.scale == (2.0, 2.0, 2.0)
    assert insert.rotation == 30.0
    # lands on the CURRENT layer in the CURRENT space
    assert insert.layer == "0"
    assert insert.space == "MODEL"
    # the transformed member geometry: base (1,0) subtracted, scale 2,
    # rotation 30 CCW, translated to (10,10)
    member = document.block("MYBLOCK").entities[0]
    assert member.p1 == (0.0, 0.0, 0.0) and member.p2 == (4.0, 0.0, 0.0)
    rad = math.radians(30.0)
    expected_p1 = (10.0 + 2.0 * (0.0 - 1.0) * math.cos(rad),
                   10.0 + 2.0 * (0.0 - 1.0) * math.sin(rad))
    expected_p2 = (10.0 + 2.0 * (4.0 - 1.0) * math.cos(rad),
                   10.0 + 2.0 * (4.0 - 1.0) * math.sin(rad))
    assert entity_bbox(insert, document) == pytest.approx(
        (expected_p1[0], expected_p1[1], expected_p2[0], expected_p2[1])
    )


def test_insert_defaults_scale_one_rotation_zero(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["B", "0,0", selection_input(ids)])
    result = run(make_context(), "insert", ["B", "5,5", "", ""])
    insert = document.get(result.created[0])
    assert insert.scale == (1.0, 1.0, 1.0)
    assert insert.rotation == 0.0


def test_insert_xyz_scale_option(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["B", "0,0", selection_input(ids)])
    ctx = make_context()
    result = run(
        ctx, "insert", ["B", "0,0", "XYZ", "2", "3", "4", "45", ""]
    )
    insert = document.get(result.created[0])
    assert insert.scale == (2.0, 3.0, 4.0)
    assert insert.rotation == 45.0
    assert any("scale (2,3,4)" in m for m in ctx.feedback_messages)


def test_insert_negative_scale_reprompts(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["B", "0,0", selection_input(ids)])
    ctx = make_context()
    result = run(ctx, "insert", ["B", "0,0", "-1", "1.5", ""])
    assert result.status == "ok"
    assert any("positive" in m for m in ctx.feedback_messages)
    insert = document.get(result.created[0])
    assert insert.scale == (1.5, 1.5, 1.5)


def test_insert_then_move_works(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["B", "0,0", selection_input(ids)])
    result = run(make_context(), "insert", ["B", "5,5", "", ""])
    insert_id = result.created[0]
    result = run(
        make_context(), "move", [selection_input([insert_id]), "0,0", "5,0"]
    )
    assert result.modified == [insert_id]
    assert document.get(insert_id).position == (10.0, 5.0, 0.0)


def test_insert_lands_on_current_layer_and_space(run, make_context, document):
    ids = _seed(document, [Line((0, 0, 0), (4, 0, 0))])
    run(make_context(), "block", ["B", "0,0", selection_input(ids)])
    with document.transaction("l"):
        document.layers.add("Fixture")
    document.settings.set("CLAYER", "Fixture")
    with document.transaction("lay"):
        document.add_layout("Layout1")
    document.set_current_space("Layout1")
    result = run(make_context(), "insert", ["B", "1,1", "", ""])
    insert = document.get(result.created[0])
    assert insert.layer == "Fixture"
    assert insert.space == "Layout1"
    assert document.entities_in_space("Layout1") == [insert]


# ---------------------------------------------------------------------------
# space routing for draw commands
# ---------------------------------------------------------------------------

def test_entity_created_while_layout_active_lands_there(
    run, make_context, document
):
    with document.transaction("lay"):
        document.add_layout("Layout1")
    document.set_current_space("Layout1")
    ctx = make_context()
    result = run(ctx, "point", ["3,3"])
    point = document.get(result.created[0])
    assert point.space == "Layout1"
    assert document.current_space == "Layout1"
    # MODEL did not gain the entity
    assert document.entities_in_space("MODEL") == []
    # switching back routes new entities to MODEL again
    document.set_current_space("MODEL")
    run(ctx, "rectang", ["0,0", "1,1"])
    assert document.entities()[-1].space == "MODEL"


def test_line_follows_current_layer_and_space(run, make_context, document):
    with document.transaction("l"):
        document.layers.add("Walls")
    document.settings.set("CLAYER", "Walls")
    with document.transaction("lay"):
        document.add_layout("Sheet")
    document.set_current_space("Sheet")
    run(make_context(), "line", ["0,0", "1,1", ""])
    line = document.entities()[0]
    assert line.layer == "Walls"
    assert line.space == "Sheet"
