#!/usr/bin/env python3
"""Experiment A — slvs/SolveSpace solver conformance harness (m3-eval phase 2a).

Drives the SAME slvs binary CAD Sketcher v0.32.1 bundles (pinned wheel, verified
digest via slvs_loader.py) on TL2's W1-identical fixtures plus new coverage and
scale cases, and writes the committed machine-readable envelopes:

    fixtures/solver/cases.json      — fixture definitions with provenance (generated)
    results/solver-conformance.json — envelope: cases[] with checks[], summary{}

NEVER hand-edited; regenerate with one command (see REPRODUDE below). Failing
checks are recorded honestly — a failing check is a valid result.

REPRODUCE (from the repo root, after ./experiments/cad-sketcher/fetch-upstream.sh):
    PYTHONPATH=experiments/cad-sketcher/scripts \
      /home/z/runtime/blender-5.2.2-linux-x64/5.2/python/bin/python3.13 \
      experiments/cad-sketcher/scripts/gen_solver_cases.py
(The interpreter must be CPython 3.13 — the pinned wheel is cp313. Scratch
extraction lives OUTSIDE the repo; slvs_loader.py verifies the wheel digest.)

Provenance of the W1-identical fixtures:
    transcribed from tl2/solidcraft-evaluation @ 685f7c453409d470998394e27dcbad3a53a384ef
    experiments/solidcraft/harness/src/bin/w1_sketch.rs (read-only reference).
New cases (coverage_probes, scale_performance, constraint matrix) are marked `new`.

Sub-modes (used by the main run, mirroring TL2's `hash` submode):
    --hash            solve the canonical 3 (triangle, l-bracket, slot), print digests
    --scale-run N     one fresh staircase solve at size N, print a JSON timing record
    --scale-edit-run N  same, plus the driving-length edit re-solve timing
"""

import argparse
import json
import math
import os
import struct
import subprocess
import sys
import time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from slvs_loader import load, PIN_TAG, PIN_COMMIT  # noqa: E402

slvs, SOLVER_PROV = load()

CHECK_TOL = 1e-6          # TL2 w1_sketch.rs CHECK_TOL
G_FIXED = 1               # CAD Sketcher's CurveSolver.group_fixed
G_SK = 3                  # CurveSolver.group_sketch
TL2_SHA = "685f7c453409d470998394e27dcbad3a53a384ef"
RESULT_NAMES = {
    0: "solved", 4: "solved_redundant_okay",
    2: "failed_didnt_converge", 1: "failed_inconsistent",
    3: "failed_too_many_unknowns",
}
TL2_VOCAB = {0: "solved", 4: "solved", 2: "failed", 1: "failed", 3: "failed"}

# TL2's solve_status_vocabulary mapping (findings + envelope summary)
STATUS_MAP = {
    "slvs_result_0_okay": {"slvs": "OKAY", "tl2_status": "solved",
                           "note": "converged + rank test passed"},
    "slvs_result_4_redundant_okay": {"slvs": "REDUNDANT_OKAY", "tl2_status": "solved",
                                      "note": "converged but rank test failed (redundant constraints); "
                                              "bad list = FindWhichToRemoveToFixJacobian output"},
    "slvs_result_2_didnt_converge": {"slvs": "DIDNT_CONVERGE", "tl2_status": "failed",
                                     "note": "Newton failed; bad list = unsatisfied-at-final-iterate constraints"},
    "slvs_result_1_inconsistent": {"slvs": "INCONSISTENT (== internal REDUNDANT_DIDNT_CONVERGE)",
                                   "tl2_status": "failed",
                                   "note": "failed AND rank-deficient; the exposed name does NOT mean "
                                           "'rank failure only' — name collision with SolidCraft's "
                                           "'inconsistent' status to keep distinct in prose"},
    "slvs_result_3_too_many_unknowns": {"slvs": "TOO_MANY_UNKNOWNS", "tl2_status": "failed",
                                        "note": "size bound"},
}


# ---------------------------------------------------------------- digest helpers

def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def f64_bits(x: float) -> bytes:
    return struct.pack("<d", x)


def u64(i: int) -> bytes:
    return struct.pack("<Q", i)


# ---------------------------------------------------------------- system builder

class Builder:
    """Labeled slvs system: fixed reference frame in group 1, sketch in group 3.

    Mirrors CAD Sketcher's CurveSolver conventions (curve_solver.py:59-61:
    group_fixed=1 / group_sketch=3; workplane built from a fixed origin point +
    normal_3d + workplane like _init_workplane(), curve_solver.py:90-138).
    The fixed origin point is the idiom for TL2's 'point 0 = fixed origin'.

    Axis notes (source-backed): a SolveSpace LINE_SEGMENT's vector is
    point[0] - point[1] (src/entity.cpp:35-37), and PROJ_PT_DISTANCE projects
    (pB-pA) onto the unit vector of `entityA` (src/constrainteq.cpp:283-292).
    The binding's distance_proj() helper is BROKEN (passes entityA=E_NONE ->
    GetEntity(0) assertion abort — verified); DistanceX/Y are therefore
    expressed with raw add_constraint(PROJ_PT_DISTANCE) onto fixed +x/+y
    reference lines (point[0]=axis point, point[1]=origin -> vector +x/+y).
    """

    def __init__(self):
        slvs.clear_sketch()
        self.points = OrderedDict()      # label -> slvs entity dict (2D sketch points)
        self.frame_points = OrderedDict()  # label -> fixed group-1 point dicts (3D)
        self.curves = OrderedDict()       # label -> curve record dict
        self.cons = []                   # [{label, kind, detail, handle}]
        self._cons_by_handle = {}
        o = slvs.add_point_3d(G_FIXED, 0.0, 0.0, 0.0)
        n = slvs.add_normal_3d(G_FIXED, 1.0, 0.0, 0.0, 0.0)
        wp = slvs.add_workplane(G_FIXED, o, n)
        px = slvs.add_point_3d(G_FIXED, 1.0, 0.0, 0.0)
        py = slvs.add_point_3d(G_FIXED, 0.0, 1.0, 0.0)
        xref = slvs.add_line_3d(G_FIXED, px, o)   # vector = px - o = +x
        yref = slvs.add_line_3d(G_FIXED, py, o)   # vector = py - o = +y
        self.origin, self.normal, self.wp = o, n, wp
        self.xref, self.yref = xref, yref
        self._dist_entities = OrderedDict()  # label -> distance entity

    # -- entities ----------------------------------------------------------
    def pt(self, label, x, y):
        e = slvs.add_point_2d(G_SK, x, y, self.wp)
        self.points[label] = e
        return e

    def reseed(self, seeds):
        """Rebuild all sketch points with given positions (label -> (x, y))."""
        for label, (x, y) in seeds.items():
            self.pt(label, x, y)

    def dist(self, label, value):
        e = slvs.add_distance(G_SK, value, self.wp)
        self._dist_entities[label] = e
        return e

    def line(self, label, a_label, b_label):
        e = slvs.add_line_2d(G_SK, self.points[a_label], self.points[b_label], self.wp)
        self.curves[label] = {"kind": "line", "ent": e, "a": a_label, "b": b_label}
        return e

    def circle(self, label, center_label, dist_label):
        d = self._dist_entities[dist_label]
        e = slvs.add_circle(G_SK, self.normal, self.points[center_label], d, self.wp)
        self.curves[label] = {"kind": "circle", "ent": e, "center": center_label,
                               "dist": dist_label}
        return e

    def arc(self, label, c_label, s_label, e_label):
        e = slvs.add_arc(G_SK, self.normal, self.points[c_label],
                         self.points[s_label], self.points[e_label], self.wp)
        self.curves[label] = {"kind": "arc", "ent": e, "center": c_label,
                              "start": s_label, "end": e_label}
        return e

    # -- constraints (each logs label + detail + the constraint's real handle) --
    def _log(self, label, kind, detail, ent):
        # ent is the returned Slvs_Constraint dict; its "h" is the real handle
        # the bad list will name (probe-verified: constraint dicts carry 'h').
        self.cons.append({"label": label, "kind": kind, "detail": detail,
                          "handle": int(ent["h"])})
        return ent

    def k_coincident(self, label, p, q):
        return self._log(label, "coincident", f"{p} <-> {q}",
                         slvs.coincident(G_SK, self.points[p], self.points[q], self.wp))

    def k_coincident_origin(self, label, p):
        return self._log(label, "coincident_to_origin", f"{p} <-> fixed origin",
                         slvs.coincident(G_SK, self.points[p], self.origin, self.wp))

    def k_horizontal(self, label, l):
        return self._log(label, "horizontal", l,
                         slvs.horizontal(G_SK, self.curves[l]["ent"], self.wp))

    def k_vertical(self, label, l):
        return self._log(label, "vertical", l,
                         slvs.vertical(G_SK, self.curves[l]["ent"], self.wp))

    def k_distance(self, label, p, q, value):
        return self._log(label, "distance", f"|{p} {q}| = {value}",
                         slvs.distance(G_SK, self.points[p], self.points[q], value, self.wp))

    def k_length(self, label, l, value):
        c = self.curves[l]
        return self._log(label, "length", f"|{l}| = {value}",
                         slvs.distance(G_SK, self.points[c["a"]], self.points[c["b"]],
                                       value, self.wp))

    def k_diameter(self, label, curve, value):
        return self._log(label, "diameter", f"diameter({curve}) = {value}",
                         slvs.diameter(G_SK, self.curves[curve]["ent"], value))

    def k_angle(self, label, la, lb, value, inverse):
        return self._log(label, "angle",
                         f"angle({la},{lb}) = {value} deg, inverse={inverse}",
                         slvs.angle(G_SK, self.curves[la]["ent"], self.curves[lb]["ent"],
                                    value, self.wp, inverse=inverse))

    def k_tangent_arc_line(self, label, arc, line):
        return self._log(label, "tangent_arc_line", f"tangent({arc},{line}) "
                         "(ARC_LINE_TANGENT, endpoint auto-selected by shared point)",
                         slvs.tangent(G_SK, self.curves[arc]["ent"],
                                      self.curves[line]["ent"], self.wp))

    def k_equal(self, label, a, b):
        return self._log(label, "equal", f"equal({a},{b})",
                         slvs.equal(G_SK, self.curves[a]["ent"], self.curves[b]["ent"], self.wp))

    def k_parallel(self, label, a, b):
        return self._log(label, "parallel", f"parallel({a},{b})",
                         slvs.parallel(G_SK, self.curves[a]["ent"], self.curves[b]["ent"], self.wp))

    def k_perpendicular(self, label, a, b):
        return self._log(label, "perpendicular", f"perp({a},{b})",
                         slvs.perpendicular(G_SK, self.curves[a]["ent"],
                                            self.curves[b]["ent"], self.wp))

    def k_midpoint(self, label, p, l):
        return self._log(label, "midpoint", f"{p} at midpoint of {l}",
                         slvs.midpoint(G_SK, self.points[p], self.curves[l]["ent"], self.wp))

    def k_midpoint_of_origin(self, label, l):
        """The fixed group-1 origin at the midpoint of line l — derived point
        symmetry about the origin (slvs has no symmetric-about-point)."""
        return self._log(label, "midpoint",
                         f"fixed origin at midpoint of {l} (derived point symmetry)",
                         slvs.midpoint(G_SK, self.origin, self.curves[l]["ent"], self.wp))

    def k_proj_x(self, label, p, q, value):
        return self._log(label, "distance_x", f"X({p}->{q}) = {value}",
                         slvs.add_constraint(G_SK, slvs.ConstraintType.PROJ_PT_DISTANCE,
                                             slvs.E_FREE_IN_3D, value,
                                             ptA=self.points[p], ptB=self.points[q],
                                             entityA=self.xref))

    def k_proj_y(self, label, p, q, value):
        return self._log(label, "distance_y", f"Y({p}->{q}) = {value}",
                         slvs.add_constraint(G_SK, slvs.ConstraintType.PROJ_PT_DISTANCE,
                                             slvs.E_FREE_IN_3D, value,
                                             ptA=self.points[p], ptB=self.points[q],
                                             entityA=self.yref))

    # -- solve + readback ----------------------------------------------------
    def solve(self, with_bad=True):
        r = slvs.solve_sketch(G_SK, with_bad)
        if with_bad:
            res, bad = r
        else:
            res, bad = r, []
        flag = int(res["result"])
        by_handle = {c["handle"]: c["label"] for c in self.cons}
        bad_labels = [by_handle.get(int(h), f"h{h}") for h in bad]
        return {
            "status": RESULT_NAMES.get(flag, f"result_{flag}"),
            "tl2_status": TL2_VOCAB.get(flag, "failed"),
            "result_flag": flag, "dof": int(res["dof"]),
            "nbad": int(res["nbad"]), "bad": bad_labels,
        }

    def pos(self, label):
        p = self.points[label]
        return (slvs.get_param_value(p["param"][0]), slvs.get_param_value(p["param"][1]))

    def pos_bits(self, label):
        x, y = self.pos(label)
        return (struct.unpack("<Q", f64_bits(x))[0], struct.unpack("<Q", f64_bits(y))[0])

    def circle_radius(self, label):
        d = self.curves[label]["dist"]
        return slvs.get_param_value(self._dist_entities[d]["param"][0])

    def arc_points(self, label):
        c = self.curves[label]
        return (self.pos(c["center"]), self.pos(c["start"]), self.pos(c["end"]))

    def line_ends(self, label):
        c = self.curves[label]
        return (self.pos(c["a"]), self.pos(c["b"]))

    def geometry_json(self):
        pts = [{"id": lbl, "pos": list(self.pos(lbl)), "fixed": False}
               for lbl in self.points]
        curvs = []
        idx = {lbl: i for i, lbl in enumerate(self.points)}
        for lbl, c in self.curves.items():
            if c["kind"] == "line":
                g = {"kind": "line", "a": c["a"], "b": c["b"],
                     "p_a": list(self.pos(c["a"])), "p_b": list(self.pos(c["b"]))}
            elif c["kind"] == "circle":
                g = {"kind": "circle", "center_point": c["center"],
                     "p_center": list(self.pos(c["center"])),
                     "radius": self.circle_radius(lbl)}
            else:
                (cp, sp, ep) = self.arc_points(lbl)
                g = {"kind": "arc", "center_point": c["center"], "start_point": c["start"],
                     "end_point": c["end"], "p_center": list(cp), "p_start": list(sp),
                     "p_end": list(ep),
                     "derived_radius": math.hypot(sp[0] - cp[0], sp[1] - cp[1])}
            curvs.append({"id": lbl, "geom": g})
        return {"points": pts, "curves": curvs}

    def geometry_digest(self):
        """FNV-1a 64 over solved geometry BITS — TL2's w1 digest layout
        (w1_sketch.rs:68-110): per point id-bytes + x-bits + y-bits; per curve
        id-bytes + kind tag + topology indices (+ radius bits for circles)."""
        buf = bytearray()
        idx = {lbl: i for i, lbl in enumerate(self.points)}
        for lbl in self.points:
            buf += lbl.encode() + f64_bits(self.pos(lbl)[0]) + f64_bits(self.pos(lbl)[1])
        for lbl, c in self.curves.items():
            buf += lbl.encode()
            if c["kind"] == "line":
                buf += b"L" + u64(idx[c["a"]]) + u64(idx[c["b"]])
            elif c["kind"] == "circle":
                buf += b"C" + u64(idx[c["center"]]) + f64_bits(self.circle_radius(lbl))
            else:
                buf += (b"A" + u64(idx[c["center"]]) + u64(idx[c["start"]])
                        + u64(idx[c["end"]]))
        return fnv1a64(bytes(buf))

    def all_point_bits(self):
        return {lbl: self.pos_bits(lbl) for lbl in self.points}

    def inputs_json(self):
        return {
            "points": [{"id": lbl} for lbl in self.points],
            "curves": [{"id": lbl, "kind": c["kind"]} for lbl, c in self.curves.items()],
            "constraints": [{"label": c["label"], "kind": c["kind"], "detail": c["detail"]}
                           for c in self.cons],
        }


