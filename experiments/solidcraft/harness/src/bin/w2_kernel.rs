//! W2 (lane b) experiment C — kernel benchmark, TRUCK SIDE.
//!
//! Runs the shared fixture set (../fixtures/kernel/, see its README + cases.json) through
//! the vendored-patched truck kernel exactly as SolidCraft ships it: direct
//! `solidcraft-kernel` API on the pinned upstream clone
//! (`../.upstream` @ 3b4db52c10279251a068cfca5eb7447068bc28e7, v0.16.2; the harness
//! replicates upstream's [patch.crates-io] so truck-geometry/truck-shapeops/
//! truck-meshalgo/truck-stepio are the SolidCraft-patched vendored copies).
//! Isolation rules of experiments/solidcraft/README.md apply: NOT product code.
//!
//! What it measures per fixture:
//!   - build outcome: the body, or the VERBATIM kernel error text (refusals are recorded,
//!     never dropped);
//!   - volume / area / CoM / bbox / topology via `kernel::measure` (tessellation-based,
//!     the same measurement the upstream oracle runner uses);
//!   - self-reported `Body::validity()` errors;
//!   - build timing: 1 warmup + 3 timed repeats, per-op split (dev profile — release-config
//!     timing comes from the official CLI path, recorded separately in results/w2-kernel.json);
//!   - STEP round-trip: `kernel::step_export` → `kernel::step_import` → volume/bbox delta.
//!
//! Modes:
//!   w2_kernel                      all fixtures → JSON to ../scratch/w2-kernel/truck-harness.json
//!   w2_kernel --case <id>          one fixture in an isolated process, JSON + peak RSS on stdout
//!   w2_kernel --emit-step <dir>    write each round-trip fixture's body as <dir>/<id>.step
//!                                  (STEP written by the vendored truck-stepio, for the
//!                                  cross-kernel read experiment)
//!   w2_kernel --read-step <dir>    STEP-import every *.step in <dir>, measure, JSON on stdout
//!                                  (used to read OCCT-written STEP with the truck reader)
//!
//! Run (from experiments/solidcraft/harness):   cargo run --bin w2_kernel -j 1

use std::f64::consts::TAU;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};
use solidcraft_geom::{Loop2, Plane, Region2, Seg2, Vec2, Vec3};
use solidcraft_kernel as kernel;

const UPSTREAM_SHA: &str = "3b4db52c10279251a068cfca5eb7447068bc28e7";
const UPSTREAM_VERSION: &str = "0.16.2";

// ---------------------------------------------------------------------------
// small utilities
// ---------------------------------------------------------------------------

fn rfc3339_now() -> String {
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let (days, rem) = (secs / 86400, secs % 86400);
    let (h, m, s) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let mth = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if mth <= 2 { y + 1 } else { y };
    format!("{y:04}-{mth:02}-{d:02}T{h:02}:{m:02}:{s:02}Z")
}

/// Peak resident set size of this process in KiB, from /proc/self/status (VmHWM).
fn peak_rss_kib() -> Option<u64> {
    let s = std::fs::read_to_string("/proc/self/status").ok()?;
    for line in s.lines() {
        if let Some(rest) = line.strip_prefix("VmHWM:") {
            return rest.trim().trim_end_matches("kB").trim().parse().ok();
        }
    }
    None
}

fn v2(x: f64, y: f64) -> Vec2 {
    Vec2::new(x, y)
}

fn rect_region(w: f64, h: f64) -> Region2 {
    rect_region_at(0.0, 0.0, w, h)
}

fn rect_region_at(x0: f64, y0: f64, w: f64, h: f64) -> Region2 {
    Region2 { outer: Loop2::polygon(&[v2(x0, y0), v2(x0 + w, y0), v2(x0 + w, y0 + h), v2(x0, y0 + h)]), holes: Vec::new() }
}

/// The XZ-plane sketch frame oracle 04 uses (sketch y = world -z), as the kernel takes it.
fn xz_ydown_plane() -> Plane {
    Plane::new(Vec3::ZERO, Vec3::X, -Vec3::Z).expect("valid plane")
}

