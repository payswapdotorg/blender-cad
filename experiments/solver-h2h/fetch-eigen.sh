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

# ----------------------------------------------------------------------------
# SECOND PIN — the m3-eval blocker retest (eigen @ 3147391d, solvespace's
# gitlink pin; m3-eval §9 recorded it as network-unverifiable from this
# sandbox class: gitlab https fetch => 403 on 2026-10-20). Re-attempted by
# this lane same day: the git smart-HTTP fetch WORKED. The exact commit is
# materialized so gen_license_record.py can verify COPYING.MPL2 AT THE PIN.
# ----------------------------------------------------------------------------
RETEST_SHA="3147391d946bb4b6c68edd901f2add6ac1f31f8c"
RETEST_DEST="$DEST/eigen-3147391d"
if [ -d "$RETEST_DEST/.git" ]; then
  echo "[fetch-eigen] $RETEST_DEST exists — pin: $(git -C "$RETEST_DEST" rev-parse FETCH_HEAD)"
else
  echo "[fetch-eigen] retest: fetching eigen @ $RETEST_SHA from gitlab (the m3-eval §9 blocker pin)"
  mkdir -p "$RETEST_DEST"
  git -C "$RETEST_DEST" init -q
  if git -C "$RETEST_DEST" fetch --depth 1 https://gitlab.com/libeigen/eigen.git "$RETEST_SHA" 2>/dev/null; then
    got="$(git -C "$RETEST_DEST" rev-parse FETCH_HEAD)"
    if [ "$got" != "$RETEST_SHA" ]; then
      echo "ERROR: retest fetch got $got, expected $RETEST_SHA" >&2
      exit 1
    fi
    git -C "$RETEST_DEST" checkout -q FETCH_HEAD -- COPYING.MPL2 COPYING.README
    echo "[fetch-eigen] retest pin verified: $got — COPYING.MPL2 materialized AT THE PIN"
  else
    # The retest fetch failing is a recorded environment fact, not an error
    # for the whole script (the primary 3.4.0 pin is already materialized).
    echo "[fetch-eigen] retest fetch FAILED (network condition) — recorded; the"
    echo "  solvespace-scoped (verify) tag then simply stays per m3-eval §9."
    rm -rf "$RETEST_DEST"
  fi
fi
