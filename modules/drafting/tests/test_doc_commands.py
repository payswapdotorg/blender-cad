"""UNDO / REDO commands + registry reachability (TP-CAT-01).

UNDO/REDO are zero-prompt commands: they call ``document.undo()/redo()`` and
sink feedback, running to completion headless with NO provider. The
reachability section pins the contract-§5 requirement that every implemented
command is reachable through the same registry interface the UI uses — by
canonical name AND by alias.
"""

import pytest

from bccmd import Registry


# ---------------------------------------------------------------------------
# UNDO / REDO
# ---------------------------------------------------------------------------

def _seed_two_segments(run, ctx):
    assert run(ctx, "line", ["0,0", "1,0", "1,1", ""]).status == "ok"
    assert run(ctx, "circle", ["5,5", "2"]).status == "ok"


def test_undo_command_steps_back_one_committed_transaction(
    run, make_context, document
):
    ctx = make_context()
    _seed_two_segments(run, ctx)
    counts = document.count_by_kind()
    depth = document.undo_depth()

    result = run(ctx, "undo", [], provider=None)  # zero prompts, headless

    assert result.status == "ok"
    assert document.undo_depth() == depth - 1
    assert document.count_by_kind() == {"line": 2}  # CIRCLE undone
    assert "one step undone" in result.summary
    assert any("step(s) left" in m for m in ctx.feedback_messages)


def test_undo_when_stack_empty_is_polite(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "undo", [], provider=None)
    assert result.status == "ok"
    assert "everything has been undone" in result.summary


def test_redo_command_reapplies(run, make_context, document):
    ctx = make_context()
    _seed_two_segments(run, ctx)
    run(ctx, "undo", [], provider=None)
    assert document.count_by_kind() == {"line": 2}

    result = run(ctx, "redo", [], provider=None)

    assert result.status == "ok"
    assert document.count_by_kind() == {"line": 2, "circle": 1}
    assert "one step redone" in result.summary


def test_redo_when_stack_empty_is_polite(run, make_context, document):
    ctx = make_context()
    result = run(ctx, "redo", [], provider=None)
    assert result.status == "ok"
    assert "nothing to redo" in result.summary


def test_undo_redo_round_trip_preserves_geometry(run, make_context, document):
    ctx = make_context()
    _seed_two_segments(run, ctx)
    circle_id = [e.id for e in document.entities() if e.kind == "circle"][0]
    center_before = document.get(circle_id).center

    for _ in range(document.undo_depth()):
        run(ctx, "undo", [], provider=None)
    assert document.count_by_kind() == {}

    while document.redo_depth():
        run(ctx, "redo", [], provider=None)
    assert document.count_by_kind() == {"line": 2, "circle": 1}
    assert document.get(circle_id).center == center_before


def test_undo_bumps_doc_version_and_fires_change_events(
    run, make_context, document
):
    ctx = make_context()
    _seed_two_segments(run, ctx)
    events = []
    document.on_change.append(lambda event: events.append(event))
    run(ctx, "undo", [], provider=None)
    # undo is itself a committed transaction (contract §3.3)
    assert events and events[-1] == ("doc", document.doc_version)


# ---------------------------------------------------------------------------
# Registry reachability — every implemented command via the SAME interface
# (contract §5: "registered through bcdraft.register_all(registry)")
# ---------------------------------------------------------------------------

EXPECTED_COMMANDS = {
    "LINE": ["L"],
    "CIRCLE": ["C"],
    "ARC": ["A"],
    "ERASE": ["E"],
    "MOVE": ["M"],
    "COPY": ["CO"],
    "ROTATE": ["RO"],
    "SCALE": ["SC"],
    "UNDO": ["U"],
    "REDO": [],
}


def test_register_all_registers_every_m1_command(registry):
    # M2 (W-D note): bcdraft now registers the drafting-core additions
    # (SELECT, PLINE, RECTANG, ... LAYER, BLOCK, INSERT) and W-A appends the
    # precision commands in parallel — the M1 set stays registered, so the
    # exact-set assertion became a subset check (intent unchanged).
    names = set(registry.names())
    assert set(EXPECTED_COMMANDS) <= names


def test_every_command_and_alias_resolves(registry):
    for name, aliases in EXPECTED_COMMANDS.items():
        assert registry.lookup(name) is not None
        assert registry.lookup(name.lower()) is not None
        for alias in aliases:
            spec = registry.lookup(alias)
            assert spec is not None and spec.name == name


@pytest.mark.parametrize("name", sorted(EXPECTED_COMMANDS))
def test_every_command_runs_through_run_command(name, registry, make_context):
    """Scripted end-to-end: each command produces an ok result through
    Registry.run_command — the exact path the modal operator drives."""
    from bccmd import ScriptedProvider

    ctx = make_context()
    minimal_inputs = {
        "LINE": ["0,0", "1,0", ""],
        "CIRCLE": ["0,0", "1"],
        "ARC": ["20,10", "10,20", "0,10"],
        "ERASE": [""],           # empty selection → polite no-op
        "MOVE": [""],            # empty selection → polite no-op
        "COPY": [""],
        "ROTATE": [""],
        "SCALE": [""],
        "UNDO": [],              # zero prompts
        "REDO": [],
    }
    result = registry.run_command(
        ctx, name, provider=ScriptedProvider(ctx, minimal_inputs[name])
    )
    assert result.status == "ok", f"{name}: {result.summary}"
