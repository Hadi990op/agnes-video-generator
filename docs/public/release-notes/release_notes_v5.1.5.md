# Release v5.1.5 — Quick Start on Docker / npm Pages + npm Release Section

> Release date: 2026-07-25

## Overview

v5.1.5 is a **patch release** that adds **Quick Start** blocks to the Docker Hub and npm package pages and includes the npm section in the release notes, so each release's "What's New" content is shown at the top of both distribution pages.

## Usage

From v5.1.4:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Quick Start on Docker / npm pages** — Docker Hub overview and npm README both lead with a Quick Start (pull / run / `npx free-short-video`) followed by the current release's "What's New", so distribution-page visitors see release content first.

> Note: from this release on, each release's What's New section is automatically prepended to the front of the Docker Hub and npm pages.
