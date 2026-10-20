//! PlaneGCS-side solver head-to-head driver (M3-entry gate; NOT product code).
//!
//! Lane: experiments/solver-h2h (isolated). Drives the pinned PlaneGCS solver
//! (FreeCAD 1.1.4 tag 4fd3bf3, src/Mod/Sketcher/App/planegcs/ — 11 files,
//! LGPL-family headers; built standalone against eigen 3.4.0 (sha256-pinned
//! release artifact) + system boost 1.83 + the lane's compat shims) on the
//! CANONICAL m3-eval fixture corpus cases.json (23 cases: 17 W1-identical +
//! 6 PAR coverage probes; consumed read-only) plus the staircase scale fixture
//! and the determinism protocol, and prints machine-readable JSON.
//!
//! Fixture semantics: the 23 builders are transcribed from m3-eval's
//! gen_solver_cases.py (which transcribed TL2's w1_sketch.rs; the equivalence
//! chain is documented per case). The generator (gen_planegcs_results.py)
//! ASSERTS the driver-emitted inputs match cases.json's inputs — the
//! transcription is machine-verified, not trusted.
//!
//! Solve protocol (mirrors FreeCAD 1.1.4 Sketch.cpp:262-340,4795-4830):
//!   declareUnknowns -> initSolution(DogLeg) [runs diagnose internally,
//!   GCS.cpp:1731-1737] -> record dof/conflicting/redundant tags ->
//!   solve chain DogLeg -> BFGS -> LevenbergMarquardt -> applySolution ONLY
//!   on Success (copy-solve, no write-back on failure = bitwise restore).
//!
//! Modes:
//!   [corpus]        run all 23 cases; JSON record on stdout
//!   --hash          solve the canonical 3 (triangle, L-bracket, slot); print
//!                   one digest line (cross-process determinism; mirrors the
//!                   m3-eval --hash submode)
//!   --staircase N [--edit]  one staircase scale run at size N; single JSON
//!                   record (one run per invocation, fresh process)
//!
//! Digest: FNV-1a-64 over f64 LE bits — the m3-eval/TL2 layout exactly:
//!   per point: id bytes + x bits + y bits; per curve: id bytes + kind tag
//!   ('L'/'C'/'A') + u64 point indices (+ radius bits for circles).

#include "Mod/Sketcher/App/planegcs/GCS.h"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <sstream>
#include <string>
#include <vector>

static constexpr double kPi = 3.14159265358979323846;

// ------------------------------------------------------------- JSON emit (stack-based)

struct JOut {
    std::string s;
    std::vector<bool> pend;   // per open container: a comma is pending before next elem
    void pre() { if (!pend.empty() && pend.back()) { s += ','; } }
    void obj() { pre(); s += '{'; pend.push_back(false); }
    void arr() { pre(); s += '['; pend.push_back(false); }
    void endobj() { s += '}'; pend.pop_back(); if (!pend.empty()) pend.back() = true; }
    void endarr() { s += ']'; pend.pop_back(); if (!pend.empty()) pend.back() = true; }
    void key(const std::string& k) { pre(); s += '"' + k + "\":"; pend.back() = false; }
    void str(const std::string& v) {
        pre(); s += '"';
        for (char c : v) { if (c == '"' || c == '\\') s += '\\'; s += c; }
        s += '"';
        pend.back() = true;
    }
    void rawval(const std::string& v) { pre(); s += v; pend.back() = true; }
    void num(double v) {
        char b[64];
        if (v == (long long)v && std::abs(v) < 1e15)
            std::snprintf(b, sizeof b, "%lld", (long long)v);
        else
            std::snprintf(b, sizeof b, "%.17g", v);
        rawval(b);
    }
    void i(long long v) { char b[32]; std::snprintf(b, sizeof b, "%lld", v); rawval(b); }
    void b(bool v) { rawval(v ? "true" : "false"); }
    void kstr(const std::string& k, const std::string& v) { key(k); str(v); }
    void knum(const std::string& k, double v) { key(k); num(v); }
    void ki(const std::string& k, long long v) { key(k); i(v); }
    void kb(const std::string& k, bool v) { key(k); b(v); }
};

// ------------------------------------------------------------- digest helpers

static uint64_t fnv1a64(const uint8_t* d, size_t n) {
    uint64_t h = 0xCBF29CE484222325ULL;
    for (size_t i = 0; i < n; i++) { h ^= d[i]; h *= 0x100000001B3ULL; }
    return h;
}
static void u64buf(std::vector<uint8_t>& b, uint64_t v) {
    for (int i = 0; i < 8; i++) b.push_back((uint8_t)(v >> (8 * i)));
}
static void f64buf(std::vector<uint8_t>& b, double v) {
    uint64_t bits; std::memcpy(&bits, &v, 8); u64buf(b, bits);
}
static std::string hex64(uint64_t v) {
    char b[32]; std::snprintf(b, sizeof b, "%016llx", (unsigned long long)v);
    return b;
}
static std::string fmt(double v) {
    char b[64]; std::snprintf(b, sizeof b, "%g", v); return b;
}

// ------------------------------------------------------------- CaseBuilder

struct ConRec { std::string label, kind, detail; int tag; };

struct CaseBuilder {
    GCS::System sys;
    std::deque<std::array<double, 2>> pstore;     // owned point coords (stable)
    std::deque<double> vstore;                    // owned datum/radius doubles
    std::vector<std::string> order;               // point insertion order
    std::map<std::string, GCS::Point> points;
    std::map<std::string, GCS::Line> lines;
    std::map<std::string, GCS::Circle> circles;
    std::map<std::string, GCS::Arc> arcs;
    std::map<std::string, int> curve_kind;        // 0 line, 1 circle, 2 arc
    std::map<std::string, double*> radius_of;     // curve label -> rad param
    std::map<std::string, double*> datum_of;      // constraint label -> datum
    std::map<std::string, std::string> c_top;     // curve topology
    std::vector<ConRec> cons;
    std::map<int, std::string> tag_to_label;
    std::vector<std::array<std::string, 4>> tangent_specs; // label,line,arc,shared
    int tag = 0;
    GCS::Point origin;                            // fixed (0,0) — NOT an unknown
    double origin_xy[2] = {0.0, 0.0};

    CaseBuilder() : origin(&origin_xy[0], &origin_xy[1]) {}

    // -- entities ----------------------------------------------------------
    GCS::Point& pt(const std::string& l, double x, double y) {
        pstore.push_back({x, y});
        order.push_back(l);
        points[l] = GCS::Point(&pstore.back()[0], &pstore.back()[1]);
        return points[l];
    }
    double* val(double v) { vstore.push_back(v); return &vstore.back(); }

    void line(const std::string& l, const std::string& a, const std::string& b) {
        GCS::Line ln; ln.p1 = points[a]; ln.p2 = points[b];
        lines[l] = ln; curve_kind[l] = 0; c_top[l] = a + " " + b;
    }
    void circle(const std::string& l, const std::string& center, double radius_seed) {
        GCS::Circle c; c.center = points[center]; c.rad = val(radius_seed);
        circles[l] = c; curve_kind[l] = 1; radius_of[l] = circles[l].rad;
        c_top[l] = center;
    }
    void arc(const std::string& l, const std::string& c, const std::string& s,
             const std::string& e) {
        GCS::Arc a; a.center = points[c]; a.start = points[s]; a.end = points[e];
        double r = std::hypot(*points[s].x - *points[c].x, *points[s].y - *points[c].y);
        double sa = std::atan2(*points[s].y - *points[c].y, *points[s].x - *points[c].x);
        double ea = std::atan2(*points[e].y - *points[c].y, *points[e].x - *points[c].x);
        a.rad = val(r); a.startAngle = val(sa); a.endAngle = val(ea);
        arcs[l] = a; curve_kind[l] = 2; radius_of[l] = arcs[l].rad;
        c_top[l] = c + " " + s + " " + e;
        int t = ++tag;
        sys.addConstraintArcRules(arcs[l], t);
        k_raw("arcrule:" + l, "arcrules", "ArcRules(" + l + "): start/end bound to "
              "centre+radius+angles (FreeCAD's own arc formulation)", t);
    }

