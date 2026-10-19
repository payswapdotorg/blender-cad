"""bccmd — command registry + prompt state machine (Blender CAD, M1).

Pure Python. No Blender dependency of any kind: this package is importable
under plain pytest and inside Blender alike (m1-module-contracts §2).

Implements contract §4 (m1-module-contracts.md):
  * input model  — Point / InputValue / Request / Cancelled      (spec.py)
  * command spec — CommandSpec / CommandContext / Runner / CommandResult
  * registry     — Registry with name-or-alias resolution, duplicate detection
  * prompt loop  — Registry.run_command(ctx, name, provider) drives any
                   CommandSpec through a blocking input provider; the same
                   spec can alternatively be driven step-by-step (StepDriver)
                   which is what the modal viewport operator uses.
  * input parse  — AutoCAD-familiar text forms ("12,34", "@3,4", "@5<30",
                   plain numbers, prefix keyword matching)
  * history      — command history with raw inputs, summary, timestamp

Commands mutate the host document ONLY through ``ctx.document``
transactions (contract §4.2 binding rule); bccmd itself never touches a
document directly.
"""

from .spec import (
    Cancelled,
    CommandContext,
    CommandResult,
    CommandSpec,
    DuplicateCommand,
    InputValue,
    Point,
    Request,
    Runner,
    UnknownCommand,
    run_steps,
)
from .state import (
    ACTIVE,
    COLLECTING,
    COMMIT,
    IDLE,
    PREVIEW,
    PromptMachine,
    StateError,
    StepDriver,
)
from .registry import Registry
from .history import History, HistoryEntry
from .input import (
    InputParseError,
    OSNAP_TOKEN_ALIASES,
    ScriptedProvider,
    angle_input,
    distance_input,
    keyword_input,
    osnap_tokens,
    parse,
    point_input,
    selection_input,
)

__all__ = [
    # input model
    "Point",
    "InputValue",
    "Request",
    "Cancelled",
    # command model
    "CommandSpec",
    "CommandContext",
    "CommandResult",
    "Runner",
    "run_steps",
    "UnknownCommand",
    "DuplicateCommand",
    # state machine
    "PromptMachine",
    "StepDriver",
    "StateError",
    "IDLE",
    "ACTIVE",
    "COLLECTING",
    "PREVIEW",
    "COMMIT",
    # registry + history
    "Registry",
    "History",
    "HistoryEntry",
    # input parsing
    "parse",
    "InputParseError",
    "ScriptedProvider",
    "point_input",
    "keyword_input",
    "selection_input",
    "distance_input",
    "angle_input",
    "osnap_tokens",
    "OSNAP_TOKEN_ALIASES",
]

__version__ = "0.1.0"
