# Release v5.0.0 — Model Selector + Full 13-Language i18n

> Release date: 2026-07-22

## Overview

v5.0.0 is a **major version** that adds a **model selector** (choose text / image / video models in the UI) with beta-flag support and completes **13-language i18n** across the model selection module and all collapsible config panels.

## Usage

From v4.7.8:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Model selector** — choose text / image / video models directly in the UI; the new `agnes-2.5-flash` model shows an in-testing (beta) notice.
- **Full 13-language i18n** — the model selection module, collapsible panel titles (Text / Image / Video) and the beta flag are localized for all 13 supported languages.
- **UI polish** — three config panels now always show a title when collapsed; switching languages refreshes the model panel immediately.

### Refactoring & Optimizations

- Hard-coded Chinese strings in the model dropdown replaced with i18n keys covering all languages.