    // -- constraints (each logs label/kind/detail + the real TAG) -------------
    // NOTE: GCS's addConstraint* return the constraint's index in clist, NOT
    // the tag; getConflicting/getRedundant report TAGS — so the label map
    // must be keyed by the tagId we pass, never by the return value.
    int k_raw(const std::string& label, const std::string& kind,
              const std::string& detail, int tagId) {
        cons.push_back({label, kind, detail, tagId});
        tag_to_label[tagId] = label;
        return tagId;
    }
    void k_coincident(const std::string& l, const std::string& p, const std::string& q) {
        int t = ++tag;
        sys.addConstraintP2PCoincident(points[p], points[q], t);
        k_raw(l, "coincident", p + " <-> " + q, t);
    }
    void k_coincident_origin(const std::string& l, const std::string& p) {
        int t = ++tag;
        sys.addConstraintP2PCoincident(points[p], origin, t);
        k_raw(l, "coincident_to_origin", p + " <-> fixed origin", t);
    }
    void k_horizontal(const std::string& l, const std::string& ln) {
        int t = ++tag;
        sys.addConstraintHorizontal(lines[ln], t);
        k_raw(l, "horizontal", ln, t);
    }
    void k_vertical(const std::string& l, const std::string& ln) {
        int t = ++tag;
        sys.addConstraintVertical(lines[ln], t);
        k_raw(l, "vertical", ln, t);
    }
    void k_distance(const std::string& l, const std::string& p, const std::string& q,
                    double v) {
        datum_of[l] = val(v);
        int t = ++tag;
        sys.addConstraintP2PDistance(points[p], points[q], datum_of[l], t);
        k_raw(l, "distance", "|" + p + " " + q + "| = " + fmt(v), t);
    }
    void k_length(const std::string& l, const std::string& ln, double v) {
        datum_of[l] = val(v);
        int t = ++tag;
        sys.addConstraintP2PDistance(lines[ln].p1, lines[ln].p2, datum_of[l], t);
        k_raw(l, "length", "|" + ln + "| = " + fmt(v), t);
    }
    void k_diameter(const std::string& l, const std::string& cv, double v) {
        datum_of[l] = val(v);
        std::string d = "diameter(" + cv + ") = " + fmt(v);
        int t = ++tag;
        if (curve_kind[cv] == 2) sys.addConstraintArcDiameter(arcs[cv], datum_of[l], t);
        else sys.addConstraintCircleDiameter(circles[cv], datum_of[l], t);
        k_raw(l, "diameter", d, t);
    }
    void k_angle(const std::string& l, const std::string& la, const std::string& lb,
                 double deg, bool inverse) {
        // m3-eval semantics: slvs angle(la,lb,deg,inverse=true) = direction
        // cosine with entityA's vector FLIPPED (constrainteq.cpp:890-910).
        // planegcs form: the 4-point L2LAngle passes the flipped pair
        // explicitly (swapping the first two points = flipping l1's vector).
        datum_of[l] = val(deg * kPi / 180.0);
        GCS::Point p1 = lines[la].p1, p2 = lines[la].p2;
        if (inverse) std::swap(p1, p2);
        int t = ++tag;
        sys.addConstraintL2LAngle(p1, p2, lines[lb].p1, lines[lb].p2, datum_of[l], t);
        k_raw(l, "angle", "angle(" + la + "," + lb + ") = " + fmt(deg) + " deg" +
              (inverse ? ", inverse=True (l1 vector flipped via the 4-point form)" : ""), t);
    }
    void k_tangent_arc_line(const std::string& l, const std::string& a,
                            const std::string& ln) {
        // Corpus semantics: "tangent(arc,line) with the endpoint auto-selected
        // by the shared point" + STRUCTURAL endpoint sharing. planegcs's
        // direct primitive for Line-Arc tangency is the curve-level form
        // addConstraintTangent(Line, Arc) == addConstraintP2LDistance(center,
        // line, rad) (GCS.cpp — the center-to-line-distance == radius form).
        // With the endpoints shared onto the lines, this reduces to
        // perpendicularity of line and radius at the shared endpoint.
        // The FreeCAD endpoint-tangency form (AngleViaPoint) was ALSO probed
        // (--slotdebug): structurally clean (dof 0) but the SOLVE collapses to
        // the r->0 degenerate manifold from the W1 rough seed — recorded in
        // findings/planegcs-conformance.md as a formulation/robustness probe.
        int t = ++tag;
        sys.addConstraintTangent(lines[ln], arcs[a], t);
        k_raw(l, "tangent_arc_line", "tangent(" + a + "," + ln + ") (curve-level "
              "Line-Arc tangent = P2LDistance(a.center, l, a.rad), structural "
              "endpoint sharing as in the corpus)", t);
    }
    void k_equal(const std::string& l, const std::string& a, const std::string& b) {
        std::string d = "equal(" + a + "," + b + ")";
        int t = ++tag;
        if (curve_kind[a] == 2)  // arcs: equal radii (slvs Equal on arcs = radius)
            sys.addConstraintEqualRadius(arcs[a], arcs[b], t);
        else
            sys.addConstraintEqualLength(lines[a], lines[b], t);
        k_raw(l, "equal", d, t);
    }
    void k_parallel(const std::string& l, const std::string& a, const std::string& b) {
        int t = ++tag;
        sys.addConstraintParallel(lines[a], lines[b], t);
        k_raw(l, "parallel", "parallel(" + a + "," + b + ")", t);
    }
    void k_perpendicular(const std::string& l, const std::string& a, const std::string& b) {
        int t = ++tag;
        sys.addConstraintPerpendicular(lines[a], lines[b], t);
        k_raw(l, "perpendicular", "perp(" + a + "," + b + ")", t);
    }
    void k_midpoint(const std::string& l, const std::string& p, const std::string& ln) {
        // "p at midpoint of ln" == ln's endpoints symmetric about point p
        // (planegcs P2PSymmetric point form; slvs exposed AT_MIDPOINT — the
        // identical equation set, native here)
        int t = ++tag;
        sys.addConstraintP2PSymmetric(lines[ln].p1, lines[ln].p2, points[p], t);
        k_raw(l, "midpoint", p + " at midpoint of " + ln +
              " (as P2PSymmetric(l.p1, l.p2, p))", t);
    }
    void k_midpoint_of_origin(const std::string& l, const std::string& ln) {
        // fixed origin at the midpoint of ln — native point-form symmetric
        // (slvs needed the AT_MIDPOINT derivation; planegcs has the primitive)
        int t = ++tag;
        sys.addConstraintP2PSymmetric(lines[ln].p1, lines[ln].p2, origin, t);
        k_raw(l, "midpoint", "fixed origin at midpoint of " + ln +
              " (derived point symmetry; as P2PSymmetric(l.p1, l.p2, origin))", t);
    }
    void k_proj_x(const std::string& l, const std::string& p, const std::string& q,
                  double v) {
        // signed X(p->q) = v  ==  q.x - p.x = v.
        // planegcs ConstraintDifference: error = param2 - param1 - difference
        // (Constraints.cpp ConstraintDifference::error), so param1 = p.x,
        // param2 = q.x. Signed like slvs PROJ distances.
        datum_of[l] = val(v);
        int t = ++tag;
        sys.addConstraintDifference(points[p].x, points[q].x, datum_of[l], t);
        k_raw(l, "distance_x", "X(" + p + "->" + q + ") = " + fmt(v) +
              " (as Difference(p.x, q.x))", t);
    }
    void k_proj_y(const std::string& l, const std::string& p, const std::string& q,
                  double v) {
        datum_of[l] = val(v);
        int t = ++tag;
        sys.addConstraintDifference(points[p].y, points[q].y, datum_of[l], t);
        k_raw(l, "distance_y", "Y(" + p + "->" + q + ") = " + fmt(v) +
              " (as Difference(p.y, q.y))", t);
    }

    // -- snapshots / solve protocol -------------------------------------------
    std::map<std::string, std::pair<double,double>> pos_snapshot() {
        std::map<std::string, std::pair<double,double>> out;
        for (auto& pr : points) out[pr.first] = {*pr.second.x, *pr.second.y};
        return out;
    }
    std::map<std::string, uint64_t> bits_snapshot() {
        std::map<std::string, uint64_t> out;
        for (auto& pr : points) {
            uint64_t bx, by; std::memcpy(&bx, pr.second.x, 8);
            std::memcpy(&by, pr.second.y, 8);
            out[pr.first + ":x"] = bx; out[pr.first + ":y"] = by;
        }
        return out;
    }
    static bool bits_equal(const std::map<std::string, uint64_t>& a,
                           const std::map<std::string, uint64_t>& b) { return a == b; }

