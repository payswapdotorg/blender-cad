"""bcshell.ops — Blender operators (contract §6.3) + the scripted headless
entry point.

Two ways drive the SAME command machinery (contract §4/§6.2):

* :class:`BCSHELL_OT_command_run` — the MODAL viewport operator. It holds a
  ``bccmd.StepDriver`` (the step-by-step driver of the same steps-generator
  the blocking Runner executes), collects one InputValue per event (mouse
  clicks → points on z=0 via pick.py tagged ``source="mouse"`` — the v2
  precision engine consumes that flag; typed text →
  ``bccmd.input.parse``), records ``ctx.pointer`` on every mouse move (the
  DDE/ortho direction data source, contracts §3/§7), draws the rubberband +
  dynamic distance/angle overlay, and finishes when the CommandResult is
  produced. Esc → ``Cancelled`` → clean finish.
* :func:`run_scripted` — the headless/acceptance path:
  ``Registry.run_command(ctx, name, provider=ScriptedProvider(ctx, inputs))``
  — the identical registry + prompt-loop + StepDriver machinery, just fed by
  a scripted provider instead of viewport events. NOT a reimplementation.

When no interactive viewport context exists (background mode), the modal
operator transparently runs the scripted path with the ``preset`` inputs:
in ``--background`` Blender routes every operator call — INVOKE_DEFAULT
included — to ``execute()`` (verified on 5.2.2; invoke-only operators are
rejected with "Invalid operator call" there), so ``execute()`` always drives
``Registry.run_command``. Headless drivers can therefore exercise the
operator end-to-end; only real mouse/pixel rendering is unverifiable
headless.
"""

from __future__ import annotations

import os
from typing import List, Optional

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from bccmd import (
    ACTIVE,
    COLLECTING,
    PREVIEW,
    Cancelled,
    CommandResult,
    ScriptedProvider,
    StepDriver,
    parse as parse_input,
    selection_input,
)
from bccmd.input import InputParseError

from . import panel_ops, pick, session, workspace
from .session import run_scripted  # re-export: the scripted path (bpy-free, in session.py)
from .sync import ID_PROP


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------

class BCSHELL_OT_workspace_open(bpy.types.Operator):
    """Create/activate the BlenderCAD top-ortho workspace"""

    bl_idname = "bcshell.workspace_open"
    bl_label = "Open CAD Workspace"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        ws = workspace.ensure_workspace()
        workspace.activate(ws)
        self.report({"INFO"}, f"BlenderCAD workspace ready ({ws.name})")
        return {"FINISHED"}

    def execute(self, context):
        return self.invoke(context, None)


# ---------------------------------------------------------------------------
# modal command operator
# ---------------------------------------------------------------------------

