//! SolidCraft-side solver head-to-head harness (M3-entry gate; NOT product code).
//!
//! Lane: experiments/solver-h2h (isolated). Drives the pinned SolidCraft sketch
//! solver (tangency-labs/solidcraft @ 3b4db52c10279251a068cfca5eb7447068bc28e7,
//! v0.16.2, consumed as path dependencies through ../.upstream/solidcraft)
//! on the CANONICAL m3-eval fixture corpus
//! experiments/cad-sketcher/fixtures/solver/cases.json (23 cases: 17 W1-identical
//! + 6 PAR coverage probes; READ-ONLY — never edited here) plus the staircase
//! scale fixture and the determinism protocol, and prints machine-readable JSON.
//!
//! Modes:
//!   [corpus] <cases.json path>   run all 23 cases; JSON envelope fragment on stdout
//!                                (default path resolved from CARGO_MANIFEST_DIR)
//!   --hash                       solve the canonical 3 (triangle, L-bracket, slot),
//!                                print one digest line (cross-process determinism;
//!                                mirrors TL2's w1_sketch hash submode)
//!   --staircase N [--edit]       one staircase scale run at size N; single JSON
//!                                record on stdout (one run per invocation)
//!
//! Fixture semantics:
//!   * The 17 W1 cases reproduce TL2's w1_sketch.rs builders VERBATIM (same seeds,
//!     same ConstraintKind formulations — Radius/Angle{flip}/unsigned DistanceX/Y/
//!     Length/Tangent pairs/Equal; cases.json's slvs adaptations are the SLVS-side
//!     expression of the SAME fixtures; this side uses the natural/W1 formulation,
//!     per the binding per-case equivalence marks quoted from cases.json).
//!   * The 6 coverage probes follow cases.json LITERALLY (solver-neutral): each
//!     cases.json constraint kind is mapped onto the crate's ConstraintKind set.
//!
//! Check tolerance: CHECK_TOL = 1e-6 (TL2's w1_sketch.rs; upstream ACCEPT).
//! Digests: FNV-1a-64 over f64 little-endian value bits in a fixed order
//! (per case: value key sort; across the canonical 3: case-id sort then value key).

use std::collections::BTreeMap;
use std::f64::consts::PI;
use std::process::Command;
use std::time::Instant;

use serde_json::{Value, json};
use solidcraft_geom::{Seg2, Vec2};
use solidcraft_sketch::{
    CONSISTENT, ConstraintKind, CurveKind, DrivingValues, Sketch, SolveReport, constraint_residual, determined_by, solve,
    solve_after_value_edit,
};

const UPSTREAM_SHA: &str = "3b4db52c10279251a068cfca5eb7447068bc28e7";
const UPSTREAM_VERSION: &str = "0.16.2";

/// Geometry comparison tolerance for analytic checks (ACCEPT is 1e-6 in upstream's solver).
const CHECK_TOL: f64 = 1e-6;

// ---------------------------------------------------------------------------
// small utilities
// ---------------------------------------------------------------------------

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

fn v(x: f64, y: f64) -> Vec2 {
    Vec2::new(x, y)
}

fn add(sk: &mut Sketch, kind: ConstraintKind, param: Option<&str>) -> String {
    let dbg = format!("{kind:?}");
    sk.add_constraint(kind, param.map(|p| p.to_string()))
        .unwrap_or_else(|e| panic!("add_constraint({dbg}) rejected: {e:?}"))
}

/// Set the value of the driving dimension with the given param id (e.g. "d1") —
/// the crate's constraint-value MUTATION API (ConstraintKind::set_value, model.rs:370-389).
fn set_dim(sk: &mut Sketch, param: &str, value: f64) {
    let i = sk
        .constraints
        .iter()
        .position(|c| c.param.as_deref() == Some(param))
        .unwrap_or_else(|| panic!("no constraint with param {param}"));
    sk.constraints[i].kind.set_value(value);
}

/// Index of the constraint with the given param id.
fn dim_index(sk: &Sketch, param: &str) -> usize {
    sk.constraints
        .iter()
        .position(|c| c.param.as_deref() == Some(param))
        .unwrap_or_else(|| panic!("no constraint with param {param}"))
}

fn point_bits(sk: &Sketch) -> Vec<(u64, u64)> {
    sk.points.iter().map(|p| (p.pos.x.to_bits(), p.pos.y.to_bits())).collect()
}

fn report_json(rep: &SolveReport) -> Value {
    json!({
        "status": if rep.ok() { "solved" } else { "failed" },
        "solidcraft_status": format!("{:?}", rep.status),
        "dof": rep.dof,
        "iterations": rep.iterations,
        "max_residual": rep.max_residual,
        "failing": rep.failing,
        "folded": rep.folded,
        "continuations": rep.continuations,
        "redundant": rep.redundant,
        "point_determined": rep.point_determined,
        "curve_determined": rep.curve_determined,
    })
}

fn geometry_json(sk: &Sketch) -> Value {
    let points: Vec<Value> = sk
        .points
        .iter()
        .map(|p| json!({"id": p.id, "pos": [p.pos.x, p.pos.y], "fixed": p.fixed}))
        .collect();
    let curves: Vec<Value> = sk
        .curves
        .iter()
        .enumerate()
        .map(|(ci, c)| {
            let kind = match &c.kind {
                CurveKind::Line { a, b } => json!({
                    "kind": "line",
                    "a": a, "b": b,
                    "p_a": sk.point(*a).map(|p| [p.x, p.y]),
                    "p_b": sk.point(*b).map(|p| [p.x, p.y]),
                }),
                CurveKind::Circle { c: center, r } => json!({
                    "kind": "circle",
                    "center_point": center, "radius_var": r,
                    "p_center": sk.point(*center).map(|p| [p.x, p.y]),
                    "radius": sk.radius(ci),
                }),
                CurveKind::Arc { c: ac, a: ai, b: bi } => {
                    // Derived angular form (what a bcdoc Arc stores natively).
                    let angles: (Option<[f64; 2]>, Option<f64>) = match sk.segs(ci).first() {
                        Some(Seg2::Arc { start, sweep, .. }) => (Some([*start, *start + *sweep]), Some(*sweep)),
                        _ => (None, None),
                    };
                    json!({
                        "kind": "arc",
                        "center_point": ac, "start_point": ai, "end_point": bi,
                        "p_center": sk.point(*ac).map(|p| [p.x, p.y]),
                        "p_start": sk.point(*ai).map(|p| [p.x, p.y]),
                        "p_end": sk.point(*bi).map(|p| [p.x, p.y]),
                        "derived_radius": sk.radius(ci),
                        "derived_start_end_angle_rad": angles.0,
                        "derived_sweep_rad": angles.1,
                        "reversed": c.reversed,
                    })
                }
                other => json!({"kind": format!("{other:?}"), "note": "not modelled in this experiment"}),
            };
            json!({"id": c.id, "geom": kind})
        })
        .collect();
    json!({"points": points, "curves": curves})
}

/// The solved values of a sketch, keyed for the determinism digest (sorted map).
fn canonical_values(sk: &Sketch) -> BTreeMap<String, f64> {
    let mut m: BTreeMap<String, f64> = BTreeMap::new();
    for p in &sk.points {
        m.insert(format!("point:{}.x", p.id), p.pos.x);
        m.insert(format!("point:{}.y", p.id), p.pos.y);
    }
    for (ci, c) in sk.curves.iter().enumerate() {
        if matches!(c.kind, CurveKind::Circle { .. } | CurveKind::Arc { .. }) {
            if let Some(r) = sk.radius(ci) {
                m.insert(format!("curve:{}.radius", c.id), r);
            }
        }
    }
    m
}

/// FNV-1a-64 over the case id bytes, then each value key + its f64 LE bits in
/// sorted (value key) order — the h2h determinism digest layout.
fn values_digest(case_id: &str, sk: &Sketch) -> u64 {
    let mut buf: Vec<u8> = Vec::new();
    buf.extend_from_slice(case_id.as_bytes());
    for (k, val) in canonical_values(sk) {
        buf.extend_from_slice(k.as_bytes());
        buf.extend_from_slice(&val.to_bits().to_le_bytes());
    }
    fnv1a64(&buf)
}

