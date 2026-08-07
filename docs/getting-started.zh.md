# 🚀 快速开始

**[🌐 官网](https://video.lichuanyang.top)** | **[🎬 在线体验（免安装）](https://video.lichuanyang.top/demo)** | **[📚 模型文档](https://video.lichuanyang.top/guides/model-overview)**

## 环境要求

- Python 3.10+
- ffmpeg（视频拼接和音频处理用）

就这些。不需要 GPU，不需要大内存，普通笔记本即可。

> 说明：手动部署（方式 A）需要本机 ffmpeg；Docker（方式 B）和 npm（方式 C）已内置 ffmpeg，无需另行安装。

## 方式 A：手动部署

**第一步 — 克隆 & 启动**

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

脚本会自动创建虚拟环境、安装依赖，并在浏览器中打开 `http://localhost:8765`。也可以手动启动：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

**第二步 — 配置 API Key**

前往 [Agnes AI](https://platform.agnes-ai.com) 获取免费 API Key，然后二选一：

```bash
# 方式 1：环境变量
export AGNES_API_KEY="your-api-key"

# 方式 2：通过 API 设置（等同于在 Web UI 中填写）
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}'
```

**第三步 — 创建第一个视频**

打开 `http://localhost:8765`，选择视频模式（简单 / 创意 / 稿件 / 数字人），输入创意描述，点击"开始生成视频"。

## 方式 B：Docker 部署（无需安装 Python/FFmpeg）

每次 release 都会推送预构建的多平台镜像（`linux/amd64`、`linux/arm64`）至 **GitHub Container Registry (GHCR)** 和 **Docker Hub**。

**拉取并运行**

```bash
# GHCR
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=<你的key> \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  ghcr.io/lcy362/free-short-video:latest

# Docker Hub
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=<你的key> \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  lcy362/free-short-video:latest
```

然后打开 `http://localhost:8765`。

**数据持久化**：应用会将视频、上传文件和设置写在容器内的 `/app/.working_dir` 和 `/app/.agnes_config` 目录。务必挂载到本机，否则容器重建后数据丢失且无法导出。挂载后生成的视频就在 `~/agnes-data/working/` 目录，直接可拷。

也可以用项目自带的 `docker-compose.yml` 一键启动：

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
AGNES_API_KEY=<你的key> docker compose up -d
```

## 方式 C：npm 部署（一条命令）

如果你已安装 **Node.js 18+** 和 **Python 3.10+**，整个服务以 npm 包形式提供——无需克隆代码、无需手动建 venv：

```bash
# 直接运行，无需安装
npx free-short-video

# 或全局安装后运行
npm install -g free-short-video
free-short-video          # 简写别名：fsv
```

首次运行时，启动器会自动创建本地虚拟环境、安装 Python 依赖、接入**内置的 ffmpeg**（`imageio-ffmpeg` 提供的静态二进制，现已在 `requirements.txt` 中显式声明，因此无需在系统中安装 ffmpeg），在 `http://localhost:8765` 启动服务并打开浏览器。可通过环境变量传入 Key，或稍后在 Web UI 中设置：

```bash
AGNES_API_KEY=<你的key> npx free-short-video
```

可用参数：`--port <n>`、`--host <h>`（用 `0.0.0.0` 允许局域网访问）、`--no-open`。

### ffmpeg：默认内置，或自行安装

使用 npm 包时，**通常无需自行安装 ffmpeg**——启动器（`bin/cli.js`）会自动把 `imageio-ffmpeg`（静态 ffmpeg 二进制，已在 `requirements.txt` 中显式声明）安装到本地 venv，并将其所在目录加入 `PATH`，因此 Python 服务内部所有 `ffmpeg` 调用都会解析到内置二进制。在 macOS、Linux、Windows 上均可开箱即用。

**如果你想在系统中自行安装 ffmpeg**（推荐用于生产 / 追求最高稳定性的场景——系统 ffmpeg 在 `PATH` 中位置更靠前，会优先于内置二进制被使用）：

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg

# CentOS / RHEL（需先启用 RPM Fusion）
sudo dnf install ffmpeg

# Windows（Chocolatey）
choco install ffmpeg

# Windows（Scoop）
scoop install ffmpeg
```

也可从 <https://ffmpeg.org/download.html> 下载并加入 `PATH`。验证：

```bash
ffmpeg -version
```

**如果不安装系统 ffmpeg（即完全依赖内置 `imageio-ffmpeg`）可能存在的风险：**

- **平台 / 架构支持** —— `imageio-ffmpeg` 仅为常见平台提供预编译二进制（macOS x86_64/arm64、Linux x86_64/arm64、Windows x64）。在极小众或老旧架构上可能不存在对应的 wheel，导致内置二进制缺失。
- **单一依赖来源** —— 全部 ffmpeg 能力都来自这一份静态二进制。若其安装 / 解压异常（磁盘权限、文件损坏），问题只会在**生成视频时**才暴露，而非服务启动时；报错为底层 `FileNotFoundError: 'ffmpeg'`，比启动期检查更难排查。
- **版本固定** —— 内置 ffmpeg 被锁定为 `imageio-ffmpeg` 所附带的具体版本（如 ffmpeg 7.1），无法自行升级。
- **缓解建议** —— 对生产或稳定性要求较高的用户，建议按上文自行安装系统 ffmpeg；内置二进制则作为兜底。

## 方式 D：AI Agent 辅助部署

本项目专为 AI 编程助手友好设计。先由你下载代码并准备好 API Key：

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
```

然后告诉你的 Agent：

> "阅读这个项目的 AGENTS.md，安装依赖，配置 API Key `<your-key>`，然后启动服务。"

Agent 会读取 `AGENTS.md`（一份完整的部署指引），自动完成：环境检查（Python 3.10+、ffmpeg）、`pip install`、服务启动和 API Key 写入。启动后还可以让 Agent 验证部署：

> "跑一下部署验证检查。"

Agent 会按 `AGENTS.md` 中的四层验证清单（连通性 → 静态分析 → 端点测试 → 字幕功能）逐项执行并汇报结果。

---

> 💡 想跳过安装？直接打开 [在线体验](https://video.lichuanyang.top/demo) 免安装使用。