    void declare_all() {
        GCS::VEC_pD params;
        for (auto& pr : points) { params.push_back(pr.second.x); params.push_back(pr.second.y); }
        for (auto& cr : circles) params.push_back(cr.second.rad);
        for (auto& ar : arcs) {
            params.push_back(ar.second.rad);
            params.push_back(ar.second.startAngle);
            params.push_back(ar.second.endAngle);
        }
        sys.declareUnknowns(params);   // assigns; idempotent (GCS.cpp)
    }

    struct SolveRec {
        std::string status;
        std::string chain;
        int dof = -1;
        std::vector<std::string> conflicting, redundant, partially_redundant;
        bool wrote_back = false;
    };

    std::string tag_label(int x) {
        return tag_to_label.count(x) ? tag_to_label[x] : ("tag" + std::to_string(x));
    }
    SolveRec solve_with_diagnosis() {
        SolveRec rec;
        declare_all();
        sys.initSolution(GCS::DogLeg);   // runs diagnose internally (GCS.cpp:1731-37)
        rec.dof = sys.dofsNumber();
        GCS::VEC_I t;
        sys.getConflicting(t);
        for (int x : t) rec.conflicting.push_back(tag_label(x));
        sys.getRedundant(t);
        for (int x : t) rec.redundant.push_back(tag_label(x));
        sys.getPartiallyRedundant(t);
        for (int x : t) rec.partially_redundant.push_back(tag_label(x));
        // FreeCAD's FULL fallback chain (Sketch.cpp:4795-4905): the configured
        // default (DogLeg), then LM and BFGS, then the LAST RESORT — the SQP
        // augmented system: every parameter pinned to its current value via
        // temporary equality constraints (tag = DefaultTemporaryConstraint),
        // re-init, solve the two-subsystem SQP form. This is the step that
        // makes FreeCAD solve redundant sketches gracefully.
        struct AlgN { GCS::Algorithm a; const char* n; };
        AlgN chain[] = {{GCS::DogLeg, "DogLeg"}, {GCS::BFGS, "BFGS"},
                        {GCS::LevenbergMarquardt, "LevenbergMarquardt"}};
        int ret = -1; std::string via;
        for (auto& an : chain) {
            ret = sys.solve(true, an.a);
            rec.chain += std::string(an.n) + "=" + std::to_string(ret) + ";";
            if (ret == GCS::Success) { via = an.n; break; }
        }
        if (ret != GCS::Success) {
            // step 4: SQP augmented system (Sketch.cpp:4862-4875)
            std::deque<double> init_params;   // stable storage for the pin targets
            GCS::VEC_pD all;
            for (auto& pr : points) { all.push_back(pr.second.x); all.push_back(pr.second.y); }
            for (auto& cr : circles) all.push_back(cr.second.rad);
            for (auto& ar : arcs) {
                all.push_back(ar.second.rad);
                all.push_back(ar.second.startAngle);
                all.push_back(ar.second.endAngle);
            }
            for (double* p : all) { init_params.push_back(*p); }
            for (size_t i = 0; i < all.size(); i++) {
                sys.addConstraintEqual(all[i], &init_params[i],
                                       GCS::DefaultTemporaryConstraint);
            }
            sys.initSolution(GCS::DogLeg);
            ret = sys.solve(true, GCS::DogLeg);
            rec.chain += "SQP-augmented=" + std::to_string(ret) + ";";
            if (ret == GCS::Success) via = "SQP-augmented";
            sys.clearByTag(GCS::DefaultTemporaryConstraint);
        }
        if (ret == GCS::Success) { sys.applySolution(); rec.wrote_back = true; rec.status = "solved"; }
        else rec.status = "failed";
        rec.chain += via.empty() ? "none-success" : "via=" + via;
        return rec;
    }

    double radius(const std::string& l) { return *radius_of[l]; }
    std::pair<double,double> pos(const std::string& l) const {
        return {*points.at(l).x, *points.at(l).y};
    }

    uint64_t geometry_digest() {
        std::vector<uint8_t> buf;
        std::map<std::string, size_t> idx;
        for (size_t i = 0; i < order.size(); i++) idx[order[i]] = i;
        for (auto& l : order) {
            auto p = points[l];
            buf.insert(buf.end(), l.begin(), l.end());
            f64buf(buf, *p.x); f64buf(buf, *p.y);
        }
        for (auto& cr : curve_kind) {
            const std::string& l = cr.first;
            buf.insert(buf.end(), l.begin(), l.end());
            std::istringstream iss(c_top[l]);
            if (cr.second == 0) {
                std::string a, b; iss >> a >> b;
                buf.push_back('L'); u64buf(buf, idx[a]); u64buf(buf, idx[b]);
            } else if (cr.second == 1) {
                std::string c; iss >> c;
                buf.push_back('C'); u64buf(buf, idx[c]); f64buf(buf, *radius_of[l]);
            } else {
                std::string c, s, e; iss >> c >> s >> e;
                buf.push_back('A'); u64buf(buf, idx[c]); u64buf(buf, idx[s]);
                u64buf(buf, idx[e]);
            }
        }
        return fnv1a64(buf.data(), buf.size());
    }
};

// ------------------------------------------------------------- case builders
// (transcribed from m3-eval gen_solver_cases.py:357-501,1174-1248 — seeds and
//  constraint parameters byte-faithful; provenance per case)

struct Seed { std::map<std::string, std::pair<double,double>> m; };

static Seed triangle_seed() {
    return {{{"A", {2.0, 1.0}}, {"B", {45.0, 3.0}}, {"C", {22.0, 35.0}}}};
}
static void build_triangle(CaseBuilder& b, Seed* seed, double d1, double d2) {
    Seed s = triangle_seed();
    if (seed) s = *seed;
    for (auto& kv : s.m) b.pt(kv.first, kv.second.first, kv.second.second);
    b.line("l1", "A", "B");
    b.line("l2", "B", "C");
    b.line("l3", "C", "A");
    b.k_coincident_origin("k1", "A");
    b.k_horizontal("k2", "l1");
    b.k_distance("d1", "A", "B", d1);
    b.k_distance("d2", "B", "C", d2);
    b.k_angle("d3", "l1", "l3", 60.0, true);
}
static Seed solved_seed(const CaseBuilder& b) {
    Seed s;
    for (auto& l : b.order) s.m[l] = b.pos(l);
    return s;
}
static Seed perturb(const CaseBuilder& b, double delta = 0.5) {
    // m3-eval perturb(): index over the SOLVED insertion order
    Seed s;
    for (size_t i = 0; i < b.order.size(); i++) {
        auto& l = b.order[i];
        auto xy = b.pos(l);
        s.m[l] = {xy.first + delta * ((i % 2 == 0) ? 1.0 : -0.7) + 0.13 * (double)i,
                  xy.second - delta * ((i % 3 == 0) ? 0.8 : -0.6) - 0.07 * (double)i};
    }
    return s;
}

