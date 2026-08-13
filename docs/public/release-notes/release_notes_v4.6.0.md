# Release v4.6.0 — Poetry Video Task Type + MultiScene Pipeline Refactor

> Release date: 2026-07-12

## Overview

v4.6.0 is a **minor version** that introduces the **Poetry Video (诗词视频)** task type — ancient poems are split into scenes by the LLM, each line is read aloud by TTS and aligned to video subtitles — and refactors the long-video pipelines onto a shared **MultiScenePipeline** base.

## Usage

From v4.5.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Poetry Video (诗词视频) task type** — new `POST /api/tasks/poetry`: the LLM splits a poem into scenes (original line | visual description format), each line is rendered by TTS narration, scenes are generated as t2v clips, and subtitles are time-aligned to the narration and concatenated.
- **Poetry scene config aligned with creative video** — per-scene duration model and duration-extraction mode; scene count / watermark / narration speed options.
- **Two-phase poetry generation** — scenes are submitted in a batch and awaited in parallel for faster completion.

### Refactoring & Optimizations

- **MultiScenePipeline base class** — creative / manuscript / anchor / poetry long-video pipelines now share one template-method base (`build_scenes → build_reference_images → generate_videos → audio+subtitle → composite`), eliminating duplicated per-pipeline logic.
- **Poetry generation reuses the base generator** — video generation is hoisted to `MultiScenePipeline._generate_videos`.

### Bug Fixes

- Per-scene TTS audio truncation in poetry videos (only the first half audible).
- Resume reused a stale `final_clip.mp4` without an audio track.
- Poetry progress step indicator not displayed.
- `switchTaskType` missing a closing brace, which disabled all page JS.
