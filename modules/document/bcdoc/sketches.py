"""Constrained-sketch document content — schema ``bcdoc/3`` (contract:
docs/00-architecture/m3-module-contracts.md §1/§2; the m3-eval seam
gap list items 1/2/4/5/6).

This module is the document-side half of the design-locked bcdoc-first
seam (m3-eval record §4.3): constraints become first-class journaled,
serialized, undoable document content; the solver stays a STATELESS
compute service that extracts fresh systems per solve and applies back
ONLY via journaled transactions. Nothing here knows about any solver
(the candidate vocabulary is the committed corpus vocabulary, not a
solver's).

Contents:

- :class:`Workplane` — the per-sketch plane description (origin + basis);
- :class:`ConstraintRecord` — one constraint addressing bcdoc entities
  BY ENTITY ID (+ endpoint slot for lines), with the dimensional
  ``value`` and the reference-dimension gating flag ``driven``;
- :class:`JunctionRecord` — the id-stable per-sketch junction map: a
  named "same point" grouping of line endpoints (bcdoc lines carry
  endpoint VALUES, so sharing is coincident-by-value; the junction
  record gives the merged point a stable identity without a second
  geometry store — seam record §2.5);
- :class:`SketchRecord` + :class:`SketchTable` — sketch content wired
  through the SAME transaction/journal/serialization machinery as
  layers/blocks/layouts (m2 §2.8 rules);
- :class:`SolveReport` + :class:`SolveReports` — the session-state
  diagnostics shape (never serialized, never journaled, never bumps
  ``doc_version`` — like selection).

Guards (binding, contract §5): dangling entity refs are refused at
every ref-writing mutation (:class:`errors.DanglingSketchRef`); slot
refs must address line-kind entities; per-sketch c_id/junction_id
uniqueness is enforced; and ``Document.remove`` refuses entities still
referenced by any sketch (:class:`errors.EntityInUse`, the BlockInUse
precedent — the UX layer composes remove-constraint-then-remove-entity
transactions; bcdoc never silently deletes constraints).
"""

from __future__ import annotations

import math
import uuid

from . import errors
from .entities import normalize_point

#: Closed constraint vocabulary (contract §1.2): kind -> (arity, class).
#: "dimensional" kinds REQUIRE a finite ``value`` and carry the driving/
#: reference gate (``driven``); "geometric" kinds take no value and must
#: stay driving. The set is exactly the kinds exercised by the committed
#: evidence (23-case corpus + the seam demonstration + the h2h adapter
#: notes); growth is a schema revision, never a runtime string.
CONSTRAINT_KINDS: dict = {
    # geometric (value must be None, driven must be False)
    "coincident": (2, "geometric"),
    "coincident_origin": (1, "geometric"),
    "horizontal": (1, "geometric"),
    "vertical": (1, "geometric"),
    "parallel": (2, "geometric"),
    "perpendicular": (2, "geometric"),
    "tangent": (2, "geometric"),
    "concentric": (2, "geometric"),
    "midpoint": (2, "geometric"),
    "symmetric": (3, "geometric"),
    # dimensional (value required, driven flag allowed)
    "distance": (2, "dimensional"),
    "length": (1, "dimensional"),
    "radius": (1, "dimensional"),
    "diameter": (1, "dimensional"),
    "angle": (2, "dimensional"),
}

#: Record key order for serialization (pinned, byte-stability contract).
WORKPLANE_KEYS = ("origin", "x_axis", "y_axis")
CONSTRAINT_KEYS = ("c_id", "kind", "refs", "value", "driven")
JUNCTION_KEYS = ("junction_id", "members")
SKETCH_KEYS = ("sketch_id", "name", "workplane", "junctions", "constraints")
#: Solve report key order (agent-boundary JSON; never document content).
REPORT_KEYS = ("sketch_id", "solver", "status", "dof", "failed",
               "redundant", "conflicting", "detail")


def _new_id() -> str:
    """Auto identity (uuid4 hex, like entity ids — same rule, same look)."""
    return uuid.uuid4().hex