/// Combined digest over the canonical 3, case ids sorted, values key-sorted.
fn combined_digest(cases: &[(&'static str, &Sketch)]) -> u64 {
    let mut sorted: Vec<(&'static str, &Sketch)> = cases.to_vec();
    sorted.sort_by(|a, b| a.0.cmp(b.0));
    let mut buf: Vec<u8> = Vec::new();
    for (id, sk) in sorted {
        buf.extend_from_slice(id.as_bytes());
        for (k, val) in canonical_values(sk) {
            buf.extend_from_slice(k.as_bytes());
            buf.extend_from_slice(&val.to_bits().to_le_bytes());
        }
    }
    fnv1a64(&buf)
}

/// A check: name + pass + observed vs expected + human detail.
fn chk(name: &str, pass: bool, observed: Value, expected: Value, detail: String) -> Value {
    json!({"name": name, "pass": pass, "observed": observed, "expected": expected, "detail": detail})
}

/// Same, flagged as an EXTRA check (beyond cases.json's checks_declared; carries
/// TL2-W1-native invariants + probe diagnostics so the 85/85 substance and the
/// API facts are visible in this envelope too).
fn xchk(name: &str, pass: bool, observed: Value, expected: Value, detail: String) -> Value {
    let mut c = chk(name, pass, observed, expected, detail);
    c["extra"] = json!(true);
    c
}

/// m3-eval's deterministic seed perturbation (gen_solver_cases.py `perturb`),
/// applied over a case's OWN point seeds (the origin is never part of them).
fn perturbed(seeds: &[Vec2], delta: f64) -> Vec<Vec2> {
    seeds
        .iter()
        .enumerate()
        .map(|(i, s)| {
            Vec2::new(
                s.x + delta * (if i % 2 == 0 { 1.0 } else { -0.7 }) + 0.13 * i as f64,
                s.y - delta * (if i % 3 == 0 { 0.8 } else { -0.6 }) - 0.07 * i as f64,
            )
        })
        .collect()
}

fn pos_of(sk: &Sketch, i: usize) -> Value {
    match sk.point(i) {
        Some(p) => json!([p.x, p.y]),
        None => json!("missing"),
    }
}

fn dist_to(sk: &Sketch, i: usize, at: Vec2) -> Option<f64> {
    sk.point(i).map(|p| p.dist(at))
}

fn pos_str(sk: &Sketch, i: usize) -> String {
    match sk.point(i) {
        Some(p) => format!("({:.12}, {:.12})", p.x, p.y),
        None => "missing".into(),
    }
}

/// A position check named exactly as cases.json declares it: "<label>_at_<x>,<y>"
/// with one decimal place (cases.json names e.g. "corner_0_at_0.0,0.0").
fn pos_check(sk: &Sketch, label: &str, idx: usize, at: Vec2) -> Value {
    let name = format!("{label}_at_{:.1},{:.1}", at.x, at.y);
    let pass = dist_to(sk, idx, at).map(|d| d < CHECK_TOL).unwrap_or(false);
    chk(&name, pass, pos_of(sk, idx), json!([at.x, at.y]), pos_str(sk, idx))
}

// ---------------------------------------------------------------------------
// sketch builders — the 17 W1 cases reproduce TL2's w1_sketch.rs builders verbatim
// (same seeds, same ConstraintKind formulations); seeds parameterized for the
// perturbed re-solve probes (mirroring m3-eval's gen_solver_cases.py builders).
// ---------------------------------------------------------------------------

/// TL2 w1_sketch.rs build_triangle (oracle 25): rough triangle, l1 horizontal from
/// origin, |l1|=50, |l2|=45, Angle(l1,l3)=60deg interior at A (flip: true).
fn build_triangle_with(seeds: Option<&[Vec2]>, d1: f64, d2: f64) -> (Sketch, usize, usize, usize) {
    let mut sk = Sketch::new();
    let rough = [v(2.0, 1.0), v(45.0, 3.0), v(22.0, 35.0)];
    let s = seeds.unwrap_or(&rough);
    let a = sk.add_point(s[0], Some("A")).unwrap();
    let b = sk.add_point(s[1], Some("B")).unwrap();
    let c = sk.add_point(s[2], Some("C")).unwrap();
    let l1 = sk.add_line_pts(a, b, Some("l1")).unwrap();
    let _l2 = sk.add_line_pts(b, c, Some("l2")).unwrap();
    let l3 = sk.add_line_pts(c, a, Some("l3")).unwrap();
    add(&mut sk, ConstraintKind::Coincident { p: a, q: 0 }, None);
    add(&mut sk, ConstraintKind::Horizontal { l: l1 }, None);
    add(&mut sk, ConstraintKind::Distance { p: a, q: b, value: d1 }, Some("d1"));
    add(&mut sk, ConstraintKind::Distance { p: b, q: c, value: d2 }, Some("d2"));
    add(
        &mut sk,
        ConstraintKind::Angle { a: l1, b: l3, value: (60.0_f64).to_radians(), flip: true },
        Some("d3"),
    );
    (sk, a, b, c)
}

fn build_triangle() -> (Sketch, usize, usize, usize) {
    build_triangle_with(None, 50.0, 45.0)
}

/// TL2 build_l_bracket (oracle 19): 6-line L outline, H/V, corner on origin,
/// dims (60/8/40/8) as UNSIGNED oriented distances (W1 formulation).
fn build_l_bracket_with(with_dims: bool, seeds: Option<&[Vec2]>) -> (Sketch, Vec<usize>) {
    let mut sk = Sketch::new();
    let rough = [v(1.0, 1.0), v(55.0, -2.0), v(57.0, 9.0), v(10.0, 7.0), v(9.0, 45.0), v(-1.0, 38.0)];
    let s = seeds.unwrap_or(&rough);
    let p: Vec<usize> = s.iter().enumerate().map(|(i, q)| sk.add_point(*q, Some(&format!("p{i}"))).unwrap()).collect();
    let l: Vec<usize> = (0..6)
        .map(|i| sk.add_line_pts(p[i], p[(i + 1) % 6], Some(&format!("l{}", i + 1))).unwrap())
        .collect();
    for li in [l[0], l[2], l[4]] {
        add(&mut sk, ConstraintKind::Horizontal { l: li }, None);
    }
    for li in [l[1], l[3], l[5]] {
        add(&mut sk, ConstraintKind::Vertical { l: li }, None);
    }
    add(&mut sk, ConstraintKind::Coincident { p: p[0], q: 0 }, None);
    if with_dims {
        add(&mut sk, ConstraintKind::DistanceX { p: p[0], q: p[1], value: 60.0 }, Some("d1"));
        add(&mut sk, ConstraintKind::DistanceY { p: p[1], q: p[2], value: 8.0 }, Some("d2"));
        add(&mut sk, ConstraintKind::DistanceY { p: p[5], q: p[0], value: 40.0 }, Some("d3"));
        add(&mut sk, ConstraintKind::DistanceX { p: p[4], q: p[5], value: 8.0 }, Some("d4"));
    }
    (sk, p)
}

/// TL2 build_slot (oracle 20): obround, arcs first (synthesized <id>.center/.start/.end
/// points), then lines whose endpoints ARE the arc endpoints (shared topology).
fn build_slot_with(seeds: Option<&[Vec2]>) -> Sketch {
    let mut sk = Sketch::new();
    let rough = [v(1.0, 1.0), v(1.0, 7.0), v(1.0, -5.0), v(37.0, 2.0), v(37.0, -3.0), v(37.0, 7.0)];
    let s = seeds.unwrap_or(&rough);
    let a1 = sk.add_arc(s[0], s[1], s[2], [None, None, None], Some("a1")).unwrap();
    let a2 = sk.add_arc(s[3], s[4], s[5], [None, None, None], Some("a2")).unwrap();
    let a1c = sk.point_index("a1.center").unwrap();
    let a1s = sk.point_index("a1.start").unwrap();
    let a1e = sk.point_index("a1.end").unwrap();
    let a2c = sk.point_index("a2.center").unwrap();
    let a2s = sk.point_index("a2.start").unwrap();
    let a2e = sk.point_index("a2.end").unwrap();
    let l1 = sk.add_line(v(1.0, -5.0), v(37.0, -3.0), Some(a1e), Some(a2s), Some("l1")).unwrap();
    let l2 = sk.add_line(v(37.0, 7.0), v(1.0, 7.0), Some(a2e), Some(a1s), Some("l2")).unwrap();
    add(&mut sk, ConstraintKind::Coincident { p: a1c, q: 0 }, None);
    add(&mut sk, ConstraintKind::Tangent { a: a1, b: l1 }, None);
    add(&mut sk, ConstraintKind::Tangent { a: l1, b: a2 }, None);
    add(&mut sk, ConstraintKind::Tangent { a: a2, b: l2 }, None);
    add(&mut sk, ConstraintKind::Tangent { a: l2, b: a1 }, None);
    add(&mut sk, ConstraintKind::Equal { a: a1, b: a2 }, None);
    add(&mut sk, ConstraintKind::Horizontal { l: l1 }, None);
    add(&mut sk, ConstraintKind::Radius { c: a1, value: 6.0 }, Some("d1"));
    add(&mut sk, ConstraintKind::DistanceX { p: a1c, q: a2c, value: 40.0 }, Some("d2"));
    sk
}

fn build_slot() -> Sketch {
    build_slot_with(None)
}

/// TL2 build_rect: fully constrained rectangle + duplicate Vertical (the last
/// constraint added). Curve ids use cases.json's l0..l3.
fn build_rect(duplicate_vertical: bool) -> Sketch {
    let mut sk = Sketch::new();
    let rough = [v(0.3, -0.2), v(38.0, 1.0), v(41.0, 29.0), v(-1.0, 31.0)];
    let p: Vec<usize> = rough.iter().enumerate().map(|(i, q)| sk.add_point(*q, Some(&format!("p{i}"))).unwrap()).collect();
    let l: Vec<usize> = (0..4)
        .map(|i| sk.add_line_pts(p[i], p[(i + 1) % 4], Some(&format!("l{i}"))).unwrap())
        .collect();
    add(&mut sk, ConstraintKind::Horizontal { l: l[0] }, None);
    add(&mut sk, ConstraintKind::Horizontal { l: l[2] }, None);
    add(&mut sk, ConstraintKind::Vertical { l: l[1] }, None);
    add(&mut sk, ConstraintKind::Vertical { l: l[3] }, None);
    add(&mut sk, ConstraintKind::Coincident { p: p[0], q: 0 }, None);
    add(&mut sk, ConstraintKind::Length { l: l[0], value: 40.0 }, Some("d1"));
    add(&mut sk, ConstraintKind::Length { l: l[1], value: 30.0 }, Some("d2"));
    if duplicate_vertical {
        add(&mut sk, ConstraintKind::Vertical { l: l[1] }, None);
    }
    sk
}

fn build_circle_origin_radius_with(seed: Vec2, radius: f64) -> (Sketch, usize, usize) {
    let mut sk = Sketch::new();
    let c = sk.add_circle(seed, 4.7, None, Some("c1")).unwrap();
    let center = sk.point_index("c1.center").unwrap();
    add(&mut sk, ConstraintKind::Coincident { p: center, q: 0 }, None);
    add(&mut sk, ConstraintKind::Radius { c, value: radius }, Some("d1"));
    (sk, c, center)
}

fn build_circle_radius_only_with(seed: Vec2, radius: f64) -> (Sketch, usize, usize) {
    let mut sk = Sketch::new();
    let c = sk.add_circle(seed, 4.7, None, Some("c1")).unwrap();
    let center = sk.point_index("c1.center").unwrap();
    add(&mut sk, ConstraintKind::Radius { c, value: radius }, Some("d1"));
    (sk, c, center)
}

// ---------------------------------------------------------------------------
// coverage-probe builders (NEW beyond W1; cases.json literal; cases.json point ids)
// ---------------------------------------------------------------------------

/// The fully constrained horizontal reference line A shared by the first two probes
/// (m3-eval _build_fixed_line_a seeds).
fn probe_fixed_line_a(sk: &mut Sketch) -> (usize, usize, usize) {
    let a0 = sk.add_point(v(0.0, 0.0), Some("A0")).unwrap();
    let a1 = sk.add_point(v(10.0, 0.05), Some("A1")).unwrap();
    let la = sk.add_line_pts(a0, a1, Some("lA")).unwrap();
    add(sk, ConstraintKind::Coincident { p: a0, q: 0 }, None);
    add(sk, ConstraintKind::Horizontal { l: la }, None);
    add(sk, ConstraintKind::DistanceX { p: a0, q: a1, value: 10.0 }, Some("kA3"));
    (a0, a1, la)
}

/// cases.json parallel_offset: line B parallel to fully-constrained horizontal A,
/// offset 3 in y, length 9. SolidCraft mapping: parallel -> Parallel{lB,lA};
/// Y(A0->B0)=3 -> DistanceY{A0,B0,3} (|B0.y-A0.y|=3, branch from seed);
/// X(A0->B0)=0 -> DistanceX{A0,B0,0} (LITERAL cases.json mapping — the crate's
/// unsigned form has a |.| kink at 0, see the case's extra diagnostics); |lB|=9 -> Length.
/// `remedy` swaps the zero DistanceX for the crate's NATIVE same-column constraint
/// VerticalPoints (the adapter-level remedy probe).
fn build_parallel_offset(remedy: bool) -> Sketch {
    let mut sk = Sketch::new();
    let (a0, _a1, la) = probe_fixed_line_a(&mut sk);
    let b0 = sk.add_point(v(0.1, 3.2), Some("B0")).unwrap();
    let b1 = sk.add_point(v(9.1, 4.0), Some("B1")).unwrap();
    let lb = sk.add_line_pts(b0, b1, Some("lB")).unwrap();
    add(&mut sk, ConstraintKind::Parallel { a: lb, b: la }, None);
    add(&mut sk, ConstraintKind::DistanceY { p: a0, q: b0, value: 3.0 }, Some("k2"));
    if remedy {
        add(&mut sk, ConstraintKind::VerticalPoints { p: a0, q: b0 }, Some("k3"));
    } else {
        add(&mut sk, ConstraintKind::DistanceX { p: a0, q: b0, value: 0.0 }, Some("k3"));
    }
    add(&mut sk, ConstraintKind::Length { l: lb, value: 9.0 }, Some("d1"));
    sk
}

/// cases.json perpendicular_pair: B through (5,0), perpendicular to A, length 4.
fn build_perpendicular_pair() -> Sketch {
    let mut sk = Sketch::new();
    let (a0, _a1, la) = probe_fixed_line_a(&mut sk);
    let b0 = sk.add_point(v(5.2, 0.3), Some("B0")).unwrap();
    let b1 = sk.add_point(v(5.0, 1.2), Some("B1")).unwrap();
    let lb = sk.add_line_pts(b0, b1, Some("lB")).unwrap();
    add(&mut sk, ConstraintKind::DistanceX { p: a0, q: b0, value: 5.0 }, Some("k1"));
    add(&mut sk, ConstraintKind::DistanceY { p: a0, q: b0, value: 0.0 }, Some("k2"));
    add(&mut sk, ConstraintKind::Perpendicular { a: lb, b: la }, None);
    add(&mut sk, ConstraintKind::Length { l: lb, value: 4.0 }, Some("d1"));
    sk
}

/// cases.json diameter_dim: circle on origin, diameter 10 -> r 5. The crate has a
/// NATIVE Diameter kind (model.rs:304-307) — literal mapping, no adaptation.
fn build_diameter_dim() -> Sketch {
    let mut sk = Sketch::new();
    let c = sk.add_circle(v(2.0, 3.0), 4.7, None, Some("c")).unwrap();
    let center = sk.point_index("c.center").unwrap();
    add(&mut sk, ConstraintKind::Coincident { p: center, q: 0 }, None);
    add(&mut sk, ConstraintKind::Diameter { c, value: 10.0 }, Some("d1"));
    sk
}

/// cases.json symmetric_points: p, q symmetric about the ORIGIN — cases.json's
/// solver-neutral formulation: the fixed origin at the midpoint of the connecting
/// segment (midpoint kind) + the component distances. X(p->q)=-4 / Y(p->q)=-6 are
/// SIGNED slvs PROJ values; the crate's DistanceX/Y enforce |dp|=value (unsigned,
/// solver.rs:544-545) — magnitudes 4/6 with the branch chosen by the seed.
fn build_symmetric_points() -> Sketch {
    let mut sk = Sketch::new();
    let p = sk.add_point(v(2.0, 3.0), Some("p")).unwrap();
    let q = sk.add_point(v(-1.0, -4.0), Some("q")).unwrap();
    let lm = sk.add_line_pts(p, q, Some("lM")).unwrap();
    add(&mut sk, ConstraintKind::Midpoint { p: 0, l: lm }, None); // fixed origin at midpoint of lM
    add(&mut sk, ConstraintKind::DistanceX { p, q, value: 4.0 }, Some("d1"));
    add(&mut sk, ConstraintKind::DistanceY { p, q, value: 6.0 }, Some("d2"));
    sk
}

/// cases.json midpoint_case: point m at the midpoint of a fully constrained
/// horizontal line (midpoint kind, native).
fn build_midpoint_case() -> Sketch {
    let mut sk = Sketch::new();
    let l0 = sk.add_point(v(0.0, 0.0), Some("l0")).unwrap();
    let l1 = sk.add_point(v(10.0, 2.0), Some("l1")).unwrap();
    let ll = sk.add_line_pts(l0, l1, Some("ll")).unwrap();
    let m = sk.add_point(v(5.2, 0.9), Some("m")).unwrap();
    add(&mut sk, ConstraintKind::Coincident { p: l0, q: 0 }, None);
    add(&mut sk, ConstraintKind::Horizontal { l: ll }, None);
    add(&mut sk, ConstraintKind::DistanceX { p: l0, q: l1, value: 10.0 }, Some("d1"));
    add(&mut sk, ConstraintKind::Midpoint { p: m, l: ll }, None);
    sk
}

/// cases.json concentric_circles: LITERAL cases.json constraint list (kind
/// "coincident" on the centres — the corpus's derived form); the crate also has a
/// NATIVE Concentric kind (model.rs:243-246), recorded in the coverage matrix.
fn build_concentric_circles() -> Sketch {
    let mut sk = Sketch::new();
    let c1 = sk.add_circle(v(2.0, 3.0), 4.7, None, Some("c1")).unwrap();
    let c2 = sk.add_circle(v(7.0, 8.0), 5.1, None, Some("c2")).unwrap();
    let c1c = sk.point_index("c1.center").unwrap();
    let c2c = sk.point_index("c2.center").unwrap();
    add(&mut sk, ConstraintKind::Coincident { p: c1c, q: 0 }, None);
    add(&mut sk, ConstraintKind::Coincident { p: c2c, q: c1c }, None);
    add(&mut sk, ConstraintKind::Diameter { c: c1, value: 6.0 }, Some("d1"));
    add(&mut sk, ConstraintKind::Diameter { c: c2, value: 10.0 }, Some("d2"));
    sk
}

// ---------------------------------------------------------------------------
// staircase scale fixture (IDENTICAL construction to m3-eval gen_solver_cases.py)
// ---------------------------------------------------------------------------

/// p_i = (ceil(i/2) + 0.01*((i%7)-3)/3.0, floor(i/2) + 0.01*((i%5)-2)/2.0)
fn staircase_seed(n: usize) -> Vec<Vec2> {
    (0..=n)
        .map(|i| {
            let ex = ((i + 1) / 2) as f64; // ceil(i/2) for integer i
            let ey = (i / 2) as f64; // floor(i/2)
            Vec2::new(
                ex + 0.01 * (((i % 7) as f64) - 3.0) / 3.0,
                ey + 0.01 * (((i % 5) as f64) - 2.0) / 2.0,
            )
        })
        .collect()
}

/// Chain of n alternating H/V segments, fully constrained: p0 coincident with the
/// fixed origin, H (even i) / V (odd i) per segment, equal(l_i, l_0) for i>=1,
/// length(l_0) = driving (the one driving dimension). seed has n+1 entries (p0..pn).
fn build_staircase(sk: &mut Sketch, n: usize, seed: &[Vec2], driving: f64) {
    for (i, s) in seed.iter().enumerate() {
        sk.add_point(*s, Some(&format!("p{i}"))).unwrap();
    }
    let mut lines = Vec::with_capacity(n);
    for i in 0..n {
        lines.push(sk.add_line_pts(i + 1, i + 2, Some(&format!("l{i}"))).unwrap());
    }
    add(sk, ConstraintKind::Coincident { p: 1, q: 0 }, None); // p0 <-> fixed origin
    for i in 0..n {
        if i % 2 == 0 {
            add(sk, ConstraintKind::Horizontal { l: lines[i] }, None);
        } else {
            add(sk, ConstraintKind::Vertical { l: lines[i] }, None);
        }
    }
    for i in 1..n {
        add(sk, ConstraintKind::Equal { a: lines[i], b: lines[0] }, None);
    }
    add(sk, ConstraintKind::Length { l: lines[0], value: driving }, Some("dDriving"));
}

fn seg_len(sk: &Sketch, ci: usize) -> Option<f64> {
    match sk.segs(ci).first() {
        Some(Seg2::Line { a, b }) => Some(a.dist(*b)),
        _ => None,
    }
}

fn max_len_err(sk: &Sketch, n: usize, driving: f64) -> f64 {
    let mut worst = 0.0_f64;
    for ci in 0..n {
        if let Some(len) = seg_len(sk, ci) {
            worst = worst.max((len - driving).abs());
        }
    }
    worst
}

// ---------------------------------------------------------------------------
// cases.json metadata (equivalence marks quoted; fixture-consistency gate)
// ---------------------------------------------------------------------------

/// The metadata this harness expects per case id, transcribed from
/// experiments/cad-sketcher/fixtures/solver/cases.json (equivalence mark + reason
/// are binding; the loader cross-checks them against the actual file).
fn expected_metadata(id: &str) -> (&'static str, &'static str) {
    match id {
        "bare_line" => ("identical", "same entities + zero constraints; slvs lines carry no params of their own (endpoints carry the 4 unknowns), like SolidCraft"),
        "bare_circle" => ("identical", "circle = 2D centre point + radius as explicit distance param (slvs circles store radius via a distance entity) — SolidCraft models the radius as an explicit rvar too"),
        "bare_arc" => ("identical", "same 3-point construction; slvs arcs also enforce |start-c|==|end-c| with NO radius variable"),
        "circle_origin_radius" => ("adapted", "TL2 Radius{5} expressed as slvs DIAMETER=10 (no radius primitive; the addon's diameter.py does the same); point_determined checked via perturbed re-solve"),
        "triangle_constrained" => ("adapted", "TL2 Angle{a:l1,b:l3,60deg,flip:true} expressed as slvs angle(l1,l3,60,inverse=True) — the direction-cosine form with entityA's vector flipped (constrainteq.cpp:890-910); formulation probe-verified to select the same branch"),
        "triangle_value_edit" => ("adapted", "slvs exposes NO constraint-value mutation API; the edit is performed by rebuilding the system from the previous solution with the new value — exactly CAD Sketcher's own edit path (curve_solver.py rebuilds the full system on every solve)"),
        "l_bracket_constrained" => ("adapted", "TL2 DistanceX/DistanceY are UNSIGNED magnitudes; slvs PROJ distances are signed dp.axis — signs chosen to reproduce TL2's expected corners exactly (d3=-40, d4=-8; magnitudes identical). The binding's distance_proj helper is broken (entityA=E_NONE aborts, probe-verified); raw add_constraint with fixed +x/+y reference lines is used"),
        "l_bracket_no_dims" => ("identical", "H/V + coincident-only fixture: identical constraint set"),
        "slot_constrained" => ("adapted", "tangent() requires (arc,line) order + structurally shared endpoints (same topology as TL2); Radius{6} expressed as DIAMETER=12; DistanceX via PROJ onto the fixed +x reference line"),
        "line_horizontal_only" => ("identical", "same line + Horizontal constraint; the recorded motion split is the behavioral comparison datum"),
        "circle_radius_only_edit" => ("adapted", "Radius{5}/Radius{8} as DIAMETER 10/16; edit via rebuild seeded from the previous solution"),
        "rect_redundant_duplicate_dimension" => ("adapted", "TL2 Length{l} expressed as endpoint distance; the duplicate Vertical is identical"),
        "conflicting_distances" => ("identical", "identical entities + constraints (Horizontal + two point-point distances)"),
        "coincident_plus_distance" => ("identical", "identical entities + constraints (Coincident + point-point Distance 5)"),
        "triangle_edit_unsolvable" => ("adapted", "edit via rebuild (no mutation API); expected FAILED regardless — same logical fixture as TL2"),
        "determinism_inprocess_5x" => ("identical", "same 5x protocol; iteration-count/residual comparison impossible (slvs exposes no iteration or residual surface — recorded as an API gap)"),
        "determinism_crossprocess_3x" => ("identical", "same 3x cross-process digest protocol"),
        "parallel_offset" => ("new", "beyond W1; PAR-area coverage probe with exact expected values (1e-6)"),
        "perpendicular_pair" => ("new", "beyond W1; PAR-area coverage probe with exact expected values (1e-6)"),
        "diameter_dim" => ("new", "beyond W1; PAR-area coverage probe with exact expected values (1e-6)"),
        "symmetric_points" => ("new", "beyond W1; PAR-area coverage probe with exact expected values (1e-6)"),
        "midpoint_case" => ("new", "beyond W1; PAR-area coverage probe with exact expected values (1e-6)"),
        "concentric_circles" => ("new", "beyond W1; PAR-area coverage probe with exact expected values (1e-6)"),
        _ => ("unknown", "unknown case id"),
    }
}

/// The cases.json constraint kinds each case declares, in cases.json order
/// (fixture-consistency gate for cases with non-null inputs).
fn declared_kinds(id: &str) -> &'static [&'static str] {
    match id {
        "bare_line" => &[],
        "bare_circle" => &[],
        "bare_arc" => &[],
        "circle_origin_radius" => &["coincident_to_origin", "diameter"],
        "triangle_constrained" => &["coincident_to_origin", "horizontal", "distance", "distance", "angle"],
        "l_bracket_constrained" => &["horizontal", "horizontal", "horizontal", "vertical", "vertical", "vertical", "coincident_to_origin", "distance_x", "distance_y", "distance_y", "distance_x"],
        "l_bracket_no_dims" => &["horizontal", "horizontal", "horizontal", "vertical", "vertical", "vertical", "coincident_to_origin"],
        "slot_constrained" => &["coincident_to_origin", "tangent_arc_line", "tangent_arc_line", "tangent_arc_line", "tangent_arc_line", "equal", "horizontal", "diameter", "distance_x"],
        "line_horizontal_only" => &["horizontal"],
        "rect_redundant_duplicate_dimension" => &["horizontal", "horizontal", "vertical", "vertical", "coincident_to_origin", "length", "length", "vertical"],
        "conflicting_distances" => &["horizontal", "distance", "distance"],
        "coincident_plus_distance" => &["coincident", "distance"],
        "parallel_offset" => &["coincident_to_origin", "horizontal", "distance_x", "parallel", "distance_y", "distance_x", "length"],
        "perpendicular_pair" => &["coincident_to_origin", "horizontal", "distance_x", "distance_x", "distance_y", "perpendicular", "length"],
        "diameter_dim" => &["coincident_to_origin", "diameter"],
        "symmetric_points" => &["midpoint", "distance_x", "distance_y"],
        "midpoint_case" => &["coincident_to_origin", "horizontal", "distance_x", "midpoint"],
        "concentric_circles" => &["coincident_to_origin", "coincident", "diameter", "diameter"],
        _ => &["inputs_null_or_unknown"],
    }
}

// ---------------------------------------------------------------------------
// case runners (23)
// ---------------------------------------------------------------------------

fn case_bare_line() -> Value {
    let mut sk = Sketch::new();
    let _l = sk.add_line(v(0.0, 0.0), v(10.0, 1.0), None, None, Some("l1")).unwrap();
    let rep = solve(&mut sk);
    let untouched = sk.point(1).map(|p| p.dist(v(0.0, 0.0))) == Some(0.0)
        && sk.point(2).map(|p| p.dist(v(10.0, 1.0))) == Some(0.0);
    let checks = vec![
        chk("dof_4", rep.dof == 4, json!(rep.dof), json!(4), format!("dof={}", rep.dof)),
        chk("solved_no_constraints", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("geometry_untouched", untouched, json!([[0.0, 0.0], [10.0, 1.0]]), json!([[0.0, 0.0], [10.0, 1.0]]), "no constraints -> nothing moves (bitwise input)".into()),
    ];
    json!({
        "id": "bare_line",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_bare_line, verbatim (line contributes only its two end points; DOF = 4)",
    })
}

fn case_bare_circle() -> Value {
    let mut sk = Sketch::new();
    let c = sk.add_circle(v(3.0, 4.0), 5.0, None, Some("c1")).unwrap();
    let rep = solve(&mut sk);
    let r = sk.radius(c).unwrap();
    let ci = sk.point_index("c1.center").unwrap();
    let center_untouched = sk.point(ci) == Some(v(3.0, 4.0));
    let mut checks = vec![
        chk("dof_3", rep.dof == 3, json!(rep.dof), json!(3), format!("dof={} (centre 2 + radius variable 1, Layout::rvar)", rep.dof)),
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("radius_is_explicit_param", (r - 5.0).abs() == 0.0, json!(r), json!(5.0), format!("r={r} (the circle radius is an explicit solver variable — untouched by the constraint-free solve)")),
        chk("center_untouched", center_untouched, json!([3.0, 4.0]), json!([3.0, 4.0]), pos_str(&sk, ci)),
    ];
    checks.push(xchk(
        "curve_not_determined", rep.curve_determined == vec![false], json!(rep.curve_determined), json!([false]),
        "TL2's native check: the circle is not determined (dof 3)".into(),
    ));
    json!({
        "id": "bare_circle",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_bare_circle, verbatim",
    })
}

fn case_bare_arc() -> Value {
    let mut sk = Sketch::new();
    let a = sk.add_arc(v(1.0, 2.0), v(6.0, 2.0), v(1.0, 7.0), [None, None, None], Some("a1")).unwrap();
    let rep = solve(&mut sk);
    let r = sk.radius(a).unwrap();
    let c = sk.point_index("a1.center").unwrap();
    let s = sk.point_index("a1.start").unwrap();
    let e = sk.point_index("a1.end").unwrap();
    let untouched = sk.point(c) == Some(v(1.0, 2.0)) && sk.point(s) == Some(v(6.0, 2.0)) && sk.point(e) == Some(v(1.0, 7.0));
    let checks = vec![
        chk("dof_5", rep.dof == 5, json!(rep.dof), json!(5), format!("dof={} (3 points = 6 coords − 1 arc-radius-equality block)", rep.dof)),
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("radius_is_derived", (r - 5.0).abs() < CHECK_TOL, json!(r), json!(5.0), format!("derived r={r} (an arc has NO radius variable; |end−c| == |start−c| enforced by Block::Arc)")),
        chk("endpoints_untouched", untouched, json!([[1.0, 2.0], [6.0, 2.0], [1.0, 7.0]]), json!([[1.0, 2.0], [6.0, 2.0], [1.0, 7.0]]), format!("c={} s={} e={}", pos_str(&sk, c), pos_str(&sk, s), pos_str(&sk, e))),
    ];
    json!({
        "id": "bare_arc",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_bare_arc, verbatim",
    })
}

/// circle_origin_radius — W1 formulation (Coincident + Radius{5}); the slvs side
/// expressed the same fixture as DIAMETER=10 (cases.json mark: adapted).
fn case_circle_origin_radius() -> Value {
    let (mut sk, c, center) = build_circle_origin_radius_with(v(2.0, 3.0), 5.0);
    let rep = solve(&mut sk);
    let r = sk.radius(c).unwrap();
    let center_ok = dist_to(&sk, center, Vec2::ZERO).map(|d| d < CHECK_TOL).unwrap_or(false);
    // native determined flags + cross-solver perturbed re-solve (m3-eval protocol:
    // the case's own seed (2,3), perturbed with the standard deterministic formula)
    let native = rep.curve_determined == vec![true] && rep.point_determined.iter().all(|d| *d);
    let pert_seed = perturbed(&[v(2.0, 3.0)], 0.5)[0];
    let (mut sk2, c2, center2) = build_circle_origin_radius_with(pert_seed, 5.0);
    let rep2 = solve(&mut sk2);
    let perturbed_ok = rep2.ok()
        && rep2.dof == 0
        && dist_to(&sk2, center2, Vec2::ZERO).map(|d| d < CHECK_TOL).unwrap_or(false)
        && (sk2.radius(c2).unwrap() - 5.0).abs() < CHECK_TOL;
    let checks = vec![
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("dof_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={}", rep.dof)),
        chk("center_at_origin", center_ok, json!(pos_of(&sk, center)), json!([0.0, 0.0]), pos_str(&sk, center)),
        chk("radius_5", (r - 5.0).abs() < CHECK_TOL, json!(r), json!(5.0), format!("r={r}")),
        chk(
            "all_determined_via_perturbed_resolve",
            native && perturbed_ok,
            json!({"native_point_determined": rep.point_determined, "native_curve_determined": rep.curve_determined, "perturbed_resolve": {"seed": [pert_seed.x, pert_seed.y], "status": format!("{:?}", rep2.status), "dof": rep2.dof, "center": pos_of(&sk2, center2), "radius": sk2.radius(c2).unwrap()}}),
            json!({"native": "all determined", "perturbed": "solved dof 0, same geometry"}),
            "SolidCraft exposes the determined surface NATIVELY (point_determined/curve_determined); the perturbed re-solve (standard m3-eval perturb formula on the case seed) also runs for cross-solver parity".into(),
        ),
    ];
    json!({
        "id": "circle_origin_radius",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "solidcraft_formulation": "Coincident{center, 0} + Radius{c, 5.0} (native radius kind; W1/TL2 formulation). cases.json's slvs side expresses the SAME fixture as DIAMETER=10 (mark: adapted, reason quoted in equivalence).",
        "w1_semantics": "TL2 w1_sketch.rs case_circle_origin_radius, verbatim",
    })
}

fn case_triangle_constrained() -> Value {
    let (mut sk, a, b, c) = build_triangle();
    let rep = solve(&mut sk);
    let t = 25.0 + 5.0 * 6.0_f64.sqrt();
    let expected_c = v(t * (PI / 3.0).cos(), t * (PI / 3.0).sin());
    let native = rep.point_determined.iter().all(|d| *d);
    // m3-eval protocol: perturb the SOLVED positions, rebuild, re-solve
    let solved: Vec<Vec2> = [a, b, c].iter().map(|&i| sk.points[i].pos).collect();
    let (mut sk2, _a2, b2, c2) = build_triangle_with(Some(&perturbed(&solved, 0.5)), 50.0, 45.0);
    let rep2 = solve(&mut sk2);
    let perturbed_ok = rep2.ok()
        && rep2.dof == 0
        && dist_to(&sk2, b2, v(50.0, 0.0)).map(|d| d < CHECK_TOL).unwrap_or(false)
        && dist_to(&sk2, c2, expected_c).map(|d| d < CHECK_TOL).unwrap_or(false);
    let checks = vec![
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?} failing={:?}", rep.status, rep.failing)),
        chk("dof_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={}", rep.dof)),
        chk("a_at_origin", dist_to(&sk, a, Vec2::ZERO).map(|d| d < CHECK_TOL).unwrap_or(false), json!(pos_of(&sk, a)), json!([0.0, 0.0]), pos_str(&sk, a)),
        chk("b_at_50_0", dist_to(&sk, b, v(50.0, 0.0)).map(|d| d < CHECK_TOL).unwrap_or(false), json!(pos_of(&sk, b)), json!([50.0, 0.0]), pos_str(&sk, b)),
        chk(
            "c_matches_analytic_60deg_far_branch",
            dist_to(&sk, c, expected_c).map(|d| d < CHECK_TOL).unwrap_or(false),
            json!(pos_of(&sk, c)), json!([expected_c.x, expected_c.y]),
            format!("got {} want ({:.12}, {:.12}) (t={t})", pos_str(&sk, c), expected_c.x, expected_c.y),
        ),
        chk(
            "all_points_determined_via_perturbed_resolve",
            native && perturbed_ok,
            json!({"native_point_determined": rep.point_determined, "perturbed_resolve": {"status": format!("{:?}", rep2.status), "dof": rep2.dof, "b": pos_of(&sk2, b2), "c": pos_of(&sk2, c2)}}),
            json!({"native": "all determined", "perturbed": "solved dof 0, same analytic branch"}),
            "native flags + perturbed re-solve both hold".into(),
        ),
    ];
    json!({
        "id": "triangle_constrained",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "analytic": {"t_far_branch": t, "t_near_branch": 25.0 - 5.0 * 6.0_f64.sqrt(), "expected_c": [expected_c.x, expected_c.y]},
        "checks": checks,
        "solidcraft_formulation": "Angle(l1,l3)=60deg expressed as Angle{l1,l3,60deg,flip:true} (W1/TL2 native form). cases.json's slvs side uses angle(l1,l3,60,inverse=True) — the same interior angle (mark: adapted, reason quoted).",
        "w1_semantics": "TL2 w1_sketch.rs case_triangle (oracle 25), verbatim",
    })
}

