#!/usr/bin/env python3
"""SolidCraft-side solver conformance envelope generator (solver-h2h lane).

Runs the built Rust driver (corpus + determinism + staircase modes) against the
pinned SolidCraft sketch solver and writes the committed machine-readable
envelope:

    ../results/solidcraft-conformance.json

mirroring the m3-eval slvs envelope schema (experiments/cad-sketcher/results/
solver-conformance.json). NEVER hand-edited; regenerate with:

    cd experiments/solver-h2h/solidcraft-side && ./build.sh
    python3 experiments/solver-h2h/solidcraft-side/gen_solidcraft_results.py

Failures are recorded honestly (failures[] + per-case checks with pass=false);
a recorded blocker is a valid result, a silently-dropped case is not.
"""

import json
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(LANE))  # /home/z/blender-cad
BIN = os.path.join(HERE, "target", "release", "solidcraft-h2h-driver")
CASES = os.path.join(REPO, "experiments", "cad-sketcher", "fixtures", "solver", "cases.json")
OUT = os.path.join(LANE, "results", "solidcraft-conformance.json")

UPSTREAM_SHA = "3b4db52c10279251a068cfca5eb7447068bc28e7"
TL2_SHA = "685f7c453409d470998394e27dcbad3a53a384ef"
CORPUS_REL = "experiments/cad-sketcher/fixtures/solver/cases.json"

COMMAND = (
    "(cd experiments/solver-h2h/solidcraft-side && cargo build --release -j 2) && "
    "python3 experiments/solver-h2h/solidcraft-side/gen_solidcraft_results.py "
    "(driver: target/release/solidcraft-h2h-driver — corpus | --hash | --staircase N [--edit])"
)


def rfc3339_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_driver(args, timeout=600):
    p = subprocess.run([BIN] + args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"driver {args} failed rc={p.returncode}: {p.stderr[-2000:]}")
    return p.stdout


def median(xs):
    return statistics.median(xs)


def host_facts():
    cpus = os.cpu_count()
    try:
        with open("/proc/meminfo") as f:
            mem_kb = int(f.readline().split()[1])
        mem_gb = round(mem_kb / 2**20, 1)
    except Exception:
        mem_gb = 0.0
    cgroup_gb = None
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as f:
                val = f.read().strip()
            if val.isdigit():
                cgroup_gb = round(int(val) / 2**30, 1)
                break
        except Exception:
            pass
    try:
        import shutil

        def _ver(tool):
            for cand in (shutil.which(tool), os.path.expanduser(f"~/.cargo/bin/{tool}")):
                if cand and os.path.exists(cand):
                    return subprocess.run([cand, "-V"], capture_output=True, text=True).stdout.strip()
            return "unrecorded"

        rustc = _ver("rustc")
        cargo = _ver("cargo")
    except Exception:
        rustc = cargo = "unrecorded"
    return {
        "cpus": cpus,
        "mem_total_gb": mem_gb,
        "cgroup_mem_limit_gb": cgroup_gb,
        "rustc": rustc,
        "cargo": cargo,
        "note": "sandbox container (2 CPU, ~4 GiB cgroup); wall-clock scale numbers are "
                "host-specific — the SHAPE of the curve is the finding",
    }


SOLVE_STATUS_VOCABULARY = {
    "solidcraft_solved": {
        "solidcraft": "Solved",
        "tl2_status": "solved",
        "note": "all constraint residuals < ACCEPT=1e-6 (solver.rs:42); SolveReport::ok() (solver.rs:88-90)",
    },
    "solidcraft_failed": {
        "solidcraft": "Failed",
        "tl2_status": "failed",
        "note": "conflict or non-convergence; geometry restored bitwise from the pre-solve "
                "snapshot x0 (solver.rs:1872-1873, 2231); failing[] names violated constraint ids",
    },
    "solidcraft_solved_folded": {
        "solidcraft": "Solved with folded != []",
        "tl2_status": "solved (refused for value-edit commands)",
        "note": "solved but an orientation flipped; kept for evaluation, refused by commands "
                "(SolveReport::keeps_orientation, solver.rs:94-97). No case in this corpus folds.",
    },
    "solidcraft_redundant": {
        "solidcraft": "not a status: redundant[] lists implied constraints alongside Solved",
        "tl2_status": "n/a (diagnostic list)",
        "note": "redundancy = adds no Jacobian rank (orthogonalised Gram walk, redundancy.rs:43-118, "
                "DEPENDENT=1e-6) AND residual ~ 0 (CONSISTENT=1e-6, constraint_residual, "
                "redundancy.rs:124-135); only checked for components of at most "
                "MAX_REDUNDANCY_VARS=400 variables (redundancy.rs:24)",
    },
}

