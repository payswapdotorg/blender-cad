"""Input parsing tests — contract §4.4 forms + error cases (TP-CAT-01)."""

import pytest

from bccmd import InputValue, Point, Request, parse, InputParseError
from bccmd.input import match_keyword


def _req(kind, options=(), default=None):
    return Request(kind=kind, prompt="test", options=list(options), default=default)


PT = Point(10.0, 20.0, 0.0)  # last point for relative forms


# -- absolute coordinates ------------------------------------------------------

def test_absolute_xy():
    v = parse("12,34", _req("point"))
    assert v.kind == "point"
    assert v.value == Point(12.0, 34.0, 0.0)
    assert v.raw == "12,34"


def test_absolute_xyz():
    v = parse("12,34,5", _req("point"))
    assert v.value == Point(12.0, 34.0, 5.0)


def test_absolute_polar_from_origin():
    v = parse("5<30", _req("point"))
    assert v.value.x == pytest.approx(5 * 0.8660254, abs=1e-6)
    assert v.value.y == pytest.approx(2.5, abs=1e-6)


def test_negative_coordinates():
    v = parse("-3,-4", _req("point"))
    assert v.value == Point(-3.0, -4.0, 0.0)


# -- relative coordinates -------------------------------------------------------

def test_relative_xy():
    v = parse("@3,4", _req("point"), last_point=PT)
    assert v.value == Point(13.0, 24.0, 0.0)


def test_relative_xyz():
    v = parse("@3,4,5", _req("point"), last_point=PT)
    assert v.value == Point(13.0, 24.0, 5.0)


def test_relative_polar():
    v = parse("@5<30", _req("point"), last_point=PT)
    assert v.value.x == pytest.approx(10 + 5 * 0.8660254, abs=1e-6)
    assert v.value.y == pytest.approx(20 + 2.5, abs=1e-6)


def test_at_alone_repeats_last_point():
    v = parse("@", _req("point"), last_point=PT)
    assert v.value == PT


def test_relative_without_last_point_is_error():
    with pytest.raises(InputParseError):
        parse("@3,4", _req("point"), last_point=None)


# -- distances / angles ---------------------------------------------------------

def test_plain_number_distance():
    v = parse("42", _req("distance"))
    assert v.kind == "distance"
    assert v.value == 42.0


def test_plain_number_angle():
    v = parse("42", _req("angle"))
    assert v.kind == "angle"
    assert v.value == 42.0


def test_negative_distance_allowed():
    v = parse("-7.5", _req("distance"))
    assert v.value == -7.5


def test_lone_number_at_point_prompt_is_error():
    with pytest.raises(InputParseError):
        parse("42", _req("point"))


def test_coordinate_at_distance_prompt_uses_last_point():
    v = parse("13,24", _req("distance"), last_point=PT)  # 3,4 away
    assert v.kind == "distance"
    assert v.value == pytest.approx(5.0)


def test_coordinate_at_angle_prompt_uses_last_point():
    v = parse("20,30", _req("angle"), last_point=PT)  # +10,+10 → 45°
    assert v.kind == "angle"
    assert v.value == pytest.approx(45.0)


# -- keywords -------------------------------------------------------------------

def test_keyword_prefix_match():
    v = parse("c", _req("point", options=["Close", "Undo"]))
    assert v.kind == "keyword"
    assert v.value == "Close"


def test_keyword_significant_uppercase():
    assert match_keyword("u", ["Close", "Undo"]) == "Undo"
    assert match_keyword("c", ["Close", "Undo"]) == "Close"
    assert match_keyword("e", ["Exit"]) == "Exit"


def test_keyword_full_word_and_case_insensitive():
    assert match_keyword("close", ["Close"]) == "Close"
    assert match_keyword("UNDO", ["Undo"]) == "Undo"


def test_keyword_ambiguity_is_no_match():
    assert match_keyword("c", ["Copy", "Close"]) is None
    # more characters disambiguate
    assert match_keyword("cl", ["Copy", "Close"]) == "Close"


def test_unknown_keyword_at_option_prompt_rejected():
    with pytest.raises(InputParseError):
        parse("z", _req("point", options=["Close", "Undo"]))


def test_options_only_on_keyword_like_input():
    # a coordinate still parses as a coordinate even when options exist
    v = parse("1,2", _req("point", options=["Close"]))
    assert v.kind == "point"


# -- empty input / defaults --------------------------------------------------------

def test_empty_input_accepts_string_default():
    v = parse("", _req("point", default="Exit"))
    assert v.kind == "keyword"
    assert v.value == "Exit"


def test_empty_input_accepts_numeric_default():
    v = parse("", _req("distance", default=2.5))
    assert v.kind == "distance"
    assert v.value == 2.5


def test_empty_input_at_point_prompt_is_enter_keyword():
    v = parse("", _req("point"))
    assert v.kind == "keyword"
    assert v.value == "Enter"


def test_empty_input_at_selection_prompt_is_enter_keyword():
    v = parse("", _req("selection"))
    assert v.kind == "keyword"
    assert v.value == "Enter"


def test_empty_input_at_distance_prompt_without_default_is_error():
    with pytest.raises(InputParseError):
        parse("", _req("distance"))


# -- malformed text ---------------------------------------------------------------

@pytest.mark.parametrize("bad", ["abc", "12,", ",5", "1,,2", "@x,y", "5<", "<30", "1,2,3,4", "nan,1"])
def test_malformed_inputs_raise(bad):
    with pytest.raises(InputParseError):
        parse(bad, _req("point"), last_point=PT)


def test_string_request_returns_string():
    v = parse("hello world", _req("string"))
    assert v.kind == "string"
    assert v.value == "hello world"


def test_selection_request_rejects_text():
    with pytest.raises(InputParseError):
        parse("some text", _req("selection"))
