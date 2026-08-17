# Release v6.0.0 — Manual Mode: Pause, Refine, and Continue at Every Checkpoint

> Release date: 2026-08-17

## Overview

v6.0.0 is a **major version** centered on **Manual Mode** — a human-in-the-loop workflow that pauses the video pipeline at configurable **checkpoints** so you can preview, refine, or regenerate each intermediate artifact before continuing. It ships with **four ways to edit artifacts** (AI-assisted editing, local editing, external Agent collaboration, and inline online editing), an **artifact-level dependency graph** that reruns only the affected steps, a **dedicated task progress page**, and **full 22-language i18n**. Auto Mode stays the default and remains fully compatible.

## Usage

From v5.7.4:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

No data migration required. Existing tasks and auto-mode behavior are unchanged.

## What's New

### Manual Mode (Human-in-the-Loop Checkpoints)

Manual Mode pauses your pipeline at the checkpoints you choose, so you can confirm, modify, or regenerate each intermediate artifact before continuing — "auto for vibe, manual for precise output."

- **Checkpoint pausing** — the pipeline stops at a checkpoint after the artifacts are produced, waits for your action, and continues from the last confirmed stage.
- **Fine-grained pause points (creative)** — up to 10 stages: image analysis, story, script & narration, character reference, end-frame prompts, end-frame generation, videos, audio, subtitle, and final composite.
- **Standard pause points (manuscript / poetry / anchor)** — 6 stages: scenes, references, videos, audio, subtitle, and final.
- **Pre-filled default pause points** — filled in automatically per task type at creation (editable; unchecked checkpoints pass through automatically).
- **Not supported** — simple (single-shot) video and simple image tasks only show the artifact list on completion.

### Four Ways to Refine Artifacts

At each paused checkpoint you can pick any of these ways to handle the current artifacts:

- 🤖 **AI-assisted editing** — describe your change (e.g. "make scene 2 more cinematic") and the built-in model rewrites the artifact; review the diff before applying.
- ✏️ **Edit locally** — copy the artifact path and edit the file directly (JSON / SRT / images / videos), then click "modified, continue".
- 🤝 **External Agent** — copy a ready-made collaboration prompt and hand the artifact to a more capable local Agent (e.g. opencode / CodeBuddy CLI / ffmpeg / PIL), then fill the result back in.
- 💻 **Online editing** — edit text artifacts (script / narration / subtitles) in an in-page dialog with side-by-side comparison against the original.

### Artifact-Level Dependency Graph (Rerun Only What Changed)

After any modification, the system computes affected downstream artifacts precisely and reruns only those — the rest are kept untouched:

- Edit narration → reruns audio / subtitle / final only.
- Edit scene descriptions → reruns reference images / videos / final only.
- A "before-modification" prompt lists exactly which artifacts will be regenerated vs. retained.

### Switch Between Auto and Manual Anytime

- Switch an **auto** task to manual while running — it pauses at the next safe checkpoint.
- Switch a **manual** task back to auto while paused — pause points are cleared and it runs straight to completion.

### Other Features & Improvements

- **Dedicated task progress page** — a focused, full-page progress view with step timeline and live status.
- **Task detail page** — opens in a new tab with official-site links and support guidance.
- **Project card pinning** — pin a task card to the top of the list; artifact previews auto-expand.
- **"Continue without changes" button** at every pause point — skip review on any channel.
- **Bilingual startup scripts** — prompts adapt to the system locale.
- **Full 22-language i18n** — missing translations completed, plus a new language-completeness checker used as a release regression gate and a language switcher in the task progress header.

### Refactoring & Optimizations

- **Unified checkpoint mechanism across pipelines** — the same MultiScenePipeline checkpoint system now powers creative, manuscript, poetry, and anchor tasks, with per-type artifact matrices.
- **Standalone artifact dependency graph** — `core/dependency_graph.py` is a pure, declarative edge-table module (product-level + parameter-level) shared by impact prediction, approve handling, and frontend highlighting; fully unit-tested.
- **Standardized artifact manifests** — per-checkpoint `checkpoint.json` lists and task-directory `MANIFEST.md` make every intermediate artifact discoverable, readable, and refillable.
- **Resume skips completed scene-building steps** — avoids duplicate LLM calls when Creative / Anchor / Poetry tasks resume.

### Bug Fixes

- Fixed an un-clickable "open edit window" button caused by checkpoint artifact field-name mismatch.
- Fixed multi-PID port-in-use hints so the kill command is emitted as a single copyable line.
- Progress control-flow fixes — pause UI cleared immediately after resume, and queued/running tasks now show real-time progress messages.
- Character reference image generation moved into the references stage for correct ordering.
- Manual-mode UI polish — visible disabled states, artifact filter compatibility, auto-collapse of earlier stages, and resume for inactive unfinished tasks.

---

**Learn more about Manual Mode:** [Manual Mode Guide](https://video.lichuanyang.top/guides/manual-mode) and the in-repo `docs/public/manual_mode_guide.md`.