class BCSHELL_OT_command_run(bpy.types.Operator):
    """Run a registered CAD command interactively (modal)"""

    bl_idname = "bcshell.command_run"
    bl_label = "Run CAD Command"
    bl_options = {"REGISTER"}

    command: StringProperty(name="Command", default="")
    preset: StringProperty(
        name="Preset inputs",
        description="Space-separated pre-typed inputs, fed in order "
        "(headless drivers use these; interactive mode feeds them before "
        "the first mouse/keyboard event)",
        default="",
    )

    # -- lifecycle ----------------------------------------------------------
    def execute(self, context):
        """Non-modal path: drive the command through ``Registry.run_command``
        with the preset inputs (the SAME machinery the UI uses).

        Background-mode note (verified on Blender 5.2.2): in ``--background``
        Blender runs ``execute()`` for INVOKE_DEFAULT calls too (there is no
        window event loop to run ``invoke()``), and invoke-ONLY operators are
        rejected with "Invalid operator call" — hence this execute() exists
        and always takes the scripted path. In the GUI, INVOKE_DEFAULT runs
        ``invoke()`` (modal path) instead.
        """
        registry = session.get_registry()
        spec = registry.lookup(self.command)
        if spec is None:
            msg = f"Unknown command: {self.command!r}"
            session.feedback_sink(msg)
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self._spec = spec
        self._ctx = session.command_context()
        self._machine = self._ctx.machine
        self._preset_queue: List[str] = self.preset.split()
        return self._headless_scripted()

    def invoke(self, context, event):
        registry = session.get_registry()
        spec = registry.lookup(self.command)
        if spec is None:
            msg = f"Unknown command: {self.command!r}"
            session.feedback_sink(msg)
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}

        self._spec = spec
        self._ctx = session.command_context()
        self._machine = self._ctx.machine
        self._typed = ""
        self._picked_selection: List[str] = []
        self._rubber: Optional[pick.Rubberband] = None
        self._preset_queue: List[str] = self.preset.split()
        self._raw_inputs: List[str] = []
        self._driver: Optional[StepDriver] = None

        if spec.steps is None:
            # Zero-prompt run()-based command (UNDO/REDO): complete now.
            self._machine.begin(spec.name)
            ok = self._finish_runbased()
            return {"FINISHED"} if ok else {"CANCELLED"}

        if context.region is None or context.area is None:
            # No interactive viewport (e.g. invoked without a VIEW_3D context):
            # scripted fallback through the SAME machinery — preset inputs
            # only. run_command performs its own machine discipline.
            return self._headless_scripted()

        self._machine.begin(spec.name)
        self._driver = StepDriver.from_factory(spec.steps, self._ctx)
        request = self._driver.start()

        request = self._drain_preset(request)
        if request is _DONE:
            return {"FINISHED"}

        # interactive modal loop
        self._start_rubberband()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # -- run()-based commands -----------------------------------------------
    def _finish_runbased(self):
        registry = session.get_registry()
        provider = ScriptedProvider(self._ctx, self._preset_queue)
        from bccmd import Runner

        runner = Runner(self._ctx, provider)
        try:
            result = self._spec.run(self._ctx, runner)
        except Cancelled:
            self._machine.cancel()
            result = CommandResult(status="cancelled",
                                    summary=f"{self._spec.name} cancelled")
        except BaseException:
            self._machine.cancel()
            raise
        else:
            self._machine.commit()
            self._machine.finish()
        registry.record(self._ctx, self._spec, result, runner.raw_inputs)
        session.feedback_sink(result.summary)
        session.set_prompt("Command:")
        self.report({"INFO"}, result.summary)
        return result.ok

    # -- headless fallback ---------------------------------------------------
    def _headless_scripted(self):
        """Background mode: drive the command through the SAME scripted
        machinery (session.run_scripted) with the preset inputs."""
        try:
            result = session.run_scripted(self._spec.name, self._preset_queue)
        except Exception as exc:  # command failure etc.
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        session.feedback_sink(result.summary)
        self.report({"INFO"}, result.summary)
        return {"FINISHED"}

    # -- modal event handling ------------------------------------------------
    def modal(self, context, event):
        if self._driver is None:
            return {"FINISHED"}

        if event.type == "MOUSEMOVE":
            return self._on_mousemove(context, event)
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            outcome = self._on_click(context, event)
            return outcome
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._on_enter(context)
        if event.type == "RIGHTMOUSE" and event.value == "PRESS":
            # right-click = accept (AutoCAD enter-equivalent)
            return self._on_enter(context)
        if event.type == "ESC":
            return self._on_escape()
        if event.type == "BACK_SPACE":
            self._typed = self._typed[:-1]
            session.set_prompt(self._prompt_line())
            return {"RUNNING_MODAL"}
        if event.value == "PRESS" and getattr(event, "unicode", ""):
            self._typed += event.unicode
            session.set_prompt(self._prompt_line())
            return {"RUNNING_MODAL"}
        if event.value == "PRESS" and getattr(event, "ascii", ""):
            self._typed += event.ascii
            session.set_prompt(self._prompt_line())
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    # -- event helpers -------------------------------------------------------
    def _on_mousemove(self, context, event):
        request = self._driver.current_request
        if request is not None and request.kind in ("point", "distance", "angle"):
            cursor = pick.point_from_event(event, context)
            if cursor is not None:
                # v2 precision data source (contracts §3/§7): DDE + ortho
                # direction read ctx.pointer — always current on mousemove.
                try:
                    self._ctx.pointer = cursor
                except AttributeError:  # slotted context (defensive) — no data
                    pass
                anchor = self._ctx.last_point
                if self._rubber is not None:
                    self._rubber.update(cursor.to_tuple())
                session.set_prompt(
                    self._prompt_line(),
                    pick.dynamic_readout(
                        anchor.to_tuple() if anchor else None,
                        cursor.to_tuple(),
                    ),
                )
        return {"RUNNING_MODAL"}

    def _on_click(self, context, event):
        request = self._driver.current_request
        if request is None:
            return {"FINISHED"}
        if request.kind == "selection":
            picked = self._pick_entity_under_mouse(context, event)
            if picked is None:
                session.feedback_sink("No CAD entity under the cursor")
                return {"RUNNING_MODAL"}
            if picked not in self._picked_selection:
                self._picked_selection.append(picked)
            session.feedback_sink(
                f"{len(self._picked_selection)} object(s) selected — "
                "Enter to finish"
            )
            return {"RUNNING_MODAL"}
        # point / distance / angle prompts: a click gives a MOUSE-sourced
        # point on z=0 (contracts §3: source="mouse" routes it through the
        # osnap/ortho/grid resolution chain in bcdraft._common.ask_point —
        # W-A's hook, feature-detected via session.mouse_point_input)
        point = pick.point_from_event(event, context)
        if point is None:
            session.feedback_sink("Cursor is off the drawing plane (z=0)")
            return {"RUNNING_MODAL"}
        return self._push(session.mouse_point_input(point.x, point.y, point.z))

    def _on_enter(self, context):
        request = self._driver.current_request
        if request is None:
            return {"FINISHED"}
        if request.kind == "selection":
            return self._push(selection_input(self._picked_selection))
        text = self._typed
        self._typed = ""
        try:
            value = parse_input(text, request, self._ctx.last_point)
        except InputParseError as exc:
            session.feedback_sink(str(exc))
            return {"RUNNING_MODAL"}
        return self._push(value)

    def _on_escape(self):
        if self._driver is not None:
            self._driver.throw(Cancelled())
        return self._finish_cancelled("Command cancelled (Esc)")

    # -- driving -------------------------------------------------------------
    def _drain_preset(self, request):
        """Feed queued preset tokens as if typed + Enter (both modes)."""
        while request is not None and self._preset_queue:
            token = self._preset_queue.pop(0)
            try:
                value = parse_input(token, request, self._ctx.last_point)
            except InputParseError as exc:
                session.feedback_sink(str(exc))
                continue
            if value.raw:
                self._raw_inputs.append(value.raw)
            request = self._driver.push(value)
        if request is None:
            self._complete_result()
            return _DONE
        self._track_request(request)
        return request

    def _push(self, value):
        if value.raw:
            self._raw_inputs.append(value.raw)
        request = None
        try:
            request = self._driver.push(value)
        except Cancelled:
            return self._finish_cancelled(f"{self._spec.name} cancelled")
        except BaseException as exc:
            self._machine.cancel()
            self._cleanup()
            self.report({"ERROR"}, f"{self._spec.name} failed: {exc}")
            raise
        if request is None:
            self._complete_result()
            return {"FINISHED"}
        self._track_request(request)
        return {"RUNNING_MODAL"}

    def _track_request(self, request):
        self._machine.track_request(request)
        if self._machine.state in (ACTIVE, COLLECTING, PREVIEW):
            self._machine.collecting()
        session.set_prompt(self._prompt_line())
        self._picked_selection = []
        if request.kind == "point":
            self._start_rubberband()
        elif request.kind in ("distance", "angle") and self._rubber is None:
            self._start_rubberband()

    def _complete_result(self):
        result = self._driver.result
        if result is None:  # driver cancelled via throw (Esc)
            result = CommandResult(status="cancelled",
                                    summary=f"{self._spec.name} cancelled")
        else:
            self._machine.commit()
            self._machine.finish()
        registry = session.get_registry()
        registry.record(self._ctx, self._spec, result, self._raw_inputs)
        session.feedback_sink(result.summary)
        session.set_prompt("Command:")
        self._cleanup()
        if result.ok:
            self.report({"INFO"}, result.summary)

    def _finish_cancelled(self, message):
        self._machine.cancel()
        result = CommandResult(status="cancelled",
                               summary=f"{self._spec.name} cancelled")
        session.get_registry().record(
            self._ctx, self._spec, result, self._raw_inputs
        )
        session.feedback_sink(message)
        session.set_prompt("Command:")
        self._cleanup()
        self.report({"INFO"}, message)
        return {"FINISHED"}

    # -- rubberband + selection picking --------------------------------------
    def _start_rubberband(self):
        if self._rubber is None:
            self._rubber = pick.Rubberband()
        anchor = self._ctx.last_point
        self._rubber.start(anchor.to_tuple() if anchor else None)

    def _pick_entity_under_mouse(self, context, event):
        try:
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            from bpy_extras import view3d_utils

            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            direction = view3d_utils.region_2d_to_vector_3d(
                region, rv3d, coord
            )
        except Exception:
            return None
        hit = pick.ray_plane_z0(origin, direction)
        if hit is None:
            return None
        # nearest display object by planar distance (v0 pickbox: 0.5 units)
        best = None
        best_dist = 0.5
        from . import sync

        for collection in sync.all_space_collections():
            for obj in collection.objects:
                entity_id = obj.get(ID_PROP)
                if not entity_id:
                    continue
                for co in _object_points(obj):
                    dist = ((co[0] - hit[0]) ** 2 + (co[1] - hit[1]) ** 2) ** 0.5
                    if dist < best_dist:
                        best, best_dist = entity_id, dist
        return str(best) if best is not None else None

    def _prompt_line(self):
        request = self._driver.current_request if self._driver else None
        if request is None:
            return "Command:"
        return f"{request.prompt}" + (f"  [typed: {self._typed}]" if self._typed else "")

    def _cleanup(self):
        """Remove the draw handler ALWAYS (TP-CAT-06)."""
        try:
            if self._rubber is not None:
                self._rubber.finish()
        finally:
            self._rubber = None
            pick.cleanup_all()


