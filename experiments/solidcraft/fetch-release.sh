#!/usr/bin/env bash
# Fetches the official SolidCraft release binary used by experiment D (agent
# interface / MCP PoC) and verifies its checksum against upstream SHA256SUMS.
#
# Fidelity note (recorded honestly in every result that uses the binary):
#   release tag v0.16.2 → commit 5de48e916df2d659586a36b15c90ed05293a0954,
#   which is 80 commits BEHIND the source-pin 3b4db52c10279251a068cfca5eb7447068bc28e7
#   (source audits use the pin; behavioral MCP evidence uses the release binary).
set -euo pipefail

RELEASE_TAG="v0.16.2"
ASSET="solidcraft-0.16.2-linux-x86_64.tar.gz"
BASE="https://github.com/tangency-labs/solidcraft/releases/download/${RELEASE_TAG}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HERE/.release"

mkdir -p "$DEST"
cd "$DEST"

if [ -x "$DEST/solidcraft-0.16.2-linux-x86_64/bin/solidcraft-cli" ]; then
  echo "[fetch-release] already present: $DEST/solidcraft-0.16.2-linux-x86_64/bin/solidcraft-cli"
  echo "[fetch-release] version: $("$DEST/solidcraft-0.16.2-linux-x86_64/bin/solidcraft-cli" --version)"
  exit 0
fi

echo "[fetch-release] downloading $ASSET"
curl -sL -o "$ASSET" "$BASE/$ASSET"
curl -sL -o SHA256SUMS.txt "$BASE/SHA256SUMS.txt"

expected="$(grep " ${ASSET}\$" SHA256SUMS.txt | awk '{print $1}')"
actual="$(sha256sum "$ASSET" | awk '{print $1}')"
if [ "$expected" != "$actual" ]; then
  echo "ERROR: checksum mismatch for $ASSET" >&2
  echo "  expected: $expected" >&2
  echo "  actual:   $actual" >&2
  exit 1
fi
echo "[fetch-release] sha256 verified: $actual"

tar xzf "$ASSET"
echo "[fetch-release] extracted: $DEST/solidcraft-0.16.2-linux-x86_64/"
"$DEST/solidcraft-0.16.2-linux-x86_64/bin/solidcraft-cli" --version
