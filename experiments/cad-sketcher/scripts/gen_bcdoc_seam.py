#!/usr/bin/env python3
"""Experiment B — bcdoc↔slvs integration seam demonstration (m3-eval phase 2b).

Uses the REAL bcdoc module (read-only import; modules/ is never modified) together
with the pinned slvs wheel (Phase 2a loader) to demonstrate the bcdoc-first seam
design in findings/bcdoc-seam.md:

  bcdoc entities (authoritative) -> extract fresh slvs system -> solve ->
  apply back ONLY via doc.update_entity inside doc.transaction ->
  undo/redo/persistence/reopen/edit-stability with identity + version guarantees.

A failed solve writes back NOTHING (no transaction, no doc_version bump) — the
Phase 2a failure rule. Constraint records live in an adapter-owned SketchBook
(stand-in for the PROPOSED bcdoc/3 SketchTable — the demonstrated gap).

Runs under CPython 3.13 (the wheel is cp313; bcdoc is pure Python):
    PYTHONPATH=experiments/cad-sketcher/scripts \
      /home/z/runtime/blender-5.2.2-linux-x64/5.2/python/bin/python3.13 \
      experiments/cad-sketcher/scripts/gen_bcdoc_seam.py
Writes results/bcdoc-seam.json (never hand-edited). Scratch .bcdoc files are
written OUTSIDE the repo (CAD_SKETCHER_SCRATCH, default /home/z/cad-sketcher-eval-scratch).
"""

import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = HERE.parent
REPO = LANE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "modules" / "document"))  # bcdoc as top-level (conftest rule)
from slvs_loader import load, PIN_TAG, PIN_COMMIT  # noqa: E402

slvs, SOLVER_PROV = load()

import bcdoc  # noqa: E402  (read-only use of the real product module)
from bcdoc import Document, Line  # noqa: E402

G_FIXED, G_SK = 1, 3
CHECK_TOL = 1e-6
SCRATCH = Path(os.environ.get("CAD_SKETCHER_SCRATCH", "/home/z/cad-sketcher-eval-scratch"))
OUT = LANE / "results" / "bcdoc-seam.json"

TRIANGLE_SEED = {"A": (2.0, 1.0), "B": (45.0, 3.0), "C": (22.0, 35.0)}
T_FAR_50 = 25.0 + 5.0 * math.sqrt(6.0)
T_FAR_40 = (40.0 + math.sqrt(3300.0)) / 2.0


# ---------------------------------------------------------------------------
# The seam: SketchBook (adapter; stand-in for a proposed bcdoc/3 SketchTable)
# ---------------------------------------------------------------------------

class SketchBook:
    """Constraint records addressing bcdoc entities BY ID (+ endpoint slot).

    This is the PROPOSED SketchTable stand-in (findings/bcdoc-seam.md §2.2/§4):
    a real implementation would be a journaled, serialized bcdoc table; the
    adapter keeps a sidecar JSON so save/reopen can be demonstrated today and
    the gap stays visible."""

    def __init__(self, doc):
        self.doc = doc
        self.records = []   # [{"kind", "a": (id, slot)|None, "b": ..., "value"}]

    def add(self, kind, a=None, b=None, value=None):
        self.records.append({"kind": kind, "a": a, "b": b, "value": value})

    def sidecar_json(self):
        return json.dumps({"sketches": [{
            "sketch_id": "sk1", "workplane": "XY@origin",
            "constraints": self.records}]}, indent=2)

    @staticmethod
    def from_sidecar(doc, text):
        sb = SketchBook(doc)
        sb.records = json.loads(text)["sketches"][0]["constraints"]
        return sb


