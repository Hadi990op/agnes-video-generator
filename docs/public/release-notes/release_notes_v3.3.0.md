# Release v3.3.0 — Bilingual Screenwriter Prompts + Prompt-Language Auto-Follow

> Release date: 2026-06-24

## Overview

v3.3.0 is a **minor version** that makes the AI screenwriter fully **bilingual (中文/English)**: all 14 meta-prompts can switch language and auto-follow the input language, with film-specific vocabulary guidance to reduce content-review rejections. It also fixes a Firefox layout bug in the language selector.

## Usage

From v3.2.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

## What's New

### Features & Improvements

- **Bilingual screenwriter** — all 14 screenwriter meta-prompts support Chinese/English switching.
- **Prompt-language auto-follow** — generated prompts and LLM instructions follow the language of the input content automatically.
- **Film-equivalent vocabulary guidance** — screenwriting prompts now include cinematic wording guidance to reduce content-review rejections.

### Bug Fixes

- Language selector overlapping the H1 heading on Firefox (fixes #11).
- Hard-coded prompt language in 5 files now follows the UI/input language.
- Character appearance prompt hardening and `get_character_appearance` completion.
