"""Blender headless evidence driver for bcshell (TP-CAT-01 + TP-CAT-06).

Run with the pinned Blender build (contract §10 testability rule 2)::

    blender --background --factory-startup --python modules/shell/tests/blender_driver.py
    blender --background --factory-startup --python modules/shell/tests/blender_driver.py -- \
        --phase reopen --blend <path from the JSON written by phase main>

Phase *main* (default): bootstraps sys.path, imports + registers bcshell,
opens the CAD workspace, drives LINE/CIRCLE/ARC/MOVE/COPY/ERASE/UNDO/REDO
through ``bcshell.run_scripted`` (the SAME registry + prompt state machine
the UI uses) asserting exact geometry, verifies display sync + native
Blender ops, DXF round-trips the document inside Blender, saves a .blend to
tmp, unregisters and asserts a clean unload (twice-safe).

Phase *reopen*: a FRESH Blender process registers bcshell again, reopens the
.blend saved by phase main, and asserts the CAD document was restored
identical (entities + doc_version — the M1 save/reopen gate, contracts
§6.2/§11), then unregisters cleanly again.

Both phases print ``PASS: <check>`` / ``FAIL: <check>`` lines and merge their
results into ``modules/shell/tests/blender_driver_result.json`` (the evidence
artifact). The process exits non-zero when any check fails.

What this driver honestly CANNOT verify headless: real mouse events, pixel
rendering of the rubberband overlay, the GUI dialog of the command line and
keymap key-press dispatch (no window event loop under --background).
Verified instead: the operator/panel registration surface, the scripted
paths, the state machine, persistence and clean unload.
"""

import json
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# sys.path bootstrap — the same top-level import model the extension uses
# (contracts §2): every modules/<module>/ dir on sys.path.
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
for _sub in ("document", "commands", "drafting", "drawings", "interchange", "agent", "shell"):
    _p = os.path.join(REPO_ROOT, "modules", _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bpy  # noqa: E402  (Blender interpreter only)

RESULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "blender_driver_result.json")
TMP_DIR = tempfile.mkdtemp(prefix="blender_cad_driver_")

RESULTS = {"blender": bpy.app.version_string,
            "python": sys.version.split()[0],
            "phases": {}}


def check(phase, name, condition, detail=""):
    ok = bool(condition)
    entry = RESULTS["phases"].setdefault(phase, {"checks": [], "failed": 0})
    entry["checks"].append({"name": name, "ok": ok, "detail": str(detail)})
    if not ok:
        entry["failed"] += 1
    print(("PASS: " if ok else "FAIL: ") + f"{phase} | {name}"
          + (f" — {detail}" if detail else ""))
    return ok


def write_results():
    RESULTS["all_passed"] = all(
        ph.get("failed", 0) == 0 for ph in RESULTS["phases"].values()
    )
    with open(RESULT_PATH, "w", encoding="utf-8") as handle:
        json.dump(RESULTS, handle, indent=1, sort_keys=True)
    print(f"RESULT JSON: {RESULT_PATH}")


def entity_signature(entity):
    """Comparable, JSON-safe signature of one bcdoc entity."""
    sig = {"kind": entity.kind, "id": entity.id, "handle": entity.handle,
           "layer": entity.layer, "color": entity.color,
           "linetype": entity.linetype}
    for field, value in entity.geometry_dict().items():
        sig[field] = list(value) if isinstance(value, tuple) else float(value)
    return sig


def document_signature(doc):
    return {
        "name": doc.name,
        "doc_version": doc.doc_version,
        "undo_depth": doc.undo_depth(),
        "redo_depth": doc.redo_depth(),
        "entities": [entity_signature(e) for e in doc.entities()],
    }


def same_document(left, right, tolerance=1e-9):
    """Compare two document signatures INCLUDING id/doc_version (reopen gate)."""
    if left["doc_version"] != right["doc_version"]:
        return f"doc_version {left['doc_version']} != {right['doc_version']}"
    return same_entities(left["entities"], right["entities"], tolerance)