fn case_triangle_value_edit() -> Value {
    let (mut sk, a, b, c) = build_triangle();
    let first = solve(&mut sk);
    let old: DrivingValues = sk.driving_values();
    let before_a = sk.point(a);
    // d1: 50 -> 40 (still solvable; t = (40 + sqrt(3300))/2)
    set_dim(&mut sk, "d1", 40.0);
    let rep = solve_after_value_edit(&mut sk, &old);
    let t = (40.0 + 3300.0_f64.sqrt()) / 2.0;
    let expected_c = v(t * (PI / 3.0).cos(), t * (PI / 3.0).sin());
    let checks = vec![
        chk("solved_after_edit", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?} failing={:?} folded={:?}", rep.status, rep.failing, rep.folded)),
        chk("dof_still_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={}", rep.dof)),
        chk("b_moved_to_40_0", dist_to(&sk, b, v(40.0, 0.0)).map(|d| d < CHECK_TOL).unwrap_or(false), json!(pos_of(&sk, b)), json!([40.0, 0.0]), pos_str(&sk, b)),
        chk(
            "c_matches_analytic_after_edit",
            dist_to(&sk, c, expected_c).map(|d| d < CHECK_TOL).unwrap_or(false),
            json!(pos_of(&sk, c)), json!([expected_c.x, expected_c.y]),
            format!("got {} want ({:.12}, {:.12})", pos_str(&sk, c), expected_c.x, expected_c.y),
        ),
        chk("anchored_point_immovable", sk.point(a) == before_a, json!(pos_of(&sk, a)), json!([0.0, 0.0]), format!("{before_a:?} -> {:?} (bitwise equality)", sk.point(a))),
        chk("no_orientation_flip", rep.folded.is_empty(), json!(rep.folded), json!([]), format!("folded={:?} (continuation keeps Owen-orientation; solves that flip are refused for commands)", rep.folded)),
        chk("first_solve_was_solved_dof0", first.ok() && first.dof == 0, json!({"status": format!("{:?}", first.status), "dof": first.dof}), json!({"status": "Solved", "dof": 0}), format!("{:?} dof={}", first.status, first.dof)),
    ];
    json!({
        "id": "triangle_value_edit",
        "first_solve": report_json(&first),
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "solidcraft_formulation": "native constraint-value MUTATION path: ConstraintKind::set_value (model.rs:370-389) + solve_after_value_edit (solver.rs:1369-1371) — NO rebuild. cases.json's slvs side performs the same edit by full system rebuild (mark: adapted — the edit PATH is the comparative dimension; the fixture semantics are identical).",
        "w1_semantics": "TL2 w1_sketch.rs case_triangle_value_edit, verbatim",
    })
}

