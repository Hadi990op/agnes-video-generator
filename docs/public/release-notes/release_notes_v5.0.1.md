# Release v5.0.1 — Subtitle Two-Line Limit + Voice-Language Fix + Test Coverage CI

> Release date: 2026-07-23

## Overview

v5.0.1 is a **patch release** that enforces a **maximum of two subtitle lines** for every language, fixes digital-anchor voices being wrongly reported as "unsupported" for cross-language tasks, and adds an automated unit-test coverage pipeline to CI.

## Usage

From v5.0.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Subtitles in all languages are now capped at two lines for consistent rendering.
- Digital-anchor tasks no longer misreport cross-language voices as "unsupported".

### Refactoring & Optimizations

- Unit tests now run on push to any branch, with coverage reported in the GitHub Actions job summary.