def same_entities(left, right, tolerance=1e-9, compare_ids=True):
    """Compare entity signature lists (insertion order preserved).

    ``compare_ids=False`` for interchange round-trips: DXF preserves HANDLES
    (the interchange identity) but not product-internal uuid ids and not
    doc_version (contracts §3.1 / §7)."""
    if len(left) != len(right):
        return f"entity count {len(left)} != {len(right)}"
    for a, b in zip(left, right):
        if a["kind"] != b["kind"] or a["handle"] != b["handle"]:
            return (f"kind/handle mismatch {a['kind']}#{a['handle']} vs "
                    f"{b['kind']}#{b['handle']}")
        if compare_ids and a["id"] != b["id"]:
            return f"id mismatch {a['id']} != {b['id']}"
        for field, value in a.items():
            if field in ("id", "kind", "handle"):
                continue
            other = b[field]
            if isinstance(value, list):
                if any(abs(v - o) > tolerance for v, o in zip(value, other)):
                    return f"{a['kind']}#{a['handle']} field {field}: {value} != {other}"
            elif value != other:
                return f"{a['kind']}#{a['handle']} field {field}: {value!r} != {other!r}"
    return None


def _argv_value(flag, default=None):
    argv = sys.argv
    if flag in argv:
        index = argv.index(flag)
        if index + 1 < len(argv):
            return argv[index + 1]
    return default


# ---------------------------------------------------------------------------
# phase: main
# ---------------------------------------------------------------------------

