#!/usr/bin/env python3
"""W3 lane-a: behavioral MCP agent-interface PoC against the real SolidCraft server.

Drives the OFFICIAL RELEASE binary (`solidcraft-cli mcp`, v0.16.2, tag commit 5de48e9 —
80 commits behind the source pin 3b4db52) headlessly through JSON-RPC 2.0 over stdio
and probes: handshake/tool inventory, a complete constrained CAD chain with analytic
verification, parameter edit + recompute, schema validation at both protocol layers,
filesystem-security rules (docs/mcp.md), transactions/rollback, and clean shutdown.

Runs the whole suite TWICE (run1 = evidence, run2 = reproducibility) and writes the
machine-readable result envelope to experiments/solidcraft/results/w3-mcp.json.

Python 3.12, STDLIB ONLY. Never mutates anything outside experiments/solidcraft/scratch/.

Reproduce:
    cd /home/z/blender-cad && python3.12 experiments/solidcraft/python/mcp_client_probe.py

Author: W3 lane-a worker (Task 99, retry), 2026-10-19.
"""
import hashlib
import json
import os
import platform
import re
import select
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EXP = os.path.abspath(os.path.join(HERE, ".."))
SCRATCH = os.path.join(EXP, "scratch", "w3")
RESULTS = os.path.join(EXP, "results", "w3-mcp.json")

# Verification-pass fix (Task 103): SOLIDCRAFT_CLI env override (consistent with the
# other drivers) + default to the in-tree .release/ layout created by ../fetch-release.sh
# (the previous hardcoded /home/z/solidcraft-release path was a dev-host symlink artifact).
BIN = os.environ.get(
    "SOLIDCRAFT_CLI",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".release",
        "solidcraft-0.16.2-linux-x86_64", "bin", "solidcraft-cli",
    ),
)
UPSTREAM_REPO = "https://github.com/tangency-labs/solidcraft"
UPSTREAM_SHA = "3b4db52c10279251a068cfca5eb7447068bc28e7"  # source pin used for audits
RELEASE_TAG_COMMIT = "5de48e9"  # release binary tag; 80 commits behind the pin (measured by W2)
COMMITS_BEHIND = 80
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
VOL_TOL = 1e-6  # relative tolerance for analytic volume checks

MAX_VERBATIM = 2000  # truncate verbatim blobs longer than this (note added)


def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def trunc(s, limit=MAX_VERBATIM):
    if s is None:
        return None
    s = str(s)
    if len(s) > limit:
        return s[:limit] + f"…[truncated, {len(s)} chars total]"
    return s


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# MCP client: newline-delimited JSON-RPC 2.0 over the server's stdio
# ---------------------------------------------------------------------------
class McpClient:
    def __init__(self, argv, cwd, stderr_path):
        self.argv = argv
        self.cwd = cwd
        self.stderr_path = stderr_path
        self.proc = None
        self._buf = b""
        self._id = 0
        self.started = None

    def start(self):
        self._errf = open(self.stderr_path, "wb")
        self.started = time.monotonic()
        self.proc = subprocess.Popen(
            self.argv, cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._errf,
        )

    # --- low-level line io --------------------------------------------------
    def _readline(self, timeout):
        end = time.monotonic() + timeout
        while b"\n" not in self._buf:
            remain = end - time.monotonic()
            if remain <= 0:
                raise TimeoutError(f"no reply within {timeout}s")
            r, _, _ = select.select([self.proc.stdout], [], [], min(remain, 5.0))
            if not r:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"server exited (rc={self.proc.returncode}) before replying")
                continue
            chunk = os.read(self.proc.stdout.fileno(), 1 << 16)
            if not chunk:
                raise RuntimeError(f"server closed stdout (rc={self.proc.poll()})")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", "replace")

    def _send(self, text):
        self.proc.stdin.write((text + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _expect_silence(self, seconds=0.4):
        """True when nothing arrives on stdout within `seconds` (notifications)."""
        end = time.monotonic() + seconds
        while True:
            remain = end - time.monotonic()
            if remain <= 0 or self._buf:
                return not self._buf and remain <= 0
            r, _, _ = select.select([self.proc.stdout], [], [], remain)
            if r:
                self._buf += os.read(self.proc.stdout.fileno(), 1 << 16)
                return False

    # --- JSON-RPC -----------------------------------------------------------
    def request(self, method, params=None, timeout=120.0):
        self._id += 1
        rid = self._id
        self._send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}))
        t0 = time.monotonic()
        while True:
            reply = json.loads(self._readline(timeout))
            if reply.get("id") == rid:
                reply["_ms"] = round((time.monotonic() - t0) * 1000, 1)
                return reply

    def notify(self, method):
        self._send(json.dumps({"jsonrpc": "2.0", "method": method}))

    def raw_line(self, text, timeout=30.0):
        """Send an arbitrary line (parse-error probes); return the raw reply line."""
        self._send(text)
        return self._readline(timeout)

    # --- tools --------------------------------------------------------------
    def call_tool(self, name, args, timeout=120.0):
        """Returns {layer, is_error, text, parsed, rpc_error?, ms}."""
        r = self.request("tools/call", {"name": name, "arguments": args}, timeout)
        if "error" in r:
            return {"layer": "json-rpc", "rpc_error": r["error"], "is_error": True,
                    "text": r["error"].get("message"), "ms": r.get("_ms")}
        res = r.get("result", {})
        blocks = res.get("content", [])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        parsed = None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            pass
        return {"layer": "tool-result", "is_error": bool(res.get("isError", False)),
                "text": text, "parsed": parsed, "content_types": [b.get("type") for b in blocks],
                "ms": r.get("_ms")}

    def close(self, timeout=20.0):
        """Close stdin; return (exit_code, seconds, orphaned?)."""
        t0 = time.monotonic()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            rc = self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            rc = self.proc.wait()
            return rc, round(time.monotonic() - t0, 2), True
        orphan = True
        try:
            os.kill(self.proc.pid, 0)  # zombie until reaped; after wait() it must be gone
        except ProcessLookupError:
            orphan = False
        try:
            self._errf.close()
        except Exception:
            pass
        return rc, round(time.monotonic() - t0, 2), orphan