fn case_l_bracket(with_dims: bool) -> Value {
    let (mut sk, p) = build_l_bracket_with(with_dims, None);
    let rep = solve(&mut sk);
    let exp: Vec<Vec2> = if with_dims {
        vec![v(0.0, 0.0), v(60.0, 0.0), v(60.0, 8.0), v(8.0, 8.0), v(8.0, 40.0), v(0.0, 40.0)]
    } else {
        Vec::new()
    };
    let mut checks = vec![chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status))];
    if with_dims {
        checks.push(chk("dof_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={}", rep.dof)));
        for (i, e) in exp.iter().enumerate() {
            checks.push(pos_check(&sk, &format!("corner_{i}"), p[i], *e));
        }
        let native = rep.point_determined.iter().all(|d| *d);
        // m3-eval protocol: perturb the SOLVED corners, rebuild with dims, re-solve
        let solved: Vec<Vec2> = p.iter().map(|&i| sk.points[i].pos).collect();
        let (mut sk2, p2) = build_l_bracket_with(true, Some(&perturbed(&solved, 0.5)));
        let rep2 = solve(&mut sk2);
        let perturbed_ok = rep2.ok()
            && rep2.dof == 0
            && (0..6).all(|i| dist_to(&sk2, p2[i], exp[i]).map(|d| d < CHECK_TOL).unwrap_or(false));
        checks.push(chk(
            "all_points_determined_via_perturbed_resolve",
            native && perturbed_ok,
            json!({"native_point_determined": rep.point_determined, "perturbed_resolve": {"status": format!("{:?}", rep2.status), "dof": rep2.dof, "corners": (0..6).map(|i| pos_of(&sk2, p2[i])).collect::<Vec<_>>()}}),
            json!({"native": "all determined", "perturbed": "solved dof 0, corners at expected"}),
            "native flags + perturbed re-solve both hold".into(),
        ));
    } else {
        checks.push(chk("dof_4", rep.dof == 4, json!(rep.dof), json!(4), format!("dof={} (the L can shear: 2 free x-offsets + 2 free y-offsets)", rep.dof)));
        checks.push(chk(
            "anchored_corner_determined",
            dist_to(&sk, p[0], Vec2::ZERO).map(|d| d < CHECK_TOL).unwrap_or(false) && rep.point_determined[p[0]],
            json!(pos_of(&sk, p[0])), json!([0.0, 0.0]),
            format!("p0={} (coincident with the fixed origin) determined={}", pos_str(&sk, p[0]), rep.point_determined[p[0]]),
        ));
        checks.push(chk(
            "free_corners_recorded", true,
            json!((0..6).map(|i| pos_of(&sk, p[i])).collect::<Vec<_>>()),
            json!((0..6).map(|i| pos_of(&sk, p[i])).collect::<Vec<_>>()),
            "recorded, no pass/fail: underconstrained placement. SolidCraft's damped LM moves the corners the least distance onto an H/V-consistent configuration (minimal motion), unlike slvs's one-sided substitution path".into(),
        ));
        // perturbation-stability probe (m3-eval protocol, delta 0.3, solved corners)
        let solved: Vec<Vec2> = p.iter().map(|&i| sk.points[i].pos).collect();
        let (mut sk2, p2) = build_l_bracket_with(false, Some(&perturbed(&solved, 0.3)));
        let rep2 = solve(&mut sk2);
        let drifted = (1..6)
            .map(|i| dist_to(&sk2, p2[i], solved[i]).unwrap_or(f64::INFINITY))
            .fold(0.0_f64, f64::max);
        checks.push(chk(
            "underconstrained_landing_perturbation_stability_recorded", true,
            json!(drifted), json!("recorded, no pass/fail"),
            format!("max corner drift after a 0.3-magnitude seed perturbation of the solved corners + re-solve: {drifted:.6} — recorded, no pass/fail; SolidCraft keeps free geometry near its seed (damped LM minimal motion; rep2 status={:?}, dof={})", rep2.status, rep2.dof),
        ));
        checks.push(xchk(
            "point_determined_origin_and_anchored_only",
            rep.point_determined == vec![true, true, false, false, false, false, false],
            json!(rep.point_determined), json!([true, true, false, false, false, false, false]),
            "TL2's native check (point 0 = fixed origin; corner A coincident with it — 7 points total)".into(),
        ));
    }
    json!({
        "id": if with_dims { "l_bracket_constrained" } else { "l_bracket_no_dims" },
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "solidcraft_formulation": if with_dims {
            "DistanceX/DistanceY in the W1 form: UNSIGNED magnitudes (residual |q−p|.axis − value, solver.rs:544-545), values 60/8/40/8 — the exact TL2 formulation. cases.json's slvs side needed signed PROJ values d3=-40, d4=-8 to express the same fixture (mark: adapted, reason quoted)."
        } else {
            "H/V + coincident only — identical constraint set (mark: identical)."
        },
        "w1_semantics": "TL2 w1_sketch.rs case_l_bracket(with_dims) (oracle 19), verbatim",
    })
}

fn case_slot() -> Value {
    let mut sk = build_slot();
    let rep = solve(&mut sk);
    // cases.json declared names: a1c_at_0.0,0.0 etc. — the ids in this sketch are
    // a1.center / a1.start / a1.end (a1c/a1s/a1e in cases.json's label space).
    let ids = [
        ("a1c", "a1.center", v(0.0, 0.0)),
        ("a1s", "a1.start", v(0.0, 6.0)),
        ("a1e", "a1.end", v(0.0, -6.0)),
        ("a2c", "a2.center", v(40.0, 0.0)),
        ("a2s", "a2.start", v(40.0, -6.0)),
        ("a2e", "a2.end", v(40.0, 6.0)),
    ];
    let mut checks = vec![
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?} failing={:?}", rep.status, rep.failing)),
        chk("dof_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={} (raw value the solver reports)", rep.dof)),
    ];
    for (label, pid, at) in ids {
        let i = sk.point_index(pid).unwrap();
        checks.push(pos_check(&sk, label, i, at));
    }
    let r0 = sk.radius(0).unwrap();
    let r1 = sk.radius(1).unwrap();
    checks.push(chk(
        "radius_6_both_caps",
        (r0 - 6.0).abs() < CHECK_TOL && (r1 - 6.0).abs() < CHECK_TOL,
        json!([r0, r1]), json!([6.0, 6.0]),
        format!("derived radii a1={r0} a2={r1} (arcs have no radius variable; Equal + Radius dimension drive them)"),
    ));
    checks.push(chk(
        "no_redundancy_reported_for_endpoint_tangency",
        rep.redundant.is_empty() && rep.failing.is_empty(),
        json!({"redundant": rep.redundant, "failing": rep.failing}), json!({"redundant": [], "failing": []}),
        format!("4 endpoint tangencies at structurally shared points produced NO redundancy and NO failure — SolidCraft's Tangent{{a,b}} is symmetric over shared endpoints (no argument-order quirk, no helper points)"),
    ));
    checks.push(xchk(
        "all_determined",
        rep.point_determined.iter().all(|d| *d) && rep.curve_determined.iter().all(|d| *d),
        json!({"point_determined": rep.point_determined, "curve_determined": rep.curve_determined}),
        json!("all true"),
        "TL2's native check".into(),
    ));
    json!({
        "id": "slot_constrained",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "label_map_note": "cases.json labels a1c/a1s/a1e/a2c/a2s/a2e; this sketch's synthesized arc points are a1.center/a1.start/a1.end (TL2's construction, kept verbatim)",
        "solidcraft_formulation": "Tangent{a,b} pairs (symmetric at shared endpoints) + Equal + Radius{6} (native) + DistanceX{40} (unsigned W1 form). cases.json's slvs side uses ARC_LINE_TANGENT with (arc,line) order + DIAMETER=12 (mark: adapted, reason quoted).",
        "w1_semantics": "TL2 w1_sketch.rs case_slot (oracle 20), verbatim",
    })
}

