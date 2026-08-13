# Release v5.4.0 — 22-Language Support + Launcher Readiness Fix

> Release date: 2026-08-07

## Overview

v5.4.0 is a **minor version** that extends the Web UI language support to **22 languages** (aligned with the official site) and fixes the launcher so the browser opens only after the service is ready (no more start-blocking).

## Usage

From v5.3.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **22-language UI** — language support extended to 22 languages, aligned with the official site.
- **Favicon / icon served at root** — `/favicon.ico` and `/icon.png` are served at the root path to avoid transient 404s on page load.

### Bug Fixes

- Launcher now waits for the service to be ready before opening the browser, avoiding a blank page on startup.
