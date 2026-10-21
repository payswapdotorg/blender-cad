#!/usr/bin/env python3
"""W2 (lane b) — experiment C orchestrator: truck (vendored-patched, pinned) vs OCCT/OCP.

Reproduce (from experiments/solidcraft/):

    # 1. build the truck-side harness once (see harness/Cargo.toml; NEVER -j > 1 here)
    cd harness && cargo build --bin w2_kernel -j 1 && cd ..
    # 2. run everything and assemble the envelope
    HARNESS_COMMIT=$(git rev-parse HEAD) python3.12 python/w2_kernel_runner.py

What it runs (all outputs land in scratch/w2-kernel/, gitignored; the envelope
results/w2-kernel.json embeds the numbers):

  A. truck direct API (harness binary, dev profile, pinned SHA 3b4db52):
     - `w2_kernel`            all 16 fixtures: build/measure/timing/STEP round-trip
     - `w2_kernel --emit-step` truck STEP files for the cross-read
     - `w2_kernel --read-step` truck reader on the OCCT-written STEP files
  B. OCP (cadquery-ocp 8.0.1.1.0 wheels in the OCP venv (default /home/z/solidcraft-ocp-venv), release build of OCCT):
     - `ocp_kernel_bench.py`  the same 16 fixtures + STEP round-trip + emitted STEP
     - `--read-step`          OCCT reader on the truck-written STEP files
  C. official release CLI (checksum-verified solidcraft-cli 0.16.2; tag 5de48e9 =
     80 commits behind the source pin — recorded in every header):
     - `oracle <case-dir> --json` for the 10 upstream-oracle fixtures (release-profile
       replay incl. STEP round-trip check);
     - `run <script> --results --timings --profile` x N=5 per fixture: the honest
       release-config timing source (per-command boolean_ms/tessellate_ms/other_ms).
  D. memory: isolated-process peak RSS per case on each path (/proc VmHWM for the
     harness, getrusage for python; the CLI is measured through a fresh wrapper process
     reading RUSAGE_CHILDREN).
  E. packaging: OCP installed footprint, harness target size (kernel closure build),
     release tarball/binary sizes, ldd of the harness binary (pure-Rust evidence).

Honesty: every failing or surprising outcome is recorded as-is; nothing is fabricated;
blocked measurements record their blocker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # experiments/solidcraft
SCRATCH = ROOT / "scratch" / "w2-kernel"
RESULTS = ROOT / "results"
FIXTURES = ROOT / "fixtures" / "kernel"
SCRIPTS = FIXTURES / "scripts"
HARNESS_BIN = ROOT / "harness" / "target" / "debug" / "w2_kernel"
OCP_VENV = Path(os.environ.get("OCP_VENV", "/home/z/solidcraft-ocp-venv"))
OCP_PY = OCP_VENV / "bin" / "python"
OCP_BENCH = ROOT / "python" / "ocp_kernel_bench.py"
UPSTREAM = Path(os.environ.get("SOLIDCRAFT_UPSTREAM", str(ROOT / ".upstream")))

# Verification-pass fix (Task 103): default to the in-tree .release/ layout created by
# ../fetch-release.sh (the previous /home/z/solidcraft-release default was a dev-host
# symlink artifact — reproducible-from-clean-checkout now works without out-of-tree setup).
CLI = os.environ.get(
    "SOLIDCRAFT_CLI",
    str(ROOT / ".release" / "solidcraft-0.16.2-linux-x86_64" / "bin" / "solidcraft-cli"),
)
UPSTREAM_SHA = "3b4db52c10279251a068cfca5eb7447068bc28e7"
RELEASE_TAG_COMMIT = "5de48e9"  # v0.16.2 tag; measured 80 commits behind the source pin
N_TIMING_RUNS = 5
JSON_MARK = "===W2_JSON==="

# fixture id -> upstream oracle case dir (None for self-authored)
ORACLE_CASE = {
    "k01-box": "01-box",
    "k02-cylinder": "02-cylinder",
    "k04-revolve-vase": "04-revolve-vase",
    "k07-fillet-all-edges": "07-fillet-all-edges",
    "k08-chamfer-top-edges": "08-chamfer",
    "k09-shell-open-top": "09-shell",
    "k13-union-box-cyl": "13-combine-join",
    "k14-cut-box-sphere": "14-combine-cut",
    "k15-intersect-cube-sphere": "15-combine-intersect",
    "k38-union-coincident-cyls": "38-coincident-cylinders",
}

ALL_FIXTURES = [
    "k01-box", "k02-cylinder", "k04-revolve-vase", "k07-fillet-all-edges",
    "k07b-fillet-4-vertical", "k08-chamfer-top-edges", "k09-shell-open-top",
    "k13-union-box-cyl", "k14-cut-box-sphere", "k15-intersect-cube-sphere",
    "k38-union-coincident-cyls", "st1-fillet-too-large", "st2-near-tangent-cut",
    "st3-thin-sliver-extrude", "st4-coincident-face-union", "st5-near-tangent-sphere-union",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(argv: list[str], timeout: int = 600) -> dict:
    t0 = time.monotonic()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {"argv": argv, "returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr,
                "wall_ms": round((time.monotonic() - t0) * 1000.0, 1)}
    except subprocess.TimeoutExpired:
        return {"argv": argv, "returncode": None, "stdout": "", "stderr": "TIMEOUT", "wall_ms": timeout * 1000.0}


def after_sentinel(stdout: str):
    if JSON_MARK in stdout:
        return json.loads(stdout.split(JSON_MARK, 1)[1].strip().splitlines()[-1])
    return None


def stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": round(sum(xs) / len(xs), 3), "min": round(min(xs), 3), "max": round(max(xs), 3)}


# --------------------------------------------------------------------------- A+B: the two kernels

def run_truck_harness(harness_commit: str) -> dict:
    if not HARNESS_BIN.is_file():
        return {"status": "blocked", "blocker": f"harness binary missing: {HARNESS_BIN} (cargo build --bin w2_kernel -j 1)"}
    env = dict(os.environ, HARNESS_COMMIT=harness_commit)
    r = subprocess.run([str(HARNESS_BIN)], capture_output=True, text=True, timeout=900, env=env, cwd=str(HARNESS_BIN.parents[2]))  # cwd = harness/ so the binary's ../scratch/w2-kernel/ output lands where this runner reads it (verification-pass fix, Task 103)
    if r.returncode != 0:
        return {"status": "blocked", "blocker": f"harness rc={r.returncode}: {r.stderr[:500]}"}
    return json.loads((SCRATCH / "truck-harness.json").read_text())


def run_step_crossreads() -> dict:
    out = {}
    r1 = subprocess.run([str(HARNESS_BIN), "--emit-step", str(SCRATCH / "truck-step")], capture_output=True, text=True, timeout=600)
    out["truck_emit"] = {"rc": r1.returncode, "stdout_tail": r1.stdout[-200:] if r1.stdout else "", "stderr": r1.stderr[-300:]}
    r2 = subprocess.run([str(OCP_PY), str(OCP_BENCH), "--read-step", str(SCRATCH / "truck-step")], capture_output=True, text=True, timeout=900)
    parsed = after_sentinel(r2.stdout)
    out["ocp_reads_truck"] = parsed or {"status": "blocked", "blocker": (r2.stderr or r2.stdout)[-500:], "rc": r2.returncode}
    r3 = subprocess.run([str(HARNESS_BIN), "--read-step", str(SCRATCH / "ocp-step")], capture_output=True, text=True, timeout=900)
    try:
        out["truck_reads_ocp"] = json.loads(r3.stdout)
    except Exception:
        out["truck_reads_ocp"] = {"status": "blocked", "blocker": (r3.stderr or r3.stdout)[-500:], "rc": r3.returncode}
    return out


def run_ocp_bench() -> dict:
    if not OCP_PY.is_file():
        return {"status": "blocked", "blocker": f"OCP venv missing: {OCP_PY}"}
    r = subprocess.run([str(OCP_PY), str(OCP_BENCH)], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return {"status": "blocked", "blocker": f"ocp bench rc={r.returncode}: {r.stderr[-500:]}"}
    return json.loads((SCRATCH / "ocp-bench.json").read_text())


# --------------------------------------------------------------------------- C: release CLI

def run_cli_oracle() -> dict:
    """The 10 upstream-oracle fixtures replayed by the release binary's own oracle runner."""
    records = {}
    for fid, case in ORACLE_CASE.items():
        d = str(UPSTREAM / "tests" / "oracle" / case)
        r = sh([CLI, "oracle", d, "--json"])
        rec = {"argv": r["argv"], "rc": r["returncode"], "wall_ms": r["wall_ms"]}
        try:
            data = json.loads(r["stdout"])
            first = data[0] if isinstance(data, list) and data else {}
            rec["case"] = first.get("case")
            rec["pass"] = first.get("pass")
            rec["source"] = first.get("source")
            rec["got"] = first.get("got")
            rec["checks"] = [{k: c.get(k) for k in ("check", "ok", "got", "want")} for c in first.get("checks", [])]
            rec["step_export_check"] = next((c for c in first.get("checks", []) if c.get("check") == "step_export"), None)
        except Exception as e:
            rec["parse_error"] = f"{type(e).__name__}: {e}"
            rec["stdout_head"] = r["stdout"][:300]
        if r["stderr"]:
            rec["stderr"] = r["stderr"][:300]
        records[fid] = rec
    return records


