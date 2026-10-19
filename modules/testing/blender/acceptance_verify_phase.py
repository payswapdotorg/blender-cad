"""M1 acceptance — verify phase. Runs INSIDE Blender (blender --background --python).

Loaded with the ISOLATED user resources (BLENDER_USER_RESOURCES) in which the
extension was installed by phase A. The extension is enabled at startup, so the
REAL load path (bl_ext.user_default.blender_cad) is exercised — no repo sys.path
bootstrap happens here. Command execution goes through the SAME registry +
prompt state machine the modal UI uses (bcshell.run_scripted).

argv after "--": <result_json_path>
Writes the phase result JSON (checks, blend_file, dxf_engine, all_passed).
"""

import json
import sys
from pathlib import Path

import bpy  # noqa: E402  (this file only ever runs inside Blender)

OUT = Path(sys.argv[sys.argv.index("--") + 1])
CHECKS = []


def record(name, passed, detail=""):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail else ""))


def approx(a, b, eps=1e-9):
    return abs(a - b) <= eps


def pts_approx(p1, p2, eps=1e-9):
    return all(approx(x, y, eps) for x, y in zip(p1, p2))


def main():
    # 1. the installed extension was enabled at startup (real load path)
    try:
        import bl_ext.user_default.blender_cad as ext_pkg  # noqa: F401
        record("extension.loaded_at_startup", True, "import bl_ext.user_default.blender_cad OK")
    except Exception as e:  # noqa: BLE001
        record("extension.loaded_at_startup", False, repr(e)[:200])
        finish(None, None)
        return

    import bcshell
    from bccmd import selection_input

    record("bcshell.registered_flag", bcshell.registered is True, f"registered={bcshell.registered}")

    doc = bcshell.session.active_document()

    # 2. CAD workspace opens
    try:
        bpy.ops.bcshell.workspace_open()
        ws_names = [w.name for w in bpy.data.workspaces]
        ok = "BlenderCAD" in ws_names
        record("workspace.opens", ok, f"workspaces={ws_names}")
    except Exception as e:  # noqa: BLE001
        record("workspace.opens", False, repr(e)[:200])

    # 3. LINE, CIRCLE, ARC through the command interface (real prompt state machine)
    res_line = bcshell.run_scripted("LINE", ["0,0", "10,0", "10,8", "C"])
    ok_line = res_line.ok and len(res_line.created) == 3
    ents = [doc.get(i) for i in res_line.created]
    geom_ok = (
        ok_line
        and pts_approx(ents[0].p1, (0.0, 0.0, 0.0))
        and pts_approx(ents[0].p2, (10.0, 0.0, 0.0))
        and pts_approx(ents[2].p2, (0.0, 0.0, 0.0))  # Close returns to first point
    )
    record("command.LINE", ok_line and geom_ok, f"created={len(res_line.created)} segments; Close honored")

    res_circle = bcshell.run_scripted("CIRCLE", ["20,5", "4"])
    c = doc.get(res_circle.created[0]) if res_circle.created else None
    record(
        "command.CIRCLE",
        res_circle.ok and c is not None and pts_approx(c.center, (20.0, 5.0, 0.0)) and approx(c.radius, 4.0),
        f"center={tuple(c.center) if c else None} radius={c.radius if c else None}",
    )

    res_arc = bcshell.run_scripted("ARC", ["20,30", "10,40", "0,30"])
    a = doc.get(res_arc.created[0]) if res_arc.created else None
    record(
        "command.ARC",
        res_arc.ok and a is not None and approx(a.radius, 10.0, 1e-6),
        f"3P arc radius={a.radius if a else None} center={tuple(a.center) if a else None} (expected r=10)",
    )

    # 4. basic modifications through the same interface
    line_id = res_line.created[0]
    res_move = bcshell.run_scripted("MOVE", [selection_input([line_id]), "0,0", "5,5"])
    moved = doc.get(line_id)
    move_ok = (
        res_move.ok
        and res_move.modified == [line_id]
        and pts_approx(moved.p1, (5.0, 5.0, 0.0))
        and pts_approx(moved.p2, (15.0, 5.0, 0.0))
    )
    record("command.MOVE", move_ok, f"p1={tuple(moved.p1)} p2={tuple(moved.p2)}")

    circle_id = res_circle.created[0]
    res_copy = bcshell.run_scripted("COPY", [selection_input([circle_id]), "20,5", "22,5", ""])
    copy_ok = res_copy.ok and len(res_copy.created) == 1
    copy_c = doc.get(res_copy.created[0]) if copy_ok else None
    record(
        "command.COPY",
        copy_ok and copy_c.id != circle_id and pts_approx(copy_c.center, (22.0, 5.0, 0.0)) and approx(copy_c.radius, 4.0),
        f"copy center={tuple(copy_c.center) if copy_c else None}; original kept at {tuple(doc.get(circle_id).center)}",
    )

    copy_id = res_copy.created[0] if copy_ok else None
    if copy_id:
        res_rot = bcshell.run_scripted("ROTATE", [selection_input([copy_id]), "22,5", "90"])
        rot_c = doc.get(copy_id)
        record(
            "command.ROTATE",
            res_rot.ok and res_rot.modified == [copy_id] and pts_approx(rot_c.center, (22.0, 5.0, 0.0)),
            "rotated 90° about base point at the circle center (center invariant)",
        )

        res_scale = bcshell.run_scripted("SCALE", [selection_input([copy_id]), "22,5", "2"])
        sc = doc.get(copy_id)
        record(
            "command.SCALE",
            res_scale.ok and approx(sc.radius, 8.0),
            f"radius {sc.radius} after scale factor 2 (base at center)",
        )

        n_before = len(doc.entities())
        res_erase = bcshell.run_scripted("ERASE", [selection_input([copy_id])])
        record(
            "command.ERASE",
            res_erase.ok and res_erase.removed == [copy_id] and len(doc.entities()) == n_before - 1,
            f"entities {n_before} -> {len(doc.entities())}",
        )

    # undo accounting: one committed group per command; document undo works
    depth = doc.undo_depth()
    record("document.undo_depth", depth > 0, f"undo_depth={depth}")
    if depth:
        doc.undo()
        record("document.undo_roundtrip", doc.get(copy_id) is not None,
               "undo() restored the ERASEd entity")

    # 5. display sync exists (derived scene objects carry bcdoc_id)
    try:
        bcshell.sync.sync_display(doc)
        coll = bpy.data.collections.get("BlenderCAD")
        n_disp = len(coll.objects) if coll else 0
        tagged = all("bcdoc_id" in o for o in coll.objects) if coll else False
        record("display.sync", n_disp == len(doc.entities()) and tagged, f"display objects={n_disp}")
    except Exception as e:  # noqa: BLE001
        record("display.sync", False, repr(e)[:200])

    # 6. native Blender functions remain usable
    try:
        bpy.ops.mesh.primitive_cube_add(location=(100.0, 100.0, 0.0))
        native_ok = any(o.type == "MESH" for o in bpy.context.scene.objects)
        record("native.functions_usable", native_ok, "primitive_cube_add OK alongside CAD entities")
    except Exception as e:  # noqa: BLE001
        record("native.functions_usable", False, repr(e)[:200])

    # 7. DXF round-trip inside Blender (export -> wipe -> re-import -> compare)
    dxf_path = OUT.parent / "acceptance_roundtrip.dxf"
    engine_out = None
    rt_ok = False
    try:
        import bcio

        stats_out = bcio.export_dxf(str(dxf_path), doc)
        engine_out = stats_out.get("engine")
        n_entities = len(doc.entities())
        before = sorted((e.kind, e.handle, repr(e.geometry_dict())) for e in doc.entities())
        with doc.transaction("wipe for re-import"):
            for e in list(doc.entities()):
                doc.remove(e.id)
        doc2, stats_in = bcio.import_dxf(str(dxf_path), doc=doc)
        after = sorted((e.kind, e.handle, repr(e.geometry_dict())) for e in doc2.entities())
        rt_ok = (
            dxf_path.is_file()
            and len(after) == n_entities
            and before == after
        )
        record(
            "dxf.roundtrip_in_blender",
            rt_ok,
            f"engine out={engine_out} in={stats_in.get('engine')}; {n_entities} entities identical after export->wipe->import",
        )
    except Exception as e:  # noqa: BLE001
        record("dxf.roundtrip_in_blender", False, repr(e)[:200])

    # 8. save the .blend for the reopen phase
    blend_file = None
    try:
        bcshell.session.flush(doc)  # CAD document JSON into its persistence text block
        blend_file = OUT.parent / "acceptance_m1.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_file))
        record("document.saved", blend_file.is_file(), str(blend_file))
    except Exception as e:  # noqa: BLE001
        record("document.saved", False, repr(e)[:200])
        blend_file = None

    finish(str(blend_file) if blend_file else None, engine_out)


def finish(blend_file, dxf_engine):
    all_passed = bool(CHECKS) and all(c["passed"] for c in CHECKS)
    payload = {
        "phase": "verify",
        "checks": CHECKS,
        "all_passed": all_passed,
        "blend_file": blend_file,
        "dxf_engine": dxf_engine,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"VERIFY PHASE: {'ALL PASSED' if all_passed else 'FAILED'} "
          f"({sum(c['passed'] for c in CHECKS)}/{len(CHECKS)})")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
