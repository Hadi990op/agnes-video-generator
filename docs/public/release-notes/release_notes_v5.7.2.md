# Release v5.7.2 — Security Hardening & Progress Artifacts Restored

> Release date: 2026-08-13

## Overview

v5.7.2 is a **patch release** that hardens security (resolving GitHub Code Scanning alerts), restores intermediate-artifact display in the task progress panel after the frontend re-architecture, and fixes release pipeline issues.

## Usage

From v5.7.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

No breaking changes or data migration required.

## What's New

### Bug Fixes

- **Intermediate artifacts restored in the progress panel** — after the v5.7.0 frontend re-architecture, intermediate artifacts (story, reference images, scene videos, subtitles, etc.) were no longer shown while a task runs. The progress panel now loads artifacts on task start, refreshes them as each step completes during polling, and shows the final output when finished. Viewing a task from the task list also opens the progress panel with its artifacts and result video.
- **GitHub Code Scanning security fixes** — sensitive data no longer logged at startup (`get_api_keys_source`); key IDs are now derived with HMAC-SHA256 (blake2b keyed mode) instead of plain SHA-256; task-directory deletion/existence checks operate only on realpath-resolved paths (path-injection hardening).
- **Release pipeline fixes** — the npm README preparation step no longer fails when the format string starts with `-`, and the release workflow now tolerates missing release-notes docs with a warning instead of aborting.

---
