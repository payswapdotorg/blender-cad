"""Scripted command flows for bcdraw layouts (contracts §5.4; FP-LAY-001/
002/004/007): LAYOUT (List/New/Copy/Delete/Rename/Set/Move), MSPACE /
PSPACE space switching with TILEMODE maintenance, MVIEW viewports
(rect + Fit + explicit view), invalid-input recovery and cancellation.
"""

from bccmd import Cancelled
from bcdoc.entities import Line, Text, Viewport


def _messages(ctx):
    return "\n".join(ctx.feedback_messages)


def _add_layout(doc, name, **props):
    with doc.transaction("setup"):
        doc.add_layout(name, **props)
    return doc.layout(name)


def _add_entity(doc, entity):
    with doc.transaction("setup"):
        return doc.add_entity(entity)


# ---------------------------------------------------------------------------
# LAYOUT: New / List
# ---------------------------------------------------------------------------

def test_layout_new_with_default_page(run, make_context, document):
    result = run(make_context(), "LAYOUT", ["New", "Sheet1", "", ""])
    assert result.status == "ok"
    record = document.layout("Sheet1")
    assert record.page_width == 420.0 and record.page_height == 297.0
    assert record.paper_units == "mm"
    assert document.doc_version == 1 and document.undo_depth() == 1  # journaled


def test_layout_new_custom_page(run, make_context, document):
    result = run(make_context(), "LAYOUT", ["New", "A3L", "297", "210"])
    record = document.layout("A3L")
    assert record.page_width == 297.0 and record.page_height == 210.0


def test_layout_new_duplicate_name_feedback_reasks(run, make_context, document):
    _add_layout(document, "Sheet1")
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["New", "Sheet1", "Sheet2", "", ""])
    assert result.status == "ok"
    assert "already exists" in _messages(ctx)
    assert "Sheet2" in document.layouts()


def test_layout_new_refuses_reserved_model_name(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["New", "MODEL", "Sheet1", "", ""])
    assert result.status == "ok"
    assert "reserved for model space" in _messages(ctx)
    assert document.layouts() == ["Sheet1"]
    assert "MODEL" not in document.layouts()


def test_layout_new_invalid_page_reasks(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["New", "Sheet1", "0", "100", ""])
    assert result.status == "ok"
    assert "value must be positive" in _messages(ctx)
    record = document.layout("Sheet1")
    assert record.page_width == 100.0 and record.page_height == 297.0


def test_layout_list_then_enter_exits(run, make_context, document):
    _add_layout(document, "Sheet1", page_width=297.0, page_height=210.0)
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["?", ""])
    assert result.status == "ok"
    messages = _messages(ctx)
    assert "Layout 'Sheet1': 297 x 210 mm" in messages


def test_layout_enter_at_option_prompt_exits_politely(run, make_context, document):
    result = run(make_context(), "LAYOUT", [""])
    assert result.status == "ok"
    assert document.doc_version == 0 and document.layouts() == []


def test_layout_cancel_no_partial_state(run, make_context, document):
    result = run(make_context(), "LAYOUT", ["New", "Sheet1", Cancelled()])
    assert result.status == "cancelled"
    assert document.doc_version == 0 and document.layouts() == []


# ---------------------------------------------------------------------------
# LAYOUT: Set / Delete / Rename / Move / Copy
# ---------------------------------------------------------------------------

def test_layout_set_activates_paper_space(run, make_context, document):
    _add_layout(document, "Sheet1")
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["Set", "Sheet1"])
    assert result.status == "ok"
    assert document.current_space == "Sheet1"
    assert document.active_layout == "Sheet1"
    assert document.settings.get("TILEMODE") == 0


def test_layout_set_missing_name_reasks(run, make_context, document):
    _add_layout(document, "Sheet1")
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["Set", "Nope", "Sheet1"])
    assert result.status == "ok"
    assert "no layout named 'Nope'" in _messages(ctx)
    assert document.current_space == "Sheet1"


def test_layout_delete_removes_empty_layout(run, make_context, document):
    _add_layout(document, "Sheet1")
    result = run(make_context(), "LAYOUT", ["Delete", "Sheet1"])
    assert result.status == "ok"
    assert document.layouts() == []
    assert document.undo_depth() == 2   # setup tx + the delete tx
    document.undo()
    assert document.layouts() == ["Sheet1"]


def test_layout_delete_refuses_non_empty_space(run, make_context, document):
    _add_layout(document, "Sheet1")
    _add_entity(document, Text((10, 10, 0), content="frame", space="Sheet1"))
    ctx = make_context()
    before_version = document.doc_version
    result = run(ctx, "LAYOUT", ["Delete", "Sheet1", ""])   # refusal -> Exit
    assert result.status == "ok"                # refusal is feedback, not abort
    assert "still carries 1 entity" in _messages(ctx)
    assert document.layouts() == ["Sheet1"]     # layout intact
    assert document.doc_version == before_version   # no partial state


