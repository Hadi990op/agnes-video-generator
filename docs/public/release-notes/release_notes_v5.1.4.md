# Release v5.1.4 — Docker Hub Short Description Limit Fix

> Release date: 2026-07-25

## Overview

v5.1.4 is a **patch release** that truncates the Docker Hub short description to ≤100 bytes — the previous 108-byte description caused the whole overview PATCH to be rejected, leaving the page title unchanged.

## Usage

From v5.1.3:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Docker Hub overview update now respects the 100-byte short-description limit, so the page title and description publish correctly.
