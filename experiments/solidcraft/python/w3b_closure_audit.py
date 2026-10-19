#!/usr/bin/env python3
"""W3-b supply-chain closure audit.

Enumerates the two reuse closures of the SolidCraft evaluation harness from the
harness's own locked dependency metadata (`cargo metadata --locked`, generated
against harness/Cargo.lock) and cross-checks every version against
harness/Cargo.lock itself. Output feeds results/w3b-supply-chain.json.

Closures (from findings/w1-sketch.md + w2-history.md reuse paths):
  1. sketch solver:   solidcraft-sketch + solidcraft-geom (candidate #1)
  2. kernel+doc:      solidcraft-kernel + solidcraft-doc (candidates #2/#3/#4,
                      only if adapted)

Semantics:
  - dev-dependencies (test-only) are EXCLUDED;
  - build-dependencies (build scripts) are included; a package reachable ONLY
    through build edges is flagged build_only=true;
  - target-gated dependencies (cfg(...)) are included in the cross-platform
    closure and each row records whether it is active on the evaluation/ship
    host triple x86_64-unknown-linux-gnu (`on_linux_x86_64`);
  - proc-macro crates (compile-time code execution) are flagged.

Read-only: writes nothing outside /tmp; prints JSON to stdout.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

META = "/tmp/meta-full.json"  # cd harness && cargo metadata --locked --format-version 1
# Verification-pass fix (Task 103): repo-relative (was an absolute dev-host path).
LOCK = Path(__file__).resolve().parents[1] / "harness" / "Cargo.lock"
HOST = {"target_arch": "x86_64", "target_os": "linux",
        "target_vendor": "unknown", "target_env": "gnu"}

CLOSURES = {
    "closure1_sketch_solver": ["solidcraft-sketch", "solidcraft-geom"],
    "closure2_kernel_doc": ["solidcraft-kernel", "solidcraft-doc"],
}

NONSTANDARD_SPDX = {"Unicode-3.0", "CDLA-Permissive-2.0", "BSL-1.0",
                    "Unlicense OR MIT", "Unlicense",
                    "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT",
                    "MIT OR Apache-2.0 OR LGPL-2.1-or-later"}

PLAIN_PERMISSIVE = {
    "MIT", "Apache-2.0", "MIT OR Apache-2.0", "Apache-2.0 OR MIT",
    "MIT/Apache-2.0", "Apache-2.0/MIT", "BSD-3-Clause", "BSD-2-Clause",
    "ISC", "Zlib", "0BSD", "MPL-2.0",
    "MIT OR Apache-2.0 OR Zlib", "Zlib OR Apache-2.0 OR MIT",
    "Apache-2.0 AND ISC", "Apache-2.0 AND MIT",
    "(MIT OR Apache-2.0) AND Unicode-3.0",
}


def cfg_active(expr: str | None) -> bool:
    """Evaluate a cfg(...) expression string for the host triple."""
    if expr is None:
        return True
    m = re.fullmatch(r"cfg\((.*)\)", expr.strip())
    if not m:
        return True  # unparsed -> assume active (conservative)
    body = m.group(1)

    def tok(s):
        return [t.strip().strip('"') for t in re.split(r"[(),]+", s) if t.strip()]

    def parse(s):
        s = s.strip()
        low = s.lower()
        if low.startswith("not(") or low.startswith("not ("):
            inner = s[3:].strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1]
            return ("not", parse(inner))
        if low.startswith("any(") or low.startswith("all("):
            op = "any" if low.startswith("any") else "all"
            inner = s[len(op):].strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1]
            # split top-level commas
            parts, depth, cur = [], 0, ""
            for ch in inner:
                if ch == "(":
                    depth += 1
                if ch == ")":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            if cur.strip():
                parts.append(cur)
            return (op, [parse(p) for p in parts])
        if "=" in s:
            k, v = [x.strip().strip('"') for x in s.split("=", 1)]
            return ("eq", k, v)
        return ("flag", s)

    def ev(node):
        if node[0] == "not":
            return not ev(node[1])
        if node[0] == "any":
            return any(ev(c) for c in node[1])
        if node[0] == "all":
            return all(ev(c) for c in node[1])
        if node[0] == "eq":
            return HOST.get(node[1]) == node[2]
        if node[0] == "flag":
            return {"unix": True, "windows": False, "wasm32": False,
                    "debug_assertions": False}.get(node[1], False)
        return False

    return ev(parse(body))


def is_proc_macro(pkg) -> bool:
    mp = pkg.get("manifest_path")
    if not mp or not Path(mp).exists():
        return False
    try:
        text = Path(mp).read_text(errors="replace")
    except OSError:
        return False
    lib = re.search(r"^\[lib\][^\[]*", text, re.M | re.S)
    return bool(lib and re.search(r"^\s*proc-macro\s*=\s*true", lib.group(0), re.M))


def main() -> int:
    meta = json.load(open(META))
    packages = {p["id"]: p for p in meta["packages"]}
    by_name = defaultdict(list)
    for p in meta["packages"]:
        by_name[p["name"]].append(p)

    # edge builder: (from, to) -> set of (kind, target_expr); kind None == normal
    edges = defaultdict(lambda: defaultdict(set))
    for n in meta["resolve"]["nodes"]:
        for d in n["deps"]:
            for dk in d.get("dep_kinds", [{"kind": None, "target": None}]):
                kind, target = dk.get("kind"), dk.get("target")
                if kind == "dev":
                    continue
                edges[n["id"]][d["pkg"]].add((kind, target))

    def resolve(name):
        cands = by_name.get(name, [])
        if len(cands) != 1:
            sys.exit(f"FATAL: expected exactly one '{name}', got {sorted(c['id'] for c in cands)}")
        return cands[0]

    def closure(roots, host_only=False):
        """BFS over edges; returns id -> {via_normal, via_build, cfgs}."""
        info = {}

        def visit(pid, via_normal, cfgs):
            rec = info.setdefault(pid, {"via_normal": False, "via_build": False, "cfgs": set()})
            changed = False
            if via_normal and not rec["via_normal"]:
                rec["via_normal"] = True
                changed = True
            if not via_normal and not rec["via_build"]:
                rec["via_build"] = True
                changed = True
            before = len(rec["cfgs"])
            rec["cfgs"] |= cfgs
            changed = changed or len(rec["cfgs"]) > before
            return changed

        queue = [(resolve(r)["id"], True, frozenset()) for r in roots]
        while queue:
            pid, via_normal, cfgs = queue.pop()
            if not visit(pid, via_normal, cfgs):
                continue
            for dep, kinds in edges.get(pid, {}).items():
                for kind, target in kinds:
                    if host_only and not cfg_active(target):
                        continue
                    # a build edge or an inactive-on-host target edge -> build/scope only
                    next_normal = via_normal and kind is None
                    next_cfgs = cfgs | (frozenset([target]) if target else frozenset())
                    queue.append((dep, next_normal, next_cfgs))
        return info

    lock_versions = {}
    for block in open(LOCK).read().split("[[package]]"):
        m, v = re.search(r'^name = "(.+)"$', block, re.M), re.search(r'^version = "(.+)"$', block, re.M)
        if m and v:
            lock_versions.setdefault(m.group(1), set()).add(v.group(1))

    proc_cache = {}

    def row(pkg, info, host_info):
        pid = pkg["id"]
        if pid not in proc_cache:
            proc_cache[pid] = is_proc_macro(pkg)
        manifest = str(pkg.get("manifest_path", ""))
        lic = pkg.get("license") or "(no license field in Cargo.toml)"
        cfgs = sorted(c for c in info["cfgs"] if c)
        flags = []
        if lic in NONSTANDARD_SPDX:
            flags.append(f"nonstandard-spdx:{lic}")
        if "GPL" in lic:
            flags.append(f"gpl-option-present:{lic}")
        if pkg.get("links"):
            flags.append(f"native-links:{pkg['links']}")
        if proc_cache[pid]:
            flags.append("proc-macro (compile-time execution)")
        if lic not in PLAIN_PERMISSIVE and lic not in NONSTANDARD_SPDX:
            flags.append(f"unlisted-license:{lic}")
        on_host = pid in host_info and host_info[pid]["via_normal"] or (pid in host_info and host_info[pid]["via_build"])
        return {
            "name": pkg["name"], "version": pkg["version"], "license": lic,
            "source": ("vendored (SolidCraft-patched)" if "/vendor/" in manifest
                       else "path (upstream workspace crate)" if "/.upstream/crates/" in manifest
                       else "crates.io registry"),
            "build_only": not info["via_normal"],
            "on_linux_x86_64": pid in host_info,
            "target_cfgs": cfgs,
            "in_lock": pkg["version"] in lock_versions.get(pkg["name"], set()),
            "links": pkg.get("links"),
            "proc_macro": proc_cache[pid],
            "risk_flags": flags,
        }

    results = {}
    for label, roots in CLOSURES.items():
        info = closure(roots)
        host_info = closure(roots, host_only=True)
        rows = [row(packages[pid], info[pid], host_info)
                for pid in sorted(info, key=lambda i: (packages[i]["name"], packages[i]["version"]))]
        missing = [r["name"] for r in rows if not r["in_lock"]]
        gpl = [r for r in rows if "GPL" in r["license"]]
        results[label] = {
            "roots": roots,
            "package_count": len(rows),
            "cross_platform_count": len(rows),
            "on_linux_x86_64_count": sum(1 for r in rows if r["on_linux_x86_64"]),
            "build_only_count": sum(1 for r in rows if r["build_only"]),
            "target_specific_count": sum(1 for r in rows if not r["on_linux_x86_64"] and not r["build_only"]),
            "gpl_licenses_found": [f"{r['name']} {r['version']}: {r['license']}" for r in gpl],
            "license_set": sorted({r["license"] for r in rows}),
            "lock_cross_check": ("all versions present in harness Cargo.lock"
                                 if not missing else f"MISSING FROM LOCK: {missing}"),
            "rows": rows,
        }

    json.dump(results, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