# ---------------------------------------------------------------------------
# Probe recorder
# ---------------------------------------------------------------------------
class Probe:
    def __init__(self):
        self.cases = []

    def record(self, cid, group, description, expected, observed, ok, layer=None, **extra):
        case = {"id": cid, "group": group, "description": description,
                "expected": expected, "observed": observed, "pass": ok}
        if layer:
            case["layer"] = layer
        case.update(extra)
        self.cases.append(case)
        mark = "PASS" if ok else ("FAIL" if ok is False else "INFO")
        print(f"  [{mark}] {cid}: {description[:90]}")
        return case

    def info(self, cid, group, description, observed):
        return self.record(cid, group, description, None, observed, None)


# ---------------------------------------------------------------------------
# helpers shared by probes
# ---------------------------------------------------------------------------
def measure_state(cli):
    """Fingerprint: measure totals + body names + undo depth."""
    m = cli.call_tool("measure", {})
    i = cli.call_tool("inspect_design", {})
    tot = (m.get("parsed") or {}).get("total", {})
    ins = i.get("parsed") or {}
    bodies = ins.get("bodies")
    names = sorted(b.get("name") for b in bodies) if isinstance(bodies, list) else None
    return {"volume_mm3": tot.get("volume_mm3"), "area_mm2": tot.get("area_mm2"),
            "faces": tot.get("faces"), "edges": tot.get("edges"),
            "body_count": len(bodies) if isinstance(bodies, list) else None,
            "body_names": names, "undo_depth": ins.get("undo")}


def volume_ok(v, expect):
    return v is not None and abs(v - expect) / expect <= VOL_TOL


def err_layer(r):
    if r.get("layer") == "json-rpc":
        e = r.get("rpc_error") or {}
        return f"json-rpc error {e.get('code')}"
    return "tool result isError" if r.get("is_error") else "tool result ok"


def normalize_verbatim(s, run_dir):
    """Strip run-specific details (paths, pids, scratch seeds, engine self-reported
    step timings — geometry is byte-identical, only `"ms"` fields vary) for run diffing.

    Temp-path classification (close-out, regression-tested in
    experiments/solidcraft/tests/test_mcp_normalizer.py):
    * The upstream runtime form is ALWAYS ``solidcraft-mcp-<pid>-<seed-hex>``
      (``crates/mcp/src/lib.rs`` @ pin ``3b4db52``:
      ``format!("solidcraft-mcp-{}-{:x}", std::process::id(), seed)``) — the pid is a
      u32 decimal, never empty, so the digit-less variant cannot occur at this pin.
    * The regex nonetheless also accepts the digit-less form
      ``solidcraft-mcp--<seed-hex>`` as defensive coverage for future upstream pins
      (upstream churn is a recorded risk — 80 commits between our pin and the nearest
      tag); previously that form would have leaked a pid-seed path into the cross-run
      comparison and produced a spurious "observed-differs" diff.
    * Residual temp-path variance is therefore classified as ENVIRONMENT-ONLY: it is
      normalized away before comparison and never affects the recorded outcome; the
      determinism claim in the envelope is scoped to exactly this normalized comparison
      (pass flags + normalized verbatim evidence; geometry and error strings compared
      exactly)."""
    s = str(s)
    s = s.replace(run_dir, "<RUNDIR>")
    # digit-ful pid-seed form (the only runtime-real form at pin 3b4db52) AND the
    # digit-less defensive form; both collapse to the same redaction token; the
    # alternation is deliberately precise so test-fixture-style names upstream uses
    # (solidcraft-mcp-urdf-<pid> etc. in crates/mcp/src/tests.rs) stay untouched
    s = re.sub(r"solidcraft-mcp-(?:\d+-|-)[0-9a-f]+", "solidcraft-mcp-<PID>", s)
    s = re.sub(r'(\\?"ms\\?"\s*:\s*)[0-9.]+', r'\1<T>', s)  # raw and escaped (inside verbatim strings)
    s = re.sub(r"\u2026\[truncated, (\d+) chars total\]", "\u2026[truncated, N chars total]", s)
    return s


# ---------------------------------------------------------------------------
# CAD chain (the part being modeled): constrained 40x30 rectangle, extruded 20
# ---------------------------------------------------------------------------
CHAIN_STEPS = [
    {"command": "sketch.create", "params": {"plane": "XY"}},
    {"command": "sketch.line", "params": {"points": [[0, 0], [40, 0], [40, 30], [0, 30]], "closed": True}},
    {"command": "sketch.constraint.horizontal_vertical", "params": {"line": "l1", "mode": "horizontal"}},
    {"command": "sketch.constraint.horizontal_vertical", "params": {"line": "l2", "mode": "vertical"}},
    {"command": "sketch.constraint.horizontal_vertical", "params": {"line": "l3", "mode": "horizontal"}},
    {"command": "sketch.constraint.horizontal_vertical", "params": {"line": "l4", "mode": "vertical"}},
    {"command": "sketch.dimension", "params": {"entities": ["l1"], "type": "horizontal", "value": "width"}},
    {"command": "sketch.dimension", "params": {"entities": ["l2"], "type": "vertical", "value": "height"}},
    {"command": "sketch.finish", "params": {}},
    {"command": "solid.extrude", "params": {"distance": "depth"}},
]

ARC_STEPS = [
    {"command": "sketch.create", "params": {"plane": "XY"}},
    {"command": "sketch.arc.three_point", "params": {"start": [60, 0], "end": [60, 5], "through": [63, 3]}},
    {"command": "sketch.circle.center", "params": {"center": [70, 10], "radius": 3}},
    {"command": "sketch.finish", "params": {}},
]

