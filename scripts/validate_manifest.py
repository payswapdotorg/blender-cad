#!/usr/bin/env python3
"""Validate every release-manifests/manifest-*.json against glossary §8.

Checks per manifest:
  - schema_version == 1; product == "blender-cad"
  - version matches ^\\d+\\.\\d+\\.\\d+(-[0-9A-Za-z.\\-]+)?$ (semver, pre-release allowed)
  - created is a real ISO date (YYYY-MM-DD)
  - status is a non-empty string
  - components.{blender,zcode_runtime,cad_extension} present with required fields
  - components.blender.upstream_ref is a 40-hex SHA
  - components.zcode_runtime.upstream_ref is a 40-hex SHA or starts with "pending:"
  - components.cad_extension.commit is a 7- or 40-hex SHA or the literal "self-at-release"
  - dependencies: non-empty list; each item carries name/license/role/module/status;
    module must be one of the 13 modules (loaded from modules/modules.json);
    status in {candidate, adopted, rejected}
  - notes present as a string

Exit codes: 0 = all manifests valid; 1 = any failure (each named file+rule).
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "release-manifests"
MODULES_FILE = REPO_ROOT / "modules" / "modules.json"

VERSION_RE_STR = r"^\d+\.\d+\.\d+(-[0-9A-Za-z.\-]+)?$"
VERSION_RE = re.compile(VERSION_RE_STR)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7}$|^[0-9a-fA-F]{40}$")

ALLOWED_DEP_STATUS = ["candidate", "adopted", "rejected"]

# Required fields per component (glossary §8 plus the manifest-0.1.0.json shape)
COMPONENT_REQUIRED = {
    "blender": ["role", "upstream", "upstream_ref", "upstream_branch", "fork", "fork_branch", "license"],
    "zcode_runtime": ["role", "upstream", "upstream_ref", "upstream_branch", "fork", "license"],
    "cad_extension": ["role", "repo", "commit"],
}


def load_module_names():
    """Return the 13 module names from modules/modules.json."""
    if not MODULES_FILE.is_file():
        raise RuntimeError(f"{MODULES_FILE} not found")
    data = json.loads(MODULES_FILE.read_text(encoding="utf-8"))
    modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(modules, dict) or not modules:
        raise RuntimeError(f"{MODULES_FILE}: no modules found")
    return sorted(modules)


def validate_manifest(path, module_names):
    errors = []

    def bad(rule, detail):
        errors.append(f"{path.name}: [{rule}] {detail}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{path.name}: FAILED — cannot read/parse JSON: {exc}", file=sys.stderr)
        return False
    if not isinstance(data, dict):
        print(f"{path.name}: FAILED — top level must be a JSON object", file=sys.stderr)
        return False

    if data.get("schema_version") != 1:
        bad("schema_version", f"expected 1, got {data.get('schema_version')!r}")
    if data.get("product") != "blender-cad":
        bad("product", f"expected 'blender-cad', got {data.get('product')!r}")

    version = data.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        bad("version", f"{version!r} does not match {VERSION_RE_STR}")

    created = data.get("created")
    if not isinstance(created, str) or not DATE_RE.match(created):
        bad("created", f"{created!r} is not an ISO date (YYYY-MM-DD)")
    else:
        try:
            date.fromisoformat(created)
        except ValueError:
            bad("created", f"{created!r} is not a real calendar date")

    status = data.get("status")
    if not isinstance(status, str) or not status.strip():
        bad("status", "must be a non-empty string (e.g. 'm0-handoff')")

    components = data.get("components")
    if not isinstance(components, dict):
        bad("components", "must be an object with keys blender, zcode_runtime, cad_extension")
        components = {}

    blender = components.get("blender")
    if not isinstance(blender, dict):
        bad("components.blender", "must be an object")
    else:
        for field in COMPONENT_REQUIRED["blender"]:
            if field not in blender:
                bad("components.blender", f"missing required field '{field}'")
        ref = blender.get("upstream_ref")
        if not isinstance(ref, str) or not SHA40_RE.match(ref):
            bad("components.blender.upstream_ref", f"{ref!r} is not a 40-hex SHA")

    zcode = components.get("zcode_runtime")
    if not isinstance(zcode, dict):
        bad("components.zcode_runtime", "must be an object")
    else:
        for field in COMPONENT_REQUIRED["zcode_runtime"]:
            if field not in zcode:
                bad("components.zcode_runtime", f"missing required field '{field}'")
        ref = zcode.get("upstream_ref")
        if not isinstance(ref, str) or not (SHA40_RE.match(ref) or ref.startswith("pending:")):
            bad(
                "components.zcode_runtime.upstream_ref",
                f"{ref!r} is not a 40-hex SHA and does not start with 'pending:'",
            )

    cad = components.get("cad_extension")
    if not isinstance(cad, dict):
        bad("components.cad_extension", "must be an object")
    else:
        for field in COMPONENT_REQUIRED["cad_extension"]:
            if field not in cad:
                bad("components.cad_extension", f"missing required field '{field}'")
        commit = cad.get("commit")
        if not isinstance(commit, str) or not (COMMIT_RE.match(commit) or commit == "self-at-release"):
            bad("components.cad_extension.commit", f"{commit!r} is not a 7/40-hex SHA or 'self-at-release'")

    dependencies = data.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        bad("dependencies", "must be a non-empty list")
        dependencies = []
    for index, dep in enumerate(dependencies, start=1):
        if not isinstance(dep, dict):
            bad("dependencies", f"item #{index} must be an object")
            continue
        name = dep.get("name", "?")
        for field in ("name", "license", "role", "module", "status"):
            if field not in dep:
                bad("dependencies", f"item #{index} ({name}): missing '{field}'")
        if "module" in dep and dep["module"] not in module_names:
            bad(
                "dependencies",
                f"item #{index} ({name}): module {dep['module']!r} is not one of the "
                "13 modules in modules/modules.json",
            )
        if "status" in dep and dep["status"] not in ALLOWED_DEP_STATUS:
            bad("dependencies", f"item #{index} ({name}): status {dep['status']!r} not in {ALLOWED_DEP_STATUS}")

    notes = data.get("notes")
    if not isinstance(notes, str):
        bad("notes", "must be present as a string")

    if errors:
        print(f"{path.name}: FAILED — {len(errors)} rule violation(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    print(f"OK: {path.name} — version {version}, status {status}, {len(dependencies)} dependencies validated")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate release-manifests/manifest-*.json against the glossary §8 schema."
    )
    parser.parse_args(argv)

    try:
        module_names = load_module_names()
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    files = sorted(MANIFEST_DIR.glob("manifest-*.json"))
    if not files:
        print(f"ERROR: no release manifests found in {MANIFEST_DIR}", file=sys.stderr)
        return 1

    all_ok = True
    for path in files:
        if not validate_manifest(path, module_names):
            all_ok = False
    if not all_ok:
        print("validate_manifest: one or more manifests FAILED", file=sys.stderr)
        return 1
    print(f"validated {len(files)} release manifest(s), all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
