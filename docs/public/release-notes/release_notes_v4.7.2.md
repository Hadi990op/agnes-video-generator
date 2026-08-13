# Release v4.7.2 — GHCR & Docker Hub Pull Instructions

> Release date: 2026-07-22

## Overview

v4.7.2 is a **patch release** that documents both **GHCR and Docker Hub** pull commands in the release notes and fixes the GHCR image tag (drops the `v` prefix) so releases are easy to pull.

## Usage

From v4.7.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- Release notes now show both GHCR and Docker Hub pull commands; the GHCR tag format is corrected to drop the `v` prefix (e.g. `ghcr.io/lcy362/free-short-video:4.7.2`).
