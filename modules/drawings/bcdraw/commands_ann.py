"""Annotation commands: dimensions, text, styles (contracts §5.2).

Registered commands (all names NEW — no collisions with bccmd/bcdraft):
``DIMLINEAR``, ``DIMALIGNED``, ``DIMSTYLE``, ``DIMREGEN``, ``TEXT``,
``MTEXT``, ``STYLE``.

Every command is a steps-generator (or a prompt-free ``run`` callable) —
one implementation driven by both the blocking Runner and the modal
operator (m1-contracts §4). All document mutations happen inside exactly
ONE transaction per command run (one undo step); invalid input gets
feedback + re-prompt; Cancelled aborts with no partial state.

Prompt flows (pinned by the W-C task letter; AutoCAD-familiar):

- DIMLINEAR: first extension origin, or Enter -> "Select line to
  dimension:" (selection; the first LINE entity wins — PICKFIRST
  preselection included; a selection without a line feeds back and
  re-asks; Enter there returns to the origin prompt), then the second
  origin (explicit path only), then "Specify dimension line location or
  [Horizontal/Vertical/Rotation]:". A plain placement point AUTO-picks
  Horizontal/Vertical by the dominant offset direction (|dy| >= |dx| ->
  horizontal; tie -> horizontal, documented); the keywords fix the
  measurement angle (Rotation asks for it); placement follows keywords.
- DIMALIGNED: same entity-select path; axis = p1 -> p2; no Rotation option.
- DIMSTYLE / STYLE: "[?List/New/Set]" — List prints one feedback line per
  record then re-asks the option; New prompts name + per-value prompts
  (defaults = the CURRENT style's values); Set validates existence before
  writing the TEXTSTYLE/DIMSTYLE setting. Enter at the option prompt ends
  the command politely.
- DIMREGEN: prompt-free; runs :func:`bcdraw.regen.refresh_document`.
- TEXT: start point (or [Justify] -> LEFT/CENTER/RIGHT), height (default
  = current text style height), rotation (default 0), content string.
- MTEXT: first corner, positive width, content string — the LITERAL
  two-character sequence ``\\n`` in the input converts to a newline
  (scripted/shell input has no editor at M2; documented).

Documented M2 limits (honest): numeric-STARTING content strings that also
contain spaces (e.g. "12.5 mm") cannot be typed through the M1 parser
(bccmd input grammar; a bccmd-owned limitation, recorded for TL) — pass
InputValue(kind="string", ...) directly from providers; DIMLINEAR's
select-object path takes LINE entities only (polyline-segment picks need
shell-side pick-point resolution, contract §5.2 note, deferred); no
per-dimension variable overrides (FP-ANN-018), no text editor (FP-ANN-022).
"""

from __future__ import annotations

import math
from typing import Optional

from bccmd import CommandContext, CommandResult, CommandSpec, Point, Request
from bcdoc.entities import Dim, Mtext, Text
from bcdraft import geometry as bgeo
from bcdraft._common import ask_point, existing_ids

from . import regen
from .dims import aligned_geometry, linear_geometry, style_for


# ---------------------------------------------------------------------------
# shared ask helpers (small, local — this package has no _common file by
# design; the file list is pinned by the task letter)
# ---------------------------------------------------------------------------

def _ask_string(ctx: CommandContext, request: Request, command: str) -> str:
    """Ask until a non-empty text value arrives (parse rejects empty)."""
    while True:
        value = yield request
        if value.kind == "string":
            if isinstance(value.value, str):
                return value.value
            if value.raw:
                # numeric tokens arrive at string prompts as floats — the
                # raw text is the honest content ("12" stays "12")
                return value.raw.strip()
            return str(value.value)
        ctx.feedback(f"{command}: text input required")


def _ask_number(ctx: CommandContext, request: Request, command: str,
                positive: bool = False, allow_zero: bool = False) -> float:
    """Ask for a number (any float, or positive/non-negative per flags).

    Defaults come through ``request.default`` (parse converts empty input).
    A POINT at a numeric prompt means "distance from the last point" when
    one exists (the AutoCAD mouse convention honored by bccmd).
    """
    while True:
        value = yield request
        if value.kind in ("distance", "angle") and isinstance(value.value, (int, float)):
            number = float(value.value)
            if positive and number <= 0.0:
                ctx.feedback(f"{command}: value must be positive")
                continue
            if allow_zero and number < 0.0:
                ctx.feedback(f"{command}: value must not be negative")
                continue
            return number
        if value.kind == "point":
            reference = ctx.last_point
            if reference is not None:
                number = bgeo.dist_2d(
                    (reference.x, reference.y),
                    (value.value.x, value.value.y),
                )
                if number > 0.0 or (allow_zero and number >= 0.0):
                    return number
            ctx.feedback(f"{command}: number required (or pick a point)")
            continue
        ctx.feedback(f"{command}: number required")