static void build_bare_line(CaseBuilder& b) {
    b.pt("l1.start", 0.0, 0.0);
    b.pt("l1.end", 10.0, 1.0);
    b.line("l1", "l1.start", "l1.end");
}
static void build_bare_circle(CaseBuilder& b) {
    b.pt("c1.center", 3.0, 4.0);
    b.circle("c1", "c1.center", 5.0);
}
static void build_bare_arc(CaseBuilder& b) {
    b.pt("a1.center", 1.0, 2.0);
    b.pt("a1.start", 6.0, 2.0);
    b.pt("a1.end", 1.0, 7.0);
    b.arc("a1", "a1.center", "a1.start", "a1.end");
}
static void build_circle_origin_radius(CaseBuilder& b, double sx, double sy,
                                       double diameter) {
    b.pt("c1.center", sx, sy);
    b.circle("c1", "c1.center", 4.7);
    b.k_coincident_origin("k1", "c1.center");
    b.k_diameter("d1", "c1", diameter);
}
static void build_l_bracket(CaseBuilder& b, bool with_dims, Seed* seed) {
    std::vector<std::pair<double,double>> rough = {
        {1.0, 1.0}, {55.0, -2.0}, {57.0, 9.0}, {10.0, 7.0}, {9.0, 45.0}, {-1.0, 38.0}};
    if (seed) {
        for (auto& kv : seed->m) b.pt(kv.first, kv.second.first, kv.second.second);
    } else {
        for (int i = 0; i < 6; i++) b.pt("p" + std::to_string(i), rough[i].first,
                                         rough[i].second);
    }
    for (int i = 0; i < 6; i++)
        b.line("l" + std::to_string(i + 1), "p" + std::to_string(i),
               "p" + std::to_string((i + 1) % 6));
    for (int i : {1, 3, 5}) b.k_horizontal("k" + std::to_string(i),
                                           "l" + std::to_string(i));
    for (int i : {2, 4, 6}) b.k_vertical("k" + std::to_string(i),
                                         "l" + std::to_string(i));
    b.k_coincident_origin("k7", "p0");
    if (with_dims) {
        b.k_proj_x("d1", "p0", "p1", 60.0);
        b.k_proj_y("d2", "p1", "p2", 8.0);
        b.k_proj_y("d3", "p5", "p0", -40.0);
        b.k_proj_x("d4", "p4", "p5", -8.0);
    }
}
static void build_slot(CaseBuilder& b, Seed* seed) {
    Seed s = {{{"a1c", {1.0, 1.0}}, {"a1s", {1.0, 7.0}}, {"a1e", {1.0, -5.0}},
                {"a2c", {37.0, 2.0}}, {"a2s", {37.0, -3.0}}, {"a2e", {37.0, 7.0}}}};
    if (seed) s = *seed;
    for (auto& kv : s.m) b.pt(kv.first, kv.second.first, kv.second.second);
    b.arc("a1", "a1c", "a1s", "a1e");
    b.arc("a2", "a2c", "a2s", "a2e");
    b.line("l1", "a1e", "a2s");
    b.line("l2", "a2e", "a1s");
    b.k_coincident_origin("k1", "a1c");
    b.k_tangent_arc_line("k2", "a1", "l1");
    b.k_tangent_arc_line("k3", "a2", "l1");
    b.k_tangent_arc_line("k4", "a2", "l2");
    b.k_tangent_arc_line("k5", "a1", "l2");
    b.k_equal("k6", "a1", "a2");
    b.k_horizontal("k7", "l1");
    b.k_diameter("d1", "a1", 12.0);
    b.k_proj_x("d2", "a1c", "a2c", 40.0);
}
static void build_line_horizontal_only(CaseBuilder& b) {
    b.pt("l1.start", 0.0, 0.0);
    b.pt("l1.end", 10.0, 1.0);
    b.line("l1", "l1.start", "l1.end");
    b.k_horizontal("k1", "l1");
}
static void build_circle_radius_only(CaseBuilder& b, double sx, double sy,
                                     double diameter) {
    b.pt("c1.center", sx, sy);
    b.circle("c1", "c1.center", 4.7);
    b.k_diameter("d1", "c1", diameter);
}
static void build_rect(CaseBuilder& b, bool duplicate_vertical) {
    std::vector<std::pair<double,double>> rough = {
        {0.3, -0.2}, {38.0, 1.0}, {41.0, 29.0}, {-1.0, 31.0}};
    for (int i = 0; i < 4; i++) b.pt("p" + std::to_string(i), rough[i].first,
                                     rough[i].second);
    for (int i = 0; i < 4; i++)
        b.line("l" + std::to_string(i), "p" + std::to_string(i),
               "p" + std::to_string((i + 1) % 4));
    b.k_horizontal("k1", "l0");
    b.k_horizontal("k2", "l2");
    b.k_vertical("k3", "l1");
    b.k_vertical("k4", "l3");
    b.k_coincident_origin("k5", "p0");
    b.k_length("d1", "l0", 40.0);
    b.k_length("d2", "l1", 30.0);
    if (duplicate_vertical) b.k_vertical("k6", "l1");
}
static void build_conflicting_distances(CaseBuilder& b) {
    b.pt("l1.start", 0.0, 0.0);
    b.pt("l1.end", 10.0, 0.0);
    b.line("l1", "l1.start", "l1.end");
    b.k_horizontal("k1", "l1");
    b.k_distance("d1", "l1.start", "l1.end", 10.0);
    b.k_distance("d2", "l1.start", "l1.end", 20.0);
}
static void build_coincident_plus_distance(CaseBuilder& b) {
    b.pt("p1", 1.0, 1.0);
    b.pt("p2", 6.0, 5.0);
    b.k_coincident("k1", "p1", "p2");
    b.k_distance("d1", "p1", "p2", 5.0);
}
static void build_fixed_line_A(CaseBuilder& b) {
    b.pt("A0", 0.0, 0.0);
    b.pt("A1", 10.0, 0.05);
    b.line("lA", "A0", "A1");
    b.k_coincident_origin("kA1", "A0");
    b.k_horizontal("kA2", "lA");
    b.k_proj_x("kA3", "A0", "A1", 10.0);
}
static void build_parallel_offset(CaseBuilder& b) {
    build_fixed_line_A(b);
    b.pt("B0", 0.1, 3.2);
    b.pt("B1", 9.1, 4.0);
    b.line("lB", "B0", "B1");
    b.k_parallel("k1", "lB", "lA");
    b.k_proj_y("k2", "A0", "B0", 3.0);
    b.k_proj_x("k3", "A0", "B0", 0.0);
    b.k_length("d1", "lB", 9.0);
}
static void build_perpendicular_pair(CaseBuilder& b) {
    build_fixed_line_A(b);
    b.pt("B0", 5.2, 0.3);
    b.pt("B1", 5.0, 1.2);
    b.line("lB", "B0", "B1");
    b.k_proj_x("k1", "A0", "B0", 5.0);
    b.k_proj_y("k2", "A0", "B0", 0.0);
    b.k_perpendicular("k3", "lB", "lA");
    b.k_length("d1", "lB", 4.0);
}
static void build_diameter_dim(CaseBuilder& b) {
    b.pt("c.center", 2.0, 3.0);
    b.circle("c", "c.center", 4.7);
    b.k_coincident_origin("k1", "c.center");
    b.k_diameter("d1", "c", 10.0);
}
static void build_symmetric_points(CaseBuilder& b) {
    b.pt("p", 2.0, 3.0);
    b.pt("q", -1.0, -4.0);
    b.line("lM", "p", "q");
    b.k_midpoint_of_origin("k1", "lM");
    b.k_proj_x("d1", "p", "q", -4.0);
    b.k_proj_y("d2", "p", "q", -6.0);
}
static void build_midpoint_case(CaseBuilder& b) {
    b.pt("l0", 0.0, 0.0);
    b.pt("l1", 10.0, 2.0);
    b.line("ll", "l0", "l1");
    b.pt("m", 5.2, 0.9);
    b.k_coincident_origin("k1", "l0");
    b.k_horizontal("k2", "ll");
    b.k_proj_x("d1", "l0", "l1", 10.0);
    b.k_midpoint("k3", "m", "ll");
}
static void build_concentric_circles(CaseBuilder& b) {
    b.pt("c1.center", 2.0, 3.0);
    b.circle("c1", "c1.center", 4.7);
    b.pt("c2.center", 7.0, 8.0);
    b.circle("c2", "c2.center", 5.1);
    b.k_coincident_origin("k1", "c1.center");
    b.k_coincident("k2", "c2.center", "c1.center");
    b.k_diameter("d1", "c1", 6.0);
    b.k_diameter("d2", "c2", 10.0);
}
static void build_staircase(CaseBuilder& b, int n,
                            std::map<int, std::pair<double,double>>* seed,
                            double driving) {
    if (seed) {
        for (auto& kv : *seed) b.pt("p" + std::to_string(kv.first),
                                    kv.second.first, kv.second.second);
    } else {
        for (int i = 0; i <= n; i++) {
            double ex = std::ceil(i / 2.0), ey = std::floor(i / 2.0);
            b.pt("p" + std::to_string(i),
                 ex + 0.01 * (((i % 7) - 3) / 3.0), ey + 0.01 * (((i % 5) - 2) / 2.0));
        }
    }
    for (int i = 0; i < n; i++)
        b.line("l" + std::to_string(i), "p" + std::to_string(i),
               "p" + std::to_string(i + 1));
    b.k_coincident_origin("k0", "p0");
    for (int i = 0; i < n; i++) {
        if (i % 2 == 0) b.k_horizontal("kh" + std::to_string(i), "l" + std::to_string(i));
        else b.k_vertical("kv" + std::to_string(i), "l" + std::to_string(i));
    }
    for (int i = 1; i < n; i++)
        b.k_equal("ke" + std::to_string(i), "l" + std::to_string(i), "l0");
    b.k_length("dDriving", "l0", driving);
}

