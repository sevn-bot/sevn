---
name: linkedin-use
description: LinkedIn staff/company/connection scraping via logged-in browser + Voyager API (StaffSpy port).
version: "1.0.0"
see_also:
  - x-use
  - facebook-use
  - browser
  - playwright-browser
egress:
  - linkedin.com
  - licdn.com
scripts:
  - path: scripts/_cli.py
    description: Internal shared helpers for linkedin-use script wrappers (not invoked directly).
    abortable: true
  - path: scripts/session_status.py
    description: Report logged-in browser profile, CDP reachability, LinkedIn login-state, and egress allowlist.
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/scrape_staff.py
    description: Scrape LinkedIn staff for a company (optional search term, location, profile enrichment).
    args_overview: "--company NAME [--search-term T] [--location L] [--max-results N] [--extra-profile-data] [--dry-run]"
    abortable: true
  - path: scripts/scrape_users.py
    description: Scrape LinkedIn profiles by public profile id slug(s).
    args_overview: "--user-ids a,b,c [--extra-profile-data] [--dry-run]"
    abortable: true
  - path: scripts/scrape_companies.py
    description: Scrape LinkedIn company metadata by name(s).
    args_overview: "--company-names a,b [--dry-run]"
    abortable: true
  - path: scripts/scrape_connections.py
    description: Scrape the logged-in account's LinkedIn connections.
    args_overview: "[--max-results N] [--extra-profile-data] [--dry-run]"
    abortable: true
---

# linkedin-use

LinkedIn **staff / company / connection** scraping using a **logged-in Chrome profile** (or CDP attach) and authenticated Voyager API calls via sevn's **own CDP browser engine**. Ported from [StaffSpy](https://github.com/cullenwatson/StaffSpy) (MIT) — no Selenium, no 2Captcha, no pandas.

## Operator setup

1. Log in to LinkedIn in a dedicated Chrome profile **or** attach to operator Chrome with remote debugging (`--remote-debugging-port=9222`).
2. Point sevn at the profile (first match wins):
   - `SEVN_BROWSER_PROFILE_DIR` (injected by the skill runner)
   - `skills.social_browser.profile_dir` in `sevn.json`
   - `skills.linkedin_use.profile_dir` in `sevn.json`
   - default: `<workspace>/.sevn/browser-profiles/default`
3. Install the CDP engine extra:

```bash
uv sync --extra browser-cdp
```

Optional: `SEVN_CDP_URL` (default `http://127.0.0.1:9222`) to attach instead of spawning Chrome.

**Browser lifecycle:** close, restart, and full session status use **`playwright-browser`** scripts — this skill exposes LinkedIn-specific `session_status` only.

## Write actions

`block` / `connect` are **not** exposed in v1 skill scripts. Enable via the `browser` tool recipe with `tools.browser.linkedin.allow_write=true` (default off).

## ToS / automation

**Operator-beware:** LinkedIn ToS, rate limits, and automation policy are the **operator's responsibility**.

Use `--dry-run` or `SEVN_LINKEDIN_USE_DRY_RUN=1` for plan-only JSON output.
