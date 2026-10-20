#!/usr/bin/env bash
# Idempotent materialization of the pinned CAD_Sketcher upstream for the M3 evaluation.
# NEVER commit the clone itself (.upstream/ is gitignored) — the pinned tag/SHA below
# plus this script are the reproducibility record.
#
# Pin choice (documented, binding for every phase of this evaluation):
#   * CAD_Sketcher's newest *versioned release* is v0.32.1 (tag object
#     6a5a34001efcdec05381b6f419cc4d0394a24ab5) → commit
#     e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4, dated 2026-09-28, tagged
#     "Changelog for 0.32.1 (#759)". blender_manifest.toml at the tag says
#     version = "0.32.1".
#   * The moving tag `latest` points at main HEAD (efd2551 at evaluation time) —
#     recorded for reference, never used as a pin.
#   * main HEAD carries dev version 0.32.2 (unreleased) — not what users install.
#   * We therefore evaluate the newest thing a user can actually install from the
#     stable channel: the v0.32.1 release tag.
set -euo pipefail

PIN_TAG="v0.32.1"
PIN_TAG_OBJECT="6a5a34001efcdec05381b6f419cc4d0394a24ab5"   # annotated tag object
PIN_COMMIT="e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4"       # commit the tag points to
UPSTREAM_URL="https://github.com/hlorus/CAD_Sketcher.git"
# Optional pre-existing local mirror (saves network + ~140 MB of object storage;
# the mirror is scratch too — if absent we clone from GitHub directly).
LOCAL_MIRROR="${CAD_SKETCHER_MIRROR:-/home/z/cad-sketcher-upstream}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/.upstream/CAD_Sketcher"

verify_pin() {
  local tag_obj commit
  tag_obj="$(git -C "$DEST" rev-parse "$PIN_TAG" 2>/dev/null || echo missing)"
  commit="$(git -C "$DEST" rev-parse "$PIN_TAG^{commit}" 2>/dev/null || echo missing)"
  if [ "$tag_obj" != "$PIN_TAG_OBJECT" ] || [ "$commit" != "$PIN_COMMIT" ]; then
    echo "ERROR: $DEST does not resolve $PIN_TAG to ($PIN_TAG_OBJECT, $PIN_COMMIT); got ($tag_obj, $commit)" >&2
    echo "       remove $DEST and re-run for a clean clone" >&2
    exit 1
  fi
  git -C "$DEST" checkout --quiet --detach "$PIN_COMMIT"
  echo "[fetch-upstream] pin OK: tag $PIN_TAG = tag-object $PIN_TAG_OBJECT -> commit $PIN_COMMIT"
}

if [ -d "$DEST/.git" ]; then
  echo "[fetch-upstream] $DEST exists — verifying pin"
  verify_pin
else
  mkdir -p "$HERE/.upstream"
  if [ -d "$LOCAL_MIRROR/.git" ]; then
    echo "[fetch-upstream] cloning --shared from local mirror $LOCAL_MIRROR (disk-cheap; alternates)"
    git clone --quiet --shared "$LOCAL_MIRROR" "$DEST"
  else
    echo "[fetch-upstream] cloning $UPSTREAM_URL (full clone)"
    git clone --quiet "$UPSTREAM_URL" "$DEST"
  fi
  verify_pin
fi

echo "[fetch-upstream] done. Upstream commit at the pin:"
git -C "$DEST" log -1 --format='  %H %ci %s'
echo "[fetch-upstream] wheels present at the pin (never committed; verified by fetch-solver.sh):"
git -C "$DEST" ls-files wheels/ | sed 's/^/  /'