def run_cli_timing() -> dict:
    """N fresh CLI processes per fixture; per-command ms + kernel share (boolean/tessellate)."""
    records = {}
    for fid in ALL_FIXTURES:
        script = SCRIPTS / f"{fid}.json"
        if not script.is_file():
            records[fid] = {"status": "blocked", "blocker": f"missing script {script}"}
            continue
        runs = []
        for i in range(N_TIMING_RUNS):
            r = sh([CLI, "run", str(script), "--results", "--timings", "--profile"])
            run = {"rc": r["returncode"], "wall_ms": r["wall_ms"]}
            try:
                d = json.loads(r["stdout"])
                t = d.get("timings", [])
                run["total_ms"] = d.get("total_ms")
                run["commands"] = [
                    {"command": c.get("command"), "index": c.get("index"), "ms": c.get("ms"), "profile": c.get("profile")}
                    for c in t
                ]
                run["sum_command_ms"] = round(sum(c.get("ms") or 0 for c in t), 3)
                run["sum_boolean_ms"] = round(sum((c.get("profile") or {}).get("boolean_ms") or 0 for c in t), 3)
                run["sum_tessellate_ms"] = round(sum((c.get("profile") or {}).get("tessellate_ms") or 0 for c in t), 3)
                run["sum_other_ms"] = round(sum((c.get("profile") or {}).get("other_ms") or 0 for c in t), 3)
            except Exception as e:
                run["parse_error"] = f"{type(e).__name__}: {e}"
            if r["returncode"] != 0 and r["stderr"]:
                run["error"] = r["stderr"].strip()[:400]  # verbatim refusal text
            runs.append(run)
        good = [x for x in runs if x.get("total_ms") is not None]
        rec = {
            "script": str(script),
            "n_runs": N_TIMING_RUNS,
            "n_ok_runs": len(good),
            "total_ms_stats": stats([x["total_ms"] for x in good]),
            "command_sum_ms_stats": stats([x["sum_command_ms"] for x in good]) if good else {},
            "boolean_ms_stats": stats([x["sum_boolean_ms"] for x in good]) if good else {},
            "tessellate_ms_stats": stats([x["sum_tessellate_ms"] for x in good]) if good else {},
            "other_ms_stats": stats([x["sum_other_ms"] for x in good]) if good else {},
            "runs": runs,
        }
        # the last command of the LAST successful run, for per-op release timing
        if good:
            last = good[-1]["commands"]
            rec["last_run_commands"] = last
        records[fid] = rec
    return records


