---
name: playwright-browser
description: Web automation with CDP-first Playwright scripts (navigate, screenshot, click, extract text).
version: "0.2.1"
see_also:
  - browser-harness
  - get_page_content
  - web_fetch
egress:
  - "*"
tools:
  - send_file
scripts:
  - path: scripts/session_status.py
    description: Report session-scoped profile, CDP, registry pid, and active tab URL (best-effort).
    args_overview: ""
    abortable: true
  - path: scripts/close_browser.py
    description: Close the sevn-managed session browser; use --force only for external CDP (dangerous).
    args_overview: "[--force]"
    abortable: false
  - path: scripts/restart_browser.py
    description: Close and respawn the session browser; cookies persist in the profile directory.
    args_overview: "[--force]"
    abortable: false
  - path: scripts/list_tabs.py
    description: List open tabs with target_id, url, title, and active flag.
    args_overview: ""
    abortable: true
  - path: scripts/find_tab.py
    description: Find open tabs by URL or title substring; optionally activate a unique match.
    args_overview: "[--url SUBSTR] [--title SUBSTR] [--activate]"
    abortable: true
  - path: scripts/new_tab.py
    description: Open a URL in a new tab and activate it (updates registry active tab).
    args_overview: "<url>"
    abortable: true
  - path: scripts/close_tab.py
    description: Close one tab by target_id; refuses to close the last tab.
    args_overview: "<target_id>"
    abortable: false
  - path: scripts/activate_tab.py
    description: Focus a tab by target_id and set it as the registry active tab.
    args_overview: "<target_id>"
    abortable: true
  - path: scripts/cdp_probe.py
    description: Check whether the CDP HTTP endpoint responds (stdlib probe, no Playwright).
    args_overview: "[cdp_url]"
    abortable: true
  - path: scripts/goto.py
    description: Navigate the active browser page to a URL and wait for load/network idle.
    args_overview: "[--tab <target_id>] [--human] <url>"
    abortable: true
  - path: scripts/capture.py
    description: Navigate to a URL and save a screenshot in one process.
    args_overview: "<url> [path] [--full-page]"
    abortable: true
  - path: scripts/screenshot.py
    description: Screenshot the current page under the workspace (for send_file).
    args_overview: "[--tab <target_id>] [path] [--full-page]"
    abortable: true
  - path: scripts/page_state.py
    description: JSON snapshot of url, title, text excerpt, and obstacle flags.
    args_overview: "[--tab <target_id>]"
    abortable: true
  - path: scripts/extract_page_text.py
    description: Extract main visible text (GitHub README/code-aware presets).
    args_overview: "[--preset auto|github|generic] [--max-chars N]"
    abortable: true
  - path: scripts/github_blob_to_raw.py
    description: Convert a GitHub blob URL to raw.githubusercontent.com (no browser).
    args_overview: "<github_blob_url>"
    abortable: true
  - path: scripts/get_html.py
    description: Return full page or element HTML (capped).
    args_overview: "[--tab <target_id>] [--selector S] [--max-chars N]"
    abortable: true
  - path: scripts/list_controls.py
    description: List links, buttons, and inputs with importance scores and selector hints.
    args_overview: "[--tab] [--visible-only] [--forms-only]"
    abortable: true
  - path: scripts/find_control.py
    description: Find a visible control by label, placeholder, role, name, or text; return selector hint.
    args_overview: "[--tab] (--label|--placeholder|--role|--name|--text TEXT)+"
    abortable: true
  - path: scripts/dismiss_cookies.py
    description: Heuristic cookie/consent banner dismissal clicks.
    args_overview: "[--tab]"
    abortable: true
  - path: scripts/handle_blockers.py
    description: Dismiss cookies and attempt reCAPTCHA checkbox; return obstacle JSON.
    args_overview: "[--skip-cookies] [--skip-recaptcha]"
    abortable: true
  - path: scripts/click_element.py
    description: Click an element by CSS selector (scroll into view; optional human pacing).
    args_overview: "[--tab] [--human] <css_selector>"
    abortable: false
  - path: scripts/fill.py
    description: Fill an input or textarea (optional human typing and Enter).
    args_overview: "[--tab] [--human] <selector> <text> [press_enter]"
    abortable: false
  - path: scripts/type_text.py
    description: Type text via keyboard after focusing an element (human random delay with --human).
    args_overview: "[--tab] [--human] <selector> <text> [delay_ms]"
    abortable: false
  - path: scripts/press.py
    description: Press keyboard keys (optionally after focusing a selector).
    args_overview: "[--selector S] <key> [key...]"
    abortable: false
  - path: scripts/hover.py
    description: Hover an element by CSS selector.
    args_overview: "<css_selector>"
    abortable: true
  - path: scripts/scroll.py
    description: Scroll the page window or an element (optional human pause).
    args_overview: "[--tab] [--human] page <dy|bottom> or <selector> <dy>"
    abortable: true
  - path: scripts/scroll_into_view.py
    description: Scroll a CSS selector into the viewport before clicking or filling.
    args_overview: "[--tab] [--human] <css_selector>"
    abortable: true
  - path: scripts/select_option.py
    description: Select an option on a HTML select element.
    args_overview: "[--tab] [--human] <selector> <value> [--by value|label|index]"
    abortable: false
  - path: scripts/wait_for_selector.py
    description: Wait for an element selector to reach a state.
    args_overview: "<selector> [--state ...] [--timeout ms]"
    abortable: true
  - path: scripts/get_text.py
    description: Read inner text or an attribute from an element.
    args_overview: "[--tab <target_id>] <selector> [--attr name]"
    abortable: true
  - path: scripts/evaluate.py
    description: Evaluate a JavaScript expression in the page context.
    args_overview: "[--tab <target_id>] <js_expression>"
    abortable: false
