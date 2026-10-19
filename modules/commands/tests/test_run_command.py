"""Prompt-loop tests — Registry.run_command with a scripted provider (TP-CAT-01).

These exercise the exact interface the UI and agents use: run_command(ctx,
name, provider) → CommandResult, with multi-point flows, mid-command
cancel, invalid-then-valid input re-asking, and history recording.
"""

import pytest

from bccmd import (
    Cancelled,
    CommandResult,
    CommandSpec,
    Point,
    Registry,
    Request,
    Runner,
    ScriptedProvider,
    StepDriver,
    UnknownCommand,
    angle_input,
    keyword_input,
    point_input,
)

from bcdoc.entities import Line


# ---------------------------------------------------------------------------
# local test commands (bccmd-only; bcdraft is tested in modules/drafting)
# ---------------------------------------------------------------------------

def two_point_steps(ctx):
    p1 = yield Request("point", "TWO first point:")
    ctx.set_last_point(p1.value)
    p2 = yield Request("point", "TWO second point or [Done]:", options=["Done"])
    if p2.kind == "keyword" and p2.value == "Done":
        return CommandResult(status="ok", summary="TWO: skipped second")
    ctx.set_last_point(p2.value)
    return CommandResult(
        status="ok",
        summary=f"TWO: {p1.value.x:g},{p1.value.y:g} -> {p2.value.x:g},{p2.value.y:g}",
    )


TWO_POINT = CommandSpec(name="TWOPT", aliases=["2P"], steps=two_point_steps)


def make_line_steps(ctx):
    doc = ctx.document
    p1 = yield Request("point", "MLINE first point:")
    p2 = yield Request("point", "MLINE second point:")
    with doc.transaction("MLINE"):
        entity = doc.add_entity(Line(p1.value.to_tuple(), p2.value.to_tuple()))
    ctx.set_last_point(p2.value)
    return CommandResult(status="ok", summary="MLINE: 1", created=[entity.id])


MAKE_LINE = CommandSpec(name="MLINE", steps=make_line_steps)


def register_test_commands(registry):
    registry.register(TWO_POINT)
    registry.register(MAKE_LINE)


@pytest.fixture()
def registry():
    reg = Registry()
    register_test_commands(reg)
    return reg


@pytest.fixture()
def ctx(make_context):
    return make_context()


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------

def test_run_command_happy_path(registry, ctx):
    result = registry.run_command(
        ctx, "twopt", provider=ScriptedProvider(ctx, ["0,0", "10,10"])
    )
    assert result.status == "ok"
    assert result.summary == "TWO: 0,0 -> 10,10"
    assert ctx.machine.state == "idle"
    assert ctx.last_point == Point(10.0, 10.0)


def test_run_command_records_history_with_raw_inputs(registry, ctx):
    registry.run_command(ctx, "TWOPT", provider=ScriptedProvider(ctx, ["0,0", "10,10"]))
    entry = ctx.history.entries()[-1]
    assert entry.command == "TWOPT"
    assert entry.inputs == ["0,0", "10,10"]
    assert entry.status == "ok"


def test_run_command_machine_trace(registry, ctx):
    registry.run_command(ctx, "TWOPT", provider=ScriptedProvider(ctx, ["0,0", "1,1"]))
    states = [new for (_old, new) in ctx.machine.transitions]
    assert states == ["command_active", "collecting", "collecting", "commit", "idle"]


def test_run_steps_equals_manual_driving(registry, make_context):
    # run_steps (blocking Runner inside run_command) and manual StepDriver
    # driving execute the SAME generator — identical document outcomes.
    ctx1 = make_context()
    result = registry.run_command(
        ctx1, "MLINE", provider=ScriptedProvider(ctx1, ["1,1", "2,2"])
    )
    assert result.created and result.status == "ok"
    line1 = ctx1.document.get(result.created[0])
    assert line1.p1 == (1.0, 1.0, 0.0)
    assert line1.p2 == (2.0, 2.0, 0.0)

    ctx2 = make_context()
    driver = StepDriver(make_line_steps(ctx2))
    req = driver.start()
    assert req is not None
    assert driver.push(point_input(1, 1)) is not None
    assert driver.push(point_input(2, 2)) is None
    line2 = ctx2.document.get(driver.result.created[0])
    assert (line2.p1, line2.p2) == (line1.p1, line1.p2)
    assert ctx2.document.doc_version == ctx1.document.doc_version


def test_run_command_via_alias(registry, ctx):
    result = registry.run_command(ctx, "2p", provider=ScriptedProvider(ctx, ["0,0", "5,5"]))
    assert result.status == "ok"


def test_run_command_unknown(registry, ctx):
    with pytest.raises(UnknownCommand):
        registry.run_command(ctx, "NOSUCH", provider=None)


# ---------------------------------------------------------------------------
# cancel paths
# ---------------------------------------------------------------------------