// ---------------------------------------------------------------------------
// case builders: each returns (body | verbatim error), recording per-op timings
// ---------------------------------------------------------------------------

/// Timed sub-operations of one case build.
#[derive(Default)]
struct Steps {
    ops: Vec<(&'static str, f64)>,
}

impl Steps {
    fn run<T>(&mut self, name: &'static str, f: impl FnOnce() -> Result<T, kernel::KernelError>) -> Result<T, String> {
        let t = Instant::now();
        match f() {
            Ok(x) => {
                self.ops.push((name, t.elapsed().as_secs_f64() * 1000.0));
                Ok(x)
            }
            Err(e) => {
                self.ops.push((name, t.elapsed().as_secs_f64() * 1000.0));
                Err(e.to_string())
            }
        }
    }
}

type Build = Box<dyn Fn(&mut Steps) -> Result<kernel::Body, String>>;

/// One fixture: identity + metadata mirrored from fixtures/kernel/cases.json (the JSON is
/// the source of truth for provenance/expectations; this is the executable mirror).
struct Fixture {
    id: &'static str,
    ops: &'static [&'static str],
    comparability: (&'static str, &'static str),
    step_roundtrip: bool,
    build: Build,
}

fn err_str(e: kernel::KernelError) -> String {
    e.to_string()
}

fn take_body(v: Vec<kernel::Body>) -> Result<kernel::Body, String> {
    v.into_iter().next().ok_or_else(|| "kernel returned no body".to_string())
}

// --- oracle-derived builders ------------------------------------------------

fn build_k01(s: &mut Steps) -> Result<kernel::Body, String> {
    s.run("extrude", || kernel::extrude(&Plane::XY, &[rect_region(40.0, 30.0)], 0.0, 20.0))
        .and_then(take_body)
}

fn build_k02(s: &mut Steps) -> Result<kernel::Body, String> {
    s.run("cylinder", || kernel::cylinder(Vec3::ZERO, Vec3::Z, 15.0, 50.0))
}

fn build_k04(s: &mut Steps) -> Result<kernel::Body, String> {
    // Oracle 04 profile in sketch coords (sketch y = world -z), counter-clockwise:
    // (0,0) -> (0,-80) -> (18,-80) -> (15,-60) -> arc -> (25,-30) -> (20,0) -> close.
    // The arc passes through (23,-46); centre (-16,-33), radius sqrt(1690).
    let (cx, cy): (f64, f64) = (-16.0, -33.0);
    let r: f64 = ((25.0 - cx) * (25.0 - cx) + (-30.0 - cy) * (-30.0 - cy)).sqrt();
    let a0 = (-60.0 - cy).atan2(15.0 - cx); // at (15,-60)
    let a1 = (-30.0 - cy).atan2(25.0 - cx); // at (25,-30)
    let segs = vec![
        Seg2::Line { a: v2(0.0, 0.0), b: v2(0.0, -80.0) },
        Seg2::Line { a: v2(0.0, -80.0), b: v2(18.0, -80.0) },
        Seg2::Line { a: v2(18.0, -80.0), b: v2(15.0, -60.0) },
        Seg2::Arc { center: v2(cx, cy), radius: r, start: a0, sweep: a1 - a0 },
        Seg2::Line { a: v2(25.0, -30.0), b: v2(20.0, 0.0) },
        Seg2::Line { a: v2(20.0, 0.0), b: v2(0.0, 0.0) },
    ];
    let region = Region2 { outer: Loop2 { segs }, holes: Vec::new() };
    let plane = xz_ydown_plane();
    s.run("revolve", || {
        kernel::revolve_whole(&plane, &[region], Vec2::ZERO, Vec2::Y, TAU)
    })
    .and_then(take_body)
}

fn box_extruded(s: &mut Steps, w: f64, h: f64, d: f64) -> Result<kernel::Body, String> {
    s.run("extrude", || kernel::extrude(&Plane::XY, &[rect_region(w, h)], 0.0, d))
        .and_then(take_body)
}

