"""Registration surface tests: names, aliases, no collisions (§5 + §1).

The combined registry (bcdraft + bcdraw) is the integration surface —
constructing it without DuplicateCommand errors IS the collision test.
"""

import pytest

import bcdraw
from bccmd import DuplicateCommand, Registry


def test_all_command_names_registered(registry):
    names = bcdraw.command_names()
    assert names == (
        "DIMLINEAR", "DIMALIGNED", "DIMSTYLE", "DIMREGEN", "TEXT", "MTEXT",
        "STYLE", "LAYOUT", "MSPACE", "PSPACE", "MVIEW",
    )
    for name in names:
        assert registry.lookup(name) is not None
        assert registry.lookup(name.lower()) is not None


def test_mview_aliases_resolve():
    registry = bcdraw.register_all(Registry())
    spec = registry.lookup("MVIEW")
    assert registry.lookup("MV") is spec
    assert registry.lookup("mv") is spec
    assert registry.lookup("VIEWPORT") is spec       # contract §5.4 pins it
    assert registry.lookup("VIEWPORTS") is None      # NOT registered (doc'd)


def test_combined_registry_has_no_collisions(registry):
    # bcdraft (M1 set + the M2 drafting/precision commands, owned by W-A/W-D
    # and landing in parallel) + bcdraw (11 commands) coexist — duplicate
    # registration would have raised DuplicateCommand in the fixture. The
    # count is asserted RELATIVE to bcdraft's live surface (other workers
    # add commands mid-flight), not as a hardcoded number.
    import bcdraft

    assert len(registry.names()) == len(bcdraft.COMMANDS) + len(bcdraw.COMMANDS)
    with pytest.raises(DuplicateCommand):
        registry.register(bcdraw.COMMANDS[0])       # DIMLINEAR again


def test_register_all_returns_the_registry():
    registry = Registry()
    assert bcdraw.register_all(registry) is registry


def test_refresh_document_is_reexported():
    from bcdraw.regen import refresh_document as source

    assert bcdraw.refresh_document is source
