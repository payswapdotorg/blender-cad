"""Units-aware value formatting for annotations (m2-module-contracts §5.1).

``format_length`` / ``format_angle`` render measurements using the document
settings (LUNITS/LUPREC, AUNITS/AUPREC — contract §2.5 names are binding).

DOCUMENTED M2 LIMIT (binding per contracts §2.5 + §13): only DECIMAL output
exists at M2. ``LUNITS`` codes other than 2 (1 scientific, 3 engineering,
4 architectural, 5 fractional) and ``AUNITS`` codes other than 0 (1 deg/min/
sec, 2 grads, 3 radians, 4 surveyor units) are ACCEPTED by the settings
store but formatted DECIMAL — architectural/surveyor display stays
"planned" (inventory FP-ANN list, §13 explicit non-claims). No unit
conversion happens: values are drawing units, INSUNITS is machine metadata.

Determinism rules (tests assert EXACT strings):

- rounding is Python format-string rounding — round-half-even over the
  exact binary double (``f"{12.5:.0f}" == "12"``, ``f"{13.5:.0f}" == "14"``);
- precision is clamped to [0, 12] (the settings store accepts any int, a
  negative or absurd precision must still format deterministically);
- negative zero normalizes away (``-0.00001`` at LUPREC 4 -> ``"0.0000"``);
- non-finite input raises ValueError (never renders "nan"/"inf" into a
  drawing).
"""

from __future__ import annotations

import math

#: Bounds applied to LUPREC/AUPREC before formatting (see module docstring).
_PRECISION_MIN = 0
_PRECISION_MAX = 12

_DEFAULT_LUPREC = 4
_DEFAULT_AUPREC = 0


def _precision(settings, name: str, fallback: int) -> int:
    """Read an int precision setting, clamped to the documented bounds."""
    try:
        raw = int(settings.get(name))
    except Exception:  # pragma: no cover - settings validates ints already
        return fallback
    if raw < _PRECISION_MIN:
        return _PRECISION_MIN
    if raw > _PRECISION_MAX:
        return _PRECISION_MAX
    return raw


def _format(value, precision: int) -> str:
    text = f"{float(value):.{precision}f}"
    if text.startswith("-") and float(text) == 0.0:
        text = text[1:]  # normalize "-0.0000" -> "0.0000"
    return text


def format_length(value: float, settings) -> str:
    """Format a length in drawing units per LUNITS/LUPREC (decimal at M2).

    >>> format_length(12.5, settings)          # LUPREC 4 default
    '12.5000'
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"cannot format non-finite length: {value!r}")
    return _format(number, _precision(settings, "LUPREC", _DEFAULT_LUPREC))


def format_angle(value_deg: float, settings) -> str:
    """Format an angle in degrees per AUNITS/AUPREC (decimal at M2).

    No degree symbol is appended (plain decimal text, matching the Dim
    entity's unit-free value storage; presentation symbols are GUI work).

    >>> format_angle(30.0, settings)            # AUPREC 0 default
    '30'
    """
    number = float(value_deg)
    if not math.isfinite(number):
        raise ValueError(f"cannot format non-finite angle: {value_deg!r}")
    return _format(number, _precision(settings, "AUPREC", _DEFAULT_AUPREC))


__all__ = ["format_length", "format_angle"]
