"""State-machine sequencing tests — PromptMachine + StepDriver (TP-CAT-01)."""

import pytest

from bccmd import (
    ACTIVE,
    COLLECTING,
    COMMIT,
    IDLE,
    PREVIEW,
    Cancelled,
    CommandResult,
    InputValue,
    Point,
    Request,
    StateError,
    StepDriver,
    PromptMachine,
    point_input,
)

# ---------------------------------------------------------------------------
# PromptMachine transitions
# ---------------------------------------------------------------------------

def test_machine_full_flow_transitions():
    machine = PromptMachine()
    assert machine.state == IDLE
    machine.begin("LINE")
    assert machine.state == ACTIVE
    machine.collecting()
    assert machine.state == COLLECTING
    machine.preview()          # drag feedback (modal operator)
    assert machine.state == PREVIEW
    machine.collecting()       # drag abandoned
    assert machine.state == COLLECTING
    machine.preview()
    machine.commit()
    assert machine.state == COMMIT
    machine.finish()
    assert machine.state == IDLE
    assert machine.command is None
    assert (
        machine.transitions
        == [
            (IDLE, ACTIVE),
            (ACTIVE, COLLECTING),
            (COLLECTING, PREVIEW),
            (PREVIEW, COLLECTING),
            (COLLECTING, PREVIEW),
            (PREVIEW, COMMIT),
            (COMMIT, IDLE),
        ]
    )


def test_machine_cancel_from_any_state():
    for enter in ("collecting", "preview"):
        machine = PromptMachine()
        machine.begin("X")
        machine.collecting()
        if enter == "preview":
            machine.preview()
        machine.cancel()
        assert machine.state == IDLE


def test_machine_begin_requires_idle():
    machine = PromptMachine()
    machine.begin("X")
    with pytest.raises(StateError):
        machine.begin("Y")
    machine.cancel()


def test_machine_illegal_commit_from_idle():
    with pytest.raises(StateError):
        PromptMachine().commit()


def test_machine_cancel_from_idle_is_noop():
    machine = PromptMachine()
    machine.cancel()
    assert machine.state == IDLE


def test_machine_tracks_current_request():
    machine = PromptMachine()
    req = Request("point", "prompt:")
    machine.begin("X")
    machine.track_request(req)
    assert machine.request is req


# ---------------------------------------------------------------------------
# StepDriver — step-by-step driving of a steps-generator
# ---------------------------------------------------------------------------

def echo_steps(ctx):
    """Two-point echo command for driving tests."""
    p1 = yield Request("point", "first:")
    p2 = yield Request("point", "second:")
    return CommandResult(status="ok", summary=f"{p1.value.x:g},{p2.value.x:g}")


def test_stepdriver_start_push_result():
    driver = StepDriver(echo_steps(None))
    req = driver.start()
    assert req is not None and req.prompt == "first:"
    assert driver.current_request is req
    req2 = driver.push(point_input(1, 2))
    assert req2.prompt == "second:"
    req3 = driver.push(point_input(3, 4))
    assert req3 is None
    assert driver.done
    assert driver.result.summary == "1,3"


def test_stepdriver_throw_cancelled():
    driver = StepDriver(echo_steps(None))
    driver.start()
    req = driver.throw(Cancelled())
    assert req is None
    assert driver.result is None  # Cancelled propagates (caller catches)


def test_stepdriver_push_after_done_raises():
    driver = StepDriver(echo_steps(None))
    driver.start()
    driver.push(point_input(0, 0))
    driver.push(point_input(1, 1))
    with pytest.raises(RuntimeError):
        driver.push(point_input(2, 2))


def test_stepdriver_start_when_generator_returns_immediately():
    def no_prompt(ctx):
        return CommandResult(status="ok", summary="instant")

    driver = StepDriver(no_prompt(None))
    assert driver.start() is None
    assert driver.done
    assert driver.result.summary == "instant"


def test_stepdriver_generators_can_absorb_exceptions():
    def swallowing(ctx):
        try:
            value = yield Request("point", "pt:")
        except Cancelled:
            return CommandResult(status="cancelled", summary="caught")
        return CommandResult(status="ok", summary=str(value.kind))

    driver = StepDriver(swallowing(None))
    driver.start()
    assert driver.throw(Cancelled()) is None
    assert driver.result.status == "cancelled"
    assert driver.result.summary == "caught"