def _object_points(obj):
    """Planar display points of one curve object (v0: all spline verts)."""
    try:
        for spline in obj.data.splines:
            for point in spline.points:
                yield point.co[:3]
    except Exception:
        return


_DONE = object()  # sentinel: command already completed


# ---------------------------------------------------------------------------
# command line (typed entry, Ctrl+Space / N-panel)
# ---------------------------------------------------------------------------

class BCSHELL_OT_cmdline(bpy.types.Operator):
    """Type a command (name + optional space-separated inputs).

    v2 behavior (contracts §3/§7): an EMPTY token repeats the last command
    (History.last_command — "Repeat: NAME"); an unknown token reports
    "did you mean:" suggestions when the registry exposes W-A's
    ``Registry.suggestions`` (feature-detected — M1 keeps the plain
    unknown-command message until then)."""

    bl_idname = "bcshell.cmdline"
    bl_label = "Command Line"
    bl_options = {"REGISTER"}

    token: StringProperty(
        name="Command",
        description="Command name or alias, optionally followed by inputs "
        "(e.g. 'line 0,0 10,10'); empty repeats the last command",
        default="",
    )

    def invoke(self, context, event):
        if context.window is not None:
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def execute(self, context):
        resolution = session.resolve_cmdline_token(self.token)
        session.feedback_sink(resolution["message"])
        if resolution["action"] == "run":
            return bpy.ops.bcshell.command_run(
                "INVOKE_DEFAULT", command=resolution["command"],
                preset=resolution["preset"],
            )
        if resolution["action"] == "repeat":
            return bpy.ops.bcshell.command_run(
                "INVOKE_DEFAULT", command=resolution["command"], preset=""
            )
        self.report({"ERROR"}, resolution["message"])
        return {"CANCELLED"}