def test_run_command_cancel_mid_command(registry, ctx):
    result = registry.run_command(
        ctx, "TWOPT", provider=ScriptedProvider(ctx, ["0,0", Cancelled()])
    )
    assert result.status == "cancelled"
    assert result.summary == "TWOPT cancelled"
    assert ctx.machine.state == "idle"
    assert ctx.machine.command is None
    entry = ctx.history.entries()[-1]
    assert entry.status == "cancelled"


def test_run_command_cancel_immediately(registry, ctx):
    result = registry.run_command(ctx, "TWOPT", provider=ScriptedProvider(ctx, [Cancelled()]))
    assert result.status == "cancelled"


def test_run_command_without_provider_cancels_at_first_prompt(registry, ctx):
    # No provider (headless no-input): the default provider raises Cancelled
    # at the first prompt — the command ends cleanly without feedback noise.
    result = registry.run_command(ctx, "TWOPT", provider=None)
    assert result.status == "cancelled"
    assert ctx.machine.state == "idle"
    assert ctx.feedback_messages == []


# ---------------------------------------------------------------------------
# invalid input handling (parse + semantic re-ask)
# ---------------------------------------------------------------------------

def test_invalid_input_then_valid_reasks(registry, ctx):
    provider = ScriptedProvider(ctx, ["garbage", "5,5", "nonsense!", "6,6"])
    result = registry.run_command(ctx, "TWOPT", provider=provider)
    assert result.status == "ok"
    assert result.summary == "TWO: 5,5 -> 6,6"
    # diagnostics were sunk for the two bad inputs
    assert len(ctx.feedback_messages) >= 2


def test_wrong_kind_then_valid_reasks(registry, ctx):
    provider = ScriptedProvider(ctx, [angle_input(30.0), point_input(5, 5), point_input(6, 6)])
    result = registry.run_command(ctx, "TWOPT", provider=provider)
    # angle at a point prompt → Runner rejects the kind, sinks a diagnostic
    # and re-asks the SAME prompt until a point arrives (semantic re-ask).
    assert result.status == "ok"
    assert result.summary == "TWO: 5,5 -> 6,6"
    assert any("Point input required" in m for m in ctx.feedback_messages)


def test_scripted_provider_exhaustion_cancels(registry, ctx):
    result = registry.run_command(ctx, "TWOPT", provider=ScriptedProvider(ctx, ["0,0"]))
    assert result.status == "cancelled"


# ---------------------------------------------------------------------------
# Runner.ask_until — the contract helper
# ---------------------------------------------------------------------------

def test_ask_until_rejects_then_accepts(ctx):
    provider = ScriptedProvider(ctx, ["nonsense", "1,2"])
    runner = Runner(ctx, provider)
    req = Request("point", "pt:")
    value = runner.ask_until(req, lambda v: v.kind == "point")
    assert value.value == Point(1.0, 2.0, 0.0)
    assert len(ctx.feedback_messages) >= 1


def test_ask_until_validator_valueerror_message(ctx):
    # a keyword passes the Runner kind rule and reaches the validator, whose
    # ValueError message is sunk as feedback; then semantic re-asks continue
    # until a valid value arrives ("-1" rejected, "5" accepted).
    provider = ScriptedProvider(ctx, [keyword_input("Bogus"), "-1", "5"])
    runner = Runner(ctx, provider)

    def positive_distance(v):
        if v.kind != "distance":
            raise ValueError("Distance required")
        if v.value <= 0:
            raise ValueError("Distance must be positive")
        return True

    value = runner.ask_until(Request("distance", "d:"), positive_distance)
    assert value.value == 5.0
    assert any("Distance required" in m for m in ctx.feedback_messages)
    assert any("positive" in m for m in ctx.feedback_messages)


def test_ask_records_raw_inputs(ctx):
    provider = ScriptedProvider(ctx, ["1,2", "@1,1"])
    runner = Runner(ctx, provider)
    ctx.set_last_point(Point(0, 0, 0))
    req = Request("point", "pt:")
    runner.ask(req)
    runner.ask(req)
    assert runner.raw_inputs == ["1,2", "@1,1"]


# ---------------------------------------------------------------------------
# command-side document rules
# ---------------------------------------------------------------------------

def test_transaction_per_command_mutation(registry, ctx):
    doc = ctx.document
    result = registry.run_command(ctx, "MLINE", provider=ScriptedProvider(ctx, ["0,0", "1,1"]))
    assert doc.doc_version == 1
    assert doc.undo_depth() == 1
    doc.undo()
    assert doc.entities() == []
    assert result.created[0] not in [e.id for e in doc.entities()]


def test_command_exception_leaves_machine_idle_and_reraises(make_context, registry):
    def broken_steps(ctx):
        yield Request("point", "pt:")
        raise RuntimeError("boom")

    registry.register(CommandSpec(name="BOOM", steps=broken_steps))
    ctx = make_context()
    with pytest.raises(RuntimeError):
        registry.run_command(ctx, "BOOM", provider=ScriptedProvider(ctx, ["0,0"]))
    assert ctx.machine.state == "idle"