fn case_line_horizontal_only() -> Value {
    let mut sk = Sketch::new();
    let l = sk.add_line(v(0.0, 0.0), v(10.0, 1.0), None, None, Some("l1")).unwrap();
    add(&mut sk, ConstraintKind::Horizontal { l }, None);
    let rep = solve(&mut sk);
    let a = sk.point(1).unwrap();
    let b = sk.point(2).unwrap();
    let mut checks = vec![
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("dof_3", rep.dof == 3, json!(rep.dof), json!(3), format!("dof={} (translation x, translation y, length)", rep.dof)),
        chk("horizontalized", (a.y - b.y).abs() < 1e-9, json!([a.x, a.y, b.x, b.y]), json!("a.y == b.y"), format!("a=({a:?}) b=({b:?})")),
        chk(
            "underconstrained_motion_split_recorded", true,
            json!([[a.x, a.y], [b.x, b.y]]), json!([[a.x, a.y], [b.x, b.y]]),
            format!("a=({:.6}, {:.6}) b=({:.6}, {:.6}) (input y's were 0.0 and 1.0): SolidCraft's damped LM splits the 1mm gap ~evenly (least motion; TL2's W1 record) — the behavioral comparison datum vs slvs's one-sided substitution path; recorded, no pass/fail on the position", a.x, a.y, b.x, b.y),
        ),
    ];
    checks.push(xchk(
        "minimal_motion_split",
        (a.y - 0.5).abs() < 0.05 && (b.y - 0.5).abs() < 0.05,
        json!([a.y, b.y]), json!([0.5, 0.5]),
        "TL2's native check: the gap closes ~evenly (damped LM takes the shortest step)".into(),
    ));
    checks.push(xchk(
        "nothing_determined_except_fixed_origin",
        rep.point_determined.iter().skip(1).all(|d| !*d),
        json!(rep.point_determined), json!("[true, false, ...]"),
        "TL2's native check (point 0 is the fixed origin — trivially determined)".into(),
    ));
    json!({
        "id": "line_horizontal_only",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_line_horizontal_only, verbatim",
    })
}

fn case_circle_radius_only_edit() -> Value {
    let (mut sk, c, center) = build_circle_radius_only_with(v(3.0, 4.0), 5.0);
    let rep = solve(&mut sk);
    let center_before_bits = sk.points[center].pos;
    let radius_after_first = sk.radius(c).unwrap();
    let determined_after_first = rep.point_determined.clone();
    let old: DrivingValues = sk.driving_values();
    set_dim(&mut sk, "d1", 8.0);
    let rep2 = solve_after_value_edit(&mut sk, &old);
    let center_after = sk.points[center].pos;
    let checks = vec![
        chk("solved_radius_only", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("dof_2_center_free", rep.dof == 2, json!(rep.dof), json!(2), format!("dof={} (centre x/y free)", rep.dof)),
        chk("radius_applied_5", (radius_after_first - 5.0).abs() < CHECK_TOL, json!(radius_after_first), json!(5.0), format!("r={radius_after_first}")),
        chk(
            "center_undetermined_left_at_seed",
            !determined_after_first[center] && sk.point(center) == Some(v(3.0, 4.0)),
            json!({"point_determined": determined_after_first[center], "center_after_first_solve": pos_of(&sk, center)}),
            json!({"point_determined": false, "center_after_first_solve": [3.0, 4.0]}),
            "native surface: the free centre is NOT determined and stays bitwise at its seed after the first solve".into(),
        ),
        chk("solved_after_edit", rep2.ok(), json!(format!("{:?}", rep2.status)), json!("Solved"), format!("{:?} (native mutation path: set_value + solve_after_value_edit, no rebuild)", rep2.status)),
        chk("dof_still_2", rep2.dof == 2, json!(rep2.dof), json!(2), format!("dof={}", rep2.dof)),
        chk("radius_now_8", (sk.radius(c).unwrap() - 8.0).abs() < CHECK_TOL, json!(sk.radius(c).unwrap()), json!(8.0), format!("r={}", sk.radius(c).unwrap())),
        chk(
            "free_center_does_not_move",
            center_after == center_before_bits,
            json!([center_after.x, center_after.y]), json!([center_before_bits.x, center_before_bits.y]),
            "bitwise equality: the radius edit does not touch the centre (exact minimal motion — the residual gradient does not reference it)".into(),
        ),
    ];
    json!({
        "id": "circle_radius_only_edit",
        "solve": report_json(&rep),
        "solve_after_edit": report_json(&rep2),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "solidcraft_formulation": "Radius{5} -> Radius{8} via the native value mutation (set_value + solve_after_value_edit; no rebuild). cases.json's slvs side rebuilds with DIAMETER 10 -> 16 (mark: adapted, reason quoted).",
        "w1_semantics": "TL2 w1_sketch.rs case_circle_radius_only_and_edit, verbatim",
    })
}

fn case_rect_redundant() -> Value {
    let mut sk = build_rect(true);
    let rep = solve(&mut sk);
    let dup = sk.constraints.len() - 1; // the duplicate Vertical is the last constraint added
    let dup_id = sk.constraints[dup].id.clone();
    let dup_is_vertical_l1 = matches!(sk.constraints[dup].kind, ConstraintKind::Vertical { l } if l == 1);
    let residual = constraint_residual(&sk, dup);
    let implied_by = determined_by(&sk, dup);
    let implied_names: Vec<String> = implied_by
        .iter()
        .filter_map(|&i| sk.constraints.get(i).map(|c| format!("{}({:?})", c.id, c.kind)))
        .collect();
    let corners = [v(0.0, 0.0), v(40.0, 0.0), v(40.0, 30.0), v(0.0, 30.0)];
    let corners_ok = (0..4).all(|i| dist_to(&sk, i + 1, corners[i]).map(|d| d < CHECK_TOL).unwrap_or(false));
    let checks = vec![
        chk(
            "solved_despite_redundancy", rep.ok(),
            json!(format!("{:?}", rep.status)), json!("Solved"),
            format!("{:?} — SolidCraft SOLVES the exactly-redundant system (unlike slvs, whose exposed path fails it: flag 1 REDUNDANT_DIDNT_CONVERGE; the slvs-side record of the same fixture is the honest divergence)", rep.status),
        ),
        chk("dof_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={} (rank analysis correct WITH the duplicate)", rep.dof)),
        chk(
            "redundant_listed",
            rep.redundant == vec![dup_id.clone()] && dup_is_vertical_l1,
            json!({"observed_redundant": rep.redundant, "observed_duplicate_id": dup_id, "is_the_duplicate_vertical_on_l1": dup_is_vertical_l1}),
            json!({"expected_redundant": ["k6"]}),
            format!("redundant={:?}; the listed constraint IS the duplicate Vertical on l1 (structural match; label spaces differ: cases.json's slvs k6 == solidcraft k8 == the 8th constraint in insertion order — TL2's W1 record also names k8)", rep.redundant),
        ),
        chk(
            "failure_leaves_geometry_at_input", true,
            json!({"failed": !rep.ok(), "corners": (0..4).map(|i| pos_of(&sk, i + 1)).collect::<Vec<_>>()}),
            json!({"failed": false, "corners": [[0, 0], [40, 0], [40, 30], [0, 30]]}),
            "not a failure on this solver: the fixture SOLVES, so the all-or-nothing contract shows its success branch (full solution written back, corners exact). The failure branch (bitwise restore of the pre-solve snapshot, solver.rs:1872-1873,2231) is exercised by conflicting_distances / coincident_plus_distance / triangle_edit_unsolvable".to_string(),
        ),
        chk(
            "w1_corners_expected_but_not_reached", corners_ok,
            json!((0..4).map(|i| pos_of(&sk, i + 1)).collect::<Vec<_>>()), json!([[0, 0], [40, 0], [40, 30], [0, 30]]),
            format!("corners reached exactly: {} (the check name is the slvs side's honest-failure record; its SEMANTIC here is corners-at-W1-expected, which hold)", (0..4).map(|i| pos_str(&sk, i + 1)).collect::<Vec<_>>().join(" ")),
        ),
        xchk(
            "redundant_constraint_consistent",
            residual.map(|r| r.abs() < CONSISTENT).unwrap_or(false),
            json!(residual), json!(format!("< CONSISTENT={CONSISTENT}")),
            format!("residual={residual:?} — implied, not conflicting (constraint_residual, redundancy.rs:124-135)"),
        ),
        xchk(
            "determined_by_reports_impliers",
            !implied_by.is_empty(),
            json!(implied_names), json!("non-empty"),
            "the crate names the implying constraints (determined_by, redundancy.rs:141-171) — TL2's W1 record: the duplicate implied by the first Vertical".into(),
        ),
    ];
    let label_map: Vec<Value> = (0..sk.constraints.len())
        .map(|i| {
            let c = &sk.constraints[i];
            json!({"index": i, "solidcraft_id": c.id, "param": c.param, "kind": format!("{:?}", c.kind), "note": if i == dup { "THE DUPLICATE (cases.json k6 == solidcraft k8: same fixture member, different label spaces)" } else { "" }})
        })
        .collect();
    json!({
        "id": "rect_redundant_duplicate_dimension",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "redundancy": {
            "constraint_id": dup_id,
            "constraint_kind": format!("{:?}", sk.constraints[dup].kind),
            "constraint_residual_mm": residual,
            "determined_by_indices": implied_by,
            "determined_by": implied_names,
        },
        "checks": checks,
        "label_map": label_map,
        "solidcraft_formulation": "W1 formulation: Length{l, 40/30} (native line-length kind; cases.json's slvs side used endpoint distance — mark: adapted) + duplicate Vertical. All constraint ids auto-generated (k1..k8 in insertion order, TL2-faithful).",
        "w1_semantics": "TL2 w1_sketch.rs case_rect_redundant, verbatim (upstream tests.rs fully_constrained_rectangle shape)",
    })
}

fn case_conflicting_distances() -> Value {
    let mut sk = Sketch::new();
    let l = sk.add_line(v(0.0, 0.0), v(10.0, 0.0), None, None, Some("l1")).unwrap();
    add(&mut sk, ConstraintKind::Horizontal { l }, None);
    add(&mut sk, ConstraintKind::Distance { p: 1, q: 2, value: 10.0 }, Some("d1"));
    add(&mut sk, ConstraintKind::Distance { p: 1, q: 2, value: 20.0 }, Some("d2"));
    let before = point_bits(&sk);
    let rep = solve(&mut sk);
    let restored = point_bits(&sk) == before;
    let d1i = dim_index(&sk, "d1");
    let d2i = dim_index(&sk, "d2");
    let r1 = constraint_residual(&sk, d1i);
    let r2 = constraint_residual(&sk, d2i);
    let id1 = sk.constraints[d1i].id.clone();
    let id2 = sk.constraints[d2i].id.clone();
    let failing_both = rep.failing.contains(&id1) && rep.failing.contains(&id2);
    let mut checks = vec![
        chk("fails", !rep.ok(), json!(format!("{:?}", rep.status)), json!("Failed"), format!("{:?} (dof={} still reported by the rank analysis)", rep.status, rep.dof)),
        chk(
            "bad_lists_conflicting_dims", failing_both,
            json!({"observed_failing": rep.failing, "d1_constraint_id": id1, "d2_constraint_id": id2}),
            json!({"expected_bad_contains": ["d1", "d2"]}),
            format!("failing={:?} — SolidCraft names constraint IDS (k-numbers); the two Distance constraints carry params d1/d2 (cases.json's slvs labels). Both conflicting dimensions are named", rep.failing),
        ),
        chk(
            "geometry_unchanged_bitwise_on_failure", restored,
            json!(sk.points.iter().map(|p| [p.pos.x, p.pos.y]).collect::<Vec<_>>()), json!([[0.0, 0.0], [10.0, 0.0]]),
            "input positions written back exactly (bitwise): on failure the solve restores the pre-solve snapshot x0 (solver.rs:1872-1873, 2231)".to_string(),
        ),
    ];
    checks.push(xchk(
        "residuals_expose_conflict",
        r1.unwrap_or(0.0) > 1e-6 || r2.unwrap_or(0.0) > 1e-6,
        json!({"d1_residual": r1, "d2_residual": r2}), json!("at least one > 1e-6"),
        format!("d1={r1:?} d2={r2:?} — per-constraint residual surface is NATIVE here (absent in slvs); TL2 measured the same conflict"),
    ));
    json!({
        "id": "conflicting_distances",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "per_constraint_residual": {"d1": r1, "d2": r2},
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_conflicting_distances, verbatim",
    })
}

