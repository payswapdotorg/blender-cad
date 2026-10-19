"""Selection-mode keyword tests — All/Previous/Window/Crossing/Last through
REAL commands (m2 contracts §4 + §10, drafting row).

Every mode resolves through ``bcdraft._common.select_ids`` — the shared
selection prompt behind every modify command — driven here by ERASE/MOVE
scripted runs, plus the operator-facing SELECT command (``bcdraft.selection``)
end-to-end. Pinned semantics under test:

* All — every CURRENT-space entity on a non-frozen layer (frozen and other
  spaces never resolve);
* Previous — ``doc.last_selection_ids``, the last NON-EMPTY resolution (an
  empty Enter never replaces the pool; stale ids drop out);
* Window/Crossing — two corner picks: full bbox containment vs bbox
  intersection;
* Last — the most recently created entity in the current space;
* keyword prefixes ("a"/"p"/"w"/"c"/"l") per the bccmd matcher;
* locked-layer entities ARE resolved but modify commands partition them out
  with "N entity(ies) on locked layer skipped" feedback (contract §2.2/§4).
"""

from bccmd import selection_input
from bcdoc.entities import Circle, Line
from bcdraft._common import SELECTION_MODES


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _line(document, p1, p2, layer="0", space="MODEL"):
    with document.transaction("add"):
        return document.add_entity(Line(p1, p2, layer=layer, space=space))


def _layer(document, name, **props):
    with document.transaction("layer"):
        document.layers.add(name)
        document.layers.set_props(name, **props)
    return name


class RecordingProvider:
    """Scripted string provider that records every Request it serves."""

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
# All
# ---------------------------------------------------------------------------

def test_all_selects_every_current_space_entity(run, make_context, document):
    lines = [_line(document, (0, 0, 0), (1, 0, 0)) for _ in range(3)]
    ctx = make_context()
    result = run(ctx, "ERASE", ["a"])
    assert result.status == "ok"
    assert result.summary == "ERASE: removed 3 object(s)"
    assert sorted(result.removed) == sorted(e.id for e in lines)
    assert document.entities() == []


def test_all_excludes_frozen_layers(run, make_context, document):
    _layer(document, "FROZ", frozen=True)
    live1 = _line(document, (0, 0, 0), (1, 0, 0))
    live2 = _line(document, (0, 1, 0), (1, 1, 0))
    frozen = _line(document, (0, 2, 0), (1, 2, 0), layer="FROZ")
    ctx = make_context()
    result = run(ctx, "ERASE", ["All"])
    assert result.status == "ok"
    assert sorted(result.removed) == sorted([live1.id, live2.id])
    assert [e.id for e in document.entities()] == [frozen.id]


def test_all_is_current_space_only(run, make_context, document):
    with document.transaction("layout"):
        document.add_layout("P1")
    model1 = _line(document, (0, 0, 0), (1, 0, 0))
    model2 = _line(document, (0, 1, 0), (1, 1, 0))
    paper = _line(document, (0, 0, 0), (1, 0, 0), space="P1")
    assert document.current_space == "MODEL"
    ctx = make_context()
    result = run(ctx, "ERASE", ["a"])
    assert result.status == "ok"
    assert sorted(result.removed) == sorted([model1.id, model2.id])
    assert [e.id for e in document.entities()] == [paper.id]


# ---------------------------------------------------------------------------
# Window / Crossing
# ---------------------------------------------------------------------------

def test_window_requires_full_containment(run, make_context, document):
    inside = _line(document, (0.25, 0.5, 0), (0.75, 0.5, 0))
    crossing = _line(document, (0.5, 0.5, 0), (2.0, 0.5, 0))
    outside = _line(document, (5.0, 5.0, 0), (6.0, 5.0, 0))
    ctx = make_context()
    result = run(ctx, "ERASE", ["w", "0,0", "1,1"])
    assert result.status == "ok"
    assert result.removed == [inside.id]           # insertion order preserved
    assert sorted(e.id for e in document.entities()) == \
        sorted([crossing.id, outside.id])


def test_window_corner_prompts_and_reversed_corners(
        run, make_context, document):
    inside = _line(document, (0.25, 0.5, 0), (0.75, 0.5, 0))
    outside = _line(document, (5.0, 5.0, 0), (6.0, 5.0, 0))
    ctx = make_context()
    provider = RecordingProvider(ctx, ["w", "1,1", "0,0"])   # reversed corners
    result = run(ctx, "ERASE", [], provider=provider)
    assert result.status == "ok"
    assert result.removed == [inside.id]                    # rect normalizes
    kinds = [r.kind for r in provider.requests]
    assert kinds == ["selection", "point", "point"]
    assert provider.requests[1].prompt == "ERASE Specify first corner:"
    assert provider.requests[2].prompt == "ERASE Specify opposite corner:"