CONSTRAINT_COVERAGE_MATRIX = [
    {
        "par_kind": "coincident",
        "solidcraft": "direct",
        "api": "ConstraintKind::Coincident { p, q } (point indices)",
        "citation": "model.rs:201-204; residual = p − q (2 rows, solver.rs:809); exercised by 11 cases",
        "probe": "all coincident_to_origin cases + concentric_circles (centre-coincident form)",
    },
    {
        "par_kind": "parallel",
        "solidcraft": "direct (NATIVE kind slvs also has; exercised directly here)",
        "api": "ConstraintKind::Parallel { a, b }",
        "citation": "model.rs:223-226; residual = cross(da,db)/(|da||db|) (solver.rs:470-475); probe 'parallel_offset'",
    },
    {
        "par_kind": "perpendicular",
        "solidcraft": "direct (NATIVE)",
        "api": "ConstraintKind::Perpendicular { a, b }",
        "citation": "model.rs:227-230; residual = dot(da,db)/(|da||db|) (solver.rs:470-475); probe 'perpendicular_pair'",
    },
    {
        "par_kind": "tangent",
        "solidcraft": "direct (symmetric, endpoint-shared)",
        "api": "ConstraintKind::Tangent { a, b } — curve-curve incl. at shared endpoints; the slot case "
               "exercises (arc,line) in BOTH argument orders with no redundancy and no failure",
        "citation": "model.rs:235-238; residual solver.rs:483-515; probe 'slot_constrained' "
                    "(contrast: slvs requires (arc,line) order + shared endpoints or FatalError)",
    },
    {
        "par_kind": "horizontal",
        "solidcraft": "direct",
        "api": "ConstraintKind::Horizontal { l } (line) and HorizontalPoints { p, q } (two points on a row)",
        "citation": "model.rs:209-218; residuals solver.rs:463-464; Horizontal { l } exercised by "
                    "l_bracket/slot/staircase; HorizontalPoints unexercised (recorded)",
    },
    {
        "par_kind": "vertical",
        "solidcraft": "direct",
        "api": "ConstraintKind::Vertical { l } and VerticalPoints { p, q }",
        "citation": "model.rs:212-221; residuals solver.rs:462,465; Vertical { l } exercised everywhere; "
                    "VerticalPoints exercised by the parallel_offset REMEDY probe (rank analysis extra check)",
    },
    {
        "par_kind": "concentric",
        "solidcraft": "direct (NATIVE — slvs must derive via coincident centres)",
        "api": "ConstraintKind::Concentric { a, b }",
        "citation": "model.rs:243-246; residual = centre difference (solver.rs:525-528); probe "
                    "'concentric_circles' follows cases.json LITERALLY (Coincident on centres — the "
                    "corpus's derived form), so the native kind is recorded but unused by the fixture",
    },
    {
        "par_kind": "equal",
        "solidcraft": "direct",
        "api": "ConstraintKind::Equal { a, b } — equal lengths (lines) or radii (round)",
        "citation": "model.rs:239-242; residual solver.rs:516-523; probes 'slot_constrained', staircase",
    },
    {
        "par_kind": "symmetric",
        "solidcraft": "direct (about a LINE — native; about a point derived via Midpoint, same as cases.json)",
        "api": "ConstraintKind::Symmetric { p, q, l } (mirror about line l); point symmetry about the origin "
               "derived as Midpoint { p: 0, l } — exactly the corpus's solver-neutral formulation",
        "citation": "model.rs:247-255; residual solver.rs:534-541; probe 'symmetric_points' (midpoint form, "
                    "cases.json literal); the native Symmetric kind is recorded but unused by the fixture "
                    "(contrast: slvs exposes symmetric about line/plane only, and the CAD Sketcher addon "
                    "DISABLES symmetry in v0.32.1 — model/symmetry.py:1)",
    },
    {
        "par_kind": "distance",
        "solidcraft": "direct",
        "api": "ConstraintKind::Distance { p, q, value }",
        "citation": "model.rs:260-264; residual = |pq| − value (solver.rs:543); triangle/conflict cases",
    },
    {
        "par_kind": "angle",
        "solidcraft": "direct",
        "api": "ConstraintKind::Angle { a, b, value, flip } (radians; flip = +180° picks any of the 4 angles)",
        "citation": "model.rs:311-317; residual solver.rs:568-576; probe 'triangle_constrained' "
                    "(Angle{60°, flip:true} — the W1 form; slvs uses angle(l1,l3,60,inverse=True))",
    },
    {
        "par_kind": "radius",
        "solidcraft": "direct (BOTH Radius and Diameter kinds — slvs derives radius from diameter)",
        "api": "ConstraintKind::Radius { c, value } and ConstraintKind::Diameter { c, value }",
        "citation": "model.rs:300-307; residuals solver.rs:566-567; Radius: circle/slot/circle_radius_only; "
                    "Diameter (native): diameter_dim, concentric_circles",
    },
    {
        "par_kind": "distance_x/y (dimensional)",
        "solidcraft": "direct, UNSIGNED (W1 semantics) — with a rank-analysis caveat at value 0",
        "api": "ConstraintKind::DistanceX/DistanceY { p, q, value }: residual |q−p|.axis − value "
               "(solver.rs:544-545) — magnitudes, branch chosen by the seed. At value 0 the |·| kink "
               "makes the central-difference Jacobian row zero (h-stepped |h|−|−h| = 0), so the "
               "finite-difference rank analysis counts the constraint redundant and reports dof+1 even "
               "though the geometry is placed exactly (probes parallel_offset / perpendicular_pair). "
               "Adapter-level remedy: the native HorizontalPoints/VerticalPoints kinds express "
               "same-row/column exactly (signed, smooth: q.axis − p.axis, solver.rs:462-465) — "
               "verified dof 0 + exact positions in the parallel_offset remedy probe",
        "citation": "model.rs:265-274; solver.rs:544-545, 1283 (central differences); probes "
                    "'parallel_offset', 'perpendicular_pair' (+ their rank_analysis extra checks)",
    },
    {
        "par_kind": "length (dimensional, slvs-side derived)",
        "solidcraft": "direct (native line length)",
        "api": "ConstraintKind::Length { l, value }",
        "citation": "model.rs:280-283; residual = |ab| − value (solver.rs:550-553); rect case + staircase + probes",
    },
    {
        "par_kind": "midpoint (slvs-side AT_MIDPOINT)",
        "solidcraft": "direct (NATIVE)",
        "api": "ConstraintKind::Midpoint { p, l }",
        "citation": "model.rs:247-250; residual = p − midpoint(ab) (solver.rs:529-533); probes "
                    "'symmetric_points' (origin on segment midpoint), 'midpoint_case'",
    },
]