fn build_k07(s: &mut Steps) -> Result<kernel::Body, String> {
    let b = box_extruded(s, 40.0, 30.0, 20.0)?;
    let edges: Vec<Vec3> = [
        [20.0, 0.0, 0.0], [20.0, 30.0, 0.0], [20.0, 0.0, 20.0], [20.0, 30.0, 20.0], // x-edges
        [0.0, 15.0, 0.0], [40.0, 15.0, 0.0], [0.0, 15.0, 20.0], [40.0, 15.0, 20.0], // y-edges
        [0.0, 0.0, 10.0], [40.0, 0.0, 10.0], [0.0, 30.0, 10.0], [40.0, 30.0, 10.0], // z-edges
    ]
    .into_iter()
    .map(|p| Vec3::new(p[0], p[1], p[2]))
    .collect();
    s.run("fillet_all_edges", || kernel::fillet(&b, &edges, 3.0))
}

fn build_k07b(s: &mut Steps) -> Result<kernel::Body, String> {
    let b = box_extruded(s, 40.0, 30.0, 20.0)?;
    let edges: Vec<Vec3> =
        [[0.0, 0.0, 10.0], [40.0, 0.0, 10.0], [0.0, 30.0, 10.0], [40.0, 30.0, 10.0]].into_iter().map(|p| Vec3::new(p[0], p[1], p[2])).collect();
    s.run("fillet_straight_edges", || kernel::fillet(&b, &edges, 3.0))
}

fn build_k08(s: &mut Steps) -> Result<kernel::Body, String> {
    let b = box_extruded(s, 40.0, 30.0, 20.0)?;
    let edges: Vec<Vec3> =
        [[20.0, 0.0, 20.0], [40.0, 15.0, 20.0], [20.0, 30.0, 20.0], [0.0, 15.0, 20.0]].into_iter().map(|p| Vec3::new(p[0], p[1], p[2])).collect();
    s.run("chamfer", || kernel::chamfer(&b, &edges, 2.0))
}

fn build_k09(s: &mut Steps) -> Result<kernel::Body, String> {
    let b = box_extruded(s, 50.0, 40.0, 30.0)?;
    let open = [Vec3::new(25.0, 20.0, 30.0)]; // pick point on the top face
    s.run("shell", || kernel::shell(&b, &open, 2.0))
}

fn build_k13(s: &mut Steps) -> Result<kernel::Body, String> {
    let a = box_extruded(s, 40.0, 40.0, 20.0)?;
    let b = s.run("cylinder", || kernel::cylinder(Vec3::new(40.0, 20.0, 0.0), Vec3::Z, 12.0, 40.0))?;
    s.run("boolean_union", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Union).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty union".into())))
    })
}

fn build_k14(s: &mut Steps) -> Result<kernel::Body, String> {
    // oracle 14: box [-25,25]^2 x [-20,0], sphere r=15 at the origin (lower hemisphere removed)
    let a = s.run("extrude", || kernel::extrude(&Plane::XY, &[rect_region_at(-25.0, -25.0, 50.0, 50.0)], -20.0, 0.0)).and_then(take_body)?;
    let b = s.run("sphere", || kernel::sphere(Vec3::ZERO, 15.0))?;
    s.run("boolean_cut", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Cut).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty cut".into())))
    })
}

fn build_k15(s: &mut Steps) -> Result<kernel::Body, String> {
    // oracle 15: cube [-20,20]^3 intersect sphere R=25 at the origin
    let a = s.run("extrude", || kernel::extrude(&Plane::XY, &[rect_region_at(-20.0, -20.0, 40.0, 40.0)], -20.0, 20.0)).and_then(take_body)?;
    let b = s.run("sphere", || kernel::sphere(Vec3::ZERO, 25.0))?;
    s.run("boolean_intersect", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Intersect).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty intersect".into())))
    })
}

fn build_k38(s: &mut Steps) -> Result<kernel::Body, String> {
    let a = s.run("cylinder", || kernel::cylinder(Vec3::ZERO, Vec3::Z, 10.0, 30.0))?;
    let b = s.run("cylinder", || kernel::cylinder(Vec3::new(0.0, 0.0, 20.0), Vec3::Z, 10.0, 30.0))?;
    s.run("boolean_union", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Union).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty union".into())))
    })
}

