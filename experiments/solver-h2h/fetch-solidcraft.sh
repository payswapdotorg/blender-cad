#!/usr/bin/env bash
# Materialize the pinned SolidCraft upstream for the solver head-to-head.
# SAME PIN as TL2's evaluation (experiments/solidcraft/fetch-upstream.sh on
# tl2/solidcraft-evaluation): tangency-labs/solidcraft @ 3b4db52 (v0.16.2).
# The head-to-head requires the SolidCraft side to run the SAME commit TL2
# evaluated — a different pin would invalidate the cross-references.
# NEVER commits the clone (.upstream/ is gitignored).
set -euo pipefail

PINNED_SHA="3b4db52c10279251a068cfca5eb7447068bc28e7"
UPSTREAM_URL="https://github.com/tangency-labs/solidcraft.git"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/.upstream/solidcraft"

if [ -d "$DEST/.git" ]; then
  current="$(git -C "$DEST" rev-parse HEAD)"
  if [ "$current" != "$PINNED_SHA" ]; then
    echo "ERROR: .upstream is at $current, expected $PINNED_SHA" >&2
    exit 1
  fi
  echo "[fetch-solidcraft] pin OK: $PINNED_SHA"
else
  echo "[fetch-solidcraft] cloning $UPSTREAM_URL @ $PINNED_SHA"
  git clone "$UPSTREAM_URL" "$DEST"
  git -C "$DEST" checkout --detach "$PINNED_SHA"
  echo "[fetch-solidcraft] cloned and pinned: $PINNED_SHA"
fi

# Seed the harness Cargo.lock from upstream's lock (TL2's dependency-fidelity
# pattern), only when the harness has no lock of its own yet.
HARNESS_LOCK="$HERE/solidcraft-side/Cargo.lock"
UPSTREAM_LOCK="$DEST/Cargo.lock"
if [ -f "$UPSTREAM_LOCK" ] && [ ! -f "$HARNESS_LOCK" ]; then
  cp "$UPSTREAM_LOCK" "$HARNESS_LOCK"
  echo "[fetch-solidcraft] seeded solidcraft-side/Cargo.lock from upstream (versions pinned to upstream-tested set)"
fi

echo "[fetch-solidcraft] done. Upstream commit:"
git -C "$DEST" log -1 --format='  %H %ci %s'
