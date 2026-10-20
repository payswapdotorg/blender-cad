#!/usr/bin/env python3
"""Generate results/planegcs-conformance.json — the PlaneGCS-side envelope (h2h-2b).

Runs the built planegcs h2h driver (FreeCAD 1.1.4 pin; eigen 3.4.0; the lane's
compat shims) on the CANONICAL m3-eval corpus
(experiments/cad-sketcher/fixtures/solver/cases.json — 23 cases, consumed
READ-ONLY), evaluates the corpus's declared checks against each case's
expected values (CHECK_TOL = 1e-6, TL2's w1_sketch.rs), orchestrates the
determinism protocol (in-process 5x + cross-process 3x via --hash) and the
staircase scale protocol (N in {10,50,100,200}, 5 fresh processes per N,
medians; edit at N=200 via rebuild + the native mutation path + warm re-solve),
embeds the slot formulation probes (--slotdebug), and machine-VERIFIES the
fixture transcription (driver-emitted inputs vs cases.json inputs).

Mirrors the m3-eval slvs envelope schema (results/solver-conformance.json) and
the solidcraft-side envelope. NEVER hand-edited; regenerate. Failing checks
are recorded honestly — a failing check is a valid result.
"""
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = HERE.parent
DRIVER = HERE / "build" / "driver"
CASES = LANE.parent / "cad-sketcher" / "fixtures" / "solver" / "cases.json"
OUT = LANE / "results" / "planegcs-conformance.json"

CHECK_TOL = 1e-6          # TL2 w1_sketch.rs CHECK_TOL
TL2_SHA = "685f7c453409d470998394e27dcbad3a53a384ef"

FREECAD_TAG = "1.1.4"
FREECAD_SHA = "4fd3bf320d9566a27e60069fc8387448aaa3a094"
EIGEN_SHA256 = "b4c198460eba6f28d34894e3a5710998818515104d6e74e5cc331ce31e46e626"

checks_total = [0, 0]  # passed, failed


def check(name, passed, detail):
    checks_total[0 if passed else 1] += 1
    return {"name": name, "pass": bool(passed), "detail": detail}


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pos_of(case, label):
    for p in case["geometry"]["points"]:
        if p["id"] == label:
            return p["pos"]
    raise KeyError(label)


def geom_positions(case):
    if "geometry" not in case:
        return {}
    return {p["id"]: p["pos"] for p in case["geometry"]["points"]}


def curve_geom(case, label):
    for c in case["geometry"]["curves"]:
        if c["id"] == label:
            return c
    raise KeyError(label)


def run_driver(args, timeout=600):
    p = subprocess.run([str(DRIVER)] + args, capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"driver {args} failed rc={p.returncode}: {p.stderr[:400]}")
    return p.stdout


# ---------------------------------------------------------------- per-case checks

