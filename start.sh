#!/usr/bin/env bash
# ============================================================
# UserSim 一键启动脚本
#   - 首次运行自动准备环境（.venv / npm 依赖 / 前端构建）
#   - 启动后端（FastAPI，同时托管前端页面）
#   - 自动打开浏览器；Ctrl+C 停止
# 用法：
#   ./start.sh              # 正常启动（缺啥补啥）
#   ./start.sh --rebuild    # 强制重新构建前端
#   ./start.sh --port 8620  # 换端口（默认 8610）
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"
PORT=8610
REBUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

info() { printf "\033[36m[UserSim]\033[0m %s\n" "$1"; }
err()  { printf "\033[31m[UserSim]\033[0m %s\n" "$1" >&2; }

# ---------- 0. 前置检查 ----------
command -v uv  >/dev/null 2>&1 || { err "未找到 uv，请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
command -v npm >/dev/null 2>&1 || { err "未找到 npm，请先安装 Node.js (>= 20)"; exit 1; }

# ---------- 1. Python 环境 ----------
if [ ! -f .venv/bin/python ]; then
  info "创建 Python 虚拟环境 (.venv)…"
  uv venv .venv
fi
if ! .venv/bin/python -c "import pydantic, fastapi, uvicorn, numpy, openai" 2>/dev/null; then
  info "安装 Python 依赖…"
  uv pip install --python .venv/bin/python pydantic numpy fastapi uvicorn openai pytest websockets openpyxl
fi

# ---------- 2. 前端依赖与构建 ----------
if [ ! -d web/node_modules ]; then
  info "安装前端依赖 (npm install)…"
  (cd web && npm install --no-audit --no-fund)
fi
if [ ! -f web/dist/index.html ] || [ "$REBUILD" = "1" ]; then
  info "构建前端 (npm run build)…"
  (cd web && npm run build)
fi

# ---------- 3. 端口检查 ----------
if lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  err "端口 $PORT 已被占用。请先停止旧进程：pkill -f 'usersim serve'，或换端口：./start.sh --port 8620"
  exit 1
fi

# ---------- 4. 启动 ----------
URL="http://127.0.0.1:$PORT/"
info "启动 UserSim（后端 + 前端托管）…"
info "打开浏览器: $URL"
(sleep 1.5 && (command -v open >/dev/null 2>&1 && open "$URL" || true)) &

info "按 Ctrl+C 停止服务"
USERSIM_PORT="$PORT" exec .venv/bin/python -m usersim serve
