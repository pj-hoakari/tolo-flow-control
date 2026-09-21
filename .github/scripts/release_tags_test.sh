#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/release_tags.sh"
FAILED=0

check() {
  local desc="$1" version="$2" stable_tags="$3" want="$4" got
  got="$(printf '%s' "$stable_tags" | bash "$SCRIPT" "$version" | paste -sd, -)"
  if [ "$got" = "$want" ]; then
    printf 'ok   %s\n' "$desc"
  else
    printf 'FAIL %s: got=%s want=%s\n' "$desc" "$got" "$want" >&2
    FAILED=1
  fi
}

check_fails() {
  local desc="$1" version="$2"
  if printf '' | bash "$SCRIPT" "$version" >/dev/null 2>&1; then
    printf 'FAIL %s: exited 0\n' "$desc" >&2
    FAILED=1
  else
    printf 'ok   %s\n' "$desc"
  fi
}

check "安定版の最大: 可動タグを付ける (major 0)" \
  "0.3.0" 'v0.1.0
v0.2.0
v0.3.0' "0.3.0,0.3,latest"

check "旧版の公開: 完全 version のみ" \
  "0.1.0" 'v0.1.0
v0.2.0
v0.3.0' "0.1.0"

check "pre-release: 完全 version のみ" \
  "1.0.0-rc.1" 'v0.9.0
v1.0.0' "1.0.0-rc.1"

check "major 1 以上の最大: major タグも付ける" \
  "1.2.3" 'v0.9.0
v1.2.3' "1.2.3,1.2,1,latest"

check "pre-release タグは最大判定に含めない" \
  "1.0.0" 'v1.0.0
v1.1.0-rc.1' "1.0.0,1.0,1,latest"

check "数値順で比較する (0.10.0 > 0.9.0)" \
  "0.10.0" 'v0.9.0
v0.10.0' "0.10.0,0.10,latest"

check "タグ一覧が空でも最大として扱う" \
  "0.1.0" '' "0.1.0,0.1,latest"

check "先頭 v 付きの入力も受け付ける" \
  "v0.1.0" 'v0.1.0' "0.1.0,0.1,latest"

check_fails "不正な version 形式は失敗する" "1.0"
check_fails "空の version は失敗する" ""

if [ "$FAILED" -ne 0 ]; then
  echo "release_tags.sh: テストに失敗しました" >&2
  exit 1
fi
echo "release_tags.sh: 全テスト成功"