def _auto_angle(p1, p2, placement) -> float:
    """Auto Horizontal/Vertical from the placement offset (AutoCAD rule).

    The dimension line is placed by dragging AWAY from the measured pair:
    a dominant vertical offset means a horizontal dim line (angle 0), a
    dominant horizontal offset a vertical one (angle 90); an exact tie
    falls back to horizontal (documented deterministic default).
    """
    mid_x = (p1[0] + p2[0]) / 2.0
    mid_y = (p1[1] + p2[1]) / 2.0
    dx = abs(placement[0] - mid_x)
    dy = abs(placement[1] - mid_y)
    return 0.0 if dy >= dx else 90.0


def _text_style_for(doc, name: str):
    """Text-style mirror of dims.style_for (Standard fallback)."""
    from bcdoc.errors import StyleNotFound

    try:
        return doc.text_style(name)
    except StyleNotFound:
        pass
    try:
        return doc.text_style("Standard")
    except Exception:  # pragma: no cover - "Standard" is always present
        from bcdoc.styles import TextStyleRecord

        return TextStyleRecord("Standard")


# ---------------------------------------------------------------------------
# DIMLINEAR / DIMALIGNED
# ---------------------------------------------------------------------------

def _select_line(ctx: CommandContext, command: str):
    """"Select line to dimension:" — first LINE entity wins (PICKFIRST
    preselection included). Enter returns None (back to the origin prompt).
    A selection without a LINE feeds back and re-asks (M2: LINEs only —
    polyline-segment picks are deferred, see module docstring)."""
    doc = ctx.document
    for eid in existing_ids(doc, sorted(doc.selection.ids)):
        if doc.get(eid).kind == "line":
            return doc.get(eid)
    request = Request("selection", f"{command} Select line to dimension:")
    while True:
        value = yield request
        if value.kind == "selection":
            for eid in existing_ids(doc, value.value or []):
                entity = doc.get(eid)
                if entity.kind == "line":
                    return entity
            ctx.feedback(f"{command}: no LINE entity in that selection")
            continue
        if value.kind == "keyword" and value.value == "Enter":
            return None
        ctx.feedback(f"{command}: select a line, or press Enter to go back")


def _measured_pair(ctx: CommandContext, command: str):
    """First-origin prompt (Enter -> line selection) + second origin.

    Returns ``(p1, p2, measured_id)`` — measured_id set only on the
    entity-select path (associativity)."""
    doc = ctx.document
    while True:
        value = yield Request(
            "point",
            f"{command} Specify first extension line origin or <select object>:",
        )
        if value.kind == "keyword" and value.value == "Enter":
            line = yield from _select_line(ctx, command)
            if line is None:
                continue
            ctx.set_last_point(Point(*line.p2))
            return tuple(line.p1), tuple(line.p2), line.id
        if value.kind == "point":
            p1 = value.value.to_tuple()
            ctx.set_last_point(value.value)
            while True:
                second = yield Request(
                    "point", f"{command} Specify second extension line origin:")
                if second.kind != "point":
                    ctx.feedback(f"{command}: second origin point required")
                    continue
                p2 = second.value.to_tuple()
                if bgeo.dist_2d(p1, p2) <= bgeo.TOL:
                    ctx.feedback(
                        f"{command}: the two origins coincide — no measurement")
                    continue
                ctx.set_last_point(second.value)
                return p1, p2, ""
        ctx.feedback(f"{command}: point required, or press Enter to select a line")


def dimlinear_steps(ctx: CommandContext):
    doc = ctx.document
    p1, p2, measured_id = yield from _measured_pair(ctx, "DIMLINEAR")

    angle_deg: Optional[float] = None
    while True:
        value = yield Request(
            "point",
            "DIMLINEAR Specify dimension line location or "
            "[Horizontal/Vertical/Rotation]:",
            options=["Horizontal", "Vertical", "Rotation"],
        )
        if value.kind == "point":
            placement = value.value.to_tuple()
            angle_deg = _auto_angle(p1, p2, placement)
            break
        if value.kind == "keyword" and isinstance(value.value, str):
            choice = value.value
            if choice == "Horizontal":
                angle_deg = 0.0
            elif choice == "Vertical":
                angle_deg = 90.0
            elif choice == "Rotation":
                angle_deg = yield from _ask_number(
                    ctx,
                    Request("angle", "DIMLINEAR Specify angle of dimension line <0>:",
                            default=0.0),
                    "DIMLINEAR",
                )
            elif choice == "Enter":
                ctx.feedback("DIMLINEAR: location point or option required")
                continue
            else:  # pragma: no cover - parser only returns listed options
                ctx.feedback(f"DIMLINEAR: unknown option {choice!r}")
                continue
            placement_pt = yield from ask_point(
                ctx, Request("point", "DIMLINEAR Specify dimension line location:"))
            placement = placement_pt.to_tuple()
            break
        ctx.feedback("DIMLINEAR: location point or option required")

    return _create_dim(ctx, "linear", p1, p2, measured_id, angle_deg, placement,
                       "DIMLINEAR")


