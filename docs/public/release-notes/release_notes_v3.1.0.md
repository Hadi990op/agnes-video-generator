# Release v3.1.0 — Task Queueing + Concurrency Control + UI Refinements

> Release date: 2026-06-22

## Overview

v3.1.0 is a **minor version** that adds **multi-task concurrency control** with a visible **task queue** in the Web UI, merges the Simple Video and Simple Image tabs into one unified tab, and switches the UI theme to blue. It also fixes two creative-video pipeline bugs introduced in v3.0.0.

## Usage

From v3.0.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Multi-task concurrency control** — a weighted semaphore lets multiple tasks run concurrently with automatic queueing; new tasks wait in line instead of blocking the UI.
- **Task queueing in the Web UI** — the frontend shows the `QUEUED` status for waiting tasks, with full i18n support across all languages.
- **Unified "Simple Image & Video" tab** — the Simple Video and Simple Image tabs are merged into a single form for faster access to single-shot generation.
- **Blue UI theme** — the interface theme switches from purple to blue.

### Bug Fixes

- Creative video subtitle step referenced the non-existent `CreativeVideoTask.combined_audio` field, failing the task.
- Creative video narration step used an invalid `SceneTask.scene_prompt` attribute.