def _nonempty_str(value, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    return value


def _coerce_ref(ref) -> dict:
    """Validate + normalize ONE constraint ref (contract §1.2):

    ``{"entity": "<id>"}`` — a whole entity, or
    ``{"entity": "<id>", "slot": 0|1}`` — a line endpoint (0 = p1, 1 = p2), or
    ``{"junction": "<id>"}`` — a junction point of the same sketch.
    """
    if not isinstance(ref, dict):
        raise ValueError(f"constraint ref must be a dict, got {ref!r}")
    if "entity" in ref:
        eid = _nonempty_str(ref["entity"], "ref entity id")
        out = {"entity": eid}
        if "slot" in ref:
            slot = ref["slot"]
            if isinstance(slot, bool) or not isinstance(slot, int) or slot not in (0, 1):
                raise ValueError(f"ref slot must be 0 or 1, got {slot!r}")
            out["slot"] = slot
        return out
    if "junction" in ref:
        jid = _nonempty_str(ref["junction"], "ref junction id")
        return {"junction": jid}
    raise ValueError(f"constraint ref needs an 'entity' or 'junction' key, got {ref!r}")


def _coerce_member(member) -> dict:
    """Validate + normalize ONE junction member (always entity + slot)."""
    ref = _coerce_ref(member)
    if "slot" not in ref:
        raise ValueError(
            f"junction members address line endpoints (need a slot), got {member!r}")
    return ref


def _refs_to_json(refs) -> list:
    return [dict(ref) for ref in refs]


def _workplane_json(workplane: "Workplane") -> dict:
    return {key: list(getattr(workplane, key)) for key in WORKPLANE_KEYS}


class Workplane:
    """The plane a sketch lives in (origin + basis; normal is derived by
    consumers as ``x_axis × y_axis`` — never stored). Default = XY@origin,
    the seam demonstration's fixed plane."""

    __slots__ = ("origin", "x_axis", "y_axis")

    def __init__(self, origin=(0.0, 0.0, 0.0), x_axis=(1.0, 0.0, 0.0),
                 y_axis=(0.0, 1.0, 0.0)):
        self.origin = normalize_point(origin)
        self.x_axis = normalize_point(x_axis)
        self.y_axis = normalize_point(y_axis)
        # exact-zero checks (no epsilon): the workplane is a stored
        # description, not enforced geometry — near-degenerate bases are
        # the adapter's problem, exact zeros are malformed data (§1.1).
        for name in ("x_axis", "y_axis"):
            vec = getattr(self, name)
            if vec == (0.0, 0.0, 0.0):
                raise ValueError(f"workplane {name} must be non-zero")
        cross = (
            self.x_axis[1] * self.y_axis[2] - self.x_axis[2] * self.y_axis[1],
            self.x_axis[2] * self.y_axis[0] - self.x_axis[0] * self.y_axis[2],
            self.x_axis[0] * self.y_axis[1] - self.x_axis[1] * self.y_axis[0],
        )
        if cross == (0.0, 0.0, 0.0):
            raise ValueError("workplane x_axis and y_axis must not be parallel")

    def to_dict(self) -> dict:
        return _workplane_json(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Workplane":
        if not isinstance(data, dict):
            raise ValueError(f"workplane must be a dict, got {data!r}")
        for key in WORKPLANE_KEYS:
            if key not in data:
                raise ValueError(f"workplane record missing key {key!r}")
        try:
            return cls(data["origin"], data["x_axis"], data["y_axis"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"malformed workplane record: {exc}") from None

    def copy(self) -> "Workplane":
        clone = cls = self.__class__.__new__(self.__class__)
        for key in WORKPLANE_KEYS:
            setattr(clone, key, getattr(self, key))
        return clone

    def __eq__(self, other) -> bool:
        if not isinstance(other, Workplane):
            return NotImplemented
        return (self.origin, self.x_axis, self.y_axis) == \
            (other.origin, other.x_axis, other.y_axis)

    __hash__ = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<Workplane origin={self.origin} x_axis={self.x_axis} "
                f"y_axis={self.y_axis}>")


class ConstraintRecord:
    """One constraint (contract §1.2) — see the module docstring for the
    ref model and the driving/reference gate."""

    def __init__(self, kind, refs=(), value=None, driven=False, c_id=None):
        c_id = _nonempty_str(c_id if c_id is not None else _new_id(),
                              "constraint id")
        if kind not in CONSTRAINT_KINDS:
            raise ValueError(f"unknown constraint kind {kind!r} "
                             f"(vocabulary: {sorted(CONSTRAINT_KINDS)})")
        try:
            refs = tuple(_coerce_ref(ref) for ref in refs)
        except TypeError:
            raise ValueError(f"constraint refs must be a sequence, got {refs!r}") from None
        arity, cls_name = CONSTRAINT_KINDS[kind]
        if len(refs) != arity:
            raise ValueError(
                f"constraint kind {kind!r} takes exactly {arity} ref(s), "
                f"got {len(refs)}")
        # validate EVERYTHING before assigning anything (a rejected value
        # must not leave a partially-initialized record — repr/eq would
        # crash on the missing attribute)
        if cls_name == "dimensional":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"dimensional constraint {c_id!r} requires a numeric "
                    f"value, got {value!r}")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"constraint {c_id!r} value must be finite")
            if not isinstance(driven, bool):
                raise ValueError(f"constraint {c_id!r} driven must be a bool")
            driven = bool(driven)
        else:
            if value is not None:
                raise ValueError(
                    f"geometric constraint {c_id!r} takes no value "
                    f"(got {value!r}); use a dimensional kind")
            if driven is not False:
                raise ValueError(
                    f"geometric constraint {c_id!r} cannot be driven "
                    "(reference gating is a dimension-only concept)")
            value = None
            driven = False
        self.c_id = c_id
        self.kind = kind
        self.refs = refs
        self.value = value
        self.driven = driven

    # -- mutation (validated; prior values returned) -------------------------
    def set(self, **changes) -> dict:
        """Validate + apply field changes; return the PRIOR values. Settable:
        ``kind``, ``refs``, ``value``, ``driven`` (``c_id`` is immutable —
        it is the addressing identity). Everything is validated BEFORE
        anything is applied (no partial apply)."""
        if "c_id" in changes:
            raise ValueError("constraint c_id is immutable")
        unknown = [key for key in changes if key not in CONSTRAINT_KEYS]
        if unknown:
            raise ValueError(f"unknown constraint field(s) {unknown!r}")
        if not changes:
            raise ValueError("constraint set() needs at least one field")
        merged = {
            "kind": changes.get("kind", self.kind),
            "refs": changes.get("refs", self.refs),
            "value": changes.get("value", self.value),
            "driven": changes.get("driven", self.driven),
        }
        scratch = ConstraintRecord(c_id=self.c_id, **merged)  # validates
        prior = {key: getattr(self, key) for key in changes}
        self.kind, self.refs = scratch.kind, scratch.refs
        self.value, self.driven = scratch.value, scratch.driven
        return prior

    # -- serialization ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "c_id": self.c_id,
            "kind": self.kind,
            "refs": _refs_to_json(self.refs),
            "value": self.value,
            "driven": self.driven,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConstraintRecord":
        if not isinstance(data, dict):
            raise ValueError(f"constraint record must be a dict, got {data!r}")
        if "c_id" not in data or "kind" not in data:
            raise ValueError("constraint record needs 'c_id' + 'kind'")
        return cls(kind=data["kind"], refs=data.get("refs") or (),
                   value=data.get("value"), driven=data.get("driven", False),
                   c_id=data["c_id"])

    def copy(self) -> "ConstraintRecord":
        clone = self.__class__.__new__(self.__class__)
        clone.c_id = self.c_id
        clone.kind = self.kind
        clone.refs = tuple(dict(ref) for ref in self.refs)
        clone.value = self.value
        clone.driven = self.driven
        return clone

    def __eq__(self, other) -> bool:
        if not isinstance(other, ConstraintRecord):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<ConstraintRecord {self.c_id!r} {self.kind} "
                f"refs={list(self.refs)} value={self.value} "
                f"driven={self.driven}>")