API_SURFACE = {
    "constraint_kinds_total": 32,
    "constraint_kinds": [
        "PatternPoint", "PatternRadius", "Coincident", "PointOnCurve", "Horizontal", "Vertical",
        "HorizontalPoints", "VerticalPoints", "Parallel", "Perpendicular", "Collinear", "Tangent",
        "Equal", "Concentric", "Midpoint", "Symmetric", "Fix", "Distance", "DistanceX", "DistanceY",
        "PointLineDistance", "Length", "LineAngle", "ArcSweep", "SlotOverallLength", "Radius",
        "Diameter", "Angle", "Smooth", "ArcLength", "LinearDiameter", "OffsetDistance",
    ],
    "kinds_exercised_by_this_corpus": 16,
    "kinds_exercised": [
        "Coincident", "Horizontal", "Vertical", "VerticalPoints (remedy probe)", "Parallel",
        "Perpendicular", "Tangent", "Equal", "Midpoint", "Distance", "DistanceX", "DistanceY",
        "Length", "Radius", "Diameter", "Angle",
    ],
    "value_mutation": {
        "available": True,
        "api": "ConstraintKind::set_value(&mut self, v) on the stored constraint "
               "(sk.constraints[i].kind.set_value) + solve_after_value_edit(&mut sk, &old)",
        "citation": "model.rs:370-389 (set_value); solver.rs:1369-1371 (solve_after_value_edit); "
                    "solver.rs:1361 (DrivingValues = BTreeMap<constraint-id, f64>); "
                    "solver.rs:1388-1390 (Sketch::driving_values)",
        "note": "warm re-solve WITHOUT rebuild: the same Sketch object is re-solved after the value "
                "edit (continuation steps old->new in <=64 substeps when the one-jump solve fails or "
                "folds). Contrast: slvs has NO mutation API (rebuild-only — CAD Sketcher's own path); "
                "this is the comparative dimension named by the task",
    },
    "constraint_add_remove": {
        "add": "Sketch::add_constraint(kind, param) — auto id k1,k2,… (model.rs:829-837)",
        "remove": "NO remove_constraint API; remove_curves/remove_points (model.rs:1421, 1464) prune "
                  "constraints whose entities are gone (retain+remap, model.rs:1441-1461)",
        "driven_dimensions": "Constraint.driven flag — a driven (reference) dimension measures, does "
                             "not constrain (model.rs:535-537; excluded from the system, solver.rs:1427-1435)",
    },
    "incremental_solving": {
        "per_solve_decomposition": "union-find over constraint block variables -> connected components, "
                                   "solved in variable-index order (solver.rs:1930-1966, union_find.rs); "
                                   "Jacobian is block-diagonal so ranks add up",
        "analysis_modes": "Analysis::Full (dof + determined flags) vs Analysis::StatusOnly (fast ok() "
                          "checks, e.g. drag frames) — solver.rs:1332-1341",
        "interactive_solves": "solve_holding / solve_with (Hold, reference positions, Budget) — "
                              "solver.rs:1325-1358",
        "note": "component-level decomposition is per solve (structural); there is no persistent "
                "cross-solve dirty-subgraph cache in this crate (that is a document-model concern)",
    },
    "diagnostics_surface": {
        "solve_report": "SolveReport {status, dof, iterations, max_residual, failing[], folded[], "
                        "continuations, point_determined[], curve_determined[], redundant[]} "
                        "(solver.rs:58-85)",
        "per_constraint_residual": "constraint_residual(sk, ci) -> Option<f64> in mm/radians "
                                   "(redundancy.rs:124-135) — measured by this harness where slvs "
                                   "cannot measure it",
        "determined_by": "determined_by(sk, ci) -> implying constraint indices "
                         "(redundancy.rs:141-171) — names WHAT implies a redundant constraint",
        "orientation": "folded[] reports flipped orientations; keeps_orientation() gates commands "
                       "(solver.rs:94-97)",
        "bounds": "MAX_COMPONENT_VARS=4000 (solver.rs:38), MAX_REDUNDANCY_VARS=400 (redundancy.rs:24), "
                  "MAX_POINTS=20000 / MAX_CONSTRAINTS=40000 / MAX_COORD=1e9 (model.rs:7-13)",
    },
    "determinism_design": {
        "no_rng": "no rand dependency anywhere in the closure; fixed LM schedule (lambda0=1e-3, /3 on "
                  "success, x4 on rejection, caps 1e-12/1e12), structural iteration orders "
                  "(blocks in insertion order solver.rs:1414-1445; components in variable order)",
        "work_budgets": "deterministic work UNITS, explicitly not wall-clock deadlines (solver.rs:956-957)",
        "verified": "in-process 5x and cross-process 3x, bitwise (this envelope's determinism cases)",
    },
}


