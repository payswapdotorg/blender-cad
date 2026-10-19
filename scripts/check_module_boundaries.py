#!/usr/bin/env python3
"""Check modules/modules.json and module directories against glossary §4.

Validates:
  - schema_version == 1
  - exactly the 13 module keys
  - every module directory exists and carries a README.md
  - depends_on members all exist
  - owner in {TL, W1, W2, W3}
  - status in {planned, in-progress, active}
  - fp_areas drawn from the 14 inventory area codes (glossary §5)
  - dependency graph is acyclic (module "testing" is exempt: test-only)

Prints the full edge list and "OK: N modules, no cycles" on success.
Exit codes: 0 = consistent; 1 = violations (each printed to stderr).
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_FILE = REPO_ROOT / "modules" / "modules.json"

EXPECTED_MODULES = [
    "document", "kernel", "drafting", "parametric", "drawings", "interchange",
    "bim", "toolsets", "commands", "agent", "skills", "shell", "testing",
]
ALLOWED_OWNERS = ["TL", "W1", "W2", "W3"]
ALLOWED_STATUS = ["planned", "in-progress", "active"]
AREA_CODES = [
    "CMD", "DRAW", "MOD", "PREC", "ORG", "ANN", "LAY", "P3D", "PAR",
    "IO", "TS", "UX", "AGT", "SKL",
]
TEST_ONLY_EXEMPT = "testing"


def find_cycle(graph):
    """Return a cycle path (list of nodes) in `graph`, or None.

    `graph` maps node -> list of dependency nodes. Nodes absent from the
    graph are ignored — that is how the test-only exemption is applied.
    Iterative-safe recursive DFS (graph has at most 13 nodes).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}

    def visit(node, path):
        color[node] = GRAY
        path.append(node)
        for dep in graph[node]:
            if dep not in graph:
                continue
            if color[dep] == GRAY:
                return path[path.index(dep):] + [dep]
            if color[dep] == WHITE:
                cycle = visit(dep, path)
                if cycle:
                    return cycle
        path.pop()
        color[node] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            cycle = visit(node, [])
            if cycle:
                return cycle
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate modules/modules.json, module directories and the "
                    "dependency graph (glossary §4 boundary rules)."
    )
    parser.parse_args(argv)

    errors = []
    edges = []

    if not MODULES_FILE.is_file():
        print(f"ERROR: {MODULES_FILE} not found", file=sys.stderr)
        return 1
    try:
        data = json.loads(MODULES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot parse {MODULES_FILE}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        print("ERROR: modules.json: schema_version must be 1", file=sys.stderr)
        return 1

    modules = data.get("modules")
    if not isinstance(modules, dict):
        print("ERROR: modules.json: 'modules' must be an object", file=sys.stderr)
        return 1

    names = set(modules)
    for missing in sorted(set(EXPECTED_MODULES) - names):
        errors.append(f"modules.json: missing module '{missing}'")
    for extra in sorted(names - set(EXPECTED_MODULES)):
        errors.append(f"modules.json: unexpected module '{extra}' (expected exactly the 13 modules)")

    for name in sorted(names):
        module = modules[name]
        if not isinstance(module, dict):
            errors.append(f"modules.json: module '{name}' must be an object")
            continue
        owner = module.get("owner")
        if owner not in ALLOWED_OWNERS:
            errors.append(f"modules.json: module '{name}': owner {owner!r} not in {ALLOWED_OWNERS}")
        status = module.get("status")
        if status not in ALLOWED_STATUS:
            errors.append(f"modules.json: module '{name}': status {status!r} not in {ALLOWED_STATUS}")
        fp_areas = module.get("fp_areas", [])
        if not isinstance(fp_areas, list):
            errors.append(f"modules.json: module '{name}': fp_areas must be a list")
            fp_areas = []
        for area in fp_areas:
            if area not in AREA_CODES:
                errors.append(
                    f"modules.json: module '{name}': fp_area {area!r} is not one of the 14 area codes"
                )
        summary = module.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"modules.json: module '{name}': summary must be a non-empty string")
        deps = module.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(f"modules.json: module '{name}': depends_on must be a list")
            deps = []
        for dep in deps:
            if dep not in names:
                errors.append(f"modules.json: module '{name}': depends_on references unknown module '{dep}'")
            edges.append((name, dep))
        module_readme = REPO_ROOT / "modules" / name / "README.md"
        if not module_readme.is_file():
            errors.append(f"modules/{name}/README.md: missing (every module must ship a README)")

    if errors:
        print("check_module_boundaries: violations found:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    # Cycle check over the dependency graph excluding the test-only module.
    graph = {
        name: [dep for dep in modules[name].get("depends_on", []) if dep != TEST_ONLY_EXEMPT]
        for name in modules
        if name != TEST_ONLY_EXEMPT
    }
    cycle = find_cycle(graph)
    if cycle:
        print(f"ERROR: dependency cycle detected: {' -> '.join(cycle)}", file=sys.stderr)
        return 1

    print("Dependency edges (module -> dependency):")
    for name, dep in edges:
        print(f"  {name} -> {dep}")
    print(
        f"OK: {len(modules)} modules, no cycles "
        f"(module '{TEST_ONLY_EXEMPT}' exempt from cycle rules: test-only)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