// --- self-authored builders (fixtures/kernel/cases.json: author W2 lane-b, 2026-10-20) ---

fn build_st1(s: &mut Steps) -> Result<kernel::Body, String> {
    let b = box_extruded(s, 40.0, 30.0, 20.0)?;
    let edges: Vec<Vec3> = [
        [20.0, 0.0, 0.0], [20.0, 30.0, 0.0], [20.0, 0.0, 20.0], [20.0, 30.0, 20.0],
        [0.0, 15.0, 0.0], [40.0, 15.0, 0.0], [0.0, 15.0, 20.0], [40.0, 15.0, 20.0],
        [0.0, 0.0, 10.0], [40.0, 0.0, 10.0], [0.0, 30.0, 10.0], [40.0, 30.0, 10.0],
    ]
    .into_iter()
    .map(|p| Vec3::new(p[0], p[1], p[2]))
    .collect();
    s.run("fillet_too_large", || kernel::fillet(&b, &edges, 200.0))
}

fn build_st2(s: &mut Steps) -> Result<kernel::Body, String> {
    let a = s.run("box", || kernel::box_solid(Vec3::ZERO, Vec3::new(20.0, 10.0, 10.0)))?;
    let b = s.run("cylinder", || kernel::cylinder(Vec3::new(10.0, 5.0, -5.0), Vec3::Z, 5.0001, 20.0))?;
    s.run("boolean_cut_near_tangent", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Cut).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty cut".into())))
    })
}

fn build_st3(s: &mut Steps) -> Result<kernel::Body, String> {
    s.run("extrude_sliver", || kernel::extrude(&Plane::XY, &[rect_region(50.0, 0.02)], 0.0, 10.0))
        .and_then(take_body)
}

fn build_st4(s: &mut Steps) -> Result<kernel::Body, String> {
    let a = s.run("box", || kernel::box_solid(Vec3::ZERO, Vec3::new(10.0, 10.0, 10.0)))?;
    let b = s.run("box", || kernel::box_solid(Vec3::new(10.0, 0.0, 0.0), Vec3::new(20.0, 10.0, 10.0)))?;
    s.run("boolean_union_coincident", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Union).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty union".into())))
    })
}

fn build_st5(s: &mut Steps) -> Result<kernel::Body, String> {
    let a = s.run("sphere", || kernel::sphere(Vec3::ZERO, 10.0))?;
    let b = s.run("sphere", || kernel::sphere(Vec3::new(19.99, 0.0, 0.0), 10.0))?;
    s.run("boolean_union_near_tangent", || {
        kernel::boolean(&a, &b, kernel::BoolOp::Union).and_then(|o| o.ok_or_else(|| kernel::KernelError::Failed("empty union".into())))
    })
}

// ---------------------------------------------------------------------------
// fixture table (mirrors fixtures/kernel/cases.json)
// ---------------------------------------------------------------------------

