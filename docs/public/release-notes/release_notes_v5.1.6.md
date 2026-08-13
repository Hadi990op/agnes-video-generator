# Release v5.1.6 — imageio-ffmpeg Dependency + ffmpeg Setup Docs

> Release date: 2026-07-27

## Overview

v5.1.6 is a **patch release** that explicitly declares the `imageio-ffmpeg` dependency and documents ffmpeg setup for npm users, ensuring video concatenation works out of the box after `npm install`.

## Usage

From v5.1.5:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- `imageio-ffmpeg` is now an explicit dependency, and the npm README documents ffmpeg setup so video concatenation works after `npm install -g free-short-video`.