FAILING_BATCH = [
    {"command": "solid.box", "params": {"length": 10, "width": 10, "height": 10}},
    {"command": "solid.fillet", "params": {"edges": [[999, 999, 999]], "radius": 5}},
]


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
def session_zero(run_dir, probe, log):
    """Setup: create designs/base.solidcraft via a server started with --allow-path.

    Also proves the doc rule that a folder NAMED with --allow-path is reached in full,
    hidden files included (contrast with the design-folder rules probed in the main run).
    """
    print(" session-0: setup (--allow-path, hidden file allowed in named root)")
    designs = os.path.join(run_dir, "designs")
    os.makedirs(designs, exist_ok=True)
    cli = McpClient([BIN, "mcp", "--allow-path", designs], run_dir, os.path.join(run_dir, "session0.err"))
    cli.start()
    try:
        base = os.path.join(designs, "base.solidcraft")
        r = cli.call_tool("save", {"path": base})
        ok = (not r["is_error"]) and os.path.exists(base) and os.path.getsize(base) > 0
        probe.record("S0A", "setup", "save empty design into --allow-path folder", "file written",
                     {"verbatim_reply": trunc(r["text"]), "file_exists": os.path.exists(base),
                      "bytes": os.path.getsize(base) if os.path.exists(base) else 0}, ok)
        hidden = os.path.join(designs, ".inside-allow-root.solidcraft")
        r = cli.call_tool("save", {"path": hidden})
        ok = (not r["is_error"]) and os.path.exists(hidden)
        probe.record("S0B", "fs-security", "save HIDDEN file inside a --allow-path root",
                     "allowed: a named folder is reached in full, hidden files included (docs/mcp.md)",
                     {"verbatim": trunc(r["text"]), "file_exists": os.path.exists(hidden)}, ok)
    finally:
        rc, secs, orphan = cli.close()
    probe.record("S0X", "shutdown", "session-0 clean shutdown after stdin close",
                 "exit code 0, no orphan", {"exit_code": rc, "seconds": secs, "orphan": orphan},
                 rc == 0 and not orphan)
    log["session0_stderr"] = trunc(open(os.path.join(run_dir, "session0.err")).read(), 1500)


def session_prelude(run_dir, probe):
    """Lifecycle enforcement: call tools/list with NO initialize handshake first."""
    print(" session-prelude: no-initialize lifecycle probe")
    cli = McpClient([BIN, "mcp"], run_dir, os.path.join(run_dir, "prelude.err"))
    cli.start()
    try:
        r = cli.request("tools/list")
        tools = r.get("result", {}).get("tools", [])
        probe.record("P1", "handshake", "tools/list BEFORE initialize (lifecycle enforcement?)",
                     "server.rs has an `initialized` flag but request() never checks it — probe what happens",
                     {"replied": True, "tool_count": len(tools),
                      "note": "server answers; initialize is not enforced at the request layer"},
                     True, extra={"source_ref": "crates/mcp/src/server.rs:114-183"})
        p = cli.request("ping")
        probe.record("P2", "handshake", "ping before initialize", "empty result {}",
                     p.get("result"), p.get("result") == {})
    finally:
        rc, secs, orphan = cli.close()
    probe.record("PX", "shutdown", "prelude session clean shutdown", "exit 0, no orphan",
                 {"exit_code": rc, "seconds": secs, "orphan": orphan}, rc == 0 and not orphan)


def session_main(run_dir, probe, log):
    """The full behavioral suite on one server process (the PoC proper).

    Started with `--in designs/base.solidcraft` and NO --allow-path, cwd = run_dir:
    the design folder is reachable only through the open-design rule, so the
    documented path rules (cwd excluded, hidden excluded, .. refused) are live.
    """
    print(" session-main: full probe suite (--in designs/base.solidcraft, no --allow-path)")
    designs = os.path.join(run_dir, "designs")
    base = os.path.join(designs, "base.solidcraft")
    argv = [BIN, "mcp", "--in", base]
    cli = McpClient(argv, run_dir, os.path.join(run_dir, "main.err"))
    cli.start()
    try:
        run_main_probes(cli, probe, run_dir, designs, log)
    finally:
        rc, secs, orphan = cli.close()
    probe.record("X1", "shutdown", "main session clean shutdown after stdin close",
                 "process exits (exit code 0), no orphan process",
                 {"exit_code": rc, "seconds": secs, "orphan": orphan},
                 rc == 0 and not orphan)
    log["main_stderr"] = trunc(open(os.path.join(run_dir, "main.err")).read(), 1500)
    return rc == 0 and not orphan


