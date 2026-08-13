# Release v5.2.0 — Agnes Domain Config (com/cn) + Windows Encoding Fixes

> Release date: 2026-07-28

## Overview

v5.2.0 is a **minor version** that adds **Agnes domain configuration** — switch the Agnes API endpoint between `.com` and `.cn` (fixing an `API_ROOT` undefined error) — and fixes all file `open()` calls to use explicit UTF-8 encoding, resolving Unicode errors on Windows.

## Usage

From v5.1.7:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Agnes domain config (com/cn)** — configure the Agnes API base domain; switching to the `.cn` domain now works without the previous `API_ROOT` undefined error.

### Bug Fixes

- All `open("w")` / `open("r")` calls now pass `encoding="utf-8"`, fixing `UnicodeEncodeError` on Windows when writing/reading task state and logs.
