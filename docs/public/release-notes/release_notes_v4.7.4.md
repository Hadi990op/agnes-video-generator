# Release v4.7.4 — GHCR Package Ownership Fix

> Release date: 2026-07-22

## Overview

v4.7.4 is a **patch release** that fixes GHCR package ownership by logging in with the `GITHUB_TOKEN`, so the published image links to this repository and appears on the repository's Packages page.

## Usage

From v4.7.3:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- GHCR images are now pushed with the `GITHUB_TOKEN`, linking the package to this repository and enabling the multi-arch pull command to work reliably.