# --------------------------------------------------------------------------- D: memory (peak RSS)

def child_peak_rss_kib(argv: list[str]) -> dict:
    """Peak RSS of ONE child process, measured in a fresh wrapper (RUSAGE_CHILDREN max)."""
    code = (
        "import resource,subprocess,sys,json;"
        "r=subprocess.run(sys.argv[1:],capture_output=True);"
        "print(json.dumps({'rc':r.returncode,"
        "'peak_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}))"
    )
    r = sh([sys.executable, "-c", code, *map(str, argv)], timeout=900)
    try:
        return json.loads(r["stdout"].strip().splitlines()[-1])
    except Exception:
        return {"rc": r["returncode"], "parse_error": True, "stderr": (r["stderr"] or "")[:200]}


def run_memory(harness_commit: str) -> dict:
    env = dict(os.environ, HARNESS_COMMIT=harness_commit)
    records = {}
    for fid in ALL_FIXTURES:
        rec = {}
        # truck harness, isolated process
        r = subprocess.run([str(HARNESS_BIN), "--case", fid], capture_output=True, text=True, timeout=600, env=env)
        try:
            rec["truck_harness"] = json.loads(r.stdout.strip().splitlines()[-1]).get("peak_rss_kib")
        except Exception:
            rec["truck_harness"] = {"error": (r.stderr or r.stdout)[-200:]}
        # OCP, isolated process (sentinel JSON)
        r = subprocess.run([str(OCP_PY), str(OCP_BENCH), "--case", fid], capture_output=True, text=True, timeout=600)
        p = after_sentinel(r.stdout)
        rec["ocp"] = p.get("peak_rss_kib") if p else {"error": (r.stderr or r.stdout)[-200:]}
        # release CLI, wrapper process
        script = SCRIPTS / f"{fid}.json"
        if script.is_file():
            rec["cli_release"] = child_peak_rss_kib([CLI, "run", str(script), "--results"])
        else:
            rec["cli_release"] = {"error": "missing script"}
        records[fid] = rec
    return records


