---
name: facebook-use
description: Facebook workflows via a logged-in browser profile or CDP attach (feed read, search).
version: "1.0.0"
see_also:
  - x-use
  - playwright-browser
  - browser-harness
egress:
  - facebook.com
  - fb.com
  - fbcdn.net
  - fbsbx.com
  - facebook.net
  - messenger.com
scripts:
  - path: scripts/session_status.py
    description: Report logged-in browser profile path, CDP reachability, and egress allowlist.
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/feed.py
    description: Open the Facebook feed and return a visible-text snapshot from the logged-in session.
    args_overview: "[--max-chars N] [--dry-run]"
    abortable: true
  - path: scripts/search.py
    description: Search Facebook and return a visible-text snapshot from the logged-in session.
    args_overview: "--query TEXT [--max-chars N] [--dry-run]"
    abortable: true
---

# facebook-use

**Facebook** surface via a **logged-in browser** (same session model as **`x-use`**). v1 scripts cover **feed read** and **search**; posting and group navigation remain product TBD.

Normative spec: `plan/architecture/04b-skills.md` §19. Security posture: `plan/architecture/05-security-sandbox.md` §8b (session-bound egress).

## Operator setup

Same profile / CDP model as **`x-use`** — configure `skills.social_browser.profile_dir`, `skills.facebook_use.profile_dir`, or `SEVN_BROWSER_PROFILE_DIR`. Reuse one logged-in profile for both skills when appropriate.

**Browser lifecycle:** use **`playwright-browser` → `close_browser` / `restart_browser` / `session_status`** — not duplicated in this skill.

## ToS / automation

**Operator-beware:** Facebook ToS and automation compliance are the **operator's responsibility**. Document risks before enabling agent access to a logged-in session.

```bash
uv sync --extra browser
```

Use `--dry-run` or `SEVN_SOCIAL_BROWSER_DRY_RUN=1` for plan-only JSON output.
