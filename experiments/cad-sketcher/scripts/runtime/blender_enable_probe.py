"""Blender-side enable probe: run INSIDE Blender (--background --python) after the
CAD_Sketcher extension was installed into the isolated BLENDER_USER_RESOURCES dir.

Checks: (a) the extension module is enabled at startup, (b) its bundled slvs wheel
is importable from within Blender (sys.path wiring by the extension system),
(c) the addon's key operators/property groups are registered.

Usage:
    blender --background --python blender_enable_probe.py -- <out.json>

Writes the evidence record to <out.json>; sets exit code 0 only if all checks pass.
"""

import json
import sys

import bpy  # noqa: F401  (this file only ever runs inside Blender)

MODULE = "bl_ext.user_default.CAD_Sketcher"


def main(out_path):
    checks = []

    def record(name, passed, detail=""):
        checks.append({"check": name, "pass": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}  {detail}")

    import addon_utils

    enabled_mods = [m.__name__ for m in addon_utils.modules() if addon_utils.check(m.__name__)[0]]
    record("extension.enabled", MODULE in enabled_mods,
           f"{MODULE} in enabled modules: {MODULE in enabled_mods}; "
           f"bl_ext modules seen: {[m.__name__ for m in addon_utils.modules() if m.__name__.startswith('bl_ext')]}")

    # addon version as Blender sees it
    try:
        mod = addon_utils.modules()[0].__class__  # placeholder to keep flake quiet
    except Exception:
        pass
    try:
        import importlib
        m = importlib.import_module(MODULE)
        version = tuple(addon_utils.module_bl_info(m).get("version", ()))
    except Exception as e:  # noqa: BLE001
        version = ()
        record("extension.import", False, f"import {MODULE} failed: {e!r}")
    else:
        record("extension.import", True, f"{MODULE} imported; version tuple {version}")

    # the bundled solver wheel must be importable from within Blender
    try:
        import slvs
        record("solver.import_in_blender", True, f"slvs from {slvs.__path__[0]}")
    except Exception as e:  # noqa: BLE001
        record("solver.import_in_blender", False, f"import slvs failed: {e!r}")

    # key operators registered by the addon (declarations.py: Operators enum)
    op_checks = {
        "add_sketch": hasattr(bpy.ops.view3d, "slvs_add_sketch"),
        "add_point2d": hasattr(bpy.ops.view3d, "slvs_add_point2d"),
        "add_line2d": hasattr(bpy.ops.view3d, "slvs_add_line2d"),
        "add_circle2d": hasattr(bpy.ops.view3d, "slvs_add_circle2d"),
        "add_coincident": hasattr(bpy.ops.view3d, "slvs_add_coincident"),
        "add_horizontal": hasattr(bpy.ops.view3d, "slvs_add_horizontal"),
        "add_distance": hasattr(bpy.ops.view3d, "slvs_add_distance"),
        "solve": hasattr(bpy.ops.view3d, "slvs_solve"),
    }
    record("operators.registered", all(op_checks.values()),
           ", ".join(f"{k}={v}" for k, v in op_checks.items()))

    # scene-level property groups registered (model/group_sketcher.py)
    record("scene.sketcher_prop", hasattr(bpy.types.Scene, "sketcher"),
           f"bpy.types.Scene.sketcher exists: {hasattr(bpy.types.Scene, 'sketcher')}")

    record("blender.version", True, bpy.app.version_string)

    result = {
        "driver": "blender_enable_probe.py",
        "blender": bpy.app.version_string,
        "module": MODULE,
        "module_version": list(version) if version else None,
        "checks": checks,
        "all_passed": all(c["pass"] for c in checks),
    }
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:]
    sys.exit(main(argv[0]))
