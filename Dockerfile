# Agnes Video Generator — 容器化构建
# 单阶段：python:3.11-slim + 内置 ffmpeg（硬依赖）+ CJK 字体（随仓库 resource/）
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg 是视频拼接/音频处理的硬依赖，必须在运行时存在
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 先装 Python 依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码（resource/fonts 含 CJK 字体，必须随镜像）
COPY . .

EXPOSE 8765

# server.py 内部以 host=0.0.0.0 port=8765 启动，容器外可访问
# API Key 通过环境变量注入：-e AGNES_API_KEY=xxx（也可在 Web UI 配置）
CMD ["python", "server.py"]