---

# playwright-browser skill

Session-scoped Playwright automation with **CDP-first** routing:

1. Attach to the conversation's **session CDP URL** (from registry or `SEVN_CDP_URL`) when reachable.
2. Spawn system Chrome with remote debugging and a **persistent profile** under
   `<content_root>/.sevn/browser-profiles/<session_id>/`.
3. Fall back to Playwright bundled headless Chromium when no system Chrome exists.

The gateway sets **`SEVN_BROWSER_AUTOCLOSE=0`** for this skill when unset so multi-step
`goto` → `screenshot` flows share one browser across conversation turns.

## Session lifecycle

The browser **persists across turns** for the same gateway conversation. Profile, cookies,
and tabs survive between skill script calls until you explicitly close, restart, or the
operator rotates the session (`/new`).

| Script | When to use |
|--------|-------------|
| `scripts/session_status.py` | Before assuming login state or CDP availability |
| `scripts/close_browser.py` | When finished browsing or the operator asks to close Chrome |
| `scripts/restart_browser.py` | When the browser is stuck, hung, or needs a clean respawn |

Cookies and local storage remain in the session profile directory across restart.
`close_browser` refuses to kill operator-attached external CDP unless `--force` (dangerous).

## CDP probe expectations

`scripts/cdp_probe.py` and `scripts/session_status.py` check whether the CDP HTTP
endpoint responds. **Before the first `capture.py` or `goto.py` run**, nothing listens on
the default port (`127.0.0.1:9222`) — the envelope returns `CDP_UNREACHABLE`. That is
**normal**, not a broken skill. Run `capture.py <url>` or `goto.py <url>` to spawn Chrome;
only then do probe scripts report a reachable CDP endpoint.

## Working with tabs

One persistent browser context per conversation holds **N tabs** (pages). The registry
tracks `active_target_id` — the tab interaction scripts target by default.

| Script | When to use |
|--------|-------------|
| `scripts/find_tab.py` | **Reuse** an existing tab by URL/title before opening a duplicate |
| `scripts/list_tabs.py` | Enumerate all tabs (optional; use when managing several pages) |
| `scripts/new_tab.py <url>` | Open a link in a new tab (activates it) |
| `scripts/activate_tab.py <target_id>` | Switch focus to an existing tab |
| `scripts/close_tab.py <target_id>` | Close a finished tab (refuses the last tab) |

**Smart tab habits (generic):**

1. Before `new_tab`, run `find_tab.py --url <domain> --activate` — reuse when `count=1`.
2. Simple single-page tasks: `goto.py` or `capture.py` on the active tab (no tab CRUD needed).
3. When done with a side task, `close_tab.py` the extra tab; keep one tab open until `close_browser`.

Interaction scripts accept optional `--tab <target_id>`. Omit `--tab` to use the registry
active tab or the best current work page when `active_target_id` is null.

## Human-like pacing

Use **`--human`** on interaction scripts for random pauses and typing delays (generic, not
site-specific):

| Script | `--human` behavior |
|--------|-------------------|
| `goto.py` | Pause after navigation settles |
| `fill.py` | Scroll into view, pause, type with random keystroke delay |
| `click_element.py` | Scroll into view, pause, click, short post-click pause |
| `type_text.py` | Random per-key delay (or fixed `delay_ms` without `--human`) |
| `select_option.py` | Scroll into view + pre-select pause |
| `scroll.py` / `scroll_into_view.py` | Pause before/after scroll |

**Default for form workflows:** pass `--human` on every `fill`, `click_element`, and
`select_option` call unless speed is critical.

## Cookies and blockers