# ---------------------------------------------------------------------------
# DXF interchange operators (bcio)
# ---------------------------------------------------------------------------

class BCSHELL_OT_dxf_import(bpy.types.Operator):
    """Import a DXF drawing into the active CAD document"""

    bl_idname = "bcshell.dxf_import"
    bl_label = "Import DXF"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")

    filter_glob: StringProperty(
        default="*.dxf", options={"HIDDEN"}, maxlen=255
    )

    def invoke(self, context, event):
        if context.window is not None:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def execute(self, context):
        import bcio

        doc = session.active_document()
        try:
            imported_doc, stats = bcio.import_dxf(self.filepath, doc=doc)
        except Exception as exc:
            self.report({"ERROR"}, f"DXF import failed: {exc}")
            return {"CANCELLED"}
        counts = stats.get("imported", {})
        message = (
            f"Imported {counts.get('total', 0)} entities "
            f"({stats.get('engine', '?')}): "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if k != "total")
        )
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BCSHELL_OT_dxf_export(bpy.types.Operator):
    """Export the active CAD document to DXF"""

    bl_idname = "bcshell.dxf_export"
    bl_label = "Export DXF"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")

    filter_glob: StringProperty(
        default="*.dxf", options={"HIDDEN"}, maxlen=255
    )

    def invoke(self, context, event):
        if context.window is not None:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def execute(self, context):
        import bcio

        doc = session.active_document()
        try:
            stats = bcio.export_dxf(self.filepath, doc)
        except Exception as exc:
            self.report({"ERROR"}, f"DXF export failed: {exc}")
            return {"CANCELLED"}
        message = f"Exported {len(doc.entities())} entities via {stats.get('engine', '?')}"
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# document JSON save/load + undo/redo + info
# ---------------------------------------------------------------------------

