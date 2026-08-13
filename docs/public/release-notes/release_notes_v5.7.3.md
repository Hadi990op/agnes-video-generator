# Release v5.7.3 — GA4 Mode-Level Video Analytics

> Release date: 2026-08-13

## Overview

v5.7.3 is a **patch release** that enriches Google Analytics 4 event tracking: task completion and failure events now carry the video generation mode (`t2v` / `i2v` / `ti2vid` / `keyframes`), so usage and generated-video counts can be broken down per mode in GA4 reports.

## Usage

From v5.7.2:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

No breaking changes or data migration required.

## What's New

### Features & Improvements

- **Mode-level analytics for generated videos** — the `task_completed` and `task_failed` GA4 events now include the `mode` parameter for simple video tasks (`t2v` / `i2v` / `ti2vid` / `keyframes`). Combined with the existing `task_type` and `mode` dimensions on `create_task`, GA4 reports can now show both usage counts (tasks started) and generated-video counts (tasks completed) per task type and per video mode. This lets you answer questions like "how many keyframes videos were generated this week".

### Bug Fixes

- None.

---