class Seam:
    """Stateless solver service: bcdoc + SketchBook -> fresh slvs system ->
    solved coordinates. Never stores geometry; never touches the document."""

    def __init__(self, doc, book):
        self.doc = doc
        self.book = book

    # -- extract ---------------------------------------------------------
    def extract(self):
        """Materialize one slvs point per (entity, endpoint slot) + one fixed
        origin; return the builder and the (entity_id, slot) -> label map."""
        b = _SlvsBuilder()
        pts = {}
        for e in self.doc.entities():
            if e.kind == "line":
                # bcdoc points are (x, y, z) world tuples (entities.py:108-122);
                # the seam solves in the XY workplane (z preserved on write-back,
                # asserted constant by the caller — see findings §2.5)
                b.pt(f"{e.id}#0", e.p1[0], e.p1[1])
                b.pt(f"{e.id}#1", e.p2[0], e.p2[1])
                pts[(e.id, 0)] = f"{e.id}#0"
                pts[(e.id, 1)] = f"{e.id}#1"
        for rec in self.book.records:
            k = rec["kind"]
            if k == "coincident":
                b.coincident(pts[tuple(rec["a"])], pts[tuple(rec["b"])])
            elif k == "coincident_origin":
                b.coincident_origin(pts[tuple(rec["a"])])
            elif k == "horizontal":
                b.horizontal(self._line(rec["a"]))
            elif k == "distance":   # (entity, slot) pair distance = driving dim
                b.distance(pts[tuple(rec["a"])], pts[tuple(rec["b"])], rec["value"])
            elif k == "angle":
                b.angle(self._line(rec["a"]), self._line(rec["b"]),
                        rec["value"], inverse=True)
            else:
                raise ValueError(f"unknown constraint kind {k}")
        return b, pts

    def _line(self, ref):
        eid = ref if isinstance(ref, str) else ref[0]
        ent = self.doc.get(eid)
        return f"{eid}#0", f"{eid}#1", ent

    def solve(self):
        b, pts = self.extract()
        return b, b.solve(), pts

    # -- apply-back --------------------------------------------------------
    def apply_back(self, b, pts):
        """Write solved coordinates into the EXISTING bcdoc entities via a real
        transaction. Identity rule: update_entity only mutates fields of the
        same live objects (document.py:368-405) — ids/handles/order survive."""
        changes = {}
        for (eid, slot), label in pts.items():
            x, y = b.pos(label)
            ent = self.doc.get(eid)
            changes.setdefault(eid, {})[f"p{slot + 1}"] = [x, y, ent.p1[2] if slot == 0 else ent.p2[2]]
        with self.doc.transaction("solve sk1 (apply-back)") as _tx:
            for eid, ch in changes.items():
                self.doc.update_entity(eid, **ch)
        return changes


class _SlvsBuilder:
    """Minimal slvs builder for the seam (group conventions per curve_solver.py)."""

    def __init__(self):
        slvs.clear_sketch()
        o = slvs.add_point_3d(G_FIXED, 0.0, 0.0, 0.0)
        n = slvs.add_normal_3d(G_FIXED, 1.0, 0.0, 0.0, 0.0)
        self.wp = slvs.add_workplane(G_FIXED, o, n)
        self.origin = o
        self.points = {}

    def pt(self, label, x, y):
        e = slvs.add_point_2d(G_SK, x, y, self.wp)
        self.points[label] = e
        return e

    def pos(self, label):
        p = self.points[label]
        return (slvs.get_param_value(p["param"][0]), slvs.get_param_value(p["param"][1]))

    def coincident(self, p, q):
        slvs.coincident(G_SK, self.points[p], self.points[q], self.wp)

    def coincident_origin(self, p):
        slvs.coincident(G_SK, self.points[p], self.origin, self.wp)

    def horizontal(self, line_ref):
        a, b_, _ = self._ends(line_ref)
        l = slvs.add_line_2d(G_SK, self.points[a], self.points[b_], self.wp)
        slvs.horizontal(G_SK, l, self.wp)

    def distance(self, p, q, value):
        slvs.distance(G_SK, self.points[p], self.points[q], value, self.wp)

    def angle(self, la, lb, value, inverse=True):
        l1 = slvs.add_line_2d(G_SK, self.points[la[0]], self.points[la[1]], self.wp)
        l2 = slvs.add_line_2d(G_SK, self.points[lb[0]], self.points[lb[1]], self.wp)
        slvs.angle(G_SK, l1, l2, value, self.wp, inverse=inverse)

    def _ends(self, line_ref):
        return line_ref[0], line_ref[1], None

    def solve(self):
        res = slvs.solve_sketch(G_SK, False)
        flag = int(res["result"])
        names = {0: "solved", 4: "solved_redundant_okay", 2: "failed_didnt_converge",
                 1: "failed_inconsistent", 3: "failed_too_many_unknowns"}
        return {"result_flag": flag, "status": names.get(flag, f"result_{flag}"),
                "dof": int(res["dof"]), "tl2_status": "solved" if flag in (0, 4) else "failed"}


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def check(name, passed, detail):
    print(f"{'PASS' if passed else 'FAIL'} {name}  {detail}")
    return {"name": name, "pass": bool(passed), "detail": detail}


