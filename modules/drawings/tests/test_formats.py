"""Exact-string formatting tests for bcdraw.formats (contracts §5.1).

Every assertion is an EXACT string: the formatting rules are pinned
(round-half-even over the binary double, precision clamp [0, 12],
negative-zero normalization, decimal-only at M2 — documented limits).
"""

import pytest

from bcdraw.formats import format_angle, format_length


def settings(**changes):
    """A Settings object with the given overrides (defaults per §2.5)."""
    from bcdoc.settings import Settings

    store = Settings()
    for name, value in changes.items():
        store.set(name, value)
    return store


# ---------------------------------------------------------------------------
# format_length
# ---------------------------------------------------------------------------

def test_length_default_luprec_4():
    assert format_length(12.5, settings()) == "12.5000"
    assert format_length(0.0, settings()) == "0.0000"
    assert format_length(10.0, settings()) == "10.0000"


def test_length_luprec_variants():
    assert format_length(12.5, settings(LUPREC=0)) == "12"  # half-even
    assert format_length(12.5, settings(LUPREC=2)) == "12.50"
    assert format_length(12.5, settings(LUPREC=8)) == "12.50000000"
    assert format_length(-3.25, settings(LUPREC=1)) == "-3.2"  # half-even
    assert format_length(-3.35, settings(LUPREC=1)) == "-3.4"


def test_length_round_half_even_on_exact_halves():
    # 2.5 / 3.5 are exact binary doubles -> the pinned Python behaviour
    assert format_length(2.5, settings(LUPREC=0)) == "2"
    assert format_length(3.5, settings(LUPREC=0)) == "4"
    assert format_length(0.125, settings(LUPREC=2)) == "0.12"
    assert format_length(0.375, settings(LUPREC=2)) == "0.38"


def test_length_negative_zero_normalizes():
    assert format_length(-0.00001, settings(LUPREC=4)) == "0.0000"
    assert format_length(-0.0, settings(LUPREC=4)) == "0.0000"
    assert format_length(-1.0, settings(LUPREC=4)) == "-1.0000"


def test_length_nondecimal_lunits_still_decimal_documented_limit():
    # LUNITS 1 (scientific) / 4 (architectural) are ACCEPTED but formatted
    # decimal at M2 (documented limit, module docstring + contract §2.5).
    assert format_length(12.5, settings(LUNITS=1)) == "12.5000"
    assert format_length(12.5, settings(LUNITS=4, LUPREC=3)) == "12.500"


def test_length_precision_is_clamped():
    assert format_length(12.5, settings(LUPREC=25)) == "12.500000000000"
    assert format_length(12.5, settings(LUPREC=-5)) == "12"  # clamp to 0, half-even


def test_length_rejects_non_finite():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            format_length(bad, settings())


# ---------------------------------------------------------------------------
# format_angle
# ---------------------------------------------------------------------------

def test_angle_default_auprec_0():
    assert format_angle(30.0, settings()) == "30"
    assert format_angle(0.0, settings()) == "0"
    assert format_angle(357.5, settings()) == "358"  # half-even on the double


def test_angle_auprec_variants():
    assert format_angle(30.0, settings(AUPREC=1)) == "30.0"
    assert format_angle(30.0, settings(AUPREC=2)) == "30.00"
    assert format_angle(-45.25, settings(AUPREC=1)) == "-45.2"  # half-even


def test_angle_nondecimal_aunits_still_decimal_documented_limit():
    assert format_angle(30.0, settings(AUNITS=1)) == "30"
    assert format_angle(30.0, settings(AUNITS=3, AUPREC=2)) == "30.00"


def test_angle_negative_zero_normalizes():
    assert format_angle(-0.2, settings(AUPREC=0)) == "0"
    assert format_angle(-0.04, settings(AUPREC=1)) == "0.0"


def test_angle_no_degree_symbol():
    # plain decimal text (presentation symbols are GUI work)
    assert "°" not in format_angle(90.0, settings(AUPREC=2))