class JunctionRecord:
    """One junction: a named "same point" grouping of line endpoints
    (contract §1.3). One or more members; the merged point's COORDINATES
    are never stored — the solve derives them from member geometry."""

    def __init__(self, members, junction_id=None):
        self.junction_id = _nonempty_str(
            junction_id if junction_id is not None else _new_id(),
            "junction id")
        try:
            members = tuple(_coerce_member(member) for member in members)
        except TypeError:
            raise ValueError(
                f"junction members must be a sequence, got {members!r}") from None
        if not members:
            raise ValueError(
                f"junction {self.junction_id!r} needs at least one member")
        self.members = members

    # -- mutation ------------------------------------------------------------
    def set(self, members) -> dict:
        """Validate + replace the member list; return the PRIOR members.
        Identity (``junction_id``) is immutable and survives member growth —
        the point of the record (contract §2)."""
        scratch = JunctionRecord(members, junction_id=self.junction_id)
        prior = self.members
        self.members = scratch.members
        return {"members": prior}

    # -- serialization ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {"junction_id": self.junction_id,
                "members": _refs_to_json(self.members)}

    @classmethod
    def from_dict(cls, data: dict) -> "JunctionRecord":
        if not isinstance(data, dict):
            raise ValueError(f"junction record must be a dict, got {data!r}")
        if "junction_id" not in data or "members" not in data:
            raise ValueError("junction record needs 'junction_id' + 'members'")
        return cls(data["members"], junction_id=data["junction_id"])

    def copy(self) -> "JunctionRecord":
        clone = self.__class__.__new__(self.__class__)
        clone.junction_id = self.junction_id
        clone.members = tuple(dict(member) for member in self.members)
        return clone

    def __eq__(self, other) -> bool:
        if not isinstance(other, JunctionRecord):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<JunctionRecord {self.junction_id!r} "
                f"members={len(self.members)}>")