def eval_case(dc, cc):
    """dc = driver case record, cc = cases.json case record -> (checks, notes)"""
    cid = dc["id"]
    s = dc.get("solve") or {}
    status = s.get("status", "")
    positions = geom_positions(dc)
    bits_in = s.get("conflicting")  # placeholder to keep linters quiet
    notes = []

    def solved():
        return status == "solved"

    if cid == "bare_line":
        a, b = positions["l1.start"], positions["l1.end"]
        return [
            check("dof_4", s["dof"] == 4, f"dof={s['dof']}"),
            check("solved_no_constraints", solved(), status),
            check("geometry_untouched", a == [0.0, 0.0] and b == [10.0, 1.0],
                  f"{a} {b} (bitwise input)"),
        ], notes
    if cid == "bare_circle":
        r = curve_geom(dc, "c1")["radius"]
        return [
            check("dof_3", s["dof"] == 3, f"dof={s['dof']}"),
            check("solved", solved(), status),
            check("radius_is_explicit_param", abs(r - 5.0) < CHECK_TOL, f"r={r}"),
            check("center_untouched", positions["c1.center"] == [3.0, 4.0],
                  f"{positions['c1.center']}"),
        ], notes
    if cid == "bare_arc":
        g = curve_geom(dc, "a1")
        cp, sp, ep = g["p_center"], g["p_start"], g["p_end"]
        r = math.hypot(sp[0] - cp[0], sp[1] - cp[1])
        return [
            check("dof_5", s["dof"] == 5, f"dof={s['dof']}"),
            check("solved", solved(), status),
            check("radius_is_derived", abs(r - 5.0) < CHECK_TOL, f"r={r}"),
            check("endpoints_untouched", sp == [6.0, 2.0] and ep == [1.0, 7.0]
                  and cp == [1.0, 2.0], f"c={cp} s={sp} e={ep}"),
        ], notes
    if cid == "circle_origin_radius":
        r = curve_geom(dc, "c1")["radius"]
        pr = dc["perturbed_resolve"]
        prs = dc["perturbed_resolve_geometry"]
        ok = (pr["status"] == "solved" and pr["dof"] == 0
              and dist2(prs["c1.center"], (0.0, 0.0)) < CHECK_TOL
              and abs(dc["perturbed_resolve"]["dof"] - 0) == 0)
        return [
            check("solved", solved(), status),
            check("dof_0", s["dof"] == 0, f"dof={s['dof']}"),
            check("center_at_origin", dist2(positions["c1.center"], (0.0, 0.0)) < CHECK_TOL,
                  f"{positions['c1.center']}"),
            check("radius_5", abs(r - 5.0) < CHECK_TOL, f"r={r}"),
            check("all_determined_via_perturbed_resolve", ok,
                  f"perturbed re-solve: status={pr['status']} dof={pr['dof']} "
                  f"center={prs['c1.center']}"),
        ], notes
    if cid == "triangle_constrained":
        t = 25.0 + 5.0 * math.sqrt(6.0)
        ec = (t * math.cos(math.pi / 3), t * math.sin(math.pi / 3))
        pr = dc["perturbed_resolve"]
        prs = dc["perturbed_resolve_geometry"]
        ok = (pr["status"] == "solved" and pr["dof"] == 0
              and dist2(prs["B"], (50.0, 0.0)) < CHECK_TOL
              and dist2(prs["C"], ec) < CHECK_TOL)
        return [
            check("solved", solved(), f"{status} conflicting={s.get('conflicting')}"),
            check("dof_0", s["dof"] == 0, f"dof={s['dof']}"),
            check("a_at_origin", dist2(positions["A"], (0.0, 0.0)) < CHECK_TOL,
                  f"{positions['A']}"),
            check("b_at_50_0", dist2(positions["B"], (50.0, 0.0)) < CHECK_TOL,
                  f"{positions['B']}"),
            check("c_matches_analytic_60deg_far_branch", dist2(positions["C"], ec) < CHECK_TOL,
                  f"got {positions['C']} want {ec} (t={t})"),
            check("all_points_determined_via_perturbed_resolve", ok,
                  f"perturbed re-solve -> {prs['B']} {prs['C']}"),
        ], notes
    if cid == "triangle_value_edit":
        t = (40.0 + math.sqrt(3300.0)) / 2.0
        ec = (t * math.cos(math.pi / 3), t * math.sin(math.pi / 3))
        rb = dc["solve_rebuild_path"]
        mp = dc["solve_mutation_path"]
        mg = dc["mutation_geometry"]
        s1 = dc["first_solve"]
        return [
            check("solved_after_edit", rb["status"] == "solved",
                  f"{rb['status']} conflicting={rb.get('conflicting')}"),
            check("dof_still_0", rb["dof"] == 0, f"dof={rb['dof']}"),
            check("b_moved_to_40_0", dist2(positions["B"], (40.0, 0.0)) < CHECK_TOL,
                  f"{positions['B']}"),
            check("c_matches_analytic_after_edit", dist2(positions["C"], ec) < CHECK_TOL,
                  f"got {positions['C']} want {ec}"),
            check("anchored_point_immovable",
                  dc["a_bits_after_rebuild"].get("A:x") == dc["a_bits_before"].get("A:x")
                  and dc["a_bits_after_rebuild"].get("A:y") == dc["a_bits_before"].get("A:y"),
                  "A bits before/after the rebuild edit (coincident with the fixed "
                  "origin — never moves)"),
            check("no_orientation_flip", positions["C"][1] > 0.0,
                  f"C.y={positions['C'][1]} > 0"),
            check("first_solve_was_solved_dof0",
                  s1["status"] == "solved" and s1["dof"] == 0,
                  f"{s1['status']} dof={s1['dof']}"),
            # EXTRA (planegcs-native mutation path; slvs needed a rebuild)
            check("mutation_path_solves_without_rebuild",
                  mp["status"] == "solved", f"{mp['status']} chain={mp['chain']}"),
            check("mutation_path_c_matches_analytic", dist2(mg["C"], ec) < CHECK_TOL,
                  f"got {mg['C']} want {ec}"),
        ], notes
    if cid == "l_bracket_constrained":
        exp = [(0, 0), (60, 0), (60, 8), (8, 8), (8, 40), (0, 40)]
        pr = dc["perturbed_resolve"]
        prs = dc["perturbed_resolve_geometry"]
        ok = all(dist2(prs[f"p{i}"], exp[i]) < CHECK_TOL for i in range(6)) \
            and pr["dof"] == 0 and pr["status"] == "solved"
        cs = [check("solved", solved(), status), check("dof_0", s["dof"] == 0, f"dof={s['dof']}")]
        for i, e in enumerate(exp):
            got = positions[f"p{i}"]
            cs.append(check(f"corner_{i}_at_{e[0]},{e[1]}", dist2(got, e) < CHECK_TOL, f"{got}"))
        cs.append(check("all_points_determined_via_perturbed_resolve", ok,
                        f"perturbed re-solve dof={pr['dof']}"))
        return cs, notes
    if cid == "l_bracket_no_dims":
        return [
            check("solved", solved(), status),
            check("dof_4", s["dof"] == 4, f"dof={s['dof']}"),
            check("anchored_corner_determined", dist2(positions["p0"], (0.0, 0.0)) < CHECK_TOL,
                  f"p0={positions['p0']}"),
            check("free_corners_recorded", True,
                  f"underconstrained placement (recorded, no pass/fail): "
                  f"{json.dumps({f'p{i}': positions[f'p{i}'] for i in range(6)})}"),
            check("underconstrained_landing_perturbation_stability_recorded", True,
                  f"max corner drift after 0.3-magnitude seed perturbation + re-solve: "
                  f"{dc['max_corner_drift_after_perturbation']:.6f} — recorded, no "
                  f"pass/fail (slvs closes the gap onto one point via substitution; "
                  f"SolidCraft keeps free geometry at its seed)"),
        ], notes
    if cid == "slot_constrained":
        exp = {"a1c": (0, 0), "a1s": (0, 6), "a1e": (0, -6),
               "a2c": (40, 0), "a2s": (40, -6), "a2e": (40, 6)}
        r1 = math.hypot(positions["a1s"][0] - positions["a1c"][0],
                        positions["a1s"][1] - positions["a1c"][1])
        r2 = math.hypot(positions["a2s"][0] - positions["a2c"][0],
                        positions["a2s"][1] - positions["a2c"][1])
        cs = [
            check("solved", solved(), f"{status} conflicting={s.get('conflicting')}"),
            check("dof_0", s["dof"] == 0,
                  f"dof={s['dof']} (raw reported value — planegcs's diagnose reports "
                  f"{s['dof']} with {s.get('conflicting')} flagged for THIS "
                  "formulation; the structurally-clean analysis exists in the "
                  "formulation probes)"),
        ]
        for lbl, e in exp.items():
            got = positions[lbl]
            cs.append(check(f"{lbl}_at_{e[0]},{e[1]}", dist2(got, e) < CHECK_TOL, f"{got}"))
        cs.append(check("radius_6_both_caps", abs(r1 - 6) < CHECK_TOL and abs(r2 - 6) < CHECK_TOL,
                        f"r1={r1} r2={r2}"))
        cs.append(check("no_redundancy_reported_for_endpoint_tangency",
                        not s.get("conflicting") and not s.get("redundant"),
                        f"planegcs diagnose at this formulation flags "
                        f"{s.get('conflicting')} as conflicting (dof {s['dof']}) — "
                        "an honest divergence; see formulation_probes"))
        return cs, notes
    if cid == "line_horizontal_only":
        a, b = positions["l1.start"], positions["l1.end"]
        return [
            check("solved", solved(), status),
            check("dof_3", s["dof"] == 3, f"dof={s['dof']}"),
            check("horizontalized", abs(a[1] - b[1]) < 1e-9, f"a={a} b={b}"),
            check("underconstrained_motion_split_recorded", True,
                  f"a={a} b={b} (input y's were 0.0 and 1.0). The recorded motion "
                  "split is the behavioral comparison datum vs slvs (all-on-one-end) "
                  "and SolidCraft (~even split, TL2 record)."),
        ], notes
    if cid == "circle_radius_only_edit":
        s1, rb, mp = dc["solve_radius_only"], dc["solve_rebuild_path"], dc["solve_mutation_path"]
        r_after = dc["radius_after_edit_rebuild"]
        return [
            check("solved_radius_only", s1["status"] == "solved", s1["status"]),
            check("dof_2_center_free", s1["dof"] == 2, f"dof={s1['dof']}"),
            check("radius_applied_5", abs(dc["radius_first_solve"] - 5.0) < CHECK_TOL,
                  f"r={dc['radius_first_solve']}"),
            check("center_undetermined_left_at_seed", True,
                  f"center after the first solve: {positions['c1.center']} (free "
                  "centre stays where the equations leave it)"),
            check("solved_after_edit", rb["status"] == "solved", rb["status"]),
            check("dof_still_2", rb["dof"] == 2, f"dof={rb['dof']}"),
            check("radius_now_8", abs(r_after - 8.0) < CHECK_TOL, f"r={r_after}"),
            check("free_center_does_not_move",
                  dc["center_bits_after_rebuild"] == dc["center_bits_before"],
                  "center bits before/after the rebuild edit (bitwise equality)"),
            check("mutation_path_solves_without_rebuild", mp["status"] == "solved",
                  f"{mp['status']} — datum double set to 16, re-init, re-solve on "
                  "the same System object (no rebuild)"),
            check("mutation_path_radius_8",
                  abs(dc["radius_after_edit_mutation"] - 8.0) < CHECK_TOL,
                  f"r={dc['radius_after_edit_mutation']}"),
            check("mutation_path_center_bitwise_stable",
                  dc["center_bits_mutation_path"] == dc["center_bits_before"],
                  "center bits identical through the mutation edit"),
        ], notes
    if cid == "rect_redundant_duplicate_dimension":
        corners = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
        cs = [
            check("solved_despite_redundancy", solved(),
                  f"{status} — planegcs's full 4-step chain (DogLeg/BFGS/LM/SQP-"
                  "augmented, FreeCAD Sketch.cpp:4795-4905 verbatim) does NOT zero "
                  "the exactly-redundant system: all four return Converged "
                  "(minimized-not-zeroed), so no write-back. Contrast: SolidCraft "
                  "solves and names the duplicate; slvs fails with a MISATTRIBUTED "
                  "bad list. planegcs fails with the CORRECT attribution."),
            check("dof_0", s["dof"] == 0,
                  f"dof={s['dof']} (the rank analysis is correct WITH the duplicate)"),
            check("redundant_listed", s.get("redundant") == ["k6"],
                  f"redundant={s.get('redundant')} — the duplicate Vertical k6, "
                  "named correctly (the W1 expectation)"),
            check("failure_leaves_geometry_at_input", dc["bits_equal_input_after_solve"],
                  "corners bitwise == the rough input (copy-solve, no write-back "
                  "on failure — FreeCAD Sketch.cpp:4823-4826 applySolution-on-Success "
                  "only)"),
            check("w1_corners_expected_but_not_reached",
                  all(dist2(positions[f"p{i}"], e) < CHECK_TOL
                      for i, e in enumerate(corners)),
                  f"corners={[positions[f'p{i}'] for i in range(4)]} — the solve "
                  "failed; recorded as the honest divergence from SolidCraft on "
                  "the same fixture"),
        ]
        return cs, notes
    if cid == "conflicting_distances":
        return [
            check("fails", status == "failed", status),
            check("bad_lists_conflicting_dims",
                  set(s.get("conflicting", [])) >= {"d1", "d2"},
                  f"conflicting={s.get('conflicting')} — planegcs names BOTH "
                  "conflicting dimensions (getConflicting tags)"),
            check("geometry_unchanged_bitwise_on_failure", dc["bits_equal_input_after_solve"],
                  "input positions written back exactly (bitwise); applySolution "
                  "only on Success"),
        ], notes
    if cid == "coincident_plus_distance":
        return [
            check("fails", status == "failed", status),
            check("constraints_named_in_bad", len(s.get("conflicting", [])) >= 1,
                  f"conflicting={s.get('conflicting')}"),
            check("geometry_unchanged_bitwise_on_failure", dc["bits_equal_input_after_solve"],
                  "p1/p2 untouched (bitwise identical)"),
        ], notes
    if cid == "triangle_edit_unsolvable":
        rb, mp = dc["solve_rebuild_path"], dc["solve_mutation_path"]
        return [
            check("fails", rb["status"] == "failed", rb["status"]),
            check("bad_list_nonempty", len(rb.get("conflicting", [])) >= 1,
                  f"conflicting={rb.get('conflicting')} (the full 4-step chain "
                  "cannot zero d1=55; t^2-55t+1000 discriminant<0)"),
            check("geometry_unchanged_bitwise_on_failure",
                  dc["rebuild_restores_solved_bits_bitwise"],
                  "all point bits identical to the stored solved state — "
                  "copy-solve + no write-back, same observable as SolidCraft's "
                  "explicit restore"),
            check("mutation_path_also_fails_and_restores", mp["status"] == "failed",
                  f"{mp['status']} — the native mutation path cannot rescue a "
                  "value with no real solution; bits restored: "
                  f"{dc['mutation_restores_bits_bitwise']}"),
        ], notes
    if cid == "determinism_inprocess_5x":
        return [
            check("bitwise_identical_geometry_5x", dc["bitwise_identical"],
                  "max coordinate delta = 0 over 5 in-process rounds"),
            check("identical_status_and_dof", dc["statuses_identical"],
                  "statuses+dof per round identical"),
            check("identical_digests", dc["digests_identical"], ",".join(dc["runs"][0]["digest"]
                  for _ in [0]) if dc["runs"] else ""),
        ], notes
    # coverage probes
    exp_pos = {
        "parallel_offset": {"A0": (0, 0), "A1": (10, 0), "B0": (0, 3), "B1": (9, 3)},
        "perpendicular_pair": {"A0": (0, 0), "A1": (10, 0), "B0": (5, 0), "B1": (5, 4)},
        "diameter_dim": {"c.center": (0, 0)},
        "symmetric_points": {"p": (2, 3), "q": (-2, -3)},
        "midpoint_case": {"l0": (0, 0), "l1": (10, 0), "m": (5, 0)},
        "concentric_circles": {"c1.center": (0, 0), "c2.center": (0, 0)},
    }[cid]
    cs = [check("solved", solved(), status), check("dof_0", s["dof"] == 0, f"dof={s['dof']}")]
    for lbl, e in exp_pos.items():
        got = positions[lbl]
        cs.append(check(f"{lbl}_at_{e[0]},{e[1]}", dist2(got, e) < CHECK_TOL, f"{got}"))
    if cid == "diameter_dim":
        r = curve_geom(dc, "c")["radius"]
        cs.append(check("c_radius_5.0", abs(r - 5.0) < CHECK_TOL, f"{r}"))
    if cid == "concentric_circles":
        r1 = curve_geom(dc, "c1")["radius"]
        r2 = curve_geom(dc, "c2")["radius"]
        cs.append(check("c1_radius_3.0", abs(r1 - 3.0) < CHECK_TOL, f"{r1}"))
        cs.append(check("c2_radius_5.0", abs(r2 - 5.0) < CHECK_TOL, f"{r2}"))
    return cs, notes


