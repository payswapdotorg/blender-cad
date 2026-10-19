"""Organization commands: LAYER, BLOCK, INSERT (W-D, drafting core).

All three are command-line flows (AutoCAD -LAYER/-BLOCK/INSERT style): a
GUI dialog is explicitly later GUI work (documented in each help string).

* LAYER — option loop [?List/Make/Set/New/Color/Ltype/Lineweight/ON/OFF/
  Freeze/Thaw/Lock/Unlock/Plot/NoPlot/State?]. Every table mutation goes
  through ``doc.layers`` inside one transaction per option invocation
  (journaled, one undo step). CLAYER changes are SETTINGS (persisted, NOT
  journaled — the documented bcdoc exception). Freezing the CURRENT layer
  is refused with feedback (AutoCAD parity); OFF of the current layer is
  allowed. "State?" answers with an honest not-supported message (v0).
* BLOCK — name (or "?" to list), base point, object selection; the
  definition stores COPIES (bcdoc add_block) and the ORIGINALS STAY in the
  drawing (documented divergence from the CLI -BLOCK that erases them —
  feedback states it). Redefinition goes through redefine_block and
  reports how many references updated.
* INSERT — name (with "?" listing), insertion point, uniform scale with an
  XYZ sub-option, rotation; creates an ``insert`` entity on the current
  layer in the current space (one undo step).
"""

from __future__ import annotations

from typing import List

from bccmd import CommandResult, CommandSpec, Request
from bccmd.input import match_keyword
from bcdoc.entities import Insert
from bcdoc.errors import BlockNotFound
from . import geometry
from ._common import ask_point, existing_ids, select_ids


def _ask_string(ctx, prompt: str, default=None) -> str:
    """String prompt; Enter accepts ``default`` when given (parse turns a
    non-str default into the request kind — for strings we resolve the
    keyword ourselves).

    Numeric-looking tokens parse as NUMBERS even at string prompts
    (bccmd parse: plain numbers become ``InputValue(kind=request.kind,
    value=<float>)``), so a layer or block named "3" arrives as the float
    3.0 in a "string"-kind value — integral floats are normalized back to
    their integer spelling ("3", not "3.0").
    """
    while True:
        value = yield Request("string", prompt, default=default)
        if value.kind == "string":
            if isinstance(value.value, float) and value.value == int(value.value):
                return str(int(value.value))
            return str(value.value)
        if value.kind in ("distance", "angle"):
            # explicit numeric InputValues (providers, the shell)
            number = float(value.value)
            if number == int(number):
                return str(int(number))
            return str(number)
        if value.kind == "keyword" and value.value == "Enter" and default:
            return str(default)
        ctx.feedback("A name is required")


def _ask_layer_names(ctx, prompt: str) -> List[str]:
    """Comma-separated layer name list (AutoCAD -LAYER convention)."""
    text = yield from _ask_string(ctx, prompt)
    names = [part.strip() for part in text.split(",") if part.strip()]
    return names


def _format_lineweight(value):
    return "Default" if value is None else f"{value:g} mm"


# ---------------------------------------------------------------------------
# LAYER
# ---------------------------------------------------------------------------

LAYER_OPTIONS = [
    "?List", "Make", "Set", "New", "Color", "Ltype", "Lineweight",
    "ON", "OFF", "Freeze", "Thaw", "Lock", "Unlock", "Plot", "NoPlot",
    "State?",
]


def _layer_list(ctx, doc) -> None:
    lines = []
    for record in doc.layers.records():
        state = "/".join([
            "on" if record.on else "off",
            "thawed" if not record.frozen else "FROZEN",
            "unlocked" if not record.locked else "LOCKED",
            "plot" if record.plot else "noplot",
        ])
        lines.append(
            f"LAYER: {record.name}: color {record.color}, "
            f"linetype {record.linetype!r}, "
            f"lineweight {_format_lineweight(record.lineweight)} [{state}]"
        )
    for line in lines:
        ctx.feedback(line)


def _layer_flag(ctx, doc, option: str, names: List[str]) -> None:
    """ON/OFF/Freeze/Thaw/Lock/Unlock/Plot/NoPlot in one transaction."""
    flags = {
        "ON": {"on": True}, "OFF": {"on": False},
        "Freeze": {"frozen": True}, "Thaw": {"frozen": False},
        "Lock": {"locked": True}, "Unlock": {"locked": False},
        "Plot": {"plot": True}, "NoPlot": {"plot": False},
    }
    changes = flags[option]
    applied: List[str] = []
    with doc.transaction(f"LAYER {option}"):
        for name in names:
            record = doc.layers.get(name)
            if record is None:
                ctx.feedback(f"LAYER: layer '{name}' not found — skipped")
                continue
            if option == "Freeze" and name == doc.current_layer:
                # AutoCAD refuses freezing the CURRENT layer
                ctx.feedback(
                    f"LAYER: cannot freeze the current layer '{name}'")
                continue
            doc.layers.set_props(name, **changes)
            applied.append(name)
    if applied:
        ctx.feedback(f"LAYER: {option} applied to {len(applied)} layer(s)")


