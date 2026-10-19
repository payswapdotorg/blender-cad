"""Settings / system variables (contract: m2-module-contracts.md §2.5).

The M2 registry mirrors AutoCAD sysvar names (binding). ``Settings`` is a
typed store over :data:`SETTING_DEFS`:

- ``get``/``set`` (plus ``__getitem__``/``__setitem__`` for the
  ``doc.settings["OSMODE"]`` access style used by bcdraft/bcdraw);
- unknown names raise :class:`errors.UnknownSetting`;
- type mismatches raise :class:`errors.InvalidSettingValue`
  (ints accept ints but not bools; floats accept ints and floats but not
  bools; non-finite floats are rejected — they cannot round-trip JSON);
- ``choices`` entries (where pinned) restrict the value set.

UNDO POLICY EXCEPTION (binding, documented): settings are document state
that is PERSISTED (the ``settings`` key of bcdoc/2) but NOT journaled and
NOT rolled back — UNDO does not revert sysvars, matching AutoCAD for
out-of-command changes. Consequently a failed transaction deliberately
leaves settings changes made inside it applied (everything else —
entities, layers, blocks, layouts, styles — rolls back bit-identically).
"""

from __future__ import annotations

import math

from . import errors

#: M2 registry — names, types and defaults are binding (contract §2.5).
#: ``help`` strings are the one-line notes from the contract table.
SETTING_DEFS: dict = {
    "CLAYER": {
        "type": "str", "default": "0",
        "help": "current layer (must exist when used)",
    },
    "OSMODE": {
        "type": "int", "default": 55,
        "help": "object-snap bitmask: 1 END, 2 MID, 4 CEN, 16 QUA, "
                "32 INT, 128 PER, 1024 TAN; 0 = none",
    },
    "ORTHOMODE": {
        "type": "int", "default": 0, "choices": [0, 1],
        "help": "ortho constraint on/off",
    },
    "SNAPMODE": {
        "type": "int", "default": 0, "choices": [0, 1],
        "help": "grid snap on/off",
    },
    "SNAPUNIT": {
        "type": "float", "default": 1.0,
        "help": "rectangular grid snap spacing (drawing units)",
    },
    "GRIDMODE": {
        "type": "int", "default": 0, "choices": [0, 1],
        "help": "display grid toggle (shell-side)",
    },
    "GRIDUNIT": {
        "type": "float", "default": 10.0,
        "help": "display grid spacing",
    },
    "APERTURE": {
        "type": "float", "default": 0.5,
        "help": "osnap aperture in DRAWING units (zoom-scaled presentation "
                "is later GUI work)",
    },
    "DYNMODE": {
        "type": "int", "default": 3,
        "help": "dynamic input toggle (3 on, 0 off)",
    },
    "PICKFIRST": {
        "type": "int", "default": 1, "choices": [0, 1],
        "help": "noun-verb selection",
    },
    "TILEMODE": {
        "type": "int", "default": 1, "choices": [0, 1],
        "help": "1 = model space active, 0 = paper space",
    },
    "INSUNITS": {
        "type": "int", "default": 0,
        "help": "machine units, DXF $INSUNITS codes "
                "(0 unitless, 1 inches, 2 feet, 4 mm, 5 cm, 6 m, …)",
    },
    "LUNITS": {
        "type": "int", "default": 2,
        "help": "length display format (2 = decimal); other codes are "
                "accepted and formatted decimal (documented)",
    },
    "LUPREC": {
        "type": "int", "default": 4,
        "help": "length display precision",
    },
    "AUNITS": {
        "type": "int", "default": 0,
        "help": "angle display format (0 = decimal); other codes are "
                "accepted and formatted decimal (documented)",
    },
    "AUPREC": {
        "type": "int", "default": 0,
        "help": "angle display precision",
    },
    "TEXTSTYLE": {
        "type": "str", "default": "Standard",
        "help": "current text style",
    },
    "DIMSTYLE": {
        "type": "str", "default": "Standard",
        "help": "current dimension style",
    },
    "LTSCALE": {
        "type": "float", "default": 1.0,
        "help": "linetype scale (stored; display application is M3)",
    },
}


def _coerce_value(name: str, value):
    """Type- and choices-validate one raw value (contract §2.5)."""
    definition = SETTING_DEFS[name]
    stype = definition["type"]
    if stype == "int":
        # ints accept ints, bools excluded (bool is an int subclass)
        if isinstance(value, bool) or not isinstance(value, int):
            raise errors.InvalidSettingValue(name, value, "expected an int")
        coerced = value
    elif stype == "float":
        # floats accept ints and floats, bools excluded; must be finite
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise errors.InvalidSettingValue(name, value, "expected a number")
        coerced = float(value)
        if not math.isfinite(coerced):
            raise errors.InvalidSettingValue(name, value, "must be finite")
    else:  # str
        if not isinstance(value, str):
            raise errors.InvalidSettingValue(name, value, "expected a string")
        coerced = value
    choices = definition.get("choices")
    if choices is not None and coerced not in choices:
        raise errors.InvalidSettingValue(
            name, value, f"expected one of {choices}")
    return coerced


class Settings:
    """Typed sysvar store over :data:`SETTING_DEFS` (contract §2.5)."""

    def __init__(self):
        self._values: dict = {name: definition["default"]
                              for name, definition in SETTING_DEFS.items()}

    # -- reads ---------------------------------------------------------------
    def get(self, name: str):
        if name not in SETTING_DEFS:
            raise errors.UnknownSetting(name)
        return self._values[name]

    def names(self) -> list:
        """Registered setting names in registry order."""
        return list(SETTING_DEFS)

    def definitions(self) -> dict:
        """The registry (read-only by convention; shared dict)."""
        return SETTING_DEFS

    def items(self):
        """(name, value) pairs in registry order."""
        return [(name, self._values[name]) for name in SETTING_DEFS]

    def __contains__(self, name) -> bool:
        return name in SETTING_DEFS

    def __getitem__(self, name: str):
        return self.get(name)

    def __iter__(self):
        return iter(SETTING_DEFS)

    def __len__(self) -> int:
        return len(SETTING_DEFS)

    # -- writes --------------------------------------------------------------
    def set(self, name: str, value):
        """Validate + store one value (NOT journaled — see module docstring)."""
        if name not in SETTING_DEFS:
            raise errors.UnknownSetting(name)
        self._values[name] = _coerce_value(name, value)

    def __setitem__(self, name: str, value):
        self.set(name, value)

    # -- serialization ---------------------------------------------------------
    def to_json(self) -> dict:
        """JSON-safe dict in registry order (byte-stable)."""
        return {name: self._values[name] for name in SETTING_DEFS}

    def from_json(self, data: dict) -> "Settings":
        """Adopt a persisted settings dict (tolerant: missing keys keep the
        defaults; unknown names and bad values raise — serialize.parse
        wraps those into SerializationError for loads)."""
        if not isinstance(data, dict):
            raise errors.InvalidSettingValue(
                "<settings>", data, "expected a JSON object")
        for name, value in data.items():
            if name not in SETTING_DEFS:
                raise errors.UnknownSetting(name)
        # validate everything first (no partial apply)
        coerced = {name: _coerce_value(name, value)
                   for name, value in data.items()}
        self._values.update(coerced)
        return self

    def copy(self) -> "Settings":
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        clone._values = dict(self._values)
        return clone

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Settings {self.to_json()!r}>"
