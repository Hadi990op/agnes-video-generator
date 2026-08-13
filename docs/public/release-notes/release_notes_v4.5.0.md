# Release v4.5.0 — Intermediate Artifacts Viewer + Error Collector + Pure Polling

> Release date: 2026-07-07

## Overview

v4.5.0 is a **minor version** that adds an **intermediate-artifacts viewer** (prompts / images / videos produced at each step) with cascading deletion, a **model API error collector** that logs detailed failure info, and replaces WebSocket progress with **pure polling** for simpler, faster task updates.

## Usage

From v4.0.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Intermediate-artifacts viewer** — the task detail panel shows every step's intermediate outputs (prompts / images / videos), filterable by mode (creative / manuscript / anchor), with cascading deletion that clears the corresponding state fields, resets downstream steps, and cleans up files.
- **Model API error collector** — new `core/api/error_collector.py` records complete failure info (prompt, error type, HTTP status code, response body, retry count) for text/image/video API calls on every failed attempt (including mid-retry), stored under the active workspace's `error_logs/`. API-level error details (e.g. `content_policy_violation`) are now extracted instead of a generic status code.

### Refactoring & Optimizations

- **Pure-polling progress** — WebSocket removed; progress is read via `GET /api/tasks/{id}` with frontend polling (default 30s interval), reducing complexity and making new/resumed task progress display faster and more stable.
- **Step-state rendering fix** — resumed/reopened tasks no longer flash gray on completed steps; colors derive directly from the state field.
- **Dynamic image-generation timeout** — 60s first attempt, extending to 120s / 180s on retries to avoid premature failures on slow networks.

### Bug Fixes

- Artifact deletion now allowed in the stopped state (was 409).
- Artifact list refreshes live while a task is running.
- Intermediate videos play correctly — `<video>` tag `type="video/mp4"` / `playsinline` / size constraints completed.
- Play-button clicks fixed — bypassed the `backdrop-filter` stacking-context block of the glass card.
