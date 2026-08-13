# Release v5.2.1 — Image Generation Retry + Analytics

> Release date: 2026-08-03

## Overview

v5.2.1 is a **patch release** that widens the image-generation read timeout and adds one retry for slow image renders, plus optional GA4 analytics for user operations and error reporting.

## Usage

From v5.2.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Optional GA4 analytics** — track user operations and error reporting; a setup script auto-configures custom dimensions and key events.

### Bug Fixes

- Image generation: read timeout widened and one retry added for slow image renders, reducing spurious failures on slower connections.
