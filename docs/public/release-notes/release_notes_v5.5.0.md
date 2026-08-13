# Release v5.5.0 — Official-Site Link Alignment

> Release date: 2026-08-10

## Overview

v5.5.0 is a **patch release** that aligns the in-app referral links with the current official site (deprecated slugs dropped) and hardens the mirror-sync workflow permissions.

## Usage

From v5.4.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Referral links in the UI and scripts now point to the current official-site paths (deprecated slugs removed).
- Mirror-sync workflow granted explicit read-only permissions.
