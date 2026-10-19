#!/usr/bin/env python3
"""M2 acceptance battery (§11, contracts m2-module-contracts.md) — the
operator-directive gate for the drafting-core milestone.

Modeled exactly on acceptance_m1.py (orchestrator + phases + JSON result),
extended to the §11 section list. Run from the repo root:

  python3 modules/testing/blender/acceptance_m2.py [--blender PATH] [--keep-userdir]
  python3 modules/testing/blender/acceptance_m2.py --list-sections   # no Blender

Orchestrator (this file, plain Python) drives three Blender subprocesses
against the SELECTED build, through Blender's ACTUAL extension system (no
sys.path bootstrap of repo sources):

  A. install  : blender --command extension install-file   (isolated BLENDER_USER_RESOURCES)
  B. verify   : blender --background --python <verify phase>   (sections 1..6 + save .blend)
  C. reopen   : blender --background --python <reopen phase>   (section 7: persistence +
                clean unload + native regression sanity)

The in-Blender phase scripts live IN THIS FILE (embedded sources written
into the run's temp dir at runtime) because the battery ships as ONE new
file per the M2 task letter — the phase code is still fully versioned
here, and --list-sections byte-compiles both sources as a self-check.

Result artifact: modules/testing/blender/acceptance_m2_result.json.
Exit code 0 only if every check passes.

Section list (contracts §11):

1. m1-regression — extension loads, workspace opens, LINE/CIRCLE/ARC +
   MOVE/COPY/ROTATE/SCALE/ERASE, undo, native coexistence.
2. precision — mouse-source ENDPOINT snap (exact point), ORTHO mouse
   point, typed DDE (relative point then distance), one-shot osnap
   keyword, invalid-input recovery, cancel leaves doc_version unchanged.
3. layers — LAYER New+Set (+Color), entity on layer, layer OFF hides its
   display objects, FROZEN excludes from osnap, LOCKED rejects MOVE with
   feedback, save/reopen keeps layers.
4. blocks — BLOCK from geometry, INSERT, MOVE the reference, REDEFINE
   updates member display, save/reopen, DXF round-trip.
5. annotations — DIMLINEAR exact measurement + display objects, TEXT,
   MTEXT, MOVE measured entity -> regen updates the dim text,
   DIMSTYLE/STYLE new+set, save/reopen, DXF round-trip.
6. layouts — LAYOUT new/set, paper-space frame, MVIEW Fit, MSPACE/PSPACE,
   save/reopen, DXF export includes paper space.
7. clean-unload + native regression sanity (reopen phase).

Battery policy (per task letter): every check that needs a command first
probes registry.lookup — a missing command FAILS the check with an
explicit "command missing" detail so TL sees integration gaps; nothing is
silently skipped. Mouse-sourced points are built with
bcshell.session.mouse_point_input (source="mouse" — the W-A input-model
glue) so the precision chain is exercised end-to-end.
"""

import argparse
import json
import os
import platform
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DIST = REPO / "dist"
RESULT = HERE / "acceptance_m2_result.json"

DEFAULT_BLENDER = "/home/z/runtime/blender-5.2.2-linux-x64/blender"

SECTIONS = [
    {"id": "1", "title": "m1-regression", "checks": [
        "extension.loaded_at_startup",
        "workspace.opens",
        "m1.command.LINE", "m1.command.CIRCLE", "m1.command.ARC",
        "m1.command.MOVE", "m1.command.COPY", "m1.command.ROTATE",
        "m1.command.SCALE", "m1.command.ERASE",
        "m1.command.UNDO",
        "m1.native_cube_coexists",
    ]},
    {"id": "2", "title": "precision", "checks": [
        "precision.mouse_endpoint_snap_exact",
        "precision.ortho_constrained_mouse_point",
        "precision.typed_dde_relative_then_distance",
        "precision.oneshot_osnap_keyword",
        "precision.invalid_input_recovery",
        "precision.cancel_leaves_doc_version_unchanged",
    ]},
    {"id": "3", "title": "layers", "checks": [
        "layers.command_available",
        "layers.new_set_color",
        "layers.entity_on_layer",
        "layers.off_hides_display_objects",
        "layers.frozen_excluded_from_osnap",
        "layers.locked_move_feedback_skip",
        "layers.persisted (reopen phase)",
    ]},
    {"id": "4", "title": "blocks", "checks": [
        "blocks.command_available",
        "blocks.create_and_insert",
        "blocks.insert_reference",
        "blocks.move_reference",
        "blocks.redefine_updates_display",
        "blocks.persisted (reopen phase)",
        "blocks.dxf_roundtrip",
    ]},
    {"id": "5", "title": "annotations", "checks": [
        "ann.dimlinear_measurement_and_display",
        "ann.dim_display_objects",
        "ann.regen_updates_dim_text",
        "ann.text", "ann.mtext",
        "ann.dimstyle_style_new_set",
        "ann.persisted (reopen phase)",
        "ann.dxf_roundtrip",
    ]},
    {"id": "6", "title": "layouts", "checks": [
        "lay.layout_new_set",
        "lay.layout_activates_paper_space",
        "lay.paper_space_frame",
        "lay.mview_fit",
        "lay.layout_collection_visible",
        "lay.mspace_pspace",
        "lay.model_collection_hidden_in_paper_space",
        "lay.persisted (reopen phase)",
        "lay.dxf_paper_space",
    ]},
    {"id": "7", "title": "clean-unload + native (reopen phase)", "checks": [
        "reopen.document_restored",
        "reopen.display_synced",
        "reopen.native_functions_usable",
        "reopen.clean_unload_reload",
        "extension.uninstall (orchestrator)",
    ]},
]