| Script | When to use |
|--------|-------------|
| `scripts/handle_blockers.py` | After navigation when overlays, cookies, or CAPTCHA may block the page |
| `scripts/dismiss_cookies.py` | Cookie/consent only (lighter than handle_blockers) |
| `scripts/page_state.py` | Check `obstacle` flags before continuing |

`goto.py` and `wait_for_page_ready` auto-attempt cookie dismissal once after load.
Re-run `handle_blockers.py` when a form remains covered.

## Discovering form controls

| Script | When to use |
|--------|-------------|
| `scripts/list_controls.py --visible-only --forms-only` | Ranked list of inputs/buttons with `importance` and `suggest` selectors |
| `scripts/find_control.py --label "…"` | Resolve one field by label, placeholder, role, name, or button text |

**Generic form loop:**

1. `list_controls.py --visible-only --forms-only` — pick high-`importance` required fields first.
2. Or `find_control.py --label "Email"` / `--placeholder "Search"` when you know the label.
3. `scroll_into_view.py <selector>` when the field may be off-screen.
4. `fill.py --human <selector> <value>` or `select_option.py --human` for dropdowns.
5. `wait_for_selector.py` when fields appear after AJAX.
6. `click_element.py --human <selector>` for submit / next buttons.

If instant `fill` fails (some sites reject programmatic input), retry with
`type_text.py --human`.

## Login and authenticated sessions

This skill does **not** store operator credentials. Login is **profile-based**:

1. Headed Chrome (`skills.browser.headless: false`) lets the operator sign in manually once.
2. Cookies persist in the session profile across turns and `restart_browser.py`.
3. Use `session_status.py` + `page_state.py` to see current URL/title and bot-wall flags.
4. When a page shows a login form, tell the operator to sign in in the visible browser window,
   then continue with `page_state.py` to confirm navigation past the login page.

Do not embed passwords or one-time codes in `argv`.

## Scrolling

| Script | When to use |
|--------|-------------|
| `scripts/scroll_into_view.py` | Bring one element into view before click/fill |
| `scripts/scroll.py page bottom` | Reach footer / lazy-loaded sections |
| `scripts/scroll.py page 400` | Incremental viewport scroll (`--human` optional) |
| `scripts/scroll.py "<selector>" 200` | Scroll inside a nested panel |

## Requirements

```bash
uv sync --extra browser
playwright install chromium
```

Headed cross-turn sessions are intended on the **macOS host** (`skills.browser.headless: false` default when Chrome exists). For Telegram operator UX smoke after gateway changes, use host-only **`sevn telegram-test`** (see [`.cursor/skills/telegram_test/SKILL.md`](../../../../../../.cursor/skills/telegram_test/SKILL.md)) — not `docker compose exec sevn-gateway`.

## Recommended loop

1. `session_status.py` when CDP or login state is uncertain; `restart_browser.py` if no registry row.
2. `capture.py <url>` or `goto.py --human <url>` — always pass the URL in `argv`.
3. `handle_blockers.py` when overlays may block the form.
4. `list_controls.py --visible-only --forms-only` or `find_control.py` to locate fields.
5. `fill.py --human`, `select_option.py --human`, `click_element.py --human` between fields.
6. `scroll.py` / `scroll_into_view.py` when content is below the fold.
7. `screenshot.py` + native **`send_file`** for proof / quotes.
8. `find_tab.py` / `close_tab.py` when managing multiple pages; `close_browser.py` when done.

## Live facts (scores, news, schedules)

For **current** scores, schedules, headlines, weather, or prices:

| Step | Action |
|------|--------|
| 1 | Prefer native **`get_page_content`** for static read-only pages (lighter than browser). |
| 2 | For JS-heavy sites: `goto.py [--human] <canonical_url>` — **URL required in `argv`**. |
| 3 | Read page: `extract_page_text.py` or `page_state.py` (not `evaluate.py` unless needed). |
| 4 | Use the **current calendar year** in URLs and queries (e.g. `https://www.nba.com/playoffs/2026`). |
| 5 | **`serp`** is for URL discovery only — do not answer live scores from snippets alone. |

Worked example (NBA playoffs score):

```
run_skill_script scripts/goto.py argv=["https://www.nba.com/playoffs/2026"]
run_skill_script scripts/extract_page_text.py argv=["--preset","generic","--max-chars","6000"]
```

Always pass the full `https://` URL in `argv` for `goto.py`, `new_tab.py`, and `capture.py`.

## Egress

Skill frontmatter declares broad **`egress: ["*"]`** because navigation targets are
operator-driven. HTTP from the browser still flows through workspace proxy / sandbox
posture per `specs/08-sandbox.md` and `PermissionConfig.egress_domains`.
