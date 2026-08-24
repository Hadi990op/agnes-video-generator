# Agnes Video Generator — 容器化构建
# 单阶段：python:3.11-slim + 内置 ffmpeg（硬依赖）+ CJK 字体（随仓库 resource/）
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg + ffprobe 是视频拼接/音频处理的硬依赖。
# 使用 apt 安装以同时获得 ffmpeg 和 ffprobe（imageio-ffmpeg 只提供 ffmpeg）
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version | head -1 \
    && ffprobe -version | head -1

# 先装项目 Python 依赖（利用层缓存）
COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip config set global.index-url "$PIP_INDEX_URL"; \
    fi \
    && pip install --no-cache-dir --default-timeout=600 -r requirements.txt \
    && if [ -n "$PIP_INDEX_URL" ]; then \
        pip config unset global.index-url; \
    fi

# 拷贝应用代码（resource/fonts 含 CJK 字体，必须随镜像）
COPY . .

EXPOSE 8765

# 声明持久化卷：即使不加 -v 直接 docker run，以下两个目录也会落到 Docker 管理的卷里，
# 同一容器 stop/start 时数据保留；可用 `docker cp 容器名:/app/.working_dir ./out` 导出。
# 若要数据直接落盘到本机并随时导出，推荐用 docker-compose.yml 或 docker-run.sh（bind mount）。
VOLUME ["/app/.working_dir", "/app/.agnes_config"]

# server.py 内部以 host=0.0.0.0 port=8765 启动，容器外可访问
# API Key 通过环境变量注入：-e AGNES_API_KEY=xxx（也可在 Web UI 配置）
CMD ["python", "server.py"]