// ------------------------------------------------------------- record helpers

static void record_solve(JOut& j, const std::string& key,
                        const CaseBuilder::SolveRec& s) {
    j.key(key); j.obj();
    j.kstr("status", s.status);
    j.kstr("chain", s.chain);
    j.ki("dof", s.dof);
    j.key("conflicting"); j.arr();
    for (auto& c : s.conflicting) j.str(c);
    j.endarr();
    j.key("redundant"); j.arr();
    for (auto& c : s.redundant) j.str(c);
    j.endarr();
    j.key("partially_redundant"); j.arr();
    for (auto& c : s.partially_redundant) j.str(c);
    j.endarr();
    j.kb("wrote_back", s.wrote_back);
    j.endobj();
}

static void record_geometry(JOut& j, CaseBuilder& b) {
    j.key("geometry"); j.obj();
    j.key("points"); j.arr();
    for (auto& l : b.order) {
        j.obj(); j.kstr("id", l);
        auto p = b.pos(l);
        j.key("pos"); j.arr(); j.num(p.first); j.num(p.second); j.endarr();
        j.endobj();
    }
    j.endarr();
    j.key("curves"); j.arr();
    for (auto& cr : b.curve_kind) {
        const std::string& l = cr.first;
        j.obj(); j.kstr("id", l);
        std::istringstream iss(b.c_top[l]);
        if (cr.second == 0) {
            std::string a, bb; iss >> a >> bb;
            j.kstr("kind", "line");
            auto p1 = b.pos(a), p2 = b.pos(bb);
            j.key("p_a"); j.arr(); j.num(p1.first); j.num(p1.second); j.endarr();
            j.key("p_b"); j.arr(); j.num(p2.first); j.num(p2.second); j.endarr();
        } else if (cr.second == 1) {
            std::string c; iss >> c;
            j.kstr("kind", "circle");
            auto p = b.pos(c);
            j.key("p_center"); j.arr(); j.num(p.first); j.num(p.second); j.endarr();
            j.knum("radius", b.radius(l));
        } else {
            std::string c, s, e; iss >> c >> s >> e;
            j.kstr("kind", "arc");
            auto pc = b.pos(c), ps = b.pos(s), pe = b.pos(e);
            j.key("p_center"); j.arr(); j.num(pc.first); j.num(pc.second); j.endarr();
            j.key("p_start"); j.arr(); j.num(ps.first); j.num(ps.second); j.endarr();
            j.key("p_end"); j.arr(); j.num(pe.first); j.num(pe.second); j.endarr();
        }
        j.endobj();
    }
    j.endarr();
    j.endobj();
}

static void record_inputs(JOut& j, CaseBuilder& b) {
    j.key("inputs"); j.obj();
    j.key("points"); j.arr();
    for (auto& l : b.order) { j.obj(); j.kstr("id", l); j.endobj(); }
    j.endarr();
    j.key("curves"); j.arr();
    for (auto& cr : b.curve_kind) {
        j.obj(); j.kstr("id", cr.first);
        j.kstr("kind", cr.second == 0 ? "line" : (cr.second == 1 ? "circle" : "arc"));
        j.endobj();
    }
    j.endarr();
    j.key("constraints"); j.arr();
    for (auto& c : b.cons) {
        j.obj(); j.kstr("label", c.label); j.kstr("kind", c.kind);
        j.kstr("detail", c.detail); j.endobj();
    }
    j.endarr();
    j.endobj();
}

static void record_bits(JOut& j, const std::string& key,
                        const std::map<std::string, uint64_t>& bits) {
    j.key(key); j.obj();
    for (auto& kv : bits) { j.key(kv.first); j.str(hex64(kv.second)); }
    j.endobj();
}

static void record_positions(JOut& j, const std::string& key, CaseBuilder& b) {
    j.key(key); j.obj();
    for (auto& l : b.order) {
        auto p = b.pos(l);
        j.key(l); j.arr(); j.num(p.first); j.num(p.second); j.endarr();
    }
    j.endobj();
}

// ------------------------------------------------------------- corpus mode

static void emit_case_head(JOut& j, const char* id, const char* group,
                           const char* desc) {
    j.obj();
    j.kstr("id", id);
    j.kstr("group", group);
    j.kstr("description", desc);
}

static void run_simple_case(JOut& j, const char* id, const char* group,
                            const char* desc, void (*build)(CaseBuilder&)) {
    emit_case_head(j, id, group, desc);
    CaseBuilder b;
    build(b);
    auto before = b.bits_snapshot();
    auto s = b.solve_with_diagnosis();
    record_solve(j, "solve", s);
    record_geometry(j, b);
    record_inputs(j, b);
    record_bits(j, "point_bits", b.bits_snapshot());
    j.kb("bits_equal_input_after_solve", CaseBuilder::bits_equal(before, b.bits_snapshot()));
    j.endobj();
}

static void emit_perturbed_resolve(JOut& j, CaseBuilder& b,
                                   void (*rebuild)(CaseBuilder&, Seed*)) {
    Seed p = perturb(b, 0.5);
    CaseBuilder b2;
    rebuild(b2, &p);
    auto s2 = b2.solve_with_diagnosis();
    record_solve(j, "perturbed_resolve", s2);
    record_positions(j, "perturbed_resolve_geometry", b2);
}

