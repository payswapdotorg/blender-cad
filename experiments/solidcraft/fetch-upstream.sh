#!/usr/bin/env bash
# Idempotent clone of the pinned SolidCraft upstream for the TL2 evaluation.
# NEVER commit the clone itself (.upstream/ is gitignored) — the pinned SHA below
# plus this script are the reproducibility record.
set -euo pipefail

PINNED_SHA="3b4db52c10279251a068cfca5eb7447068bc28e7"
UPSTREAM_URL="https://github.com/tangency-labs/solidcraft.git"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/.upstream"

if [ -d "$DEST/.git" ]; then
  echo "[fetch-upstream] $DEST exists — verifying pin"
  current="$(git -C "$DEST" rev-parse HEAD)"
  if [ "$current" != "$PINNED_SHA" ]; then
    echo "ERROR: .upstream is at $current, expected $PINNED_SHA" >&2
    echo "       remove $DEST and re-run for a clean clone" >&2
    exit 1
  fi
  echo "[fetch-upstream] pin OK: $PINNED_SHA"
else
  echo "[fetch-upstream] cloning $UPSTREAM_URL @ $PINNED_SHA"
  git clone "$UPSTREAM_URL" "$DEST"
  git -C "$DEST" checkout --detach "$PINNED_SHA"
  echo "[fetch-upstream] cloned and pinned: $PINNED_SHA"
fi

# Seed the harness Cargo.lock from upstream's lock (dependency-version fidelity),
# but only when the harness has no lock of its own yet.
HARNESS_LOCK="$HERE/harness/Cargo.lock"
UPSTREAM_LOCK="$DEST/Cargo.lock"
if [ -f "$UPSTREAM_LOCK" ] && [ ! -f "$HARNESS_LOCK" ]; then
  cp "$UPSTREAM_LOCK" "$HARNESS_LOCK"
  echo "[fetch-upstream] seeded harness/Cargo.lock from upstream (versions pinned to upstream-tested set)"
fi

echo "[fetch-upstream] done. Upstream commit:"
git -C "$DEST" log -1 --format='  %H %ci %s'
