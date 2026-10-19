"""bcshell.ui — the BlenderCAD N-panel (View3D sidebar) + status line.

Panel layout (contract §6.2/§6.3 + v2 §7): document info (name, doc_version,
entity counts, undo/redo depth), the prompt/status line (pending Request
text + dynamic distance/angle overlay), action buttons — Open CAD Workspace,
Command Line, DXF Import/Export, Save/Load JSON, Undo/Redo, Document Info —
the recent feedback echo, and the v2 sections:

* "Layers" — one row per layer (capped at 32 visible, "+N more" label):
  the layer-name button sets it current (current layers carry the radio
  indicator), and per-row On / Freeze / Lock toggles map to
  ``bcshell.layer_toggle``;
* "Layout / Space" — the current space label, one Activate button per
  layout (+ MODEL) and the New Layout button (``bcshell.layout_new``);
* "Precision" — running-osnap checkboxes (Endpoint / Midpoint / Center /
  Quadrant / Intersection / Perpendicular / Tangent → OSMODE bits via
  ``bcshell.osnap_toggle``) and the ORTHO / GRID / SNAP / DYN setting
  toggles (``bcshell.setting_toggle``).

Every control is a working operator (no dead UI): buttons carry the
current state through icons; mutations run through the same journaled /
settings paths the commands use and resync the display.

Every button's operator is registered and invocable in background mode
(headless drivers call each with EXEC_DEFAULT / INVOKE_DEFAULT).
"""

from __future__ import annotations

import bpy

#: how many layer rows the panel draws before the "+N more" label
LAYER_ROW_CAP = 32

#: how many layout rows the panel draws (layouts are few; defensive cap)
LAYOUT_ROW_CAP = 16

#: osnap mode label -> OSMODE bit (contract §2.5; the P0 panel set)
OSNAP_PANEL_BITS = (
    ("Endpoint", 1), ("Midpoint", 2), ("Center", 4), ("Quadrant", 16),
    ("Intersection", 32), ("Perpendicular", 128), ("Tangent", 1024),
)

#: setting-toggle rows: (label, sysvar name)
SETTING_PANEL_TOGGLES = (
    ("Ortho", "ORTHOMODE"), ("Grid", "GRIDMODE"),
    ("Snap", "SNAPMODE"), ("Dyn", "DYNMODE"),
)


class BLENDERCAD_PT_main(bpy.types.Panel):
    """BlenderCAD: document info + commands + v2 layers/layouts/precision + feedback"""

    bl_idname = "BLENDERCAD_PT_main"
    bl_label = "BlenderCAD"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlenderCAD"

    def draw(self, context):
        from . import session

        layout = self.layout
        info = session.status()
        panel = session.panel_state()

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

        # -- v2 section: Layers (contract §7) -----------------------------------
        box = layout.box()
        box.label(text="Layers", icon="OUTLINER")
        layers = panel.get("layers", [])
        for record in layers[:LAYER_ROW_CAP]:
            row = box.row(align=True)
            name_op = row.operator(
                "bcshell.layer_set_current",
                text=record["name"],
                icon="RADIOBUT_ON" if record["current"] else "RADIOBUT_OFF",
            )
            name_op.name = record["name"]
            on_op = row.operator(
                "bcshell.layer_toggle", text="On",
                icon="CHECKBOX_HLT" if record["on"] else "CHECKBOX_UNHLT",
            )
            on_op.name = record["name"]
            on_op.prop = "on"
            frozen_op = row.operator(
                "bcshell.layer_toggle", text="Frz",
                icon="CHECKBOX_HLT" if record["frozen"] else "CHECKBOX_UNHLT",
            )
            frozen_op.name = record["name"]
            frozen_op.prop = "frozen"
            lock_op = row.operator(
                "bcshell.layer_toggle", text="Lock",
                icon="CHECKBOX_HLT" if record["locked"] else "CHECKBOX_UNHLT",
            )
            lock_op.name = record["name"]
            lock_op.prop = "locked"
        if len(layers) > LAYER_ROW_CAP:
            box.label(text=f"+{len(layers) - LAYER_ROW_CAP} more layers…",
                      icon="DOT")

        # -- v2 section: Layout / Space (contract §7) ---------------------------
        box = layout.box()
        box.label(
            text=f"Space: {panel.get('current_space') or 'MODEL'}",
            icon="WORLD",
        )
        spaces = ["MODEL"] + list(panel.get("layouts", []))[:LAYOUT_ROW_CAP]
        for name in spaces:
            current = panel.get("current_space") == name
            row = box.row(align=True)
            op = row.operator(
                "bcshell.layout_activate", text=name,
                icon="RADIOBUT_ON" if current else "RADIOBUT_OFF",
            )
            op.name = name
        box.operator("bcshell.layout_new", text="New Layout", icon="ADD")

        # -- v2 section: Precision (contract §7) ----------------------------------
        box = layout.box()
        box.label(text="Precision", icon="SNAP_ON")
        osmode = int(panel.get("osmode", 0))
        for label, bit in OSNAP_PANEL_BITS:
            row = box.row(align=True)
            op = row.operator(
                "bcshell.osnap_toggle", text=label,
                icon="CHECKBOX_HLT" if osmode & bit else "CHECKBOX_UNHLT",
            )
            op.bit = bit
            op.mode = label.upper()
        settings = panel.get("settings", {})
        row = box.row(align=True)
        for label, name in SETTING_PANEL_TOGGLES:
            value = int(settings.get(name, 0))
            op = row.operator(
                "bcshell.setting_toggle", text=label,
                icon="CHECKBOX_HLT" if value else "CHECKBOX_UNHLT",
            )
            op.name = name

        # -- feedback echo (last messages) ---------------------------------------
        messages = info.get("feedback", [])
        if messages:
            box = layout.box()
            box.label(text="Command line:")
            for message in messages[-5:]:
                box.label(text=message[:80])


classes = (BLENDERCAD_PT_main,)