int run_corpus() {
    JOut j;
    j.obj();
    j.kstr("mode", "corpus");
    j.kstr("driver", "planegcs-h2h (FreeCAD 1.1.4 pin 4fd3bf3; eigen 3.4.0)");
    j.kstr("solve_protocol", "declareUnknowns -> initSolution(DogLeg) [diagnose "
           "inside] -> chain DogLeg/BFGS/LM -> applySolution only on Success "
           "(FreeCAD Sketch.cpp:4795-4830)");
    j.key("cases"); j.arr();

    run_simple_case(j, "bare_line", "mapping",
                    "single line, no constraints: unknowns = 4 point coordinates",
                    build_bare_line);
    run_simple_case(j, "bare_circle", "mapping",
                    "single circle, no constraints: unknowns = centre (2) + radius (1)",
                    build_bare_circle);
    run_simple_case(j, "bare_arc", "mapping",
                    "single arc, no constraints: 9 params (3 points + rad + 2 angles) "
                    "minus 4 ArcRules equations = 5 DOF",
                    build_bare_arc);

    {   // circle_origin_radius (+ perturbation probe)
        emit_case_head(j, "circle_origin_radius", "fully_constrained",
                       "circle: centre coincident with the fixed origin + radius dimension");
        CaseBuilder b;
        build_circle_origin_radius(b, 2.0, 3.0, 10.0);
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        emit_perturbed_resolve(j, b, [](CaseBuilder& b2, Seed* p) {
            build_circle_origin_radius(b2, p->m["c1.center"].first,
                                       p->m["c1.center"].second, 10.0);
        });
        j.endobj();
    }

    {   // triangle_constrained (+ perturbation probe)
        double t = 25.0 + 5.0 * std::sqrt(6.0);
        emit_case_head(j, "triangle_constrained", "fully_constrained",
                       "rough triangle; A on origin, l1 horizontal, |AB|=50, |BC|=45, "
                       "angle(l1,l3)=60deg interior at A");
        CaseBuilder b;
        build_triangle(b, nullptr, 50.0, 45.0);
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        emit_perturbed_resolve(j, b, [](CaseBuilder& b2, Seed* p) {
            build_triangle(b2, p, 50.0, 45.0);
        });
        j.knum("expected_c_x_analytic", t * std::cos(kPi / 3.0));
        j.knum("expected_c_y_analytic", t * std::sin(kPi / 3.0));
        j.endobj();
    }

    {   // triangle_value_edit — rebuild path (slvs parity) + mutation path
        double t = (40.0 + std::sqrt(3300.0)) / 2.0;
        emit_case_head(j, "triangle_value_edit", "value_edit",
                       "triangle solved, then |AB| edited 50->40 and re-solved "
                       "(rebuild path = slvs parity; mutation path = planegcs-native)");
        CaseBuilder b1;
        build_triangle(b1, nullptr, 50.0, 45.0);
        auto s1 = b1.solve_with_diagnosis();
        record_solve(j, "first_solve", s1);
        auto a_bits = b1.bits_snapshot();
        Seed solved = solved_seed(b1);
        CaseBuilder b2;                       // rebuild path
        build_triangle(b2, &solved, 40.0, 45.0);
        auto s2 = b2.solve_with_diagnosis();
        record_solve(j, "solve_rebuild_path", s2);
        record_geometry(j, b2);
        record_inputs(j, b2);
        record_bits(j, "a_bits_before", a_bits);
        record_bits(j, "a_bits_after_rebuild", b2.bits_snapshot());
        {   // mutation path: same System, set d1's datum double, re-solve
            CaseBuilder b3;
            build_triangle(b3, &solved, 50.0, 45.0);
            *b3.datum_of["d1"] = 40.0;
            auto s3 = b3.solve_with_diagnosis();
            record_solve(j, "solve_mutation_path", s3);
            record_positions(j, "mutation_geometry", b3);
            {   // warm re-solve: solve() again on the solved system
                auto s4 = b3.solve_with_diagnosis();
                record_solve(j, "warm_resolve_same_system", s4);
            }
        }
        j.knum("expected_c_x_analytic", t * std::cos(kPi / 3.0));
        j.knum("expected_c_y_analytic", t * std::sin(kPi / 3.0));
        j.endobj();
    }

    {   // l_bracket_constrained + l_bracket_no_dims
        emit_case_head(j, "l_bracket_constrained", "fully_constrained",
                       "6-line L outline, H/V constraints, corner on origin, "
                       "4 dimensions (60/8/40/8)");
        CaseBuilder b;
        build_l_bracket(b, true, nullptr);
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        emit_perturbed_resolve(j, b, [](CaseBuilder& b2, Seed* p) {
            build_l_bracket(b2, true, p);
        });
        j.key("expected_corners"); j.arr();
        double expc[6][2] = {{0,0},{60,0},{60,8},{8,8},{8,40},{0,40}};
        for (auto& e : expc) { j.arr(); j.num(e[0]); j.num(e[1]); j.endarr(); }
        j.endarr();
        j.endobj();

        emit_case_head(j, "l_bracket_no_dims", "underconstrained",
                       "6-line L outline, H/V constraints, corner on origin, no dimensions");
        CaseBuilder b0;
        build_l_bracket(b0, false, nullptr);
        auto before = b0.bits_snapshot();
        auto s0 = b0.solve_with_diagnosis();
        record_solve(j, "solve", s0);
        record_geometry(j, b0);
        record_inputs(j, b0);
        record_bits(j, "input_bits", before);
        record_bits(j, "after_bits", b0.bits_snapshot());
        j.kb("bits_equal_input_after_solve",
             CaseBuilder::bits_equal(before, b0.bits_snapshot()));
        {   // perturbation stability record (recorded, no pass/fail)
            Seed solved = solved_seed(b0);
            Seed p = perturb(b0, 0.3);
            CaseBuilder b2;
            build_l_bracket(b2, false, &p);
            auto s2 = b2.solve_with_diagnosis();
            record_solve(j, "perturbed_resolve_recorded", s2);
            double drift = 0;
            for (auto& l : b2.order) {
                auto q1 = solved.m[l], q2 = b2.pos(l);
                drift = std::max(drift, std::hypot(q1.first - q2.first,
                                                   q1.second - q2.second));
            }
            j.knum("max_corner_drift_after_perturbation", drift);
        }
        j.endobj();
    }

    {   // slot_constrained
        emit_case_head(j, "slot_constrained", "fully_constrained",
                       "obround: 2 arcs + 2 lines sharing end points, 4 endpoint "
                       "tangencies, equal radii, horizontal line, a1 centre on origin, "
                       "radius 6, centre distance 40");
        CaseBuilder b;
        build_slot(b, nullptr);
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        emit_perturbed_resolve(j, b, [](CaseBuilder& b2, Seed* p) {
            build_slot(b2, p);
        });
        j.endobj();
    }

    run_simple_case(j, "line_horizontal_only", "underconstrained",
                    "single line, horizontal only: 3 DOF remain",
                    build_line_horizontal_only);

    {   // circle_radius_only_edit — rebuild + mutation paths
        emit_case_head(j, "circle_radius_only_edit", "underconstrained",
                       "circle with only a radius dimension (centre free); edit "
                       "radius 5->8 (rebuild path = slvs parity; mutation = native)");
        CaseBuilder b1;
        build_circle_radius_only(b1, 3.0, 4.0, 10.0);
        auto s1 = b1.solve_with_diagnosis();
        record_solve(j, "solve_radius_only", s1);
        auto center_before = b1.bits_snapshot();
        auto center_solved = b1.pos("c1.center");
        j.knum("radius_first_solve", b1.radius("c1"));
        CaseBuilder b2;   // rebuild path
        build_circle_radius_only(b2, center_solved.first, center_solved.second, 16.0);
        auto s2 = b2.solve_with_diagnosis();
        record_solve(j, "solve_rebuild_path", s2);
        record_geometry(j, b2);
        record_inputs(j, b2);
        j.knum("radius_after_edit_rebuild", b2.radius("c1"));
        {   // mutation path
            CaseBuilder b3;
            build_circle_radius_only(b3, center_solved.first, center_solved.second, 10.0);
            *b3.datum_of["d1"] = 16.0;
            auto s3 = b3.solve_with_diagnosis();
            record_solve(j, "solve_mutation_path", s3);
            record_bits(j, "center_bits_mutation_path", b3.bits_snapshot());
            j.knum("radius_after_edit_mutation", b3.radius("c1"));
        }
        record_bits(j, "center_bits_before", center_before);
        record_bits(j, "center_bits_after_rebuild", b2.bits_snapshot());
        j.endobj();
    }

    {   // rect_redundant_duplicate_dimension — THE case that rejected slvs
        emit_case_head(j, "rect_redundant_duplicate_dimension", "redundancy",
                       "fully constrained rectangle + duplicate Vertical on the same "
                       "side (W1 oracle: solved, dof 0, duplicate listed redundant, "
                       "corners exact — the expectation slvs FAILED)");
        CaseBuilder b;
        build_rect(b, true);
        auto before = b.bits_snapshot();
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        record_bits(j, "input_bits", before);
        record_bits(j, "after_bits", b.bits_snapshot());
        j.kb("bits_equal_input_after_solve", CaseBuilder::bits_equal(before, b.bits_snapshot()));
        j.endobj();
    }

    {   // conflicting_distances
        emit_case_head(j, "conflicting_distances", "conflict",
                       "the same pair of points given two different distances (10 and 20)");
        CaseBuilder b;
        build_conflicting_distances(b);
        auto before = b.bits_snapshot();
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        record_bits(j, "input_bits", before);
        record_bits(j, "after_bits", b.bits_snapshot());
        j.kb("bits_equal_input_after_solve", CaseBuilder::bits_equal(before, b.bits_snapshot()));
        j.endobj();
    }

    {   // coincident_plus_distance
        emit_case_head(j, "coincident_plus_distance", "failure",
                       "genuinely unsolvable: two points forced coincident AND "
                       "dimensioned 5 apart");
        CaseBuilder b;
        build_coincident_plus_distance(b);
        auto before = b.bits_snapshot();
        auto s = b.solve_with_diagnosis();
        record_solve(j, "solve", s);
        record_geometry(j, b);
        record_inputs(j, b);
        record_bits(j, "input_bits", before);
        record_bits(j, "after_bits", b.bits_snapshot());
        j.kb("bits_equal_input_after_solve", CaseBuilder::bits_equal(before, b.bits_snapshot()));
        j.endobj();
    }

    {   // triangle_edit_unsolvable — rebuild + mutation paths
        emit_case_head(j, "triangle_edit_unsolvable", "failure",
                       "driving dimension edited to a value with no real solution "
                       "(d1=55; t^2-55t+1000 discriminant<0)");
        CaseBuilder b1;
        build_triangle(b1, nullptr, 50.0, 45.0);
        auto s1 = b1.solve_with_diagnosis();
        record_solve(j, "first_solve", s1);
        auto solved_bits = b1.bits_snapshot();
        Seed solved = solved_seed(b1);
        CaseBuilder b2;   // rebuild path
        build_triangle(b2, &solved, 55.0, 45.0);
        auto s2 = b2.solve_with_diagnosis();
        record_solve(j, "solve_rebuild_path", s2);
        record_bits(j, "solved_bits_before", solved_bits);
        record_bits(j, "bits_after_rebuild", b2.bits_snapshot());
        j.kb("rebuild_restores_solved_bits_bitwise",
             CaseBuilder::bits_equal(solved_bits, b2.bits_snapshot()));
        record_geometry(j, b2);
        record_inputs(j, b2);
        {   // mutation path
            CaseBuilder b3;
            build_triangle(b3, &solved, 50.0, 45.0);
            auto bits3 = b3.bits_snapshot();
            *b3.datum_of["d1"] = 55.0;
            auto s3 = b3.solve_with_diagnosis();
            record_solve(j, "solve_mutation_path", s3);
            record_bits(j, "bits_after_mutation", b3.bits_snapshot());
            j.kb("mutation_restores_bits_bitwise",
                 CaseBuilder::bits_equal(bits3, b3.bits_snapshot()));
        }
        j.endobj();
    }

    {   // determinism_inprocess_5x
        emit_case_head(j, "determinism_inprocess_5x", "determinism",
                       "the same constrained triangle built and solved 5 times in one "
                       "process");
        j.key("runs"); j.arr();
        std::vector<std::string> digests;
        std::vector<std::map<std::string, uint64_t>> allbits;
        std::vector<std::pair<int,int>> statuses;
        for (int r = 0; r < 5; r++) {
            CaseBuilder b;
            build_triangle(b, nullptr, 50.0, 45.0);
            auto s = b.solve_with_diagnosis();
            digests.push_back(hex64(b.geometry_digest()));
            allbits.push_back(b.bits_snapshot());
            statuses.push_back({s.status == "solved" ? 1 : 0, s.dof});
            j.obj();
            j.kstr("digest", digests.back());
            j.kstr("status", s.status); j.ki("dof", s.dof);
            j.endobj();
        }
        j.endarr();
        j.kb("bitwise_identical", std::equal(allbits.begin() + 1, allbits.end(),
                                             allbits.begin()));
        j.kb("digests_identical", std::equal(digests.begin() + 1, digests.end(),
                                             digests.begin()));
        j.kb("statuses_identical", std::equal(statuses.begin() + 1, statuses.end(),
                                              statuses.begin()));
        j.endobj();
    }

    // coverage probes
    run_simple_case(j, "parallel_offset", "coverage_probes",
                    "line B parallel to a fully-constrained horizontal line A, "
                    "offset 3 in y, length 9",
                    build_parallel_offset);
    run_simple_case(j, "perpendicular_pair", "coverage_probes",
                    "line B through (5,0) perpendicular to a fully-constrained "
                    "horizontal A, length 4",
                    build_perpendicular_pair);
    run_simple_case(j, "diameter_dim", "coverage_probes",
                    "circle on origin with diameter=10 -> r=5",
                    build_diameter_dim);
    run_simple_case(j, "symmetric_points", "coverage_probes",
                    "two points symmetric about the origin, p fully determined",
                    build_symmetric_points);
    run_simple_case(j, "midpoint_case", "coverage_probes",
                    "point m at the midpoint of a fully-constrained horizontal line",
                    build_midpoint_case);
    run_simple_case(j, "concentric_circles", "coverage_probes",
                    "two concentric circles, radii 3 and 5",
                    build_concentric_circles);

    j.endarr();   // cases
    j.endobj();   // root
    std::fputs(j.s.c_str(), stdout);
    std::fputc('\n', stdout);
    return 0;
}

