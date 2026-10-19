"""Settings / system-variable commands (M2 contract §4: commands_precision).

Registered commands (aliases in brackets; every invalid input re-prompts
with a diagnostic — commands never crash; :class:`bccmd.Cancelled` always
propagates, leaving settings unchanged — sysvars are persisted but NOT
journaled, so a cancelled command must not have side effects):

=============  ==============================================================
SETVAR         ``?`` (or bare Enter) lists every SETTING_DEFS entry as
               ``NAME (type) = value`` feedback lines, then re-prompts;
               otherwise a NAME prompt (validated — UnknownSetting feedback
               + re-ask), then a value prompt parsed per type with choices
               validation (CLAYER/TEXTSTYLE/DIMSTYLE must name an existing
               record); Enter keeps the current value.
GETVAR         NAME prompt -> feedback ``NAME = value``.
OSNAP [OS]     ``none``/``non``/``off`` clears OSMODE; a comma mode list
               (``END,MID,CEN,QUA,INT,INS,PER,TAN`` — short or full names)
               SETS the running bits; bare Enter (or ``?``) shows the
               current running modes.
ORTHO          toggles ORTHOMODE.
SNAP           toggles SNAPMODE.
GRID           toggles GRIDMODE.
UNITS          walks LUNITS / LUPREC / AUNITS / AUPREC / INSUNITS with value
               prompts + defaults shown; every entered value is validated
               on a scratch copy and ALL writes happen at the END (Esc
               mid-walk leaves the settings untouched); feedback summary.
DYNAMICINPUT   [DYN] toggles DYNMODE 3 <-> 0.
=============  ==============================================================

Zero-prompt toggles follow the commands_doc.py pattern (plain ``run``
callables — no prompts, they complete headless without a provider).
"""

from __future__ import annotations

from typing import List

from bccmd import CommandContext, CommandResult, CommandSpec, Request, Runner
from bcdoc import errors
from bcdoc.settings import SETTING_DEFS

from . import precision


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _setting_names() -> List[str]:
    """Registered sysvar names in registry order (bcdoc §2.5)."""
    return list(SETTING_DEFS)


def _typed_value(value, stype: str):
    """Normalize a typed InputValue payload for a settings prompt.

    ``bccmd.input.parse`` resolves NUMERIC text at string prompts to floats
    ("3" -> 3.0), so payloads may be int/float/str; the bcdoc type decides
    the coercion. Raises ValueError with a re-prompt-ready message on a
    mismatch (bcdoc's Settings.set stays the authority for choices and
    finiteness)."""
    if isinstance(value, bool):
        raise ValueError("expected a value, got a bool")
    if stype == "int":
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"expected an integer, got {value!r}")
            return int(value)
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"expected an integer, got {text!r}") from None
    if stype == "float":
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"expected a number, got {text!r}") from None
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _parse_setting_value(name: str, value):
    """Typed InputValue payload -> a value matching the SETTING_DEFS type
    for ``name`` (Settings.set remains the single validation authority for
    type, choices and finiteness)."""
    definition = SETTING_DEFS.get(name)
    if definition is None:
        raise errors.UnknownSetting(name)
    try:
        return _typed_value(value, definition["type"])
    except ValueError as exc:
        raise ValueError(f"{name} {exc}") from None


def _validate_record_setting(doc, name: str, value) -> None:
    """CLAYER/TEXTSTYLE/DIMSTYLE must reference an existing table record
    (AutoCAD parity — bcdoc's Settings.set cannot check this itself)."""
    if name == "CLAYER":
        if value not in doc.layers:
            raise ValueError(f"layer {value!r} does not exist")
    elif name == "TEXTSTYLE":
        if value not in doc.text_styles():
            raise ValueError(f"text style {value!r} does not exist")
    elif name == "DIMSTYLE":
        if value not in doc.dim_styles():
            raise ValueError(f"dimension style {value!r} does not exist")


# ---------------------------------------------------------------------------
# SETVAR / GETVAR
# ---------------------------------------------------------------------------