fn fixtures() -> Vec<Fixture> {
    fn f(
        id: &'static str,
        ops: &'static [&'static str],
        comparability: (&'static str, &'static str),
        step_roundtrip: bool,
        build: Build,
    ) -> Fixture {
        Fixture { id, ops, comparability, step_roundtrip, build }
    }

    vec![
        f("k01-box", &["primitive", "extrude"], ("comparable", "planar box; both kernels judged against V=abc"), true, Box::new(build_k01)),
        f("k02-cylinder", &["primitive"], ("comparable", "analytic cylinder; truck measures tessellated, OCCT integrates surfaces"), true, Box::new(build_k02)),
        f("k04-revolve-vase", &["revolve"], ("approximately-comparable", "same profile revolved 360 deg; seam/face splitting differs by kernel"), true, Box::new(build_k04)),
        f(
            "k07-fillet-all-edges",
            &["fillet_all_edges"],
            ("approximately-comparable", "rolling-ball corners differ BY DESIGN between kernels; totals judged against Steiner"),
            true,
            Box::new(build_k07),
        ),
        f(
            "k07b-fillet-4-vertical",
            &["fillet_straight_edge"],
            ("approximately-comparable", "no triple-edge corner patches; only end trimming can differ"),
            true,
            Box::new(build_k07b),
        ),
        f("k08-chamfer-top-edges", &["chamfer"], ("approximately-comparable", "chamfer miters at corners may differ"), true, Box::new(build_k08)),
        f(
            "k09-shell-open-top",
            &["shell"],
            ("approximately-comparable", "truck polyhedron::shell vs OCCT MakeThickSolid are different algorithms; equal only on this convex analytic case"),
            true,
            Box::new(build_k09),
        ),
        f("k13-union-box-cyl", &["boolean_union", "boolean_curved_curved"], ("comparable", "analytic totals for the union"), true, Box::new(build_k13)),
        f("k14-cut-box-sphere", &["boolean_cut", "boolean_curved_curved"], ("comparable", "analytic totals for the cut"), true, Box::new(build_k14)),
        f("k15-intersect-cube-sphere", &["boolean_intersect", "boolean_curved_curved"], ("comparable", "analytic totals for the intersection"), true, Box::new(build_k15)),
        f(
            "k38-union-coincident-cyls",
            &["boolean_union", "robustness_coincident"],
            ("comparable", "coincident lateral faces; analytic result is one r10 h50 cylinder"),
            true,
            Box::new(build_k38),
        ),
        f(
            "st1-fillet-too-large",
            &["robustness_refusal", "fillet_all_edges"],
            ("approximately-comparable", "failure probe: refusal with a clear error is an honest outcome"),
            false,
            Box::new(build_st1),
        ),
        f("st2-near-tangent-cut", &["boolean_cut", "robustness_near_tangent"], ("comparable", "near-tangent cut with analytic total"), true, Box::new(build_st2)),
        f("st3-thin-sliver-extrude", &["extrude", "robustness_sliver"], ("comparable", "sliver with exact analytic total"), true, Box::new(build_st3)),
        f("st4-coincident-face-union", &["boolean_union", "robustness_coincident"], ("comparable", "coincident face union with analytic total"), true, Box::new(build_st4)),
        f("st5-near-tangent-sphere-union", &["boolean_union", "robustness_near_tangent"], ("comparable", "near-tangent lens union with analytic total"), true, Box::new(build_st5)),
    ]
}

// ---------------------------------------------------------------------------
// measurement
// ---------------------------------------------------------------------------

fn measure_json(m: &kernel::BodyMeasure) -> Value {
    json!({
        "volume_mm3": m.volume,
        "area_mm2": m.area,
        "center_of_mass": [m.centroid.x, m.centroid.y, m.centroid.z],
        "bbox": {"min": [m.bbox.min.x, m.bbox.min.y, m.bbox.min.z], "max": [m.bbox.max.x, m.bbox.max.y, m.bbox.max.z]},
        "faces": m.faces, "edges": m.edges, "vertices": m.vertices, "shells": m.shells,
        "faces_merged": m.merged.faces,
    })
}

