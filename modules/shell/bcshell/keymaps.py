"""bcshell.keymaps — extension-owned keymap: Ctrl+Space → command line.

The keymap lives under ``window_manager.keyconfigs.addon`` under the
extension-owned name "BlenderCAD" so ``unregister()`` can remove exactly
what ``register()`` added (TP-CAT-06 clean unload). When no addon keyconfig
exists (some headless contexts), registration degrades to a no-op and the
panel buttons keep the command line reachable.
"""

from __future__ import annotations

KEYCONFIG_NAME = "BlenderCAD"
KEYMAP_NAME = "BlenderCAD Window"
OPERATOR_ID = "bcshell.cmdline"

_keyconfig = None
_keymap = None


def register_keymaps():
    """Ctrl+Space (Window context) opens the command line (ux-spec §3.1)."""
    global _keyconfig, _keymap
    import bpy

    window_manager = bpy.context.window_manager
    addon_configs = getattr(window_manager.keyconfigs, "addon", None)
    if addon_configs is None:
        _keyconfig = None
        _keymap = None
        return False  # headless fallback: no addon keyconfig available
    _keyconfig = addon_configs
    _keymap = addon_configs.keymaps.new(name=KEYMAP_NAME, space_type="EMPTY")
    _keymap.keymap_items.new(OPERATOR_ID, "SPACE", "PRESS", ctrl=True)
    return True


def unregister_keymaps():
    """Remove the extension keymap (idempotent, twice-safe)."""
    global _keyconfig, _keymap
    try:
        if _keyconfig is not None and _keymap is not None:
            _keyconfig.keymaps.remove(_keymap)
    except Exception:
        pass  # already gone / keyconfig freed — clean unload must not fail
    finally:
        _keymap = None
        _keyconfig = None


def active_keymap_name():
    """Diagnostics + tests: the keymap name when registered, else None."""
    return KEYMAP_NAME if _keymap is not None else None