def setvar_steps(ctx: CommandContext):
    doc = ctx.document
    while True:
        value = yield Request(
            "string", "SETVAR Enter variable name or [?]:", default="?"
        )
        if isinstance(value.value, str) and value.value.strip() == "?":
            # Contract §4: ``?`` lists all defs+values. Both spellings land
            # here — bare Enter (the ``"?"`` default arrives as a keyword)
            # AND a typed ``?`` (a string request yields kind="string").
            _list_settings(ctx, doc)
            continue
        name = str(value.value).strip().upper()
        if name not in SETTING_DEFS:
            ctx.feedback(f"SETVAR: Unknown system variable: {name!r}")
            continue
        break

    current = doc.settings.get(name)
    while True:
        value = yield Request(
            "string",
            f"SETVAR Enter new value for {name} <{current}>:",
            default=current,
        )
        if value.raw == "":
            # Enter accepts the shown default (keep-current)
            ctx.feedback(f"SETVAR: {name} = {current}")
            return CommandResult(
                status="ok", summary=f"SETVAR: {name} unchanged ({current})"
            )
        try:
            new_value = _parse_setting_value(name, value.value)
            _validate_record_setting(doc, name, new_value)
            doc.settings.set(name, new_value)
        except (ValueError, errors.BcdocError) as exc:
            ctx.feedback(f"SETVAR: {exc}")
            continue
        stored = doc.settings.get(name)
        ctx.feedback(f"SETVAR: {name} = {stored}")
        return CommandResult(status="ok", summary=f"SETVAR: {name} = {stored}")


def _list_settings(ctx: CommandContext, doc) -> None:
    """One feedback line per SETTING_DEFS entry: NAME (type) = value."""
    for name in SETTING_DEFS:
        definition = SETTING_DEFS[name]
        try:
            current = doc.settings.get(name)
        except Exception:  # pragma: no cover - definitions always registered
            current = "?"
        ctx.feedback(f"{name} ({definition['type']}) = {current}")


def getvar_steps(ctx: CommandContext):
    doc = ctx.document
    while True:
        value = yield Request("string", "GETVAR Enter variable name:")
        name = str(value.value).strip().upper()
        if name not in SETTING_DEFS:
            ctx.feedback(f"GETVAR: Unknown system variable: {name!r}")
            continue
        current = doc.settings.get(name)
        ctx.feedback(f"{name} = {current}")
        return CommandResult(status="ok", summary=f"GETVAR: {name} = {current}")


# ---------------------------------------------------------------------------
# OSNAP
# ---------------------------------------------------------------------------

def osnap_steps(ctx: CommandContext):
    doc = ctx.document
    while True:
        value = yield Request(
            "string",
            "OSNAP Specify object snap modes, [?] to list, or none:",
            default="?",
        )
        text = str(value.value).strip()
        if text == "" or text == "?":
            modes = precision.running_modes(doc)
            if modes:
                ctx.feedback("OSNAP: running modes " + ", ".join(modes))
            else:
                ctx.feedback("OSNAP: off (no running modes)")
            return CommandResult(
                status="ok",
                summary="OSNAP: " + (", ".join(modes) if modes else "off"),
            )
        if text.lower() in ("none", "non", "off"):
            doc.settings.set("OSMODE", 0)
            ctx.feedback("OSNAP: off")
            return CommandResult(status="ok", summary="OSNAP: off")
        modes = precision.parse_osnap_tokens(text)
        if not modes:
            ctx.feedback(
                "OSNAP: unknown mode(s) — expected e.g. END,MID,CEN,QUA,"
                "INT,INS,PER,TAN (comma list) or none"
            )
            continue
        try:
            doc.settings.set(
                "OSMODE", sum(precision.OSMODE_BITS[mode] for mode in modes)
            )
        except errors.BcdocError as exc:  # pragma: no cover - bits are ints
            ctx.feedback(f"OSNAP: {exc}")
            continue
        ctx.feedback("OSNAP: running modes " + ", ".join(modes))
        return CommandResult(
            status="ok", summary="OSNAP: " + ", ".join(modes)
        )


# ---------------------------------------------------------------------------
# ORTHO / SNAP / GRID / DYNAMICINPUT — zero-prompt toggles
# ---------------------------------------------------------------------------