def test_crossing_selects_bbox_intersect(run, make_context, document):
    crossing = _line(document, (0.5, 0.5, 0), (2.0, 0.5, 0))
    # circle bbox (4..6, 4..6) clips the rect (0..4.5, 0..4.5) although the
    # curve itself never enters it — crossing is a BBOX intersect
    with document.transaction("add"):
        circle = document.add_entity(Circle((5.0, 5.0, 0), 1.0))
    outside = _line(document, (10.0, 10.0, 0), (11.0, 10.0, 0))
    ctx = make_context()
    result = run(ctx, "ERASE", ["c", "0,0", "4.5,4.5"])
    assert result.status == "ok"
    assert sorted(result.removed) == sorted([crossing.id, circle.id])
    assert [e.id for e in document.entities()] == [outside.id]


# ---------------------------------------------------------------------------
# Last
# ---------------------------------------------------------------------------

def test_last_selects_most_recent_entity(run, make_context, document):
    first = _line(document, (0, 0, 0), (1, 0, 0))
    second = _line(document, (0, 1, 0), (1, 1, 0))
    third = _line(document, (0, 2, 0), (1, 2, 0))
    ctx = make_context()
    result = run(ctx, "ERASE", ["l"])
    assert result.status == "ok"
    assert result.removed == [third.id]
    assert sorted(e.id for e in document.entities()) == \
        sorted([first.id, second.id])


# ---------------------------------------------------------------------------
# Previous + doc.last_selection_ids (the session pool)
# ---------------------------------------------------------------------------

def test_previous_reuses_last_nonempty_resolution(run, make_context, document):
    picked = _line(document, (1, 1, 0), (2, 1, 0))
    far = _line(document, (20, 20, 0), (21, 20, 0))
    # first command resolves Window -> only `picked`
    ctx = make_context()
    result = run(ctx, "MOVE", ["w", "0,0", "10,10", "5,0", "6,0"])
    assert result.status == "ok"
    assert result.modified == [picked.id]
    assert document.last_selection_ids == [picked.id]
    # a second command reuses the same resolution via Previous
    ctx = make_context()
    result = run(ctx, "ERASE", ["p"])
    assert result.status == "ok"
    assert result.removed == [picked.id]
    assert [e.id for e in document.entities()] == [far.id]


def test_previous_without_prior_selection_feedback_reasks(
        run, make_context, document):
    line = _line(document, (0, 0, 0), (1, 0, 0))
    ctx = make_context()
    result = run(ctx, "ERASE", ["p", "a"])
    assert result.status == "ok"
    assert "ERASE: no previous selection" in ctx.feedback_messages
    assert result.removed == [line.id]


def test_empty_resolution_never_replaces_previous_pool(
        run, make_context, document):
    picked = _line(document, (1, 1, 0), (2, 1, 0))
    other = _line(document, (20, 20, 0), (21, 20, 0))
    ctx = make_context()
    assert run(ctx, "MOVE", ["w", "0,0", "10,10", "5,0", "6,0"]).status == "ok"
    assert document.last_selection_ids == [picked.id]
    # Enter ends an ERASE with NOTHING selected — the pool must survive
    ctx = make_context()
    result = run(ctx, "ERASE", [""])
    assert result.status == "ok"
    assert result.summary == "ERASE: no objects selected"
    assert document.last_selection_ids == [picked.id]
    ctx = make_context()
    result = run(ctx, "MOVE", ["p", "0,0", "1,0"])
    assert result.status == "ok"
    assert result.modified == [picked.id]            # Previous still resolves


def test_previous_drops_erased_ids(run, make_context, document):
    first = _line(document, (0, 0, 0), (1, 0, 0))
    second = _line(document, (0, 1, 0), (1, 1, 0))
    ctx = make_context()
    assert run(ctx, "ERASE", ["a"]).status == "ok"    # pool = [first, second]
    assert document.last_selection_ids == [first.id, second.id]
    ctx = make_context()
    result = run(ctx, "ERASE", ["p"])                 # every pooled id is stale
    assert result.status == "ok"
    assert result.summary == "ERASE: no objects selected"
    assert result.removed == []