def phase_main():
    phase = "main"
    import bcshell

    # -- 1. register --------------------------------------------------------
    bcshell.register()
    check(phase, "bcshell.registered flag", bcshell.registered is True)
    op_names = [
        "BCSHELL_OT_workspace_open", "BCSHELL_OT_command_run",
        "BCSHELL_OT_cmdline", "BCSHELL_OT_dxf_import",
        "BCSHELL_OT_dxf_export", "BCSHELL_OT_doc_save_json",
        "BCSHELL_OT_doc_load_json", "BCSHELL_OT_undo",
        "BCSHELL_OT_redo", "BCSHELL_OT_doc_info",
        # v2 panel operators (contract §7 — Layers / Layout-Space /
        # Precision; additive check so the M1 driver also validates the
        # v2 register surface when TL next runs it on the M2 build)
        "BCSHELL_OT_layer_set_current", "BCSHELL_OT_layer_toggle",
        "BCSHELL_OT_layout_activate", "BCSHELL_OT_layout_new",
        "BCSHELL_OT_setting_toggle", "BCSHELL_OT_osnap_toggle",
    ]
    missing = [n for n in op_names if not hasattr(bpy.types, n)]
    check(phase, "all operators registered", not missing,
          f"missing: {missing}" if missing else f"{len(op_names)} operators")
    check(phase, "N-panel registered",
          hasattr(bpy.types, "BLENDERCAD_PT_main"))
    from bcshell import handlers, keymaps
    check(phase, "keymap registered", keymaps.active_keymap_name() is not None,
          keymaps.active_keymap_name())
    check(phase, "load_post/save_pre handlers installed", handlers.installed())

    # -- 2. workspace --------------------------------------------------------
    from bcshell import workspace
    ws = workspace.ensure_workspace()
    check(phase, "workspace BlenderCAD exists",
          ws is not None and ws.name == "BlenderCAD"
          and "BlenderCAD" in bpy.data.workspaces, ws.name if ws else None)
    res = bpy.ops.bcshell.workspace_open()
    check(phase, "bcshell.workspace_open operator", res == {"FINISHED"}, res)

    # -- 3. scripted session through the SAME machinery the UI uses ----------
    from bccmd import selection_input
    doc = bcshell.session.active_document()

    r = bcshell.run_scripted("LINE", ["0,0", "10,0", "10,10", ""])
    check(phase, "LINE 3 chained points -> 2 segments",
          r.ok and len(r.created) == 2, r.summary)
    l1 = doc.get(r.created[0])
    l2 = doc.get(r.created[1])
    check(phase, "LINE geometry exact",
          l1.p1 == (0.0, 0.0, 0.0) and l1.p2 == (10.0, 0.0, 0.0)
          and l2.p1 == (10.0, 0.0, 0.0) and l2.p2 == (10.0, 10.0, 0.0),
          f"{l1.p1}-{l1.p2}; {l2.p1}-{l2.p2}")
    line_ids = list(r.created)

    r = bcshell.run_scripted("CIRCLE", ["20,20", "5"])
    check(phase, "CIRCLE center+radius", r.ok, r.summary)
    circle = doc.get(r.created[0])
    check(phase, "CIRCLE geometry exact",
          circle.center == (20.0, 20.0, 0.0)
          and abs(circle.radius - 5.0) < 1e-9,
          f"c={circle.center} r={circle.radius}")
    circle_id = circle.id

    r = bcshell.run_scripted("ARC", ["20,30", "10,40", "0,30"])
    check(phase, "ARC 3-point method", r.ok, r.summary)
    arc = doc.get(r.created[0])
    check(phase, "ARC geometry exact",
          all(abs(a - b) < 1e-9 for a, b in zip(arc.center, (10.0, 30.0, 0.0)))
          and abs(arc.radius - 10.0) < 1e-9
          and abs(arc.start_angle - 0.0) < 1e-9
          and abs(arc.end_angle - 180.0) < 1e-9,
          f"c={arc.center} r={arc.radius} {arc.start_angle}-{arc.end_angle}")
    check(phase, "session doc_version after draw commands", doc.doc_version == 4,
          doc.doc_version)

    r = bcshell.run_scripted(
        "MOVE", [selection_input(line_ids), "0,0", "5,5"])
    check(phase, "MOVE via command interface", r.ok and r.modified == line_ids,
          r.summary)
    l1 = doc.get(line_ids[0])
    check(phase, "MOVE geometry exact",
          l1.p1 == (5.0, 5.0, 0.0) and l1.p2 == (15.0, 5.0, 0.0), f"{l1.p1}-{l1.p2}")

    # trailing "" = Enter, accepting the <Exit> default (AutoCAD-familiar:
    # Enter ends the multiple-copy loop instead of aborting)
    r = bcshell.run_scripted(
        "COPY", [selection_input([circle_id]), "20,20", "30,20", ""])
    check(phase, "COPY via command interface", r.ok and len(r.created) == 1,
          r.summary)
    if not r.ok:
        return
    copy_circle = doc.get(r.created[0])
    check(phase, "COPY new id + geometry exact",
          copy_circle.id != circle_id
          and copy_circle.center == (30.0, 20.0, 0.0)
          and abs(copy_circle.radius - 5.0) < 1e-9
          and doc.get(circle_id).center == (20.0, 20.0, 0.0),
          f"copy c={copy_circle.center}")
    copy_id = copy_circle.id

    r = bcshell.run_scripted("ERASE", [selection_input([copy_id])])
    check(phase, "ERASE via command interface",
          r.ok and r.removed == [copy_id], r.summary)
    check(phase, "ERASE removed from document", doc.count_by_kind()
          == {"line": 2, "circle": 1, "arc": 1}, doc.count_by_kind())

    r = bcshell.run_scripted("UNDO", [])
    check(phase, "UNDO restores erased entity", r.ok
          and doc.get(copy_id) is not None, r.summary)
    r = bcshell.run_scripted("REDO", [])
    check(phase, "REDO re-removes", r.ok
          and doc.count_by_kind() == {"line": 2, "circle": 1, "arc": 1},
          r.summary)
    check(phase, "doc_version after full command battery", doc.doc_version == 9,
          doc.doc_version)
    # 7 committed groups (LINE×2, CIRCLE, ARC, MOVE, COPY, ERASE) — UNDO pops
    # one, REDO re-commits it as a new group: back to 7, redo empty.
    check(phase, "undo depth tracks every committed transaction",
          doc.undo_depth() == 7 and doc.redo_depth() == 0,
          f"undo={doc.undo_depth()} redo={doc.redo_depth()}")

    # -- 4. typed command-line operator dispatch (headless execute path) ----
    res = bpy.ops.bcshell.cmdline("EXEC_DEFAULT", token="circle 40,40 2")
    check(phase, "bcshell.cmdline operator dispatch", res == {"FINISHED"}, res)
    check(phase, "cmdline-created circle geometry",
          doc.count_by_kind().get("circle") == 2
          and doc.entities()[-1].center == (40.0, 40.0, 0.0),
          doc.count_by_kind())

    # -- 5. display sync ------------------------------------------------------
    collection = bpy.data.collections.get("BlenderCAD")
    check(phase, "display collection BlenderCAD", collection is not None)
    doc_ids = {e.id for e in doc.entities()}
    objects = list(collection.objects) if collection else []
    check(phase, "one display object per entity", len(objects) == len(doc_ids),
          f"{len(objects)} objects / {len(doc_ids)} entities")
    prop_ok = all(obj.get("bcdoc_id") in doc_ids for obj in objects)
    check(phase, "display objects carry bcdoc_id custom prop", prop_ok)
    # display deletion NEVER touches the document (doc-model §7 invariant 3):
    # removing a display object leaves all 5 entities intact, and the same
    # sync the on_change hook uses fully regenerates the display from the doc.
    victim = objects[0]
    bpy.data.objects.remove(victim)
    check(phase, "display deletion leaves document untouched",
          len(doc.entities()) == len(doc_ids),
          f"{len(doc.entities())} entities")
    from bcshell import sync
    stats = sync.sync_display(doc)
    check(phase, "display regenerates from document",
          len(collection.objects) == len(doc.entities()) == len(doc_ids),
          f"rebuilt {stats['objects']} objects")

    # -- 6. native Blender still works ---------------------------------------
    res = bpy.ops.mesh.primitive_cube_add()
    check(phase, "native bpy.ops.mesh.primitive_cube_add", res == {"FINISHED"}, res)
    cubes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    check(phase, "native cube in scene", len(cubes) >= 1, len(cubes))
    check(phase, "CAD display collection unaffected by native ops",
          "BlenderCAD" in bpy.data.collections
          and bpy.data.collections["BlenderCAD"].library is None)

    # -- 7. DXF round-trip inside Blender -------------------------------------
    import bcio
    dxf_path = os.path.join(TMP_DIR, "driver_roundtrip.dxf")
    stats = bcio.export_dxf(dxf_path, doc)
    imported, import_stats = bcio.import_dxf(dxf_path)
    mismatch = same_entities(
        [entity_signature(e) for e in doc.entities()],
        [entity_signature(e) for e in imported.entities()],
        compare_ids=False,
    )
    check(phase, "DXF round-trip document compare (in Blender)",
          mismatch is None, mismatch or
          f"engine={stats.get('engine')}/{import_stats.get('engine')} "
          f"losses={len(stats.get('losses', []))}")
    check(phase, "DXF round-trip stats recorded",
          stats.get("engine") in ("ezdxf", "r12-minimal")
          and import_stats.get("engine") in ("ezdxf", "r12-minimal"),
          f"export={stats.get('engine')} import={import_stats.get('engine')}")
    RESULTS["dxf_engine"] = import_stats.get("engine")

    # -- 8. save/reopen gate preparation ---------------------------------------
    signature = document_signature(doc)
    blend_path = os.path.join(TMP_DIR, "blender_cad_driver.blend")
    res = bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    check(phase, ".blend saved", res == {"FINISHED"}
          and os.path.isfile(blend_path), blend_path)
    text_block = bpy.data.texts.get("blender_cad_document.json")
    check(phase, "persistence text block in bpy.data.texts", text_block is not None)
    # bcdoc v2 (M2, contracts §2.7): the serialized schema literal is
    # bcdoc/2 (load still accepts legacy bcdoc/1 — checked by the
    # document suite, not here).
    check(phase, "text block content is bcdoc/2 JSON",
          text_block is not None
          and text_block.as_string().startswith('{"schema": "bcdoc/2"'))
    RESULTS["phases"][phase]["blend"] = blend_path
    RESULTS["phases"][phase]["document"] = signature

    # -- 9. clean unload -------------------------------------------------------
    bcshell.unregister()
    check(phase, "unregister clears flag", bcshell.registered is False)
    gone = [n for n in op_names if hasattr(bpy.types, n)]
    check(phase, "unregister removes operators", not gone,
          f"left: {gone}" if gone else "all gone")
    check(phase, "unregister removes keymap",
          keymaps.active_keymap_name() is None)
    check(phase, "unregister removes handlers", not handlers.installed())
    bcshell.unregister()
    check(phase, "second unregister is safe", bcshell.registered is False)


