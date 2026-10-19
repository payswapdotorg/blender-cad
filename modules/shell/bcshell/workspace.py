"""bcshell.workspace — the "BlenderCAD" Blender workspace (contract §6.2).

``ensure_workspace()`` creates the workspace when absent. Blender 5.2 has NO
``bpy.data.workspaces.new()`` (verified on the 5.2.2 pinned build:
``AttributeError: bpy_prop_collection: attribute "new" not found``) — the
supported creation path is the ``bpy.ops.workspace.duplicate()`` operator
(duplicating the active window's workspace), after which the new workspace
is renamed to "BlenderCAD". The operator works in background mode
(returns ``{'FINISHED'}`` under ``--background``, verified on 5.2.2), but
``window.workspace`` does NOT change headless — the new workspace is
therefore detected by diffing ``bpy.data.workspaces`` names before/after
(verified headless).

Top orthographic view: every 3D viewport space in the workspace's screens
gets ``region_3d.view_perspective = 'ORTHO'`` and the identity view rotation
(+ a sensible view distance) — the identity rotation IS Blender's Top view
(looking along −Z with +Y up).

Activating the workspace (``window.workspace = ws``) is attempted in
:func:`activate` and silently skipped when it does not stick (background
mode); the workspace still EXISTS in ``bpy.data.workspaces``, which is the
M1 acceptance criterion (m1-module-contracts §11).
"""

from __future__ import annotations

WORKSPACE_NAME = "BlenderCAD"

#: default view distance for a fresh CAD top view
TOP_VIEW_DISTANCE = 80.0


def ensure_workspace():
    """Get or create the "BlenderCAD" workspace, configured top-ortho."""
    import bpy

    workspace = bpy.data.workspaces.get(WORKSPACE_NAME)
    if workspace is None:
        workspace = _create_workspace(bpy)
    _configure_screens(workspace)
    return workspace


def activate(workspace=None):
    """Activate the workspace in the ACTIVE window (GUI only)."""
    import bpy

    ws = workspace if workspace is not None else ensure_workspace()
    window = getattr(bpy.context, "window", None)
    if window is None:
        windows = getattr(bpy.context.window_manager, "windows", [])
        window = windows[0] if windows else None
    if window is not None:
        try:
            window.workspace = ws
        except Exception:
            pass  # headless assignment does not stick (verified) — skip
    return ws


def _create_workspace(bpy):
    """Create the workspace by duplicating the active one (the only
    supported Blender 5.2 creation path) and renaming it.

    The new workspace is detected by name-diffing ``bpy.data.workspaces``
    around the operator call: in background mode the operator finishes but
    ``window.workspace`` stays unchanged (verified on 5.2.2), so the window's
    active-workspace probe is unusable headless.
    """
    window = getattr(bpy.context, "window", None)
    if window is None:
        windows = getattr(bpy.context.window_manager, "windows", [])
        if not windows:
            raise RuntimeError(
                "cannot create workspace: no Blender window available"
            )
        window = windows[0]
    before_names = {ws.name for ws in bpy.data.workspaces}
    result = bpy.ops.workspace.duplicate()
    if result != {"FINISHED"}:
        raise RuntimeError(f"bpy.ops.workspace.duplicate() failed: {result!r}")
    new_workspaces = [
        ws for ws in bpy.data.workspaces if ws.name not in before_names
    ]
    if not new_workspaces:
        raise RuntimeError("workspace duplication produced no new workspace")
    new_workspace = new_workspaces[0]
    new_workspace.name = WORKSPACE_NAME
    return bpy.data.workspaces.get(WORKSPACE_NAME)


def _configure_screens(workspace) -> None:
    """Top orthographic view for every VIEW_3D space in the workspace."""
    import bpy
    from mathutils import Quaternion

    for screen in workspace.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                region_3d = getattr(space, "region_3d", None)
                if region_3d is None:
                    continue
                region_3d.view_perspective = "ORTHO"
                # identity rotation == Blender Top view (verified on 5.2.2)
                region_3d.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
                region_3d.view_location = (0.0, 0.0, 0.0)
                region_3d.view_distance = TOP_VIEW_DISTANCE
