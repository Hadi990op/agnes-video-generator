#!/usr/bin/env bash
# Agnes Video Generator — 一行命令启动（数据自动持久化到本地）
#
# 用法：
#   ./docker-run.sh
#   AGNES_API_KEY=你的key ./docker-run.sh          # 注入 API Key
#   AGNES_IMAGE=其它镜像:tag ./docker-run.sh        # 指定镜像
#
# 生成的视频/上传文件会落在本地 ./agnes_data/working/，直接打开文件夹即可导出；
# 设置（API Key 等）落在 ./agnes_data/config/。容器删了重建数据也不丢。
set -euo pipefail
cd "$(dirname "$0")"

# ── 终端超链接（ANSI OSC 8）：支持的终端可点击跳转，不支持的自动降级为纯文本；
#    非 TTY（重定向/管道）时只输出纯文本，不混入转义字符。
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
echo "   $(link 'https://video.lichuanyang.top' '🌐 官网：https://video.lichuanyang.top')  |  $(link 'https://video.lichuanyang.top/demo' '⚡ 在线体验（免安装）：https://video.lichuanyang.top/demo')"
echo "================================================"
echo ""

IMAGE="${AGNES_IMAGE:-ghcr.io/lcy362/agnes-video-generator/free-short-video:4.7.2}"
NAME="agnes-video"
PORT="${AGNES_PORT:-8765}"
DATA_DIR="$(pwd)/agnes_data"

mkdir -p "$DATA_DIR/working" "$DATA_DIR/config"

# 若已存在同名容器则先移除（数据在宿主机 agnes_data/，不会丢）
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker rm -f "$NAME" >/dev/null
fi

docker run -d --name "$NAME" -p "$PORT:$PORT" \
  -e AGNES_API_KEY="${AGNES_API_KEY:-}" \
  -v "$DATA_DIR/working:/app/.working_dir" \
  -v "$DATA_DIR/config:/app/.agnes_config" \
  "$IMAGE" >/dev/null

echo "✓ 已启动: http://localhost:$PORT"
echo "✓ 生成文件在本地: $DATA_DIR/working/"
echo "✓ 停止: docker stop $NAME   查看日志: docker logs -f $NAME"
