#!/usr/bin/env python3
"""Assemble the Blender CAD extension package from module-owned sources.

Binding per docs/00-architecture/m1-module-contracts.md §2:
  source of truth = modules/<module>/<pkg>/ + modules/shell/ext/blender_cad/
  artifact        = dist/blender_cad-<version>.zip (blender_manifest.toml at zip root)

The build is deterministic and content-free: it only COPIES files (no code
generation, no vendoring, no network). Built artifacts are never committed.

Usage:
  python3 scripts/build_extension.py            # build into build/ + dist/
  python3 scripts/build_extension.py --check    # verify dist/ is up to date
Exit codes: 0 ok, 1 error (message on stderr).
"""

import argparse
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_SRC = REPO_ROOT / "modules" / "shell" / "ext" / "blender_cad"
BUILD = REPO_ROOT / "build" / "blender_cad"
DIST = REPO_ROOT / "dist"

# module package -> source dir (contracts §2 table; M2 §1 adds bcdraw
# BEFORE bcshell — dependency order)
PACKAGES = {
    "bcdoc": REPO_ROOT / "modules" / "document" / "bcdoc",
    "bcio": REPO_ROOT / "modules" / "interchange" / "bcio",
    "bccmd": REPO_ROOT / "modules" / "commands" / "bccmd",
    "bcdraft": REPO_ROOT / "modules" / "drafting" / "bcdraft",
    "bcdraw": REPO_ROOT / "modules" / "drawings" / "bcdraw",
    "bcshell": REPO_ROOT / "modules" / "shell" / "bcshell",
    "bcagent": REPO_ROOT / "modules" / "agent" / "bcagent",
}

EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_DIRS = {"__pycache__", "tests", ".pytest_cache", ".git"}


def manifest_version() -> str:
    text = (EXT_SRC / "blender_manifest.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("version"):
            return s.split("=", 1)[1].strip().strip('"')
    raise SystemExit("blender_manifest.toml: no version field")


def copy_tree(src: Path, dst: Path) -> list[Path]:
    out = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(src).parts):
            continue
        if p.suffix in EXCLUDE_SUFFIXES:
            continue
        rel = p.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
        out.append(target)
    return out


def build() -> Path:
    if not EXT_SRC.is_dir():
        raise SystemExit(f"missing extension source: {EXT_SRC}")
    missing = [str(v) for v in PACKAGES.values() if not (v / "__init__.py").is_file()]
    if missing:
        raise SystemExit("missing package __init__.py: " + ", ".join(missing))

    if BUILD.exists():
        for p in sorted(BUILD.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
    BUILD.mkdir(parents=True, exist_ok=True)
    copied = copy_tree(EXT_SRC, BUILD)
    for name, src in PACKAGES.items():
        copied += copy_tree(src, BUILD / name)

    version = manifest_version()
    DIST.mkdir(parents=True, exist_ok=True)
    zpath = DIST / f"blender_cad-{version}.zip"
    if zpath.exists():
        zpath.unlink()
    # manifest at zip ROOT (Blender extension spec)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(BUILD.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(BUILD).as_posix())
    print(f"built {zpath.name}: {len(copied)} files, {zpath.stat().st_size} bytes")
    return zpath


def check() -> int:
    version = manifest_version()
    zpath = DIST / f"blender_cad-{version}.zip"
    if not zpath.is_file():
        print(f"CHECK FAILED: {zpath} missing", file=sys.stderr)
        return 1
    with zipfile.ZipFile(zpath) as zf:
        names = set(zf.namelist())
    required = {"blender_manifest.toml", "__init__.py"} | {
        f"{pkg}/__init__.py" for pkg in PACKAGES
    }
    missing = required - names
    if missing:
        print("CHECK FAILED: zip missing: " + ", ".join(sorted(missing)), file=sys.stderr)
        return 1
    # freshness: every source file must exist in the zip with identical size
    for name, src in PACKAGES.items():
        for p in src.rglob("*"):
            if not p.is_file() or any(part in EXCLUDE_DIRS for part in p.relative_to(src).parts):
                continue
            rel = f"{name}/{p.relative_to(src).as_posix()}"
            if rel not in names:
                print(f"CHECK FAILED: {rel} not in dist (stale zip — rebuild)", file=sys.stderr)
                return 1
    print(f"check OK: {zpath.name} up to date ({len(names)} entries)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    return check() if args.check else (0 if build() else 1)


if __name__ == "__main__":
    raise SystemExit(main())