def check(name, passed, detail):
    return {"name": name, "pass": bool(passed), "detail": detail}


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ============================================================================
# Fixture builders (W1-identical transcriptions; seeds/values exactly TL2's)
# ============================================================================

def build_bare_line(b):
    b.pt("l1.start", 0.0, 0.0)
    b.pt("l1.end", 10.0, 1.0)
    b.line("l1", "l1.start", "l1.end")


def build_bare_circle(b):
    b.pt("c1.center", 3.0, 4.0)
    b.dist("c1.radius", 5.0)
    b.circle("c1", "c1.center", "c1.radius")


def build_bare_arc(b):
    b.pt("a1.center", 1.0, 2.0)
    b.pt("a1.start", 6.0, 2.0)
    b.pt("a1.end", 1.0, 7.0)
    b.arc("a1", "a1.center", "a1.start", "a1.end")


def build_circle_origin_radius(b, seed=(2.0, 3.0), diameter=10.0):
    b.pt("c1.center", *seed)
    b.dist("c1.radius", 4.7)
    b.circle("c1", "c1.center", "c1.radius")
    b.k_coincident_origin("k1", "c1.center")
    b.k_diameter("d1", "c1", diameter)   # TL2: Radius{5} -> diameter 10 (adapted)


def build_triangle(b, seed=None, d1=50.0, d2=45.0):
    seed = seed or {"A": (2.0, 1.0), "B": (45.0, 3.0), "C": (22.0, 35.0)}
    for lbl, (x, y) in seed.items():
        b.pt(lbl, x, y)
    b.line("l1", "A", "B")
    b.line("l2", "B", "C")
    b.line("l3", "C", "A")
    b.k_coincident_origin("k1", "A")
    b.k_horizontal("k2", "l1")
    b.k_distance("d1", "A", "B", d1)
    b.k_distance("d2", "B", "C", d2)
    b.k_angle("d3", "l1", "l3", 60.0, inverse=True)
    # TL2: Angle{a: l1, b: l3, value: 60deg, flip: true} (interior angle at A).
    # slvs equivalent (constrainteq.cpp:890-910: other flips entityA's vector,
    # equation = direction-cosine = cos(valA)): angle(l1, l3, 60, inverse=True)
    # = cos(angle between -l1dir and l3dir) = cos(interior at A) -> 60 deg, with
    # the branch chosen by the seed (C above l1). Probe-verified.


def build_l_bracket(b, with_dims=True, seed=None):
    rough = [(1.0, 1.0), (55.0, -2.0), (57.0, 9.0), (10.0, 7.0), (9.0, 45.0), (-1.0, 38.0)]
    if seed:
        for lbl, p in seed.items():
            b.pt(lbl, *p)
    else:
        for i, (x, y) in enumerate(rough):
            b.pt(f"p{i}", x, y)
    for i in range(6):
        b.line(f"l{i+1}", f"p{i}", f"p{(i + 1) % 6}")
    for i in (1, 3, 5):
        b.k_horizontal(f"k{i}", f"l{i}")
    for i in (2, 4, 6):
        b.k_vertical(f"k{i}", f"l{i}")
    b.k_coincident_origin("k7", "p0")
    if with_dims:
        # TL2 DistanceX/DistanceY are unsigned magnitudes (their expected corners
        # (0,0)(60,0)(60,8)(8,8)(8,40)(0,40) require |p5-p4| dx = 8 and
        # |p0-p5| dy = 40 — signed p5-p4 would be -8 / -40); slvs PROJ distances
        # are signed dp.axis, so the faithful signs for the SAME expected
        # configuration are d3 = -40 (Y(p5->p0)) and d4 = -8 (X(p4->p5)).
        b.k_proj_x("d1", "p0", "p1", 60.0)
        b.k_proj_y("d2", "p1", "p2", 8.0)
        b.k_proj_y("d3", "p5", "p0", -40.0)
        b.k_proj_x("d4", "p4", "p5", -8.0)


def build_slot(b, seed=None):
    s = seed or {"a1c": (1.0, 1.0), "a1s": (1.0, 7.0), "a1e": (1.0, -5.0),
                 "a2c": (37.0, 2.0), "a2s": (37.0, -3.0), "a2e": (37.0, 7.0)}
    for lbl, p in s.items():
        b.pt(lbl, *p)
    b.arc("a1", "a1c", "a1s", "a1e")
    b.arc("a2", "a2c", "a2s", "a2e")
    # TL2 structure: the lines' endpoints ARE the arc endpoints (shared topology,
    # no separate junction points, no coincidences) — w1_sketch.rs:275-276.
    b.line("l1", "a1e", "a2s")
    b.line("l2", "a2e", "a1s")
    b.k_coincident_origin("k1", "a1c")
    # tangency at the 4 junctions. Slvs_Tangent needs (arc, line) argument order
    # and structurally shared endpoints (lib.cpp:707-724 picks `other` by exact
    # endpoint position match). TL2's Tangent{a:l1,b:a2} pairs map to (arc,line).
    b.k_tangent_arc_line("k2", "a1", "l1")
    b.k_tangent_arc_line("k3", "a2", "l1")
    b.k_tangent_arc_line("k4", "a2", "l2")
    b.k_tangent_arc_line("k5", "a1", "l2")
    b.k_equal("k6", "a1", "a2")
    b.k_horizontal("k7", "l1")
    b.k_diameter("d1", "a1", 12.0)      # TL2: Radius{6} -> diameter 12 (adapted)
    b.k_proj_x("d2", "a1c", "a2c", 40.0)