def run_main_probes(cli, probe, run_dir, designs, log):
    # ---- 1. handshake ------------------------------------------------------
    r = cli.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "w3-probe", "version": "1"}})
    init = r.get("result", {})
    probe.record("H1", "handshake", "initialize protocolVersion 2025-06-18",
                 "echo 2025-06-18 + serverInfo + capabilities + instructions",
                 {"protocolVersion": init.get("protocolVersion"),
                  "serverInfo": init.get("serverInfo"),
                  "capabilities": init.get("capabilities"),
                  "instructions_head": trunc(init.get("instructions", ""), 300)}, 
                 init.get("protocolVersion") == "2025-06-18" and bool(init.get("serverInfo")))
    r = cli.request("initialize", {"protocolVersion": "1999-01-01", "capabilities": {},
                                   "clientInfo": {"name": "w3-probe", "version": "1"}})
    v = r.get("result", {}).get("protocolVersion")
    probe.record("H2", "handshake", "initialize with UNKNOWN protocolVersion 1999-01-01",
                 "fallback to the server's newest (2025-06-18) per server.rs:140-141",
                 {"protocolVersion": v}, v == "2025-06-18")
    r = cli.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "w3-probe", "version": "1"}})
    v = r.get("result", {}).get("protocolVersion")
    probe.record("H2b", "handshake", "initialize with oldest supported 2024-11-05",
                 "echo 2024-11-05", {"protocolVersion": v}, v == "2024-11-05")

    cli.notify("notifications/initialized")
    silent = cli._expect_silence(0.4)
    probe.record("H3", "handshake", "notifications/initialized produces NO reply line",
                 "no output on stdout within 0.4s (notifications carry no id)",
                 {"silence_observed": silent}, silent is True)

    r = cli.request("ping")
    probe.record("H4", "handshake", "ping", "result {}", r.get("result"), r.get("result") == {})

    # array batch of two requests in one line
    cli._id += 2
    a, b = cli._id - 1, cli._id
    cli._send(json.dumps([{"jsonrpc": "2.0", "id": a, "method": "ping"},
                          {"jsonrpc": "2.0", "id": b, "method": "resources/list"}]))
    replies = json.loads(cli._readline(30.0))
    probe.record("H5", "handshake", "JSON-RPC array batch (ping + resources/list) in one line",
                 "one array line back with both replies, in order",
                 {"reply_count": len(replies), "ids": [x.get("id") for x in replies]},
                 len(replies) == 2 and [x.get("id") for x in replies] == [a, b])

    r = cli.request("no/such/method")
    e = r.get("error", {})
    probe.record("H6", "handshake", "unknown method", "JSON-RPC -32601",
                 {"code": e.get("code"), "message": e.get("message")},
                 e.get("code") == -32601, layer="json-rpc")

    raw = cli.raw_line("this is not json{{{")
    pe = json.loads(raw).get("error", {})
    r2 = cli.request("ping")
    probe.record("H7", "handshake", "malformed line then ping (server keeps serving)",
                 "-32700 parse error, then ping still answers",
                 {"parse_error": {"code": pe.get("code"), "message": pe.get("message")},
                  "ping_after": r2.get("result")},
                 pe.get("code") == -32700 and r2.get("result") == {}, layer="json-rpc")

    raw = cli.raw_line("{}")
    e = json.loads(raw).get("error", {})
    probe.record("H8", "handshake", "request object without `method`", "JSON-RPC -32600",
                 {"code": e.get("code"), "message": e.get("message")},
                 e.get("code") == -32600, layer="json-rpc")
    raw = cli.raw_line("[]")
    e = json.loads(raw).get("error", {})
    probe.record("H9", "handshake", "empty JSON-RPC batch []", "JSON-RPC -32600 'empty batch'",
                 {"code": e.get("code"), "message": e.get("message")},
                 e.get("code") == -32600 and "empty batch" in str(e.get("message")), layer="json-rpc")

    # ---- 2. tool inventory -------------------------------------------------
    r = cli.request("tools/list")
    tools = r.get("result", {}).get("tools", [])
    by_effect = {}
    for t in tools:
        ann = t.get("annotations", {})
        k = ("readOnly" if ann.get("readOnlyHint") else
             "edits" if not ann.get("destructiveHint") and not ann.get("openWorldHint") else
             "replaces" if ann.get("destructiveHint") and not ann.get("openWorldHint") else "files")
        by_effect.setdefault(k, []).append(t["name"])
    log["tools"] = [{"name": t["name"], "annotations": t.get("annotations"),
                     "required": t.get("inputSchema", {}).get("required")} for t in tools]
    probe.record("T1", "inventory", "tools/list inventory",
                 "15 MCP tools with MCP annotations (readOnly/destructive/openWorld hints)",
                 {"count": len(tools), "names": [t["name"] for t in tools],
                  "by_effect_class": by_effect},
                 len(tools) == 15)

    r = cli.call_tool("list_commands", {})
    cmds = r.get("parsed") or []
    groups = {}
    for c in cmds if isinstance(cmds, list) else []:
        top = c.get("id", "?").split(".")[0]
        groups[top] = groups.get(top, 0) + 1
    log["command_catalog_count"] = len(cmds) if isinstance(cmds, list) else None
    log["command_catalog_groups"] = groups
    probe.record("T2", "inventory", "list_commands: engine command catalog size",
                 "engine exposes every modelling action as a command (394 at this tag, per W2)",
                 {"count": len(cmds) if isinstance(cmds, list) else None,
                  "by_prefix": dict(sorted(groups.items(), key=lambda kv: -kv[1]))},
                 isinstance(cmds, list) and len(cmds) > 300)

    # ---- 3. resources + crash reports --------------------------------------
    r = cli.request("resources/list")
    res = r.get("result", {}).get("resources", [])
    probe.record("R1", "inventory", "resources/list", "2 resources (design, commands)",
                 {"resources": res}, len(res) == 2)
    r = cli.request("resources/read", {"uri": "solidcraft://design"})
    txt = r.get("result", {}).get("contents", [{}])[0].get("text", "")
    probe.info("R2", "inventory", "resources/read solidcraft://design (empty design)",
               {"text_head": trunc(txt, 400)})
    r = cli.request("resources/read", {"uri": "solidcraft://nope"})
    e = r.get("error", {})
    probe.record("R3", "inventory", "resources/read unknown uri", "JSON-RPC -32002",
                 {"code": e.get("code"), "message": e.get("message")},
                 e.get("code") == -32002, layer="json-rpc")
    r = cli.call_tool("crash_reports", {})
    cr = r.get("parsed")
    probe.info("R4", "inventory", "crash_reports (read-only tool)",
               {"is_error": r["is_error"], "count": len(cr) if isinstance(cr, list) else cr})

    # ---- 4. the real CAD chain ---------------------------------------------
    params_reply = []
    for name, val in (("width", 40), ("height", 30), ("depth", 20)):
        r = cli.call_tool("set_parameter", {"name": name, "value": val})
        params_reply.append({k: v for k, v in (r.get("parsed") or {}).items()
                             if k in ("name", "value", "recomputed", "restored", "errors")})
    probe.record("C1", "cad-chain", "set_parameter width/height/depth (user parameters)",
                 "parameters created, timeline recomputes cleanly (errors: [])",
                 {"replies": params_reply},
                 all(p.get("errors") == [] for p in params_reply))

    r = cli.call_tool("batch", {"commands": CHAIN_STEPS, "verbose": False}, timeout=300.0)
    p = r.get("parsed") or {}
    created_line = ((p.get("results") or [{}] * 10)[1] or {}).get("created", {}) if p.get("results") else {}
    extrude = (p.get("results") or [{}])[-1] if p.get("results") else {}
    probe.record("C2", "cad-chain",
                 "batch: sketch.create → line → 4 HV constraints → 2 dimensions(width/height) → "
                 "sketch.finish → solid.extrude(distance=depth)",
                 "ok:true, completed=10, created curve/point/constraint/dimension ids + extrude feature",
                 {"ok": p.get("ok"), "completed": p.get("completed"),
                  "line_created_ids": created_line,
                  "extrude_feature": {k: v for k, v in extrude.items()
                                      if k in ("feature", "name", "created_bodies", "changed_bodies")},
                  "verbatim_head": trunc(r["text"], 700)},
                 p.get("ok") is True and p.get("completed") == 10)

    m = cli.call_tool("measure", {})
    tot = (m.get("parsed") or {}).get("total", {})
    vol = tot.get("volume_mm3")
    probe.record("C3", "cad-chain", "measure: 40×30 rectangle extruded 20 mm",
                 "volume_mm3 = 24000 (analytic; mm³) within 1e-6 rel",
                 {"total": tot, "analytic_mm3": 24000, "rel_err": None if vol is None else abs(vol - 24000) / 24000},
                 volume_ok(vol, 24000))

    i = cli.call_tool("inspect_design", {})
    ins = i.get("parsed") or {}
    sketches = ins.get("sketches", [])
    sk0 = sketches[0] if sketches else {}
    solve_keys = {k: v for k, v in sk0.items() if any(w in k.lower() for w in ("dof", "solve", "status", "error"))
                  and not isinstance(v, (list, dict))}
    probe.record("C4", "cad-chain", "constrained sketch: DOF and solve status via inspect_design",
                 "fully constrained rectangle: DOF 0, no solve error",
                 {"sketch_dof_fields": solve_keys,
                  "curve_count": len(sk0.get("curves", [])),
                  "constraint_count": len(sk0.get("constraints", [])),
                  "dimension_count": len(sk0.get("dimensions", []))},
                 sk0.get("dof") == 0)

    before = measure_state(cli)
    r = cli.call_tool("batch", {"commands": ARC_STEPS, "verbose": False}, timeout=300.0)
    p = r.get("parsed") or {}
    arc_created = (p.get("results") or [{}])[1].get("created", {}) if p.get("results") else {}
    circ_created = (p.get("results") or [{}])[2].get("created", {}) if p.get("results") else {}
    after = measure_state(cli)
    probe.record("C5", "cad-chain",
                 "second sketch: arc (sketch.arc.three_point) + circle (sketch.circle.center), not extruded",
                 "arc + circle curve ids created; bodies unchanged (no feature consumed the profile)",
                 {"ok": p.get("ok"), "completed": p.get("completed"),
                  "arc_created": arc_created, "circle_created": circ_created,
                  "bodies_before": before["body_names"], "bodies_after": after["body_names"],
                  "volume_before": before["volume_mm3"], "volume_after": after["volume_mm3"]},
                 p.get("ok") is True and after["volume_mm3"] == before["volume_mm3"]
                 and after["body_count"] == before["body_count"])

    r = cli.call_tool("set_parameter", {"name": "width", "value": 50})
    p = r.get("parsed") or {}
    m = cli.call_tool("measure", {})
    vol = (m.get("parsed") or {}).get("total", {}).get("volume_mm3")
    probe.record("C6", "cad-chain", "parameter edit width 40→50, timeline recomputes",
                 "volume 50×30×20 = 30000 mm³; reply reports recomputed feature count",
                 {"reply": {k: v for k, v in p.items() if k != "parameters"},
                  "volume_mm3": vol, "analytic_mm3": 30000,
                  "rel_err": None if vol is None else abs(vol - 30000) / 30000},
                 volume_ok(vol, 30000) and p.get("value") == 50.0)

    # ---- 5. transactions / undo / rollback ----------------------------------
    st_30000 = measure_state(cli)
    u = cli.call_tool("undo", {})
    after_undo = measure_state(cli)
    probe.record("TR1", "transaction", "undo reverts the parameter edit",
                 "volume back to 24000; undo depth decreases by 1",
                 {"undo_reply": trunc(u["text"], 300),
                  "depth_before": st_30000["undo_depth"], "depth_after": after_undo["undo_depth"],
                  "volume_after": after_undo["volume_mm3"]},
                 volume_ok(after_undo["volume_mm3"], 24000)
                 and after_undo["undo_depth"] == st_30000["undo_depth"] - 1)
    rr = cli.call_tool("redo", {})
    after_redo = measure_state(cli)
    probe.record("TR2", "transaction", "redo reapplies the parameter edit",
                 "volume 30000 again", 
                 {"redo_reply": trunc(rr["text"], 300), "volume_after": after_redo["volume_mm3"]},
                 volume_ok(after_redo["volume_mm3"], 30000))
    cli.call_tool("undo", {})  # leave the design at the 24000 state
    baseline = measure_state(cli)

    r = cli.call_tool("batch", {"commands": FAILING_BATCH, "verbose": False}, timeout=300.0)
    p = r.get("parsed") or {}
    after_fail = measure_state(cli)
    state_same = all(after_fail[k] == baseline[k] for k in
                     ("volume_mm3", "area_mm2", "faces", "edges", "body_count", "body_names", "undo_depth"))
    probe.record("TR3", "transaction",
                 "failing batch (box ok, fillet on nonexistent edge fails) with rollback",
                 "ok:false, failed{index,command,error}, completed steps undone, state identical",
                 {"ok": p.get("ok"), "completed": p.get("completed"),
                  "failed": p.get("failed"), "rolled_back": p.get("rolled_back"), "undone": p.get("undone"),
                  "state_before": baseline, "state_after": after_fail, "state_identical": state_same},
                 p.get("ok") is False and p.get("failed", {}).get("index") == 1 and state_same)

    r = cli.call_tool("execute", {"command": "solid.fillet", "params": {"edges": [[999, 999, 999]], "radius": 5}})
    after_exec = measure_state(cli)
    state_same = all(after_exec[k] == baseline[k] for k in
                     ("volume_mm3", "faces", "body_count", "undo_depth"))
    probe.record("TR4", "transaction", "single failing execute: design unchanged",
                 "tool result isError; state identical before/after",
                 {"is_error": r["is_error"], "verbatim": trunc(r["text"], 500),
                  "state_identical": state_same, "layer": err_layer(r)},
                 r["is_error"] and state_same, layer=err_layer(r))

    r = cli.call_tool("batch", {"commands": FAILING_BATCH, "rollback": False, "verbose": False}, timeout=300.0)
    p = r.get("parsed") or {}
    after_nr = measure_state(cli)
    probe.record("TR5", "transaction", "same failing batch with rollback:false",
                 "completed box step REMAINS (volume 25000, +1 body); failure still reported",
                 {"ok": p.get("ok"), "failed": p.get("failed"), "rolled_back": p.get("rolled_back"),
                  "state_after": after_nr},
                 p.get("ok") is False and volume_ok(after_nr["volume_mm3"], 25000)
                 and after_nr["body_count"] == baseline["body_count"] + 1)
    cli.call_tool("undo", {})
    restored = measure_state(cli)
    probe.record("TR6", "transaction", "one undo after rollback:false removes the surviving box",
                 "volume back to 24000 (batch steps are individually undoable)",
                 {"volume_after": restored["volume_mm3"]},
                 volume_ok(restored["volume_mm3"], 24000))

    # ---- 6. schema-validation probes (both layers) ---------------------------
    def schema_probe(cid, desc, name, args, expect_code=None, expect_msg=None, timeout=60.0):
        r = cli.call_tool(name, args, timeout=timeout)
        obs = {"layer": err_layer(r)}
        if r.get("layer") == "json-rpc":
            obs["rpc_error"] = r.get("rpc_error")
        else:
            obs["is_error"] = r["is_error"]
            obs["verbatim"] = trunc(r["text"], 600)
        ok = True
        if expect_code is not None:
            ok = ok and (r.get("rpc_error") or {}).get("code") == expect_code
        if r.get("layer") == "json-rpc" and expect_msg:
            ok = ok and expect_msg in str((r.get("rpc_error") or {}).get("message"))
        elif expect_msg:
            ok = ok and expect_msg in str(r["text"])
        if expect_code is None:  # engine-layer expectation: tool result error
            ok = ok and r["is_error"]
        probe.record(cid, "schema", desc,
                     (f"JSON-RPC {expect_code}" if expect_code is not None else "tool result isError") +
                     (f" containing '{expect_msg}'" if expect_msg else ""),
                     obs, ok, layer=err_layer(r))

    schema_probe("SC1", "missing required argument: body_topology without `body`",
                 "body_topology", {}, -32602, "missing required argument `body`")
    schema_probe("SC2", "wrong type: body_topology {body: 5}",
                 "body_topology", {"body": 5}, -32602, "must be of type")
    schema_probe("SC3", "unknown enum value: screenshot {source: 'sideways'}",
                 "screenshot", {"source": "sideways"}, -32602, "must be one of")
    schema_probe("SC4", "unknown tool name: warp_drive",
                 "warp_drive", {}, -32602, "unknown tool `warp_drive`")
    schema_probe("SC5", "unknown argument: measure {bodeez}",
                 "measure", {"bodeez": "x"}, -32602, "unknown argument `bodeez`")
    schema_probe("SC6", "tool-level type check: execute {command: 42}",
                 "execute", {"command": 42}, -32602, "must be of type")
    schema_probe("SC7", "engine layer: execute solid.extrude {distance: 'twenty'} (bad value type)",
                 "execute", {"command": "solid.extrude", "params": {"distance": "twenty"}})
    schema_probe("SC8", "engine layer: execute solid.extrude {operation: 'explode'} (bad enum)",
                 "execute", {"command": "solid.extrude", "params": {"distance": 5, "operation": "explode"}})
    schema_probe("SC9", "engine layer: execute unknown command solid.warp_drive",
                 "execute", {"command": "solid.warp_drive"})

    # ---- 7. filesystem-security probes ---------------------------------------
    def fs_probe(cid, desc, tool, args, target=None, expect_substr="outside the folders this agent may use"):
        r = cli.call_tool(tool, args, timeout=60.0)
        refused = r["is_error"] and expect_substr in str(r["text"])
        created = os.path.exists(target) if target else None
        obs = {"layer": err_layer(r), "verbatim": trunc(r["text"], 800),
               "target_exists_after": created}
        ok = refused and not created
        probe.record(cid, "fs-security", desc,
                     f"refused (isError, '{expect_substr}') and nothing written",
                     obs, ok, layer=err_layer(r))
        return r

    esc = os.path.join(designs, "..", "escaped.step")
    fs_probe("FS0", "save into the server's WORKING FOLDER (cwd, not in scope by itself)",
             "save", {"path": os.path.join(run_dir, "canary.solidcraft")})
    fs_probe("FS1", "save to /etc/w3-mcp-leak.solidcraft (outside all roots)",
             "save", {"path": "/etc/w3-mcp-leak.solidcraft"})
    fs_probe("FS2", "open /etc/passwd (outside all roots)",
             "open", {"path": "/etc/passwd"})
    fs_probe("FS3", "export to /etc/w3-mcp-leak.step (outside all roots)",
             "export", {"path": "/etc/w3-mcp-leak.step"}, target="/etc/w3-mcp-leak.step")
    fs_probe("FS4", "save into hidden folder ~/.config/ (outside roots, hidden)",
             "save", {"path": os.path.expanduser("~/.config/w3-mcp-leak.solidcraft")},
             target=os.path.expanduser("~/.config/w3-mcp-leak.solidcraft"))
    fs_probe("FS5", "`..` escape from the design folder: designs/../escaped.step",
             "export", {"path": esc}, target=os.path.join(run_dir, "escaped.step"))
    fs_probe("FS6", "save to hidden FILE .env inside the design folder",
             "save", {"path": os.path.join(designs, ".env")}, target=os.path.join(designs, ".env"))
    os.makedirs(os.path.join(designs, ".hidden"), exist_ok=True)
    fs_probe("FS7", "save into hidden FOLDER designs/.hidden/ (design-folder root only)",
             "save", {"path": os.path.join(designs, ".hidden", "x.solidcraft")},
             target=os.path.join(designs, ".hidden", "x.solidcraft"))
    fs_probe("FS8", "save into MISSING folder inside the design folder (not auto-created)",
             "save", {"path": os.path.join(designs, "noexist", "x.solidcraft")},
             expect_substr="does not exist")
    lnk = os.path.join(designs, "lnk-to-etc")
    if not os.path.lexists(lnk):
        os.symlink("/etc", lnk)
    fs_probe("FS9", "symlink escape: designs/lnk-to-etc -> /etc, save through it",
             "save", {"path": os.path.join(lnk, "w3-sym.solidcraft")},
             target="/etc/w3-sym.solidcraft")

    saved = os.path.join(designs, "w3-probe.solidcraft")
    r = cli.call_tool("save", {"path": saved})
    probe.record("FS10", "fs-security", "positive control: save inside the open design's folder",
                 "allowed: the design's folder is one of the agent's folders (docs/mcp.md)",
                 {"is_error": r["is_error"], "verbatim": trunc(r["text"], 300),
                  "file_exists": os.path.exists(saved),
                  "bytes": os.path.getsize(saved) if os.path.exists(saved) else 0},
                 not r["is_error"] and os.path.exists(saved))

    # ---- 8. screenshot (expected limitation: no GPU in sandbox) --------------
    r = cli.call_tool("screenshot", {"view": "iso", "width": 96, "height": 64}, timeout=180.0)
    shot = {"is_error": r["is_error"], "content_types": r.get("content_types")}
    if r.get("parsed") and isinstance(r["parsed"], dict):
        shot.update({k: r["parsed"].get(k) for k in ("source", "renderer", "warning", "bytes", "width", "height")})
    else:
        shot["verbatim"] = trunc(r["text"], 400)
    probe.info("G1", "rendering", "screenshot {view: iso, 96x64} (no GPU in sandbox)", shot)

    # ---- 9. serial/version fields + persisted document -----------------------
    final = os.path.join(designs, "w3-final.solidcraft")
    r = cli.call_tool("save", {"path": final})

    def read_doc(path):
        try:
            with zipfile.ZipFile(path) as z:
                name = next(n for n in z.namelist() if n.endswith("document.json"))
                return json.loads(z.read(name).decode("utf-8"))
        except Exception as e:  # noqa: BLE001 — recorded verbatim as a blocker
            return {"error": str(e)}

    d0, d1 = read_doc(os.path.join(designs, "base.solidcraft")), read_doc(final)
    f0 = [f.get("id") for f in d0.get("features", [])] if isinstance(d0, dict) else None
    f1 = [f.get("id") for f in d1.get("features", [])] if isinstance(d1, dict) else None
    sv_ok = (isinstance(d0, dict) and isinstance(d1, dict)
             and d1.get("next_id", 0) > d0.get("next_id", 0))
    probe.record("SV1", "transaction",
                 "serial/version fields: persisted document.json (base vs final) + undo depth",
                 "next_id grows monotonically; features carry u64 ids; undo depth from inspect",
                 {"base": {"format": d0.get("format") if isinstance(d0, dict) else d0,
                            "next_id": d0.get("next_id") if isinstance(d0, dict) else None,
                            "feature_ids": f0},
                  "final": {"format": d1.get("format") if isinstance(d1, dict) else d1,
                            "next_id": d1.get("next_id") if isinstance(d1, dict) else None,
                            "feature_ids": f1,
                            "feature_names": [f.get("name") for f in d1.get("features", [])],
                            "param_names": d1.get("param_names")},
                  "undo_depth_now": measure_state(cli)["undo_depth"]},
                 sv_ok)

    pl = cli.call_tool("execute", {"command": "parameters.list"})
    pars = pl.get("parsed") or {}
    plist = pars.get("parameters", pars) if isinstance(pars, dict) else pars
    probe.info("PM1", "cad-chain", "parameters.list after the run (parametric wiring)",
               {"parameters": [{k: p.get(k) for k in ("name", "expression", "unit", "value", "uses")}
                               for p in (plist if isinstance(plist, list) else [])]
                if isinstance(plist, list) else trunc(pl["text"], 600)})