def test_layout_delete_last_layout_is_allowed_and_fixes_session(run, make_context, document):
    _add_layout(document, "Only")
    document.set_current_space("Only")
    document.active_layout = "Only"
    result = run(make_context(), "LAYOUT", ["Delete", "Only"])
    assert result.status == "ok"
    assert document.layouts() == []
    # session pointers never dangle after deleting the current/active layout
    assert document.current_space == "MODEL"
    assert document.active_layout is None
    assert document.settings.get("TILEMODE") == 1


def test_layout_rename_reroutes_entities_and_session(run, make_context, document):
    _add_layout(document, "Sheet1")
    text = _add_entity(document, Text((1, 1, 0), content="x", space="Sheet1"))
    document.set_current_space("Sheet1")
    document.active_layout = "Sheet1"
    result = run(make_context(), "LAYOUT", ["Rename", "Sheet1", "Plan"])
    assert result.status == "ok"
    assert document.layouts() == ["Plan"]
    assert text.space == "Plan"                    # re-routed by bcdoc
    assert document.current_space == "Plan"        # session pointers follow
    assert document.active_layout == "Plan"


def test_layout_rename_duplicate_new_name_reasks(run, make_context, document):
    _add_layout(document, "Sheet1")
    _add_layout(document, "Other")
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["Rename", "Sheet1", "Other", "Plan"])
    assert result.status == "ok"
    assert "already exists" in _messages(ctx)
    assert document.layouts() == ["Plan", "Other"]


def test_layout_move_reorders(run, make_context, document):
    _add_layout(document, "A")
    _add_layout(document, "B")
    _add_layout(document, "C")
    result = run(make_context(), "LAYOUT", ["Move", "A", "C"])
    assert result.status == "ok"
    assert document.layouts() == ["B", "A", "C"]


def test_layout_copy_clones_layout_record_and_entities(run, make_context, document):
    _add_layout(document, "Sheet1", page_width=297.0, page_height=210.0)
    text = _add_entity(document, Text((1, 1, 0), content="frame", space="Sheet1"))
    vp = _add_entity(document,
                     Viewport((5.0, 2.0, 0.0), 4.0, (0, 0, 0), (20, 10, 0),
                              space="Sheet1"))
    model_line = _add_entity(document, Line((0, 0, 0), (10, 0, 0)))  # MODEL

    ctx = make_context()
    result = run(ctx, "LAYOUT", ["Copy", "Sheet1", "Sheet2"])
    assert result.status == "ok"
    record = document.layout("Sheet2")
    assert (record.page_width, record.page_height) == (297.0, 210.0)

    clones = document.entities_in_space("Sheet2")
    assert len(clones) == 2                       # text + viewport cloned
    clone_ids = {c.id for c in clones}
    assert len(clone_ids) == 2
    assert clone_ids.isdisjoint({text.id, vp.id})  # FRESH identities (distinct ids)
    assert {c.handle for c in clones}.isdisjoint({text.handle, vp.handle})
    assert clones[0].space == "Sheet2" and clones[1].space == "Sheet2"
    # originals untouched
    assert text.space == "Sheet1" and vp.space == "Sheet1"
    assert document.entities_in_space("Sheet1") == [text, vp]
    # model space is not cloned
    assert document.entities_in_space("MODEL") == [model_line]
    # ONE undo step removes the whole copy (record + clones)
    assert document.undo_depth() == 5   # 4 setup txs + the copy tx
    document.undo()
    assert document.layouts() == ["Sheet1"]
    assert len(document.entities()) == 3   # the three originals only
    assert "Sheet2" not in document.layouts()


def test_layout_copy_missing_source_reasks(run, make_context, document):
    _add_layout(document, "Sheet1")
    ctx = make_context()
    result = run(ctx, "LAYOUT", ["Copy", "Nope", "Sheet1", "Sheet2"])
    assert result.status == "ok"
    assert "no layout named 'Nope'" in _messages(ctx)
    assert document.layouts() == ["Sheet1", "Sheet2"]


# ---------------------------------------------------------------------------
# MSPACE / PSPACE
# ---------------------------------------------------------------------------

def test_mspace_in_model_is_a_note(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "MSPACE", [])
    assert result.status == "ok"
    assert "already in model space" in _messages(ctx)
    assert document.current_space == "MODEL"
    assert document.settings.get("TILEMODE") == 1


def test_mspace_switches_to_model_keeping_active_layout(run, make_context, document):
    _add_layout(document, "Sheet1")
    document.set_current_space("Sheet1")
    document.active_layout = "Sheet1"
    result = run(make_context(), "MSPACE", [])
    assert result.status == "ok"
    assert document.current_space == "MODEL"
    assert document.active_layout == "Sheet1"     # VIEWING layout kept
    assert document.settings.get("TILEMODE") == 1