class SketchRecord:
    """One sketch: workplane + junction map + constraint list (contract
    §1.4). ``sketch_id`` is the immutable addressing key; ``name`` is the
    display field (defaults to the id)."""

    def __init__(self, sketch_id, name=None, workplane=None):
        self.sketch_id = _nonempty_str(sketch_id, "sketch id")
        self.name = _nonempty_str(name if name is not None else sketch_id,
                                  "sketch name")
        self.workplane = workplane if workplane is not None else Workplane()
        if not isinstance(self.workplane, Workplane):
            raise ValueError("workplane must be a bcdoc.Workplane")
        self.junctions: list = []
        self.constraints: list = []

    # -- mutation (sketch-level fields only) -----------------------------------
    def set(self, **changes) -> dict:
        """Validate + apply ``name``/``workplane`` changes; return the
        PRIOR values (the journal payload of ``mutate_sketch`` — contract
        §2)."""
        unknown = [key for key in changes if key not in ("name", "workplane")]
        if unknown:
            raise ValueError(f"unknown sketch field(s) {unknown!r}")
        if not changes:
            raise ValueError("sketch set() needs 'name' or 'workplane'")
        prior = {}
        if "name" in changes:
            prior["name"] = self.name
            self.name = _nonempty_str(changes["name"], "sketch name")
        if "workplane" in changes:
            plane = changes["workplane"]
            if isinstance(plane, dict):
                plane = Workplane.from_dict(plane)
            if not isinstance(plane, Workplane):
                raise ValueError("workplane must be a bcdoc.Workplane")
            # the PRIOR form is the JSON-safe dict (journal payloads must
            # serialize; the replay path converts dicts back — it accepts
            # both forms here)
            prior["workplane"] = self.workplane.to_dict()
            self.workplane = plane
        return prior

    # -- containment (uniqueness + lookups; no doc context here) -------------
    def constraint(self, c_id: str):
        for record in self.constraints:
            if record.c_id == c_id:
                return record
        return None

    def junction(self, junction_id: str):
        for record in self.junctions:
            if record.junction_id == junction_id:
                return record
        return None

    def _assert_unique(self, record) -> None:
        """Uniqueness guards used by every append path (live table, journal
        replay, load)."""
        if isinstance(record, ConstraintRecord):
            if self.constraint(record.c_id) is not None:
                raise errors.DuplicateConstraint(self.sketch_id, record.c_id)
        else:
            if self.junction(record.junction_id) is not None:
                raise errors.DuplicateJunction(self.sketch_id,
                                               record.junction_id)

    # -- serialization ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "sketch_id": self.sketch_id,
            "name": self.name,
            "workplane": self.workplane.to_dict(),
            "junctions": [record.to_dict() for record in self.junctions],
            "constraints": [record.to_dict() for record in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SketchRecord":
        if not isinstance(data, dict):
            raise ValueError(f"sketch record must be a dict, got {data!r}")
        if "sketch_id" not in data:
            raise ValueError("sketch record needs a 'sketch_id'")
        plane = data.get("workplane")
        if plane is not None and not isinstance(plane, Workplane):
            plane = Workplane.from_dict(plane)
        record = cls(data["sketch_id"], name=data.get("name"),
                     workplane=plane)
        for item in data.get("junctions") or ():
            junction = item if isinstance(item, JunctionRecord) \
                else JunctionRecord.from_dict(item)
            record._assert_unique(junction)
            record.junctions.append(junction)
        for item in data.get("constraints") or ():
            constraint = item if isinstance(item, ConstraintRecord) \
                else ConstraintRecord.from_dict(item)
            record._assert_unique(constraint)
            record.constraints.append(constraint)
        return record

    def copy(self) -> "SketchRecord":
        clone = self.__class__(self.sketch_id, name=self.name,
                               workplane=self.workplane.copy())
        clone.junctions = [record.copy() for record in self.junctions]
        clone.constraints = [record.copy() for record in self.constraints]
        return clone

    def __eq__(self, other) -> bool:
        if not isinstance(other, SketchRecord):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<SketchRecord {self.sketch_id!r} name={self.name!r} "
                f"junctions={len(self.junctions)} "
                f"constraints={len(self.constraints)}>")


