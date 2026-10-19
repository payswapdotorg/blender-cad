#!/usr/bin/env python3
"""W2 (lane b) experiment C — kernel benchmark, OCP SIDE (OCCT 8.0.1 through OCP bindings).

Counterpart of harness/src/bin/w2_kernel.rs: the SAME 16 fixtures from
fixtures/kernel/cases.json, re-implemented with OCCT operations through the
`cadquery-ocp` 8.0.1.1.0 wheels (experiment-side venv /home/z/solidcraft-ocp-venv only — NOT a product
dependency; ADR-0002 keeps OCCT as the product direction and this file is evidence for
that decision, not an implementation of it).

Per fixture it measures:
  - build outcome: the shape, or the VERBATIM exception text (refusals recorded, never
    dropped); OCCT "not done" states are recorded as refusals too;
  - volume / area / CoM / bbox / face+shell counts (BRepGProp, BRepBndLib, TopExp);
  - validity via BRepCheck_Analyzer;
  - build timing: 1 warmup + 5 timed repeats (perf_counter, in-process; the truck side
    records 3 repeats of the same protocol — both labeled as in-process warm timings,
    NOT comparable to the release-binary CLI timings recorded separately);
  - STEP round-trip: STEPControl_Writer (AsIs) -> STEPControl_Reader -> volume/bbox delta;
  - peak RSS via resource.getrusage(RUSAGE_SELF).ru_maxrss (whole process, KiB).

Modes:
  ocp_kernel_bench.py                    all fixtures -> ../scratch/w2-kernel/ocp-bench.json
  ocp_kernel_bench.py --case <id>        one fixture, JSON + peak RSS on stdout
  ocp_kernel_bench.py --read-step <dir>  read every *.step in dir (truck-written STEP read
                                         with the OCCT reader), measure, JSON on stdout

STEP files for the cross-read experiment are written into ../scratch/w2-kernel/ocp-step/
during the full run (--emit-step-dir to override).

Run (from experiments/solidcraft/):  /home/z/solidcraft-ocp-venv/bin/python python/ocp_kernel_bench.py
"""

from __future__ import annotations

import json
import math
import os
import resource
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # experiments/solidcraft
SCRATCH = ROOT / "scratch" / "w2-kernel"

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakePrism,
    BRepPrimAPI_MakeRevol,
    BRepPrimAPI_MakeSphere,
)
from OCP.BRepTools import BRepTools  # noqa: F401  (available if needed)
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRep import BRep_Tool
from OCP.Bnd import Bnd_Box
from OCP.GC import GC_MakeArcOfCircle
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.collections import List_TopoDS_Shape
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Vec

UPSTREAM_SHA = "3b4db52c10279251a068cfca5eb7447068bc28e7"  # provenance anchor of the fixture set
TAU = 2.0 * math.pi


JSON_MARK = "===W2_JSON==="


def emit_json(obj) -> None:
    """Print JSON behind a sentinel line: OCCT's own messengers write to stdout too."""
    print(JSON_MARK)
    print(json.dumps(obj))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def peak_rss_kib() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB on Linux


def ocp_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("cadquery-ocp")
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def measure(shape) -> dict:
    vp = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vp, True)  # onlyClosed=False default; True = skip open
    sp = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, sp)
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)  # useTriangulation=False: bounds from geometry
    lo, hi = box.CornerMin(), box.CornerMax()
    xmin, ymin, zmin, xmax, ymax, zmax = lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()
    com = vp.CentreOfMass()
    return {
        "volume_mm3": vp.Mass(),
        "area_mm2": sp.Mass(),
        "center_of_mass": [com.X(), com.Y(), com.Z()],
        "bbox": {"min": [xmin, ymin, zmin], "max": [xmax, ymax, zmax]},
        "faces": count_subshapes(shape, TopAbs_FACE),
        "shells": count_subshapes(shape, TopAbs_SHELL),
    }


def count_subshapes(shape, kind) -> int:
    n = 0
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        n += 1
        exp.Next()
    return n


