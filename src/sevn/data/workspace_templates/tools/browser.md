# browser — sevn-native CDP browser automation

Drive the operator's **host Chrome** over the Chrome DevTools Protocol. Pure sevn code
(no Playwright, no WebDriver); needs `uv sync --extra browser-cdp`.

The tool attaches to an already-running Chrome (`SEVN_CDP_URL` or the session registry)
or **spawns** a headed Chrome with a persistent profile when none is reachable. Logins
and cookies persist across runs via that profile. Operator Chrome is never force-closed.

## When to use
- You need to act inside a logged-in web app the operator already uses (read mail, post
  to a site, fill a multi-step form, click through a flow).
- `get_page_content` / `web_fetch` are not enough because the page needs JS, a session
  cookie, or interaction.

## Actions

| action | params | result |
|--------|--------|--------|
| `list_tabs` | — | open page tabs (`target_id`, `url`, `title`, `active`) |
| `open_tab` | `url` | new tab row |
| `close_tab` | `target_id` | `{closed}` |
| `activate_tab` | `target_id` | focus + persist active tab |
| `goto` | `url`, `tab?` | navigate active (or `tab`) and wait for load |
| `back` / `forward` / `reload` | `tab?` | history / reload |
| `page_state` | `tab?` | `url`, `title`, text excerpt |
| `extract_text` | `selector?`, `max_chars?` | visible text (capped, may spill) |
| `extract_html` | `selector?`, `max_chars?` | outer HTML (capped, may spill) |
| `wait_for` | `selector` | poll until the selector appears |
| `click` | `selector` **or** `text` | synthetic mouse click at the element centre |
| `fill` | (`selector`/`text`) + `value` | clear then type into a field |
| `type` | (`selector`/`text`) + `value` | type without clearing |
| `press_key` | (`selector`/`text`) + `key` | Enter / Tab / Backspace / Arrow… |
| `select_option` | `selector` + `value` | choose a `<select>` option |
| `scroll` | `pixels` | scroll (negative = up) |
| `screenshot` | `full_page?` | PNG under `screenshots/`; returns `path` for `send_file` |
| `dismiss_blockers` | — | best-effort accept/close cookie + consent banners |
| `get_cookies` / `set_cookies` | `cookies?` | read / write cookies (login portability) |
| `eval` | `expression` | **gated** — only when `tools.browser.allow_eval=true` |
| `telegram` | `op`, `chat?`, `value?`, `query?` | Telegram Web recipe — `op`: `login` (QR/code human-handoff) · `chats` · `read` · `send` · `reply` · `search` · `botfather` (read a bot token) |
| `google_search` | `query`, `mode?` | Google Search — `mode`: `results` (organic + People-Also-Ask) or `ask` (AI Overview, Gemini fallback) |
| `gmail` | `op`, `query?`, `message_id?`, `to?`, `subject?`, `body?` | Gmail — `op`: `list` · `read` · `search` · `compose` · `reply` (writes require `tools.browser.gmail.allow_write=true`) |
| `maps` | `op`, `query?`, `place?`, `origin?`, `destination?` | Google Maps — `op`: `search` · `place` · `directions` · `reviews` |
| `youtube` | `op`, `url?`, `query?`, `comment_hint?`, `body?` | YouTube — `op`: `search` · `info` · `comments` · `read_replies` · `comment` · `reply` (writes require `tools.browser.youtube.allow_write=true`) |
| `social` | `site`, `op`, `url?`, `query?`, `body?` | Social sites — `site`: `x` · `facebook` · `instagram` · `linkedin` · `reddit` · `tiktok`; `op`: `read` · `post` · `reply` · `read_replies` · `search` · `timeline_collect` · `home_feed`. On **X**, `read` / `timeline_collect` / `home_feed` return structured `{tweet_url, author_handle, text}[]` posts (status permalinks, not raw HTML). Writes require `tools.browser.social.<site>.allow_write=true` |

## Element targeting
Prefer a precise CSS `selector`. When you only know the label, pass `text` — the tool
finds the smallest visible element whose text/`aria-label` contains it. iframe-aware.

## Typical flow
1. `list_tabs` → see what's open. `goto` or `open_tab` to reach a page.
2. `dismiss_blockers` if a cookie banner is in the way.
3. `extract_text` / `page_state` to read; `click` / `fill` / `press_key` to act.
4. `screenshot` then the `send_file` tool to show the operator a result.

## Safety
- `eval` is off by default (`EVAL_DISABLED`); recipes do not need it.
- 2FA / QR / CAPTCHA are not bypassed — those flows pause for the operator.
- Writes to email/social are governed by per-recipe kill-switches (see recipe actions).