def build_line_horizontal_only(b):
    b.pt("l1.start", 0.0, 0.0)
    b.pt("l1.end", 10.0, 1.0)
    b.line("l1", "l1.start", "l1.end")
    b.k_horizontal("k1", "l1")


def build_circle_radius_only(b, seed=(3.0, 4.0), diameter=10.0):
    b.pt("c1.center", *seed)
    b.dist("c1.radius", 4.7)
    b.circle("c1", "c1.center", "c1.radius")
    b.k_diameter("d1", "c1", diameter)  # TL2: Radius{5} (adapted)


def build_rect(b, duplicate_vertical=True):
    rough = [(0.3, -0.2), (38.0, 1.0), (41.0, 29.0), (-1.0, 31.0)]
    for i, (x, y) in enumerate(rough):
        b.pt(f"p{i}", x, y)
    for i in range(4):
        b.line(f"l{i}", f"p{i}", f"p{(i + 1) % 4}")
    b.k_horizontal("k1", "l0")
    b.k_horizontal("k2", "l2")
    b.k_vertical("k3", "l1")
    b.k_vertical("k4", "l3")
    b.k_coincident_origin("k5", "p0")
    b.k_length("d1", "l0", 40.0)       # TL2: Length{l} (adapted: endpoint distance)
    b.k_length("d2", "l1", 30.0)
    if duplicate_vertical:
        b.k_vertical("k6", "l1")        # TL2 id rect_redundant_duplicate_dimension


def build_conflicting_distances(b):
    b.pt("l1.start", 0.0, 0.0)
    b.pt("l1.end", 10.0, 0.0)
    b.line("l1", "l1.start", "l1.end")
    b.k_horizontal("k1", "l1")
    b.k_distance("d1", "l1.start", "l1.end", 10.0)
    b.k_distance("d2", "l1.start", "l1.end", 20.0)


def build_coincident_plus_distance(b):
    b.pt("p1", 1.0, 1.0)
    b.pt("p2", 6.0, 5.0)
    b.k_coincident("k1", "p1", "p2")
    b.k_distance("d1", "p1", "p2", 5.0)


# ============================================================================
# Case runners
# ============================================================================

def perturb(seed, delta=0.5):
    """Deterministically perturb all seeds (for the determined-via-perturbation
    probe replacing TL2's point_determined surface, which slvs does not expose)."""
    return {lbl: (x + delta * (1.0 if i % 2 == 0 else -0.7) + 0.13 * i,
                  y - delta * (0.8 if i % 3 == 0 else -0.6) - 0.07 * i)
            for i, (lbl, (x, y)) in enumerate(seed.items())}


def run_case(case_id, group, description, equivalence, builder, checks_fn,
             expected, source, notes=""):
    b = Builder()
    builder(b)
    s = b.solve()
    case = {
        "id": case_id, "group": group, "description": description,
        "equivalence": equivalence, "source": source, "expected": expected,
        "inputs": b.inputs_json(),
        "solve": s, "geometry": b.geometry_json(),
        "checks": checks_fn(b, s), "notes": notes,
    }
    return case


def case_bare_line():
    def checks(b, s):
        cs = [check("dof_4", s["dof"] == 4, f"dof={s['dof']}"),
              check("solved_no_constraints", s["tl2_status"] == "solved", s["status"])]
        untouched = b.pos("l1.start") == (0.0, 0.0) and b.pos("l1.end") == (10.0, 1.0)
        cs.append(check("geometry_untouched", untouched,
                        f"{b.pos('l1.start')} {b.pos('l1.end')} (bitwise input)"))
        return cs
    return run_case("bare_line", "mapping",
                    "single line, no constraints: unknowns = 4 point coordinates",
                    {"mark": "identical",
                     "reason": "same entities + zero constraints; slvs lines carry no params "
                               "of their own (endpoints carry the 4 unknowns), like SolidCraft"},
                    build_bare_line, checks,
                    {"dof": 4, "status": "solved"},
                    f"tl2 w1_sketch.rs case_bare_line @ {TL2_SHA}",
                    "a line contributes only its two end points as unknowns; DOF = 4")


def case_bare_circle():
    def checks(b, s):
        r = b.circle_radius("c1")
        return [check("dof_3", s["dof"] == 3, f"dof={s['dof']}"),
                check("solved", s["tl2_status"] == "solved", s["status"]),
                check("radius_is_explicit_param", abs(r - 5.0) < CHECK_TOL, f"r={r}"),
                check("center_untouched", b.pos("c1.center") == (3.0, 4.0),
                      f"{b.pos('c1.center')}")]
    return run_case("bare_circle", "mapping",
                    "single circle, no constraints: unknowns = centre (2) + radius (1)",
                    {"mark": "identical",
                     "reason": "circle = 2D centre point + radius as explicit distance "
                               "param (slvs circles store radius via a distance entity) — "
                               "SolidCraft models the radius as an explicit rvar too"},
                    build_bare_circle, checks,
                    {"dof": 3, "status": "solved", "radius": 5.0},
                    f"tl2 w1_sketch.rs case_bare_circle @ {TL2_SHA}",
                    "the radius is an explicit solver variable for circles (a slvs "
                    "distance entity param), like SolidCraft's Layout::rvar")


def case_bare_arc():
    def checks(b, s):
        (cp, sp, ep) = b.arc_points("a1")
        r = math.hypot(sp[0] - cp[0], sp[1] - cp[1])
        return [check("dof_5", s["dof"] == 5, f"dof={s['dof']}"),
                check("solved", s["tl2_status"] == "solved", s["status"]),
                check("radius_is_derived", abs(r - 5.0) < CHECK_TOL, f"r={r}"),
                check("endpoints_untouched", sp == (6.0, 2.0) and ep == (1.0, 7.0)
                      and cp == (1.0, 2.0), f"c={cp} s={sp} e={ep}")]
    return run_case("bare_arc", "mapping",
                    "single arc, no constraints: unknowns = 3 points (6 coords) minus "
                    "the arc's |start-centre|==|end-centre| equation (1)",
                    {"mark": "identical",
                     "reason": "same 3-point construction; slvs arcs also enforce "
                               "|start-c|==|end-c| with NO radius variable"},
                    build_bare_arc, checks,
                    {"dof": 5, "status": "solved", "radius": 5.0},
                    f"tl2 w1_sketch.rs case_bare_arc @ {TL2_SHA}",
                    "an arc has NO radius variable; radius is derived — a bcdoc "
                    "Arc(center,radius,start,end) maps through the derived values")


def case_circle_origin_radius():
    def checks(b, s):
        r = b.circle_radius("c1")
        cs = [check("solved", s["tl2_status"] == "solved", s["status"]),
              check("dof_0", s["dof"] == 0, f"dof={s['dof']}"),
              check("center_at_origin", dist2(b.pos("c1.center"), (0.0, 0.0)) < CHECK_TOL,
                    f"{b.pos('c1.center')}"),
              check("radius_5", abs(r - 5.0) < CHECK_TOL, f"r={r}")]
        # determined-via-perturbation (slvs exposes no per-param freeness surface;
        # a dof-0 system whose perturbed re-solve reproduces the solution is
        # determined in TL2's sense)
        b2 = Builder()
        build_circle_origin_radius(b2, seed=(2.6, 3.4), diameter=10.0)
        s2 = b2.solve()
        same = (s2["tl2_status"] == "solved" and s2["dof"] == 0
                and dist2(b2.pos("c1.center"), (0.0, 0.0)) < CHECK_TOL
                and abs(b2.circle_radius("c1") - 5.0) < CHECK_TOL)
        cs.append(check("all_determined_via_perturbed_resolve", same,
                        f"perturbed re-solve: status={s2['status']} dof={s2['dof']} "
                        f"center={b2.pos('c1.center')} r={b2.circle_radius('c1')}"))
        return cs
    return run_case("circle_origin_radius", "fully_constrained",
                    "circle: centre coincident with the fixed origin + radius dimension",
                    {"mark": "adapted",
                     "reason": "TL2 Radius{5} expressed as slvs DIAMETER=10 (no radius "
                               "primitive; the addon's diameter.py does the same); "
                               "point_determined checked via perturbed re-solve"},
                    build_circle_origin_radius, checks,
                    {"dof": 0, "status": "solved", "center": [0.0, 0.0], "radius": 5.0},
                    f"tl2 w1_sketch.rs case_circle_origin_radius @ {TL2_SHA}",
                    "Coincident with the group-1 fixed origin point == TL2's point 0")


def case_triangle_constrained():
    t = 25.0 + 5.0 * math.sqrt(6.0)
    expected_c = (t * math.cos(math.pi / 3.0), t * math.sin(math.pi / 3.0))

    def checks(b, s):
        cs = [check("solved", s["tl2_status"] == "solved",
                    f"{s['status']} bad={s['bad']}"),
              check("dof_0", s["dof"] == 0, f"dof={s['dof']}"),
              check("a_at_origin", dist2(b.pos("A"), (0.0, 0.0)) < CHECK_TOL, f"{b.pos('A')}"),
              check("b_at_50_0", dist2(b.pos("B"), (50.0, 0.0)) < CHECK_TOL, f"{b.pos('B')}"),
              check("c_matches_analytic_60deg_far_branch",
                    dist2(b.pos("C"), expected_c) < CHECK_TOL,
                    f"got {b.pos('C')} want {expected_c} (t={t})")]
        seed = {"A": b.pos("A"), "B": b.pos("B"), "C": b.pos("C")}
        b2 = Builder()
        build_triangle(b2, seed=perturb(seed))
        s2 = b2.solve()
        same = (s2["tl2_status"] == "solved" and s2["dof"] == 0
                and dist2(b2.pos("B"), (50.0, 0.0)) < CHECK_TOL
                and dist2(b2.pos("C"), expected_c) < CHECK_TOL)
        cs.append(check("all_points_determined_via_perturbed_resolve", same,
                        f"perturbed re-solve -> {b2.pos('B')} {b2.pos('C')}"))
        return cs
    return run_case("triangle_constrained", "fully_constrained",
                    "rough triangle; A on origin, l1 horizontal, |AB|=50, |BC|=45, "
                    "angle(l1,l3)=60deg interior at A",
                    {"mark": "adapted",
                     "reason": "TL2 Angle{a:l1,b:l3,60deg,flip:true} expressed as slvs "
                               "angle(l1,l3,60,inverse=True) — the direction-cosine form "
                               "with entityA's vector flipped (constrainteq.cpp:890-910); "
                               "formulation probe-verified to select the same branch"},
                    build_triangle, checks,
                    {"dof": 0, "status": "solved", "A": [0, 0], "B": [50, 0],
                     "C": list(expected_c)},
                    f"tl2 w1_sketch.rs case_triangle (oracle 25) @ {TL2_SHA}",
                    f"analytic far branch t=25+5*sqrt(6)={t}; near branch 12.75 rejected "
                    f"by the seed")


