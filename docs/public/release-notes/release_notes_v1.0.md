# Release v1.0 — AI Video Generator with Web UI + Keyframes Chaining

> Release date: 2026-06-13

## Overview

v1.0 is the **initial release** of Agnes Video Generator: a completely free AI video generation tool powered by the Agnes AI API. It turns a text idea into multi-scene AI videos automatically — with a Web UI, character reference images, end-frame control, three video chaining modes, and checkpoint resume.

## Usage

### Prerequisites

- Python 3.10+
- ffmpeg (for AI video concatenation)

### One-Click Launch

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

Your browser will automatically open `http://localhost:8765`.

### Manual Launch

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Then configure your Agnes API key in the Web UI (also settable via the `/api/config` endpoint).

## What's New

### Features & Improvements

- **Web UI** — one-click launch, operate entirely in the browser, no command line needed.
- **AI-powered full pipeline** — idea → story → character reference → script → per-scene AI video → final video.
- **Custom reference image** — upload a character reference image for consistent character appearance across all scenes.
- **Custom end frames** — specify end frame images for each scene to precisely control AI video output.
- **Image-to-image end frames** — auto-generate scene end frames via img2img based on the reference image.
- **Three video chaining modes** — `keyframes` (recommended) / `ti2vid` (transition frames) / `none` (independent scenes).
- **Checkpoint resume** — auto-resume interrupted AI video tasks from the last checkpoint; no duplicate uploads or generation.
- **Real-time progress** — WebSocket-powered live progress updates for every step of AI video generation.
- **Multi-language support** — 中文 / English / Русский / 日本語 / 한국어 / Bahasa Melayu / Bahasa Indonesia.
- **In-page API Key configuration** — configure your Agnes API key directly in the Web UI.

### Bug Fixes

- Standardized all API timeouts (image 120s, video 300s, LLM 120/300s) with separate connect/read timeouts.
- i2i end-frame read timeout fix — async base64 encoding, timeout raised to 120s, exponential backoff.
- Video duration parsed from the user requirement text; frontend duration selector wired through server and pipeline.
- Task list crash and API key status overwrite caused by i18n variable shadowing.
- Resume-flow bugs, log noise, and missing network logs.
