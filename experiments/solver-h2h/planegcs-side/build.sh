#!/usr/bin/env bash
# Build the planegcs h2h driver: compile FreeCAD 1.1.4's planegcs TUs
# (materialized read-only by ../fetch-planegcs.sh) against eigen 3.4.0
# (../fetch-eigen.sh) + system boost + the lane's compat shims, then link the
# driver. Everything lands in build/ (gitignored). NOT product code.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANE="$(cd "$HERE/.." && pwd)"
FC="$LANE/.upstream/freecad-pin"
EIGEN="$LANE/.upstream/eigen-3.4.0"
BUILD="$HERE/build"
JOBS="${JOBS:-2}"

[ -d "$FC/src/Mod/Sketcher/App/planegcs" ] || { echo "run fetch-planegcs.sh first" >&2; exit 1; }
[ -d "$EIGEN/Eigen" ] || { echo "run fetch-eigen.sh first" >&2; exit 1; }

mkdir -p "$BUILD/inc/src/Mod/Sketcher/App/planegcs"
cp "$FC"/src/Mod/Sketcher/App/planegcs/*.h "$FC"/src/Mod/Sketcher/App/planegcs/*.cpp \
   "$BUILD/inc/src/Mod/Sketcher/App/planegcs/"
cp "$FC/src/Mod/Sketcher/SketcherGlobal.h" "$BUILD/inc/src/Mod/Sketcher/"
cp "$FC/src/boost_graph_adjacency_list.hpp" "$BUILD/inc/src/"

CXXFLAGS="-std=c++20 -O2 -fPIC -I$EIGEN -I$LANE/compat -I$BUILD/inc/src"
cd "$BUILD"
echo "[build] compiling planegcs TUs (-j$JOBS; C++20 per FreeCAD 1.1.4)"
pids=(); files=(Constraints Geo SubSystem qp_eq GCS)
for f in "${files[@]}"; do
  g++ $CXXFLAGS -c "inc/src/Mod/Sketcher/App/planegcs/$f.cpp" -o "$f.o" &
  pids+=($!)
  while [ "$(jobs -r | wc -l)" -ge "$JOBS" ]; do wait -n; done
done
for p in "${pids[@]}"; do wait "$p"; done
echo "[build] compiling driver"
g++ $CXXFLAGS -c "$HERE/driver.cpp" -o driver.o
echo "[build] linking"
g++ driver.o Constraints.o Geo.o SubSystem.o qp_eq.o GCS.o -o driver -pthread
echo "[build] OK: $BUILD/driver"
"$BUILD/driver" --hash
