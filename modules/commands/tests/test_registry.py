"""Registry tests — lookup, alias, collision, hook (TP-CAT-01)."""

import pytest

from bccmd import (
    CommandResult,
    CommandSpec,
    DuplicateCommand,
    Registry,
    UnknownCommand,
)


def _spec(name, aliases=()):
    def run(ctx, runner):  # pragma: no cover - never invoked here
        return CommandResult(status="ok", summary="done")

    return CommandSpec(name=name, aliases=list(aliases), run=run)


def test_register_and_lookup_name():
    reg = Registry()
    reg.register(_spec("LINE", ["L"]))
    assert reg.lookup("LINE") is reg.lookup("line")
    assert reg.lookup("l").name == "LINE"
    assert reg.lookup("  Line ") is not None
    assert reg.lookup("NOSUCH") is None


def test_alias_lookup_case_insensitive():
    reg = Registry()
    reg.register(_spec("CIRCLE", ["C"]))
    assert reg.lookup("c").name == "CIRCLE"


def test_duplicate_name_rejected():
    reg = Registry()
    reg.register(_spec("MOVE"))
    with pytest.raises(DuplicateCommand):
        reg.register(_spec("Move"))


def test_duplicate_alias_rejected():
    reg = Registry()
    reg.register(_spec("LINE", ["L"]))
    with pytest.raises(DuplicateCommand):
        reg.register(_spec("LAYER", ["L"]))


def test_alias_colliding_with_existing_name_rejected():
    reg = Registry()
    reg.register(_spec("ERASE"))
    with pytest.raises(DuplicateCommand):
        reg.register(_spec("ZAP", ["Erase"]))


def test_name_colliding_with_existing_alias_rejected():
    reg = Registry()
    reg.register(_spec("LINE", ["L"]))
    with pytest.raises(DuplicateCommand):
        reg.register(_spec("L"))


def test_names_and_specs_in_registration_order():
    reg = Registry()
    reg.register(_spec("A"))
    reg.register(_spec("B"))
    reg.register(_spec("C", ["c2"]))
    assert reg.names() == ["A", "B", "C"]
    assert [s.name for s in reg.specs()] == ["A", "B", "C"]


def test_completions_prefix_matches_names_and_aliases():
    reg = Registry()
    reg.register(_spec("LINE", ["L"]))
    reg.register(_spec("LTSCALE"))
    assert reg.completions("L") == ["L", "LINE", "LTSCALE"]
    assert reg.completions("Z") == []


def test_register_hook_present_unused():
    reg = Registry()
    assert reg.hooks == {}
    marker = []
    reg.register_hook("skills", lambda: marker.append(1))
    assert list(reg.hooks) == ["skills"]
    for callback in reg.hooks["skills"]:
        callback()
    assert marker == [1]


def test_run_command_unknown_raises():
    reg = Registry()
    with pytest.raises(UnknownCommand):
        reg.run_command(None, "NOSUCH", provider=None)


def test_spec_requires_run_or_steps():
    with pytest.raises(ValueError):
        CommandSpec(name="X")
    with pytest.raises(ValueError):
        CommandSpec(name="")


def test_spec_name_normalized_upper():
    spec = _spec("line")
    assert spec.name == "LINE"
    assert spec.aliases == []