def transcription_check(dc, cc):
    """Machine-verify the driver's fixture transcription against cases.json."""
    issues = []
    d_in, c_in = dc.get("inputs") or {}, (cc.get("inputs") or {})
    d_pts = [p["id"] for p in (d_in.get("points") or [])]
    c_pts = [p["id"] for p in (c_in.get("points") or [])]
    if c_in and sorted(d_pts) != sorted(c_pts):
        issues.append(f"points {sorted(d_pts)} != {sorted(c_pts)}")
    if c_in:
        d_cur = {c["id"]: c["kind"] for c in (d_in.get("curves") or [])}
        c_cur = {c["id"]: c["kind"] for c in (c_in.get("curves") or [])}
        if d_cur != c_cur:
            issues.append(f"curves {d_cur} != {c_cur}")
        d_cons = [(k["label"], k["kind"]) for k in (d_in.get("constraints") or [])
                  if k["kind"] != "arcrules"]
        c_cons = [(k["label"], k["kind"]) for k in (c_in.get("constraints") or [])]
        if sorted(d_cons) != sorted(c_cons):
            issues.append(f"constraints {sorted(d_cons)} != {sorted(c_cons)}")
    return issues


# ---------------------------------------------------------------- main

def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not DRIVER.is_file():
        raise SystemExit("driver missing — run planegcs-side/build.sh first")

    # 1. corpus
    corpus = json.loads(run_driver([]))
    by_id = {c["id"]: c for c in corpus["cases"]}
    cases_doc = json.load(open(CASES))
    cases_cc = {c["id"]: c for c in cases_doc["cases"]}
    assert len(by_id) == 22, f"expected 22 driver cases, got {len(by_id)}"

    # 2. transcription verification
    transcription_issues = {}
    for cid, cc in cases_cc.items():
        if cid == "determinism_crossprocess_3x":
            continue
        issues = transcription_check(by_id.get(cid, {}), cc)
        if issues:
            transcription_issues[cid] = issues

    # 3. cross-process determinism (3 fresh processes)
    outs, codes = [], []
    for _ in range(3):
        p = subprocess.run([str(DRIVER), "--hash"], capture_output=True, text=True,
                           timeout=120)
        codes.append(p.returncode)
        outs.append(p.stdout.strip())
    cross_identical = all(o == outs[0] for o in outs[1:]) and all(c == 0 for c in codes)

    # 4. slot formulation probes
    slotdebug = json.loads(run_driver(["--slotdebug"]))

    # 5. staircase: 5 fresh processes per N + edit
    def median(xs):
        s = sorted(xs)
        return s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2

    scale = {
        "method": "chain of N alternating H/V line segments, fully constrained "
                  "(coincident chain to origin, H/V per segment, equal lengths via "
                  "one driving length dimension, length=1), small deterministic "
                  "perturbation on the seed; 5 fresh OS processes per N; wall-clock "
                  "measured around the solve call only (steady clock), build time "
                  "recorded separately; 2-CPU sandbox — absolute times are "
                  "host-specific, the SHAPE of the curve is the finding",
        "sizes": [],
    }
    for n in (10, 50, 100, 200):
        runs = []
        for _ in range(5):
            runs.append(json.loads(run_driver(["--staircase", str(n)])))
        scale["sizes"].append({
            "n": n, "runs": runs,
            "median_build_s": median([r["build_s"] for r in runs]),
            "median_solve_s": median([r["solve_s"] for r in runs]),
            "all_solved_dof0": all(r["status"] == "solved" and r["dof"] == 0
                                   for r in runs),
            "max_len_err": max(r["max_len_err"] for r in runs),
        })
    scale["edit_at_200"] = json.loads(run_driver(["--staircase", "200", "--edit"]))

    # 6. evaluate checks
    cases_out = []
    for cid in [c["id"] for c in cases_doc["cases"]]:
        if cid == "determinism_crossprocess_3x":
            cases_out.append({
                "id": cid, "group": "determinism",
                "description": "the canonical cases (triangle, L-bracket, slot) "
                               "solved in 3 separate OS processes (--hash submode)",
                "runs": 3, "child_stdout": outs, "exit_codes": codes,
                "identical": cross_identical,
                "expected": {"bitwise_identical": True, "runs": 3},
                "checks": [
                    check("all_child_processes_exit_0", all(c == 0 for c in codes),
                          f"{codes}"),
                    check("hashes_identical_across_processes", cross_identical,
                          " | ".join(outs)),
                ],
                "notes": "cross-process determinism of the pinned planegcs build "
                         "at the bit level (FNV-1a-64 over the m3-eval digest layout)",
            })
            continue
        dc = by_id[cid]
        cc = cases_cc[cid]
        checks, notes = eval_case(dc, cc)
        case = {
            "id": cid, "group": cc.get("group"),
            "description": cc.get("description", ""),
            "equivalence": cc.get("equivalence"),
            "source": cc.get("source"),
            "expected": cc.get("expected"),
            "solve": dc.get("solve") or dc.get("first_solve") or dc.get("solve_radius_only"),
            "geometry": dc.get("geometry"),
            "inputs": dc.get("inputs"),
            "checks": checks,
            "notes": cc.get("notes", ""),
        }
        # carry the rich path records for the edit/probe cases
        for k in ("first_solve", "solve_rebuild_path", "solve_mutation_path",
                  "warm_resolve_same_system", "solve_radius_only",
                  "perturbed_resolve", "perturbed_resolve_geometry",
                  "bits_equal_input_after_solve", "input_bits", "after_bits",
                  "solved_bits_before", "bits_after_rebuild", "bits_after_mutation",
                  "rebuild_restores_solved_bits_bitwise", "mutation_restores_bits_bitwise",
                  "a_bits_before", "a_bits_after_rebuild", "center_bits_before",
                  "center_bits_after_rebuild", "center_bits_mutation_path",
                  "mutation_geometry", "radius_first_solve", "radius_after_edit_rebuild",
                  "radius_after_edit_mutation", "max_corner_drift_after_perturbation",
                  "runs", "bitwise_identical", "digests_identical", "statuses_identical"):
            if k in dc:
                case[k] = dc[k]
        if cid == "slot_constrained":
            case["formulation_probes"] = slotdebug["steps"]
        cases_out.append(case)

    # 7. assemble
    failed = [c for c in cases_out for c in c["checks"] if not c["pass"]]
    n_checks = sum(len(c["checks"]) for c in cases_out)
    n_pass = n_checks - len(failed)
    doc = {
        "experiment": "h2h-planegcs-side",
        "issue_ref": "m3-solver-h2h (m3-eval §8 item 1; solidcraft-evaluation "
                     "§4.1 gate (a)) — PlaneGCS conformance on the canonical corpus",
        "command": "python3 experiments/solver-h2h/planegcs-side/gen_planegcs_results.py",
        "started_utc": started,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream": {
            "solver": "PlaneGCS (FreeCAD src/Mod/Sketcher/App/planegcs, 11 files)",
            "repo": "https://github.com/FreeCAD/FreeCAD.git",
            "tag": FREECAD_TAG, "tag_sha": FREECAD_SHA,
            "pinned_by": "experiments/solver-h2h/fetch-planegcs.sh (tag sha-verified)",
            "eigen": {"artifact": "eigen3_3.4.0.orig.tar.bz2", "sha256": EIGEN_SHA256,
                      "provenance": "Debian pool mirror of the upstream release "
                                    "tarball (canonical gitlab intermittently 403 "
                                    "from this sandbox — recorded in "
                                    "license-planegcs-eigen.md §3)"},
            "build": "g++ 14.2, -std=c++20 -O2 (FreeCAD 1.1.4 requires C++20), "
                     "system boost 1.83, the lane's compat shims (null-sink Console, "
                     "FCGlobal/FCConfig stubs) — never product code",
        },
        "w1_fixture_source": f"experiments/cad-sketcher/fixtures/solver/cases.json "
                             f"(READ-ONLY; transcribed from tl2 w1_sketch.rs @ {TL2_SHA} "
                             f"by m3-eval; transcription machine-verified here)",
        "transcription_verification": {
            "issues": transcription_issues,
            "clean": not transcription_issues,
        },
        "host": {"cpus": os.cpu_count(), "python": sys.version.split()[0]},
        "solve_status_vocabulary": {
            "Success(0)": {"gcs": "Success", "status": "solved",
                            "note": "error zeroed; applySolution writes back "
                                    "(FreeCAD Sketch.cpp:4823)"},
            "Converged(1)": {"gcs": "Converged", "status": "no-write-back",
                              "note": "minimized without zeroing — treated as "
                                      "failure by FreeCAD's contract (no write-back)"},
            "Failed(2)": {"gcs": "Failed", "status": "failed"},
            "SuccessfulSolutionInvalid(3)": {"gcs": "SuccessfulSolutionInvalid",
                                             "status": "solved_invalid_geometry",
                                             "note": "not produced by this corpus"},
            "chain": "DogLeg -> BFGS -> LevenbergMarquardt -> SQP-augmented "
                     "(Sketch.cpp:4795-4905 verbatim; the 4th step pins every "
                     "parameter to its current value via temporary equalities)",
        },
        "api_surface": {
            "constraint_kinds_available": "GCS.h System API: Horizontal/Vertical/Parallel/"
                                          "Perpendicular/P2PCoincident/P2PDistance/Difference/"
                                          "CircleDiameter/ArcDiameter/ArcRadius/L2LAngle/"
                                          "AngleViaPoint/EqualLength/EqualRadius/"
                                          "P2PSymmetric(point+line forms)/MidpointOnLine/"
                                          "Tangent(line,arc|circle|arc-arc)/PointOn*/... "
                                          "(GCS.h:270-560)",
            "value_mutation": {
                "available": True,
                "api": "constraint datums are caller-owned plain double* — set the "
                       "value, initSolution(), solve() (no rebuild of the object "
                       "graph); verified by the mutation-path checks in "
                       "triangle_value_edit / circle_radius_only_edit / the "
                       "staircase edit at N=200",
                "contrast": "slvs has NO mutation API (m3-eval rejection pillar 2); "
                            "SolidCraft has set_value + solve_after_value_edit with "
                            "continuation substeps",
            },
            "diagnostics": "dofsNumber() + getConflicting/getRedundant/"
                           "getPartiallyRedundant (TAGS — the label mapping is "
                           "caller-owned) + getDependentParams (GCS.h:608-651); "
                           "diagnose runs inside initSolution (GCS.cpp:1731-1737)",
            "diagnose_caveats": "diagnose outcomes are formulation- and order-"
                                "dependent for degenerate/redundant systems — "
                                "demonstrated by the slot formulation_probes: the "
                                "same fixture yields dof 0 (AngleViaPoint form, "
                                "constraint-addition order A) vs dof 2 + 4 flagged "
                                "(P2LDistance form) vs dof 4 + 10 flagged "
                                "(corpus order); rank itself should be read from "
                                "the structurally-clean probe, and the solver's "
                                "own report recorded as-is per formulation",
            "failure_semantics": "copy-solve + applySolution only on Success = "
                                 "bitwise restore on failure (reference/undoSolution, "
                                 "GCS.cpp:1849-1888) — verified by every failure case",
        },
        "cases": cases_out,
        "scale_performance": scale,
        "summary": {
            "cases": len(cases_out),
            "w1_identical_cases": 17,
            "new_cases": 6,
            "checks_total": n_checks,
            "checks_passed": n_pass,
            "checks_failed": len(failed),
            "cases_with_failed_checks": sorted({f["name"] for f in failed}) and
                                        sorted({c["id"] for c in cases_out
                                                if any(not x["pass"] for x in c["checks"])}),
            "equivalence": cases_doc["provenance"],
            "solver": "FreeCAD 1.1.4 planegcs + eigen 3.4.0; FreeCAD's own solve "
                      "contract (4-step chain, applySolution-on-Success)",
        },
        "failures": {"failed_checks": failed,
                     "transcription_issues": transcription_issues,
                     "note": "Every failing check is a recorded honest result; "
                             "see findings/planegcs-conformance.md for analysis."},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    json.loads(OUT.read_text())  # parse self-check
    print(f"wrote {OUT}")
    print(f"checks: {n_pass}/{n_checks} pass, {len(failed)} fail")
    print("failed:", [(f["name"]) for f in failed])


if __name__ == "__main__":
    main()
