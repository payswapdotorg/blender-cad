#!/usr/bin/env bash
# Idempotent pin + verification of the evaluated SOLVER binary and its source provenance.
# NEVER commit the wheel or any unpacked solver artifact — the digests below + this
# script are the reproducibility record.
#
# What is being evaluated (binding):
#   * The solver binary is the wheel CAD_Sketcher v0.32.1 ships for CPython 3.13
#     linux-x64, taken from the upstream checkout at the pinned tag:
#       wheels/slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
#     sha256 9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80
#     size  2861309 bytes
#   * That wheel is byte-identical to the PyPI `slvs` 3.2 wheel of the same name
#     (PyPI digest matches; all 10 in-repo wheels match their PyPI counterparts).
#   * The `slvs` PyPI project has NO project URLs in its metadata. Its source is
#     identifiable from the sdist `slvs-3.2.tar.gz` (sha256
#     cf7c00fb17a2d100df7cfa80db5e04c7ec16e6093b3d9a74402f001043550a9b), which
#     embeds git provenance files (pyproject.toml sdist.include = [".git/HEAD",
#     ".git/refs"]):
#       .git/HEAD        = 477d4c87ca51b9727fbc0765cbd94253c3968b8b
#       .git/refs/tags/v3.2 = 477d4c87ca51b9727fbc0765cbd94253c3968b8b
#     => the source of slvs 3.2 is UPSTREAM solvespace/solvespace itself at commit
#        477d4c8 ("Update CHANGELOG.md", Paul Kahler, 2026-03-16), snapshotted and
#        released to PyPI on 2026-03-23. The solvespace `v3.2` tag has since moved
#        to 27b6a08 ("fix windows single_core paths", Koen Schmeets, 2026-03-26) —
#        AFTER the PyPI upload; the PyPI artifacts correspond to 477d4c8.
#   * Full license evidence for both the wheel and the source repo is in
#     findings/license-supply-chain.md (verbatim quotes at pinned SHAs).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM="$HERE/.upstream/CAD_Sketcher"
WHEEL="wheels/slvs-3.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
WHEEL_SHA256="9ee04ff5a00482cef1751eed71658f4b01f605de42c56786373c7da9e5b25f80"
PIN_TAG="v0.32.1"
PIN_COMMIT="e7db7e6f94ad9dcaf2be03e849e1d3a2ac82e7a4"
SDIST_SHA256="cf7c00fb17a2d100df7cfa80db5e04c7ec16e6093b3d9a74402f001043550a9b"
SOLVER_SOURCE_REPO="https://github.com/solvespace/solvespace.git"
SOLVER_SOURCE_SHA="477d4c87ca51b9727fbc0765cbd94253c3968b8b"

if [ ! -d "$UPSTREAM/.git" ]; then
  echo "[fetch-solver] upstream checkout missing at $UPSTREAM — run fetch-upstream.sh first" >&2
  exit 1
fi

echo "[fetch-solver] verifying CAD_Sketcher pin ($PIN_TAG @ $PIN_COMMIT)"
actual_tag="$(git -C "$UPSTREAM" rev-parse "$PIN_TAG^{commit}")"
if [ "$actual_tag" != "$PIN_COMMIT" ]; then
  echo "ERROR: upstream checkout not at the pin ($actual_tag != $PIN_COMMIT)" >&2
  exit 1
fi

echo "[fetch-solver] verifying the pinned wheel digest"
git -C "$UPSTREAM" cat-file blob "$PIN_COMMIT:$WHEEL" > /dev/null   # must exist at the pin
wheel_path="$UPSTREAM/$WHEEL"
actual_sha="$(sha256sum "$wheel_path" | cut -d' ' -f1)"
actual_size="$(stat -c%s "$wheel_path")"
if [ "$actual_sha" != "$WHEEL_SHA256" ]; then
  echo "ERROR: wheel sha256 $actual_sha != pinned $WHEEL_SHA256" >&2
  exit 1
fi
echo "[fetch-solver] wheel OK: $WHEEL"
echo "    sha256 $actual_sha  size $actual_size bytes (PyPI slvs 3.2 cp313 manylinux: identical digest)"

echo "[fetch-solver] solver SOURCE provenance (recorded, not re-fetched):"
echo "    source repo   $SOLVER_SOURCE_REPO"
echo "    source commit $SOLVER_SOURCE_SHA  (= slvs 3.2, PyPI upload 2026-03-23)"
echo "    sdist         slvs-3.2.tar.gz  sha256 $SDIST_SHA256 (embedded .git/HEAD = source SHA)"
echo "[fetch-solver] done."
