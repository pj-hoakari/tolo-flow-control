#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: release_tags.sh <version>   # 安定版タグ一覧 (v*) を標準入力で渡す" >&2
  exit 2
fi

VERSION="${1#v}"
if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$'; then
  echo "unexpected version format: '$1' (expected vX.Y.Z or vX.Y.Z-suffix)" >&2
  exit 1
fi

echo "$VERSION"

case "$VERSION" in
*-*) exit 0 ;;
esac

NEWEST="$(
  {
    printf '%s\n' "$VERSION"
    sed 's/^v//'
  } | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1
)"

if [ "$NEWEST" != "$VERSION" ]; then
  exit 0
fi

MAJOR="${VERSION%%.*}"
MINOR="${VERSION#*.}"
MINOR="${MINOR%%.*}"

echo "${MAJOR}.${MINOR}"
if [ "$MAJOR" != "0" ]; then
  echo "$MAJOR"
fi
echo "latest"