# ---------------------------------------------------------------------------
# phase: reopen
# ---------------------------------------------------------------------------

def phase_reopen():
    phase = "reopen"
    blend_path = _argv_value("--blend")
    if not blend_path:
        with open(RESULT_PATH, "r", encoding="utf-8") as handle:
            blend_path = RESULTS["phases"].get("main", {}).get("blend")
    if not blend_path or not os.path.isfile(blend_path):
        check(phase, "reopen needs the saved .blend path", False, str(blend_path))
        return

    import bcshell
    bcshell.register()
    check(phase, "fresh-process register", bcshell.registered is True)

    res = bpy.ops.wm.open_mainfile(filepath=blend_path)
    check(phase, "bpy.ops.wm.open_mainfile", res == {"FINISHED"}, res)

    # the load_post handler must have restored the document
    doc = bcshell.session.active_document()
    text_block = bpy.data.texts.get("blender_cad_document.json")
    check(phase, "load_post restored persistence text block",
          text_block is not None)

    with open(RESULT_PATH, "r", encoding="utf-8") as handle:
        saved = json.load(handle)
    expected = saved["phases"]["main"].get("document", {})
    mismatch = same_document(expected, document_signature(doc))
    check(phase, "document restored identical (entities + doc_version)",
          mismatch is None, mismatch or
          f"v{doc.doc_version}, {len(doc.entities())} entities, "
          f"undo {doc.undo_depth()}/redo {doc.redo_depth()}")

    collection = bpy.data.collections.get("BlenderCAD")
    objects = list(collection.objects) if collection else []
    doc_ids = {e.id for e in doc.entities()}
    check(phase, "display synced after reopen",
          collection is not None and len(objects) == len(doc_ids)
          and all(obj.get("bcdoc_id") in doc_ids for obj in objects),
          f"{len(objects)} objects / {len(doc_ids)} entities")

    # the restored document is LIVE: undo journal survived the round-trip
    before = doc.doc_version
    r = bcshell.run_scripted("UNDO", [])
    check(phase, "restored document is live (UNDO works after reopen)",
          r.ok and doc.doc_version == before + 1, r.summary)
    r = bcshell.run_scripted("REDO", [])
    check(phase, "REDO after reopen", r.ok and doc.doc_version == before + 2,
          r.summary)

    bcshell.unregister()
    check(phase, "reopen-phase clean unload", bcshell.registered is False)
    bcshell.unregister()
    check(phase, "reopen-phase second unregister safe",
          bcshell.registered is False)