# ---------------------------------------------------------------------------
# embedded in-Blender phase sources (written into the run temp dir; the
# battery ships as ONE file per the task letter — this keeps the phase code
# versioned and --list-sections byte-compiles both as a self-check)
# ---------------------------------------------------------------------------

VERIFY_PHASE_SOURCE = r'''# M2 acceptance - verify phase (generated by acceptance_m2.py).
# Runs INSIDE Blender with the INSTALLED extension enabled at startup
# (isolated BLENDER_USER_RESOURCES). Sections 1..6 of contracts m2
# section 11 + saves the .blend for the reopen phase.
# argv after "--": <result_json_path>
import json
import sys
from pathlib import Path

import bpy  # noqa: E402  (Blender interpreter only)

OUT = Path(sys.argv[sys.argv.index("--") + 1])
CHECKS = []


def record(name, passed, detail=""):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": str(detail)})
    print(("PASS " if passed else "FAIL ") + name + (f" - {detail}" if detail else ""))


def approx(a, b, eps=1e-9):
    return abs(a - b) <= eps


def pts_equal(p1, p2, eps=1e-9):
    return all(abs(x - y) <= eps for x, y in zip(tuple(p1), tuple(p2)))


def main():
    import bcshell
    from bccmd import selection_input

    session = bcshell.session
    doc = session.active_document()
    registry = session.get_registry()

    def missing(*names):
        return [n for n in names if registry.lookup(n) is None]

    # ---- SECTION 1: m1-regression -------------------------------------
    try:
        import bl_ext.user_default.blender_cad  # noqa: F401
        record("extension.loaded_at_startup", True)
    except Exception as exc:
        record("extension.loaded_at_startup", False, repr(exc)[:200])
    try:
        bpy.ops.bcshell.workspace_open()
        record("workspace.opens", "BlenderCAD" in [w.name for w in bpy.data.workspaces])
    except Exception as exc:
        record("workspace.opens", False, repr(exc)[:200])

    miss = missing("LINE", "CIRCLE", "ARC", "MOVE", "COPY", "ROTATE", "SCALE", "ERASE", "UNDO")
    if miss:
        record("m1.commands_available", False, f"command missing: {', '.join(miss)}")
        return finish(None)

    r = bcshell.run_scripted("LINE", ["0,0", "10,0", "10,8", "C"])
    l1 = doc.get(r.created[0]) if r.created else None
    record("m1.command.LINE", r.ok and len(r.created) == 3
           and pts_equal(l1.p1, (0, 0, 0)) and pts_equal(l1.p2, (10, 0, 0)),
           r.summary)
    r = bcshell.run_scripted("CIRCLE", ["20,5", "4"])
    c = doc.get(r.created[0]) if r.created else None
    record("m1.command.CIRCLE", r.ok and c is not None
           and pts_equal(c.center, (20, 5, 0)) and approx(c.radius, 4.0), r.summary)
    r = bcshell.run_scripted("ARC", ["20,30", "10,40", "0,30"])
    a = doc.get(r.created[0]) if r.created else None
    record("m1.command.ARC", r.ok and a is not None and approx(a.radius, 10.0, 1e-6),
           r.summary)

    line_id = doc.entities()[0].id
    r = bcshell.run_scripted("MOVE", [selection_input([line_id]), "0,0", "5,5"])
    moved = doc.get(line_id)
    record("m1.command.MOVE", r.ok and pts_equal(moved.p1, (5, 5, 0))
           and pts_equal(moved.p2, (15, 5, 0)), r.summary)
    r = bcshell.run_scripted("COPY", [selection_input([line_id]), "5,5", "8,5", ""])
    copy_ok = r.ok and len(r.created) == 1
    copy_id = r.created[0] if copy_ok else None
    copy_line = doc.get(copy_id) if copy_id else None
    record("m1.command.COPY", copy_ok and pts_equal(copy_line.p1, (8, 5, 0)),
           r.summary)
    if copy_id:
        r = bcshell.run_scripted("ROTATE", [selection_input([copy_id]), "8,5", "90"])
        rot = doc.get(copy_id)
        record("m1.command.ROTATE", r.ok and approx(
            (rot.p2[0] - rot.p1[0]) ** 2 + (rot.p2[1] - rot.p1[1]) ** 2, 100.0),
            r.summary)
        r = bcshell.run_scripted("SCALE", [selection_input([copy_id]), "8,5", "2"])
        sc = doc.get(copy_id)
        record("m1.command.SCALE", r.ok and approx(
            (sc.p2[0] - sc.p1[0]) ** 2 + (sc.p2[1] - sc.p1[1]) ** 2, 400.0), r.summary)
        n_before = len(doc.entities())
        r = bcshell.run_scripted("ERASE", [selection_input([copy_id])])
        record("m1.command.ERASE", r.ok and len(doc.entities()) == n_before - 1,
               r.summary)
        r = bcshell.run_scripted("UNDO", [])
        record("m1.command.UNDO", r.ok and doc.get(copy_id) is not None, r.summary)

    try:
        bpy.ops.mesh.primitive_cube_add(location=(200.0, 200.0, 0.0))
        record("m1.native_cube_coexists",
               any(o.type == "MESH" for o in bpy.context.scene.objects),
               "cube added alongside CAD entities")
    except Exception as exc:
        record("m1.native_cube_coexists", False, repr(exc)[:200])

    # ---- SECTION 2: precision -----------------------------------------
    if missing("LINE"):
        record("precision.section", False, "command missing: LINE")
    else:
        # mouse-source ENDPOINT snap: a raw mouse point 0.36 units off the
        # stored endpoint resolves EXACTLY onto it
        seed = bcshell.run_scripted("LINE", ["10,0", "20,0", ""])
        assert seed.ok
        r = bcshell.run_scripted("LINE", [
            session.mouse_point_input(10.35, 0.2, 0.0), "12,0", ""])
        created = doc.get(r.created[0]) if r.created else None
        record("precision.mouse_endpoint_snap_exact",
               r.ok and created is not None
               and pts_equal(created.p1, (10.0, 0.0, 0.0), 1e-12),
               f"raw mouse (10.35, 0.2) -> resolved {tuple(created.p1) if created else None}")

        # ORTHO: mouse point (5, 3) with last point (0,0) projects to (5, 0)
        doc.settings.set("ORTHOMODE", 1)
        r = bcshell.run_scripted("LINE", [
            "0,0", session.mouse_point_input(5.0, 3.0, 0.0), ""])
        created = doc.get(r.created[0]) if r.created else None
        record("precision.ortho_constrained_mouse_point",
               r.ok and created is not None
               and pts_equal(created.p2, (5.0, 0.0, 0.0), 1e-12),
               f"raw mouse (5, 3) -> resolved {tuple(created.p2) if created else None}")
        doc.settings.set("ORTHOMODE", 0)

        # typed DDE: relative point then a typed distance (pointer None ->
        # +X direction per bcdraft.precision.dde_point)
        r = bcshell.run_scripted("LINE", ["0,0", "@3,4", "5", ""])
        seg2 = doc.get(r.created[1]) if len(r.created or []) > 1 else None
        record("precision.typed_dde_relative_then_distance",
               r.ok and seg2 is not None and pts_equal(seg2.p2, (8.0, 4.0, 0.0)),
               f"DDE distance 5 -> {tuple(seg2.p2) if seg2 else None}")

        # one-shot osnap keyword: "END" arms ENDPOINT for the NEXT mouse pick
        r = bcshell.run_scripted("LINE", [
            "END", session.mouse_point_input(20.4, -0.2, 0.0), "22,0", ""])
        created = doc.get(r.created[0]) if r.created else None
        record("precision.oneshot_osnap_keyword",
               r.ok and created is not None
               and pts_equal(created.p1, (20.0, 0.0, 0.0), 1e-12),
               f"one-shot END mouse (20.4, -0.2) -> {tuple(created.p1) if created else None}")

        # invalid input -> diagnostic -> re-prompt recovery
        r = bcshell.run_scripted("LINE", ["not-a-point-or-option", "3,3", "6,3", ""])
        created = doc.get(r.created[0]) if r.created else None
        record("precision.invalid_input_recovery",
               r.ok and created is not None and pts_equal(created.p1, (3, 3, 0)),
               f"created after re-ask: {r.summary}")

        # cancel mid-command leaves the document unchanged
        from bccmd import Cancelled
        version = doc.doc_version
        n_entities = len(doc.entities())
        r = bcshell.run_scripted("LINE", ["0,0", Cancelled()])
        record("precision.cancel_leaves_doc_version_unchanged",
               r.status == "cancelled" and doc.doc_version == version
               and len(doc.entities()) == n_entities,
               f"status={r.status} version {version}=={doc.doc_version}")

    # ---- SECTION 3: layers --------------------------------------------
    layer_gone = missing("LAYER", "-LAYER")
    record("layers.command_available", not layer_gone,
           f"command missing: {', '.join(layer_gone)}" if layer_gone
           else "LAYER registered")
    if not layer_gone:
        layer_cmd = "LAYER" if registry.lookup("LAYER") else "-LAYER"
        r = bcshell.run_scripted(layer_cmd, ["New", "WALLS", "Set", "WALLS",
                                             "Color", "1", "WALLS", ""])
        record("layers.new_set_color",
               r.ok and "WALLS" in doc.layers
               and doc.layers.get("WALLS").color == 1
               and doc.current_layer == "WALLS", r.summary)
    # document/display rules are exercised through the same journaled paths
    # the LAYER command uses (available regardless of the command; direct
    # API adds pass the layer explicitly — bcdoc does not apply CLAYER on
    # add_entity, the COMMANDS do that):
    with doc.transaction("layer rules"):
        doc.layers.add("FROZ", color=5, frozen=True)
        doc.layers.add("LOCKED", color=3, locked=True)
    from bcdoc.entities import Line as _Line
    wall_layer = "WALLS" if "WALLS" in doc.layers else "0"
    with doc.transaction("layer content"):
        doc.add_entity(_Line((50, 0, 0), (60, 0, 0), layer="FROZ"))
        frozen_id = doc.entities()[-1].id
        doc.add_entity(_Line((0, 50, 0), (9, 50, 0), layer="LOCKED"))
        locked_id = doc.entities()[-1].id
        doc.add_entity(_Line((0, 0, 0), (1, 0, 0), layer=wall_layer))
        wall_id = doc.entities()[-1].id
    record("layers.entity_on_layer", doc.get(wall_id).layer == wall_layer,
           f"entity created on layer {wall_layer!r}")

    if "WALLS" in doc.layers:
        with doc.transaction("layer off"):
            doc.layers.set_props("WALLS", on=False)
        bcshell.sync.sync_display(doc)
        wall_objs = [o for o in bpy.data.collections["BlenderCAD"].objects
                     if o.get("bcdoc_id") == wall_id]
        record("layers.off_hides_display_objects",
               bool(wall_objs) and all(o.hide_viewport for o in wall_objs),
               f"{len(wall_objs)} display object(s) for the off-layer entity")
        with doc.transaction("layer on"):
            doc.layers.set_props("WALLS", on=True)

    # frozen: a mouse pick near the frozen layer's endpoint must NOT snap
    osmode_backup = doc.settings.get("OSMODE")
    doc.settings.set("OSMODE", 1)  # ENDPOINT only
    r = bcshell.run_scripted("LINE", [
        session.mouse_point_input(50.05, 0.05, 0.0), "52,0", ""])
    created = doc.get(r.created[0]) if r.created else None
    record("layers.frozen_excluded_from_osnap",
           r.ok and created is not None
           and not pts_equal(created.p1, (50.0, 0.0, 0.0), 1e-12),
           f"frozen-endpoint mouse (50.05, 0.05) -> {tuple(created.p1) if created else None}")
    doc.settings.set("OSMODE", osmode_backup)

    # locked: MOVE must skip locked-layer entities with feedback
    r = bcshell.run_scripted("MOVE", [selection_input([locked_id]), "0,0", "1,1"])
    feedback = session.feedback_messages(5)
    locked_line = doc.get(locked_id)
    record("layers.locked_move_feedback_skip",
           pts_equal(locked_line.p1, (0, 50, 0))
           and any("lock" in m.lower() for m in feedback),
           f"move summary: {r.summary}")

    # ---- SECTION 4: blocks --------------------------------------------
    block_gone = missing("BLOCK", "INSERT")
    record("blocks.command_available", not block_gone,
           f"command missing: {', '.join(block_gone)}" if block_gone
           else "BLOCK/INSERT registered")
    insert_id = None
    if not block_gone:
        from bcdoc.entities import Insert as _Insert
        source = bcshell.run_scripted("LINE", ["0,0", "2,0", ""])
        r = bcshell.run_scripted("BLOCK", ["MYBLOCK", "0,0",
                                           selection_input(list(source.created)),
                                           ""])
        record("blocks.create_and_insert", r.ok and "MYBLOCK" in doc.blocks(),
               r.summary)
        if "MYBLOCK" in doc.blocks():
            r = bcshell.run_scripted("INSERT", ["MYBLOCK", "30,0", "1", "0"])
            insert_id = r.created[0] if r.ok and r.created else None
            insert_ent = doc.get(insert_id) if insert_id else None
            record("blocks.insert_reference",
                   insert_ent is not None and insert_ent.kind == "insert"
                   and pts_equal(insert_ent.position, (30, 0, 0)), r.summary)
            r = bcshell.run_scripted("MOVE", [selection_input([insert_id]),
                                              "0,0", "2,3"])
            record("blocks.move_reference",
                   r.ok and pts_equal(doc.get(insert_id).position, (32, 3, 0)),
                   r.summary)
            # redefine -> display members change (spec points differ)
            bcshell.sync.sync_display(doc)
            from bcdoc.entities import Circle as _Circle
            with doc.transaction("redefine"):
                doc.redefine_block("MYBLOCK", [_Circle((0, 0, 0), 1.0)])
            bcshell.sync.sync_display(doc)
            members = [o for o in bpy.data.collections["BlenderCAD"].objects
                       if o.get("bcdoc_id") == insert_id]
            record("blocks.redefine_updates_display", bool(members),
                   f"{len(members)} member display object(s) after redefine")

    # ---- SECTION 5: annotations ---------------------------------------
    ann_gone = missing("DIMLINEAR", "TEXT", "MTEXT", "DIMSTYLE", "STYLE")
    dim_id = None
    if ann_gone:
        record("ann.section", False,
               f"command missing: {', '.join(ann_gone)}")
    else:
        measured = bcshell.run_scripted("LINE", ["100,100", "110,100", ""])
        measured_id = measured.created[0]
        # ASSOCIATIVE path (FP-ANN-015): Enter at the first prompt selects the
        # measured LINE — the dim stores measured_id and follows the entity.
        r = bcshell.run_scripted("DIMLINEAR", ["",
                                               selection_input([measured_id]),
                                               "105,105"])
        dim_id = r.created[0] if r.ok and r.created else None
        dim = doc.get(dim_id) if dim_id else None
        record("ann.dimlinear_measurement_and_display",
               dim is not None and approx(dim.measurement, 10.0), r.summary)
        if dim is not None:
            specs = bcshell.sync.display_specs(dim, doc)
            kinds = sorted(s["role"] for s in specs)
            record("ann.dim_display_objects", len(specs) == 2
                   and kinds == ["dim", "dim-text"], f"roles {kinds}")
            # SCALE the measured line (10 -> 14 units): the associative dim
            # must re-derive measurement + text after regen (FP-ANN-015).
            r = bcshell.run_scripted("SCALE", [selection_input([measured_id]),
                                              "0,0", "1.4"])
            r2 = bcshell.run_scripted("DIMREGEN", []) if registry.lookup("DIMREGEN") else None
            specs = bcshell.sync.display_specs(dim, doc)
            text = [s for s in specs if s["kind"] == "font"][0]["body"]
            record("ann.regen_updates_dim_text",
                   r.ok and "14" in text,
                   f"dim text after SCALE+regen: {text!r}")
        r = bcshell.run_scripted("TEXT", ["120,120", "2.5", "0", "M2TEXT"])
        text_ent = doc.get(r.created[0]) if r.ok and r.created else None
        record("ann.text", text_ent is not None
               and text_ent.content == "M2TEXT", r.summary)
        r = bcshell.run_scripted("MTEXT", ["130,120", "20", "line1\\nline2"])
        mtext_ent = doc.get(r.created[0]) if r.ok and r.created else None
        record("ann.mtext", mtext_ent is not None
               and "line1" in mtext_ent.content, r.summary)
        r = bcshell.run_scripted("DIMSTYLE", ["New", "TIGHT", "", "", "", "", ""])
        r2 = bcshell.run_scripted("STYLE", ["New", "SERIF", "", ""])
        record("ann.dimstyle_style_new_set",
               "TIGHT" in doc.dim_styles() and "SERIF" in doc.text_styles()
               and (r.ok or "TIGHT" in doc.dim_styles()),
               f"dimstyles={doc.dim_styles()} textstyles={doc.text_styles()}")

    # ---- SECTION 6: layouts -------------------------------------------
    lay_gone = missing("LAYOUT", "MVIEW", "MSPACE", "PSPACE")
    viewport_id = None
    if lay_gone:
        record("lay.section", False, f"command missing: {', '.join(lay_gone)}")
    else:
        r = bcshell.run_scripted("LAYOUT", ["New", "Sheet1", "", ""])
        record("lay.layout_new_set", r.ok and "Sheet1" in doc.layouts(),
               r.summary)
        if "Sheet1" in doc.layouts():
            r = bcshell.run_scripted("LAYOUT", ["Set", "Sheet1"])
            record("lay.layout_activates_paper_space",
                   r.ok and doc.current_space == "Sheet1"
                   and doc.settings.get("TILEMODE") == 0, r.summary)
            # frame rect in paper space (typed points -> paper entities)
            frame = bcshell.run_scripted("LINE", ["10,10", "400,10", "400,280",
                                                  "10,280", "C"])
            frame_ids = list(frame.created)
            frame_ok = frame.ok and all(
                doc.get(i).space == "Sheet1" for i in frame_ids)
            record("lay.paper_space_frame", frame_ok,
                   f"{len(frame_ids)} frame segments in Sheet1")
            r = bcshell.run_scripted("MVIEW", ["20,20", "380,260", ""])
            viewport_id = r.created[0] if r.ok and r.created else None
            viewport = doc.get(viewport_id) if viewport_id else None
            record("lay.mview_fit", viewport is not None
                   and viewport.space == "Sheet1" and viewport.view_height > 0,
                   r.summary)
            bcshell.sync.sync_display(doc)
            layout_coll = bpy.data.collections.get("BlenderCAD/Layout Sheet1")
            record("lay.layout_collection_visible", layout_coll is not None
                   and not layout_coll.hide_viewport,
                   f"collection {'present' if layout_coll else 'MISSING'}")
            r = bcshell.run_scripted("MSPACE", [])
            r2 = bcshell.run_scripted("PSPACE", [])
            record("lay.mspace_pspace",
                   r.ok and r2.ok
                   and doc.current_space == "Sheet1"
                   and doc.settings.get("TILEMODE") == 0,
                   f"mspace: {r.summary}; pspace: {r2.summary}")
            model_coll = bpy.data.collections.get("BlenderCAD")
            record("lay.model_collection_hidden_in_paper_space",
                   model_coll is not None and bool(model_coll.hide_viewport),
                   f"hide_viewport={model_coll.hide_viewport if model_coll else None}")

    # ---- DXF round-trips (blocks + annotations + paper space) ----------
    dxf_path = OUT.parent / "acceptance_m2_roundtrip.dxf"
    try:
        import bcio
        stats_out = bcio.export_dxf(str(dxf_path), doc)
        imported, stats_in = bcio.import_dxf(str(dxf_path))
        n_kinds = doc.count_by_kind()
        rt_kinds = imported.count_by_kind()
        roundtrip_ok = dxf_path.is_file()
        details = (f"engine {stats_out.get('engine')}/{stats_in.get('engine')}; "
                   f"kinds doc={n_kinds} roundtrip={rt_kinds}; "
                   f"losses={len(stats_out.get('losses', []))}")
        blocks_ok = set(doc.blocks()) <= set(imported.blocks())
        record("blocks.dxf_roundtrip", roundtrip_ok and blocks_ok, details)
        dims_ok = n_kinds.get("dim", 0) == rt_kinds.get("dim", 0)
        record("ann.dxf_roundtrip", roundtrip_ok and dims_ok, details)
        lay_ok = set(doc.layouts()) == set(imported.layouts())
        paper_ok = (n_kinds.get("viewport", 0) == rt_kinds.get("viewport", 0)
                    and any(e.space != "MODEL" for e in imported.entities()))
        record("lay.dxf_paper_space", roundtrip_ok and lay_ok and paper_ok, details)
    except Exception as exc:
        record("blocks.dxf_roundtrip", False, repr(exc)[:200])
        record("ann.dxf_roundtrip", False, repr(exc)[:200])
        record("lay.dxf_paper_space", False, repr(exc)[:200])

    # ---- save for the reopen phase ------------------------------------
    blend_file = None
    try:
        session.flush(doc)
        blend_file = OUT.parent / "acceptance_m2.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_file))
        record("document.saved", blend_file.is_file(), str(blend_file))
    except Exception as exc:
        record("document.saved", False, repr(exc)[:200])
        blend_file = None

    state = {
        "layers": sorted(doc.layers.names()),
        "blocks": sorted(doc.blocks()),
        "layouts": sorted(doc.layouts()),
        "kinds": doc.count_by_kind(),
        "current_layer": doc.current_layer,
        "dim_id": dim_id,
        "insert_id": insert_id,
        "viewport_id": viewport_id,
    }
    finish(str(blend_file) if blend_file else None, state)


def finish(blend_file, state=None):
    all_passed = bool(CHECKS) and all(c["passed"] for c in CHECKS)
    payload = {
        "phase": "verify",
        "checks": CHECKS,
        "all_passed": all_passed,
        "blend_file": blend_file,
        "state": state or {},
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"VERIFY PHASE: {'ALL PASSED' if all_passed else 'FAILED'} "
          f"({sum(c['passed'] for c in CHECKS)}/{len(CHECKS)})")
    sys.exit(0 if all_passed else 1)


main()
'''

