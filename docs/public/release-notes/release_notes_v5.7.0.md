# Release v5.7.0 — Multi-Key Rotation & Production-Grade Frontend

> Release date: 2026-08-13

## Overview

v5.7.0 is a **minor version** that upgrades the entire frontend from a single HTML file to a **Vue 3 + Vite + TypeScript engineering project**, and brings **multi-API-key rotation with layered rate limiting** for higher generation throughput, alongside user-supplied scene reference images, task deletion, and an API-key masking security fix.

## Usage

From v5.6.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

No breaking changes or data migration required. New environment variables (optional) are documented in `.env.example`.

## What's New

### Features & Improvements

- **Multi-API-Key rotation & throughput boost** — configure multiple Agnes API keys (env + config, auto-dedup); requests rotate across keys via a `KeyRing`, and an **instant retry on 429 key-switch** mechanism immediately switches to the next key on rate-limit instead of backing off. Layered rate limiting gives video submissions a dedicated `1×Key/min` bucket alongside the shared `20×Key×0.8/min` bucket, roughly doubling achievable throughput with 2 keys.
- **User-supplied scene reference images (creative)** — in creative long-video mode you can now upload a reference image per scene; the pipeline uses your image instead of AI-generated storyboard frames for that scene.
- **Task deletion (UI + API)** — delete completed task folders from the task list or via `DELETE /api/tasks/{id}`; running tasks are protected with a clear error. The whole `.working_dir` stays clean.
- **API-key list & per-key removal** — the settings panel now lists all configured keys with source badges (env/config); config-sourced keys can be removed individually without clearing everything.
- **Windows one-click start** — `start.bat` for native Windows usage without Docker.

### Refactoring & Optimizations

- **Frontend engineering re-architecture** — the single-file `index.html` was refactored into a **Vue 3 + Vite + TypeScript** project (`frontend/`) with build output committed to `static/`. This brings type safety, modular components/composables/i18n, and a stable dev/build workflow (verified by CI's frontend-build job).
- **Unified image normalization module** — new `utils/image_normalizer.py` normalizes reference/end-frame images to target size with black-bar padding before model submission, improving i2i/keyframes input consistency.

### Bug Fixes

- **API-key plaintext leak** — `GET /api/config/keys` now returns masked keys (`sk-xxx...xxxx`) with stable IDs instead of plaintext, preventing key disclosure via the API; deletion uses the stable ID.
- **Legacy task API compatibility** — the legacy `POST /api/tasks` route now forwards `scene_reference_images`, fixing CI failures for older clients.
- **JSON robustness** — optional `json_repair` fallback for LLM JSON responses with trailing commas / missing colons.
- **npm packaging** — exclude runtime-generated `static/generated/` from the published npm package.

---