class BCSHELL_OT_doc_save_json(bpy.types.Operator):
    """Save the CAD document as bcdoc/3 JSON"""

    bl_idname = "bcshell.doc_save_json"
    bl_label = "Save Document JSON"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        if context.window is not None:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def execute(self, context):
        doc = session.active_document()
        try:
            with open(self.filepath, "w", encoding="utf-8") as handle:
                handle.write(doc.serialize())
        except OSError as exc:
            self.report({"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}
        message = f"Saved {doc.name} (v{doc.doc_version}) to {os.path.basename(self.filepath)}"
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BCSHELL_OT_doc_load_json(bpy.types.Operator):
    """Load a bcdoc/3 (or legacy bcdoc/1/bcdoc/2) JSON document as the active document"""

    bl_idname = "bcshell.doc_load_json"
    bl_label = "Load Document JSON"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        if context.window is not None:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def execute(self, context):
        from bcdoc.document import Document

        try:
            with open(self.filepath, "r", encoding="utf-8") as handle:
                doc = Document.load(handle.read())
        except OSError as exc:
            self.report({"ERROR"}, f"Load failed: {exc}")
            return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Not a valid bcdoc document: {exc}")
            return {"CANCELLED"}
        session.set_active(doc)
        message = f"Loaded {doc.name} (v{doc.doc_version}, {len(doc.entities())} entities)"
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BCSHELL_OT_undo(bpy.types.Operator):
    """Undo the last CAD transaction"""

    bl_idname = "bcshell.undo"
    bl_label = "CAD Undo"
    bl_options = {"REGISTER"}

    def execute(self, context):
        doc = session.active_document()
        if doc.undo():
            message = f"UNDO: one step undone, {doc.undo_depth()} left"
        else:
            message = "UNDO: everything has been undone"
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BCSHELL_OT_redo(bpy.types.Operator):
    """Redo one undone CAD transaction"""

    bl_idname = "bcshell.redo"
    bl_label = "CAD Redo"
    bl_options = {"REGISTER"}

    def execute(self, context):
        doc = session.active_document()
        if doc.redo():
            message = f"REDO: one step redone, {doc.redo_depth()} left"
        else:
            message = "REDO: nothing to redo"
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BCSHELL_OT_doc_info(bpy.types.Operator):
    """Refresh/report the active CAD document status"""

    bl_idname = "bcshell.doc_info"
    bl_label = "CAD Document Info"
    bl_options = {"REGISTER"}

    def execute(self, context):
        doc = session.active_document()
        counts = doc.count_by_kind()
        message = (
            f"{doc.name}: version {doc.doc_version}, "
            f"{len(doc.entities())} entities "
            f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'empty'}), "
            f"undo {doc.undo_depth()}/redo {doc.redo_depth()}"
        )
        session.feedback_sink(message)
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# v2 panel operators — Layers / Layout-Space / Precision (contract §7).
# Every control in the N-panel maps to one of these; the mutation logic
# lives in bcshell.panel_ops (pure, headless-tested) and each operator
# adds: session feedback + Blender report + display resync.
# ---------------------------------------------------------------------------

