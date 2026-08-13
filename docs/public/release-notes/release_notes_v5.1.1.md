# Release v5.1.1 — npm Version Sync Fix

> Release date: 2026-07-25

## Overview

v5.1.1 is a **patch release** that fixes the npm version-sync step in the release workflow — the package version is now set with `npm pkg set` instead of a git commit, so the npm publish stays in sync with the tag even on a detached HEAD in CI.

## Usage

From v5.1.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Release workflow: npm version is synced via `npm pkg set` (no git commit on detached HEAD), keeping `npx free-short-video` versions aligned with the tag.
