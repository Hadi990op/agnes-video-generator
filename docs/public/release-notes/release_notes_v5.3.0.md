# Release v5.3.0 — Engineering Refactor Batch (Modularization + Test Coverage 63%)

> Release date: 2026-08-06

## Overview

v5.3.0 is a **minor version** that delivers the first engineering-refactor batches: the server entry is **modularized into a `web/` routing layer**, screenwriter / creative pipeline / subtitle / concatenator modules are split into packages, audio fallback is unified on a shared method, and unit-test coverage rises to **63% (291 tests)**. It also fixes the legacy `POST /api/tasks` endpoint broken since v3.x.

## Usage

From v5.2.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Refactoring & Optimizations

- **`web/` routing layer** — `server.py` is split into a modular route layer (`web/routes/`), improving structure and testability.
- **Package splits** — `screenwriter.py` → `core/screenwriter/`; the 1928-line `creative_video.py` → `core/pipelines/creative/`; `subtitle.py` and `concatenator.py` → packages; backward-compatible re-export alias modules kept.
- **Unified audio fallback** — poetry / manuscript / anchor / creative pipelines share one `_generate_audio_with_fallback` method instead of duplicated logic.
- **Typed config & constants** — typed `AppSettings` via Pydantic for config reads; progress literals and retry bases converged into named constants.
- **Stale-task sweep** — zombie task cleanup endpoint added.
- **Test coverage 55% → 63%** — 178 → 291 passing tests across all refactor batches.

### Bug Fixes

- Legacy `POST /api/tasks` endpoint (broken since v3.x) restored via router-level integration tests.
- Missing `re` import in the creative `steps_video` module.
- Regression checker now exempts v2.0 legacy step fields.