def edges_of(shape):
    """Unique edges (an edge shared by two faces appears once, whatever its orientation)."""
    seen = []
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        e = TopoDS.Edge(exp.Current())
        if not any(e.IsSame(p) for p in seen):
            seen.append(e)
        exp.Next()
    return seen


def faces_of(shape):
    out = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        out.append(TopoDS.Face(exp.Current()))
        exp.Next()
    return out


def edge_vertices(e):
    pts = []
    exp = TopExp_Explorer(e, TopAbs_VERTEX)
    while exp.More():
        v = TopoDS.Vertex(exp.Current())
        p = BRep_Tool.Pnt_s(v)
        pts.append((p.X(), p.Y(), p.Z()))
        exp.Next()
    return pts


def is_valid(shape) -> bool:
    try:
        return BRepCheck_Analyzer(shape).IsValid()
    except Exception:
        return False


def rect_face(w: float, h: float, x0: float = 0.0, y0: float = 0.0, z0: float = 0.0):
    """Planar rectangular face in the XY plane (the extrude profile)."""
    a, b, c, d = (gp_Pnt(x0, y0, z0), gp_Pnt(x0 + w, y0, z0), gp_Pnt(x0 + w, y0 + h, z0), gp_Pnt(x0, y0 + h, z0))
    mw = BRepBuilderAPI_MakeWire()
    for p, q in ((a, b), (b, c), (c, d), (d, a)):
        mw.Add(BRepBuilderAPI_MakeEdge(p, q).Edge())
    return BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()


# ---------------------------------------------------------------------------
# case builders — mirror of the truck-side harness; each records per-op timings
# ---------------------------------------------------------------------------


class Steps:
    def __init__(self):
        self.ops = []

    def run(self, name, fn):
        t0 = time.perf_counter()
        try:
            out = fn()
        except Exception as e:  # OCCT raises Standard_Failure subclasses through pybind
            self.ops.append((name, (time.perf_counter() - t0) * 1000.0))
            return Err(f"{type(e).__name__}: {e}")
        self.ops.append((name, (time.perf_counter() - t0) * 1000.0))
        return out


class Err:
    """A refusal/error: carries the verbatim text."""

    def __init__(self, text):
        self.text = text


def boolean(a, b, cls):
    op = cls(a, b)
    op.Build()
    if not op.IsDone():
        return Err(f"{cls.__name__}: IsDone() is false")
    return op.Shape()


def build_k01(s: Steps):
    out = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 30.0), gp_Vec(0, 0, 20)).Shape())
    return out


def build_k02(s: Steps):
    return s.run("cylinder", lambda: BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 15.0, 50.0).Shape())


def build_k04(s: Steps):
    def revolve():
        mw = BRepBuilderAPI_MakeWire()
        mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(20, 0, 0)).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(20, 0, 0), gp_Pnt(25, 0, 30)).Edge())
        arc = GC_MakeArcOfCircle(gp_Pnt(25, 0, 30), gp_Pnt(23, 0, 46), gp_Pnt(15, 0, 60)).Value()
        mw.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(15, 0, 60), gp_Pnt(18, 0, 80)).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(18, 0, 80), gp_Pnt(0, 0, 80)).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 80), gp_Pnt(0, 0, 0)).Edge())
        face = BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()
        return BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), TAU).Shape()

    return s.run("revolve", revolve)


def _box(s: Steps, x0, y0, z0, dx, dy, dz, name="box"):
    return s.run(name, lambda: BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), dx, dy, dz).Shape())


def _fillet(s: Steps, shape, radius, name, pred=None):
    def fillet():
        mk = BRepFilletAPI_MakeFillet(shape)
        picked = 0
        for e in edges_of(shape):
            if pred is not None and not pred(e):
                continue
            mk.Add(radius, e)
            picked += 1
        if picked == 0:
            return Err("fillet: no edges matched the pick predicate")
        mk.Build()
        if not mk.IsDone():
            return Err(f"fillet r={radius}: IsDone() is false")
        return mk.Shape()

    return s.run(name, fillet)


