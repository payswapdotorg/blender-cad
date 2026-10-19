"""Registry.suggestions (M2 contract §3) + the M2 input-parse forms:
osnap one-shot tokens, direct distance entry, source passthrough — plus an
M1 regression sweep of every parse behavior the M2 changes touch (contracts
§10 row: "source flag, suggestions, osnap tokens, DDE parsing").
"""

import pytest

from bccmd import (
    CommandSpec,
    InputValue,
    InputParseError,
    Point,
    Registry,
    Request,
    angle_input,
    distance_input,
    keyword_input,
    osnap_tokens,
    parse,
    point_input,
    selection_input,
)


def _req(kind, options=(), default=None):
    return Request(kind=kind, prompt="test", options=list(options), default=default)


PT = Point(10.0, 20.0, 0.0)


def _reg(*specs):
    registry = Registry()
    for spec in specs:
        registry.register(spec)
    return registry


def _spec(name, aliases=(), help_text=""):
    return CommandSpec(
        name=name, aliases=list(aliases), run=lambda ctx, runner: None,
        help=help_text or f"help for {name}",
    )


# ---------------------------------------------------------------------------
# Registry.suggestions — ranking, aliases, stability
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry():
    return _reg(
        _spec("LINE", ["L"], "chained line segments"),
        _spec("CIRCLE", ["C"], "full circle"),
        _spec("COPY", ["CO"], "duplicate objects"),
        _spec("MOVE", ["M"], "displace objects"),
        _spec("XLINE", ["XL"], "infinite construction line"),
        _spec("DIMLINEAR", ["DLI"], "linear dimension"),
    )


def test_suggestions_prefix_matches_case_insensitive(registry):
    # "L" is also CONTAINED in CIRCLE/XLINE/DIMLINEAR — those rank after
    # the exact-prefix match (LINE); the lowercase form is identical.
    low = [name for name, _ in registry.suggestions("l")]
    assert low[0] == "LINE"
    assert low == [name for name, _ in registry.suggestions("L")]
    # a prefix that matches nothing by containment is exact
    only = _reg(_spec("LINE", ["L"]), _spec("COPY", ["CO"]))
    assert [name for name, _ in only.suggestions("L")] == ["LINE"]


def test_suggestions_exact_prefix_matches_before_contains(registry):
    # DRILL would be a contains-match; register one to prove the ordering
    registry.register(_spec("DRILL", [], "drill down"))
    names = [name for name, _ in registry.suggestions("D")]
    assert names[0] == "DIMLINEAR"
    assert "DRILL" in names
    assert names.index("DIMLINEAR") < names.index("DRILL")


def test_suggestions_names_then_aliases_in_registration_order(registry):
    names = [name for name, _ in registry.suggestions("C")]
    assert names == ["CIRCLE", "COPY"]  # both canonical; registration order


def test_suggestions_alias_reports_canonical_name(registry):
    suggestions = registry.suggestions("XL")
    assert suggestions == [("XLINE", "infinite construction line")]
    # a pure-alias prefix whose canonical name does NOT start with it
    assert [name for name, _ in registry.suggestions("DLI")] == ["DIMLINEAR"]


def test_suggestions_dedup_alias_and_canonical(registry):
    # "M" matches the canonical MOVE and the alias M -> MOVE collapses to
    # one entry (the small registry avoids accidental contains-matches)
    only = _reg(_spec("MOVE", ["M"]), _spec("COPY", ["CO"]))
    assert [name for name, _ in only.suggestions("M")] == ["MOVE"]


def test_suggestions_limit_truncates(registry):
    registry.register(_spec("LAYER"))
    registry.register(_spec("LAYOUT"))
    all_la = [name for name, _ in registry.suggestions("LA", limit=99)]
    assert all_la == ["LAYER", "LAYOUT"]  # registration order, no others
    assert [name for name, _ in registry.suggestions("LA", limit=1)] == ["LAYER"]
    assert [name for name, _ in registry.suggestions("LA", limit=2)] == [
        "LAYER", "LAYOUT",
    ]


def test_suggestions_limit_zero_is_empty(registry):
    assert registry.suggestions("L", limit=0) == []


def test_suggestions_empty_prefix_returns_first_names(registry):
    assert [name for name, _ in registry.suggestions("")] == [
        "LINE", "CIRCLE", "COPY", "MOVE", "XLINE", "DIMLINEAR",
    ]
    limited = registry.suggestions("", limit=2)
    assert [name for name, _ in limited] == ["LINE", "CIRCLE"]


def test_suggestions_unknown_prefix_is_empty(registry):
    assert registry.suggestions("ZZZ") == []


def test_suggestions_pairs_carry_help(registry):
    suggestions = registry.suggestions("CIR")
    assert suggestions == [("CIRCLE", "full circle")]


def test_suggestions_stable_order_repeated_calls(registry):
    assert registry.suggestions("C") == registry.suggestions("C")
    assert registry.suggestions("c") == registry.suggestions("C")


def test_suggestions_default_limit_is_eight(registry):
    for name in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"):
        registry.register(_spec(name))
    assert len(registry.suggestions("A")) == 8
    assert [name for name, _ in registry.suggestions("A")][0] == "A1"


