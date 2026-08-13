# Release v5.1.7 — Dependency Declarations + Test Coverage

> Release date: 2026-07-27

## Overview

v5.1.7 is a **patch release** that consolidates the `imageio-ffmpeg` dependency declaration and ffmpeg documentation for npm users, and raises unit-test coverage from 55% to 58% with new `path_security` and `artifacts` tests.

## Usage

From v5.1.6:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- `imageio-ffmpeg` dependency explicitly declared; npm README documents ffmpeg setup.

### Refactoring & Optimizations

- Added `path_security` and `artifacts` unit tests, raising coverage from 55% to 58%.
