# Release v2.1 — Code Review Hardening + Regression Test Framework

> Release date: 2026-06-16

## Overview

v2.1 is a **maintenance version** that closes all 24 issues from the full code review (security, correctness, robustness), and introduces an **automated regression test framework** so major-version releases stay verifiable. It also brings convenience fixes like API Key reset and longer keyframes submission timeouts.

## Usage

From v2.0, upgrade in place:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Run the smoke check:

```bash
.venv/bin/python scripts/regression_runner.py --auto-start
```

## What's New

### Features & Improvements

- **API Key clear/reset** — cleanly clear a key in the Web UI instead of only overwriting it.
- **Automated regression framework** — `scripts/regression_runner.py` runs 9 scenarios concurrently (WeightedSemaphore, total weight ≤ 10), with incremental JSON + Markdown reports, endpoint verification, artifact checks, and resume / quick-verify / `--cleanup` modes.
- **Longer keyframes timeout** — video submission timeout raised to 180s for keyframes-heavy tasks to avoid spurious failures on slow renders.

### Refactoring & Optimizations

- **Security hardening (H1–H6)** — API Key reads unified via `config.py` (no hardcoded keys); upload path traversal blocked; shell injection removed (`shell=True` → list args); CJK font fallback in subtitle overlay; moviepy log leakage silenced; JSON parse failure in screenwriter hardened with LLM retry fallback.
- **Robustness (M1–M10, L1–L8)** — index/bounds safety, granular exception handling, path normalization, unified HTTP timeouts, task-state race fix, TTS file handle leak fix, i18n variable shadowing fix, dead-file cleanup, and the first automated unit test suite.

### Bug Fixes

- UI bug: switching language no longer flips the API Key status display back to "not configured".
- Subtitle multi-line wrapping (dynamic `max_chars_per_line`, CJK punctuation-break priority, `method="caption"`).
- TTS edge-case error handling with automatic 2.5× volume boost.
- Concatenator single-video shortcut optimization + subtitle overlay failure degradation (non-blocking).
- `start.sh` auto-creates venv, installs dependencies, and opens the browser on macOS.