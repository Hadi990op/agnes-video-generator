# Release v4.7.7 — Docker Hub Description Limit Fix

> Release date: 2026-07-22

## Overview

v4.7.7 is a **patch release** that truncates the Docker Hub short description to the API's 100-byte limit so the repository overview update no longer gets rejected.

## Usage

From v4.7.6:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Docker Hub overview update now respects the 100-byte short-description API limit, so the description and README publish correctly.
