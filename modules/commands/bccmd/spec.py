"""Command spec + input model — contract §4.1/§4.2 (m1-module-contracts.md).

One input model, three input sources (interactive shell operator, scripted
tests, agent adapter later) — every source produces :class:`InputValue`
objects consumed by the same prompt state machine.

The module is deliberately dependency-free (stdlib only) so it can be
imported both under pytest and inside the host application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class Cancelled(Exception):
    """User aborted the command (Esc). The state machine returns cleanly."""


class UnknownCommand(Exception):
    """Raised by Registry.run_command when a token resolves to no command."""

    def __init__(self, token: str):
        super().__init__(f"Unknown command: {token!r}")
        self.token = token


class DuplicateCommand(Exception):
    """Raised by Registry.register on a name/alias collision."""


# ---------------------------------------------------------------------------
# Input model (contract §4.1)
# ---------------------------------------------------------------------------

@dataclass
class Point:
    """A 3D point in document/world coordinates (drawing units)."""

    x: float
    y: float
    z: float = 0.0

    def to_tuple(self) -> tuple:
        return (float(self.x), float(self.y), float(self.z))

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y, self.z - other.z)

    def __eq__(self, other) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return (self.x, self.y, self.z) == (other.x, other.y, other.z)


@dataclass
class InputValue:
    """One resolved user input.

    ``kind`` is one of ``"point" | "distance" | "angle" | "keyword" |
    "string" | "selection"``; ``value`` is a :class:`Point`, ``float`` or
    ``str`` (selection: ``list[str]`` entity ids). ``raw`` keeps the
    original text for the history.
    """

    kind: str
    value: Any
    raw: str = ""


@dataclass
class Request:
    """What the state machine asks the input provider for next."""

    kind: str                 # same kinds as InputValue
    prompt: str              # display text, e.g. "LINE Specify first point:"
    options: List[str] = field(default_factory=list)   # accepted keywords
    default: Any = None      # value accepted on empty input (Enter)


# ---------------------------------------------------------------------------
# Command result (contract §4.2)
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    """Outcome of one command invocation."""

    status: str                      # "ok" | "cancelled"
    summary: str = ""
    created: List[str] = field(default_factory=list)    # entity ids
    modified: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# ---------------------------------------------------------------------------
# Command context (contract §4.2) — provided by the host
# ---------------------------------------------------------------------------

def _noop_feedback(message: str) -> None:  # pragma: no cover - trivial
    pass


@dataclass
class CommandContext:
    """Host-provided context for one command run.

    ``document``  — the authoritative CAD document (transactions only).
    ``view``      — optional view bridge; ``None`` in headless tests.
    ``history``   — command history (auto-created when omitted).
    ``feedback``  — host message sink (command line / status bar).
    ``last_point``— tracked anchor for relative/polar input; commands
                    update it after each accepted point.
    ``machine``   — the prompt state machine (auto-created; shared with the
                    modal operator which drives PREVIEW transitions).
    """

    document: Any = None
    view: Optional[Any] = None
    history: Optional["History"] = None
    feedback: Callable[[str], None] = _noop_feedback
    last_point: Optional[Point] = None
    machine: Optional["PromptMachine"] = None
    default_provider: Optional[Callable[[Request], InputValue]] = None

    def __post_init__(self):
        if self.history is None:
            from .history import History
            self.history = History()
        if self.machine is None:
            from .state import PromptMachine
            self.machine = PromptMachine()

    def set_last_point(self, point: Point) -> Point:
        """Record the anchor used by relative (@dx,dy) and polar (@d<ang) input."""
        if point is None:
            return None
        self.last_point = Point(point.x, point.y, point.z)
        return self.last_point


# ---------------------------------------------------------------------------
# Runner — the prompt-loop driver passed INTO CommandSpec.run()
# ---------------------------------------------------------------------------

class Runner:
    """Blocking prompt-loop driver.

    ``ask(req)`` pulls the next input from the provider. Providers may raise
    :class:`InputParseError` (bad text) — the runner then re-asks with the
    SAME Request after sinking a diagnostic, which is the AutoCAD-familiar
    "invalid input → diagnostic → re-prompt" behavior (ux-spec §3.2).
    An :class:`InputValue` of the WRONG kind for the Request is treated the
    same way (diagnostic + re-ask); keywords are always passed through so
    commands can branch on options. :class:`Cancelled` propagates and
    aborts the command.
    """

    def __init__(self, ctx: CommandContext, provider: Callable[[Request], InputValue]):
        self._ctx = ctx
        self._provider = provider
        self.raw_inputs: List[str] = []

    @property
    def ctx(self) -> CommandContext:
        return self._ctx

    def ask(self, req: Request) -> InputValue:
        from .input import InputParseError
        while True:
            # The Request is pending the moment we ask for it: track it and
            # enter Collecting (ux-spec §3.2) before the provider blocks.
            self._track(req)
            try:
                value = self._provider(req)
            except InputParseError as exc:
                # Parse errors never abort: diagnostic + re-ask (same Request).
                self._ctx.feedback(str(exc))
                continue
            if not isinstance(value, InputValue):
                self._ctx.feedback(
                    f"Invalid input {value!r}: expected an InputValue"
                )
                continue
            if not _kind_accepted(req, value):
                self._ctx.feedback(
                    f"{req.kind.capitalize()} input required for: {req.prompt}"
                )
                continue
            if value.raw:
                self.raw_inputs.append(value.raw)
            return value

    def ask_until(self, req: Request, validate: Callable[[InputValue], bool]) -> InputValue:
        """Ask until ``validate`` accepts the value (semantic re-ask loop)."""
        while True:
            value = self.ask(req)
            try:
                accepted = bool(validate(value))
                message = ""
            except ValueError as exc:
                accepted = False
                message = str(exc)
            if accepted:
                return value
            self._ctx.feedback(message or f"Invalid input for: {req.prompt}")

    def _track(self, req: Request) -> None:
        machine = self._ctx.machine
        if machine is not None:
            machine.track_request(req)
            from .state import ACTIVE, COLLECTING, PREVIEW  # lazy: avoid cycle

            if machine.state in (ACTIVE, COLLECTING, PREVIEW):
                machine.collecting()


def _kind_accepted(req: Request, value: InputValue) -> bool:
    """Kind rule for one Request → InputValue pair.

    Accepted: same kind; any keyword (option branch — the command decides
    whether it is one of ITS options); anything at a string prompt; a POINT
    at distance/angle prompts (the AutoCAD mouse convention: a click at
    "Specify radius" means the distance from the reference point — the
    command computes the implied value; typed coordinates at those prompts
    are converted by ``bccmd.input._as_kind`` before ever reaching here).
    Rejected: a genuinely wrong kind (e.g. an angle at a point prompt) — the
    Runner sinks a diagnostic and re-asks (test_wrong_kind_then_valid_reasks).
    """
    if req.kind == "string":
        return True
    if value.kind == req.kind or value.kind == "keyword":
        return True
    return value.kind == "point" and req.kind in ("distance", "angle")


def run_steps(steps_factory: Callable[[CommandContext], Any]):
    """Build a contract-§4.2 ``run(ctx, runner)`` callable from a steps-generator.

    A *steps-generator* yields :class:`Request` objects and receives the
    corresponding :class:`InputValue` via ``send()``; its return value is the
    :class:`CommandResult`. Both drivers (blocking Runner here, step-by-step
    StepDriver in the modal operator) execute the exact same generator, so
    the command logic exists exactly once.
    """

    def run(ctx: CommandContext, runner: Runner) -> CommandResult:
        from .state import StepDriver
        driver = StepDriver.from_factory(steps_factory, ctx)
        request = driver.start()
        while request is not None:
            value = runner.ask(request)
            request = driver.push(value)
        result = driver.result
        if result is None:
            # A Cancelled the steps-generator did not absorb ends the run
            # here only when the host pushed it via the provider (which
            # raises before this line) — result None at this point means
            # the generator ended without returning a CommandResult.
            result = CommandResult(status="ok", summary="done")
        return result

    return run


# ---------------------------------------------------------------------------
# CommandSpec (contract §4.2)
# ---------------------------------------------------------------------------

class CommandSpec:
    """A registered command.

    ``name``     — canonical, upper-case ("LINE").
    ``aliases``  — short tokens ("L"); the global alias map stays
                   collision-free (Registry enforces it).
    ``run``      — contract entry: ``run(ctx, runner) -> CommandResult``.
    ``steps``    — optional steps-generator factory; when present the modal
                   viewport operator drives it step-by-step (no threads, no
                   replay). ``run`` (built with :func:`run_steps`) drives the
                   same generator through the blocking Runner.
    ``help``     — one-line description for UI/autocomplete.
    """

    def __init__(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        run: Optional[Callable[[CommandContext, Runner], CommandResult]] = None,
        steps: Optional[Callable[[CommandContext], Any]] = None,
        help: str = "",
    ):
        if not name:
            raise ValueError("CommandSpec.name must be non-empty")
        self.name = name.upper()
        self.aliases = [a.upper() for a in (aliases or [])]
        if run is None:
            if steps is None:
                raise ValueError(f"CommandSpec {self.name}: run or steps required")
            run = run_steps(steps)
        self.run = run
        self.steps = steps
        self.help = help or self.name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CommandSpec({self.name}, aliases={self.aliases})"


def _no_input_provider(request: Request) -> InputValue:
    raise Cancelled()
