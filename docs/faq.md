# ❓ FAQ

### Is Agnes Video Generator really free? Are there any hidden costs?

Yes, it is **completely free**. All AI model calls (Agnes Chat, Agnes Image, Agnes Video) are free of charge with no trial period, no watermarks, and no usage limits. The only TTS integration (Microsoft Edge TTS) is also free and requires no extra API key. You only need a free API key from [Agnes AI](https://platform.agnes-ai.com) to get started.

### Do I need a GPU to run this AI video generator?

No. All AI compute runs in the cloud via Agnes AI's free API. You just need a regular laptop or desktop computer that can run Python 3.10+ and ffmpeg. No GPU, no high RAM, no special hardware required.

### How is this different from Runway, Pika, or Sora?

Unlike commercial AI video tools that charge $10–$95/month, Agnes Video Generator is completely free and open-source (MIT). It offers built-in multi-scene pipelines, AI narration, auto subtitles, and digital anchor — features that require third-party tools or manual editing elsewhere. See the [comparison table](../README.md#comparison-agnes-vs-commercial-ai-video-tools) in the README for details.

### What video generation modes are supported?

Four modes: **Simple Video** (single prompt, full parameter control), **Creative Video** (AI story → multi-scene video with narration), **Manuscript Video** (long text → auto-split → narrated video), and **Digital Anchor** (AI anchor with TTS). Additional options include text-to-video, image-to-video, keyframes animation, and image-to-image end frame generation.

### Can I use my own images as references?

Yes. You can upload reference images for character or scene consistency across scenes, use custom end frames for precise visual transitions, or choose img2img to auto-generate end frames from your reference. Reference images are supported in both Creative Video and Digital Anchor modes.

### What languages does the UI support?

The Web UI supports 13 languages: 中文, English, Deutsch, Français, Nederlands, Español, Português, Italiano, Русский, 日本語, 한국어, Bahasa Melayu, and Bahasa Indonesia. Subtitles are generated in the source text language with CJK font support built-in.

### Can I run this with Docker?

Yes. Pre-built images are published to both [GHCR](https://github.com/lcy362/agnes-video-generator/pkgs/container/free-short-video) and [Docker Hub](https://hub.docker.com/r/lcy362/free-short-video). Just pull the `latest` tag and run — no Python or ffmpeg installation needed. See **[Option B: Docker](../docs/getting-started.md#option-b-docker-no-pythonffmpeg-required)** in Getting Started for the full command and volume mount instructions.

### Can I host this on my own server?

Absolutely. The project is designed for self-hosting. Just clone the repo, run `./start.sh`, and the server starts on `http://localhost:8765`. No external dependencies, no cloud lock-in. See the [Quick Start](../docs/getting-started.md) section.

### How do I get help or report issues?

Check the [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) page for existing reports or open a new one. The project also includes a comprehensive `AGENTS.md` for AI-agent-assisted debugging. For feature requests, bug reports, or questions, the Issues page is the best place.