# ---------------------------------------------------------------------------
# parse(): osnap one-shot tokens (point requests only, after option matching)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("END", "osnap:ENDPOINT"),
    ("ENDP", "osnap:ENDPOINT"),
    ("endpoint", "osnap:ENDPOINT"),
    ("MID", "osnap:MIDPOINT"),
    ("CEN", "osnap:CENTER"),
    ("QUA", "osnap:QUADRANT"),
    ("INT", "osnap:INTERSECTION"),
    ("TAN", "osnap:TANGENT"),
    ("PER", "osnap:PERPENDICULAR"),
    ("INS", "osnap:INSERTION"),
    ("END,MID", "osnap:ENDPOINT,MIDPOINT"),
    ("mid,cen", "osnap:MIDPOINT,CENTER"),
    ("END,END", "osnap:ENDPOINT"),          # duplicates collapse
    ("END,BOGUS", "osnap:ENDPOINT"),        # unknown pieces skipped
])
def test_parse_osnap_tokens(token, expected):
    value = parse(token, _req("point"))
    assert value.kind == "keyword"
    assert value.value == expected
    assert value.raw == token


def test_parse_osnap_token_only_at_point_requests():
    with pytest.raises(InputParseError):
        parse("END", _req("distance"))
    with pytest.raises(InputParseError):
        parse("MID", _req("angle"))
    with pytest.raises(InputParseError):
        parse("CEN", _req("selection"))


def test_parse_osnap_token_after_option_matching():
    # an option that shadows the token wins (option matching comes first)
    value = parse("cen", _req("point", options=["Center"]))
    assert value.kind == "keyword"
    assert value.value == "Center"
    # options present but not matching -> the osnap token fires
    value = parse("cen", _req("point", options=["Close", "Undo"]))
    assert value.value == "osnap:CENTER"


def test_parse_osnap_ambiguity_with_option_prefix():
    # "end" does not prefix-match any option, so the osnap reading applies
    value = parse("end", _req("point", options=["Undo"]))
    assert value.value == "osnap:ENDPOINT"


def test_osnap_tokens_helper():
    assert osnap_tokens("END,mid") == ["ENDPOINT", "MIDPOINT"]
    assert osnap_tokens("  qua , TAN ") == ["QUADRANT", "TANGENT"]
    assert osnap_tokens("none") == []       # not a token (OSNAP cmd handles it)
    assert osnap_tokens("xyz") == []
    assert osnap_tokens("") == []


# ---------------------------------------------------------------------------
# parse(): direct distance entry (plain number at a point request)
# ---------------------------------------------------------------------------

def test_parse_plain_number_at_point_with_last_point_is_dde():
    value = parse("25", _req("point"), last_point=PT)
    assert value.kind == "distance"
    assert value.value == 25.0
    assert value.source == "typed"
    assert value.raw == "25"


def test_parse_plain_number_at_point_without_last_point_is_m1_error():
    with pytest.raises(InputParseError, match="two coordinates"):
        parse("42", _req("point"), last_point=None)


def test_parse_negative_number_at_point_is_negative_distance():
    value = parse("-7.5", _req("point"), last_point=PT)
    assert value.kind == "distance"
    assert value.value == -7.5


# ---------------------------------------------------------------------------
# parse(): M1 regression sweep for every touched path
# ---------------------------------------------------------------------------

def test_regression_plain_numbers_per_request_kind():
    assert parse("42", _req("distance")).kind == "distance"
    assert parse("42", _req("distance")).value == 42.0
    assert parse("42", _req("angle")).kind == "angle"
    assert parse("abc", _req("string")).value == "abc"


def test_regression_point_forms_unchanged():
    assert parse("12,34", _req("point")).value == Point(12.0, 34.0, 0.0)
    assert parse("12,34,5", _req("point")).value == Point(12.0, 34.0, 5.0)
    assert parse("5<30", _req("point")).value.x == pytest.approx(4.330127, abs=1e-6)
    assert parse("@3,4", _req("point"), last_point=PT).value == Point(13.0, 24.0, 0.0)
    assert parse("@", _req("point"), last_point=PT).value == PT
    assert parse("-3,-4", _req("point")).value == Point(-3.0, -4.0, 0.0)


def test_regression_keywords_and_enter():
    value = parse("c", _req("point", options=["Close", "Undo"]))
    assert value.value == "Close"
    assert parse("", _req("point")).value == "Enter"
    assert parse("", _req("point", default="Exit")).value == "Exit"


def test_regression_malformed_inputs_raise():
    for bad in ("abc", "12,", "1,2,3,4", "<30"):
        with pytest.raises(InputParseError):
            parse(bad, _req("point"), last_point=PT)


def test_regression_unknown_keyword_with_options_raises():
    with pytest.raises(InputParseError):
        parse("z", _req("point", options=["Close", "Undo"]))


# ---------------------------------------------------------------------------
# InputValue source flag + factory passthrough
# ---------------------------------------------------------------------------

def test_inputvalue_source_defaults_to_typed():
    assert InputValue(kind="point", value=Point(0, 0)).source == "typed"


def test_point_input_source_passthrough():
    assert point_input(1.0, 2.0).source == "typed"
    mouse = point_input(1.0, 2.0, source="mouse")
    assert mouse.source == "mouse"
    assert mouse.kind == "point"
    assert mouse.value == Point(1.0, 2.0, 0.0)
    z_mouse = point_input(1, 2, 3, source="mouse")
    assert z_mouse.value == Point(1.0, 2.0, 3.0)


def test_factory_source_passthrough_all_kinds():
    assert distance_input(5).source == "typed"
    assert distance_input(5, source="mouse").source == "mouse"
    assert angle_input(90).source == "typed"
    assert angle_input(90, source="mouse").source == "mouse"
    assert keyword_input("Close").source == "typed"
    assert keyword_input("Enter", source="mouse").source == "mouse"
    assert selection_input(["a", "b"]).source == "typed"
    assert selection_input([], source="mouse").source == "mouse"