def layer_steps(ctx):
    doc = ctx.document
    while True:
        value = yield Request(
            "string",
            "LAYER Enter an option "
            "[?List/Make/Set/New/Color/Ltype/Lineweight/ON/OFF/Freeze/Thaw/"
            "Lock/Unlock/Plot/NoPlot/State?]: ",
            default="Enter",
        )
        if value.kind == "keyword" and value.value == "Enter":
            break  # Enter ends the option loop
        if value.kind in ("distance", "angle"):
            ctx.feedback("LAYER: option required")
            continue
        token = str(value.value).strip()
        option = match_keyword(token, LAYER_OPTIONS)
        if option is None:
            ctx.feedback(f"LAYER: unknown option {token!r}")
            continue
        if option == "?List":
            _layer_list(ctx, doc)
        elif option == "Make":
            name = yield from _ask_string(
                ctx, "LAYER Enter name of layer to make current:")
            if doc.layers.get(name) is None:
                with doc.transaction("LAYER Make"):
                    doc.layers.add(name)
                ctx.feedback(f"LAYER: layer '{name}' created")
            doc.settings.set("CLAYER", name)
            ctx.feedback(f"LAYER: current layer is '{name}'")
        elif option == "Set":
            while True:
                name = yield from _ask_string(
                    ctx, "LAYER Enter name of layer to make current or <*>:")
                if doc.layers.get(name) is None:
                    ctx.feedback(f"LAYER: layer '{name}' not found")
                    continue
                doc.settings.set("CLAYER", name)
                ctx.feedback(f"LAYER: current layer is '{name}'")
                break
        elif option == "New":
            names = yield from _ask_layer_names(
                ctx, "LAYER Enter name list of new layer(s) (comma-separated):")
            if not names:
                ctx.feedback("LAYER: no layer names given")
                continue
            created = 0
            with doc.transaction("LAYER New"):
                for name in names:
                    if doc.layers.get(name) is None:
                        doc.layers.add(name)
                        created += 1
                    else:
                        ctx.feedback(f"LAYER: layer '{name}' already exists")
            if created:
                ctx.feedback(f"LAYER: {created} layer(s) created")
        elif option == "Color":
            while True:
                color_value = yield Request(
                    "distance", "LAYER New color [ACI 1-255]:")
                if color_value.kind in ("distance", "angle"):
                    number = float(color_value.value)
                    if number == int(number) and 1.0 <= number <= 255.0:
                        break
                ctx.feedback("LAYER: color must be an integer 1-255")
            names = yield from _ask_layer_names(
                ctx, f"LAYER Enter name list of layers for color {int(number)}:")
            applied = 0
            with doc.transaction("LAYER Color"):
                for name in names:
                    if doc.layers.get(name) is None:
                        ctx.feedback(f"LAYER: layer '{name}' not found — skipped")
                        continue
                    doc.layers.set_props(name, color=int(number))
                    applied += 1
            if applied:
                ctx.feedback(
                    f"LAYER: color {int(number)} applied to {applied} layer(s)")
        elif option == "Ltype":
            linetype = yield from _ask_string(ctx, "LAYER Linetype:")
            names = yield from _ask_layer_names(
                ctx, f"LAYER Enter name list of layers for linetype {linetype!r}:")
            # stored as a name — linetype RENDERING is later work (M3)
            applied = 0
            with doc.transaction("LAYER Ltype"):
                for name in names:
                    if doc.layers.get(name) is None:
                        ctx.feedback(f"LAYER: layer '{name}' not found — skipped")
                        continue
                    doc.layers.set_props(name, linetype=str(linetype))
                    applied += 1
            if applied:
                ctx.feedback(
                    f"LAYER: linetype {linetype!r} applied to {applied} layer(s)")
        elif option == "Lineweight":
            while True:
                weight_value = yield Request(
                    "distance", "LAYER Lineweight (mm, 0 = default):")
                if weight_value.kind in ("distance", "angle"):
                    weight = float(weight_value.value)
                    if weight >= 0.0:
                        break
                ctx.feedback("LAYER: lineweight must be zero or positive")
            names = yield from _ask_layer_names(
                ctx, "LAYER Enter name list of layers for lineweight:")
            applied = 0
            with doc.transaction("LAYER Lineweight"):
                for name in names:
                    if doc.layers.get(name) is None:
                        ctx.feedback(f"LAYER: layer '{name}' not found — skipped")
                        continue
                    doc.layers.set_props(
                        name, lineweight=(None if weight == 0.0 else weight))
                    applied += 1
            if applied:
                ctx.feedback(f"LAYER: lineweight applied to {applied} layer(s)")
        elif option in ("ON", "OFF", "Freeze", "Thaw", "Lock", "Unlock",
                        "Plot", "NoPlot"):
            names = yield from _ask_layer_names(
                ctx, f"LAYER Enter name list of layers to {option}:")
            _layer_flag(ctx, doc, option, names)
        elif option == "State?":
            ctx.feedback(
                "LAYER: layer-state save/restore is not supported (v0)")
    return CommandResult(status="ok", summary="LAYER: done")


# ---------------------------------------------------------------------------
# BLOCK
# ---------------------------------------------------------------------------