# ---------------------------------------------------------------------------

def main():
    phase = _argv_value("--phase", "main")
    RESULTS["driver_phase"] = phase
    if phase == "main":
        # a fresh main run invalidates any previous reopen evidence (its
        # blend lives in a per-run tmp dir) — start the JSON from scratch.
        phase_main()
    elif phase == "reopen":
        # keep the main phase's evidence (blend path + document signature)
        # from the prior run in the merged result JSON.
        if os.path.exists(RESULT_PATH):
            try:
                with open(RESULT_PATH, "r", encoding="utf-8") as handle:
                    prior = json.load(handle)
                if "main" in prior.get("phases", {}):
                    RESULTS["phases"]["main"] = prior["phases"]["main"]
                if "dxf_engine" in prior:
                    RESULTS["dxf_engine"] = prior["dxf_engine"]
            except (ValueError, OSError):
                pass
        phase_reopen()
    else:
        check("boot", f"unknown phase {phase!r}", False)
    write_results()
    failed = sum(p.get("failed", 0) for p in RESULTS["phases"].values())
    total = sum(len(p.get("checks", [])) for p in RESULTS["phases"].values())
    print(f"DRIVER RESULT ({phase}): "
          f"{'PASS' if failed == 0 else 'FAIL'} — {total - failed}/{total} checks")
    if failed:
        sys.exit(1)


main()
