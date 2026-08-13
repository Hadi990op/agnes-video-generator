# Release v4.7.0 — Resource Navigation + Voice Selector

> Release date: 2026-07-15

## Overview

v4.7.0 is a **minor version** that enriches the Web UI with **resource navigation** (demo / guides / FAQ / GitHub quick links, sticky desktop sidebars) and adds a full **voice selector** with per-language filtering, playback preview and cross-language compatibility checks for the 13 project languages.

## Usage

From v4.6.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Resource navigation bar** — quick-access links (Demo, Home, Guides, FAQ, GitHub) below the header.
- **Resource footer** — links to the project homepage, online demo, usage guides, FAQ, API docs and GitHub.
- **Sticky desktop sidebars** — on screens ≥1024px, a left sidebar (Star on GitHub, disable AdBlock, click ads) and a right sidebar (demo, guides, model overview, API docs) stick to the viewport; all external links open in new tabs.
- **Voice selector** — dynamic voice catalog filterable by the 13 project languages; voice preview playback with cross-language compatibility validation; detailed voice info (gender, region, styles).