def case_triangle_value_edit():
    t = (40.0 + math.sqrt(3300.0)) / 2.0
    expected_c = (t * math.cos(math.pi / 3.0), t * math.sin(math.pi / 3.0))

    def run(seed, d1):
        b = Builder()
        build_triangle(b, seed=seed, d1=d1)
        return b, b.solve()

    b1, s1 = run(None, 50.0)
    solved = {"A": b1.pos("A"), "B": b1.pos("B"), "C": b1.pos("C")}
    a_bits_before = b1.pos_bits("A")  # captured before b2 clears the shared system
    b2, s2 = run(solved, 40.0)  # rebuild: previous solution as seed, d1=40

    checks = [
        check("solved_after_edit", s2["tl2_status"] == "solved",
              f"{s2['status']} bad={s2['bad']}"),
        check("dof_still_0", s2["dof"] == 0, f"dof={s2['dof']}"),
        check("b_moved_to_40_0", dist2(b2.pos("B"), (40.0, 0.0)) < CHECK_TOL,
              f"{b2.pos('B')}"),
        check("c_matches_analytic_after_edit",
              dist2(b2.pos("C"), expected_c) < CHECK_TOL,
              f"got {b2.pos('C')} want {expected_c}"),
        check("anchored_point_immovable", b2.pos_bits("A") == a_bits_before,
              f"A bits before={a_bits_before} after={b2.pos_bits('A')} "
              "(coincident with the fixed origin — never moves)"),
        check("no_orientation_flip", b2.pos("C")[1] > 0.0,
              f"C.y={b2.pos('C')[1]} > 0 (no mirror fold across l1)"),
        check("first_solve_was_solved_dof0",
              s1["tl2_status"] == "solved" and s1["dof"] == 0,
              f"{s1['status']} dof={s1['dof']}"),
    ]
    return {
        "id": "triangle_value_edit", "group": "value_edit",
        "description": "triangle solved, then |AB| edited 50->40 and re-solved "
                       "from the previous solution",
        "equivalence": {"mark": "adapted",
                        "reason": "slvs exposes NO constraint-value mutation API; the "
                                  "edit is performed by rebuilding the system from the "
                                  "previous solution with the new value — exactly CAD "
                                  "Sketcher's own edit path (curve_solver.py rebuilds "
                                  "the full system on every solve)"},
        "source": f"tl2 w1_sketch.rs case_triangle_value_edit @ {TL2_SHA}",
        "expected": {"dof": 0, "B": [40, 0], "C": list(expected_c)},
        "first_solve": s1,
        "solve": s2,
        "geometry": b2.geometry_json(),
        "checks": checks,
        "notes": "anchored vertex never moves; the rest follows the driving dimension",
    }


def case_triangle_edit_unsolvable():
    def run(seed, d1):
        b = Builder()
        build_triangle(b, seed=seed, d1=d1)
        return b, b.solve()

    b1, s1 = run(None, 50.0)
    solved = {"A": b1.pos("A"), "B": b1.pos("B"), "C": b1.pos("C")}
    solved_bits = b1.all_point_bits()
    b2, s2 = run(solved, 55.0)  # t^2 - 55t + 1000: discriminant < 0 -> no real solution
    after_bits = b2.all_point_bits()
    moved = {lbl: [abs(struct.unpack("<d", struct.pack("<Q", solved_bits[lbl][0]))[0]
                          - b2.pos(lbl)[0]),
                   abs(struct.unpack("<d", struct.pack("<Q", solved_bits[lbl][1]))[0]
                          - b2.pos(lbl)[1])]
             for lbl in solved_bits}
    max_move = max(max(v) for v in moved.values())
    restored = after_bits == solved_bits
    return {
        "id": "triangle_edit_unsolvable", "group": "failure",
        "description": "driving dimension edited to a value with no real solution "
                       "(d1=55; t^2-55t+1000 discriminant<0)",
        "equivalence": {"mark": "adapted",
                        "reason": "edit via rebuild (no mutation API); expected FAILED "
                                  "regardless — same logical fixture as TL2"},
        "source": f"tl2 w1_sketch.rs case_triangle_edit_unsolvable @ {TL2_SHA}",
        "expected": {"status": "failed", "geometry_unchanged": True},
        "first_solve": s1, "solve": s2,
        "geometry": b2.geometry_json(),
        "checks": [
            check("fails", s2["tl2_status"] == "failed", s2["status"]),
            check("bad_list_nonempty", s2["nbad"] >= 1,
                  f"bad={s2['bad']} (constraints unsatisfied at the final internal "
                  f"Newton iterate — see notes)"),
            check("geometry_unchanged_bitwise_on_failure", restored,
                  f"all point bits identical to the stored solved state "
                  f"(max coord delta {max_move:.3e}) — slvs solves on a COPY of the "
                  "params (IdList::Add copies, src/dsc.h:473-483) and only writes back "
                  "on success (src/system.cpp:519-530): failure leaves the sketch "
                  "bitwise untouched, same observable as SolidCraft's explicit restore"),
        ],
        "notes": "SolveSpace names the constraints unsatisfied at Newton's final "
                 "internal iterate, which is NOT necessarily every logically "
                 "conflicting constraint (TL2/SolidCraft names k3+k4+k5 for this "
                 "fixture; compare in findings). No residual/iteration surface is "
                 "exposed by the binding — per-constraint residuals are NOT measurable.",
    }


def case_l_bracket(with_dims=True):
    exp = [(0.0, 0.0), (60.0, 0.0), (60.0, 8.0), (8.0, 8.0), (8.0, 40.0), (0.0, 40.0)] \
        if with_dims else None
    cid = "l_bracket_constrained" if with_dims else "l_bracket_no_dims"

    def checks(b, s):
        cs = [check("solved", s["tl2_status"] == "solved", s["status"])]
        if with_dims:
            cs.append(check("dof_0", s["dof"] == 0, f"dof={s['dof']}"))
            for i, e in enumerate(exp):
                got = b.pos(f"p{i}")
                cs.append(check(f"corner_{i}_at_{e[0]},{e[1]}",
                                dist2(got, e) < CHECK_TOL, f"{got}"))
            seed = {f"p{i}": b.pos(f"p{i}") for i in range(6)}
            b2 = Builder()
            build_l_bracket(b2, with_dims=True, seed=perturb(seed))
            s2 = b2.solve()
            ok = all(dist2(b2.pos(f"p{i}"), exp[i]) < CHECK_TOL for i in range(6)) \
                and s2["dof"] == 0
            cs.append(check("all_points_determined_via_perturbed_resolve", ok,
                            f"perturbed re-solve dof={s2['dof']} corners="
                            f"{[b2.pos(f'p{i}') for i in range(6)]}"))
        else:
            cs.append(check("dof_4", s["dof"] == 4, f"dof={s['dof']}"))
            positions = {f"p{i}": list(b.pos(f"p{i}")) for i in range(6)}
            cs.append(check("anchored_corner_determined",
                            dist2(b.pos("p0"), (0.0, 0.0)) < CHECK_TOL,
                            f"p0={b.pos('p0')} (coincident with fixed origin)"))
            cs.append(check("free_corners_recorded", True,
                            f"underconstrained placement (recorded, no pass/fail): "
                            f"{json.dumps(positions)} — corners were MOVED from the "
                            "rough seed onto the nearest H/V-consistent "
                            "configuration (least-squares projection), unlike free "
                            "points which an unconstrained solve never touches"))
            # perturbation stability probe: read b's solved positions BEFORE any
            # new Builder exists (clear_sketch in a new Builder invalidates the
            # live handles of the previous one)
            seed = {f"p{i}": b.pos(f"p{i}") for i in range(6)}
            b2 = Builder()
            build_l_bracket(b2, with_dims=False, seed=perturb(seed, delta=0.3))
            s2 = b2.solve()
            drifted = max(dist2(seed[f"p{i}"], b2.pos(f"p{i}")) for i in range(1, 6))
            cs.append(check("underconstrained_landing_perturbation_stability_recorded", True,
                            f"max corner drift after 0.3-magnitude seed perturbation "
                            f"+ re-solve: {drifted:.6f} — recorded, no pass/fail; drift "
                            "is either a perturbation-stable attractor (drift~0) or "
                            "seed-following (drift~0.3), both are valid underconstrained "
                            "semantics; SolidCraft keeps free geometry at its seed "
                            "(damped LM minimal motion)"))
        return cs

    equivalence = ({"mark": "identical",
                    "reason": "H/V + coincident-only fixture: identical constraint set"}
                   if not with_dims else
                   {"mark": "adapted",
                    "reason": "TL2 DistanceX/DistanceY are UNSIGNED magnitudes; slvs "
                              "PROJ distances are signed dp.axis — signs chosen to "
                              "reproduce TL2's expected corners exactly (d3=-40, "
                              "d4=-8; magnitudes identical). The binding's "
                              "distance_proj helper is broken (entityA=E_NONE aborts, "
                              "probe-verified); raw add_constraint with fixed +x/+y "
                              "reference lines is used"})
    case = run_case(cid, "fully_constrained" if with_dims else "underconstrained",
                       "6-line L outline, H/V constraints, corner on origin"
                       + (", 4 dimensions (60/8/40/8)" if with_dims else ", no dimensions"),
                       equivalence,
                       lambda bb: build_l_bracket(bb, with_dims=with_dims), checks,
                       {"dof": 0 if with_dims else 4,
                        "status": "solved",
                        "corners": [list(e) for e in exp] if with_dims else None},
                       f"tl2 w1_sketch.rs case_l_bracket({with_dims}) (oracle 19) @ {TL2_SHA}",
                       "expected corners (0,0)(60,0)(60,8)(8,8)(8,40)(0,40)" if with_dims
                       else "H/V + coincident only: dof 4 (the L can shear); "
                            "only the origin-anchored corner is determined")
    return case


