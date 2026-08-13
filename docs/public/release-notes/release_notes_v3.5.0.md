# Release v3.5.0 — Video Watermark + Branding (favicon)

> Release date: 2026-06-30

## Overview

v3.5.0 is a **minor version** that adds a **video watermark** to all generated videos (language-aware, stream-processed with ffmpeg overlay to avoid OOM), generates a project **favicon & apple-touch-icon**, and moves the watermark switch into each generation tab. Video polling interval is relaxed to 60s.

## Usage

From v3.4.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Video watermark** — automatic watermark overlay on generated videos, with language detection and a UI toggle.
- **Per-tab watermark switch** — the watermark toggle moves from the task list into each generation tab (Simple / Creative / Manuscript / Anchor), below the subtitle config.
- **Project favicon** — favicon and apple-touch-icon generated with the Agnes Image API.
- **Watermark visuals** — repositioned watermark with a branded blue background and more natural informational copy.

### Refactoring & Optimizations

- **OOM-safe watermarking** — the watermark is composited with the ffmpeg `overlay` filter in a streaming pass instead of a MoviePy re-encode, eliminating `Killed: 9` out-of-memory failures on long videos.
- **Relaxed video polling** — polling interval raised from 30s to 60s to reduce rate-limit quota consumption.

### Bug Fixes

- Watermark switch was hidden behind the progress panel; moved to avoid occlusion.
- Auto-detect video dimensions for watermark placement.