def dimaligned_steps(ctx: CommandContext):
    doc = ctx.document
    p1, p2, measured_id = yield from _measured_pair(ctx, "DIMALIGNED")

    placement_pt = yield from ask_point(
        ctx, Request("point", "DIMALIGNED Specify dimension line location:"))
    placement = placement_pt.to_tuple()

    # Informational axis angle (aligned geometry always derives its axis
    # live from p1 -> p2; the stored angle is presentation reference only).
    axis_angle = bgeo.normalize_deg(
        math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0])))
    return _create_dim(ctx, "aligned", p1, p2, measured_id, axis_angle,
                       placement, "DIMALIGNED")


def _create_dim(ctx: CommandContext, dim_type: str, p1, p2, measured_id,
                angle_deg, placement, command: str) -> CommandResult:
    doc = ctx.document
    settings_name = str(doc.settings.get("DIMSTYLE"))
    style = style_for(doc, settings_name)
    if style.name != settings_name:
        ctx.feedback(
            f"{command}: dim style {settings_name!r} not found — "
            f"using {style.name!r}")
    geometry = (
        aligned_geometry(p1, p2, placement, style, doc.settings)
        if dim_type == "aligned"
        else linear_geometry(p1, p2, angle_deg, placement, style, doc.settings)
    )
    dim = Dim(
        dim_type, p1, p2,
        angle=float(angle_deg),
        offset_point=placement,
        measured_id=measured_id,
        measurement=geometry.measurement,
        style=style.name,
        layer=doc.current_layer,
        space=doc.current_space,
    )
    with doc.transaction(command):
        entity = doc.add_entity(dim)
    ctx.set_last_point(Point(*placement))
    ctx.feedback(f"{command}: {dim_type} dimension, measured {geometry.text_value}")
    return CommandResult(
        status="ok",
        summary=f"{command}: {geometry.text_value}",
        created=[entity.id],
    )


# ---------------------------------------------------------------------------
# DIMREGEN (prompt-free)
# ---------------------------------------------------------------------------

def dimregen_run(ctx: CommandContext, runner) -> CommandResult:
    result = regen.refresh_document(ctx.document)
    summary = f"DIMREGEN: {result['refreshed']} dimension(s) refreshed"
    ctx.feedback(summary)
    return CommandResult(status="ok", summary=summary)


# ---------------------------------------------------------------------------
# DIMSTYLE / STYLE ([?List/New/Set])
# ---------------------------------------------------------------------------

_DIM_FIELDS = (
    ("dimscale", "Enter overall scale factor (dimscale)", True),
    ("dimtxt", "Enter text height (dimtxt)", True),
    ("dimasz", "Enter arrow size (dimasz)", True),
    ("dimexo", "Enter extension line offset (dimexo)", False),
    ("dimexe", "Enter extension line extension (dimexe)", False),
)