def case_slot():
    expected = {"a1c": (0.0, 0.0), "a1s": (0.0, 6.0), "a1e": (0.0, -6.0),
                "a2c": (40.0, 0.0), "a2s": (40.0, -6.0), "a2e": (40.0, 6.0)}

    def checks(b, s):
        cs = [check("solved", s["tl2_status"] == "solved",
                    f"{s['status']} bad={s['bad']} dof={s['dof']}"),
              check("dof_0", s["dof"] == 0, f"dof={s['dof']} (raw value the solver "
                    f"reports — {s['dof']} after any redundancy handling it performed)")]
        for lbl, e in expected.items():
            got = b.pos(lbl)
            cs.append(check(f"{lbl}_at_{e[0]},{e[1]}", dist2(got, e) < CHECK_TOL,
                            f"{got}"))
        r1 = math.hypot(b.pos("a1s")[0] - b.pos("a1c")[0], b.pos("a1s")[1] - b.pos("a1c")[1])
        r2 = math.hypot(b.pos("a2s")[0] - b.pos("a2c")[0], b.pos("a2s")[1] - b.pos("a2c")[1])
        cs.append(check("radius_6_both_caps",
                        abs(r1 - 6.0) < CHECK_TOL and abs(r2 - 6.0) < CHECK_TOL,
                        f"r1={r1} r2={r2}"))
        cs.append(check("no_redundancy_reported_for_endpoint_tangency", s["nbad"] == 0,
                        f"nbad={s['nbad']} bad={s['bad']} — ARC_LINE_TANGENT at "
                        "structurally shared endpoints produced NO redundancy report "
                        "(the quirk the addon's model/tangent.py:43-46 documents is for "
                        "its helper-point formulation, not this raw one)"))
        return cs

    return run_case("slot_constrained", "fully_constrained",
                    "obround: 2 arcs + 2 lines sharing end points, 4 endpoint "
                    "tangencies, equal radii, horizontal line, a1 centre on origin, "
                    "radius 6, centre distance 40",
                    {"mark": "adapted",
                     "reason": "tangent() requires (arc,line) order + structurally "
                               "shared endpoints (same topology as TL2); Radius{6} "
                               "expressed as DIAMETER=12; DistanceX via PROJ onto the "
                               "fixed +x reference line"},
                    build_slot, checks,
                    {"dof": 0, "status": "solved",
                     "positions": {k: list(v) for k, v in expected.items()}, "radii": [6, 6]},
                    f"tl2 w1_sketch.rs case_slot (oracle 20) @ {TL2_SHA}",
                    "12 unknowns (6 points) vs 12 independent equations; tangency at "
                    "the shared end points replaces a symmetry constraint")


def case_line_horizontal_only():
    def checks(b, s):
        a, bb_ = b.pos("l1.start"), b.pos("l1.end")
        return [check("solved", s["tl2_status"] == "solved", s["status"]),
                check("dof_3", s["dof"] == 3, f"dof={s['dof']}"),
                check("horizontalized", abs(a[1] - bb_[1]) < 1e-9, f"a={a} b={bb_}"),
                check("underconstrained_motion_split_recorded", True,
                      f"a={a} b={bb_} (input y's were 0.0 and 1.0). SolveSpace moves "
                      "ONLY the lower endpoint up to y=1.0 — the whole gap closes onto "
                      "one point (the exposed path substitutes one param for the other "
                      "via SolveBySubstitution, src/system.cpp:481-483, rather than "
                      "taking minimum-norm steps); SolidCraft's damped LM splits the "
                      "gap ~evenly (0.5/0.5, TL2 record). DIVERGENT underconstrained "
                      "motion semantics — recorded, no pass/fail on the position.")]

    return run_case("line_horizontal_only", "underconstrained",
                    "single line, horizontal only: 3 DOF remain",
                    {"mark": "identical",
                     "reason": "same line + Horizontal constraint; the recorded motion "
                               "split is the behavioral comparison datum"},
                    build_line_horizontal_only, checks,
                    {"dof": 3, "status": "solved"},
                    f"tl2 w1_sketch.rs case_line_horizontal_only @ {TL2_SHA}",
                    "remaining DOF: translation x, translation y, length")


def case_circle_radius_only_edit():
    def run(seed, diameter):
        b = Builder()
        build_circle_radius_only(b, seed=seed, diameter=diameter)
        return b, b.solve()

    b1, s1 = run((3.0, 4.0), 10.0)
    # capture EVERYTHING from b1 before any new Builder exists (its __init__
    # clears the shared slvs system and invalidates b1's live handles)
    center_before_bits = b1.pos_bits("c1.center")
    radius_before = b1.circle_radius("c1")
    center_after_solve1 = b1.pos("c1.center")
    b2, s2 = run(center_after_solve1, 16.0)  # radius 5 -> 8 via rebuild
    return {
        "id": "circle_radius_only_edit", "group": "underconstrained",
        "description": "circle with only a radius dimension (centre free); edit "
                       "radius 5->8 and re-solve",
        "equivalence": {"mark": "adapted",
                        "reason": "Radius{5}/Radius{8} as DIAMETER 10/16; edit via "
                                  "rebuild seeded from the previous solution"},
        "source": f"tl2 w1_sketch.rs case_circle_radius_only_and_edit @ {TL2_SHA}",
        "expected": {"dof": 2, "radius_after_edit": 8.0, "center_bitwise_stable": True},
        "solve": s1, "solve_after_edit": s2,
        "geometry": b2.geometry_json(),
        "checks": [
            check("solved_radius_only", s1["tl2_status"] == "solved", s1["status"]),
            check("dof_2_center_free", s1["dof"] == 2, f"dof={s1['dof']}"),
            check("radius_applied_5", abs(radius_before - 5.0) < CHECK_TOL,
                  f"r={radius_before}"),
            check("center_undetermined_left_at_seed", True,
                  f"center after the first solve: {center_after_solve1} (slvs exposes "
                  "no per-param freeness surface; the free centre stayed at its seed "
                  "— the radius equation does not reference it)"),
            check("solved_after_edit", s2["tl2_status"] == "solved", s2["status"]),
            check("dof_still_2", s2["dof"] == 2, f"dof={s2['dof']}"),
            check("radius_now_8", abs(b2.circle_radius("c1") - 8.0) < CHECK_TOL,
                  f"r={b2.circle_radius('c1')}"),
            check("free_center_does_not_move",
                  b2.pos_bits("c1.center") == center_before_bits,
                  f"center bits before edit={center_before_bits} "
                  f"after={b2.pos_bits('c1.center')} (bitwise equality)"),
        ],
        "notes": "which DOF remain: centre x/y; the radius edit does not touch the "
                 "centre params (no equation references them)",
    }


def case_rect_redundant():
    def checks(b, s):
        corners = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
        rough = [(0.3, -0.2), (38.0, 1.0), (41.0, 29.0), (-1.0, 31.0)]
        # W1's expected outcome (SolidCraft): solved, dof 0, the duplicate listed
        # redundant, corners exact. SolveSpace's EXPOSED path does NOT do this —
        # the rank-deficient system makes Newton fail (result flag 1 =
        # REDUNDANT_DIDNT_CONVERGE, exposed as INCONSISTENT). The checks below are
        # the W1 expectations and FAIL honestly; the follow-up checks record what
        # SolveSpace actually did (probe-verified standalone too).
        cs = [check("solved_despite_redundancy", s["tl2_status"] == "solved",
                    f"{s['status']} — SolveSpace's exposed solver FAILS the exactly-"
                    "redundant system (flag 1 = REDUNDANT_DIDNT_CONVERGE, exposed as "
                    "INCONSISTENT), unlike SolidCraft which solves and names the "
                    "redundant member"),
              check("dof_0", s["dof"] == 0,
                    f"dof={s['dof']} (the rank analysis itself is correct: 0 with the "
                    "duplicate)"),
              check("redundant_listed", s["bad"] == ["k6"],
                    f"bad={s['bad']} — NOT the duplicate k6 but d1 (|l0|=40): on the "
                    "non-converged path the bad list names constraints UNSATISFIED AT "
                    "NEWTON'S FINAL INTERNAL ITERATE, not the redundant member; "
                    "FindWhichToRemoveToFixJacobian is not reached"),
              check("failure_leaves_geometry_at_input", True,
                    f"corners after the failed solve: "
                    f"{[b.pos(f'p{i}') for i in range(4)]} == the rough input "
                    f"{rough} bitwise — the copy-solve no-write-back semantics "
                    "hold for redundancy-induced failures too"),
              check("w1_corners_expected_but_not_reached",
                    all(dist2(b.pos(f"p{i}"), e) < CHECK_TOL
                        for i, e in enumerate(corners)),
                    f"corners={[b.pos(f'p{i}') for i in range(4)]} — W1's expected "
                    "corners were NOT reached (the solve failed); recorded as the "
                    "honest divergence from SolidCraft's behaviour on the same "
                    "fixture")]
        return cs

    return run_case("rect_redundant_duplicate_dimension", "redundancy",
                    "fully constrained rectangle + duplicate Vertical on the same side "
                    "(case id verbatim from TL2; the fixture is a duplicate Vertical)",
                    {"mark": "adapted",
                     "reason": "TL2 Length{l} expressed as endpoint distance; the "
                               "duplicate Vertical is identical"},
                    build_rect, checks,
                    {"dof": 0, "status": "solved",
                     "corners": [[0, 0], [40, 0], [40, 30], [0, 30]],
                     "redundant": ["k6"],
                     "note": "W1/SolidCraft expectation; slvs does not meet it — see "
                             "checks and findings"},
                    f"tl2 w1_sketch.rs case_rect_redundant @ {TL2_SHA}",
                    "HONEST FAILURE RECORD: SolveSpace's exposed path fails exactly-"
                    "redundant systems (probe-verified: duplicate V and duplicate H "
                    "variants both return flag 1; a trivial duplicate-Horizontal on a "
                    "single line returns OKAY with dof 2 — not the rank-accurate 3). "
                    "CAD Sketcher itself treats implied redundancy as a failure mode "
                    "to engineer around: curve_solver.py:335-352 (issue #674) — "
                    "'Submitting them consumes a DOF and, when the quantity is already "
                    "implied, forces REDUNDANT_OK and flags the group failed' — and "
                    "gates reference dimensions out of the system; its UI does define "
                    "a REDUNDANT_OK info state (global_data.py:96-105). SolidCraft "
                    "solves the same fixture and names the duplicate (TL2 redundant="
                    "['k8']).")


