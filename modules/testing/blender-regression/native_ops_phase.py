"""TP-CAT-06 native ops phase — runs INSIDE Blender.

Runs a fixed list of stock-Blender operations (no CAD involvement) and records
per-op success. If the extension is present and enabled (the "loaded" run), it
also records registration state and performs a clean unload.

argv after "--": <result_json> <label>
"""

import json
import sys
import time
from pathlib import Path

import bpy  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(argv[0])
LABEL = argv[1] if len(argv) > 1 else "?"


def op(name, fn):
    t0 = time.time()
    try:
        fn()
        return {"op": name, "ok": True, "ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"op": name, "ok": False, "ms": int((time.time() - t0) * 1000), "error": repr(e)[:200]}


def native_ops():
    ops = []

    def add_mesh():
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))

    def add_cyl():
        bpy.ops.mesh.primitive_cylinder_add(location=(3, 0, 0), radius=1, depth=2)

    def transform():
        o = bpy.context.scene.objects[-1] if bpy.context.scene.objects else None
        o.location = (5, 5, 5)
        o.rotation_euler = (0.2, 0.4, 0.6)
        o.scale = (1.5, 1.5, 1.5)
        bpy.context.view_layer.update()

    def material():
        mat = bpy.data.materials.new("tcat06_mat")
        o = bpy.context.scene.objects[-1]
        o.data.materials.append(mat)

    def curve_native():
        cu = bpy.data.curves.new("tcat06_curve", type="CURVE")
        cu.dimensions = "3D"
        spline = cu.splines.new("POLY")
        spline.points.add(3)
        for i, co in enumerate([(0, 0, 0), (1, 2, 0), (2, 0, 0)]):
            spline.points[i].co = (*co, 1)
        ob = bpy.data.objects.new("tcat06_curve", cu)
        bpy.context.scene.collection.objects.link(ob)

    def modifier_add():
        # data-API modifier add (window-context-free). NOTE: Blender's global
        # undo operators (ed.undo/redo) poll-fail in --background mode (window
        # context required) — identical in stock and loaded runs; recorded as an
        # environment limitation in the battery result, NOT a regression. The
        # CAD document's own undo system is covered by the pytest suites.
        ob = bpy.context.scene.objects[-1]
        ob.modifiers.new(name="tcat06_subsurf", type='SUBSURF')
        ob.modifiers.new(name="tcat06_bevel", type='BEVEL')

    def render_info():
        sc = bpy.context.scene
        _ = sc.render.engine  # touches render settings safely
        sc.frame_set(1)

    ops.append(op("mesh.primitive_cube_add", add_mesh))
    ops.append(op("mesh.primitive_cylinder_add", add_cyl))
    ops.append(op("object.transform", transform))
    ops.append(op("data.material_new", material))
    ops.append(op("data.curve_new", curve_native))
    ops.append(op("object.modifier_add", modifier_add))
    ops.append(op("render.frame_set", render_info))
    return ops


def main():
    startup_s = round(time.time() - _start, 2) if (_start := globals().get("_start", time.time())) else 0
    data = {"label": LABEL, "startup_s": startup_s, "ops": native_ops()}

    # extension present? (only in the "loaded" run)
    try:
        import bcshell  # noqa: F401
        data["extension_registered"] = bool(getattr(bcshell, "registered", False))
        bcshell.unregister()
        bcshell.register()
        data["clean_unload"] = True
    except ImportError:
        data["extension_registered"] = False
        data["clean_unload"] = None  # not applicable: extension absent (stock run)

    # .blend save/reload round-trip (native persistence path)
    blend = OUT.parent / f"tcat06_{LABEL}.blend"
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        bpy.ops.wm.open_mainfile(filepath=str(blend))
        data["blend_roundtrip_ok"] = blend.is_file()
    except Exception as e:  # noqa: BLE001
        data["blend_roundtrip_ok"] = False
        data["blend_error"] = repr(e)[:200]

    OUT.write_text(json.dumps(data, indent=2))
    ok = all(o["ok"] for o in data["ops"]) and data["blend_roundtrip_ok"]
    print(f"TP-CAT-06 phase ({LABEL}): {'OK' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


_start = time.time()
if __name__ == "__main__":
    main()
