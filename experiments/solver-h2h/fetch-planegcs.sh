#!/usr/bin/env bash
# Materialize the pinned FreeCAD planegcs sources for the solver head-to-head.
# NEVER commits upstream content (.upstream/ is gitignored); the pinned tag/SHA
# below + this script are the reproducibility record.
#
# Pin policy (same as m3-eval): the pin is the LATEST VERSIONED RELEASE TAG at
# evaluation time — FreeCAD 1.1.4 (tag 4fd3bf320d9566a27e60069fc8387448aaa3a094).
# planegcs lives at src/Mod/Sketcher/App/planegcs/ (11 files, 13,142 lines).
set -euo pipefail

FREECAD_TAG="1.1.4"
FREECAD_TAG_SHA="4fd3bf320d9566a27e60069fc8387448aaa3a094"
FREECAD_URL="https://github.com/FreeCAD/FreeCAD.git"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/.upstream/freecad-pin"

if [ -d "$DEST/.git" ]; then
  current="$(git -C "$DEST" rev-parse FETCH_HEAD 2>/dev/null || git -C "$DEST" rev-parse HEAD)"
  echo "[fetch-planegcs] $DEST exists — pin: $current"
else
  echo "[fetch-planegcs] shallow-fetching FreeCAD tag $FREECAD_TAG ($FREECAD_TAG_SHA)"
  mkdir -p "$DEST"
  git -C "$DEST" init -q
  git -C "$DEST" remote add origin "$FREECAD_URL"
  git -C "$DEST" fetch --depth 1 origin "refs/tags/$FREECAD_TAG"
  actual="$(git -C "$DEST" rev-parse FETCH_HEAD)"
  if [ "$actual" != "$FREECAD_TAG_SHA" ]; then
    echo "ERROR: tag $FREECAD_TAG resolved to $actual, expected $FREECAD_TAG_SHA" >&2
    exit 1
  fi
  echo "[fetch-planegcs] pin verified: $actual"
fi

# Materialize exactly the files the planegcs build consumes (read-only copies)
# plus the two license-evidence files the record verifies (SetupEigen.cmake =
# FreeCAD's Eigen requirement at the pin).
git -C "$DEST" checkout -q FETCH_HEAD -- \
  src/Mod/Sketcher/App/planegcs \
  src/Mod/Sketcher/SketcherGlobal.h \
  src/boost_graph_adjacency_list.hpp \
  cMake/FreeCAD_Helpers/SetupEigen.cmake \
  LICENSE

echo "[fetch-planegcs] materialized under $DEST/:"
echo "  src/Mod/Sketcher/App/planegcs/  (11 files — the solver, LGPL header per file)"
echo "  src/Mod/Sketcher/SketcherGlobal.h (export macros; LGPL)"
echo "  src/boost_graph_adjacency_list.hpp (11-line boost>=1.75 workaround; SPDX LGPL-2.1-or-later)"
echo "  cMake/FreeCAD_Helpers/SetupEigen.cmake (license evidence: the Eigen3 requirement)"
echo "  LICENSE (FreeCAD root = full LGPL-2.1 text)"
git -C "$DEST" log -1 --format='  pin: %H %ci %s' FETCH_HEAD