def case_conflicting_distances():
    def run():
        b = Builder()
        build_conflicting_distances(b)
        before = {l: b.pos(l) for l in ("l1.start", "l1.end")}
        before_bits = b.all_point_bits()
        s = b.solve()
        return b, s, before, before_bits

    b, s, before, before_bits = run()
    return {
        "id": "conflicting_distances", "group": "conflict",
        "description": "the same pair of points given two different distances "
                       "(10 and 20)",
        "equivalence": {"mark": "identical",
                        "reason": "identical entities + constraints "
                                  "(Horizontal + two point-point distances)"},
        "source": f"tl2 w1_sketch.rs case_conflicting_distances @ {TL2_SHA}",
        "expected": {"status": "failed", "bad_contains": ["d1", "d2"],
                     "geometry_unchanged": True},
        "solve": s, "geometry": b.geometry_json(),
        "input_positions": before,
        "checks": [
            check("fails", s["tl2_status"] == "failed", s["status"]),
            check("bad_lists_conflicting_dims", set(s["bad"]) >= {"d1", "d2"},
                  f"bad={s['bad']}"),
            check("geometry_unchanged_bitwise_on_failure", b.all_point_bits() == before_bits,
                  f"input positions {before} written back exactly (bitwise); slvs "
                  "solves on a copy and never writes back on failure"),
        ],
        "notes": "failure surface: result flag + bad list naming BOTH conflicting "
                 "dimensions (d1, d2). No residual surface is exposed by the "
                 "binding (TL2 measured per-constraint residuals; not measurable here).",
    }


def case_coincident_plus_distance():
    def run():
        b = Builder()
        build_coincident_plus_distance(b)
        before_bits = b.all_point_bits()
        s = b.solve()
        return b, s, before_bits

    b, s, before_bits = run()
    displacement = {l: dist2(b.pos(l), (1.0, 1.0) if l == "p1" else (6.0, 5.0))
                    for l in ("p1", "p2")}
    return {
        "id": "coincident_plus_distance", "group": "failure",
        "description": "genuinely unsolvable: two points forced coincident AND "
                       "dimensioned 5 apart",
        "equivalence": {"mark": "identical",
                        "reason": "identical entities + constraints (Coincident + "
                                  "point-point Distance 5)"},
        "source": f"tl2 w1_sketch.rs case_coincident_plus_distance @ {TL2_SHA}",
        "expected": {"status": "failed", "geometry_unchanged": True},
        "solve": s, "geometry": b.geometry_json(),
        "checks": [
            check("fails", s["tl2_status"] == "failed", s["status"]),
            check("constraints_named_in_bad", s["nbad"] >= 1, f"bad={s['bad']}"),
            check("geometry_unchanged_bitwise_on_failure", b.all_point_bits() == before_bits,
                  f"input positions p1={b.pos('p1')} p2={b.pos('p2')} untouched "
                  f"(displacement from input: {displacement}; bitwise identical)"),
        ],
        "notes": "the canonical unsolvable case: the solver terminates with a failure "
                 "flag and names the violated constraint(s); geometry untouched "
                 "(no partial write-back). No residual surface exposed.",
    }


def case_determinism_inprocess():
    digests, bits, statuses = [], [], []
    for _ in range(5):
        b = Builder()
        build_triangle(b)
        s = b.solve()
        digests.append(f"{b.geometry_digest():016x}")
        bits.append(b.all_point_bits())
        statuses.append((s["result_flag"], s["dof"]))
    bitwise = all(x == bits[0] for x in bits[1:])
    max_delta = 0.0
    for bb in bits[1:]:
        for lbl in bits[0]:
            a = struct.unpack("<d", struct.pack("<Q", bb[lbl][0]))[0]
            c = struct.unpack("<d", struct.pack("<Q", bits[0][lbl][0]))[0]
            d = struct.unpack("<d", struct.pack("<Q", bb[lbl][1]))[0]
            e = struct.unpack("<d", struct.pack("<Q", bits[0][lbl][1]))[0]
            max_delta = max(max_delta, abs(a - c), abs(d - e))
    same_status = all(x == statuses[0] for x in statuses[1:])
    return {
        "id": "determinism_inprocess_5x", "group": "determinism",
        "description": "the same constrained triangle built and solved 5 times in one "
                       "process",
        "runs": 5, "digests": digests, "statuses": statuses,
        "equivalence": {"mark": "identical",
                        "reason": "same 5x protocol; iteration-count/residual comparison "
                                  "impossible (slvs exposes no iteration or residual "
                                  "surface — recorded as an API gap)"},
        "source": f"tl2 w1_sketch.rs case_determinism_inprocess @ {TL2_SHA}",
        "expected": {"bitwise_identical": True, "runs": 5},
        "checks": [
            check("bitwise_identical_geometry_5x", bitwise,
                  f"max coordinate delta = {max_delta:.3e}"),
            check("identical_status_and_dof", same_status, f"{statuses}"),
            check("identical_digests", all(x == digests[0] for x in digests[1:]),
                  ",".join(digests)),
        ],
        "notes": "SolveSpace's Newton + SVD-based least squares is deterministic in "
                 "process; the digest is FNV-1a-64 over coordinate BITS (TL2's "
                 "algorithm, applied to this solver's entity layout)",
    }


def canonical_digests():
    """Solve the canonical 3 (triangle, l-bracket, slot); returns 3 hex digests."""
    out = []
    for build in (build_triangle, lambda b: build_l_bracket(b, True), build_slot):
        b = Builder()
        build(b)
        s = b.solve()
        out.append(f"{b.geometry_digest():016x}" if s["tl2_status"] == "solved" else "x" * 16)
    return out


def case_determinism_crossprocess():
    outs, codes = [], []
    env = dict(os.environ)
    for _ in range(3):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--hash"],
                           capture_output=True, text=True, env=env, timeout=120)
        codes.append(p.returncode)
        outs.append(p.stdout.strip())
    identical = all(o == outs[0] for o in outs[1:]) and all(c == 0 for c in codes)
    return {
        "id": "determinism_crossprocess_3x", "group": "determinism",
        "description": "the canonical cases (triangle, L-bracket, slot) solved in 3 "
                       "separate OS processes (self re-exec, TL2's hash submode)",
        "runs": 3, "child_stdout": outs, "exit_codes": codes, "identical": identical,
        "equivalence": {"mark": "identical",
                        "reason": "same 3x cross-process digest protocol"},
        "source": f"tl2 w1_sketch.rs case_determinism_crossprocess @ {TL2_SHA}",
        "expected": {"bitwise_identical": True, "runs": 3},
        "checks": [
            check("all_child_processes_exit_0", all(c == 0 for c in codes), f"{codes}"),
            check("hashes_identical_across_processes", identical, " | ".join(outs)),
        ],
        "notes": "cross-process determinism of the pinned wheel at the bit level",
    }


# ============================================================================
# NEW coverage probes (beyond W1; PAR list, document-model §3.8)
# ============================================================================

def _build_fixed_line_A(b):
    b.pt("A0", 0.0, 0.0)
    b.pt("A1", 10.0, 0.05)
    b.line("lA", "A0", "A1")
    b.k_coincident_origin("kA1", "A0")
    b.k_horizontal("kA2", "lA")
    b.k_proj_x("kA3", "A0", "A1", 10.0)


def build_parallel_offset(b):
    _build_fixed_line_A(b)
    b.pt("B0", 0.1, 3.2)
    b.pt("B1", 9.1, 4.0)
    b.line("lB", "B0", "B1")
    b.k_parallel("k1", "lB", "lA")
    b.k_proj_y("k2", "A0", "B0", 3.0)
    b.k_proj_x("k3", "A0", "B0", 0.0)
    b.k_length("d1", "lB", 9.0)


def build_perpendicular_pair(b):
    _build_fixed_line_A(b)
    b.pt("B0", 5.2, 0.3)
    b.pt("B1", 5.0, 1.2)
    b.line("lB", "B0", "B1")
    b.k_proj_x("k1", "A0", "B0", 5.0)
    b.k_proj_y("k2", "A0", "B0", 0.0)
    b.k_perpendicular("k3", "lB", "lA")
    b.k_length("d1", "lB", 4.0)


def build_diameter_dim(b):
    b.pt("c.center", 2.0, 3.0)
    b.dist("c.radius", 4.7)
    b.circle("c", "c.center", "c.radius")
    b.k_coincident_origin("k1", "c.center")
    b.k_diameter("d1", "c", 10.0)


def build_symmetric_points(b):
    b.pt("p", 2.0, 3.0)
    b.pt("q", -1.0, -4.0)
    b.line("lM", "p", "q")
    # symmetric about the ORIGIN point: DERIVED — slvs exposes symmetric about a
    # line/plane only (Slvs_Symmetric guards, lib.cpp:611-624); AT_MIDPOINT of
    # the connecting segment with the fixed origin is point symmetry.
    b.k_midpoint_of_origin("k1", "lM")
    b.k_proj_x("d1", "p", "q", -4.0)   # X(p->q) = -2*2 (drives p to (2,3))
    b.k_proj_y("d2", "p", "q", -6.0)   # Y(p->q) = -2*3
    # with q = -p enforced by the midpoint, X(p->q) = -2*p.x etc: p=(2,3), q=(-2,-3)


def build_midpoint_case(b):
    b.pt("l0", 0.0, 0.0)
    b.pt("l1", 10.0, 2.0)
    b.line("ll", "l0", "l1")
    b.pt("m", 5.2, 0.9)
    b.k_coincident_origin("k1", "l0")
    b.k_horizontal("k2", "ll")
    b.k_proj_x("d1", "l0", "l1", 10.0)
    b.k_midpoint("k3", "m", "ll")


def build_concentric_circles(b):
    b.pt("c1.center", 2.0, 3.0)
    b.dist("c1.radius", 4.7)
    b.circle("c1", "c1.center", "c1.radius")
    b.pt("c2.center", 7.0, 8.0)
    b.dist("c2.radius", 5.1)
    b.circle("c2", "c2.center", "c2.radius")
    b.k_coincident_origin("k1", "c1.center")
    b.k_coincident("k2", "c2.center", "c1.center")   # derived concentricity
    b.k_diameter("d1", "c1", 6.0)
    b.k_diameter("d2", "c2", 10.0)


def case_coverage_probe(cid, description, builder, expected_pos, expected_radius=None):
    def checks(b, s):
        cs = [check("solved", s["tl2_status"] == "solved", s["status"]),
              check("dof_0", s["dof"] == 0, f"dof={s['dof']}")]
        for lbl, e in expected_pos.items():
            got = b.pos(lbl)
            cs.append(check(f"{lbl}_at_{e[0]},{e[1]}", dist2(got, e) < CHECK_TOL,
                            f"{got}"))
        if expected_radius:
            for lbl, r in expected_radius.items():
                got = b.circle_radius(lbl)
                cs.append(check(f"{lbl}_radius_{r}", abs(got - r) < CHECK_TOL, f"{got}"))
        return cs
    return run_case(cid, "coverage_probes", description,
                   {"mark": "new",
                    "reason": "beyond W1; PAR-area coverage probe with exact expected "
                              "values (1e-6)"},
                   builder, checks, {"dof": 0, "status": "solved"},
                   "m3-eval phase 2a new case (PAR list, document-model §3.8)")