def build_k07(s: Steps):
    box = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 30.0), gp_Vec(0, 0, 20)).Shape())
    if isinstance(box, Err):
        return box
    return _fillet(s, box, 3.0, "fillet_all_edges")


def build_k07b(s: Steps):
    box = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 30.0), gp_Vec(0, 0, 20)).Shape())
    if isinstance(box, Err):
        return box

    def vertical(e):
        vs = edge_vertices(e)
        return len(vs) == 2 and abs(vs[0][0] - vs[1][0]) < 1e-7 and abs(vs[0][1] - vs[1][1]) < 1e-7

    return _fillet(s, box, 3.0, "fillet_straight_edges", pred=vertical)


def build_k08(s: Steps):
    box = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 30.0), gp_Vec(0, 0, 20)).Shape())
    if isinstance(box, Err):
        return box

    def chamfer():
        mk = BRepFilletAPI_MakeChamfer(box)
        picked = 0
        for e in edges_of(box):
            vs = edge_vertices(e)
            if len(vs) == 2 and all(abs(v[2] - 20.0) < 1e-7 for v in vs):
                mk.Add(2.0, e)
                picked += 1
        if picked != 4:
            return Err(f"chamfer: picked {picked} top edges, expected 4")
        mk.Build()
        if not mk.IsDone():
            return Err("chamfer d=2: IsDone() is false")
        return mk.Shape()

    return s.run("chamfer", chamfer)


def build_k09(s: Steps):
    box = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(50.0, 40.0), gp_Vec(0, 0, 30)).Shape())
    if isinstance(box, Err):
        return box

    def shell():
        top = None
        for f in faces_of(box):
            ad = BRepAdaptor_Surface(f)
            if ad.GetType() == GeomAbs_Plane:
                pl = ad.Plane()
                n = pl.Axis().Direction()
                loc = pl.Location()
                if abs(abs(n.Z()) - 1.0) < 1e-7 and abs(loc.Z() - 30.0) < 1e-7:
                    top = f
                    break
        if top is None:
            return Err("shell: top face not found")
        closing = List_TopoDS_Shape()
        closing.Append(top)
        mk = BRepOffsetAPI_MakeThickSolid()
        # negative offset = inward; 2 mm wall; tolerance 1e-3 like upstream's analytic cavity
        mk.MakeThickSolidByJoin(box, closing, -2.0, 1e-3)
        mk.Build()
        if not mk.IsDone():
            return Err("shell 2mm open-top: IsDone() is false")
        return mk.Shape()

    return s.run("shell", shell)


def build_k13(s: Steps):
    a = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 40.0), gp_Vec(0, 0, 20)).Shape())
    if isinstance(a, Err):
        return a
    b = s.run("cylinder", lambda: BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(40, 20, 0), gp_Dir(0, 0, 1)), 12.0, 40.0).Shape())
    if isinstance(b, Err):
        return b
    return s.run("boolean_union", lambda: boolean(a, b, BRepAlgoAPI_Fuse))


def build_k14(s: Steps):
    a = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(50.0, 50.0, -25.0, -25.0), gp_Vec(0, 0, -20)).Shape())
    if isinstance(a, Err):
        return a
    b = s.run("sphere", lambda: BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 15.0).Shape())
    if isinstance(b, Err):
        return b
    return s.run("boolean_cut", lambda: boolean(a, b, BRepAlgoAPI_Cut))


def build_k15(s: Steps):
    a = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 40.0, -20.0, -20.0, -20.0), gp_Vec(0, 0, 40)).Shape())
    if isinstance(a, Err):
        return a
    b = s.run("sphere", lambda: BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 25.0).Shape())
    if isinstance(b, Err):
        return b
    return s.run("boolean_intersect", lambda: boolean(a, b, BRepAlgoAPI_Common))