def _toggle_run(setting: str, label: str, on_value=1, off_value=0):
    """Build a zero-prompt run callable flipping ``setting`` between
    off_value and on_value (commands_doc.py pattern)."""

    def run(ctx: CommandContext, runner: Runner) -> CommandResult:
        doc = ctx.document
        current = int(doc.settings.get(setting) or 0)
        new = on_value if current == off_value else off_value
        doc.settings.set(setting, new)
        state = "on" if new == on_value else "off"
        ctx.feedback(f"{label} {state}")
        return CommandResult(
            status="ok", summary=f"{label}: {state} ({setting} = {new})"
        )

    return run


# ---------------------------------------------------------------------------
# UNITS — guided walk with deferred apply
# ---------------------------------------------------------------------------

_UNITS_PROMPTS = (
    ("LUNITS", "Enter length units format (1=Scientific, 2=Decimal, "
               "3=Engineering, 4=Architectural)"),
    ("LUPREC", "Enter length precision (decimal places)"),
    ("AUNITS", "Enter angle units format (0=Decimal, 1=Deg/Min/Sec, "
               "2=Grads, 3=Radians, 4=Surveyor)"),
    ("AUPREC", "Enter angle precision (decimal places)"),
    ("INSUNITS", "Enter insertion scale units (0=Unitless, 1=Inches, "
                 "2=Feet, 4=Millimeters, 5=Centimeters, 6=Meters)"),
)


def units_steps(ctx: CommandContext):
    doc = ctx.document
    values = {}
    for name, text in _UNITS_PROMPTS:
        current = doc.settings.get(name)
        while True:
            value = yield Request(
                "string", f"UNITS {text} <{current}>:", default=current
            )
            if value.raw == "":
                values[name] = current  # Enter keeps the shown default
                break
            try:
                number = _typed_value(value.value, "int")
            except ValueError as exc:
                ctx.feedback(f"UNITS: {name} {exc}")
                continue
            try:
                # validate on a scratch copy — writes are DEFERRED so a
                # cancellation mid-walk leaves every setting unchanged
                doc.settings.copy().set(name, number)
            except errors.BcdocError as exc:
                ctx.feedback(f"UNITS: {exc}")
                continue
            values[name] = number
            break
    for name, value in values.items():
        doc.settings.set(name, value)
    summary = (
        f"UNITS: length {doc.settings.get('LUNITS')}/{doc.settings.get('LUPREC')}, "
        f"angle {doc.settings.get('AUNITS')}/{doc.settings.get('AUPREC')}, "
        f"insertion units {doc.settings.get('INSUNITS')}"
    )
    ctx.feedback(summary)
    return CommandResult(status="ok", summary=summary)


# ---------------------------------------------------------------------------
# Command specs
# ---------------------------------------------------------------------------

SETVAR = CommandSpec(
    name="SETVAR", aliases=[], steps=setvar_steps,
    help="Set a system variable (? lists all)",
)
GETVAR = CommandSpec(
    name="GETVAR", aliases=[], steps=getvar_steps,
    help="Show the value of a system variable",
)
OSNAP = CommandSpec(
    name="OSNAP", aliases=["OS"], steps=osnap_steps,
    help="Set running object snaps (none/off, mode list, Enter shows)",
)
ORTHO = CommandSpec(
    name="ORTHO", aliases=[], run=_toggle_run("ORTHOMODE", "Ortho"),
    help="Toggle orthographic cursor constraint",
)
SNAP = CommandSpec(
    name="SNAP", aliases=[], run=_toggle_run("SNAPMODE", "Snap"),
    help="Toggle grid snap",
)
GRID = CommandSpec(
    name="GRID", aliases=[], run=_toggle_run("GRIDMODE", "Grid"),
    help="Toggle the display grid",
)
UNITS = CommandSpec(
    name="UNITS", aliases=[], steps=units_steps,
    help="Walk length/angle unit formats and precisions",
)
DYNAMICINPUT = CommandSpec(
    name="DYNAMICINPUT", aliases=["DYN"],
    run=_toggle_run("DYNMODE", "Dynamic input", on_value=3, off_value=0),
    help="Toggle dynamic input (DYNMODE 3 on / 0 off)",
)

COMMANDS = (SETVAR, GETVAR, OSNAP, ORTHO, SNAP, GRID, UNITS, DYNAMICINPUT)


def register_all(registry) -> object:
    """Register every settings/sysvar command spec into ``registry``
    (mirrors the commands_* modules; called by bcdraft.register_all)."""
    for spec in COMMANDS:
        registry.register(spec)
    return registry
