# Release v4.7.1 — Docker Build Source Default Fix

> Release date: 2026-07-22

## Overview

v4.7.1 is a **patch release** that makes the Docker image build default to the **official PyPI** as the Python package source, with China-local builds available via an opt-in build argument — improving build reliability across regions.

## Usage

From v4.7.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Bug Fixes

- Docker builds now default to the official PyPI source; builds inside mainland China can opt into a local mirror via a build argument.