def test_pspace_without_active_layout_is_cancelled(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "PSPACE", [])
    assert result.status == "cancelled"
    assert "no active layout" in _messages(ctx)
    assert document.current_space == "MODEL"
    assert document.settings.get("TILEMODE") == 1


def test_pspace_after_mspace_returns_to_active_layout(run, make_context, document):
    _add_layout(document, "Sheet1")
    document.set_current_space("Sheet1")
    document.active_layout = "Sheet1"
    run(make_context(), "MSPACE", [])
    result = run(make_context(), "PSPACE", [])
    assert result.status == "ok"
    assert document.current_space == "Sheet1"
    assert document.settings.get("TILEMODE") == 0
    assert document.active_layout == "Sheet1"


def test_pspace_idempotent_when_already_in_paper(run, make_context, document):
    _add_layout(document, "Sheet1")
    document.set_current_space("Sheet1")
    document.active_layout = "Sheet1"
    result = run(make_context(), "PSPACE", [])
    assert result.status == "ok"
    assert document.current_space == "Sheet1"


# ---------------------------------------------------------------------------
# MVIEW
# ---------------------------------------------------------------------------

def _paper_ctx(document, make_context, layout="Sheet1"):
    _add_layout(document, layout)
    document.set_current_space(layout)
    document.active_layout = layout
    return make_context(document)


def test_mview_refused_in_model_space(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "MVIEW", ["5,5", "45,30", ""])
    assert result.status == "cancelled"
    assert "paper space" in _messages(ctx)
    assert document.count_by_kind() == {}


def test_mview_explicit_center_and_height(run, make_context, document):
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["5,5", "45,30", "10,5", "8"])
    assert result.status == "ok"
    vp = document.get(result.created[0])
    assert vp.kind == "viewport"
    assert vp.center == (10.0, 5.0, 0.0)
    assert vp.view_height == 8.0
    assert vp.p1 == (5.0, 5.0, 0.0)     # normalized lower-left
    assert vp.p2 == (45.0, 30.0, 0.0)   # normalized upper-right
    assert vp.space == "Sheet1" and vp.locked is False


def test_mview_corners_normalized_when_entered_reversed(run, make_context, document):
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["45,30", "5,5", "10,5", "8"])
    vp = document.get(result.created[0])
    assert vp.p1 == (5.0, 5.0, 0.0) and vp.p2 == (45.0, 30.0, 0.0)


def test_mview_fit_from_model_bbox_exact(run, make_context, document):
    _add_entity(document, Line((0.0, 0.0, 0.0), (10.0, 4.0, 0.0)))  # MODEL
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["5,5", "45,30", ""])   # Enter -> <Fit>
    assert result.status == "ok"
    vp = document.get(result.created[0])
    assert vp.center == (5.0, 2.0, 0.0)   # exact bbox center
    assert vp.view_height == 4.0           # exact bbox height
    assert "fit to model extents" in _messages(ctx)


def test_mview_fit_keyword_typed(run, make_context, document):
    _add_entity(document, Line((0.0, 0.0, 0.0), (10.0, 4.0, 0.0)))
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["5,5", "45,30", "Fit"])
    vp = document.get(result.created[0])
    assert vp.center == (5.0, 2.0, 0.0) and vp.view_height == 4.0


def test_mview_fit_with_empty_model_uses_documented_defaults(run, make_context, document):
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["5,5", "45,30", ""])
    assert result.status == "ok"
    vp = document.get(result.created[0])
    assert vp.center == (0.0, 0.0, 0.0)
    assert vp.view_height == 100.0
    assert "model space is empty" in _messages(ctx)


def test_mview_degenerate_rect_reasks(run, make_context, document):
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["5,5", "45,5", "45,30", "10,5", "8"])
    assert result.status == "ok"
    assert "must differ in both X and Y" in _messages(ctx)
    vp = document.get(result.created[0])
    assert vp.p1 == (5.0, 5.0, 0.0) and vp.p2 == (45.0, 30.0, 0.0)


def test_mview_negative_height_reasks(run, make_context, document):
    ctx = _paper_ctx(document, make_context)
    result = run(ctx, "MVIEW", ["5,5", "45,30", "10,5", "-2", "6"])
    assert result.status == "ok"
    assert "view height must be positive" in _messages(ctx)
    assert document.get(result.created[0]).view_height == 6.0


def test_mview_cancel_no_partial_state(run, make_context, document):
    ctx = _paper_ctx(document, make_context)
    before = document.doc_version
    result = run(ctx, "MVIEW", ["5,5", Cancelled()])
    assert result.status == "cancelled"
    assert document.count_by_kind() == {}
    assert document.doc_version == before   # only the setup tx remains