def test_doc_last_selection_ids_tracks_command_resolutions(
        run, make_context, document):
    first = _line(document, (0, 0, 0), (1, 0, 0))
    second = _line(document, (0, 1, 0), (1, 1, 0))
    ctx = make_context()
    result = run(ctx, "MOVE", ["a", "0,0", "1,0"])
    assert result.status == "ok"
    assert document.last_selection_ids == [first.id, second.id]
    for entity in document.entities():
        assert tuple(entity.p1) == (1.0, entity.p1[1], 0.0)   # moved +1 X


# ---------------------------------------------------------------------------
# Enter ends selection empty + prompt surface
# ---------------------------------------------------------------------------

def test_enter_ends_selection_empty(run, make_context, document):
    line = _line(document, (0, 0, 0), (1, 0, 0))
    ctx = make_context()
    result = run(ctx, "ERASE", [""])
    assert result.status == "ok"
    assert result.summary == "ERASE: no objects selected"
    assert result.removed == []
    assert [e.id for e in document.entities()] == [line.id]


def test_selection_prompt_pins_the_mode_options(run, make_context, document):
    _line(document, (0, 0, 0), (1, 0, 0))
    ctx = make_context()
    provider = RecordingProvider(ctx, [""])
    result = run(ctx, "ERASE", [], provider=provider)
    assert result.status == "ok"
    request = provider.requests[0]
    assert request.kind == "selection"
    assert request.options == SELECTION_MODES
    assert "[All/Previous/Window/Crossing/Last]" in request.prompt


# ---------------------------------------------------------------------------
# locked layers: resolved by selection, skipped by modify
# ---------------------------------------------------------------------------

def test_locked_resolved_by_all_but_skipped_by_move_with_feedback(
        run, make_context, document):
    _layer(document, "LOCK", locked=True)
    free = _line(document, (0, 0, 0), (1, 0, 0))
    locked = _line(document, (0, 1, 0), (1, 1, 0), layer="LOCK")
    ctx = make_context()
    result = run(ctx, "MOVE", ["a", "0,0", "1,0"])
    assert result.status == "ok"
    # locked entity WAS resolved (it is in the pool) but not modified
    assert document.last_selection_ids == [free.id, locked.id]
    assert result.modified == [free.id]
    assert "MOVE: 1 entity(ies) on locked layer skipped" in ctx.feedback_messages
    assert tuple(document.get(free.id).p1) == (1.0, 0.0, 0.0)
    assert tuple(document.get(locked.id).p1) == (0.0, 1.0, 0.0)  # unmoved


def test_erase_all_locked_reports_no_objects_and_keeps_entities(
        run, make_context, document):
    _layer(document, "LOCK", locked=True)
    locked = _line(document, (0, 1, 0), (1, 1, 0), layer="LOCK")
    ctx = make_context()
    result = run(ctx, "ERASE", ["a"])
    assert result.status == "ok"
    assert result.summary == "ERASE: no objects selected"
    assert result.removed == []
    assert "ERASE: 1 entity(ies) on locked layer skipped" in ctx.feedback_messages
    assert [e.id for e in document.entities()] == [locked.id]


# ---------------------------------------------------------------------------
# SELECT command (bcdraft.selection) end-to-end
# ---------------------------------------------------------------------------

def _select_fixture_lines(document):
    """A(inside rect R), B(crossing R), C(far) — R = (0,0)-(1,1)."""
    inside = _line(document, (0.25, 0.5, 0), (0.75, 0.5, 0))
    crossing = _line(document, (0.5, 0.5, 0), (3.0, 0.5, 0))
    far = _line(document, (10.0, 10.0, 0), (11.0, 10.0, 0))
    return inside, crossing, far


def test_select_all_sets_document_selection_with_count_feedback(
        run, make_context, document):
    inside, crossing, far = _select_fixture_lines(document)
    ctx = make_context()
    result = run(ctx, "SELECT", ["a", ""])
    assert result.status == "ok"
    assert result.summary == "SELECT: 3 object(s) selected"
    assert sorted(document.selection.ids) == \
        sorted([inside.id, crossing.id, far.id])
    assert document.last_selection_ids == \
        [inside.id, crossing.id, far.id]


def test_select_all_skips_frozen_and_other_spaces(run, make_context, document):
    _layer(document, "FROZ", frozen=True)
    with document.transaction("layout"):
        document.add_layout("P1")
    live1 = _line(document, (0, 0, 0), (1, 0, 0))
    live2 = _line(document, (0, 1, 0), (1, 1, 0))
    _line(document, (0, 2, 0), (1, 2, 0), layer="FROZ")
    _line(document, (0, 3, 0), (1, 3, 0), space="P1")
    ctx = make_context()
    result = run(ctx, "SELECT", ["a", ""])
    assert result.status == "ok"
    assert result.summary == "SELECT: 2 object(s) selected"
    assert sorted(document.selection.ids) == sorted([live1.id, live2.id])


