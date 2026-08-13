# Release v2.0 — Three-Pipeline Architecture + Multilingual Web UI

> Release date: 2026-06-15

## Overview

v2.0 is a **major version** that rebuilds the single-file script into an engineered application: **three video generation pipelines** (Simple / Creative / Manuscript), each with its own backend engine, a fully **internationalized 7-language Web UI**, and a rich **AI subtitle system** built on edge_tts word-level timestamps.

## Usage

From v1.0, upgrade in place — no data migration required:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh        # opens http://localhost:8765
```

> **Requirements**: Python 3.10+. New dependencies: `edge_tts>=6.1.0`, `srt>=3.5.0`.

## What's New

### Features & Improvements

- **Three task types with shared foundations** — Simple Video (single prompt → single video via Agnes Video API, `t2v`/`i2v`/`ti2vid`/`keyframes`), Creative Video (AI screenwriter → storyboards → per-scene videos → edge_tts narration → fine-grained subtitles → concatenation), Manuscript Video (long-text splitting → AI scene prompts → per-segment videos → unified TTS + subtitles → concatenation).
- **Multilingual Web UI** — three-tab single-page frontend (Simple / Creative / Manuscript) with i18n for 中文 / English / Русский / 日本語 / 한국어 / Bahasa Melayu / Bahasa Indonesia.
- **Real-time progress** — WebSocket push of pipeline progress; task pause, resume, and stop.
- **Fine-grained subtitle system** — word-level SRT grouping from edge_tts timestamps, CJK multi-line wrapping, `method="caption"` rendering with stroke / background / position customization.

### Refactoring & Optimizations

- **Four-layer architecture** — `core/api` (Agnes Chat / Image / Video wrappers with retry + polling), `core/audio` (edge_tts + SRT + moviepy overlay), `core/compositor` (concatenation / scaling / frame extraction), `core/pipelines` (three pipeline implementations).
- **Pydantic v2 data models** — typed task subclasses with persistent state serialization and backward-compatible task loading.
- **Two-phase manuscript generation** — A/B split of video generation for parallelism and faster completion.

### Bug Fixes

- MoviePy 2.x compatibility for subtitle `bg_color`/`position`; TTS volume auto-boosted.
- CJK font fallback for legacy tasks; bundled fonts shipped for reliable rendering.
- Video frame cap at the Agnes API limit (409 at 720p) with auto-retry for transient failures.
- Single continuous TTS + SRT for the manuscript pipeline, eliminating per-segment padding drift.

---

> Optional: Compatibility / configuration change notice — since v1.0, `start.sh` already bundles venv creation and dependency installation, so the first run after upgrading will set up the environment automatically.