def dimstyle_steps(ctx: CommandContext):
    doc = ctx.document
    while True:
        value = yield Request(
            "keyword", "DIMSTYLE Enter option [?List/New/Set]:",
            options=["?List", "New", "Set"], default="Exit",
        )
        choice = value.value if (value.kind == "keyword"
                                 and isinstance(value.value, str)) else None
        if choice == "Exit":
            return CommandResult(status="ok", summary="DIMSTYLE: done")
        if choice == "?List":
            for name in doc.dim_styles():
                record = doc.dim_style(name)
                ctx.feedback(
                    f"Dim style {record.name!r}: dimscale={record.dimscale:g} "
                    f"dimtxt={record.dimtxt:g} dimasz={record.dimasz:g} "
                    f"dimexo={record.dimexo:g} dimexe={record.dimexe:g}")
            continue
        if choice == "New":
            name = yield from _new_style_name(ctx, "DIMSTYLE", doc.dim_styles())
            current = style_for(doc, str(doc.settings.get("DIMSTYLE")))
            props = {}
            for field, label, positive in _DIM_FIELDS:
                props[field] = yield from _ask_number(
                    ctx,
                    Request("distance", f"DIMSTYLE {label} <{getattr(current, field):g}>:",
                            default=getattr(current, field)),
                    "DIMSTYLE", positive=positive, allow_zero=not positive,
                )
            with doc.transaction("DIMSTYLE New"):
                doc.add_dim_style(name, **props)
            ctx.feedback(f"DIMSTYLE: dimension style {name!r} created")
            return CommandResult(status="ok",
                                 summary=f"DIMSTYLE: created {name!r}")
        if choice == "Set":
            name = yield from _existing_style_name(ctx, "DIMSTYLE", "dim",
                                                   doc.dim_styles())
            doc.settings.set("DIMSTYLE", name)
            ctx.feedback(f"DIMSTYLE: current dimension style is {name!r}")
            return CommandResult(status="ok", summary=f"DIMSTYLE: set {name!r}")
        ctx.feedback("DIMSTYLE: option ?List/New/Set required")


def _new_style_name(ctx: CommandContext, command: str, existing) -> str:
    doc = ctx.document
    while True:
        name = yield from _ask_string(
            ctx, Request("string", f"{command} Enter name for new style:"), command)
        if name.upper() == "STANDARD":
            ctx.feedback(f"{command}: 'Standard' always exists — pick another name")
            continue
        if name in existing:
            ctx.feedback(f"{command}: style {name!r} already exists")
            continue
        return name


def _existing_style_name(ctx: CommandContext, command: str, kind: str,
                         existing) -> str:
    while True:
        name = yield from _ask_string(
            ctx, Request("string", f"{command} Enter name of {kind} style to use:"),
            command)
        if name not in existing:
            ctx.feedback(f"{command}: no {kind} style named {name!r}")
            continue
        return name


def style_steps(ctx: CommandContext):
    doc = ctx.document
    while True:
        value = yield Request(
            "keyword", "STYLE Enter option [?List/New/Set]:",
            options=["?List", "New", "Set"], default="Exit",
        )
        choice = value.value if (value.kind == "keyword"
                                 and isinstance(value.value, str)) else None
        if choice == "Exit":
            return CommandResult(status="ok", summary="STYLE: done")
        if choice == "?List":
            for name in doc.text_styles():
                record = doc.text_style(name)
                ctx.feedback(
                    f"Text style {record.name!r}: height={record.height:g} "
                    f"width_factor={record.width_factor:g}")
            continue
        if choice == "New":
            name = yield from _new_style_name(ctx, "STYLE", doc.text_styles())
            current = _text_style_for(doc, str(doc.settings.get("TEXTSTYLE")))
            height = yield from _ask_number(
                ctx,
                Request("distance", f"STYLE Enter text height <{current.height:g}>:",
                        default=current.height),
                "STYLE", positive=True)
            width_factor = yield from _ask_number(
                ctx,
                Request("distance",
                        f"STYLE Enter width factor <{current.width_factor:g}>:",
                        default=current.width_factor),
                "STYLE", positive=True)
            with doc.transaction("STYLE New"):
                doc.add_text_style(name, height=height, width_factor=width_factor)
            ctx.feedback(f"STYLE: text style {name!r} created")
            return CommandResult(status="ok", summary=f"STYLE: created {name!r}")
        if choice == "Set":
            name = yield from _existing_style_name(ctx, "STYLE", "text",
                                                   doc.text_styles())
            doc.settings.set("TEXTSTYLE", name)
            ctx.feedback(f"STYLE: current text style is {name!r}")
            return CommandResult(status="ok", summary=f"STYLE: set {name!r}")
        ctx.feedback("STYLE: option ?List/New/Set required")


# ---------------------------------------------------------------------------
# TEXT / MTEXT
# ---------------------------------------------------------------------------