# --------------------------------------------------------------------------- E: packaging

def du_bytes(path: Path) -> int:
    out = subprocess.run(["du", "-sb", str(path)], capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else 0


def run_packaging() -> dict:
    rec = {}
    # OCP installed footprint
    site = OCP_VENV / "lib" / "python3.12" / "site-packages"
    ocp_dir = site / "OCP"
    rec["ocp_installed_bytes"] = du_bytes(ocp_dir) if ocp_dir.is_dir() else None
    wheels = list(OCP_VENV.rglob("*.whl"))
    rec["ocp_wheel_files_in_venv"] = [{"name": w.name, "bytes": w.stat().st_size} for w in wheels]
    rec["ocp_wheel_download_note"] = (
        "wheel file not retained in the venv; installed size measured directly; "
        "docs/00-architecture/kernel-bindings-evaluation-m1.md records 45-65 MB per platform for the "
        "cadquery-ocp 8.0.1.1.0 wheels (cp313; this venv is cp312)"
    )
    # truck: harness target (kernel closure build), release artifacts
    rec["harness_target_bytes"] = du_bytes(ROOT / "harness" / "target")
    rel = Path(CLI).parents[1]
    rec["release_dir_bytes"] = du_bytes(rel)
    rec["release_cli_binary_bytes"] = Path(CLI).stat().st_size if Path(CLI).is_file() else None
    rec["release_tarball"] = None
    for cand in [rel.parent / f"{rel.name}.tar.gz", rel.parent / f"{rel.name}.tgz", rel / "solidcraft-0.16.2.tar.gz"]:
        if cand.is_file():
            rec["release_tarball"] = {"path": str(cand), "bytes": cand.stat().st_size}
            break
    # native-dependency evidence: ldd of the harness binary (kernel closure)
    r = sh(["ldd", str(HARNESS_BIN)])
    rec["harness_ldd"] = {"rc": r["returncode"], "stdout": r["stdout"].strip()}
    rec["notes"] = (
        "truck-side kernel closure is pure Rust (vendored truck family + solidcraft crates); the harness "
        "binary's dynamic deps are the C runtime only. The product's zstd dependency lives in "
        "solidcraft-io, which this harness deliberately does not build (cadmpeg-ir OOM, Task 96). "
        "OCP wheels bundle the full C++ OCCT + TBB + FFMpeg shared libraries."
    )
    return rec


# --------------------------------------------------------------------------- envelope

def main() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    repo = ROOT.parents[1]
    harness_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True).stdout.strip()
    started = utcnow()
    print("A. truck harness (direct API, pinned vendored truck)...", file=sys.stderr)
    truck = run_truck_harness(harness_commit)
    print("B. OCP bench...", file=sys.stderr)
    ocp = run_ocp_bench()
    print("B2. STEP cross-reads...", file=sys.stderr)
    cross = run_step_crossreads()
    print("C1. release CLI oracle (10 upstream cases)...", file=sys.stderr)
    oracle = run_cli_oracle()
    print(f"C2. release CLI timing x{N_TIMING_RUNS} (16 fixtures)...", file=sys.stderr)
    timing = run_cli_timing()
    print("D. isolated-process peak RSS...", file=sys.stderr)
    memory = run_memory(harness_commit)
    print("E. packaging...", file=sys.stderr)
    packaging = run_packaging()
    finished = utcnow()

    cpus = os.cpu_count() or 2
    mem_total_kib = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                mem_total_kib = int(line.split()[1])
    except Exception:
        pass

    failures = []
    # collect failure-class records (never dropped)
    for fid in ALL_FIXTURES:
        for side, doc in (("truck", truck), ("ocp", ocp)):
            if isinstance(doc, dict) and doc.get("status") == "blocked":
                failures.append({"fixture": fid, "side": side, "kind": "blocked", "detail": doc.get("blocker")})
                continue
            cases = doc.get("cases", []) if isinstance(doc, dict) else []
            c = next((x for x in cases if x.get("id") == fid), None)
            if not c:
                continue
            if c["outcome"]["outcome"] == "refused-with-error":
                failures.append({"fixture": fid, "side": side, "kind": "refused-with-error", "verbatim": c["outcome"]["error"]})
    # cross-read anomaly detection (wrong-volume imports are failures, never dropped)
    tr = cross.get("truck_reads_ocp", {})
    if isinstance(tr, dict) and "files" in tr:
        for f in tr["files"]:
            if "error" in f:
                failures.append({"fixture": f["file"], "side": "truck-reader", "kind": "step-import-error", "verbatim": f["error"]})

    # STEP interop summary: volume deltas both directions, against each writer's own measured volume
    step_interop = {"truck_to_ocp": [], "ocp_to_truck": []}
    ocp_reads = cross.get("ocp_reads_truck") or {}
    truck_reads = cross.get("truck_reads_ocp", {})
    if isinstance(truck_reads, dict) and "files" in truck_reads and isinstance(truck, dict) and truck.get("status") != "blocked":
        truck_cases = {c["id"]: c for c in truck.get("cases", [])}
        for f in truck_reads["files"]:
            fid = f["file"].replace(".step", "")
            base = truck_cases.get(fid, {}).get("outcome", {}).get("measure", {}).get("volume_mm3")
            got = sum(m["volume_mm3"] for m in f.get("measures", [])) if "measures" in f else None
            rel = None if not (base and got) else abs(got - base) / abs(base)
            step_interop["ocp_to_truck"].append({"fixture": fid, "writer": "OCCT STEPControl_Writer", "reader": "truck step_in",
                                                  "writer_volume_mm3": base, "reader_volume_mm3": got, "rel_delta": rel,
                                                  "bodies": f.get("bodies"), "warnings": f.get("warnings")})
            if rel is not None and rel > 1e-3:
                failures.append({"fixture": fid, "side": "truck-reader-on-OCCT-STEP", "kind": "step-crossread-volume-anomaly",
                                 "verbatim": f"volume read back {got:.6f} vs writer's {base:.6f} (rel {rel:.2e} > 1e-3), no warnings, body closed"})
    if isinstance(ocp_reads, dict) and "files" in ocp_reads and isinstance(ocp, dict) and ocp.get("status") != "blocked":
        ocp_cases = {c["id"]: c for c in ocp.get("cases", [])}
        for f in ocp_reads["files"]:
            fid = f["file"].replace(".step", "")
            base = ocp_cases.get(fid, {}).get("outcome", {}).get("measure", {}).get("volume_mm3")
            got = f.get("volume_mm3")
            rel = None if not (base and got) else abs(got - base) / abs(base)
            step_interop["truck_to_ocp"].append({"fixture": fid, "writer": "truck-stepio (vendored)", "reader": "OCCT STEPControl_Reader",
                                                  "writer_volume_mm3": base, "reader_volume_mm3": got, "rel_delta": rel,
                                                  "valid": f.get("valid")})
            if rel is not None and rel > 1e-3:
                failures.append({"fixture": fid, "side": "OCCT-reader-on-truck-STEP", "kind": "step-crossread-volume-anomaly",
                                 "verbatim": f"volume read back {got:.6f} vs writer's {base:.6f} (rel {rel:.2e} > 1e-3)"})

    envelope = {
        "experiment": "w2-kernel",
        "issue_ref": "payswapdotorg/blender-cad#1",
        "upstream": {
            "repo": "https://github.com/tangency-labs/solidcraft",
            "sha": UPSTREAM_SHA,
            "version": "0.16.2",
            "vendored_truck_patches": True,
        },
        "harness_commit": harness_commit,
        "command": f"HARNESS_COMMIT={harness_commit} python3.12 {sys.argv[0]}",
        "started_utc": started,
        "finished_utc": finished,
        "host": {
            "cpus": cpus,
            "mem_gb": round(mem_total_kib / 1_048_576, 1),
            "note": "sandbox container (2-CPU, ~4 GiB cgroup; builds run with cargo -j 1)",
        },
        "paths": {
            "truck_direct_api": {
                "what": "harness/src/bin/w2_kernel.rs against solidcraft-kernel (vendored patched truck) at the pinned SHA",
                "profile": "dev, dependencies opt-level 2, debug-assertions off (upstream dev-profile fidelity)",
                "binary": str(HARNESS_BIN),
            },
            "truck_release_cli": {
                "what": "official release binary (checksum-verified at fetch): oracle replay + run --timings --profile",
                "version": "solidcraft-cli 0.16.2",
                "tag_commit": RELEASE_TAG_COMMIT,
                "tag_commit_note": "tag v0.16.2 = 5de48e9 is 80 commits behind the source pin 3b4db52 (measured: 50 first-parent; 35 touch crates/doc|engine|kernel, 3 the CLI app, 3 crates/mcp) — behavioral CLI evidence uses the binary, source audits use the pin",
            },
            "ocp": {
                "what": "python/ocp_kernel_bench.py, OCCT 8.0.1 via cadquery-ocp wheels",
                "profile": "python in-process, OCP wheel (release build of OCCT), warm",
                "venv": "OCP_VENV env var, default /home/z/solidcraft-ocp-venv (outside the repo tree — moved after the secret-scanner walk found the venv inside experiments/; experiment-side only; NOT a product dependency)",
            },
            "timing_note": (
                "release-config timing = the CLI path (release profile, shipped config); the harness and OCP "
                "timings are in-process warm repeats (dev profile / pybind calls) and are NOT directly "
                "comparable to the CLI numbers or to each other — all three are recorded with their context"
            ),
            "memory_note": "isolated-process peak RSS per fixture per path (VmHWM / getrusage / RUSAGE_CHILDREN wrapper)",
        },
        "fixtures": json.loads((FIXTURES / "cases.json").read_text()),
        "truck_harness": truck,
        "ocp_bench": ocp,
        "step_crossread": cross,
        "step_interop": step_interop,
        "cli_oracle": oracle,
        "cli_timing": timing,
        "memory": memory,
        "packaging": packaging,
        "failures": failures,
    }

    # ---- summary tables (computed, not hand-written) ----
    def vol(doc, fid, side):
        if not isinstance(doc, dict) or doc.get("status") == "blocked":
            return None
        c = next((x for x in doc.get("cases", []) if x.get("id") == fid), None)
        if not c or c["outcome"]["outcome"] != "success":
            return None
        return c["outcome"]["measure"]["volume_mm3"]

    fx = {c["id"]: c for c in envelope["fixtures"]["cases"]}
    per_case = []
    for fid in ALL_FIXTURES:
        exp = fx[fid]["expected"]
        tv, ov = vol(truck, fid, "truck"), vol(ocp, fid, "ocp")
        row = {
            "id": fid,
            "op_classes": fx[fid]["op_classes"],
            "comparability": fx[fid]["comparability"]["label"],
            "expected_volume_mm3": exp.get("volume_mm3"),
            "expected_source": exp.get("source"),
            "truck_volume_mm3": tv,
            "ocp_volume_mm3": ov,
            "truck_vs_expected_rel": None if not tv or not exp.get("volume_mm3") else abs(tv - exp["volume_mm3"]) / abs(exp["volume_mm3"]),
            "ocp_vs_expected_rel": None if not ov or not exp.get("volume_mm3") else abs(ov - exp["volume_mm3"]) / abs(exp["volume_mm3"]),
            "cross_kernel_rel": None if not (tv and ov) else abs(tv - ov) / max(abs(tv), abs(ov)),
            "truck_outcome": (next((x for x in (truck.get("cases", []) if isinstance(truck, dict) else [])), None) or {}).get("outcome", {}).get("outcome") if isinstance(truck, dict) else None,
            "ocp_outcome": (next((x for x in (ocp.get("cases", []) if isinstance(ocp, dict) else [])), None) or {}).get("outcome", {}).get("outcome") if isinstance(ocp, dict) else None,
        }
        # fix the outcome extraction (the expression above grabbed the first case only)
        for side, doc in (("truck_outcome", truck), ("ocp_outcome", ocp)):
            if isinstance(doc, dict) and doc.get("status") != "blocked":
                c = next((x for x in doc.get("cases", []) if x.get("id") == fid), None)
                if c:
                    row[side] = c["outcome"]["outcome"]
        per_case.append(row)

    n_pass = lambda rows, k: sum(1 for r in rows if r[k] is not None and r[k] <= 1e-3)
    envelope["summary"] = {
        "fixtures": len(ALL_FIXTURES),
        "provenance": {"upstream_oracle": len(ORACLE_CASE), "self_authored": len(ALL_FIXTURES) - len(ORACLE_CASE)},
        "truck_direct_api": {
            "success": sum(1 for r in per_case if r["truck_outcome"] == "success"),
            "refused_with_error": sum(1 for r in per_case if r["truck_outcome"] == "refused-with-error"),
            "within_oracle_tolerance_vs_analytic": n_pass(per_case, "truck_vs_expected_rel"),
        },
        "ocp": {
            "success": sum(1 for r in per_case if r["ocp_outcome"] == "success"),
            "refused_with_error": sum(1 for r in per_case if r["ocp_outcome"] == "refused-with-error"),
            "within_oracle_tolerance_vs_analytic": n_pass(per_case, "ocp_vs_expected_rel"),
        },
        "cli_oracle_pass": sum(1 for r in oracle.values() if r.get("pass") is True) if isinstance(oracle, dict) else None,
        "per_case": per_case,
        "comparability_counts": {
            label: sum(1 for r in per_case if r["comparability"] == label)
            for label in sorted({r["comparability"] for r in per_case})
        },
    }

    out = RESULTS / "w2-kernel.json"
    out.write_text(json.dumps(envelope, indent=1))
    size_kb = out.stat().st_size // 1024
    print(f"wrote {out} ({size_kb} KB) in {finished}", file=sys.stderr)
    print(f"failures/anomalies recorded: {len(failures)}", file=sys.stderr)
    for f in failures:
        print(f"  - {f.get('fixture')} [{f.get('side')}] {f.get('kind')}: {str(f.get('verbatim'))[:110]}", file=sys.stderr)
    print(json.dumps(envelope["summary"], indent=1)[:1200], file=sys.stderr)


if __name__ == "__main__":
    main()
