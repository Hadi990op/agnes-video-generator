# Release v4.7.5 — Release Workflow CI Fix

> Release date: 2026-07-22

## Overview

v4.7.5 is a **patch release** that fixes the release workflow's orphan-cleanup step, which used secrets in an `if` condition where the secrets context is unavailable — preventing the release pipeline from failing.

## Usage

From v4.7.4:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Release workflow: orphan-cleanup step no longer references secrets in an `if` condition, keeping the multi-arch image publish reliable.
