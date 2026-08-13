# Release v4.7.6 — Correct GHCR Two-Level Path

> Release date: 2026-07-22

## Overview

v4.7.6 is a **patch release** that fixes the GHCR image path to the correct two-level form (`ghcr.io/lcy362/free-short-video`) and removes a bogus orphan-cleanup step, so `docker pull ghcr.io/lcy362/free-short-video:<version>` works as documented.

## Usage

From v4.7.5:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- GHCR pull path corrected to `ghcr.io/lcy362/free-short-video:<version>`; the invalid orphan-cleanup step is removed.
