# Release v5.1.2 — npm Publish Guard Fix

> Release date: 2026-07-25

## Overview

v5.1.2 is a **patch release** that moves the npm-publish guard out of the job-level `if` (where GitHub rejects the secrets context) and into a shell check inside the step, keeping the npm publication optional and non-blocking for Docker releases.

## Usage

From v5.1.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Release workflow: npm publish is now guarded inside the step with a shell check; missing `NPM_TOKEN` skips only the npm publish and never blocks the Docker image release.