def build_k38(s: Steps):
    a = s.run("cylinder", lambda: BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10.0, 30.0).Shape())
    if isinstance(a, Err):
        return a
    b = s.run("cylinder", lambda: BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 20), gp_Dir(0, 0, 1)), 10.0, 30.0).Shape())
    if isinstance(b, Err):
        return b
    return s.run("boolean_union", lambda: boolean(a, b, BRepAlgoAPI_Fuse))


def build_st1(s: Steps):
    box = s.run("extrude", lambda: BRepPrimAPI_MakePrism(rect_face(40.0, 30.0), gp_Vec(0, 0, 20)).Shape())
    if isinstance(box, Err):
        return box
    return _fillet(s, box, 200.0, "fillet_too_large")


def build_st2(s: Steps):
    a = _box(s, 0, 0, 0, 20, 10, 10, "box")
    if isinstance(a, Err):
        return a
    b = s.run("cylinder", lambda: BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10, 5, -5), gp_Dir(0, 0, 1)), 5.0001, 20.0).Shape())
    if isinstance(b, Err):
        return b
    return s.run("boolean_cut_near_tangent", lambda: boolean(a, b, BRepAlgoAPI_Cut))


def build_st3(s: Steps):
    return s.run("extrude_sliver", lambda: BRepPrimAPI_MakePrism(rect_face(50.0, 0.02), gp_Vec(0, 0, 10)).Shape())


def build_st4(s: Steps):
    a = _box(s, 0, 0, 0, 10, 10, 10, "box")
    if isinstance(a, Err):
        return a
    b = _box(s, 10, 0, 0, 10, 10, 10, "box")
    if isinstance(b, Err):
        return b
    return s.run("boolean_union_coincident", lambda: boolean(a, b, BRepAlgoAPI_Fuse))


def build_st5(s: Steps):
    a = s.run("sphere", lambda: BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 10.0).Shape())
    if isinstance(a, Err):
        return a
    b = s.run("sphere", lambda: BRepPrimAPI_MakeSphere(gp_Pnt(19.99, 0, 0), 10.0).Shape())
    if isinstance(b, Err):
        return b
    return s.run("boolean_union_near_tangent", lambda: boolean(a, b, BRepAlgoAPI_Fuse))


FIXTURES = [
    # (id, op_classes, comparability label+why, step_roundtrip, builder)
    ("k01-box", ["primitive", "extrude"], ("comparable", "planar box; judged against V=abc"), True, build_k01),
    ("k02-cylinder", ["primitive"], ("comparable", "analytic cylinder; OCCT integrates surfaces exactly"), True, build_k02),
    ("k04-revolve-vase", ["revolve"], ("approximately-comparable", "same profile revolved 360 deg; seam splitting differs"), True, build_k04),
    ("k07-fillet-all-edges", ["fillet_all_edges"], ("approximately-comparable", "rolling-ball corners differ BY DESIGN between kernels"), True, build_k07),
    ("k07b-fillet-4-vertical", ["fillet_straight_edge"], ("approximately-comparable", "no triple-edge corner patches"), True, build_k07b),
    ("k08-chamfer-top-edges", ["chamfer"], ("approximately-comparable", "chamfer miters may differ"), True, build_k08),
    ("k09-shell-open-top", ["shell"], ("approximately-comparable", "BRepOffsetAPI_MakeThickSolid vs truck polyhedron::shell"), True, build_k09),
    ("k13-union-box-cyl", ["boolean_union", "boolean_curved_curved"], ("comparable", "analytic totals"), True, build_k13),
    ("k14-cut-box-sphere", ["boolean_cut", "boolean_curved_curved"], ("comparable", "analytic totals"), True, build_k14),
    ("k15-intersect-cube-sphere", ["boolean_intersect", "boolean_curved_curved"], ("comparable", "analytic totals"), True, build_k15),
    ("k38-union-coincident-cyls", ["boolean_union", "robustness_coincident"], ("comparable", "analytic totals"), True, build_k38),
    ("st1-fillet-too-large", ["robustness_refusal", "fillet_all_edges"], ("approximately-comparable", "failure probe"), False, build_st1),
    ("st2-near-tangent-cut", ["boolean_cut", "robustness_near_tangent"], ("comparable", "near-tangent + split, analytic totals"), True, build_st2),
    ("st3-thin-sliver-extrude", ["extrude", "robustness_sliver"], ("comparable", "sliver, exact analytic total"), True, build_st3),
    ("st4-coincident-face-union", ["boolean_union", "robustness_coincident"], ("comparable", "analytic totals"), True, build_st4),
    ("st5-near-tangent-sphere-union", ["boolean_union", "robustness_near_tangent"], ("comparable", "near-tangent lens, analytic totals"), True, build_st5),
]


