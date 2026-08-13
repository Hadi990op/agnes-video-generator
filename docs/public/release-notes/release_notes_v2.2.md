# Release v2.2 — i2i End Frames + Global Rate Limiter + Stability Enhancements

> Release date: 2026-06-19

## Overview

v2.2 is a **minor version** that introduces the **i2i (Image-to-Image) end frame pipeline** so character appearance stays visually consistent across creative-video scenes, plus a **global rate limiter**, unified API retry logic, and broad stability fixes from the second code-review batch. Creative videos now default to i2i end frames enabled.

## Usage

From v2.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **i2i end frame pipeline** — image model unified to `agnes-image-2.1-flash`; i2i array API; character reference images normalized in size; character appearance persisted across scenes via programmatic prompt injection; multi-image guided end frames create a visual chain linking scenes; keyframes fallback branch kept in sync.
- **Global rate limiter** — single shared token bucket (16 req/min) across Chat + Image + Video APIs keeps free-tier API usage within limits and prevents 429 storms.
- **i18n improvements** — duration parsing and localized defaults for user requirements / visual styles across all 7 languages.

### Refactoring & Optimizations

- **Unified API retry** — exponential backoff for 429 / 5xx across all three Agnes API modules.
- **Code-review Batch 2 fixes (P1–P13)** — video concatenation made async (no blocking), `active_pipelines` concurrency race fixed, `chat_json` robustness, prompt-injection protection, resource-leak cleanup, URL cache expiry, temp filename uniqueness.
- **Regression runner enhancements** — 404-polling detection, `--quick` manifest mode, auto-resume, resolution matching.

### Bug Fixes

- Resume crash fixes — `_upload_image_to_host` method name, `_run_pipeline` `task_id` undefined, `load()` creating empty directories.
- Custom end frame not applied; manuscript step-key alignment.
- Paused scopes: subtitle silent degradation on failure, SilentTTS return-code handling.
- Concatenator `AttributeError` on the video-concatenation failure path.