def block_steps(ctx):
    doc = ctx.document
    while True:
        name = yield from _ask_string(
            ctx, "BLOCK Enter name for block (or ? to list existing):")
        if name == "?":
            names = doc.block_names()
            if names:
                ctx.feedback(
                    "BLOCK: " + ", ".join(names))
            else:
                ctx.feedback("BLOCK: no block definitions")
            continue
        if name:
            break
    try:
        doc.block(name)
        redefining = True
    except BlockNotFound:
        redefining = False
    if redefining:
        ctx.feedback(f"BLOCK: '{name}' already exists — redefining")
    base = yield from ask_point(
        ctx, Request("point", "BLOCK Specify insertion base point:"))
    ctx.set_last_point(base)
    ids = yield from select_ids(ctx, "BLOCK")
    if not ids:
        return CommandResult(
            status="ok",
            summary="BLOCK: no objects selected — nothing defined")
    members = [doc.get(eid) for eid in ids]
    with doc.transaction("BLOCK"):
        if redefining:
            definition = doc.redefine_block(
                name, members, base_point=base.to_tuple())
        else:
            definition = doc.add_block(name, base.to_tuple(), members)
    # v0 policy (documented divergence): the definition stores COPIES and
    # the SOURCE OBJECTS STAY in the drawing (the CLI -BLOCK erases them —
    # we keep them, feedback states it; the GUI dialog may add the choice).
    ctx.feedback(
        f"BLOCK: '{name}' defined with {len(definition.entities)} member(s) "
        "— source objects stay in the drawing (v0)")
    if redefining:
        refs = len(doc.block_ref_ids(name))
        ctx.feedback(f"BLOCK: {refs} reference(s) updated")
    summary = f"BLOCK: '{name}' defined with {len(definition.entities)} member(s)"
    if redefining:
        summary += f" (redefined, {len(doc.block_ref_ids(name))} ref(s) updated)"
    return CommandResult(status="ok", summary=summary, created=[])


# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------

def insert_steps(ctx):
    doc = ctx.document
    while True:
        name = yield from _ask_string(
            ctx, "INSERT Enter block name (or ? to list existing):")
        if name == "?":
            names = doc.block_names()
            ctx.feedback(
                "INSERT: " + (", ".join(names) if names else "no block definitions"))
            continue
        if name not in doc.block_names():
            ctx.feedback(f"INSERT: block '{name}' not found")
            continue
        break
    position = yield from ask_point(
        ctx, Request("point", "INSERT Specify insertion point:"))
    ctx.set_last_point(position)
    scale = (1.0, 1.0, 1.0)
    while True:
        value = yield Request(
            "distance", "INSERT Specify scale factor for XYZ axes or [XYZ] <1>:",
            options=["XYZ"], default=1.0,
        )
        if value.kind == "keyword" and value.value == "XYZ":
            components = []
            for axis in ("X", "Y", "Z"):
                while True:
                    axis_value = yield Request(
                        "distance", f"INSERT Specify {axis} scale factor <1>:",
                        default=1.0,
                    )
                    if (axis_value.kind in ("distance", "angle")
                            and float(axis_value.value) > 0.0):
                        components.append(float(axis_value.value))
                        break
                    ctx.feedback("INSERT: scale factors must be positive")
            scale = tuple(components)
            break
        if value.kind in ("distance", "angle") and float(value.value) > 0.0:
            uniform = float(value.value)
            scale = (uniform, uniform, uniform)
            break
        ctx.feedback("INSERT: positive scale factor or [XYZ]")
    while True:
        value = yield Request(
            "angle", "INSERT Specify rotation angle <0>:", default=0.0)
        if value.kind == "angle":
            rotation = float(value.value)
            break
        if value.kind == "point":
            rotation = geometry.angle_of(
                (value.value.x - position.x, value.value.y - position.y))
            break
        ctx.feedback("INSERT: rotation angle required")
    with doc.transaction("INSERT"):
        entity = doc.add_entity(Insert(
            name, position.to_tuple(), scale=scale, rotation=rotation,
            layer=doc.current_layer, space=doc.current_space,
        ))
    ctx.feedback(
        f"INSERT: '{name}' at ({position.x:g}, {position.y:g}) "
        f"scale ({scale[0]:g},{scale[1]:g},{scale[2]:g}) rotation {rotation:g}°")
    return CommandResult(
        status="ok",
        summary=f"INSERT: '{name}' reference created",
        created=[entity.id],
    )


# ---------------------------------------------------------------------------
# Command specs
# ---------------------------------------------------------------------------

LAYER = CommandSpec(
    name="LAYER", aliases=["-LAYER", "LA"], steps=layer_steps,
    help="Layer table options (command-line; Make/Set/New/Color/Ltype/...",
)
BLOCK = CommandSpec(
    name="BLOCK", aliases=["B"], steps=block_steps,
    help="Define a block from selected objects (originals stay; command-line)",
)
INSERT = CommandSpec(
    name="INSERT", aliases=["I"], steps=insert_steps,
    help="Place a block reference at a point with scale and rotation",
)

COMMANDS = (LAYER, BLOCK, INSERT)