class SketchTable:
    """The sketch table (contract §2): every mutation requires the owning
    document's open transaction and journals its op; reads are always
    legal. Refs are validated against the LIVE document at every
    ref-writing mutation (guards §5.1)."""

    def __init__(self, document=None):
        self._doc = document
        self._records: list = []

    # -- reads ------------------------------------------------------------------
    def get(self, sketch_id: str):
        sketch_id = str(sketch_id)
        for record in self._records:
            if record.sketch_id == sketch_id:
                return record
        return None

    def ids(self) -> list:
        return [record.sketch_id for record in self._records]

    def records(self) -> list:
        return [record.copy() for record in self._records]

    def __contains__(self, sketch_id) -> bool:
        try:
            return self.get(sketch_id) is not None
        except Exception:
            return False

    def __iter__(self):
        return iter(self.ids())

    def __len__(self) -> int:
        return len(self._records)

    # -- sketch lifecycle -------------------------------------------------------
    def add(self, sketch_id, name=None, workplane=None) -> SketchRecord:
        tx = self._doc._require_tx()
        if self.get(sketch_id) is not None:
            raise errors.DuplicateSketch(sketch_id)
        record = SketchRecord(sketch_id, name=name, workplane=workplane)
        self._records.append(record)
        tx._record({"op": "add_sketch", "sketch_id": record.sketch_id,
                    "record": record.to_dict()})
        return record

    def remove(self, sketch_id) -> SketchRecord:
        """Remove the sketch — its constraints and junctions go with it;
        the referenced bcdoc ENTITIES stay (document content, contract §2).
        The inverse re-adds the full record byte-exactly AT THE SAME
        POSITION (the entity-add precedent: insertion order is content —
        undo must not reorder the table)."""
        tx = self._doc._require_tx()
        record = self.get(sketch_id)
        if record is None:
            raise errors.SketchNotFound(sketch_id)
        index = self._records.index(record)
        self._records.remove(record)
        tx._record({"op": "remove_sketch", "sketch_id": record.sketch_id,
                    "record": record.to_dict(), "index": index})
        return record

    def set_props(self, sketch_id, **changes) -> SketchRecord:
        tx = self._doc._require_tx()
        record = self.get(sketch_id)
        if record is None:
            raise errors.SketchNotFound(sketch_id)
        prior = record.set(**changes)  # validates everything first
        tx._record({"op": "mutate_sketch", "sketch_id": record.sketch_id,
                    "changes": prior})
        return record

    # -- constraints -------------------------------------------------------------
    def add_constraint(self, sketch_id, kind, refs=(), value=None,
                       driven=False, c_id=None) -> ConstraintRecord:
        tx = self._doc._require_tx()
        sketch = self.get(sketch_id)
        if sketch is None:
            raise errors.SketchNotFound(sketch_id)
        record = ConstraintRecord(kind=kind, refs=refs, value=value,
                                   driven=driven, c_id=c_id)
        self._validate_refs(sketch, record.refs)
        sketch._assert_unique(record)
        sketch.constraints.append(record)
        tx._record({"op": "add_constraint", "sketch_id": sketch.sketch_id,
                    "constraint": record.to_dict()})
        return record

    def set_constraint(self, sketch_id, c_id, **changes) -> ConstraintRecord:
        """The first-class parametric edit (contract §2): ONE journal op
        whose undo restores exactly the prior field values."""
        tx = self._doc._require_tx()
        sketch = self.get(sketch_id)
        if sketch is None:
            raise errors.SketchNotFound(sketch_id)
        record = sketch.constraint(c_id)
        if record is None:
            raise errors.ConstraintNotFound(sketch_id, c_id)
        merged = {
            "kind": changes.get("kind", record.kind),
            "refs": changes.get("refs", record.refs),
            "value": changes.get("value", record.value),
            "driven": changes.get("driven", record.driven),
        }
        scratch = ConstraintRecord(c_id=record.c_id, **merged)  # validates
        if "refs" in changes:
            self._validate_refs(sketch, scratch.refs)
        prior = record.set(**changes)
        tx._record({"op": "mutate_constraint", "sketch_id": sketch.sketch_id,
                    "c_id": record.c_id, "changes": prior})
        return record

    def remove_constraint(self, sketch_id, c_id) -> ConstraintRecord:
        tx = self._doc._require_tx()
        sketch = self.get(sketch_id)
        if sketch is None:
            raise errors.SketchNotFound(sketch_id)
        record = sketch.constraint(c_id)
        if record is None:
            raise errors.ConstraintNotFound(sketch_id, c_id)
        index = sketch.constraints.index(record)
        sketch.constraints.remove(record)
        tx._record({"op": "remove_constraint", "sketch_id": sketch.sketch_id,
                    "c_id": record.c_id, "constraint": record.to_dict(),
                    "index": index})
        return record

    # -- junctions ----------------------------------------------------------------
    def add_junction(self, sketch_id, members, junction_id=None) -> JunctionRecord:
        tx = self._doc._require_tx()
        sketch = self.get(sketch_id)
        if sketch is None:
            raise errors.SketchNotFound(sketch_id)
        record = JunctionRecord(members, junction_id=junction_id)
        self._validate_members(sketch, record.members)
        sketch._assert_unique(record)
        sketch.junctions.append(record)
        tx._record({"op": "add_junction", "sketch_id": sketch.sketch_id,
                    "junction": record.to_dict()})
        return record

    def set_junction(self, sketch_id, junction_id, members) -> JunctionRecord:
        """Grow/shrink a junction's members WITHOUT losing its identity
        (the drawing-tools' connect-line-to-junction flow, contract §2)."""
        tx = self._doc._require_tx()
        sketch = self.get(sketch_id)
        if sketch is None:
            raise errors.SketchNotFound(sketch_id)
        record = sketch.junction(junction_id)
        if record is None:
            raise errors.JunctionNotFound(sketch_id, junction_id)
        scratch = JunctionRecord(members, junction_id=record.junction_id)
        self._validate_members(sketch, scratch.members)
        prior = record.set(members=scratch.members)
        tx._record({"op": "mutate_junction", "sketch_id": sketch.sketch_id,
                    "junction_id": record.junction_id, "changes": prior})
        return record

    def remove_junction(self, sketch_id, junction_id) -> JunctionRecord:
        tx = self._doc._require_tx()
        sketch = self.get(sketch_id)
        if sketch is None:
            raise errors.SketchNotFound(sketch_id)
        record = sketch.junction(junction_id)
        if record is None:
            raise errors.JunctionNotFound(sketch_id, junction_id)
        index = sketch.junctions.index(record)
        sketch.junctions.remove(record)
        tx._record({"op": "remove_junction", "sketch_id": sketch.sketch_id,
                    "junction_id": record.junction_id,
                    "junction": record.to_dict(), "index": index})
        return record

    # -- ref validation (contract §5.1; needs the live document) ------------
    def _validate_refs(self, sketch: SketchRecord, refs) -> None:
        for ref in refs:
            if "junction" in ref:
                if sketch.junction(ref["junction"]) is None:
                    raise errors.JunctionNotFound(sketch.sketch_id,
                                                 ref["junction"])
                continue
            entity = self._doc_entity(ref["entity"])
            if "slot" in ref and entity.kind != "line":
                raise ValueError(
                    f"slot ref addresses line endpoints, but entity "
                    f"{ref['entity']!r} is a {entity.kind}")

    def _validate_members(self, sketch: SketchRecord, members) -> None:
        for member in members:
            entity = self._doc_entity(member["entity"])
            if entity.kind != "line":
                raise ValueError(
                    f"junction members address line endpoints, but entity "
                    f"{member['entity']!r} is a {entity.kind}")

    def _doc_entity(self, eid: str):
        entity = self._doc._store.get(eid)
        if entity is None:
            raise errors.DanglingSketchRef(eid)
        return entity

    # -- internals (journal application / rollback / load; no tx) -------------
    def _insert_at(self, index: int, record: SketchRecord) -> None:
        """Insert at the recorded position (journal replay; index defaults
        to the end for plain adds — insertion order is content, the
        entity-add precedent, contract §2)."""
        index = max(0, min(int(index), len(self._records)))
        self._records.insert(index, record)

    def _drop(self, sketch_id: str):
        record = self.get(sketch_id)
        if record is not None:
            self._records.remove(record)
        return record

    def _restore(self, records: list) -> None:
        """Adopt a full record list (transaction rollback / load)."""
        ids = [record.sketch_id for record in records]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate sketch ids in {ids!r}")
        self._records = list(records)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SketchTable {self.ids()!r}>"