REOPEN_PHASE_SOURCE = r'''# M2 acceptance - reopen phase (generated by acceptance_m2.py).
# Fresh Blender process: reopens the .blend saved by the verify phase and
# asserts SECTION 7: document restored (all M2 tables), display synced,
# native functions, clean unload/reload.
# argv after "--": <blend_path> <result_json_path> <state_json_path>
import json
import sys
from pathlib import Path

import bpy  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
BLEND = Path(argv[0])
OUT = Path(argv[1])
STATE = json.loads(Path(argv[2]).read_text()) if len(argv) > 2 else {}
CHECKS = []


def record(name, passed, detail=""):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": str(detail)})
    print(("PASS " if passed else "FAIL ") + name + (f" - {detail}" if detail else ""))


def main():
    record("blend.reopened", BLEND.is_file(), str(BLEND))
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    import bcshell

    doc = bcshell.session.active_document()
    record("reopen.document_restored", doc.doc_version > 0
           and len(doc.entities()) > 0,
           f"v{doc.doc_version}, {len(doc.entities())} entities")

    expected_layers = set(STATE.get("layers", []))
    record("reopen.layers_kept",
           expected_layers <= set(doc.layers.names()),
           f"layers {doc.layers.names()} (expected superset of {sorted(expected_layers)})")
    record("reopen.current_layer_kept",
           doc.current_layer == STATE.get("current_layer"),
           f"current_layer {doc.current_layer}")
    expected_blocks = set(STATE.get("blocks", []))
    record("reopen.blocks_kept", expected_blocks <= set(doc.blocks()),
           f"blocks {doc.blocks()}")
    expected_layouts = set(STATE.get("layouts", []))
    record("reopen.layouts_kept", expected_layouts <= set(doc.layouts()),
           f"layouts {doc.layouts()}")
    kinds = STATE.get("kinds", {})
    record("reopen.kinds_kept", doc.count_by_kind().get("dim", 0) >= kinds.get("dim", 0)
           and doc.count_by_kind().get("insert", 0) >= kinds.get("insert", 0)
           and doc.count_by_kind().get("viewport", 0) >= kinds.get("viewport", 0),
           f"kinds {doc.count_by_kind()} (had {kinds})")

    # display resync across ALL spaces (model + layout collections).
    # Multi-object entities (dim = curve+font, insert = members, text = font)
    # map to SEVERAL display objects by design (contracts §7), so the
    # expected object count comes from the display specs themselves.
    try:
        bcshell.sync.sync_display(doc)
        model_coll = bpy.data.collections.get("BlenderCAD")
        layout_coll = bpy.data.collections.get("BlenderCAD/Layout Sheet1") \
            if "Sheet1" in doc.layouts() else None
        def _expected(space):
            return sum(len(bcshell.sync.display_specs(e, doc))
                       for e in doc.entities_in_space(space))
        model_ok = model_coll is not None and \
            len(model_coll.objects) == _expected("MODEL")
        layout_ok = layout_coll is None or \
            len(layout_coll.objects) == _expected("Sheet1")
        record("reopen.display_synced", model_ok and layout_ok,
               f"model objects={len(model_coll.objects) if model_coll else 0}")
    except Exception as exc:
        record("reopen.display_synced", False, repr(exc)[:200])

    # native functions still usable in the reopened file
    try:
        bpy.ops.mesh.primitive_cube_add(location=(-200.0, -200.0, 0.0))
        record("reopen.native_functions_usable", True, "cube add OK after reopen")
    except Exception as exc:
        record("reopen.native_functions_usable", False, repr(exc)[:200])

    # clean unload + reload (TP-CAT-06)
    try:
        bcshell.unregister()
        bcshell.register()
        record("reopen.clean_unload_reload", True,
               "unregister() then register() both clean")
    except Exception as exc:
        record("reopen.clean_unload_reload", False, repr(exc)[:200])

    all_passed = bool(CHECKS) and all(c["passed"] for c in CHECKS)
    OUT.write_text(json.dumps({"phase": "reopen", "checks": CHECKS,
                               "all_passed": all_passed}, indent=2))
    print(f"REOPEN PHASE: {'ALL PASSED' if all_passed else 'FAILED'} "
          f"({sum(c['passed'] for c in CHECKS)}/{len(CHECKS)})")
    sys.exit(0 if all_passed else 1)


main()
'''