// ------------------------------------------------------------- hash + staircase

static std::string canonical_hash_line() {
    // canonical 3: triangle, L-bracket(with dims), slot (m3-eval protocol)
    uint64_t d[3] = {0, 0, 0};
    {
        CaseBuilder b; build_triangle(b, nullptr, 50.0, 45.0);
        auto s = b.solve_with_diagnosis();
        if (s.status == "solved") d[0] = b.geometry_digest();
    }
    {
        CaseBuilder b; build_l_bracket(b, true, nullptr);
        auto s = b.solve_with_diagnosis();
        if (s.status == "solved") d[1] = b.geometry_digest();
    }
    {
        CaseBuilder b; build_slot(b, nullptr);
        auto s = b.solve_with_diagnosis();
        if (s.status == "solved") d[2] = b.geometry_digest();
    }
    return "PLANEGCS_HASH " + hex64(d[0]) + " " + hex64(d[1]) + " " + hex64(d[2])
           + " ok=" + std::to_string((d[0] && d[1] && d[2]) ? 1 : 0);
}

static double max_len_err(CaseBuilder& b, double target) {
    double e = 0;
    for (auto& cr : b.curve_kind) {
        if (cr.second != 0) continue;
        std::istringstream iss(b.c_top[cr.first]);
        std::string pa, pb; iss >> pa >> pb;
        auto p1 = b.pos(pa), p2 = b.pos(pb);
        e = std::max(e, std::abs(std::hypot(p2.first - p1.first,
                                            p2.second - p1.second) - target));
    }
    return e;
}

int run_staircase(int n, bool do_edit) {
    using Steady = std::chrono::steady_clock;
    JOut j; j.obj();
    j.ki("n", n);
    auto t0 = Steady::now();
    CaseBuilder b;
    build_staircase(b, n, nullptr, 1.0);
    double build_s = std::chrono::duration<double>(Steady::now() - t0).count();
    t0 = Steady::now();
    auto s = b.solve_with_diagnosis();
    double solve_s = std::chrono::duration<double>(Steady::now() - t0).count();
    j.knum("build_s", build_s);
    j.knum("solve_s", solve_s);
    j.kstr("status", s.status); j.ki("dof", s.dof);
    j.ki("constraint_count", (int)b.cons.size());
    j.knum("max_len_err", max_len_err(b, 1.0));
    if (do_edit) {
        // solved seed -> rebuild path (driving 1.5)
        std::map<int, std::pair<double,double>> solved;
        for (int i = 0; i <= n; i++) solved[i] = b.pos("p" + std::to_string(i));
        auto t1 = Steady::now();
        CaseBuilder b2;
        build_staircase(b2, n, &solved, 1.5);
        double rebuild_s = std::chrono::duration<double>(Steady::now() - t1).count();
        t1 = Steady::now();
        auto s2 = b2.solve_with_diagnosis();
        double edit_solve_s = std::chrono::duration<double>(Steady::now() - t1).count();
        j.key("edit"); j.obj();
        j.knum("new_driving", 1.5);
        j.knum("rebuild_s", rebuild_s);
        j.knum("solve_after_edit_s", edit_solve_s);
        j.kstr("status", s2.status); j.ki("dof", s2.dof);
        j.knum("max_len_err", max_len_err(b2, 1.5));
        j.endobj();
        // mutation path on the ORIGINAL system: set the driving datum, re-solve
        auto t2 = Steady::now();
        *b.datum_of["dDriving"] = 1.5;
        auto s3 = b.solve_with_diagnosis();
        double mut_solve_s = std::chrono::duration<double>(Steady::now() - t2).count();
        j.key("edit_mutation_path"); j.obj();
        j.knum("solve_after_mutation_s", mut_solve_s);
        j.kstr("status", s3.status); j.ki("dof", s3.dof);
        j.knum("max_len_err", max_len_err(b, 1.5));
        j.endobj();
        // warm re-solve: solve() again on the solved system (slvs parity)
        auto t3 = Steady::now();
        auto s4 = b.solve_with_diagnosis();
        double warm_s = std::chrono::duration<double>(Steady::now() - t3).count();
        j.key("warm_resolve"); j.obj();
        j.knum("warm_resolve_s", warm_s);
        j.kstr("status", s4.status);
        j.endobj();
    }
    j.endobj();
    std::fputs(j.s.c_str(), stdout);
    std::fputc('\n', stdout);
    return 0;
}

int run_slot_debug();

int main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "--slotdebug") {
        return run_slot_debug();
    }
    if (argc >= 2 && std::string(argv[1]) == "--hash") {
        std::puts(canonical_hash_line().c_str());
        return 0;
    }
    if (argc >= 2 && std::string(argv[1]) == "--staircase") {
        int n = argc >= 3 ? std::atoi(argv[2]) : 200;
        bool edit = argc >= 4 && std::string(argv[3]) == "--edit";
        return run_staircase(n, edit);
    }
    return run_corpus();
}

