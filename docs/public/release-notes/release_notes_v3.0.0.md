# Release v3.0.0 — Subtitle & Narrator Independent Control + AI Subtitle Styling + Digital Anchor + Image Generation

> Release date: 2026-06-21

## Overview

v3.0.0 is a **major version** that introduces **four significant capabilities**: independent subtitle/narrator control, AI-powered subtitle styling, a new **Digital Anchor** video task type, and **simple image generation**. It also delivers extensive subtitle rendering improvements and system-prompt support for both video and image tasks.

## Usage

From v2.2:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

> **Breaking change**: `AudioConfig.subtitle_style` has been removed. Legacy task states are auto-migrated on load — no manual intervention required.

## What's New

### Features & Improvements

- **Subtitle & narrator independent control** — `SubtitleConfig` elevated to a peer of `AudioConfig`, each with its own `enabled` toggle; four combination modes (narrator+subtitle, narrator-only, subtitle-only, silent); new `subtitle_enabled` parameter on creative and manuscript endpoints.
- **AI-powered subtitle styling (LLM mode)** — `style_mode` `"fixed"` (global style) or `"llm"` (per-subtitle position/color/font size decided by the LLM); `style_hints` accepts natural-language guidance ("key lines in red, summaries in yellow"); `generate_subtitle_styles()` sends all subtitles to the LLM in one call and renders via sidecar `subtitle_styles.json`.
- **Digital Anchor task type** — AI-generated presenter via t2i or i2i (user-uploaded reference photo); manuscript split into 5–12s paragraphs, each generating a unique i2v clip with different gestures/expressions; unified TTS + LLM-optimized subtitle overlay; audio from the model or post-concatenation; `POST /api/tasks/anchor`.
- **Simple image generation** — new fifth tab; lightweight `SimpleImageTask`; system-prompt support; `GET /api/image/{id}` to retrieve results.
- **System prompt support** — optional system prompt for simple video and image tasks, prepended to the final prompt.

### Refactoring & Optimizations

- **Pipeline step split** — `_step_audio_subtitle` replaced by independent `_step_audio` + `_step_subtitle` in creative and manuscript pipelines.
- **Subtitle rendering improvements** — multi-line display with 0.3s overlap, 0.8s transition overlap, two-pass `extend-end` timing, safe-margin overflow protection, LLM vertical-zone positioning for visual variety.

### Bug Fixes

- `subprocess.run` now passes `stdin=DEVNULL`, preventing background-process SIGTTIN hangs.
- `SilentTTSEngine.generate()` returns `None` → empty `dict`, fixing SRT generation in subtitle-only mode.
- SRT timeline is based on actual audio duration instead of estimated video duration.
- Image generation failures now surface the specific error (HTTP status + body + traceback).
- Defensive UTF-8 encoding fix in the digital-anchor pipeline; TTS now runs first to obtain the real audio duration.