# ---------------------------------------------------------------------------
# STEP round-trip + cross-read
# ---------------------------------------------------------------------------


def step_write(shape, path) -> None:
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    status = w.Write(str(path))
    if status != 1:  # IFSelect_RetDone
        raise RuntimeError(f"STEPControl_Writer.Write returned {status}")


def step_read(path):
    r = STEPControl_Reader()
    stat = r.ReadFile(str(path))
    if stat != 1:
        raise RuntimeError(f"STEPControl_Reader.ReadFile returned {stat}")
    n = r.TransferRoots()
    if n == 0:
        raise RuntimeError("STEPControl_Reader.TransferRoots transferred 0 roots")
    return r.OneShape()


def step_roundtrip(shape, workdir: Path, fid: str) -> dict:
    path = workdir / f"{fid}.step"
    try:
        t0 = time.perf_counter()
        step_write(shape, path)
        write_ms = (time.perf_counter() - t0) * 1000.0
        t1 = time.perf_counter()
        back = step_read(path)
        read_ms = (time.perf_counter() - t1) * 1000.0
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    m0 = measure(shape)
    m1 = measure(back)
    dvol = abs(m1["volume_mm3"] - m0["volume_mm3"]) / max(abs(m0["volume_mm3"]), 1e-9)
    darea = abs(m1["area_mm2"] - m0["area_mm2"]) / max(abs(m0["area_mm2"]), 1e-9)
    dbbox = max(
        abs(a - b) for a, b in zip(m0["bbox"]["min"] + m0["bbox"]["max"], m1["bbox"]["min"] + m1["bbox"]["max"])
    )
    return {
        "ok": True,
        "file": str(path),
        "bytes": path.stat().st_size,
        "write_ms": round(write_ms, 3),
        "read_ms": round(read_ms, 3),
        "roundtrip_volume_mm3": m1["volume_mm3"],
        "roundtrip_area_mm2": m1["area_mm2"],
        "rel_volume_delta": dvol,
        "rel_area_delta": darea,
        "bbox_max_abs_delta_mm": dbbox,
        "roundtrip_faces": m1["faces"],
        "roundtrip_valid": is_valid(back),
        "original_volume_mm3": m0["volume_mm3"],
    }


# ---------------------------------------------------------------------------
# case execution
# ---------------------------------------------------------------------------


