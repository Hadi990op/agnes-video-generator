# ❓ 常见问题

### Agnes Video Generator 真的完全免费吗？有没有隐藏费用？

是的，**完全免费**。所有 AI 模型调用（Agnes Chat、Agnes Image、Agnes Video）均免费，无试用期、无水印、无用量限制。唯一的 TTS 集成（微软 Edge TTS）也是免费的，无需额外 API Key。你只需要从 [Agnes AI](https://platform.agnes-ai.com) 获取一个免费的 API Key 即可开始使用。

### 运行这个 AI 视频生成器需要 GPU 吗？

不需要。所有 AI 计算都在云端通过 Agnes AI 的免费 API 完成。你只需要一台能运行 Python 3.10+ 和 ffmpeg 的普通电脑，无需 GPU、无需大内存、无需任何特殊硬件。

### 这个工具和 Runway、Pika、Sora 有什么不同？

商业 AI 视频工具每月收费 $10–$95，而 Agnes Video Generator 完全免费且开源（MIT）。它还内置了多场景流水线、AI 旁白配音、自动字幕和数字人口播——这些功能在其他平台要么需要第三方工具，要么需要手动编辑。详见 [README 中的对比表格](../README_ZH.md#对比agnes-与商业-ai-视频工具)。

### 支持哪些视频生成模式？

四种模式：**简单视频**（单条 prompt，完整参数控制）、**创意长视频**（AI 故事 → 多场景视频 + 旁白）、**稿件长视频**（长文本 → 自动拆段 → 配音视频）、**数字人口播**（AI 数字人 + TTS）。额外支持文生视频、图生视频、关键帧动画、图生图尾帧等。

### 可以使用自己的图片作为参考吗？

可以。你可以上传参考图来保持角色或场景的一致性，使用自定义尾帧精确控制画面过渡，或选择 img2img 从参考图自动生成尾帧。创意长视频和数字人口播模式均支持参考图。

### Web UI 支持哪些语言？

界面支持 13 种语言：中文、English、Deutsch、Français、Nederlands、Español、Português、Italiano、Русский、日本語、한국어、Bahasa Melayu、Bahasa Indonesia。字幕以源文本语言生成，内置 CJK 字体支持。

### 可以用 Docker 部署吗？

可以。预构建镜像已推送至 [GHCR](https://github.com/lcy362/agnes-video-generator/pkgs/container/free-short-video) 和 [Docker Hub](https://hub.docker.com/r/lcy362/free-short-video)。拉取 `latest` 标签后直接运行，无需安装 Python 或 ffmpeg。详见快速开始中的 **[方式 B：Docker 部署](../docs/getting-started.zh.md#方式-bdocker-部署无需安装-pythonffmpeg)**。

### 可以部署在自己的服务器上吗？

完全可以。本项目专为自托管设计。克隆仓库后运行 `./start.sh`，服务即启动在 `http://localhost:8765`。无外部依赖、无云锁定。详见 [快速开始](../docs/getting-started.zh.md)。

### 如何获取帮助或报告问题？

请访问 [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) 页面查看已有报告或提交新 Issue。项目还包含完整的 `AGENTS.md` 部署指引，支持 AI 编程助手辅助调试。

---

## 📚 更多资源

- [🌐 官网](https://video.lichuanyang.top) — 项目主页与最新资讯
- [🎬 在线体验](https://video.lichuanyang.top/demo) — 免安装直接使用
- [📋 API 文档](https://video.lichuanyang.top/api-docs) — 完整接口列表
