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

# ── 语言检测：仅中文环境显示中文，其他情况一律英文 ──────────────
# 检测优先级：LC_ALL > LC_MESSAGES > LANG（任意以 zh 开头即视为中文环境）
_LANG_VAL="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}"
_IS_ZH=0
case "$_LANG_VAL" in
  zh*) _IS_ZH=1 ;;
esac
# 输出双语消息：msg "中文" "English"
msg() {
  if [ "$_IS_ZH" = "1" ]; then
    printf '%s\n' "$1"
  else
    printf '%s\n' "$2"
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
msg "   free-short-video — 免费 AI 短视频生成" "   free-short-video — Free AI Short Video Generator"
echo ""
msg "   $(link 'https://video.lichuanyang.top' '🌐 官网：https://video.lichuanyang.top')" "   $(link 'https://video.lichuanyang.top' '🌐 Website: https://video.lichuanyang.top')"
msg "   $(link 'https://video.lichuanyang.top/demo' '⚡ 在线体验（免安装）：https://video.lichuanyang.top/demo')" "   $(link 'https://video.lichuanyang.top/demo' '⚡ Try Online (no install): https://video.lichuanyang.top/demo')"
echo "================================================"
echo ""

# ── L5: 环境校验 ──────────────────────────────────────────────

# 检查 Python 3.10+
if ! command -v python3 &> /dev/null; then
    msg "❌ 未找到 python3，请先安装 Python 3.10+" "❌ python3 not found. Please install Python 3.10+:"
    echo "   macOS:   brew install python3"
    echo "   Ubuntu:  sudo apt install python3 python3-venv"
    msg "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')" "   Or try online (no install): $(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
    exit 1
fi

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || {
    PY_VER=$(python3 --version 2>&1)
    msg "❌ Python 版本过低 ($PY_VER)，需要 3.10+" "❌ Python version too old ($PY_VER). Required: 3.10+"
    msg "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')" "   Or try online (no install): $(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
    exit 1
}

# 检查 ffmpeg（视频拼接和音频处理依赖）
if ! command -v ffmpeg &> /dev/null; then
    msg "❌ 未找到 ffmpeg，视频处理依赖 ffmpeg" "❌ ffmpeg not found. Video processing requires ffmpeg:"
    echo "   macOS:   brew install ffmpeg"
    echo "   Ubuntu:  sudo apt install ffmpeg"
    msg "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')" "   Or try online (no install): $(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
    exit 1
fi

# 检查端口 8765 是否被占用
if command -v lsof &> /dev/null; then
    PID=$(lsof -ti:8765 2>/dev/null || true)
    if [ -n "$PID" ]; then
        # lsof 输出的多行 PID 拼成单行，输出一条完整的 kill 命令（kill 支持一次传入多个 PID）
        PID_ONE_LINE=$(echo $PID | tr '\n' ' ')
        msg "⚠️  端口 8765 已被 PID $PID_ONE_LINE 占用" "⚠️  Port 8765 is already in use by PID $PID_ONE_LINE"
        msg "   执行: kill $PID_ONE_LINE 后重试，或修改端口" "   Run: kill $PID_ONE_LINE then retry, or change the port"
        msg "   或直接在线体验（免安装）：$(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')" "   Or try online (no install): $(link 'https://video.lichuanyang.top/demo' 'https://video.lichuanyang.top/demo')"
        exit 1
    fi
fi

msg "✓ 环境检查通过" "✓ Environment check passed"
echo ""

VENV_DIR=".venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [ ! -f "$VENV_PYTHON" ]; then
    msg "[1/3] 创建虚拟环境..." "[1/3] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

msg "[2/3] 安装依赖..." "[2/3] Installing dependencies..."
$VENV_PIP install -q -r requirements.txt

msg "[3/3] 启动服务..." "[3/3] Starting server..."
echo ""
msg "  浏览器将自动打开 http://localhost:8765" "  The browser will open http://localhost:8765 automatically"
msg "  按 Ctrl+C 停止服务" "  Press Ctrl+C to stop the server"
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
