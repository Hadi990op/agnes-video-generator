# Release v4.7.3 — Workspace Persistence via VOLUME + One-Command Launch

> Release date: 2026-07-22

## Overview

v4.7.3 is a **patch release** that makes Docker **data persistence** explicit: the image declares `VOLUME` for the working directory and config, and release notes document one-command launch with bind mounts so generated videos and settings survive container recreation.

## Usage

From v4.7.2:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Docker data persistence** — the image now declares `VOLUME` for `/app/.working_dir` and `/app/.agnes_config`; one-command launch and bind-mount run methods are documented so outputs and settings survive container recreation.

> Note: a plain `docker run` without `-v` keeps data only while reusing the same container (`stop`/`start`); recreating the container starts fresh. Use bind mounts or named volumes to persist data.
