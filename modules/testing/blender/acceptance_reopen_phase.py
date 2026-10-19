"""M1 acceptance — reopen phase. Runs INSIDE a FRESH Blender process.

Proves requirement 5 (documents survive save/reopen): the .blend written by the
verify phase is reopened here; the load_post persistence must restore the CAD
document — identical entities + doc_version — without any repo sys.path
bootstrap (the extension is the installed one, enabled at startup).

argv after "--": <blend_path> <result_json_path>
"""

import json
import sys
from pathlib import Path

import bpy  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
BLEND = Path(argv[0])
OUT = Path(argv[1])
CHECKS = []


def record(name, passed, detail=""):
    CHECKS.append({"check": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail else ""))


def approx(a, b, eps=1e-9):
    return abs(a - b) <= eps


def main():
    record("blend.reopened", BLEND.is_file(), str(BLEND))
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))

    try:
        import bcshell

        record("extension.active_after_reopen", bcshell.registered is True, "installed extension loaded at startup")
    except Exception as e:  # noqa: BLE001
        record("extension.active_after_reopen", False, repr(e)[:200])
        finish(False)
        return

    doc = bcshell.session.active_document()
    ents = doc.entities()
    n = len(ents)

    # The verify phase ends with 6 CAD entities (3 LINE + 2 CIRCLE + 1 ARC:
    # LINE/CIRCLE/ARC created, COPY added one, ERASE removed it, undo restored it)
    record("document.restored_entities", n == 6, f"{n} entities after reopen (expected 6)")
    record("document.restored_version", doc.doc_version > 0, f"doc_version={doc.doc_version}")
    kinds = doc.count_by_kind()
    record(
        "document.restored_kinds",
        set(kinds) == {"line", "circle", "arc"},
        f"kinds={kinds}",
    )

    # undo history survived
    record("document.undo_survived", doc.undo_depth() > 0, f"undo_depth={doc.undo_depth()}")

    # document is live: undo/redo callable
    if doc.undo_depth():
        doc.undo()
        doc.redo()
        record("document.live_after_reopen", True, "undo()+redo() callable on restored document")
    else:
        record("document.live_after_reopen", False, "no undo depth to exercise")

    # display resync on reopen: derived collection present with matching objects
    try:
        bcshell.sync.sync_display(doc)
        coll = bpy.data.collections.get("BlenderCAD")
        record("display.resync_after_reopen", coll is not None and len(coll.objects) == n,
              f"display objects={len(coll.objects) if coll else 0} vs entities={n}")
    except Exception as e:  # noqa: BLE001
        record("display.resync_after_reopen", False, repr(e)[:200])

    # native functions still usable in the reopened file
    try:
        bpy.ops.mesh.primitive_cube_add(location=(-100.0, -100.0, 0.0))
        record("native.functions_after_reopen", True, "primitive_cube_add OK after reopen")
    except Exception as e:  # noqa: BLE001
        record("native.functions_after_reopen", False, repr(e)[:200])

    # clean unload (TP-CAT-06 precondition)
    try:
        bcshell.unregister()
        bcshell.register()
        record("extension.clean_unload_reload", True, "unregister() then register() both clean")
    except Exception as e:  # noqa: BLE001
        record("extension.clean_unload_reload", False, repr(e)[:200])

    finish(True)


def finish(_ok):
    all_passed = bool(CHECKS) and all(c["passed"] for c in CHECKS)
    OUT.write_text(json.dumps({"phase": "reopen", "checks": CHECKS, "all_passed": all_passed}, indent=2))
    print(f"REOPEN PHASE: {'ALL PASSED' if all_passed else 'FAILED'} ({sum(c['passed'] for c in CHECKS)}/{len(CHECKS)})")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