fn steps_json(steps: &Steps) -> Value {
    json!(steps.ops.iter().map(|(n, ms)| json!({"op": n, "ms": round3(*ms)})).collect::<Vec<_>>())
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

/// STEP round-trip of one body: export (vendored truck-stepio) → import (truck step_in) →
/// volume/bbox deltas. Returns the JSON record.
fn step_roundtrip(body: &kernel::Body) -> Value {
    let t = Instant::now();
    let export = match kernel::step_export(&[body], "w2-kernel-harness") {
        Ok(t) => t,
        Err(e) => return json!({"ok": false, "stage": "export", "error": e.to_string()}),
    };
    let export_ms = t.elapsed().as_secs_f64() * 1000.0;
    let t = Instant::now();
    let imp = match kernel::step_import(&export) {
        Ok(i) => i,
        Err(e) => return json!({"ok": false, "stage": "import", "error": e.to_string(), "export_bytes": export.len()}),
    };
    let import_ms = t.elapsed().as_secs_f64() * 1000.0;
    let original = kernel::measure(body).ok();
    let back: Vec<kernel::BodyMeasure> = imp.bodies.iter().filter_map(|b| kernel::measure(&b.body).ok()).collect();
    let vol: f64 = back.iter().map(|m| m.volume).sum();
    let area: f64 = back.iter().map(|m| m.area).sum();
    // bbox of the imported bodies taken together (a multi-lump result round-trips as several bodies)
    let back_bbox = back.iter().fold(None::<(solidcraft_geom::Vec3, solidcraft_geom::Vec3)>, |acc, m| match acc {
        None => Some((m.bbox.min, m.bbox.max)),
        Some((lo, hi)) => Some((
            solidcraft_geom::Vec3::new(lo.x.min(m.bbox.min.x), lo.y.min(m.bbox.min.y), lo.z.min(m.bbox.min.z)),
            solidcraft_geom::Vec3::new(hi.x.max(m.bbox.max.x), hi.y.max(m.bbox.max.y), hi.z.max(m.bbox.max.z)),
        )),
    });
    let (dvol, darea, dbbox) = match (&original, back_bbox) {
        (Some(o), Some((blo, bhi))) => {
            let db = (o.bbox.min.x - blo.x)
                .abs()
                .max((o.bbox.min.y - blo.y).abs())
                .max((o.bbox.min.z - blo.z).abs())
                .max((o.bbox.max.x - bhi.x).abs())
                .max((o.bbox.max.y - bhi.y).abs())
                .max((o.bbox.max.z - bhi.z).abs());
            (
                if o.volume.abs() > 1e-9 { (vol - o.volume).abs() / o.volume.abs() } else { f64::NAN },
                if o.area.abs() > 1e-9 { (area - o.area).abs() / o.area.abs() } else { f64::NAN },
                db,
            )
        }
        _ => (f64::NAN, f64::NAN, f64::NAN),
    };
    json!({
        "ok": true,
        "export_bytes": export.len(),
        "export_ms": round3(export_ms),
        "import_ms": round3(import_ms),
        "bodies_back": imp.bodies.len(),
        "closed": imp.bodies.iter().map(|b| b.closed).collect::<Vec<_>>(),
        "file_faces": imp.bodies.iter().map(|b| b.file_faces).collect::<Vec<_>>(),
        "warnings": imp.warnings,
        "schema": imp.schema,
        "roundtrip_volume_mm3": vol,
        "roundtrip_area_mm2": area,
        "rel_volume_delta": dvol,
        "rel_area_delta": darea,
        "bbox_max_abs_delta_mm": dbbox,
        "original_volume_mm3": original.as_ref().map(|o| o.volume),
    })
}

/// Run one fixture: warmup + 3 timed repeats (successful builds) or the single failing run.
fn run_fixture(fix: &Fixture) -> Value {
    // warmup (also the run that produces the error, if any)
    let (warm, warm_err) = {
        let mut s = Steps::default();
        let r = (fix.build)(&mut s);
        match r {
            Ok(b) => (Some((b, s)), None),
            Err(e) => (None, Some((e, s))),
        }
    };

    let mut repeats: Vec<Value> = Vec::new();
    let mut last_steps: Option<Value> = None;
    let mut last_ok_body: Option<kernel::Body> = None;

    if let Some((body, _)) = warm.as_ref() {
        last_ok_body = Some(body.clone());
    }

    if warm_err.is_some() {
        let (e, s) = warm_err.unwrap();
        let ms: f64 = s.ops.iter().map(|(_, ms)| ms).sum();
        repeats.push(json!({"run": "failure", "total_ms": round3(ms)}));
        last_steps = Some(steps_json(&s));
        return case_json(fix, json!({"outcome": "refused-with-error", "error": e}), last_steps.unwrap(), repeats, None, &warm);
    }

    for i in 0..3 {
        let mut s = Steps::default();
        let t = Instant::now();
        let r = (fix.build)(&mut s);
        let total = t.elapsed().as_secs_f64() * 1000.0;
        match r {
            Ok(b) => {
                repeats.push(json!({"run": i, "total_ms": round3(total), "ok": true}));
                last_steps = Some(steps_json(&s));
                last_ok_body = Some(b);
            }
            Err(e) => {
                // a build that succeeded once and failed later would be recorded verbatim
                repeats.push(json!({"run": i, "total_ms": round3(total), "ok": false, "error": e}));
            }
        }
    }

    let mut measure_rec: Option<(Value, f64)> = None;
    if let Some(body) = last_ok_body.as_ref() {
        let t = Instant::now();
        match kernel::measure(body) {
            Ok(m) => {
                let ms = t.elapsed().as_secs_f64() * 1000.0;
                measure_rec = Some((measure_json(&m), ms));
            }
            Err(e) => {
                measure_rec = Some((json!({"measure_error": e.to_string()}), f64::NAN));
            }
        }
    }

    let body_ref = last_ok_body.as_ref();
    case_json(fix, success_json(body_ref, measure_rec), last_steps.unwrap_or(Value::Null), repeats, body_ref, &warm)
}

#[allow(clippy::too_many_arguments)]
fn case_json(
    fix: &Fixture,
    outcome: Value,
    steps: Value,
    repeats: Vec<Value>,
    body: Option<&kernel::Body>,
    warm: &Option<(kernel::Body, Steps)>,
) -> Value {
    let validity = body.map(|b| b.validity()).unwrap_or_default();
    let mut timing = json!({
        "profile": "harness dev (deps opt-level 2, debug-assertions off; release-config timing comes from the official CLI path in results/w2-kernel.json)",
        "repeats": repeats,
        "steps_last_run": steps,
    });
    if let Some((_, ws)) = warm {
        timing["warmup_steps"] = steps_json(ws);
    }
    let step_rt = if fix.step_roundtrip && body.is_some() { step_roundtrip(body.unwrap()) } else { Value::Null };
    json!({
        "id": fix.id,
        "op_classes": fix.ops,
        "comparability": {"label": fix.comparability.0, "why": fix.comparability.1},
        "outcome": outcome,
        "validity_errors": validity,
        "timing": timing,
        "step_roundtrip": step_rt,
    })
}

fn success_json(body: Option<&kernel::Body>, measure_rec: Option<(Value, f64)>) -> Value {
    match (body, measure_rec) {
        (Some(_), Some((m, ms))) => json!({"outcome": "success", "measure": m, "measure_ms": if ms.is_nan() { Value::Null } else { json!(round3(ms)) }}),
        (Some(_), None) => json!({"outcome": "success", "measure": Value::Null}),
        (None, _) => json!({"outcome": "no-body"}),
    }
}

// ---------------------------------------------------------------------------
// modes
// ---------------------------------------------------------------------------

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let harness_commit = std::env::var("HARNESS_COMMIT").ok().or_else(|| {
        // best-effort: the runner sets HARNESS_COMMIT; a manual run records "unrecorded"
        None
    });

    if let Some(i) = args.iter().position(|a| a == "--case") {
        let id = args.get(i + 1).cloned().unwrap_or_default();
        let fix = fixtures().into_iter().find(|f| f.id == id).unwrap_or_else(|| panic!("unknown case {id}"));
        let rec = run_fixture(&fix);
        let out = json!({
            "mode": "case", "id": id, "upstream_sha": UPSTREAM_SHA, "harness_commit": harness_commit,
            "record": rec, "peak_rss_kib": peak_rss_kib(),
        });
        println!("{out}");
        return;
    }

    if let Some(i) = args.iter().position(|a| a == "--emit-step") {
        let dir = args.get(i + 1).cloned().unwrap_or_else(|| ".".into());
        std::fs::create_dir_all(&dir).expect("create dir");
        let mut written = Vec::new();
        for fix in fixtures() {
            if !fix.step_roundtrip {
                continue;
            }
            let mut s = Steps::default();
            if let Ok(body) = (fix.build)(&mut s) {
                match kernel::step_export(&[&body], "w2-kernel-harness") {
                    Ok(text) => {
                        let path = format!("{}/{}.step", dir.trim_end_matches('/'), fix.id);
                        std::fs::write(&path, &text).expect("write step");
                        written.push(json!({"id": fix.id, "path": path, "bytes": text.len()}));
                    }
                    Err(e) => written.push(json!({"id": fix.id, "error": e.to_string()})),
                }
            }
        }
        println!("{}", json!({"mode": "emit-step", "dir": dir, "files": written, "upstream_sha": UPSTREAM_SHA}));
        return;
    }

    if let Some(i) = args.iter().position(|a| a == "--read-step") {
        let dir = args.get(i + 1).cloned().unwrap_or_else(|| ".".into());
        let mut entries: Vec<_> = std::fs::read_dir(&dir)
            .unwrap_or_else(|e| panic!("read dir {dir}: {e}"))
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.extension().is_some_and(|x| x == "step"))
            .collect();
        entries.sort();
        let mut read = Vec::new();
        for p in &entries {
            let name = p.file_name().unwrap_or_default().to_string_lossy().to_string();
            let text = match std::fs::read_to_string(p) {
                Ok(t) => t,
                Err(e) => {
                    read.push(json!({"file": name, "error": e.to_string()}));
                    continue;
                }
            };
            let t = Instant::now();
            match kernel::step_import(&text) {
                Ok(imp) => {
                    let ms = t.elapsed().as_secs_f64() * 1000.0;
                    let measures: Vec<Value> = imp.bodies.iter().filter_map(|b| kernel::measure(&b.body).ok()).map(|m| measure_json(&m)).collect();
                    read.push(json!({
                        "file": name, "import_ms": round3(ms), "bodies": imp.bodies.len(),
                        "closed": imp.bodies.iter().map(|b| b.closed).collect::<Vec<_>>(),
                        "warnings": imp.warnings, "schema": imp.schema, "system": imp.system,
                        "measures": measures,
                    }));
                }
                Err(e) => read.push(json!({"file": name, "error": e.to_string(), "import_ms": round3(t.elapsed().as_secs_f64() * 1000.0)})),
            }
        }
        println!("{}", json!({"mode": "read-step", "dir": dir, "files": read, "upstream_sha": UPSTREAM_SHA}));
        return;
    }

    // default: all fixtures → scratch JSON + stdout summary
    let started = rfc3339_now();
    let t0 = Instant::now();
    let mut records = Vec::new();
    for fix in fixtures() {
        records.push(run_fixture(&fix));
    }
    let finished = rfc3339_now();

    let n_ok = records.iter().filter(|r| r["outcome"]["outcome"] == "success").count();
    let n_refused = records.iter().filter(|r| r["outcome"]["outcome"] == "refused-with-error").count();
    let out = json!({
        "mode": "all",
        "upstream": {"repo": "https://github.com/tangency-labs/solidcraft", "sha": UPSTREAM_SHA, "version": UPSTREAM_VERSION, "vendored_truck_patches": true},
        "harness_commit": harness_commit,
        "kernel_path": "solidcraft-kernel (vendored patched truck-geometry/truck-shapeops/truck-meshalgo/truck-stepio via [patch.crates-io])",
        "profile": "dev (deps opt-level 2, debug-assertions off; upstream dev-profile fidelity)",
        "started_utc": started,
        "finished_utc": finished,
        "wall_ms": round3(t0.elapsed().as_secs_f64() * 1000.0),
        "peak_rss_kib": peak_rss_kib(),
        "cases": records,
        "summary": {"total": records.len(), "success": n_ok, "refused_with_error": n_refused},
    });

    let path = "../scratch/w2-kernel/truck-harness.json";
    if let Some(parent) = std::path::Path::new(path).parent() {
        std::fs::create_dir_all(parent).expect("scratch dir");
    }
    std::fs::write(path, serde_json::to_vec_pretty(&out).expect("serialize")).expect("write result");
    eprintln!("wrote {path}: {} cases, {} success, {} refused, wall {:.1}s", records.len(), n_ok, n_refused, t0.elapsed().as_secs_f64());
    for r in &records {
        let id = r["id"].as_str().unwrap_or("?");
        let outcome = r["outcome"]["outcome"].as_str().unwrap_or("?");
        if outcome == "success" {
            let v = r["outcome"]["measure"]["volume_mm3"].as_f64().unwrap_or(f64::NAN);
            eprintln!("  {id:<32} {outcome:<20} V={v:.6}");
        } else {
            let e = r["outcome"]["error"].as_str().unwrap_or("");
            eprintln!("  {id:<32} {outcome:<20} error: {e}");
        }
    }
}