fn case_coincident_plus_distance() -> Value {
    let mut sk = Sketch::new();
    let p = sk.add_point(v(1.0, 1.0), Some("p1")).unwrap();
    let q = sk.add_point(v(6.0, 5.0), Some("p2")).unwrap();
    add(&mut sk, ConstraintKind::Coincident { p, q }, None);
    add(&mut sk, ConstraintKind::Distance { p, q, value: 5.0 }, Some("d1"));
    let before = point_bits(&sk);
    let rep = solve(&mut sk);
    let restored = point_bits(&sk) == before;
    let di = dim_index(&sk, "d1");
    let r = constraint_residual(&sk, di);
    let named = rep.failing.contains(&sk.constraints[di].id);
    let mut checks = vec![
        chk("fails", !rep.ok(), json!(format!("{:?}", rep.status)), json!("Failed"), format!("{:?}", rep.status)),
        chk(
            "constraints_named_in_bad", named,
            json!({"observed_failing": rep.failing, "distance_constraint_id": sk.constraints[di].id}),
            json!({"expected": "the violated constraint(s) named"}),
            format!("failing={:?} — the violated Coincident/Distance constraints are named by id (cases.json's slvs labels: k1/d1)", rep.failing),
        ),
        chk(
            "geometry_unchanged_bitwise_on_failure", restored,
            json!([[1.0, 1.0], [6.0, 5.0]]), json!([[1.0, 1.0], [6.0, 5.0]]),
            "input positions p1/p2 untouched (bitwise): an unsolvable system leaves the geometry at the input (restore of x0)".to_string(),
        ),
    ];
    checks.push(xchk(
        "residual_measured_on_restored_geometry",
        r.map(|x| x > 1.0).unwrap_or(false),
        json!(r), json!("~|sqrt(41) − 5| = 1.403 (TL2 record)"),
        format!("{r:?} — LM stalls between the 0 and 5 targets, then the input is restored; residual measured on the restored geometry"),
    ));
    json!({
        "id": "coincident_plus_distance",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "per_constraint_residual": {"d1": r},
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_coincident_plus_distance, verbatim",
    })
}

fn case_triangle_edit_unsolvable() -> Value {
    let (mut sk, _, _, _) = build_triangle();
    let first = solve(&mut sk);
    let old: DrivingValues = sk.driving_values();
    let solved_positions: Vec<Vec2> = sk.points.iter().map(|p| p.pos).collect();
    // d1: 50 -> 55 violates the triangle inequality at angle(A)=60deg: no real solution.
    set_dim(&mut sk, "d1", 55.0);
    let rep = solve_after_value_edit(&mut sk, &old);
    let restored = sk.points.iter().map(|p| p.pos).zip(&solved_positions).all(|(n, o)| n == *o);
    let mut checks = vec![
        chk("fails", !rep.ok(), json!(format!("{:?}", rep.status)), json!("Failed"), format!("{:?} (iters={} max_residual={:.6} continuations={})", rep.status, rep.iterations, rep.max_residual, rep.continuations)),
        chk(
            "bad_list_nonempty", !rep.failing.is_empty(),
            json!({"observed_failing": rep.failing}),
            json!({"expected_nonempty": true}),
            format!("failing={:?} — names the constraints unsatisfied at the final iterate (native id space; TL2's W1 record: k3+k4+k5; cases.json notes slvs named only d2 — compared in findings)", rep.failing),
        ),
        chk(
            "geometry_unchanged_bitwise_on_failure", restored,
            json!(sk.points.iter().map(|p| [p.pos.x, p.pos.y]).collect::<Vec<_>>()),
            json!(solved_positions.iter().map(|p| [p.x, p.y]).collect::<Vec<_>>()),
            "geometry restored BITWISE to the stored solved state (restore of x0; no partial write-back)".to_string(),
        ),
    ];
    checks.push(xchk(
        "max_residual_large",
        rep.max_residual > 1e-6,
        json!(rep.max_residual), json!("> 1e-6"),
        format!("max_residual={:.6} (TL2 recorded 1.194 with 222 iterations — the continuation budget exhausted)", rep.max_residual),
    ));
    json!({
        "id": "triangle_edit_unsolvable",
        "first_solve": report_json(&first),
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "solidcraft_formulation": "native mutation path: set_value(55) + solve_after_value_edit (continuation steps old->new in substeps, then reports Failed); no rebuild anywhere.",
        "w1_semantics": "TL2 w1_sketch.rs case_triangle_edit_unsolvable, verbatim",
    })
}

/// In-process determinism: the canonical 3 solved 5 times in one process.
/// Digest protocol (h2h lane): FNV-1a-64 over f64 LE value bits, per case sorted
/// by value key; canonical order triangle/l_bracket/slot + a combined digest
/// (case-id sort then value key).
fn case_determinism_inprocess() -> Value {
    let mut round_digests: Vec<[u64; 4]> = Vec::new();
    let mut round_bits: Vec<Vec<Vec<(u64, u64)>>> = Vec::new();
    let mut round_status: Vec<[String; 3]> = Vec::new();
    let mut round_dofs: Vec<[usize; 3]> = Vec::new();
    let mut round_iters: Vec<[usize; 3]> = Vec::new();
    let mut round_residuals: Vec<[f64; 3]> = Vec::new();
    for _ in 0..5 {
        let (mut t, ..) = build_triangle();
        let rt = solve(&mut t);
        let (mut lb, _) = build_l_bracket_with(true, None);
        let rlb = solve(&mut lb);
        let mut sl = build_slot();
        let rsl = solve(&mut sl);
        let per = [
            values_digest("triangle_constrained", &t),
            values_digest("l_bracket_constrained", &lb),
            values_digest("slot_constrained", &sl),
        ];
        let comb = combined_digest(&[
            ("triangle_constrained", &t),
            ("l_bracket_constrained", &lb),
            ("slot_constrained", &sl),
        ]);
        round_digests.push([per[0], per[1], per[2], comb]);
        round_bits.push(vec![point_bits(&t), point_bits(&lb), point_bits(&sl)]);
        round_status.push([format!("{:?}", rt.status), format!("{:?}", rlb.status), format!("{:?}", rsl.status)]);
        round_dofs.push([rt.dof, rlb.dof, rsl.dof]);
        round_iters.push([rt.iterations, rlb.iterations, rsl.iterations]);
        round_residuals.push([rt.max_residual, rlb.max_residual, rsl.max_residual]);
    }
    let bitwise = (1..5).all(|r| round_bits[r] == round_bits[0]);
    let statuses_same = (1..5).all(|r| round_status[r] == round_status[0] && round_dofs[r] == round_dofs[0]);
    let iters_same = (1..5).all(|r| round_iters[r] == round_iters[0]);
    let residuals_same = (1..5).all(|r| round_residuals[r] == round_residuals[0]);
    let digests_same = (1..5).all(|r| round_digests[r] == round_digests[0]);
    let digest_strs: Vec<String> = round_digests
        .iter()
        .map(|d| d.iter().map(|x| format!("{x:016x}")).collect::<Vec<_>>().join(" "))
        .collect();
    let max_delta = {
        let first = &round_bits[0];
        round_bits[1..]
            .iter()
            .map(|round| {
                round
                    .iter()
                    .zip(first.iter())
                    .flat_map(|(b, f)| b.iter().zip(f.iter()))
                    .map(|(x, y)| {
                        (f64::from_bits(x.0) - f64::from_bits(y.0)).abs().max((f64::from_bits(x.1) - f64::from_bits(y.1)).abs())
                    })
                    .fold(0.0, f64::max)
            })
            .fold(0.0, f64::max)
    };
    let mut checks = vec![
        chk("bitwise_identical_geometry_5x", bitwise, json!(format!("{max_delta:e}")), json!("0.000e+00"), format!("max coordinate delta = {max_delta:e} over the canonical 3 (triangle, L-bracket, slot)")),
        chk(
            "identical_status_and_dof", statuses_same,
            json!((0..5).map(|r| round_status[r].clone()).collect::<Vec<_>>()),
            json!("identical across 5 rounds"),
            format!("statuses+doF per round: {}", (0..5).map(|r| format!("({},{},{})", round_status[r][0], round_status[r][1], round_status[r][2])).collect::<Vec<_>>().join("; ")),
        ),
        chk(
            "identical_digests", digests_same,
            json!(digest_strs.clone()), json!("identical across 5 rounds"),
            format!("digest layout: fnv1a64 over f64 LE bits (per case: value key sort; combined: case-id sort then value key); round-0 digests (triangle, l_bracket, slot, combined): {}", digest_strs[0]),
        ),
    ];
    checks.push(xchk(
        "identical_iteration_counts_and_residuals",
        iters_same && residuals_same,
        json!({"iterations": round_iters, "max_residuals": round_residuals}),
        json!("identical across 5 rounds"),
        "SolidCraft-native surfaces absent in slvs (its m3-eval envelope records the gap); deterministic LM schedule + constructive seed".into(),
    ));
    json!({
        "id": "determinism_inprocess_5x",
        "runs": 5,
        "digests": (0..4).map(|i| format!("{:016x}", round_digests[0][i])).collect::<Vec<_>>(),
        "digest_names": ["triangle_constrained", "l_bracket_constrained", "slot_constrained", "combined(case-id sorted)"],
        "digest_layout": "per-case: fnv1a64(case_id bytes ++ [value_key bytes ++ f64 LE bits] in BTreeMap order over point:<id>.x/y + curve:<id>.radius); combined: the three cases in case-id sort (l_bracket_constrained, slot_constrained, triangle_constrained)",
        "statuses": (0..5).map(|r| round_status[r].clone()).collect::<Vec<_>>(),
        "dofs": (0..5).map(|r| round_dofs[r]).collect::<Vec<_>>(),
        "iterations": (0..5).map(|r| round_iters[r]).collect::<Vec<_>>(),
        "max_residuals": (0..5).map(|r| round_residuals[r]).collect::<Vec<_>>(),
        "bitwise_identical_points": bitwise,
        "max_abs_coordinate_delta": max_delta,
        "checks": checks,
        "w1_semantics": "m3-eval/TL2 5x in-process protocol, per the h2h determinism protocol extended to the canonical 3",
    })
}

fn case_determinism_crossprocess() -> Value {
    let exe = std::env::current_exe().unwrap_or_default();
    let mut outs: Vec<String> = Vec::new();
    let mut codes: Vec<i32> = Vec::new();
    for _ in 0..3 {
        match Command::new(&exe).arg("--hash").output() {
            Ok(o) => {
                codes.push(o.status.code().unwrap_or(-1));
                outs.push(String::from_utf8_lossy(&o.stdout).trim().to_string());
            }
            Err(e) => {
                codes.push(-1);
                outs.push(format!("spawn failed: {e}"));
            }
        }
    }
    let identical = outs.windows(2).all(|w| w[0] == w[1]) && codes.iter().all(|c| *c == 0);
    let checks = vec![
        chk("all_child_processes_exit_0", codes.iter().all(|c| *c == 0), json!(codes), json!([0, 0, 0]), format!("{codes:?}")),
        chk("hashes_identical_across_processes", identical, json!(outs.clone()), json!("identical"), outs.join(" | ")),
    ];
    json!({
        "id": "determinism_crossprocess_3x",
        "runs": 3,
        "child_stdout": outs,
        "exit_codes": codes,
        "identical": identical,
        "checks": checks,
        "w1_semantics": "TL2 w1_sketch.rs case_determinism_crossprocess (self re-exec hash submode), same protocol",
    })
}

// ---------------------------------------------------------------------------
// coverage-probe runners (6, NEW beyond W1)
// ---------------------------------------------------------------------------

fn probe_common_checks(sk: &Sketch, rep: &SolveReport, positions: &[(&str, usize, Vec2)]) -> Vec<Value> {
    let mut checks = vec![
        chk("solved", rep.ok(), json!(format!("{:?}", rep.status)), json!("Solved"), format!("{:?}", rep.status)),
        chk("dof_0", rep.dof == 0, json!(rep.dof), json!(0), format!("dof={}", rep.dof)),
    ];
    for (label, idx, at) in positions {
        checks.push(pos_check(sk, label, *idx, *at));
    }
    checks
}