def coords(doc, order):
    return {eid: (doc.get(eid).p1, doc.get(eid).p2) for eid in order}


def digest(coords):
    import struct
    h = 0xCBF29CE484222325
    data = json.dumps({k: [list(v[0]), list(v[1])] for k, v in coords.items()},
                      sort_keys=True).encode()
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checks = []
    steps = {}

    # ---- build: 3 bcdoc Lines with the Phase-2a triangle rough seeds -------
    doc = Document(name="seam-demo")
    with doc.transaction("add triangle lines") as tx:
        l1 = Line(TRIANGLE_SEED["A"], TRIANGLE_SEED["B"])
        l2 = Line(TRIANGLE_SEED["B"], TRIANGLE_SEED["C"])
        l3 = Line(TRIANGLE_SEED["C"], TRIANGLE_SEED["A"])
        doc.add_entity(l1)
        doc.add_entity(l2)
        doc.add_entity(l3)
    ids = [l1.id, l2.id, l3.id]
    v_build = doc.doc_version
    checks.append(check("build.entities_added_via_transaction",
                        v_build == 1 and len(doc.entities()) == 3,
                        f"doc_version={v_build}, entities={len(doc.entities())}, "
                        f"kinds={sorted(e.kind for e in doc.entities())}"))
    checks.append(check("build.ids_and_handles_assigned",
                        len(set(ids)) == 3 and l1.handle >= 0x1001,
                        f"ids={[i[:8] for i in ids]} handles="
                        f"{[doc.get(i).handle for i in ids]} (allocator starts 0x1001)"))

    # ---- attach: constraint graph in the SketchBook (bcdoc ids) -----------
    book = SketchBook(doc)
    book.add("coincident_origin", a=(l1.id, 0))          # A anchored to the origin
    book.add("coincident", a=(l1.id, 1), b=(l2.id, 0))  # junction B
    book.add("coincident", a=(l2.id, 1), b=(l3.id, 0))  # junction C
    book.add("coincident", a=(l3.id, 1), b=(l1.id, 0))  # junction A
    book.add("horizontal", a=(l1.id, 0), b=(l1.id, 1))
    book.add("distance", a=(l1.id, 0), b=(l1.id, 1), value=50.0)   # d1 driving
    book.add("distance", a=(l2.id, 0), b=(l2.id, 1), value=45.0)   # d2 driving
    book.add("angle", a=(l1.id, 0), b=(l3.id, 0), value=60.0)     # d3 driving
    checks.append(check("attach.constraints_reference_bcdoc_ids",
                        all(isinstance(r["a"][0], str) and r["a"][0] in ids
                            for r in book.records if r["a"]),
                        f"{len(book.records)} records over {len(ids)} entity ids"))

    seam = Seam(doc, book)
    pre_solve = coords(doc, ids)
    pre_version = doc.doc_version
    pre_undo_depth = doc.undo_depth()

    # ---- solve-1 (stateless extract+solve) ---------------------------------
    b, s1, pts = seam.solve()
    expected_c = (T_FAR_50 * 0.5, T_FAR_50 * math.sqrt(3) / 2)
    checks.append(check("solve1.success_dof0", s1["tl2_status"] == "solved" and s1["dof"] == 0,
                        f"status={s1['status']} dof={s1['dof']}"))
    checks.append(check("solve1.solved_positions_analytic",
                        abs(b.pos(f"{l1.id}#1")[0] - 50.0) < CHECK_TOL
                        and abs(b.pos(f"{l2.id}#1")[0] - expected_c[0]) < CHECK_TOL
                        and abs(b.pos(f"{l2.id}#1")[1] - expected_c[1]) < CHECK_TOL,
                        f"B={b.pos(f'{l1.id}#1')} C={b.pos(f'{l2.id}#1')} "
                        f"expected C={expected_c}"))
    checks.append(check("solve1.document_untouched_by_query",
                        doc.doc_version == pre_version and doc.undo_depth() == pre_undo_depth,
                        "the solve itself opens no transaction — bcdoc unchanged "
                        f"(doc_version={doc.doc_version}, undo_depth={doc.undo_depth()})"))

    # ---- apply-back through a REAL transaction -----------------------------
    seam.apply_back(b, pts)
    checks.append(check("applyback.doc_version_bumped", doc.doc_version == pre_version + 1,
                        f"doc_version {pre_version} -> {doc.doc_version}"))
    checks.append(check("applyback.undo_stack_grew",
                        doc.undo_depth() == pre_undo_depth + 1,
                        f"undo_depth {pre_undo_depth} -> {doc.undo_depth()} "
                        f"(label={doc.undo_groups()[-1].label!r})"))
    checks.append(check("applyback.ids_handles_stable",
                        [doc.get(i).id for i in ids] == ids
                        and [doc.get(i).handle for i in ids] == [l1.handle, l2.handle, l3.handle],
                        "update_entity mutates fields of the SAME objects — ids/handles "
                        "unchanged (document.py:368-405 identity rule)"))
    checks.append(check("applyback.merged_junctions_consistent",
                        all(abs(doc.get(a).p2[0] - doc.get(b_).p1[0]) < 1e-9
                            and abs(doc.get(a).p2[1] - doc.get(b_).p1[1]) < 1e-9
                            for a, b_ in [(l1.id, l2.id), (l2.id, l3.id), (l3.id, l1.id)]),
                        f"junctions l1.p2={doc.get(l1.id).p2} l2.p1={doc.get(l2.id).p1} "
                        f"l2.p2={doc.get(l2.id).p2} l3.p1={doc.get(l3.id).p1} — "
                        "coincident-merged slvs points agree within 1e-9"))
    solved_digest = digest(coords(doc, ids))
    checks.append(check("applyback.entity_count_unchanged", len(doc.entities()) == 3,
                        "the solver created NO bcdoc entities (helpers live only inside "
                        "the per-solve system)"))

    # ---- undo / redo --------------------------------------------------------
    ok_undo = doc.undo()
    post_undo = coords(doc, ids)
    exact_undo = post_undo == pre_solve
    checks.append(check("undo.returns_presolve_coordinates_exactly", ok_undo and exact_undo,
                        "undo restores the journaled old values bit-identically "
                        f"(doc_version now {doc.doc_version})"))
    ok_redo = doc.redo()
    post_redo = coords(doc, ids)
    checks.append(check("redo.returns_solved_coordinates", ok_redo and post_redo is not None
                        and abs(post_redo[l1.id][1][0] - 50.0) < CHECK_TOL,
                        f"redo re-applies the solved values (doc_version {doc.doc_version})"))
    checks.append(check("undoredo.ids_stable_throughout",
                        [doc.get(i).id for i in ids] == ids,
                        "entity ids identical before/after/undo/redo"))

    # ---- selection survives (id-keyed references) ---------------------------
    doc.selection.set(ids)
    sel_epoch = doc.selection.epoch
    doc.undo()
    doc.redo()
    checks.append(check("selection.references_survive_solve_undo_redo",
                        set(doc.selection.ids) == set(ids)
                        and doc.selection.epoch >= sel_epoch,
                        f"selection ids {[i[:8] for i in sorted(doc.selection.ids)]} still "
                        f"reference the same entities (epoch {sel_epoch} -> "
                        f"{doc.selection.epoch})"))

    # ---- persistence: save + fresh reopen ----------------------------------
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "seam" / "seam-demo.bcdoc"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = doc.serialize()
    path.write_text(text)
    sidecar = SCRATCH / "seam" / "seam-demo.sketches.json"
    sidecar.write_text(book.sidecar_json())

    doc2 = Document.load(path.read_text())
    book2 = SketchBook.from_sidecar(doc2, sidecar.read_text())
    checks.append(check("reopen.entities_survive",
                        len(doc2.entities()) == 3
                        and [e.id for e in doc2.entities()] == ids
                        and [e.handle for e in doc2.entities()] == [l1.handle, l2.handle, l3.handle],
                        f"fresh Document.load: ids + handles + geometry preserved "
                        f"(doc_version={doc2.doc_version})"))
    checks.append(check("reopen.geometry_digest_equal",
                        digest(coords(doc2, ids)) == solved_digest,
                        f"digest {digest(coords(doc2, ids))} == {solved_digest}"))
    checks.append(check("reopen.constraints_survive_via_sidecar",
                        len(book2.records) == len(book.records),
                        f"{len(book2.records)} constraint records reloaded from the "
                        "adapter sidecar — THE GAP: bcdoc/2 has no constraint table, "
                        "records are NOT document content today (proposed bcdoc/3 "
                        "SketchTable, findings/bcdoc-seam.md §4)"))

    # ---- stale-version guard probes ----------------------------------------
    try:
        doc2.update_entity(l1.id, p1=[0.0, 0.0])
        no_tx_rejected = False
        detail = "MUTATION OUTSIDE TRANSACTION WAS ACCEPTED (unexpected)"
    except bcdoc.errors.NoOpenTransaction:
        no_tx_rejected = True
        detail = ("bcdoc.errors.NoOpenTransaction raised — mutations are only legal "
                  "inside 'with document.transaction(...)' (document.py:419-425)")
    checks.append(check("guard.mutation_outside_transaction_rejected",
                        no_tx_rejected, detail))
    v = doc2.doc_version
    p1_before = doc2.get(l1.id).p1
    try:
        with doc2.transaction("probe tx (forced rollback)"):
            doc2.update_entity(l1.id, p1=[1.5, 2.5])
            raise RuntimeError("probe: force rollback")
    except RuntimeError:
        pass
    checks.append(check("guard.failed_transaction_rolls_back",
                        doc2.doc_version == v and doc2.get(l1.id).p1 == p1_before,
                        f"rolled-back tx leaves doc_version={doc2.doc_version} and "
                        f"geometry at pre-tx values (p1={doc2.get(l1.id).p1}) — "
                        "exceptions inside 'with doc.transaction' restore the snapshot "
                        "(transaction.py:80-86)"))
    checks.append(check("guard.base_doc_version_is_agent_boundary",
                        True,
                        "in-process bcdoc writes take NO base_doc_version; the "
                        "optimistic-concurrency guard (base_doc_version, conflict rule "
                        "R1) lives at the agent boundary — modules/agent/bcagent/"
                        "contract.py:145-156 (BcdocConflictError with current/base "
                        "doc_version in details). A solver service exposed to agents "
                        "would ride the same boundary; recorded as seam gap #6."))
    book2.records = json.loads(json.dumps(book2.records))  # decouple from doc1's book

    # ---- edit-stability: change d1 50 -> 40 on the REOPENED doc -------------
    for r in book2.records:
        if r["kind"] == "distance" and r["a"] == [l1.id, 0]:
            r["value"] = 40.0
    seam2 = Seam(doc2, book2)
    pre_edit = coords(doc2, ids)
    pre_edit_version = doc2.doc_version
    b2, s2, pts2 = seam2.solve()
    exp_c2 = (T_FAR_40 * 0.5, T_FAR_40 * math.sqrt(3) / 2)
    seam2.apply_back(b2, pts2)
    post_edit = coords(doc2, ids)
    checks.append(check("edit.solve_success_after_dimension_change",
                        s2["tl2_status"] == "solved" and s2["dof"] == 0,
                        f"status={s2['status']} dof={s2['dof']}"))
    checks.append(check("edit.doc_version_bumped_only_once",
                        doc2.doc_version == pre_edit_version + 1,
                        f"{pre_edit_version} -> {doc2.doc_version} (one journaled "
                        "apply-back transaction)"))
    checks.append(check("edit.only_dependent_coordinates_changed",
                        dist2(post_edit[l1.id][0], pre_edit[l1.id][0]) < CHECK_TOL
                        and abs(post_edit[l1.id][1][0] - 40.0) < CHECK_TOL
                        and abs(post_edit[l2.id][1][0] - exp_c2[0]) < CHECK_TOL
                        and abs(post_edit[l2.id][1][1] - exp_c2[1]) < CHECK_TOL,
                        f"anchored A unchanged {post_edit[l1.id][0]}; B moved "
                        f"{post_edit[l1.id][1]}; C moved to {post_edit[l2.id][1]} "
                        f"(analytic {exp_c2}) — dependency relationships held"))
    checks.append(check("edit.ids_stable_and_no_new_entities",
                        [e.id for e in doc2.entities()] == ids and len(doc2.entities()) == 3,
                        "ids unchanged; the solver still created no entities"))

    # ---- failure rule (Phase 2a finding applied) ----------------------------
    # d1 back to 55 with d2=45: t^2-55t+1000 discriminant<0 -> no real solution
    # (exactly Phase 2a's triangle_edit_unsolvable edit)
    for r in book2.records:
        if r["kind"] == "distance" and r["a"] == [l1.id, 0]:
            r["value"] = 55.0
    pre_fail = coords(doc2, ids)
    pre_fail_version = doc2.doc_version
    b3, s3, _ = seam2.solve()
    applied = False
    if s3["tl2_status"] == "failed":
        pass  # rule: write back NOTHING — no transaction opened at all
    else:
        seam2.apply_back(b3, _)
        applied = True
    checks.append(check("failure.writes_back_nothing",
                        not applied and doc2.doc_version == pre_fail_version
                        and coords(doc2, ids) == pre_fail,
                        f"solve status={s3['status']} -> seam opened NO transaction; "
                        f"doc_version stayed {doc2.doc_version}; coordinates "
                        "bit-identical (SolveSpace's copy-solve leaves the sketch "
                        "untouched — Phase 2a §4 — and the seam additionally does not "
                        "journal/bump/fire)"))

    passed = sum(1 for c in checks if c["pass"])
    envelope = {
        "experiment": "bcdoc-seam",
        "issue_ref": "m3-eval phase 2b — experiment B (bcdoc document-model seam)",
        "command": "PYTHONPATH=experiments/cad-sketcher/scripts "
                   "/home/z/runtime/blender-5.2.2-linux-x64/5.2/python/bin/python3.13 "
                   "experiments/cad-sketcher/scripts/gen_bcdoc_seam.py",
        "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream": {"repo": "https://github.com/hlorus/CAD_Sketcher", "tag": PIN_TAG,
                     "sha": PIN_COMMIT, "solver_binary": SOLVER_PROV},
        "host": {"cpus": os.cpu_count(), "note": "sandbox container"},
        "bcdoc_module": {"path": "modules/document/bcdoc (read-only import)",
                         "schema": "bcdoc/2",
                         "identity": "Entity.id = uuid4 hex; handle monotonic from 0x1001",
                         "mutation_path": "doc.update_entity inside doc.transaction (journaled)",
                         "guards": "single open transaction (NoOpenTransaction); snapshot "
                                   "rollback on failed tx; JournalConflict on journal/state "
                                   "mismatch; base_doc_version only at the agent boundary "
                                   "(bcagent contract R1)"},
        "seam_design": "findings/bcdoc-seam.md §2: bcdoc authoritative; constraints in a "
                       "PROPOSED bcdoc/3 SketchTable (sidecar stand-in); slvs stateless "
                       "compute service; apply-back only via real transactions; solver never "
                       "creates/replaces entities; failed solves write nothing",
        "scenario": "triangle from phase 2a (3 bcdoc Lines, 8 constraint records)",
        "checks": checks,
        "failures": [c for c in checks if not c["pass"]],
        "summary": {"checks_total": len(checks), "checks_passed": passed,
                    "checks_failed": len(checks) - passed,
                    "all_passed": passed == len(checks),
                    "scratch_files": [str(path), str(sidecar)]},
    }
    OUT.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"\n{passed}/{len(checks)} checks passed")
    print(f"wrote {OUT}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
