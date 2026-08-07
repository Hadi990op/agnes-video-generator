#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# ── 终端超链接（ANSI OSC 8）：支持的终端（macOS 终端/iTerm2/Windows Terminal/VS Code 等）
#    显示文本可点击跳转；不支持的终端自动降级为纯文本。非 TTY（重定向/管道）时只输出纯文本。
_IS_TTY=0
[[ -t 1 ]] && _IS_TTY=1
link() {
  if [ "$_IS_TTY" = "1" ]; then
    printf '\033]8;;%s\033\\%s\033]8;;\033\\' "$1" "$2"
  else
    printf '%s' "$2"
  fi
}

# ── 启动图案（ASCII art）：TTY 下亮青色显示，非 TTY 纯文本 ──────────
FSV_LOGO=(
  '   _____ ______     __'
  '  |  ___/ ___\ \   / /'
  '  | |_  \___ \\ \ / /'
  '  |  _|  ___) |\ V /'
  '  |_|   |____/  \_/'
)
print_logo() {
  if [ "$_IS_TTY" = "1" ]; then
    printf '\033[1;36m\n'
    printf '%s\n' "${FSV_LOGO[@]}"
    printf '\033[0m'
  else
    printf '\n'
    printf '%s\n' "${FSV_LOGO[@]}"
  fi
}

echo "================================================"
print_logo
echo "   free-short-video — 免费 AI 短视频生成"
echo ""
echo "   $(link 'https://video.lichuanyang.top' '🌐 官网：https://video.lichuanyang.top')"
echo "   $(link 'https://video.lichuanyang.top/demo' '⚡ 在线体验（免安装）：https://video.lichuanyang.top/demo')"
echo "================================================"
echo ""

# ── L5: 环境校验 ──────────────────────────────────────────────

# 检查 Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.10+"
    echo "   macOS:   brew install python3"
    echo "   Ubuntu:  sudo apt install python3 python3-venv"
    echo "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
    exit 1
fi

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || {
    PY_VER=$(python3 --version 2>&1)
    echo "❌ Python 版本过低 ($PY_VER)，需要 3.10+"
    echo "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
    exit 1
}

# 检查 ffmpeg（视频拼接和音频处理依赖）
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ 未找到 ffmpeg，视频处理依赖 ffmpeg"
    echo "   macOS:   brew install ffmpeg"
    echo "   Ubuntu:  sudo apt install ffmpeg"
    echo "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
    exit 1
fi

# 检查端口 8765 是否被占用
if command -v lsof &> /dev/null; then
    PID=$(lsof -ti:8765 2>/dev/null || true)
    if [ -n "$PID" ]; then
        echo "⚠️  端口 8765 已被 PID $PID 占用"
        echo "   执行: kill $PID 后重试，或修改端口"
        echo "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
        exit 1
    fi
fi

echo "✓ 环境检查通过"
echo ""

VENV_DIR=".venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[1/3] 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

echo "[2/3] 安装依赖..."
$VENV_PIP install -q -r requirements.txt

echo "[3/3] 启动服务..."
echo ""
echo "  浏览器将自动打开 http://localhost:8765"
echo "  按 Ctrl+C 停止服务"
echo ""

# 轮询等待服务就绪后再打开浏览器，避免启动初期闪现"无法访问"
_APP_URL="http://localhost:8765"
wait_ready() {
    local i
    for i in $(seq 1 120); do
        if curl -s -o /dev/null --connect-timeout 1 -m 2 "$_APP_URL/" 2>/dev/null; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

if command -v open &> /dev/null; then
    (wait_ready && open "$_APP_URL") &
elif command -v xdg-open &> /dev/null; then
    (wait_ready && xdg-open "$_APP_URL") &
fi

$VENV_PYTHON server.py
