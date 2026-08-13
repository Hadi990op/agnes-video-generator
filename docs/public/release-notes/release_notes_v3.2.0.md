# Release v3.2.0 — Multi-Workspace Management

> Release date: 2026-06-23

## Overview

v3.2.0 is a **minor version** that introduces **multi-workspace management**: add, switch, and manage multiple working directories directly from the Web UI using the system's native directory picker. Digital-anchor pipeline fixes and regression-tool alignment are included.

## Usage

From v3.1.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Multi-workspace management** — add, switch, and manage multiple working directories from the Web UI; each workspace keeps its own generated videos, uploads and settings.
- **Native directory picker** — cross-platform system directory selection replaces manual path input.
- **Locked regression working directory** — regression tests can pin their workspace via `AGNES_REGRESSION_WORKING_DIR`.

### Bug Fixes

- Digital-anchor pipeline now saves its `task.json` / `curl.sh` companion files.
- A2 regression check fixes — F1 path lookup and R3 model-audio step skipping.
- `scene_runner.py` validation logic aligned with `regression_runner.py`.
- Anchor pipeline method-name corrections and scene-prompt updates.
