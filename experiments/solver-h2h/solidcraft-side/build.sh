#!/usr/bin/env bash
# Build the SolidCraft head-to-head driver (isolated experiment; NOT product code).
# Memory safety: -j 2 (2 jobs) to stay inside the sandbox's 2-CPU / 4 GiB cgroup
# (TL2's Task-96 record: larger parallel rustc codegen OOM-kills here; the
# sketch+geom closure is small and builds fine at -j 2).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOME/.cargo/env"
cd "$HERE"
cargo build --release -j 2
echo "[build.sh] built: $HERE/target/release/solidcraft-h2h-driver"