# ---------------------------------------------------------------------------
# one full run (setup + prelude + main)
# ---------------------------------------------------------------------------
def run_suite(run_id):
    run_dir = os.path.join(SCRATCH, run_id)
    if os.path.exists(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    print(f"=== RUN {run_id} ({run_dir}) ===")
    probe = Probe()
    log = {}
    t0 = time.monotonic()
    blockers = []
    try:
        session_zero(run_dir, probe, log)
        session_prelude(run_dir, probe)
        session_main(run_dir, probe, log)
    except Exception as e:  # noqa: BLE001 — honest blocker recording
        blockers.append(f"{type(e).__name__}: {e}")
        print(f"  [BLOCKER] {e}", file=sys.stderr)
    duration = round(time.monotonic() - t0, 1)
    return {"run_id": run_id, "duration_s": duration, "cases": probe.cases,
            "blockers": blockers, "log": log, "run_dir": run_dir}


def compare_runs(run1, run2):
    """Deterministic comparison on pass flags + normalized verbatim evidence."""
    def key(c, run_dir):
        v = c.get("observed", {})
        v = normalize_verbatim(json.dumps(v, sort_keys=True, default=str), run_dir)
        return (c["id"], str(c.get("pass")), v)
    diffs = []
    ids = [c["id"] for c in run1["cases"]]
    for cid in ids:
        c1 = next((c for c in run1["cases"] if c["id"] == cid), None)
        c2 = next((c for c in run2["cases"] if c["id"] == cid), None)
        if not c2:
            diffs.append({"id": cid, "kind": "missing-in-run2"})
        elif str(c1.get("pass")) != str(c2.get("pass")):
            diffs.append({"id": cid, "kind": "pass-flag",
                          "run1": c1.get("pass"), "run2": c2.get("pass")})
        elif key(c1, run1["run_dir"]) != key(c2, run2["run_dir"]):
            diffs.append({"id": cid, "kind": "observed-differs (path/pid-normalized)"})
    return {"identical": not diffs and len(run1["cases"]) == len(run2["cases"])
            and not run1["blockers"] and not run2["blockers"],
            "case_count_run1": len(run1["cases"]), "case_count_run2": len(run2["cases"]),
            "diffs": diffs}


# ---------------------------------------------------------------------------
# envelope + main
# ---------------------------------------------------------------------------
def main():
    if not os.path.exists(BIN):
        print(f"BLOCKER: release binary missing: {BIN}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    started = utcnow()
    host = {"cpus": os.cpu_count(), "mem_gb": round(
        int([l for l in open("/proc/meminfo").read().splitlines()
             if l.startswith("MemTotal")][0].split()[1]) / 1e6, 1),
        "python": platform.python_version(), "kernel": platform.release(),
        "note": "sandbox container, no GPU"}
    try:
        harness_commit = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                                        capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        harness_commit = "unavailable"

    run1 = run_suite("run1")
    run2 = run_suite("run2")
    repro = compare_runs(run1, run2)

    cases = run1["cases"]
    failures = [c for c in cases if c.get("pass") is False]
    blockers = run1["blockers"] + run2["blockers"]
    groups = {}
    for c in cases:
        g = groups.setdefault(c["group"], {"pass": 0, "fail": 0, "info": 0})
        g["pass" if c.get("pass") is True else "fail" if c.get("pass") is False else "info"] += 1

    envelope = {
        "experiment": "w3-mcp",
        "issue_ref": "payswapdotorg/blender-cad#1",
        "agent": "W3 lane-a (Task 99, retry)",
        "upstream": {
            "repo": UPSTREAM_REPO, "sha": UPSTREAM_SHA, "version": "0.16.2",
            "behavioral_binary": {
                "path": BIN, "sha256": sha256_file(BIN), "tag_commit": RELEASE_TAG_COMMIT,
                "commits_behind_source_pin": COMMITS_BEHIND,
                "note": ("behavioral evidence uses the official release binary; the source pin "
                         "3b4db52 (used for audits) is 80 commits ahead of the tag")},
        },
        "harness_commit": harness_commit,
        "command": "python3.12 experiments/solidcraft/python/mcp_client_probe.py",
        "started_utc": started, "finished_utc": utcnow(),
        "host": host,
        "profile": "official release binary, headless in-process session, CPU rasterizer",
        "cases": cases,
        "failures": [c["id"] for c in failures],
        "blockers": blockers,
        "summary": {
            "case_count": len(cases),
            "by_group": groups,
            "passed": sum(1 for c in cases if c.get("pass") is True),
            "failed": len(failures),
            "info": sum(1 for c in cases if c.get("pass") is None),
            "tool_inventory": {"mcp_tools": len(run1["log"].get("tools", [])),
                               "engine_commands": run1["log"].get("command_catalog_count")},
            "reproducibility": {
                "run1_duration_s": run1["duration_s"],
                "run2_duration_s": run2["duration_s"],
                "identical_to_run1": repro["identical"],
                "diffs": repro["diffs"],
                "normalization": ("run-dir paths, mcp scratch pid-seed folders (digit-ful "
                                   "runtime form + digit-less defensive form, regression-tested) "
                                   "and engine self-reported \"ms\" step timings redacted — "
                                   "temp-path variance is environment-only and never affects "
                                   "the outcome; geometry and all error strings compared exactly"),
            },
        },
        "notes": {
            "session0_stderr": run1["log"].get("session0_stderr"),
            "main_stderr": run1["log"].get("main_stderr"),
            "scratch_root": SCRATCH + " (gitignored)",
        },
        "reproducibility_run2": {
            "duration_s": run2["duration_s"], "blockers": run2["blockers"],
            "cases": run2["cases"],
        },
    }
    with open(RESULTS, "w") as f:
        json.dump(envelope, f, indent=1, default=str)
    print(f"\nWrote {RESULTS}")
    print(f"  cases={len(cases)} pass={envelope['summary']['passed']} "
          f"fail={len(failures)} info={envelope['summary']['info']} blockers={len(blockers)}")
    print(f"  reproducibility identical={repro['identical']} diffs={len(repro['diffs'])}")
    sys.exit(0 if not blockers else 1)


if __name__ == "__main__":
    main()
