---
name: x-use
description: X (Twitter) workflows via a logged-in browser profile or CDP attach (timeline, search).
version: "1.0.0"
see_also:
  - playwright-browser
  - browser-harness
  - get_page_content
egress:
  - x.com
  - twitter.com
  - twimg.com
  - abs.twimg.com
  - pbs.twimg.com
  - video.twimg.com
  - api.twitter.com
  - api.x.com
  - t.co
scripts:
  - path: scripts/session_status.py
    description: Report logged-in browser profile path, CDP reachability, and egress allowlist.
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/timeline.py
    description: Open the X home timeline and return a visible-text snapshot from the logged-in session.
    args_overview: "[--max-chars N] [--dry-run]"
    abortable: true
  - path: scripts/search.py
    description: Search X and return a visible-text snapshot from the logged-in session.
    args_overview: "--query TEXT [--max-chars N] [--dry-run]"
    abortable: true
---

# x-use

Workflows on **X (Twitter)** using a **real, logged-in browser profile** (persistent Chrome `user-data-dir` or CDP attach to operator Chrome). Covers **reading** the home timeline and **search** — not unauthenticated scrape-only tools.

Normative spec: `plan/architecture/04b-skills.md` §18. Security posture: `plan/architecture/05-security-sandbox.md` §8b (session-bound egress via manifest `egress:` + script URL validation).

## Operator setup

1. Log in to X in a dedicated Chrome profile **or** start Chrome with remote debugging (`--remote-debugging-port=9222`) while logged in.
2. Point sevn at the profile (first match wins):
   - `SEVN_BROWSER_PROFILE_DIR` (injected by the skill runner from workspace config)
   - `skills.social_browser.profile_dir` in `sevn.json`
   - `skills.x_use.profile_dir` in `sevn.json`
   - default: `<workspace>/.sevn/browser-profiles/default`
3. Optional: `SEVN_CDP_URL` (default `http://127.0.0.1:9222`) to attach instead of spawning Chrome.

## Session model

Shares the **logged-in browser profile / CDP attach** stack with **`facebook-use`**. The harness sets `SEVN_BROWSER_AUTOCLOSE=0` so multi-step runs reuse cookies. Outbound navigation is limited to the **`egress:`** hosts above (enforced in Python before Playwright navigation).

**Browser lifecycle:** close, restart, and full session status use **`playwright-browser`** scripts (`close_browser`, `restart_browser`, `session_status`) — this skill does not duplicate them. Call **`playwright-browser` → `session_status`** before assuming login state.

## ToS / automation

**Operator-beware:** X ToS, rate limits, and automation policy are the **operator's responsibility**. The product does not assert legal clearance per jurisdiction.

Install Playwright when running live scripts:

```bash
uv sync --extra browser
```

Use `--dry-run` or `SEVN_SOCIAL_BROWSER_DRY_RUN=1` to emit argv/plan JSON without launching a browser.