// ------------------------------------------------------------- slot debug

int run_slot_debug() {
    // Formulation probes for the corpus slot fixture (committed evidence mode;
    // the generator embeds these steps into the envelope). Three formulations:
    //   A = FreeCAD endpoint tangency (AngleViaPoint) + structural sharing
    //   B = FreeCAD style: SEPARATE endpoints + Coincidents + AngleViaPoint
    //   C = curve-level Line-Arc tangent (P2LDistance) + structural sharing
    //       (the corpus's chosen formulation — the one that solves the W1 seed)
    JOut j; j.obj(); j.kstr("mode", "slot_debug");
    j.key("steps"); j.arr();
    auto diag1 = [&](CaseBuilder& b, const std::string& note) {
        b.declare_all();
        b.sys.initSolution(GCS::DogLeg);
        j.obj();
        j.kstr("after", note);
        j.ki("dof", b.sys.dofsNumber());
        GCS::VEC_I t;
        b.sys.getConflicting(t);
        j.key("conflicting"); j.arr();
        for (int x : t) j.str(b.tag_label(x));
        j.endarr();
        b.sys.getRedundant(t);
        j.key("redundant"); j.arr();
        for (int x : t) j.str(b.tag_label(x));
        j.endarr();
        j.endobj();
    };
    auto finish1 = [&](CaseBuilder& b, const std::string& note) {
        auto srec = b.solve_with_diagnosis();
        j.obj(); j.kstr("after", note);
        j.kstr("status", srec.status); j.kstr("chain", srec.chain); j.ki("dof", srec.dof);
        j.key("conflicting"); j.arr();
        for (auto& x : srec.conflicting) j.str(x);
        j.endarr();
        j.key("positions"); j.obj();
        for (auto& lbl : {"a1c","a1s","a1e","a2c","a2s","a2e"})
            { auto p = b.pos(lbl); j.key(lbl); j.arr(); j.num(p.first); j.num(p.second); j.endarr(); }
        j.knum("r1", b.radius("a1"));
        j.endobj();
        j.endobj();
    };
    auto seed_slot = [](CaseBuilder& b) {
        b.pt("a1c", 1.0, 1.0); b.pt("a1s", 1.0, 7.0); b.pt("a1e", 1.0, -5.0);
        b.pt("a2c", 37.0, 2.0); b.pt("a2s", 37.0, -3.0); b.pt("a2e", 37.0, 7.0);
        b.arc("a1", "a1c", "a1s", "a1e");
        b.arc("a2", "a2c", "a2s", "a2e");
        b.line("l1", "a1e", "a2s");
        b.line("l2", "a2e", "a1s");
    };
    auto probe_datums = [&](CaseBuilder& b,
                            const std::vector<std::array<std::string,4>>& specs,
                            std::map<std::string,double>& out) {
        std::vector<double> sp, sv;
        for (auto& a : b.pstore) { sp.push_back(a[0]); sp.push_back(a[1]); }
        for (auto& d : b.vstore) sv.push_back(d);
        *b.points["a1c"].x = 0; *b.points["a1c"].y = 0;
        *b.points["a1s"].x = 0; *b.points["a1s"].y = 6;
        *b.points["a1e"].x = 0; *b.points["a1e"].y = -6;
        *b.points["a2c"].x = 40; *b.points["a2c"].y = 0;
        *b.points["a2s"].x = 40; *b.points["a2s"].y = -6;
        *b.points["a2e"].x = 40; *b.points["a2e"].y = 6;
        *b.arcs["a1"].rad = 6; *b.arcs["a1"].startAngle = kPi/2; *b.arcs["a1"].endAngle = -kPi/2;
        *b.arcs["a2"].rad = 6; *b.arcs["a2"].startAngle = -kPi/2; *b.arcs["a2"].endAngle = kPi/2;
        for (auto& spec : specs)
            out[spec[0]] = b.sys.calculateAngleViaPoint(b.lines[spec[1]],
                                   b.arcs[spec[2]], b.points[spec[3]]);
        size_t k = 0;
        for (auto& a : b.pstore) { a[0] = sp[k++]; a[1] = sp[k++]; }
        for (auto& d : b.vstore) d = sv[k++];
    };
    {   // A: AngleViaPoint + structural sharing
        CaseBuilder b; seed_slot(b);
        b.k_coincident_origin("k1", "a1c");
        std::vector<std::array<std::string,4>> specs =
            {{"k2","l1","a1","a1e"},{"k3","l1","a2","a2s"},
             {"k4","l2","a2","a2e"},{"k5","l2","a1","a1s"}};
        for (auto& s : specs) {
            b.datum_of[s[0]] = b.val(0.0);
            int t = ++b.tag;
            b.sys.addConstraintAngleViaPoint(b.lines[s[1]], b.arcs[s[2]],
                                             b.points[s[3]], b.datum_of[s[0]], t);
            b.k_raw(s[0], "tangent_arc_line", "AngleViaPoint form", t);
        }
        b.k_equal("k6", "a1", "a2");
        b.k_horizontal("k7", "l1");
        b.k_diameter("d1", "a1", 12.0);
        b.k_proj_x("d2", "a1c", "a2c", 40.0);
        std::map<std::string,double> datums;
        probe_datums(b, specs, datums);
        for (auto& kv : datums) *b.datum_of[kv.first] = kv.second;
        diag1(b, "A: AngleViaPoint + sharing (diagnose)");
        finish1(b, "A: AngleViaPoint + sharing (solve)");
    }
    {   // B: separate endpoints + coincidents + AngleViaPoint (FreeCAD style)
        CaseBuilder b;
        b.pt("a1c", 1.0, 1.0); b.pt("a1s", 1.0, 7.0); b.pt("a1e", 1.0, -5.0);
        b.pt("a2c", 37.0, 2.0); b.pt("a2s", 37.0, -3.0); b.pt("a2e", 37.0, 7.0);
        b.arc("a1", "a1c", "a1s", "a1e");
        b.arc("a2", "a2c", "a2s", "a2e");
        b.pt("l1p1", 1.0, -5.0); b.pt("l1p2", 37.0, -3.0);
        b.pt("l2p1", 37.0, 7.0); b.pt("l2p2", 1.0, 7.0);
        b.line("l1", "l1p1", "l1p2");
        b.line("l2", "l2p1", "l2p2");
        b.k_coincident("c1", "l1p1", "a1e");
        b.k_coincident("c2", "l1p2", "a2s");
        b.k_coincident("c3", "l2p1", "a2e");
        b.k_coincident("c4", "l2p2", "a1s");
        b.k_coincident_origin("k1", "a1c");
        std::vector<std::array<std::string,4>> specs =
            {{"k2","l1","a1","a1e"},{"k3","l1","a2","a2s"},
             {"k4","l2","a2","a2e"},{"k5","l2","a1","a1s"}};
        for (auto& s : specs) {
            b.datum_of[s[0]] = b.val(0.0);
            int t = ++b.tag;
            b.sys.addConstraintAngleViaPoint(b.lines[s[1]], b.arcs[s[2]],
                                             b.points[s[3]], b.datum_of[s[0]], t);
            b.k_raw(s[0], "tangent_arc_line", "AngleViaPoint form", t);
        }
        b.k_equal("k6", "a1", "a2");
        b.k_horizontal("k7", "l1");
        b.k_diameter("d1", "a1", 12.0);
        b.k_proj_x("d2", "a1c", "a2c", 40.0);
        std::map<std::string,double> datums;
        probe_datums(b, specs, datums);
        for (auto& kv : datums) *b.datum_of[kv.first] = kv.second;
        diag1(b, "B: coincidents + AngleViaPoint (diagnose)");
        finish1(b, "B: coincidents + AngleViaPoint (solve)");
    }
    {   // C: corpus formulation (P2LDistance + sharing) — verbatim
        CaseBuilder b; build_slot(b, nullptr);
        diag1(b, "C: corpus P2LDistance + sharing (diagnose)");
        finish1(b, "C: corpus P2LDistance + sharing (solve)");
    }
    j.endarr(); j.endobj();
    std::fputs(j.s.c_str(), stdout);
    std::fputc('\n', stdout);
    return 0;
}