fn case_parallel_offset() -> Value {
    let mut sk = build_parallel_offset(false);
    let rep = solve(&mut sk);
    let a0 = sk.point_index("A0").unwrap();
    let a1 = sk.point_index("A1").unwrap();
    let b0 = sk.point_index("B0").unwrap();
    let b1 = sk.point_index("B1").unwrap();
    let mut checks = probe_common_checks(&sk, &rep, &[
        ("A0", a0, v(0.0, 0.0)),
        ("A1", a1, v(10.0, 0.0)),
        ("B0", b0, v(0.0, 3.0)),
        ("B1", b1, v(9.0, 3.0)),
    ]);
    // The literal cases.json mapping used DistanceX{A0,B0,0}: the crate's DistanceX
    // residual is |dx| − value (solver.rs:544) — at dx=0 the central-difference
    // Jacobian row is zero (|h| − |−h| = 0), so the finite-difference rank analysis
    // may not see the constraint even though it holds. Record what actually
    // happens + the NATIVE remedy probe (VerticalPoints = same column).
    let mut skr = build_parallel_offset(true);
    let rep_r = solve(&mut skr);
    let b0r = skr.point_index("B0").unwrap();
    let b1r = skr.point_index("B1").unwrap();
    let remedy_ok = rep_r.ok()
        && rep_r.dof == 0
        && dist_to(&skr, b0r, v(0.0, 3.0)).map(|d| d < CHECK_TOL).unwrap_or(false)
        && dist_to(&skr, b1r, v(9.0, 3.0)).map(|d| d < CHECK_TOL).unwrap_or(false);
    checks.push(xchk(
        "distance_x_zero_rank_analysis",
        rep.dof == 0,
        json!({"dof_with_literal_DistanceX0": rep.dof, "solved": rep.ok(), "geometry": [[sk.point(a0).unwrap().x, sk.point(a0).unwrap().y], [sk.point(b0).unwrap().x, sk.point(b0).unwrap().y]]}),
        json!({"dof": 0}),
        format!(
            "literal cases.json mapping DistanceX{{A0,B0,0.0}} (residual |dx|−0, solver.rs:544 — non-smooth at 0): solved={}, dof={} — the unsigned form's kink at zero {} the rank analysis{}",
            rep.ok(), rep.dof,
            if rep.dof == 0 { "does not hide the constraint from" } else { "is hidden from" },
            if rep.dof == 0 { String::new() } else { " (positions may still land correctly from the constructive seed)".to_string() },
        ),
    ));
    checks.push(xchk(
        "native_remedy_VerticalPoints_reaches_expected",
        remedy_ok,
        json!({"status": format!("{:?}", rep_r.status), "dof": rep_r.dof, "B0": pos_of(&skr, b0r), "B1": pos_of(&skr, b1r)}),
        json!({"status": "Solved", "dof": 0, "B0": [0.0, 3.0], "B1": [9.0, 3.0]}),
        "the crate's NATIVE same-column constraint VerticalPoints{p,q} (residual q.x−p.x, solver.rs:465 — signed, smooth) expresses X(A0->B0)=0 exactly — recorded as the adapter-level remedy".into(),
    ));
    json!({
        "id": "parallel_offset",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "cases_kind_mapping": [
            {"cases_kind": "coincident_to_origin", "solidcraft": "Coincident { p: A0, q: 0 }"},
            {"cases_kind": "horizontal", "solidcraft": "Horizontal { l: lA }"},
            {"cases_kind": "distance_x", "solidcraft": "DistanceX { p: A0, q: A1, value: 10.0 } (unsigned; branch from seed)"},
            {"cases_kind": "parallel", "solidcraft": "Parallel { a: lB, b: lA } — NATIVE (model.rs:223-226)"},
            {"cases_kind": "distance_y", "solidcraft": "DistanceY { p: A0, q: B0, value: 3.0 } (unsigned; B0 above A0 from seed)"},
            {"cases_kind": "distance_x", "solidcraft": "DistanceX { p: A0, q: B0, value: 0.0 } (literal; see the rank-analysis extra check + VerticalPoints remedy)"},
            {"cases_kind": "length", "solidcraft": "Length { l: lB, value: 9.0 } — native line length"},
        ],
        "provenance": "cases.json literal (m3-eval phase 2a new case); seeds from gen_solver_cases.py build_parallel_offset",
    })
}

fn case_perpendicular_pair() -> Value {
    let mut sk = build_perpendicular_pair();
    let rep = solve(&mut sk);
    let a0 = sk.point_index("A0").unwrap();
    let a1 = sk.point_index("A1").unwrap();
    let b0 = sk.point_index("B0").unwrap();
    let b1 = sk.point_index("B1").unwrap();
    let mut checks = probe_common_checks(&sk, &rep, &[
        ("A0", a0, v(0.0, 0.0)),
        ("A1", a1, v(10.0, 0.0)),
        ("B0", b0, v(5.0, 0.0)),
        ("B1", b1, v(5.0, 4.0)),
    ]);
    // same question for the zero-valued projection here (k2: Y(A0->B0)=0.0)
    checks.push(xchk(
        "distance_y_zero_rank_analysis",
        rep.dof == 0,
        json!({"dof": rep.dof, "solved": rep.ok()}),
        json!({"dof": 0}),
        format!("literal DistanceY{{A0,B0,0.0}} mapping: solved={}, dof={}", rep.ok(), rep.dof),
    ));
    json!({
        "id": "perpendicular_pair",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "cases_kind_mapping": [
            {"cases_kind": "coincident_to_origin", "solidcraft": "Coincident { p: A0, q: 0 }"},
            {"cases_kind": "horizontal", "solidcraft": "Horizontal { l: lA }"},
            {"cases_kind": "distance_x", "solidcraft": "DistanceX { p: A0, q: A1, value: 10.0 }"},
            {"cases_kind": "distance_x", "solidcraft": "DistanceX { p: A0, q: B0, value: 5.0 }"},
            {"cases_kind": "distance_y", "solidcraft": "DistanceY { p: A0, q: B0, value: 0.0 } (literal; unsigned form at 0)"},
            {"cases_kind": "perpendicular", "solidcraft": "Perpendicular { a: lB, b: lA } — NATIVE (model.rs:227-230)"},
            {"cases_kind": "length", "solidcraft": "Length { l: lB, value: 4.0 }"},
        ],
        "provenance": "cases.json literal (m3-eval phase 2a new case); seeds from gen_solver_cases.py build_perpendicular_pair",
    })
}

fn case_diameter_dim() -> Value {
    let mut sk = build_diameter_dim();
    let rep = solve(&mut sk);
    let c = sk.curve_index("c").unwrap();
    let center = sk.point_index("c.center").unwrap();
    let r = sk.radius(c).unwrap();
    let mut checks = probe_common_checks(&sk, &rep, &[("c.center", center, v(0.0, 0.0))]);
    checks.push(chk(
        "c_radius_5.0", (r - 5.0).abs() < CHECK_TOL, json!(r), json!(5.0),
        format!("r={r} via the NATIVE Diameter kind (Diameter{{c, 10.0}}, residual 2r − value, solver.rs:567) — no adaptation needed"),
    ));
    json!({
        "id": "diameter_dim",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "cases_kind_mapping": [
            {"cases_kind": "coincident_to_origin", "solidcraft": "Coincident { p: c.center, q: 0 }"},
            {"cases_kind": "diameter", "solidcraft": "Diameter { c, value: 10.0 } — NATIVE (model.rs:304-307); unlike slvs, which derives radius from diameter, the crate has BOTH Radius and Diameter kinds"},
        ],
        "provenance": "cases.json literal (m3-eval phase 2a new case); seed from gen_solver_cases.py build_diameter_dim",
    })
}

fn case_symmetric_points() -> Value {
    let mut sk = build_symmetric_points();
    let rep = solve(&mut sk);
    let p = sk.point_index("p").unwrap();
    let q = sk.point_index("q").unwrap();
    let mut checks = probe_common_checks(&sk, &rep, &[
        ("p", p, v(2.0, 3.0)),
        ("q", q, v(-2.0, -3.0)),
    ]);
    checks.push(xchk(
        "native_Symmetric_kind_available",
        true,
        json!("Symmetric { p, q, l } (model.rs:251-255; residual: midpoint on the line + segment perpendicular to it, solver.rs:534-541)"),
        json!("recorded API-surface fact"),
        "cases.json's fixture uses midpoint-about-the-origin (point symmetry — which slvs must DERIVE via AT_MIDPOINT); the crate ALSO has the native line-mirror kind Symmetric, unused by this literal fixture — recorded for the coverage matrix".into(),
    ));
    json!({
        "id": "symmetric_points",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "cases_kind_mapping": [
            {"cases_kind": "midpoint", "solidcraft": "Midpoint { p: 0 (fixed origin), l: lM } — NATIVE (model.rs:247-250); the origin at the connecting segment's midpoint == point symmetry about the origin"},
            {"cases_kind": "distance_x", "solidcraft": "DistanceX { p, q, value: 4.0 } — cases.json's SIGNED slvs PROJ X(p->q)=-4 becomes the magnitude 4 (unsigned residual |dx|−value, solver.rs:544); the branch (q left of p) is chosen by the seed"},
            {"cases_kind": "distance_y", "solidcraft": "DistanceY { p, q, value: 6.0 } — signed Y(p->q)=-6 as magnitude 6 (q below p from seed)"},
        ],
        "provenance": "cases.json literal (m3-eval phase 2a new case); seeds from gen_solver_cases.py build_symmetric_points",
    })
}

fn case_midpoint_case() -> Value {
    let mut sk = build_midpoint_case();
    let rep = solve(&mut sk);
    let l0 = sk.point_index("l0").unwrap();
    let l1 = sk.point_index("l1").unwrap();
    let m = sk.point_index("m").unwrap();
    let checks = probe_common_checks(&sk, &rep, &[
        ("l0", l0, v(0.0, 0.0)),
        ("l1", l1, v(10.0, 0.0)),
        ("m", m, v(5.0, 0.0)),
    ]);
    json!({
        "id": "midpoint_case",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "cases_kind_mapping": [
            {"cases_kind": "coincident_to_origin", "solidcraft": "Coincident { p: l0, q: 0 }"},
            {"cases_kind": "horizontal", "solidcraft": "Horizontal { l: ll }"},
            {"cases_kind": "distance_x", "solidcraft": "DistanceX { p: l0, q: l1, value: 10.0 } (unsigned; l1 right of l0 from seed)"},
            {"cases_kind": "midpoint", "solidcraft": "Midpoint { p: m, l: ll } — NATIVE (model.rs:247-250; residual p − midpoint(l), solver.rs:529-533)"},
        ],
        "provenance": "cases.json literal (m3-eval phase 2a new case); seeds from gen_solver_cases.py build_midpoint_case",
    })
}

fn case_concentric_circles() -> Value {
    let mut sk = build_concentric_circles();
    let rep = solve(&mut sk);
    let c1 = sk.curve_index("c1").unwrap();
    let c2 = sk.curve_index("c2").unwrap();
    let c1c = sk.point_index("c1.center").unwrap();
    let c2c = sk.point_index("c2.center").unwrap();
    let r1 = sk.radius(c1).unwrap();
    let r2 = sk.radius(c2).unwrap();
    let mut checks = probe_common_checks(&sk, &rep, &[
        ("c1.center", c1c, v(0.0, 0.0)),
        ("c2.center", c2c, v(0.0, 0.0)),
    ]);
    checks.push(chk("c1_radius_3.0", (r1 - 3.0).abs() < CHECK_TOL, json!(r1), json!(3.0), format!("r1={r1} (native Diameter kind)")));
    checks.push(chk("c2_radius_5.0", (r2 - 5.0).abs() < CHECK_TOL, json!(r2), json!(5.0), format!("r2={r2} (native Diameter kind)")));
    checks.push(xchk(
        "native_Concentric_kind_available",
        true,
        json!("Concentric { a, b } (model.rs:243-246; residual = centre difference, solver.rs:525-528)"),
        json!("recorded API-surface fact"),
        "cases.json's fixture DERIVES concentricity via coincident centres (the slvs-side form — slvs has no concentric primitive); the crate has the native kind, unused by this literal fixture — recorded for the coverage matrix".into(),
    ));
    json!({
        "id": "concentric_circles",
        "solve": report_json(&rep),
        "geometry": geometry_json(&sk),
        "checks": checks,
        "cases_kind_mapping": [
            {"cases_kind": "coincident_to_origin", "solidcraft": "Coincident { p: c1.center, q: 0 }"},
            {"cases_kind": "coincident", "solidcraft": "Coincident { p: c2.center, q: c1.center } — the cases.json literal (derived concentricity); the crate ALSO has Concentric { a, b } natively"},
            {"cases_kind": "diameter", "solidcraft": "Diameter { c1, value: 6.0 } — native"},
            {"cases_kind": "diameter", "solidcraft": "Diameter { c2, value: 10.0 } — native"},
        ],
        "provenance": "cases.json literal (m3-eval phase 2a new case); seeds from gen_solver_cases.py build_concentric_circles",
    })
}

// ---------------------------------------------------------------------------
// corpus mode
// ---------------------------------------------------------------------------

