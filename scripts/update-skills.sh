#!/usr/bin/env bash
# 重新同步 .claude/skills/ 下 vendor 进来的外部 skill。
#
# 幂等：跑完后用 `git diff .claude/skills/` 查看上游改了什么。
# 只同步下面显式列出的目录——上游新增的 skill 不会被静默拉进来。
#
# 用法： bash scripts/update-skills.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/.claude/skills"

KARPATHY_REPO="https://github.com/multica-ai/andrej-karpathy-skills"
EMIL_REPO="https://github.com/emilkowalski/skills"

# 从 karpathy 仓库同步的目录
KARPATHY_SKILLS=(karpathy-guidelines)

# 从 emilkowalski 仓库同步的目录
EMIL_SKILLS=(
  animation-vocabulary
  apple-design
  emil-design-eng
  find-animation-opportunities
  improve-animations
  pick-ui-library
  prototype
  review-animations
)

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

clone() {
  # $1=url  $2=目标子目录名
  git clone --depth 1 --quiet "$1" "$TMP/$2"
  git -C "$TMP/$2" rev-parse HEAD
}

sync_skills() {
  # $1=源仓库 checkout 路径  $2...=skill 目录名
  local src="$1"; shift
  local name
  for name in "$@"; do
    if [[ ! -f "$src/skills/$name/SKILL.md" ]]; then
      echo "  ! 上游已不存在，跳过: $name" >&2
      continue
    fi
    rm -rf "$SKILLS_DIR/$name"
    cp -R "$src/skills/$name" "$SKILLS_DIR/$name"
    echo "  ✓ $name"
  done
}

mkdir -p "$SKILLS_DIR"

echo "==> multica-ai/andrej-karpathy-skills"
KARPATHY_SHA="$(clone "$KARPATHY_REPO" karpathy)"
sync_skills "$TMP/karpathy" "${KARPATHY_SKILLS[@]}"

echo "==> emilkowalski/skills"
EMIL_SHA="$(clone "$EMIL_REPO" emil)"
sync_skills "$TMP/emil" "${EMIL_SKILLS[@]}"

cat <<EOF

上游 commit（请同步更新 .claude/skills/README.md 里的 SHA）：
  multica-ai/andrej-karpathy-skills  $KARPATHY_SHA
  emilkowalski/skills                $EMIL_SHA

下一步： git diff --stat .claude/skills/
EOF
