# Release v5.7.1 — CI Release Pipeline Fix

> Release date: 2026-08-13

## Overview

v5.7.1 is a **patch release** that fixes a bug in the GitHub Actions release workflow. The v5.7.0 Docker image and GitHub Release were published successfully; this patch enables the **npm package publishing** step that previously failed.

## Usage

Same as v5.7.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

No code changes to the application itself.

## What's New

### Bug Fixes

- **npm publish step fails with `printf: --: invalid option`** — the release workflow's "Prepare npm README" step used `printf '---\n...'` whose format string starts with `-` and is treated as a CLI option by bash, exiting with code 2. Fixed by using `printf '%s\n'` so the format string is never parsed as an option.
- **npm package publishing restored** — with the above fix, `npm publish` (when `NPM_TOKEN` is configured) now runs as part of the release pipeline.

---
