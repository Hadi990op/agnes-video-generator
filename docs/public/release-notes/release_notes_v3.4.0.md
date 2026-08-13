# Release v3.4.0 — Structured Scene Configuration + Per-Scene Durations

> Release date: 2026-06-30

## Overview

v3.4.0 is a **minor version** that refactors creative-video **scene configuration**: the free-text `user_requirement` is replaced by structured parameters (duration source, scene count, uniform or per-scene durations), and each scene can have its **own duration from 2 to 30 seconds**. The LLM now auto-extracts scene count and durations from your idea.

## Usage

From v3.3.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Structured scene configuration** — replace the free-text `user_requirement` with explicit parameters: `duration_source` (manual / extracted from creative description), `scene_count`, and `uniform_duration` / `scene_durations` (uniform or per-scene lengths).
- **Per-scene duration** — `SceneTask` supports an independent duration (2–30 s) for every scene.
- **LLM auto-analysis** — the LLM analyzes your idea to extract the scene count and per-scene durations automatically.
- **Collapsible panels** — API Key and workspace panels are now collapsible and auto-collapse when configured.

### Bug Fixes

- Collapsible panels could not be re-collapsed after expanding.
- Per-scene duration mode did not generate input fields on switch.
- Prompt mode wrongly reported scene count/duration validation errors.