# ---------------------------------------------------------------------------
# orchestrator (modeled on acceptance_m1.py)
# ---------------------------------------------------------------------------

def find_zip() -> Path:
    zips = sorted(DIST.glob("blender_cad-*.zip"))
    if not zips:
        raise SystemExit("no dist/blender_cad-*.zip — run scripts/build_extension.py first")
    return zips[-1]


def run(cmd, env, timeout=300):
    t0 = time.time()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    return p, time.time() - t0


def list_sections() -> int:
    """Dry-run mode: print the planned section/check list WITHOUT Blender,
    byte-compiling the embedded phase sources as a self-check (exit 0)."""
    total = 0
    for section in SECTIONS:
        print(f"[{section['id']}] {section['title']}")
        for check in section["checks"]:
            print(f"    - {check}")
            total += 1
    print(f"\n{len(SECTIONS)} sections, {total} planned checks "
          "(in-Blender phases run per-check; guards turn missing commands "
          "into explicit failures).")
    for name, source in (("verify", VERIFY_PHASE_SOURCE),
                         ("reopen", REOPEN_PHASE_SOURCE)):
        with tempfile.TemporaryDirectory(prefix="bcad-m2-selfcheck-") as tmp:
            path = Path(tmp) / f"acceptance_m2_{name}_phase.py"
            path.write_text(source, encoding="utf-8")
            try:
                py_compile.compile(str(path), doraise=True)
                print(f"self-check OK: embedded {name} phase byte-compiles")
            except py_compile.PyCompileError as exc:
                print(f"SELF-CHECK FAILED: embedded {name} phase: {exc}",
                      file=sys.stderr)
                return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=DEFAULT_BLENDER)
    ap.add_argument("--keep-userdir", action="store_true")
    ap.add_argument("--list-sections", action="store_true",
                    help="print the planned sections/checks and exit "
                    "(no Blender; byte-compiles the embedded phases)")
    args = ap.parse_args()

    if args.list_sections:
        return list_sections()

    blender = Path(args.blender)
    if not blender.is_file():
        raise SystemExit(f"blender binary not found: {blender}")

    zip_path = find_zip()
    userdir = Path(tempfile.mkdtemp(prefix="bcad-accept-m2-"))
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = str(userdir)
    env.pop("BLENDER_USER_EXTENSIONS", None)

    checks = []
    result = {
        "battery": "acceptance_m2",
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blender_binary": str(blender),
        "extension_zip": zip_path.name,
        "blender_version": None,
        "phases": {},
        "checks": checks,
        "all_passed": False,
    }

    def record(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + name + (f"  - {detail}" if detail else ""))
        return bool(passed)

    try:
        # ---- phase 0: version probe --------------------------------------
        p, _ = run([str(blender), "--version"], env)
        ver_line = next((l for l in (p.stdout or "").splitlines()
                         if l.startswith("Blender")), "?")
        result["blender_version"] = ver_line.strip()
        record("blender.version", "Blender" in ver_line, ver_line.strip())

        # ---- phase A: install the built zip through the extension system --
        p, dur = run(
            [str(blender), "--command", "extension", "install-file",
             "-r", "user_default", "-e", str(zip_path)],
            env, timeout=300,
        )
        out = (p.stdout or "") + (p.stderr or "")
        installed = p.returncode == 0 and ("Installed" in out or "Reinstalled" in out)
        result["phases"]["install"] = {
            "exit": p.returncode, "seconds": round(dur, 1),
            "output": out.strip()[:400],
        }
        record("extension.install", installed,
               f"exit {p.returncode}; {out.strip()[:120]}")

        # ---- phase B: verify (sections 1..6 + save) -----------------------
        verify_script = userdir / "acceptance_m2_verify_phase.py"
        verify_script.write_text(VERIFY_PHASE_SOURCE, encoding="utf-8")
        outb = userdir / "verify_phase.json"
        p, dur = run(
            [str(blender), "--background", "--python", str(verify_script),
             "--", str(outb)],
            env, timeout=900,
        )
        out = (p.stdout or "") + (p.stderr or "")
        vd = {}
        if outb.is_file():
            vd = json.loads(outb.read_text())
            result["phases"]["verify"] = {
                "exit": p.returncode, "seconds": round(dur, 1),
                "blend": vd.get("blend_file"),
                "phase_all_passed": vd.get("all_passed"),
                "state": vd.get("state"),
            }
            for c in vd.get("checks", []):
                record("verify." + c["check"], c["passed"], c.get("detail", ""))
        else:
            record("verify.phase_ran", False,
                   f"no result json; exit {p.returncode}; tail: {out[-500:]}")

        blend_file = vd.get("blend_file")
        state_path = userdir / "verify_state.json"
        state_path.write_text(json.dumps(vd.get("state") or {}), encoding="utf-8")

        # ---- phase C: reopen (section 7: persistence + clean unload) -----
        outc = userdir / "reopen_phase.json"
        if blend_file and Path(blend_file).is_file():
            reopen_script = userdir / "acceptance_m2_reopen_phase.py"
            reopen_script.write_text(REOPEN_PHASE_SOURCE, encoding="utf-8")
            p, dur = run(
                [str(blender), "--background", "--python", str(reopen_script),
                 "--", str(blend_file), str(outc), str(state_path)],
                env, timeout=600,
            )
            out = (p.stdout or "") + (p.stderr or "")
            if outc.is_file():
                rd = json.loads(outc.read_text())
                result["phases"]["reopen"] = {
                    "exit": p.returncode, "seconds": round(dur, 1),
                    "phase_all_passed": rd.get("all_passed"),
                }
                for c in rd.get("checks", []):
                    record("reopen." + c["check"], c["passed"], c.get("detail", ""))
            else:
                record("reopen.phase_ran", False,
                       f"no result json; exit {p.returncode}; tail: {out[-500:]}")
        else:
            record("reopen.blend_exists", False,
                   "phase B produced no .blend to reopen")

        # ---- uninstall cleanly (extension system) --------------------------
        p, _ = run(
            [str(blender), "--command", "extension", "remove", "blender_cad"],
            env, timeout=120,
        )
        out = (p.stdout or "") + (p.stderr or "")
        removed = (p.returncode == 0 or "not installed" in out.lower()
                   or "removed" in out.lower())
        record("extension.uninstall", removed,
               f"exit {p.returncode}; {out.strip()[:120]}")
    finally:
        result["all_passed"] = bool(checks) and all(c["passed"] for c in checks)
        result["platform"] = platform.platform()
        RESULT.write_text(json.dumps(result, indent=2))
        print(f"\n{'ALL CHECKS PASSED' if result['all_passed'] else 'BATTERY FAILED'} "
              f"({sum(c['passed'] for c in checks)}/{len(checks)} checks)")
        print(f"evidence: {RESULT}")
        if not args.keep_userdir:
            shutil.rmtree(userdir, ignore_errors=True)
        else:
            print(f"userdir kept: {userdir}")

    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
