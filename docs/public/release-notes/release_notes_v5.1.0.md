# Release v5.1.0 — Word-Level Subtitle Timeline + Security Hardening

> Release date: 2026-07-25

## Overview

v5.1.0 is a **minor version** that upgrades the subtitle engine to **word-level cue alignment** (v2.0 timeline; WhisperX dependency dropped — `edge_tts` cues are the source of truth), fixes narration-metadata leakage on resume, and closes **31 path-traversal vulnerabilities** found by GitHub code scanning.

## Usage

From v5.0.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Word-level subtitle timeline (v2.0)** — subtitles are aligned to `edge_tts` word-level cues, the exact source of truth; the WhisperX external dependency is removed, making subtitle timing precise and self-contained.

### Security Hardening

- **27 path-traversal issues + 1 stack-trace leak** fixed from GitHub code scanning (PR #21).
- **4 remaining path traversals** in workspace endpoints fixed (CodeQL sink sanitization, PR #22).
- **Workspace endpoint path traversal** closed by sanitizing the trusted root (#29–#32, PR #23).

### Bug Fixes

- Narration metadata leaking between tasks on resume; resumed subtitle generation falls back to the legacy path correctly.
