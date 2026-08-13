# Release v5.7.4 — Fix Blank Page After Frontend Bundle Merge

> Release date: 2026-08-13

## Overview

v5.7.4 is a **patch release** that fixes a blank page caused by a corrupted frontend JavaScript bundle introduced during the v5.7.3 branch merge. Git mistakenly treated two independent build artifacts as a rename and wrote conflict markers into the minified JS, so the Vue app could not mount. The bundle is restored to the correct build output.

## Usage

From v5.7.3:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

If you already ran v5.7.3, just `git pull` and restart the service. No data migration required.

> **If the page still shows blank after upgrading:** hard-refresh the browser (Cmd+Shift+R / Ctrl+Shift+R) to clear the cached `index.html`, which may reference an older asset filename.

## What's New

### Bug Fixes

- **Blank page after v5.7.3 upgrade fixed** — during the merge of the analytics changes into `master`, git auto-merge treated the new minified JS bundle as a rename of the old one and injected `<<<<<<<<` / `>>>>>>>>` conflict markers into the shipped bundle. Browsers failed to parse the file with `SyntaxError: Unexpected end of input`, leaving a white screen. The production bundle is now restored byte-for-byte from the original build output, and the page renders normally.

---

