"""Prompt state machine + step-by-step command driver.

States follow ux-specification §3.2 (Idle → CommandActive → Collecting →
Preview → Commit → Idle, Esc → Idle). ``PromptMachine`` validates every
transition; illegal jumps raise :class:`StateError` so sequencing bugs are
caught by tests instead of surfacing as broken prompts.

``StepDriver`` executes a steps-generator (see spec.run_steps) one Request
at a time. This is the deterministic, thread-free mechanism the modal
viewport operator uses: it holds the current Request, the operator collects
one InputValue per event, and the command resumes exactly where it paused.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .spec import Cancelled, CommandResult, InputValue, Request

# State names (ux-spec §3.2)
IDLE = "idle"
ACTIVE = "command_active"
COLLECTING = "collecting"
PREVIEW = "preview"
COMMIT = "commit"

# Legal transitions. IDLE is reachable from every non-idle state (Esc cancel);
# ACTIVE → COMMIT covers zero-prompt commands (UNDO/REDO).
_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    IDLE: (ACTIVE,),
    ACTIVE: (COLLECTING, COMMIT, IDLE),
    COLLECTING: (COLLECTING, PREVIEW, COMMIT, IDLE),
    PREVIEW: (COLLECTING, PREVIEW, COMMIT, IDLE),
    COMMIT: (IDLE,),
}


class StateError(Exception):
    """Illegal prompt-state transition attempted."""


class PromptMachine:
    """Tracks the prompt state for one command session.

    The blocking prompt loop uses Collecting → Commit → Idle; the modal
    operator additionally enters Preview on drag feedback (rubberband).
    ``transitions`` keeps an append-only trace for tests and diagnostics.
    """

    def __init__(self) -> None:
        self.state: str = IDLE
        self.command: Optional[str] = None
        self.request: Optional[Request] = None
        self.transitions: List[Tuple[str, str]] = []

    # -- internals ---------------------------------------------------------
    def _to(self, new_state: str) -> None:
        if new_state not in _TRANSITIONS[self.state]:
            raise StateError(
                f"illegal prompt transition {self.state!r} -> {new_state!r} "
                f"(command={self.command!r})"
            )
        self.transitions.append((self.state, new_state))
        self.state = new_state

    # -- transitions -------------------------------------------------------
    def begin(self, command_name: str) -> None:
        """Idle → CommandActive: a command was resolved and started."""
        if self.state != IDLE:
            raise StateError(
                f"cannot begin {command_name!r}: session not idle ({self.state})"
            )
        self._to(ACTIVE)
        self.command = command_name
        self.request = None

    def collecting(self) -> None:
        """First prompt issued; further asks stay in Collecting."""
        if self.state in (ACTIVE, COLLECTING, PREVIEW):
            # PREVIEW → Collecting covers "drag abandoned / option revised"
            # (ux-spec §3.2); Collecting → Collecting is the re-ask loop.
            self._to(COLLECTING)
        else:
            raise StateError(
                f"collecting requires CommandActive/Collecting/Preview "
                f"state, got {self.state!r}"
            )

    def preview(self) -> None:
        """Drag-based live feedback begins (modal operator only)."""
        if self.state in (COLLECTING, PREVIEW):
            self._to(PREVIEW)
        else:
            raise StateError(
                f"preview requires Collecting/Preview state, got {self.state!r}"
            )

    def track_request(self, request: Request) -> None:
        """Record the prompt currently being asked (drives the status line)."""
        self.request = request

    def commit(self) -> None:
        """Final input accepted — document transaction(s) committed.

        Legal from ACTIVE (zero-prompt commands like UNDO skip Collecting),
        COLLECTING and PREVIEW; illegal from IDLE/COMMIT (StateError)."""
        if self.state in (ACTIVE, COLLECTING, PREVIEW):
            self._to(COMMIT)
        else:
            raise StateError(f"illegal commit from {self.state!r}")

    def finish(self) -> None:
        """Commit → Idle."""
        self._to(IDLE)
        self.command = None
        self.request = None

    def cancel(self) -> None:
        """Esc: any non-idle state → Idle, no document change."""
        if self.state != IDLE:
            self._to(IDLE)
        self.command = None
        self.request = None


class StepDriver:
    """Drives a steps-generator one InputValue at a time.

    Usage::

        driver = StepDriver(line_steps(ctx))
        req = driver.start()          # first Request (or None → done)
        while req is not None:
            value = ...              # collect ONE InputValue (blocking call,
                                    # modal event, agent reply, ...)
            req = driver.push(value) # next Request (or None → done)
        result = driver.result       # CommandResult
    """

    def __init__(self, generator: Any):
        # Accept both a steps-generator and a zero-prompt factory product:
        # a steps-factory that returns a CommandResult directly (UNDO/REDO
        # style commands) finishes the driver immediately.
        if isinstance(generator, CommandResult):
            self._gen = None
            self._done = True
            self._result = generator
        else:
            self._gen = generator
            self._done = False
            self._result = None
        self._pending: Optional[Request] = None

    @classmethod
    def from_factory(cls, factory, ctx: Any) -> "StepDriver":
        """Build from a steps-factory (``factory(ctx)``).

        Accepts both generator-factories (yield Requests) and plain
        factories that return a :class:`CommandResult` directly (zero-prompt
        commands) — the latter finish immediately.
        """
        return cls(factory(ctx))

    # -- introspection -----------------------------------------------------
    @property
    def current_request(self) -> Optional[Request]:
        return self._pending

    @property
    def done(self) -> bool:
        return self._done

    @property
    def result(self) -> Optional[CommandResult]:
        return self._result

    # -- driving -----------------------------------------------------------
    def start(self) -> Optional[Request]:
        """Advance to the first prompt. Returns None if the command is done."""
        if self._done:
            return None
        try:
            request = next(self._gen)
        except StopIteration as stop:
            self._finish(stop)
            return None
        self._pending = request
        return request

    def push(self, value: InputValue) -> Optional[Request]:
        """Feed one accepted input; returns the next Request or None."""
        if self._done:
            raise RuntimeError("command already finished")
        try:
            request = self._gen.send(value)
        except StopIteration as stop:
            self._finish(stop)
            return None
        self._pending = request
        return request

    def throw(self, exc: BaseException) -> Optional[Request]:
        """Inject an exception (e.g. Cancelled) at the paused ask-point.

        If the generator swallows it and yields a new Request, driving
        continues; StopIteration finishes the command as usual. A
        :class:`Cancelled` the command does NOT absorb finishes the driver
        cleanly with ``result is None`` — the driving host (modal operator,
        ``Registry.run_command``) turns that into ``status="cancelled"``;
        ``driver.done`` distinguishes it from a never-started driver. Any
        other exception propagates to the caller.
        """
        if self._done:
            raise exc
        try:
            request = self._gen.throw(exc)
        except StopIteration as stop:
            self._finish(stop)
            return None
        except Cancelled:
            self._done = True
            self._pending = None
            self._result = None
            return None
        self._pending = request
        return request

    def _finish(self, stop: StopIteration) -> None:
        self._done = True
        self._pending = None
        self._result = stop.value
