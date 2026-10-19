"""bcshell.sync — document → scene display sync (contract §6.2, one-way).

The Blender scene is DERIVED data (document-model doc §2 invariant 3):
every entity maps to one display object in the collection "BlenderCAD"
carrying the custom property ``bcdoc_id``; deleting display objects never
touches the document — the next sync rebuilds them (scene can always be
regenerated from the document).

Headless-testable core: :func:`entity_display_spec` computes the pure
display description of one bcdoc entity (name, polyline points, cyclic
flag). The Blender-facing :func:`sync_display` consumes it and (re)builds
curve objects. bpy is imported lazily so THIS module imports under plain
pytest (the pure helper is covered by modules/shell/tests).

Honest v0 budget note: ``sync_display`` is a FULL rebuild after every
committed transaction. Fine up to roughly 200 entities (measured behavior
target: < 16 ms budget applies from M3 — TP-CAT-02/06); beyond that the
rebuild is still correct but interactive-frame sync needs the incremental
dirty-set path planned for M2 (document-model doc §8 "Sync granularity").
"""

from __future__ import annotations

from typing import Dict, List

#: display collection name (contract §6.2)
COLLECTION_NAME = "BlenderCAD"

#: custom property linking a display object to its document entity
ID_PROP = "bcdoc_id"

#: arc sampling density for display polylines (32 segments per full sweep)
ARC_SEGMENTS = 32


# ---------------------------------------------------------------------------
# pure helpers (no bpy — headless-testable)
# ---------------------------------------------------------------------------

def entity_display_spec(entity) -> Dict:
    """Pure display description for one bcdoc entity.

    Returns ``{"name": str, "kind": str, "bcdoc_id": str, "points": [(x,y,z)..],
    "cyclic": bool}``. Mapping per contract §6.2:

    * line  → two-point polyline (non-cyclic)
    * circle→ cyclic 4-point curve (points at 0/90/180/270°) — a deliberate
      coarse display approximation at v0; the authoritative geometry stays
      exact in the document and finer tessellation is M2+ display work
    * arc   → non-cyclic polyline sampled CCW start→end (ARC_SEGMENTS)
    """
    kind = getattr(entity, "kind", "")
    points: List = []
    cyclic = False
    if kind == "line":
        points = [tuple(entity.p1), tuple(entity.p2)]
    elif kind == "circle":
        cx, cy, cz = entity.center
        r = float(entity.radius)
        points = [
            (cx + r, cy, cz),
            (cx, cy + r, cz),
            (cx - r, cy, cz),
            (cx, cy - r, cz),
        ]
        cyclic = True
    elif kind == "arc":
        from bcdraft.geometry import arc_points

        points = arc_points(
            entity.center, entity.radius,
            entity.start_angle, entity.end_angle, segments=ARC_SEGMENTS,
        )
    else:
        raise ValueError(f"no display mapping for entity kind {kind!r}")
    return {
        "name": f"BC_{kind.capitalize()}_{entity.handle}",
        "kind": kind,
        "bcdoc_id": entity.id,
        "points": [(float(p[0]), float(p[1]), float(p[2])) for p in points],
        "cyclic": cyclic,
    }


# ---------------------------------------------------------------------------
# Blender-facing rebuild (bpy lazily imported)
# ---------------------------------------------------------------------------

def ensure_collection():
    """Get or create the display collection (linked to the scene)."""
    import bpy

    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
    scene = bpy.context.scene
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def _remove_objects(collection, objects) -> None:
    import bpy

    for obj in objects:
        try:
            if obj.name in collection.objects:
                collection.objects.unlink(obj)
            bpy.data.objects.remove(obj)
        except ReferenceError:
            pass  # already gone


def _build_object(spec: Dict):
    """Create the display curve object for one display spec."""
    import bpy

    curve = bpy.data.curves.new(name=spec["name"], type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(count=len(spec["points"]) - 1)  # new() starts with 1
    for point, coord in zip(spline.points, spec["points"]):
        point.co = (coord[0], coord[1], coord[2], 1.0)
    spline.use_cyclic_u = spec["cyclic"]
    spline.type = "POLY"
    obj = bpy.data.objects.new(spec["name"], curve)
    obj[ID_PROP] = spec["bcdoc_id"]
    return obj


def sync_display(doc) -> Dict:
    """Rebuild the whole display collection from ``doc`` (one-way derived).

    Returns a small stats dict: ``{"objects": n, "entities": n}``.
    Display deletions never touch the document: this full rebuild simply
    regenerates whatever is missing.
    """
    import bpy

    collection = ensure_collection()
    _remove_objects(collection, list(collection.objects))
    count = 0
    for entity in doc.entities():
        spec = entity_display_spec(entity)
        obj = _build_object(spec)
        collection.objects.link(obj)
        count += 1
    return {"objects": count, "entities": len(doc.entities())}


def clear_display() -> None:
    """Delete every display object (document untouched by definition)."""
    import bpy

    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is not None:
        _remove_objects(collection, list(collection.objects))


def display_ids_in_scene_selection() -> List[str]:
    """Document ids of BlenderCAD display objects that are selected.

    v0 selection mechanism (honest scope, documented per contract §6.2):
    the modal operator and operators that need the document selection call
    this; a msgbus/DEG-driven automatic sync of Blender's viewport
    selection into ``document.selection`` is M2 UX work. Objects outside
    the display collection are ignored (blender-native data is never
    claimed by the CAD layer — document-model doc §7.2 rule 5).
    """
    import bpy

    ids = []
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        return ids
    for obj in collection.objects:
        if obj.select_get():
            entity_id = obj.get(ID_PROP)
            if entity_id:
                ids.append(str(entity_id))
    return ids