def test_select_window_crossing_last_previous_each_mode_e2e(
        run, make_context, document):
    inside, crossing, far = _select_fixture_lines(document)
    ctx = make_context()
    result = run(ctx, "SELECT", ["w", "0,0", "1,1", ""])
    assert result.summary == "SELECT: 1 object(s) selected"
    assert set(document.selection.ids) == {inside.id}
    ctx = make_context()
    result = run(ctx, "SELECT", ["c", "0,0", "1,1", ""])
    assert result.summary == "SELECT: 2 object(s) selected"
    assert set(document.selection.ids) == {inside.id, crossing.id}
    ctx = make_context()
    result = run(ctx, "SELECT", ["l", ""])
    assert result.summary == "SELECT: 1 object(s) selected"
    assert set(document.selection.ids) == {far.id}      # most recent entity
    ctx = make_context()
    result = run(ctx, "SELECT", ["p", ""])
    assert result.summary == "SELECT: 1 object(s) selected"
    # Previous resolves the LAST non-empty selection — the "l" run's {far}
    assert set(document.selection.ids) == {far.id}


def test_select_previous_with_empty_pool_selects_nothing(
        run, make_context, document):
    _line(document, (0, 0, 0), (1, 0, 0))
    ctx = make_context()
    result = run(ctx, "SELECT", ["p", ""])
    assert result.status == "ok"
    assert result.summary == "SELECT: 0 object(s) selected"
    assert document.selection.ids == frozenset()


def test_select_keyword_prefixes_resolve_modes(run, make_context, document):
    inside, crossing, far = _select_fixture_lines(document)
    ctx = make_context()
    assert run(ctx, "SELECT", ["a", ""]).summary == "SELECT: 3 object(s) selected"
    assert run(ctx, "SELECT", ["w", "0,0", "1,1", ""]).summary == \
        "SELECT: 1 object(s) selected"
    assert set(document.selection.ids) == {inside.id}
    assert run(ctx, "SELECT", ["c", "0,0", "1,1", ""]).summary == \
        "SELECT: 2 object(s) selected"
    assert run(ctx, "SELECT", ["l", ""]).summary == "SELECT: 1 object(s) selected"
    assert set(document.selection.ids) == {far.id}
    assert run(ctx, "SELECT", ["p", ""]).summary == "SELECT: 1 object(s) selected"
    assert set(document.selection.ids) == {far.id}      # pool == last SELECT


def test_select_raw_id_list_dedups_and_drops_stale(
        run, make_context, document):
    line = _line(document, (0, 0, 0), (1, 0, 0))
    ctx = make_context()
    result = run(ctx, "SELECT", [
        selection_input([line.id, line.id, "no-such-id"]), "",
    ])
    assert result.status == "ok"
    assert result.summary == "SELECT: 1 object(s) selected"
    assert document.selection.ids == frozenset({line.id})


def test_select_enter_empty_clears_selection_but_keeps_previous_pool(
        run, make_context, document):
    inside, crossing, far = _select_fixture_lines(document)
    ctx = make_context()
    assert run(ctx, "SELECT", ["w", "0,0", "1,1", ""]).status == "ok"
    assert document.last_selection_ids == [inside.id]
    ctx = make_context()
    result = run(ctx, "SELECT", [""])
    assert result.status == "ok"
    assert result.summary == "SELECT: 0 object(s) selected"
    assert document.selection.ids == frozenset()
    # the Previous pool holds the last NON-EMPTY selection (contract §4)
    assert document.last_selection_ids == [inside.id]
    ctx = make_context()
    result = run(ctx, "SELECT", ["p", ""])
    assert set(document.selection.ids) == {inside.id}


def test_select_corner_prompts_are_point_requests(run, make_context, document):
    _select_fixture_lines(document)
    ctx = make_context()
    provider = RecordingProvider(ctx, ["w", "0,0", "1,1", ""])
    result = run(ctx, "SELECT", [], provider=provider)
    assert result.status == "ok"
    kinds = [r.kind for r in provider.requests]
    assert kinds == ["selection", "point", "point", "selection"]
    assert provider.requests[1].prompt == "SELECT Specify first corner:"
    assert provider.requests[2].prompt == "SELECT Specify opposite corner:"
