"""bcshell.panel_ops — pure mutation logic behind the v2 panel operators.

The v2 N-panel sections (contract §7: Layers / Layout-Space / Precision)
need operators that do REAL document mutations. The mutation logic lives
HERE — pure, bpy-free, headless-testable — and the thin bpy operator
wrappers in ops.py call it, add the session feedback/report/sync and
return FINISHED/CANCELLED. (The operator classes themselves are the
Blender-GUI side: modules/shell/tests/blender_driver*.py validate their
registration + execute paths inside Blender; the M1 pure/bpy boundary
tests forbid importing ops.py under plain pytest, so the LOGIC is what
pytest exercises.)

Every function returns ``(ok: bool, message: str)`` so operators sink the
message into the session feedback ring + Blender's report system with the
right severity. Transactions are used where bcdoc requires them (layer
property changes, layout creation); settings use the direct
``doc.settings.set`` path (contract §2.5: settings are persisted but NOT
journaled — UNDO does not revert sysvars, matching AutoCAD).
"""

from __future__ import annotations

from typing import Tuple

#: layer properties the toggle operator may flip (contract §7 Layers
#: section: on / freeze / lock; "plot" is exposed for completeness)
LAYER_TOGGLE_PROPS = ("on", "frozen", "locked", "plot")

#: the bool-style int settings the Precision section toggles. ORTHOMODE /
#: SNAPMODE / GRIDMODE flip 0/1; DYNMODE flips 3/0 (contracts §2.5/§5.2 —
#: the dynamic-input sysvar uses 3 for "on", like AutoCAD).
BOOL_SETTINGS = ("ORTHOMODE", "SNAPMODE", "GRIDMODE", "DYNMODE")

#: osnap mode name -> OSMODE bit (contracts §2.5 — the P0 panel set)
OSNAP_BITS = {
    "ENDPOINT": 1,
    "MIDPOINT": 2,
    "CENTER": 4,
    "QUADRANT": 16,
    "INTERSECTION": 32,
    "PERPENDICULAR": 128,
    "TANGENT": 1024,
}

#: default OSMODE as defined by the bcdoc settings registry
OSMODE_DEFAULT = 55


def set_current_layer(doc, name) -> Tuple[bool, str]:
    """Set CLAYER (the current layer). The layer must exist (a clear error
    instead of a dangling CLAYER — bcdoc falls back to "0" on read, so the
    operator refuses the change up front)."""
    name = str(name)
    if not name:
        return False, "Layer name required"
    if doc.layers.get(name) is None:
        return False, f"Layer not found: {name}"
    doc.settings.set("CLAYER", name)
    return True, f"Current layer: {name}"


def toggle_layer_prop(doc, name, prop, value) -> Tuple[bool, str]:
    """Flip one layer property (on/frozen/locked/plot) through a journaled
    transaction (undoable like the LAYER command's equivalents)."""
    name = str(name)
    prop = str(prop)
    if prop not in LAYER_TOGGLE_PROPS:
        return False, f"Unknown layer property: {prop}"
    record = doc.layers.get(name)
    if record is None:
        return False, f"Layer not found: {name}"
    value = bool(value)
    current = bool(getattr(record, prop))
    if current == value:
        return True, f"Layer {name}: {prop} already {'on' if value else 'off'}"
    with doc.transaction(f"Layer {name} {prop} {'on' if value else 'off'}"):
        doc.layers.set_props(name, **{prop: value})
    return True, f"Layer {name}: {prop} {'on' if value else 'off'}"


def activate_space(doc, name) -> Tuple[bool, str]:
    """Activate a space: sets ``doc.current_space`` ("MODEL" resets to
    model space) and keeps the ``active_layout`` viewing pointer in step
    (contracts §5.4: MODEL view = active_layout None; a layout view sets
    both, TILEMODE follows through set_current_space)."""
    name = str(name)
    if name == "MODEL":
        doc.set_current_space("MODEL")
        doc.active_layout = None
        return True, "Current space: MODEL"
    if name not in doc.layouts():
        return False, f"Layout not found: {name}"
    doc.set_current_space(name)
    doc.active_layout = name
    return True, f"Current space: {name}"


def new_layout(doc, name) -> Tuple[bool, str]:
    """Create a layout through a journaled transaction and activate it
    (the LAYOUT New + Set flow the panel button drives)."""
    name = str(name).strip()
    if not name:
        return False, "Layout name required"
    if name == "MODEL":
        return False, "MODEL is the model space and cannot be a layout"
    if name in doc.layouts():
        return False, f"Layout already exists: {name}"
    with doc.transaction(f"New layout {name}"):
        doc.add_layout(name)
    return activate_space(doc, name)


def toggle_setting(doc, name) -> Tuple[bool, str]:
    """Flip a bool-style int setting: ORTHO/GRID/SNAP 0↔1, DYNMODE 0↔3
    (contracts §2.5/§5.2). Settings are persisted but NOT journaled —
    UNDO does not revert them (bcdoc §2.5 binding exception)."""
    name = str(name).upper()
    if name not in BOOL_SETTINGS:
        return False, f"Not a toggleable setting: {name}"
    try:
        current = int(doc.settings.get(name))
    except Exception:
        return False, f"Unknown setting: {name}"
    if name == "DYNMODE":
        new_value = 0 if current else 3
    else:
        new_value = 0 if current else 1
    doc.settings.set(name, new_value)
    return True, f"{name}: {new_value}"


def toggle_osnap_bit(doc, bit, mode: str = "") -> Tuple[bool, str]:
    """XOR one OSMODE bit into the running object-snap mask (the Precision
    checkboxes; ``mode`` names the mode in the feedback when known)."""
    try:
        bit = int(bit)
    except (TypeError, ValueError):
        return False, f"Invalid osnap bit: {bit!r}"
    if bit <= 0:
        return False, f"Invalid osnap bit: {bit!r}"
    try:
        current = int(doc.settings.get("OSMODE"))
    except Exception:
        return False, "Unknown setting: OSMODE"
    new_value = current ^ bit
    doc.settings.set("OSMODE", new_value)
    enabled = bool(new_value & bit)
    label = str(mode).strip() or f"osnap bit {bit}"
    return True, f"{label} snap {'enabled' if enabled else 'disabled'} (OSMODE {new_value})"


__all__ = [
    "LAYER_TOGGLE_PROPS",
    "BOOL_SETTINGS",
    "OSNAP_BITS",
    "OSMODE_DEFAULT",
    "set_current_layer",
    "toggle_layer_prop",
    "activate_space",
    "new_layout",
    "toggle_setting",
    "toggle_osnap_bit",
]