def text_steps(ctx: CommandContext):
    doc = ctx.document
    justification = "LEFT"
    while True:
        value = yield Request(
            "point", "TEXT Specify start point of text or [Justify]:",
            options=["Justify"],
        )
        if value.kind == "point":
            start = value.value.to_tuple()
            ctx.set_last_point(value.value)
            break
        if value.kind == "keyword" and value.value == "Justify":
            justification = yield from _ask_justification(ctx)
            continue
        ctx.feedback("TEXT: start point or [Justify] required")

    style = _text_style_for(doc, str(doc.settings.get("TEXTSTYLE")))
    if style.name != str(doc.settings.get("TEXTSTYLE")):
        ctx.feedback(
            f"TEXT: text style {doc.settings.get('TEXTSTYLE')!r} not found — "
            f"using {style.name!r}")
    height = yield from _ask_number(
        ctx,
        Request("distance", f"TEXT Specify height of text <{style.height:g}>:",
                default=style.height),
        "TEXT", positive=True)
    rotation = yield from _ask_number(
        ctx, Request("angle", "TEXT Specify rotation angle of text <0>:", default=0.0),
        "TEXT")
    content = yield from _ask_string(
        ctx, Request("string", "TEXT Enter text:"), "TEXT")

    entity = Text(
        start, height=height, rotation=rotation, content=content,
        style=style.name, justification=justification,
        layer=doc.current_layer, space=doc.current_space,
    )
    with doc.transaction("TEXT"):
        added = doc.add_entity(entity)
    ctx.feedback(
        f"TEXT: {content!r} at ({start[0]:g}, {start[1]:g}) "
        f"height {height:g}, rotation {rotation:g}")
    return CommandResult(
        status="ok", summary=f"TEXT: {content!r}", created=[added.id])


def _ask_justification(ctx: CommandContext) -> str:
    while True:
        value = yield Request(
            "keyword", "TEXT Enter justification [Left/Center/Right]:",
            options=["Left", "Center", "Right"],
        )
        if value.kind == "keyword" and isinstance(value.value, str):
            if value.value == "Enter":
                ctx.feedback("TEXT: justification Left/Center/Right required")
                continue
            if value.value in ("Left", "Center", "Right"):
                return value.value.upper()   # bcdoc stores LEFT/CENTER/RIGHT
        ctx.feedback("TEXT: justification Left/Center/Right required")


def mtext_steps(ctx: CommandContext):
    doc = ctx.document
    corner_pt = yield from ask_point(
        ctx, Request("point", "MTEXT Specify first corner of text box:"))
    corner = corner_pt.to_tuple()
    ctx.set_last_point(corner_pt)
    width = yield from _ask_number(
        ctx, Request("distance", "MTEXT Specify width of text box:"), "MTEXT",
        positive=True)
    raw = yield from _ask_string(
        ctx, Request("string", "MTEXT Enter text (literal \\n = new line):"),
        "MTEXT")
    content = raw.replace("\\n", "\n")

    style = _text_style_for(doc, str(doc.settings.get("TEXTSTYLE")))
    entity = Mtext(
        corner, width=width, content=content, style=style.name,
        layer=doc.current_layer, space=doc.current_space,
    )
    with doc.transaction("MTEXT"):
        added = doc.add_entity(entity)
    ctx.feedback(f"MTEXT: {len(content.splitlines())} line(s) at "
                 f"({corner[0]:g}, {corner[1]:g}), width {width:g}")
    return CommandResult(
        status="ok", summary=f"MTEXT: {len(content.splitlines())} line(s)",
        created=[added.id])


# ---------------------------------------------------------------------------
# command specs
# ---------------------------------------------------------------------------

DIMLINEAR = CommandSpec(
    name="DIMLINEAR", aliases=[],
    steps=dimlinear_steps,
    help="Linear dimension (horizontal/vertical/rotated) with associativity",
)
DIMALIGNED = CommandSpec(
    name="DIMALIGNED", aliases=[],
    steps=dimaligned_steps,
    help="Aligned dimension parallel to the measured points",
)
DIMSTYLE = CommandSpec(
    name="DIMSTYLE", aliases=[],
    steps=dimstyle_steps,
    help="Dimension styles: list / create / set current",
)
DIMREGEN = CommandSpec(
    name="DIMREGEN", aliases=[],
    run=dimregen_run,
    help="Refresh cached dimension measurements from their geometry",
)
TEXT = CommandSpec(
    name="TEXT", aliases=[],
    steps=text_steps,
    help="Single-line text with justification options",
)
MTEXT = CommandSpec(
    name="MTEXT", aliases=[],
    steps=mtext_steps,
    help="Multiline text block (literal \\n converts to a new line)",
)
STYLE = CommandSpec(
    name="STYLE", aliases=[],
    steps=style_steps,
    help="Text styles: list / create / set current",
)

COMMANDS = (
    DIMLINEAR, DIMALIGNED, DIMSTYLE, DIMREGEN, TEXT, MTEXT, STYLE,
)


def register_all(registry):
    """Register every annotation command spec into ``registry``."""
    for spec in COMMANDS:
        registry.register(spec)
    return registry


__all__ = ["COMMANDS", "register_all"]