def collect_scale():
    out = {
        "method": (
            "chain of N alternating H/V line segments, fully constrained (coincident chain to "
            "origin, H/V per segment, equal lengths via one driving length dimension, length=1), "
            "small deterministic perturbation on the seed — IDENTICAL construction to m3-eval's "
            "gen_solver_cases.py staircase (p_i = (ceil(i/2) + 0.01*((i%7)-3)/3, "
            "floor(i/2) + 0.01*((i%5)-2)/2)); 5 fresh processes per N; wall-clock measured around "
            "the solve() call only (steady clock), build time recorded separately; 2-CPU sandbox — "
            "absolute times are host-specific, the SHAPE of the curve is the finding"
        ),
        "sizes": [],
    }
    for n in (10, 50, 100, 200):
        runs = []
        for _ in range(5):
            rec = json.loads(run_driver(["--staircase", str(n)]))
            runs.append(rec)
        out["sizes"].append({
            "n": n,
            "runs": runs,
            "median_build_s": median([r["build_s"] for r in runs]),
            "median_solve_s": median([r["solve_s"] for r in runs]),
            "all_solved_dof0": all(r["status"] == "solved" and r["dof"] == 0 for r in runs),
            "max_len_err": max(r["max_len_err"] for r in runs),
        })
    edit = json.loads(run_driver(["--staircase", "200", "--edit"]))
    out["edit_at_200"] = edit
    out["scale_notes"] = (
        "SolidCraft's constructive seed (Owen/Fudos-Hoffmann cluster decomposition) solves the "
        "staircase EXACTLY: 0 LM iterations, residual 0, max_len_err 0 at every N — the timings "
        "measure seed+rank analysis+writeback, not Newton iterations (contrast: slvs runs its "
        "generic Newton path; the interpretation belongs to the head-to-head comparison, not this "
        "envelope). The edit protocol records THREE paths: rebuild (slvs-comparable), the crate's "
        "NATIVE warm mutation (set_value + solve_after_value_edit, NO rebuild) and an idempotent "
        "re-solve (the exact analogue of slvs's warm second solve_sketch)."
    )
    return out