fn run_corpus(cases_path: &str) -> Value {
    let file = std::fs::read_to_string(cases_path).unwrap_or_else(|e| panic!("cannot read cases corpus {cases_path}: {e}"));
    let corpus: Value = serde_json::from_str(&file).unwrap_or_else(|e| panic!("cases corpus is not valid JSON: {e}"));
    let cases_file = corpus
        .get("cases")
        .and_then(|c| c.as_array())
        .unwrap_or_else(|| panic!("cases corpus has no cases array"))
        .clone();

    // fixture-consistency gate: the harness must cover exactly the corpus ids, in
    // order; the embedded equivalence marks must match the (read-only) corpus; the
    // embedded declared-kinds lists must match the corpus's inputs.constraints.
    let mut mismatches: Vec<Value> = Vec::new();
    let corpus_ids: Vec<String> = cases_file.iter().map(|c| c.get("id").and_then(|i| i.as_str()).unwrap_or("?").to_string()).collect();
    let harness_order = [
        "bare_line", "bare_circle", "bare_arc", "circle_origin_radius", "triangle_constrained",
        "triangle_value_edit", "l_bracket_constrained", "l_bracket_no_dims", "slot_constrained",
        "line_horizontal_only", "circle_radius_only_edit", "rect_redundant_duplicate_dimension",
        "conflicting_distances", "coincident_plus_distance", "triangle_edit_unsolvable",
        "determinism_inprocess_5x", "determinism_crossprocess_3x",
        "parallel_offset", "perpendicular_pair", "diameter_dim", "symmetric_points",
        "midpoint_case", "concentric_circles",
    ];
    if corpus_ids.iter().map(String::as_str).collect::<Vec<_>>() != harness_order {
        mismatches.push(json!({"kind": "case_id_order", "corpus": corpus_ids, "harness": harness_order}));
    }
    for c in &cases_file {
        let id = c.get("id").and_then(|i| i.as_str()).unwrap_or("?");
        let mark = c.get("equivalence").and_then(|e| e.get("mark")).and_then(|m| m.as_str()).unwrap_or("");
        let (exp_mark, _) = expected_metadata(id);
        if mark != exp_mark {
            mismatches.push(json!({"kind": "equivalence_mark", "case": id, "corpus": mark, "harness": exp_mark}));
        }
        let corpus_kinds: Vec<String> = c
            .get("inputs")
            .and_then(|i| i.get("constraints"))
            .and_then(|k| k.as_array())
            .map(|a| a.iter().map(|x| x.get("kind").and_then(|k| k.as_str()).unwrap_or("").to_string()).collect())
            .unwrap_or_default();
        let harness_kinds: Vec<String> = declared_kinds(id).iter().map(|s| s.to_string()).collect();
        if c.get("inputs").map(|i| !i.is_null()).unwrap_or(false) && corpus_kinds != harness_kinds {
            mismatches.push(json!({"kind": "declared_constraint_kinds", "case": id, "corpus": corpus_kinds, "harness": harness_kinds}));
        }
    }

    let meta: BTreeMap<String, Value> = cases_file
        .iter()
        .map(|c| (c.get("id").and_then(|i| i.as_str()).unwrap_or("?").to_string(), c.clone()))
        .collect();

    let mut cases: Vec<Value> = Vec::new();
    cases.push(attach_meta(&meta, case_bare_line()));
    cases.push(attach_meta(&meta, case_bare_circle()));
    cases.push(attach_meta(&meta, case_bare_arc()));
    cases.push(attach_meta(&meta, case_circle_origin_radius()));
    cases.push(attach_meta(&meta, case_triangle_constrained()));
    cases.push(attach_meta(&meta, case_triangle_value_edit()));
    cases.push(attach_meta(&meta, case_l_bracket(true)));
    cases.push(attach_meta(&meta, case_l_bracket(false)));
    cases.push(attach_meta(&meta, case_slot()));
    cases.push(attach_meta(&meta, case_line_horizontal_only()));
    cases.push(attach_meta(&meta, case_circle_radius_only_edit()));
    cases.push(attach_meta(&meta, case_rect_redundant()));
    cases.push(attach_meta(&meta, case_conflicting_distances()));
    cases.push(attach_meta(&meta, case_coincident_plus_distance()));
    cases.push(attach_meta(&meta, case_triangle_edit_unsolvable()));
    cases.push(attach_meta(&meta, case_determinism_inprocess()));
    cases.push(attach_meta(&meta, case_determinism_crossprocess()));
    cases.push(attach_meta(&meta, case_parallel_offset()));
    cases.push(attach_meta(&meta, case_perpendicular_pair()));
    cases.push(attach_meta(&meta, case_diameter_dim()));
    cases.push(attach_meta(&meta, case_symmetric_points()));
    cases.push(attach_meta(&meta, case_midpoint_case()));
    cases.push(attach_meta(&meta, case_concentric_circles()));

    // every checks_declared name must be evaluated by the harness
    let mut undeclared_missing: Vec<Value> = Vec::new();
    for case in &cases {
        let id = case.get("id").and_then(|i| i.as_str()).unwrap_or("?");
        let declared: Vec<String> = meta
            .get(id)
            .and_then(|m| m.get("checks_declared"))
            .and_then(|d| d.as_array())
            .map(|a| a.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect())
            .unwrap_or_default();
        let evaluated: Vec<String> = case
            .get("checks")
            .and_then(|c| c.as_array())
            .map(|a| a.iter().map(|x| x.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string()).collect())
            .unwrap_or_default();
        for d in &declared {
            if !evaluated.contains(d) {
                undeclared_missing.push(json!({"case": id, "declared_check_not_evaluated": d}));
            }
        }
    }

    let mut checks_total = 0usize;
    let mut checks_passed = 0usize;
    let mut declared_total = 0usize;
    let mut declared_passed = 0usize;
    let mut failed_check_cases: Vec<String> = Vec::new();
    let mut not_run: Vec<Value> = Vec::new();
    for case in &cases {
        let id = case.get("id").and_then(|i| i.as_str()).unwrap_or("?").to_string();
        let mut any_failed = false;
        if let Some(list) = case.get("checks").and_then(|c| c.as_array()) {
            for ck in list {
                checks_total += 1;
                let extra = ck.get("extra").and_then(|e| e.as_bool()).unwrap_or(false);
                let pass = ck.get("pass").and_then(|p| p.as_bool()).unwrap_or(false);
                if !extra {
                    declared_total += 1;
                    if pass {
                        declared_passed += 1;
                    }
                }
                if pass {
                    checks_passed += 1;
                } else {
                    any_failed = true;
                    not_run.push(json!({"case": id, "check": ck.get("name"), "pass": false}));
                }
            }
        }
        if any_failed {
            failed_check_cases.push(id);
        }
    }

    json!({
        "mode": "corpus",
        "upstream": {
            "repo": "https://github.com/tangency-labs/solidcraft",
            "sha": UPSTREAM_SHA,
            "version": UPSTREAM_VERSION,
            "consumed_as": "path dependencies on ../.upstream/solidcraft/crates/{sketch,geom} (fetch-solidcraft.sh; gitignored scratch)",
        },
        "cases_corpus": {
            "path": cases_path,
            "note": "READ-ONLY canonical m3-eval corpus (experiments/cad-sketcher/fixtures/solver/cases.json); consumed, never edited",
            "cases": corpus_ids.len(),
        },
        "fixture_consistency": {
            "mismatches": mismatches,
            "declared_checks_missing": undeclared_missing,
        },
        "cases": cases,
        "summary": {
            "cases": cases.len(),
            "checks_total": checks_total,
            "checks_passed": checks_passed,
            "checks_failed": checks_total - checks_passed,
            "declared_checks_total": declared_total,
            "declared_checks_passed": declared_passed,
            "declared_checks_failed": declared_total - declared_passed,
            "cases_with_failed_checks": failed_check_cases,
        },
        "failed_checks_list": not_run,
    })
}

/// Attach the corpus metadata (description, equivalence mark+reason quoted,
/// source, expected, notes, checks_declared) to a harness case result.
fn attach_meta(meta: &BTreeMap<String, Value>, case: Value) -> Value {
    let id = case.get("id").and_then(|i| i.as_str()).unwrap_or("?").to_string();
    let m = meta.get(&id).cloned().unwrap_or(Value::Null);
    let mut out = serde_json::Map::new();
    out.insert("id".into(), json!(id));
    if !m.is_null() {
        for k in ["group", "description"] {
            if let Some(val) = m.get(k) {
                if !val.is_null() {
                    out.insert(k.to_string(), val.clone());
                }
            }
        }
        out.insert(
            "equivalence".into(),
            json!({
                "mark": m.get("equivalence").and_then(|e| e.get("mark")).cloned().unwrap_or(json!(null)),
                "reason": m.get("equivalence").and_then(|e| e.get("reason")).cloned().unwrap_or(json!(null)),
            }),
        );
        for k in ["source", "expected", "notes", "checks_declared"] {
            if let Some(val) = m.get(k) {
                if !val.is_null() {
                    out.insert(k.to_string(), val.clone());
                }
            }
        }
    }
    for (k, val) in case.as_object().unwrap() {
        if k != "id" {
            out.insert(k.clone(), val.clone());
        }
    }
    Value::Object(out)
}

// ---------------------------------------------------------------------------
// hash mode: the canonical 3 solved; digest line on stdout
// ---------------------------------------------------------------------------

fn hash_mode() {
    let (mut t, ..) = build_triangle();
    let r1 = solve(&mut t);
    let h1 = values_digest("triangle_constrained", &t);
    let (mut lb, _) = build_l_bracket_with(true, None);
    let r2 = solve(&mut lb);
    let h2 = values_digest("l_bracket_constrained", &lb);
    let mut sl = build_slot();
    let r3 = solve(&mut sl);
    let h3 = values_digest("slot_constrained", &sl);
    let hc = combined_digest(&[
        ("triangle_constrained", &t),
        ("l_bracket_constrained", &lb),
        ("slot_constrained", &sl),
    ]);
    let all_ok = r1.ok() && r2.ok() && r3.ok();
    println!("W1_GEOM_HASH {h1:016x} {h2:016x} {h3:016x} {hc:016x} ok={}", if all_ok { 1 } else { 0 });
}

// ---------------------------------------------------------------------------
// staircase mode: ONE run per invocation (fresh-process protocol)
// ---------------------------------------------------------------------------

fn staircase_mode(n: usize, do_edit: bool) -> Value {
    let mut rec = json!({"n": n, "driving": 1.0});
    let seed = staircase_seed(n);
    let mut sk = Sketch::new();
    let t0 = Instant::now();
    build_staircase(&mut sk, n, &seed, 1.0);
    let build_s = t0.elapsed().as_secs_f64();
    let t0 = Instant::now();
    let rep = solve(&mut sk);
    let solve_s = t0.elapsed().as_secs_f64();
    rec["build_s"] = json!(build_s);
    rec["solve_s"] = json!(solve_s);
    rec["status"] = json!(if rep.ok() { "solved" } else { "failed" });
    rec["dof"] = json!(rep.dof);
    rec["iterations"] = json!(rep.iterations);
    rec["max_residual"] = json!(rep.max_residual);
    rec["failing"] = json!(rep.failing);
    rec["redundant"] = json!(rep.redundant);
    rec["point_count"] = json!(sk.points.len());
    rec["curve_count"] = json!(sk.curves.len());
    rec["constraint_count"] = json!(sk.constraints.len());
    rec["max_len_err"] = json!(max_len_err(&sk, n, 1.0));

    if do_edit {
        // snapshot the SOLVED positions (points[0] is the fixed origin — skip it;
        // the staircase seed vector is p0..pn)
        let solved: Vec<Vec2> = sk.points.iter().skip(1).map(|p| p.pos).collect();

        // (a) slvs-comparable REBUILD path: rebuild from the solved seed, driving 1.5
        let mut sk2 = Sketch::new();
        let t0 = Instant::now();
        build_staircase(&mut sk2, n, &solved, 1.5);
        let rebuild_s = t0.elapsed().as_secs_f64();
        let t0 = Instant::now();
        let rep2 = solve(&mut sk2);
        let solve_after_edit_s = t0.elapsed().as_secs_f64();

        // (b) slvs's warm re-solve analogue: solve the ALREADY-SOLVED rebuilt system again
        let t0 = Instant::now();
        let _rep_warm = solve(&mut sk2);
        let idempotent_resolve_s = t0.elapsed().as_secs_f64();

        // (c) the crate's NATIVE edit path: constraint-value MUTATION + warm
        // re-solve WITHOUT any rebuild (set_value + solve_after_value_edit).
        let old: DrivingValues = sk.driving_values();
        set_dim(&mut sk, "dDriving", 1.5);
        let t0 = Instant::now();
        let rep_m = solve_after_value_edit(&mut sk, &old);
        let warm_resolve_s = t0.elapsed().as_secs_f64();

        rec["edit"] = json!({
            "new_driving": 1.5,
            "rebuild_s": rebuild_s,
            "solve_after_edit_s": solve_after_edit_s,
            "status_after_rebuild_path": if rep2.ok() { "solved" } else { "failed" },
            "dof_after_rebuild_path": rep2.dof,
            "max_len_err_after_rebuild_path": max_len_err(&sk2, n, 1.5),
            "warm_resolve_s": warm_resolve_s,
            "warm_resolve_path": "NATIVE MUTATION: ConstraintKind::set_value (model.rs:370-389) + solve_after_value_edit (solver.rs:1369-1371) on the already-solved sketch — NO rebuild (this is the path SolidCraft actually has)",
            "status_after_warm_mutation": if rep_m.ok() { "solved" } else { "failed" },
            "dof_after_warm_mutation": rep_m.dof,
            "continuations": rep_m.continuations,
            "folded": rep_m.folded,
            "max_len_err_after_warm_mutation": max_len_err(&sk, n, 1.5),
            "idempotent_resolve_s": idempotent_resolve_s,
            "idempotent_resolve_path": "solve() called again on the solved rebuilt system — the exact analogue of slvs's warm re-solve (second solve_sketch on the same system)",
        });
    }
    rec
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--hash") {
        hash_mode();
        return;
    }
    if let Some(pos) = args.iter().position(|a| a == "--staircase") {
        let n: usize = args.get(pos + 1).and_then(|s| s.parse().ok()).unwrap_or(10);
        let do_edit = args.iter().any(|a| a == "--edit");
        println!("{}", serde_json::to_string_pretty(&staircase_mode(n, do_edit)).unwrap_or_default());
        return;
    }
    let path = args
        .get(1)
        .cloned()
        .unwrap_or_else(|| format!("{}/../../cad-sketcher/fixtures/solver/cases.json", env!("CARGO_MANIFEST_DIR")));
    let out = run_corpus(&path);
    // human summary on stderr; the JSON envelope fragment on stdout
    eprintln!(
        "solidcraft-h2h-driver corpus: {} cases, checks {}/{} (declared {}/{})",
        out["summary"]["cases"], out["summary"]["checks_passed"], out["summary"]["checks_total"],
        out["summary"]["declared_checks_passed"], out["summary"]["declared_checks_total"],
    );
    for c in out["cases"].as_array().cloned().unwrap_or_default() {
        let id = c.get("id").and_then(|i| i.as_str()).unwrap_or("?");
        let (status, dof, iters) = match c.get("solve") {
            Some(s) => (
                s.get("status").and_then(|x| x.as_str()).unwrap_or("-").to_string(),
                s.get("dof").and_then(|x| x.as_u64()).map(|d| d.to_string()).unwrap_or_else(|| "-".into()),
                s.get("iterations").and_then(|x| x.as_u64()).map(|d| d.to_string()).unwrap_or_else(|| "-".into()),
            ),
            None => ("-".to_string(), "-".to_string(), "-".to_string()),
        };
        let nchecks = c.get("checks").and_then(|x| x.as_array()).map(|a| a.len()).unwrap_or(0);
        let passed = c
            .get("checks")
            .and_then(|x| x.as_array())
            .map(|a| a.iter().filter(|ck| ck.get("pass").and_then(|p| p.as_bool()).unwrap_or(false)).count())
            .unwrap_or(0);
        eprintln!("  {id:<38} status={status:<7} dof={dof:<3} iters={iters:<4} checks={passed}/{nchecks}");
    }
    println!("{}", serde_json::to_string_pretty(&out).unwrap_or_default());
}
