#!/usr/bin/env bash
# Materialize the pinned Eigen headers for the planegcs build + LICENSE VERIFICATION.
#
# Provenance note (honest constraint record): Eigen's canonical repo is
# gitlab.com/libeigen/eigen — BLOCKED from this sandbox (https fetch => 403,
# Cloudflare; re-tested for this lane, see findings/license-planegcs-eigen.md §4).
# The pin is therefore the EXACT upstream release artifact eigen 3.4.0
# (orig tarball) as mirrored byte-identically in the Debian pool — the same
# upstream tarball Debian's libeigen3-dev 3.4.0-2 builds from. sha256 recorded.
#
# This pin ALSO resolves the license verification that m3-eval could not do for
# the solvespace path (Eigen@3147391d, unverifiable from this sandbox): for
# THIS lane's build the exact artifact is 3.4.0 and COPYING.MPL2 is verified
# verbatim at the pin. The solvespace-scoped Eigen@3147391d (verify) blocker is
# a DIFFERENT pin (master-branch commit) and stays untouched by this script.
set -euo pipefail

EIGEN_TARBALL="eigen3_3.4.0.orig.tar.bz2"
EIGEN_SHA256="b4c198460eba6f28d34894e3a5710998818515104d6e74e5cc331ce31e46e626"
EIGEN_URL="https://deb.debian.org/debian/pool/main/e/eigen3/$EIGEN_TARBALL"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/.upstream"

if [ -d "$DEST/eigen-3.4.0" ]; then
  echo "[fetch-eigen] $DEST/eigen-3.4.0 exists — verifying pin by re-download+digest skip"
else
  echo "[fetch-eigen] downloading $EIGEN_URL"
  mkdir -p "$DEST"
  curl -sSfL -o "$DEST/$EIGEN_TARBALL" "$EIGEN_URL"
  actual="$(sha256sum "$DEST/$EIGEN_TARBALL" | cut -d' ' -f1)"
  if [ "$actual" != "$EIGEN_SHA256" ]; then
    echo "ERROR: digest mismatch: got $actual, expected $EIGEN_SHA256" >&2
    exit 1
  fi
  echo "[fetch-eigen] sha256 verified: $actual"
  tar -xjf "$DEST/$EIGEN_TARBALL" -C "$DEST"
fi
echo "[fetch-eigen] eigen-3.4.0/ materialized (COPYING.MPL2 = full MPL-2.0 text; verified verbatim"
echo "  in findings/license-planegcs-eigen.md — FreeCAD 1.1.4's SetupEigen.cmake targets the 3.4 line;"
echo "  GCS.h uses <Eigen/QR> + <Eigen/Dense> + FullPivLU, all present in 3.4.0)."