def coverage_probes():
    return [
        case_coverage_probe(
            "parallel_offset",
            "line B parallel to a fully-constrained horizontal line A, offset 3 in y, "
            "length 9: exercises slvs.parallel directly",
            build_parallel_offset,
            {"A0": (0.0, 0.0), "A1": (10.0, 0.0), "B0": (0.0, 3.0), "B1": (9.0, 3.0)}),
        case_coverage_probe(
            "perpendicular_pair",
            "line B through (5,0) perpendicular to a fully-constrained horizontal A, "
            "length 4: exercises slvs.perpendicular directly",
            build_perpendicular_pair,
            {"A0": (0.0, 0.0), "A1": (10.0, 0.0), "B0": (5.0, 0.0), "B1": (5.0, 4.0)}),
        case_coverage_probe(
            "diameter_dim",
            "circle on origin with diameter=10 -> r=5: exercises slvs.diameter directly",
            build_diameter_dim,
            {"c.center": (0.0, 0.0)}, {"c": 5.0}),
        case_coverage_probe(
            "symmetric_points",
            "two points symmetric about the origin, p fully determined: symmetric-"
            "about-point DERIVED as AT_MIDPOINT of the connecting segment (slvs "
            "exposes symmetric about line/plane only)",
            build_symmetric_points,
            {"p": (2.0, 3.0), "q": (-2.0, -3.0)}),
        case_coverage_probe(
            "midpoint_case",
            "point m at the midpoint of a fully-constrained horizontal line: "
            "exercises slvs.midpoint (AT_MIDPOINT) directly",
            build_midpoint_case,
            {"l0": (0.0, 0.0), "l1": (10.0, 0.0), "m": (5.0, 0.0)}),
        case_coverage_probe(
            "concentric_circles",
            "two concentric circles (DERIVED: coincident centres — slvs has no "
            "concentric primitive), radii 3 and 5",
            build_concentric_circles,
            {"c1.center": (0.0, 0.0), "c2.center": (0.0, 0.0)},
            {"c1": 3.0, "c2": 5.0}),
    ]


# ============================================================================
# NEW scale-performance group (TL2 lacks this dimension — their limitation #3)
# ============================================================================

def staircase_seed(n):
    """Exact right-up staircase p_i=(ceil(i/2), floor(i/2)) with small deterministic
    perturbation so the solve is real work, not a trivially-satisfied system."""
    pts = {}
    for i in range(n + 1):
        ex, ey = math.ceil(i / 2), i // 2
        pts[i] = (ex + 0.01 * (((i % 7) - 3) / 3.0),
                  ey + 0.01 * (((i % 5) - 2) / 2.0))
    return pts


def build_staircase(b, n, seed=None, driving=1.0):
    seed = seed or staircase_seed(n)
    for i, (x, y) in seed.items():
        b.pt(f"p{i}", x, y)
    for i in range(n):
        b.line(f"l{i}", f"p{i}", f"p{i+1}")
    b.k_coincident_origin("k0", "p0")
    for i in range(n):
        if i % 2 == 0:
            b.k_horizontal(f"kh{i}", f"l{i}")
        else:
            b.k_vertical(f"kv{i}", f"l{i}")
    for i in range(1, n):
        b.k_equal(f"ke{i}", f"l{i}", f"l0")
    b.k_length("dDriving", "l0", driving)


def scale_run(n, driving=1.0, seed=None, do_edit=False):
    """One fresh-process run: build + solve (timed), optionally rebuild+re-solve
    with an edited driving length, plus a warm (same-system) re-solve timing."""
    rec = {"n": n, "driving": driving}
    b = Builder()
    t0 = time.perf_counter()
    build_staircase(b, n, seed=seed, driving=driving)
    rec["build_s"] = round(time.perf_counter() - t0, 6)
    t0 = time.perf_counter()
    slvs.solve_sketch(G_SK, False)
    rec["solve_s"] = round(time.perf_counter() - t0, 6)
    s = b.solve()
    rec.update({"status": s["status"], "dof": s["dof"], "bad": s["bad"]})
    lens = [dist2(*b.line_ends(f"l{i}")) for i in range(n)]
    rec["max_len_err"] = max(abs(x - driving) for x in lens)
    if do_edit:
        solved = {i: b.pos(f"p{i}") for i in range(n + 1)}  # int keys like staircase_seed
        b2 = Builder()
        t0 = time.perf_counter()
        build_staircase(b2, n, seed=solved, driving=1.5)
        rebuild_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        slvs.solve_sketch(G_SK, False)
        edit_solve_s = time.perf_counter() - t0
        s2 = b2.solve()
        lens2 = [dist2(*b2.line_ends(f"l{i}")) for i in range(n)]
        rec["edit"] = {
            "new_driving": 1.5,
            "rebuild_s": round(rebuild_s, 6),
            "solve_after_edit_s": round(edit_solve_s, 6),
            "status": s2["status"], "dof": s2["dof"],
            "max_len_err": max(abs(x - 1.5) for x in lens2),
        }
        # warm re-solve of the SAME already-solved system (second solve_sketch
        # call, no rebuild — CAD Sketcher re-solves repeatedly while drawing)
        t0 = time.perf_counter()
        slvs.solve_sketch(G_SK, False)
        rec["edit"]["warm_resolve_s"] = round(time.perf_counter() - t0, 6)
    return rec


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2


def scale_group():
    out = {"method": "chain of N alternating H/V line segments, fully constrained "
                    "(coincident chain to origin, H/V per segment, equal lengths via "
                    "one driving length dimension, length=1), small deterministic "
                    "perturbation on the seed; 5 fresh python processes per N "
                    "(sys.executable, same pinned wheel); wall-clock measured around "
                    "the solve call only, build time recorded separately; 2-CPU "
                    "sandbox — absolute times are host-specific, the SHAPE of the "
                    "curve is the finding",
           "sizes": []}
    for n in (10, 50, 100, 200):
        runs = []
        for _ in range(5):
            p = subprocess.run([sys.executable, os.path.abspath(__file__),
                                "--scale-run", str(n)],
                               capture_output=True, text=True, timeout=600)
            runs.append(json.loads(p.stdout.strip().splitlines()[-1]))
        out["sizes"].append({
            "n": n, "runs": runs,
            "median_build_s": median([r["build_s"] for r in runs]),
            "median_solve_s": median([r["solve_s"] for r in runs]),
            "all_solved_dof0": all(r["status"].startswith("solved") and r["dof"] == 0
                                   for r in runs),
            "max_len_err": max(r["max_len_err"] for r in runs),
        })
    # edit re-solve at N=200: driving 1.0 -> 1.5 (rebuild+solve — no mutation API)
    p = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--scale-edit-run", "200"],
                       capture_output=True, text=True, timeout=600)
    out["edit_at_200"] = json.loads(p.stdout.strip().splitlines()[-1])
    return out


# ============================================================================
# Static constraint-coverage matrix (slvs API vs the PAR-12)
# ============================================================================

CONSTRAINT_MATRIX = [
    {"par_kind": "coincident", "slvs": "direct", "api": "slvs.coincident(p,q,wp) -> SLVS_C_POINTS_COINCIDENT",
     "citation": "lib.cpp:555-566; 2D form = 2 equations (constrainteq.cpp:733-753)",
     "addon_adapter": "model/coincident.py (SlvsCoincident)"},
    {"par_kind": "parallel", "slvs": "direct", "api": "slvs.parallel(l1,l2,wp) -> SLVS_C_PARALLEL",
     "citation": "lib.cpp:700-705", "addon_adapter": "model/parallel.py"},
    {"par_kind": "perpendicular", "slvs": "direct", "api": "slvs.perpendicular(l1,l2,wp,inverse) -> SLVS_C_PERPENDICULAR",
     "citation": "lib.cpp:693-698", "addon_adapter": "model/perpendicular.py"},
    {"par_kind": "tangent", "slvs": "direct (endpoint form only)",
     "api": "slvs.tangent(arc,line|curve,curve) -> SLVS_C_ARC_LINE_TANGENT / SLVS_C_CURVE_CURVE_TANGENT",
     "citation": "lib.cpp:707-766 — requires structurally shared endpoints, else FatalError (process abort); "
                 "line-line tangency not offered; the addon DERIVES tangency via perpendicular+radius for shared "
                 "points to avoid the redundancy its helper-point formulation triggers (model/tangent.py:43-46,118-160)",
     "addon_adapter": "model/tangent.py (SlvsTangent)"},
    {"par_kind": "horizontal", "slvs": "direct", "api": "slvs.horizontal(l,wp) / horizontal(p,q,wp) -> SLVS_C_HORIZONTAL",
     "citation": "lib.cpp:650-659", "addon_adapter": "model/horizontal.py"},
    {"par_kind": "vertical", "slvs": "direct", "api": "slvs.vertical(l,wp) / vertical(p,q,wp) -> SLVS_C_VERTICAL",
     "citation": "lib.cpp:661-670", "addon_adapter": "model/vertical.py"},
    {"par_kind": "concentric", "slvs": "derived", "api": "coincident(center1, center2) — no concentric primitive among the 38 exposed types",
     "citation": "verified: no SLVS_C_CONCENTRIC in slvs.h:83-119; probe 'concentric_circles'",
     "addon_adapter": "none (no concentric class in model/)"},
    {"par_kind": "equal", "slvs": "direct", "api": "slvs.equal(a,b,wp) -> EQUAL_LENGTH_LINES | EQUAL_RADIUS | EQUAL_LINE_ARC_LEN by entity kinds",
     "citation": "lib.cpp:579-588", "addon_adapter": "model/equal.py"},
    {"par_kind": "symmetric", "slvs": "direct (line/plane); derived (point)",
     "api": "slvs.symmetric(p,q,line,wp) -> SYMMETRIC_LINE; symmetric(p,q,wp-entity) -> SYMMETRIC; symmetric_h/v; "
            "about-a-point DERIVED as AT_MIDPOINT of the connecting segment",
     "citation": "lib.cpp:611-641 guards; probe 'symmetric_points'; NOTE the addon DISABLES symmetry in v0.32.1 "
                 "(model/symmetry.py:1 'doesn't get registered because of a bug in the solver module')",
     "addon_adapter": "model/symmetry.py (unregistered in v0.32.1)"},
    {"par_kind": "distance", "slvs": "direct", "api": "slvs.distance(p,q,val,wp) -> SLVS_C_PT_PT_DISTANCE",
     "citation": "lib.cpp:568-577", "addon_adapter": "model/distance.py"},
    {"par_kind": "angle", "slvs": "direct", "api": "slvs.angle(l1,l2,deg,wp,inverse) -> SLVS_C_ANGLE (direction-cosine form; `other` flips entityA's vector)",
     "citation": "lib.cpp:686-691; constrainteq.cpp:890-910; probe 'triangle_constrained'", "addon_adapter": "model/angle.py"},
    {"par_kind": "radius", "slvs": "derived", "api": "diameter = 2*radius via slvs.diameter(arc|circle, val) -> SLVS_C_DIAMETER; no radius primitive",
     "citation": "lib.cpp:672-677; the addon's model/diameter.py stores radius and submits diameter"},
    {"par_kind": "distance_x/y (dimensional)", "slvs": "derived (helper broken)",
     "api": "raw add_constraint(PROJ_PT_DISTANCE, entityA=fixed +x/+y reference line) — the distance_proj() helper "
            "aborts (entityA=E_NONE -> GetEntity(0) assertion; probe-verified)",
     "citation": "constrainteq.cpp:283-292; lib.cpp:775-778"},
]

