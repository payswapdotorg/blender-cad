"""bcshell.ui — the BlenderCAD N-panel (View3D sidebar) + status line.

Panel layout (contract §6.2/§6.3): document info (name, doc_version, entity
counts, undo/redo depth), the prompt/status line (pending Request text +
dynamic distance/angle overlay), action buttons — Open CAD Workspace,
Command Line, DXF Import/Export, Save/Load JSON, Undo/Redo, Document Info —
and the recent feedback messages (the command-line dock echo).

Every button's operator is registered and invocable in background mode
(headless driver calls each with EXEC_DEFAULT / INVOKE_DEFAULT).
"""

from __future__ import annotations

import bpy


class BLENDERCAD_PT_main(bpy.types.Panel):
    """BlenderCAD: document info + commands + feedback echo"""

    bl_idname = "BLENDERCAD_PT_main"
    bl_label = "BlenderCAD"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlenderCAD"

    def draw(self, context):
        from . import session

        layout = self.layout
        info = session.status()

        # -- prompt / dynamic input line (the status bar of the command line)
        prompt = info.get("prompt", "Command:")
        dynamic = info.get("dynamic", "")
        row = layout.row()
        row.label(text=prompt, icon="CONSOLE")
        if dynamic:
            row = layout.row()
            row.label(text=dynamic, icon="ORIENTATION_CURSOR")

        # -- document block ----------------------------------------------------
        if not info.get("registered_document", False):
            layout.label(text="No document (not registered)", icon="ERROR")
            return
        box = layout.box()
        box.label(text=f"Document: {info['name']}", icon="FILE_TEXT")
        box.label(text=f"Version: {info['doc_version']}")
        counts = info.get("counts", {})
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        box.label(text=f"Entities: {info['entities']}" + (f" ({kinds})" if kinds else ""))
        box.label(
            text=f"Undo: {info['undo_depth']}   Redo: {info['redo_depth']}"
        )

        # -- actions -----------------------------------------------------------
        col = layout.column(align=True)
        col.operator("bcshell.workspace_open", text="Open CAD Workspace",
                     icon="WORKSPACE")
        col.operator("bcshell.cmdline", text="Command Line (Ctrl+Space)",
                     icon="CONSOLE")
        col.separator()
        row = col.row(align=True)
        row.operator("bcshell.dxf_import", text="Import DXF", icon="IMPORT")
        row.operator("bcshell.dxf_export", text="Export DXF", icon="EXPORT")
        row = col.row(align=True)
        row.operator("bcshell.doc_save_json", text="Save JSON", icon="SAVE_AS")
        row.operator("bcshell.doc_load_json", text="Load JSON", icon="OPEN_NEW")
        col.separator()
        row = col.row(align=True)
        row.operator("bcshell.undo", text="Undo", icon="LOOP_BACK")
        row.operator("bcshell.redo", text="Redo", icon="LOOP_FORWARDS")
        row = col.row(align=True)
        row.operator("bcshell.doc_info", text="Refresh Info", icon="INFO")

        # -- feedback echo (last messages) ---------------------------------------
        messages = info.get("feedback", [])
        if messages:
            box = layout.box()
            box.label(text="Command line:")
            for message in messages[-5:]:
                box.label(text=message[:80])


classes = (BLENDERCAD_PT_main,)