class BCSHELL_OT_layer_set_current(bpy.types.Operator):
    """Set the current layer (CLAYER) from the panel's layer list"""

    bl_idname = "bcshell.layer_set_current"
    bl_label = "Set Current Layer"
    bl_options = {"REGISTER"}

    name: StringProperty(name="Layer", default="0")

    def execute(self, context):
        doc = session.active_document()
        ok, message = panel_ops.set_current_layer(doc, self.name)
        session.feedback_sink(message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


class BCSHELL_OT_layer_toggle(bpy.types.Operator):
    """Toggle one layer property (on/frozen/locked/plot) — journaled + undoable"""

    bl_idname = "bcshell.layer_toggle"
    bl_label = "Toggle Layer Property"
    bl_options = {"REGISTER"}

    name: StringProperty(name="Layer", default="0")
    prop: EnumProperty(
        name="Property",
        items=(
            ("on", "On", "Layer visibility (off = hidden but hit-testable)"),
            ("frozen", "Frozen", "Frozen layers are hidden + excluded from "
             "selection and osnap"),
            ("locked", "Locked", "Locked layers are visible but not "
             "modifiable"),
            ("plot", "Plot", "Include the layer when plotting/exporting"),
        ),
        default="on",
    )

    def execute(self, context):
        doc = session.active_document()
        record = doc.layers.get(self.name)
        if record is None:
            message = f"Layer not found: {self.name}"
            session.feedback_sink(message)
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        value = not bool(getattr(record, self.prop))
        ok, message = panel_ops.toggle_layer_prop(doc, self.name,
                                                    self.prop, value)
        session.feedback_sink(message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        from . import sync

        sync.sync_display(doc)
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


class BCSHELL_OT_layout_activate(bpy.types.Operator):
    """Activate a space (MODEL or a layout) from the panel's layout list"""

    bl_idname = "bcshell.layout_activate"
    bl_label = "Activate Space"
    bl_options = {"REGISTER"}

    name: StringProperty(name="Space", default="MODEL")

    def execute(self, context):
        doc = session.active_document()
        ok, message = panel_ops.activate_space(doc, self.name)
        session.feedback_sink(message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        from . import sync

        sync.sync_display(doc)
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


class BCSHELL_OT_layout_new(bpy.types.Operator):
    """Create a new paper-space layout and activate it"""

    bl_idname = "bcshell.layout_new"
    bl_label = "New Layout"
    bl_options = {"REGISTER"}

    name: StringProperty(name="Layout", default="Layout1")

    def invoke(self, context, event):
        if context.window is not None:
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def execute(self, context):
        doc = session.active_document()
        ok, message = panel_ops.new_layout(doc, self.name)
        session.feedback_sink(message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        from . import sync

        sync.sync_display(doc)
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


class BCSHELL_OT_setting_toggle(bpy.types.Operator):
    """Toggle a bool-style setting (ORTHO/GRID/SNAP/DYN) — persisted, not journaled"""

    bl_idname = "bcshell.setting_toggle"
    bl_label = "Toggle Setting"
    bl_options = {"REGISTER"}

    name: StringProperty(name="Setting", default="ORTHOMODE")

    def execute(self, context):
        doc = session.active_document()
        ok, message = panel_ops.toggle_setting(doc, self.name)
        session.feedback_sink(message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


class BCSHELL_OT_osnap_toggle(bpy.types.Operator):
    """Toggle one running osnap mode (OSMODE bit XOR)"""

    bl_idname = "bcshell.osnap_toggle"
    bl_label = "Toggle Osnap Mode"
    bl_options = {"REGISTER"}

    bit: IntProperty(name="OSMODE bit", default=1, min=1)
    mode: StringProperty(name="Mode", default="")

    def execute(self, context):
        doc = session.active_document()
        ok, message = panel_ops.toggle_osnap_bit(doc, self.bit, self.mode)
        session.feedback_sink(message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# class registration table
# ---------------------------------------------------------------------------

classes = (
    BCSHELL_OT_workspace_open,
    BCSHELL_OT_command_run,
    BCSHELL_OT_cmdline,
    BCSHELL_OT_dxf_import,
    BCSHELL_OT_dxf_export,
    BCSHELL_OT_doc_save_json,
    BCSHELL_OT_doc_load_json,
    BCSHELL_OT_undo,
    BCSHELL_OT_redo,
    BCSHELL_OT_doc_info,
    BCSHELL_OT_layer_set_current,
    BCSHELL_OT_layer_toggle,
    BCSHELL_OT_layout_activate,
    BCSHELL_OT_layout_new,
    BCSHELL_OT_setting_toggle,
    BCSHELL_OT_osnap_toggle,
)