class SolveReport:
    """One solve's diagnostics, as reported by a solver service (contract
    §1.5). A record, not a diagnosis: empty lists are HONEST — a service
    that names no failed constraints yields empty tuples (PlaneGCS's
    structurally-clean failure shape), and nothing here synthesizes
    diagnostics a solver did not produce."""

    __slots__ = ("sketch_id", "solver", "status", "dof", "failed",
                 "redundant", "conflicting", "detail")

    #: The status vocabulary (the corpus envelope's, exact).
    STATUSES = ("solved", "failed")

    def __init__(self, sketch_id, solver, status, dof, failed=(),
                 redundant=(), conflicting=(), detail=""):
        self.sketch_id = _nonempty_str(sketch_id, "report sketch id")
        self.solver = _nonempty_str(solver, "report solver identity")
        if status not in self.STATUSES:
            raise ValueError(f"report status must be one of "
                             f"{self.STATUSES}, got {status!r}")
        self.status = status
        if isinstance(dof, bool) or not isinstance(dof, int) or dof < 0:
            raise ValueError(f"report dof must be an int >= 0, got {dof!r}")
        self.dof = int(dof)
        for name, value in (("failed", failed), ("redundant", redundant),
                            ("conflicting", conflicting)):
            items = tuple(value)
            if any(not isinstance(item, str) for item in items):
                raise ValueError(f"report {name} must be a list of "
                                 f"constraint ids (strings)")
            setattr(self, name, items)
        if not isinstance(detail, str):
            raise ValueError("report detail must be a string")
        self.detail = str(detail)

    def to_dict(self) -> dict:
        return {
            "sketch_id": self.sketch_id,
            "solver": self.solver,
            "status": self.status,
            "dof": self.dof,
            "failed": list(self.failed),
            "redundant": list(self.redundant),
            "conflicting": list(self.conflicting),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SolveReport":
        if not isinstance(data, dict):
            raise ValueError(f"solve report must be a dict, got {data!r}")
        for key in REPORT_KEYS:
            if key not in data:
                raise ValueError(f"solve report missing key {key!r}")
        return cls(data["sketch_id"], data["solver"], data["status"],
                   data["dof"], data["failed"], data["redundant"],
                   data["conflicting"], data["detail"])

    def copy(self) -> "SolveReport":
        clone = self.__class__(self.sketch_id, self.solver, self.status,
                               self.dof, self.failed, self.redundant,
                               self.conflicting, self.detail)
        return clone

    def __eq__(self, other) -> bool:
        if not isinstance(other, SolveReport):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<SolveReport {self.sketch_id!r} {self.status} dof={self.dof} "
                f"failed={list(self.failed)} redundant={list(self.redundant)} "
                f"conflicting={list(self.conflicting)} solver={self.solver!r}>")


class SolveReports:
    """Session-state holder for solve reports (contract §1.5): NEVER
    serialized, NEVER journaled, NEVER part of the transaction snapshot,
    never bumps ``doc_version`` (selection semantics, minus events). The
    solver service's caller stores what the solve returned; a loaded
    document always starts empty."""

    def __init__(self):
        self._reports: dict = {}

    def set(self, report: SolveReport) -> None:
        if not isinstance(report, SolveReport):
            raise TypeError("solve_reports.set expects a bcdoc.SolveReport")
        self._reports[report.sketch_id] = report

    def get(self, sketch_id: str):
        return self._reports.get(sketch_id)

    def all(self) -> tuple:
        """All current reports (insertion ordered)."""
        return tuple(self._reports.values())

    def clear(self) -> None:
        self._reports.clear()

    def __len__(self) -> int:
        return len(self._reports)

    def __contains__(self, sketch_id) -> bool:
        return sketch_id in self._reports

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<SolveReports {sorted(self._reports)!r}>")