def run_case(fid, ops, comparability, step_rt_flag, builder, emit_dir: Path | None):
    # warmup (produces the error, if any)
    s0 = Steps()
    out0 = builder(s0)
    warm = {"ops": [{"op": n, "ms": round(ms, 3)} for n, ms in s0.ops]}

    if isinstance(out0, Err):
        total = sum(ms for _, ms in s0.ops)
        return {
            "id": fid,
            "op_classes": ops,
            "comparability": {"label": comparability[0], "why": comparability[1]},
            "outcome": {"outcome": "refused-with-error", "error": out0.text},
            "validity_ok": None,
            "timing": {
                "profile": "python in-process, OCP wheel (release build of OCCT), warm",
                "repeats": [{"run": "failure", "total_ms": round(total, 3)}],
                "steps_last_run": warm["ops"],
                "warmup_steps": warm["ops"],
            },
            "step_roundtrip": None,
        }

    repeats = []
    last_shape = out0
    last_steps = warm["ops"]
    for i in range(5):
        s = Steps()
        t0 = time.perf_counter()
        out = builder(s)
        total = (time.perf_counter() - t0) * 1000.0
        repeats.append({"run": i, "total_ms": round(total, 3), "ok": not isinstance(out, Err)})
        if isinstance(out, Err):
            repeats[-1]["error"] = out.text
        else:
            last_shape = out
            last_steps = [{"op": n, "ms": round(ms, 3)} for n, ms in s.ops]

    m = measure(last_shape)
    valid = is_valid(last_shape)
    rt = step_roundtrip(last_shape, emit_dir, fid) if step_rt_flag else None
    return {
        "id": fid,
        "op_classes": ops,
        "comparability": {"label": comparability[0], "why": comparability[1]},
        "outcome": {"outcome": "success", "measure": m, "valid": valid},
        "validity_ok": valid,
        "timing": {
            "profile": "python in-process, OCP wheel (release build of OCCT), warm",
            "repeats": repeats,
            "steps_last_run": last_steps,
            "warmup_steps": warm["ops"],
        },
        "step_roundtrip": rt,
    }


def main():
    args = sys.argv[1:]
    if "--case" in args:
        i = args.index("--case")
        fid = args[i + 1]
        for f in FIXTURES:
            if f[0] == fid:
                rec = run_case(f[0], f[1], f[2], f[3], f[4], emit_dir=SCRATCH / "ocp-step")
                emit_json(
                    {
                        "mode": "case",
                        "id": fid,
                        "ocp_version": ocp_version(),
                        "record": rec,
                        "peak_rss_kib": peak_rss_kib(),
                    }
                )
                return
        emit_json({"mode": "case", "id": fid, "error": "unknown case"})
        return

    if "--read-step" in args:
        i = args.index("--read-step")
        d = Path(args[i + 1])
        files = sorted(d.glob("*.step"))
        out = []
        for p in files:
            rec = {"file": p.name}
            try:
                t0 = time.perf_counter()
                shape = step_read(p)
                rec["read_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
                m = measure(shape)
                rec.update(m)
                rec["valid"] = is_valid(shape)
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"
            out.append(rec)
        emit_json({"mode": "read-step", "dir": str(d), "files": out, "ocp_version": ocp_version()})
        return

    emit_dir = SCRATCH / "ocp-step"
    if "--emit-step-dir" in args:
        i = args.index("--emit-step-dir")
        emit_dir = Path(args[i + 1])
    emit_dir.mkdir(parents=True, exist_ok=True)

    started = utcnow()
    t0 = time.perf_counter()
    records = [run_case(*f, emit_dir=emit_dir) for f in FIXTURES]
    finished = utcnow()

    n_ok = sum(1 for r in records if r["outcome"]["outcome"] == "success")
    n_ref = sum(1 for r in records if r["outcome"]["outcome"] == "refused-with-error")
    doc = {
        "mode": "all",
        "kernel": "OCCT 8.0.1 via cadquery-ocp wheels",
        "ocp_version": ocp_version(),
        "upstream_sha": UPSTREAM_SHA,
        "profile": "python in-process, OCP wheel (release build of OCCT), warm",
        "started_utc": started,
        "finished_utc": finished,
        "wall_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        "peak_rss_kib": peak_rss_kib(),
        "emit_step_dir": str(emit_dir),
        "cases": records,
        "summary": {"total": len(records), "success": n_ok, "refused_with_error": n_ref},
    }
    out_path = SCRATCH / "ocp-bench.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1))
    print(f"wrote {out_path}: {len(records)} cases, {n_ok} success, {n_ref} refused, wall {doc['wall_ms']/1000:.1f}s", file=sys.stderr)
    for r in records:
        o = r["outcome"]["outcome"]
        if o == "success":
            print(f"  {r['id']:<32} {o:<20} V={r['outcome']['measure']['volume_mm3']:.6f}", file=sys.stderr)
        else:
            print(f"  {r['id']:<32} {o:<20} error: {r['outcome']['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