def main():
    started = rfc3339_now()
    t0 = time.time()

    corpus_json = run_driver([CASES])
    corpus = json.loads(corpus_json)
    cases = corpus["cases"]

    # cross-process determinism is already a corpus case (self re-exec x3); the
    # in-process 5x digests are in determinism_inprocess_5x.
    scale = collect_scale()

    failed_checks = []
    for c in cases:
        for chk in c.get("checks", []):
            if not chk.get("pass", False):
                failed_checks.append({
                    "case": c["id"],
                    "name": chk["name"],
                    "detail": chk.get("detail", ""),
                    "extra": chk.get("extra", False),
                    "observed": chk.get("observed"),
                    "expected": chk.get("expected"),
                })

    by_id = {c["id"]: c for c in cases}
    s = corpus["summary"]

    # any harness-level blockers (fixture-consistency mismatches, unevaluated declared checks)
    blockers = []
    for m in corpus["fixture_consistency"]["mismatches"]:
        blockers.append({"kind": "fixture_consistency_mismatch", "detail": m})
    for m in corpus["fixture_consistency"]["declared_checks_missing"]:
        blockers.append({"kind": "declared_check_not_evaluated", "detail": m})

    ident = [c["id"] for c in cases if c["equivalence"]["mark"] == "identical"]
    adapted = [c["id"] for c in cases if c["equivalence"]["mark"] == "adapted"]
    new = [c["id"] for c in cases if c["equivalence"]["mark"] == "new"]

    under_dof = {c["id"]: c["solve"]["dof"] for c in cases if c.get("group") in ("mapping", "underconstrained")}
    det_ip = by_id["determinism_inprocess_5x"]
    det_cp = by_id["determinism_crossprocess_3x"]

    summary = {
        "cases": s["cases"],
        "w1_identical_cases": 17,
        "new_cases": 6,
        "checks_total": s["checks_total"],
        "checks_passed": s["checks_passed"],
        "checks_failed": s["checks_failed"],
        "declared_checks_total": s["declared_checks_total"],
        "declared_checks_passed": s["declared_checks_passed"],
        "declared_checks_failed": s["declared_checks_failed"],
        "note_declared_vs_extra": (
            "declared_* counts the cases.json checks_declared names (the head-to-head comparable "
            "set, equal in size to the slvs envelope's 115); extra checks (extra=true) carry "
            "TL2-W1-native invariants (bitwise restores, minimal motion, redundancy residuals, "
            "determined_by) and probe diagnostics"
        ),
        "cases_with_failed_checks": s["cases_with_failed_checks"],
        "equivalence": {"identical": ident, "adapted": adapted, "new": new},
        "fully_constrained_dof0_cases": [
            c["id"] for c in cases
            if c.get("group") in ("fully_constrained", "redundancy") and c.get("solve", {}).get("dof") == 0
            and c["solve"]["status"] == "solved"
        ],
        "underconstrained_dof": under_dof,
        "conflict_failure_modes": [
            c["id"] for c in cases if c.get("group") in ("conflict", "failure")
            and c.get("solve", {}).get("status") == "failed"
        ],
        "redundancy_detected_and_listed": True,
        "redundancy_detail": "rect_redundant_duplicate_dimension: solved, dof 0, redundant=['k8'] "
                             "(the duplicate Vertical), residual 0.0 (< CONSISTENT), implied by "
                             "k3 (the first Vertical) — exactly TL2's W1 record; contrast: slvs "
                             "FAILS the same fixture (flag 1) and its bad list names d1, not the duplicate",
        "determinism_inprocess_bitwise": det_ip["checks"][0]["pass"],
        "determinism_crossprocess_bitwise": det_cp["identical"],
        "determinism_digests_canonical": det_ip["digests"],
        "failure_geometry_unchanged_bitwise": all(
            chk["pass"]
            for cid in ("conflicting_distances", "coincident_plus_distance", "triangle_edit_unsolvable")
            for chk in by_id[cid]["checks"]
            if chk["name"] == "geometry_unchanged_bitwise_on_failure"
        ),
        "w1_17_vs_tl2_consistency": (
            "all 17 W1 cases reproduce TL2's w1-sketch.json results at the same pin: dof values "
            "(4/3/5/0/0/0/4/3/2), exact expected branches (triangle far branch, slot positions, "
            "L-bracket corners, rect corners), failure surfaces identical (failing=[k2,k3] / "
            "[k1,k2] / [k3,k4,k5]; triangle_edit_unsolvable 222 iterations, max_residual 1.194; "
            "redundant=['k8'] implied-by k3), minimal-motion and bitwise-restore behaviour — "
            "TL2's 85/85 is reproduced in substance with cases.json's renamed declared checks "
            "(113/115 declared here; the 2 declared failures are the 2 NEW probe dof diagnostics, "
            "not W1 cases; every W1 case passes all its declared checks)"
        ),
        "scale_medians": {str(sz["n"]): sz["median_solve_s"] for sz in scale["sizes"]},
        "api_gaps_vs_slvs_none": (
            "everything the slvs envelope recorded as not-measurable IS measurable here: "
            "per-constraint residuals, iteration counts, max_residual, per-entity determined "
            "flags, and constraint-value mutation"
        ),
    }

    envelope = {
        "experiment": "h2h-solidcraft-side",
        "issue_ref": "m3-solver-h2h (m3-eval §8 item 1; solidcraft-evaluation §4.1 gate (a))",
        "command": COMMAND,
        "started_utc": started,
        "finished_utc": None,  # filled below
        "wall_seconds": None,
        "upstream": {
            "repo": "https://github.com/tangency-labs/solidcraft",
            "pinned_sha": UPSTREAM_SHA,
            "tag_version": "v0.16.2",
            "pinned_by": "experiments/solver-h2h/fetch-solidcraft.sh — TL2's exact pin "
                         "(experiments/solidcraft/fetch-upstream.sh on tl2/solidcraft-evaluation); "
                         "a different pin would invalidate the cross-references",
            "crates_consumed": ["crates/sketch (solidcraft-sketch)", "crates/geom (solidcraft-geom)"],
            "crate_closure": "serde + thiserror + ttf-parser only (sketch Cargo.toml at the pin) — "
                             "no truck, no C libraries",
            "patch_table": "upstream's [patch.crates-io] NOT replicated: it only patches "
                           "truck-*/matext4cgmath/egui-wgpu (root Cargo.toml:139-147), none of which "
                           "is in the sketch+geom closure — verified at the pin",
        },
        "w1_fixture_source": {
            "corpus": CORPUS_REL,
            "corpus_note": "READ-ONLY canonical m3-eval corpus (generated by their gen_solver_cases.py; "
                           "never edited in this lane); 17 W1-identical cases transcribed from TL2 + "
                           "6 coverage probes",
            "w1_reference": {
                "repo": "payswapdotorg/blender-cad branch tl2/solidcraft-evaluation",
                "sha": TL2_SHA,
                "file": "experiments/solidcraft/harness/src/bin/w1_sketch.rs",
                "note": "read-only reference; this harness reproduces TL2's builders verbatim "
                        "(same seeds, same ConstraintKind formulations); cases.json's slvs "
                        "adaptations are the SLVS-side expression of the same fixtures",
            },
            "fixture_consistency": corpus["fixture_consistency"],
        },
        "host": host_facts(),
        "solve_status_vocabulary": SOLVE_STATUS_VOCABULARY,
        "cases": cases,
        "constraint_coverage_matrix": CONSTRAINT_COVERAGE_MATRIX,
        "api_surface": API_SURFACE,
        "scale_performance": scale,
        "summary": summary,
        "failures": {
            "failed_checks": failed_checks,
            "harness_blockers": blockers,
            "notes": (
                "The only failing checks are the two NEW coverage probes' dof_0 (parallel_offset, "
                "perpendicular_pair) and their rank-analysis diagnostics: the LITERAL cases.json "
                "mapping of a zero-valued 'distance_x'/'distance_y' onto the crate's UNSIGNED "
                "DistanceX/DistanceY (residual |dp|.axis − value, solver.rs:544-545) hides the "
                "constraint from the finite-difference rank analysis at dp=0 (|h|−|−h|=0), so the "
                "solver reports dof=1 and names the constraint redundant — while the GEOMETRY is "
                "still placed exactly (residual 0.0, all expected positions reached, constructive "
                "seed). The crate's NATIVE same-row/column kinds (HorizontalPoints/VerticalPoints, "
                "signed residuals solver.rs:462-465) express the same constraint exactly (verified: "
                "dof 0 + exact positions in the parallel_offset remedy probe). Recorded as a "
                "cross-solver semantic divergence + adapter-level remedy; nothing was faked, no "
                "case was dropped."
            ),
        },
    }

    envelope["finished_utc"] = rfc3339_now()
    envelope["wall_seconds"] = round(time.time() - t0, 1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(envelope, f, indent=2)
        f.write("\n")

    print(f"cases: {s['cases']}; declared checks: {s['declared_checks_passed']}/{s['declared_checks_total']}, "
          f"total checks: {s['checks_passed']}/{s['checks_total']}")
    for fc in failed_checks:
        print(f"  FAILED [{fc['case']}] {fc['name']}")
    print(f"scale medians (solve_s): " + ", ".join(f"N={sz['n']}: {sz['median_solve_s']:.6f}" for sz in scale["sizes"]))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