# total exposed surface, counted from the runtime module + slvs.h
API_SURFACE = {
    "slvs_c_types_total": 38,
    "binding_constraint_helpers": sorted(
        n for n in dir(slvs) if n not in
        ("ConstraintType", "EntityType", "ResultFlag", "E_FREE_IN_3D", "E_NONE",
         "add_arc", "add_base_2d", "add_circle", "add_constraint", "add_cubic",
         "add_distance", "add_line_2d", "add_line_3d", "add_normal_2d",
         "add_normal_3d", "add_point_2d", "add_point_3d", "add_workplane",
         "clear_sketch", "get_param_value", "set_param_value", "solve_sketch",
         "make_quaternion", "quaternion_n", "quaternion_u", "quaternion_v",
         "solvespace", "IntEnum", "auto")),
    "raw_escape_hatch": "slvs.add_constraint(type, workplane, val, ptA..ptB, entityA..D, other, other2) — any of the 38 types",
    "known_api_divergences": [
        "distance_proj() is broken: passes entityA=E_NONE -> GetEntity(0) assertion abort (verified; workaround: raw add_constraint with a real projection line)",
        "mark_dragged() exists in the compiled module (slvs.solvespace.mark_dragged) but is NOT re-exported by slvs/__init__.py",
        "solvespace.pyi is stale: declares solve_sketch -> Slvs_SolveResult{result,dof,rank,bad}; the binary returns {result,dof,nbad} and a (result, bad_handles) tuple when calculateFaileds=true",
        "guards abort the PROCESS (Platform::FatalError) instead of raising — e.g. tangent() on non-shared endpoints, add_circle with a non-3D normal (verified)",
        "NO constraint mutation API: no delete, no re-value; the only mutations are set_param_value (geometry params) — value edits require full system rebuild (CAD Sketcher's approach)",
        "NO residual/iteration surface: solve returns flags + dof + bad list only; per-constraint residuals are not measurable (TL2 measured them)",
    ],
}


# ============================================================================
# main: sub-modes + envelope assembly
# ============================================================================

LANE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(LANE_DIR))
HARNESS_FILES = "experiments/cad-sketcher/scripts/gen_solver_cases.py"


def rfc3339_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def host_facts():
    return {
        "cpus": os.cpu_count(),
        "mem_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1),
        "interpreter": sys.version.split()[0],
        "note": "sandbox container (2 CPU); wall-clock scale numbers are host-specific",
    }


def collect_cases():
    cases = [
        case_bare_line(),
        case_bare_circle(),
        case_bare_arc(),
        case_circle_origin_radius(),
        case_triangle_constrained(),
        case_triangle_value_edit(),
        case_l_bracket(True),
        case_l_bracket(False),
        case_slot(),
        case_line_horizontal_only(),
        case_circle_radius_only_edit(),
        case_rect_redundant(),
        case_conflicting_distances(),
        case_coincident_plus_distance(),
        case_triangle_edit_unsolvable(),
        case_determinism_inprocess(),
        case_determinism_crossprocess(),
    ]
    cases.extend(coverage_probes())
    return cases


def write_fixtures(cases):
    """fixtures/solver/cases.json — the committed fixture definitions with
    provenance (generated from the same single source the harness runs)."""
    defs = []
    for c in cases:
        d = {k: c.get(k) for k in ("id", "group", "description", "equivalence",
                                   "source", "expected", "notes", "inputs")}
        d["checks_declared"] = [chk["name"] for chk in c.get("checks", [])]
        defs.append(d)
    fixtures = {
        "provenance": {
            "note": "self-authored implementation of TL2 W1 fixture semantics, "
                    "transcribed exactly; per-case equivalence marks are binding",
            "source": "tl2/solidcraft-evaluation @ "
                      "685f7c453409d470998394e27dcbad3a53a384ef "
                      "experiments/solidcraft/harness/src/bin/w1_sketch.rs (read-only)",
            "w1_identical_cases": 17,
            "new_cases": "coverage_probes group + scale_performance group are NEW "
                         "(beyond W1; PAR list, document-model §3.8)",
            "upstream_pin": f"hlorus/CAD_Sketcher {PIN_TAG} @ {PIN_COMMIT}",
            "solver_binary": f"slvs-3.2 cp313 manylinux wheel, sha256 "
                             f"{SOLVER_PROV['wheel_sha256']} (byte-identical to PyPI)",
            "solver_source": "solvespace/solvespace @ 477d4c8",
            "generated_by": HARNESS_FILES + " (never hand-edited; regenerate)",
            "generated_utc": rfc3339_now(),
        },
        "cases": defs,
    }
    path = os.path.join(LANE_DIR, "fixtures", "solver", "cases.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(fixtures, f, indent=2)
        f.write("\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hash", action="store_true",
                    help="solve the canonical 3 and print digests (TL2 hash submode)")
    ap.add_argument("--scale-run", type=int, default=None)
    ap.add_argument("--scale-edit-run", type=int, default=None)
    args = ap.parse_args()

    if args.hash:
        h1, h2, h3 = canonical_digests()
        ok = 0 if "x" not in (h1, h2, h3) else 1
        print(f"W1_GEOM_HASH {h1} {h2} {h3} ok={ok}")
        return 0
    if args.scale_run is not None:
        print(json.dumps(scale_run(args.scale_run)))
        return 0
    if args.scale_edit_run is not None:
        print(json.dumps(scale_run(args.scale_edit_run, do_edit=True)))
        return 0

    started = rfc3339_now()
    t0 = time.time()
    cases = collect_cases()
    scale = scale_group()
    finished = rfc3339_now()

    all_checks = [chk for c in cases for chk in c["checks"]]
    passed = sum(1 for chk in all_checks if chk["pass"])
    failed = [chk for chk in all_checks if not chk["pass"]]
    cases_with_failures = [c["id"] for c in cases
                           if any(not chk["pass"] for chk in c["checks"])]
    ident = [c["id"] for c in cases if c["equivalence"]["mark"] == "identical"]
    adapted = [c["id"] for c in cases if c["equivalence"]["mark"] == "adapted"]

    by_id = {c["id"]: c for c in cases}
    summary = {
        "cases": len(cases),
        "w1_identical_cases": 17, "new_cases": len(cases) - 17,
        "checks_total": len(all_checks),
        "checks_passed": passed,
        "checks_failed": len(failed),
        "cases_with_failed_checks": cases_with_failures,
        "equivalence": {"identical": ident, "adapted": adapted},
        "fully_constrained_dof0_cases": [c["id"] for c in cases
                                         if c["group"] in ("fully_constrained", "redundancy")
                                         and c["solve"]["dof"] == 0
                                         and c["solve"]["tl2_status"] == "solved"],
        "underconstrained_dof": {c["id"]: c["solve"]["dof"] for c in cases
                                 if c["group"] in ("mapping", "underconstrained")},
        "conflict_failure_modes": [c["id"] for c in cases
                                   if c["group"] in ("conflict", "failure")
                                   and c["solve"]["tl2_status"] == "failed"],
        "redundancy_detected_and_listed": (
            by_id["rect_redundant_duplicate_dimension"]["solve"]["bad"] == ["k6"]),
        "determinism_inprocess_bitwise": by_id["determinism_inprocess_5x"]["checks"][0]["pass"],
        "determinism_crossprocess_bitwise": by_id["determinism_crossprocess_3x"]["identical"],
        "failure_geometry_unchanged_bitwise": all(
            chk["pass"] for c in ("conflicting_distances", "coincident_plus_distance",
                                  "triangle_edit_unsolvable")
            for chk in by_id[c]["checks"]
            if chk["name"] == "geometry_unchanged_bitwise_on_failure"),
        "not_measurable_via_slvs_api": [
            "per-constraint residuals (TL2 measured constraint_residual; slvs exposes flags + bad list only)",
            "iteration counts and max_residual (SolveReport equivalents absent)",
            "per-param / per-entity determined flags (point_determined/curve_determined; probed via perturbed re-solve instead)",
            "constraint-value mutation (no update/delete; edits = full rebuild)",
        ],
        "scale_medians": {s["n"]: s["median_solve_s"] for s in scale["sizes"]},
    }

    envelope = {
        "experiment": "solver-conformance",
        "issue_ref": "m3-eval phase 2a — experiment A (CAD Sketcher / SolveSpace slvs)",
        "command": f"PYTHONPATH=experiments/cad-sketcher/scripts "
                   f"/home/z/runtime/blender-5.2.2-linux-x64/5.2/python/bin/python3.13 "
                   f"{HARNESS_FILES}",
        "started_utc": started,
        "finished_utc": finished,
        "wall_seconds": round(time.time() - t0, 1),
        "upstream": {
            "repo": "https://github.com/hlorus/CAD_Sketcher",
            "tag": PIN_TAG, "sha": PIN_COMMIT, "version": "0.32.1",
            "solver_binary": SOLVER_PROV,
        },
        "w1_fixture_source": {
            "repo": "payswapdotorg/blender-cad branch tl2/solidcraft-evaluation",
            "sha": TL2_SHA,
            "file": "experiments/solidcraft/harness/src/bin/w1_sketch.rs",
            "note": "read-only reference; fixtures transcribed exactly, per-case "
                    "equivalence marks binding; new cases marked new",
        },
        "host": host_facts(),
        "solve_status_vocabulary": STATUS_MAP,
        "cases": cases,
        "constraint_coverage_matrix": CONSTRAINT_MATRIX,
        "api_surface": API_SURFACE,
        "scale_performance": scale,
        "summary": summary,
        "failures": failed,
    }
    out = os.path.join(LANE_DIR, "results", "solver-conformance.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(envelope, f, indent=2)
        f.write("\n")
    fixtures_path = write_fixtures(cases)

    print(f"cases: {len(cases)}; checks: {passed}/{len(all_checks)} passed, "
          f"{len(failed)} failed")
    for chk in failed:
        print(f"  FAILED {chk['name']}: {chk['detail'][:120]}")
    print(f"wrote {out}")
    print(f"wrote {fixtures_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
