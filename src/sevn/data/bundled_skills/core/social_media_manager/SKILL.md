---
name: social_media_manager
description: Browser-first social monitoring across six platforms via CDP browser; TwexAPI optional on X only.
version: "1.0.0"
specialist: social_media_manager
requires_specialist: social_media_manager
see_also:
  - spawn_subagent
  - browser
  - playwright-browser
  - browser-harness
  - x-use
  - facebook-use
  - linkedin-use
  - last30days
  - yt-dlp
  - media_generation
  - scheduling
egress:
  - api.twexapi.io
  - docs.twexapi.io
  - twexapi.io
  - x.com
  - twitter.com
  - facebook.com
  - linkedin.com
  - instagram.com
  - reddit.com
  - tiktok.com
scripts:
  - path: scripts/_common.py
    description: Shared TwexAPI / specialist helpers for social_media_manager scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/capabilities.py
    description: Per-platform medium matrix — assigned skills/tools, allowed media, effective medium, readiness.
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/session_status.py
    description: Report TwexAPI key readiness, CDP/profile path, and optional per-site login probe.
    args_overview: "[--site SITE] [--dry-run]"
    abortable: true
  - path: scripts/x_ops.py
    description: Unified X ops facade — every §4 op over browser|twexapi with normalized {ok,medium,op,data} envelope.
    args_overview: "OP [--task JSON] [--medium browser|twexapi] [--site x] [--dry-run]"
    abortable: true
  - path: scripts/x_timeline.py
    description: Convenience wrapper for home_timeline_collect / search facade ops.
    args_overview: "[OP] [--task JSON] [--medium browser|twexapi] [--dry-run]"
    abortable: true
  - path: scripts/x_tweet_actions.py
    description: Tweet-action facade ops (like, retweet, create, bookmark, …) with write gates.
    args_overview: "OP [--tweet-id ID] [--text TEXT] [--medium browser|twexapi] [--dry-run]"
    abortable: true
  - path: scripts/twexapi_search.py
    description: Advanced X/Twitter search via TwexAPI (https://docs.twexapi.io/) — X only.
    args_overview: "QUERY [--max-items N] [--dry-run]"
    abortable: true
  - path: scripts/twexapi_users.py
    description: Look up X/Twitter users by username via TwexAPI — X only.
    args_overview: "USERNAMES [--dry-run]"
    abortable: true
  - path: scripts/twexapi_call.py
    description: Call an allowlisted TwexAPI op with optional JSON body/params — X only.
    args_overview: "OP [--body JSON] [--params JSON] [--path-params JSON] [--dry-run]"
    abortable: true
---

# social_media_manager skill

Level-2 **`social_media_manager`** specialist (`subagents.specialists.social_media_manager`)
for monitoring and interacting with social media across **six platforms**. **Browser (CDP)
is the universal default medium**; TwexAPI is optional on **X only**.

## Platform matrix

| Platform | Site key | Allowed media | Primary browser path | Dedicated skill |
|----------|----------|---------------|----------------------|-----------------|
| **X** | `x` | `browser`, `twexapi` | `browser` `action=social` `site=x` | `x-use` |
| **Facebook** | `facebook` | `browser` | `browser` `action=social` `site=facebook` | `facebook-use` |
| **LinkedIn** | `linkedin` | `browser` | `browser` `action=social` `site=linkedin` | `linkedin-use` |
| **Instagram** | `instagram` | `browser` | `browser` `action=social` `site=instagram` | `playwright-browser`, `browser-harness` |
| **Reddit** | `reddit` | `browser` | `browser` `action=social` `site=reddit` | `playwright-browser`, `browser-harness`, `last30days` |
| **TikTok** | `tiktok` | `browser` | `browser` `action=social` `site=tiktok` | `playwright-browser`, `browser-harness`, `yt-dlp` |

Instagram, Reddit, and TikTok have **no REST/API medium** in this specialist — use
browser medium only. TwexAPI scripts and `medium=twexapi` apply to **X** only; non-X
sites coerce to browser at runtime.

## Medium resolution

When a task omits `medium`, resolution order is:

1. **Task JSON `medium`** (explicit override)
2. **`skills.social_media_manager.platforms.<site>.medium`**
3. **`skills.social_media_manager.default_medium`**
4. **`browser`** (final fallback)

Omitted `medium` in spawn tasks therefore defaults to **browser** (or the configured
platform/default chain above).

## Operator config (Telegram menu)

**`/config → Skills → Social Media Manager`**

- **Default medium** cycle — global fallback (`browser` or `twexapi`)
- **Per-site medium** cycles — one row per platform; TwexAPI appears in the X cycle only
- **TwexAPI enabled** toggle — `skills.social_media_manager.twexapi.enabled` (default off)
- **Set TwexAPI key** — secrets wizard → `SEVN_SECRET_TWEXAPI`
- **Readiness** — key configured (yes/no), CDP URL or profile dir, per-site login hints

All medium settings live under **`skills.social_media_manager`**, not on
`subagents.specialists.social_media_manager` fields.

## Assigned core skills

Declared specialist toolkit (returned by `medium=capabilities`; parent/tier-B
turns may `load_skill` these). The L2 worker executes **TwexAPI** inline on X when
resolved medium is `twexapi`; **browser** medium returns a CDP `browser` tool plan
for the parent turn.

| Skill | Role |
|-------|------|
| `social_media_manager` | This specialist binding + TwexAPI scripts |
| `x-use` | Logged-in X (Twitter) timeline / search via CDP profile |
| `facebook-use` | Logged-in Facebook feed / search |
| `linkedin-use` | LinkedIn Voyager scrapes via logged-in browser |
| `playwright-browser` | CDP-first Playwright scripts (IG/Reddit/TikTok and generic social) |
| `browser-harness` | Thin extendable CDP harness |
| `last30days` | Multi-source social research (Reddit, X, YouTube, …) |
| `yt-dlp` | Download video/audio from allowlisted social hosts |
| `media_generation` | Generate images/video/music for posts (MiniMax specialist) |
| `scheduling` | Cron / reminders for monitoring cadences |

## Assigned core tools

| Tool | Role |
|------|------|
| `browser` | **sevn native CDP automator** (social / linkedin / tabs / extract) |
| `get_page_content` | Fetch page → markdown |
| `web_fetch` / `web_search` / `serp` | Live web research |
| `load_skill` / `run_skill_script` | Load and run the skills above |
| `send_file` / `message` | Deliver artifacts / updates on the active channel |

## Preferred tier-B path (spawn + wait)

```
spawn_subagent(
  specialist="social_media_manager",
  wait=true,
  task='{"op":"search","site":"x","query":"sevn.bot"}'
)
```

Per-platform matrix and readiness:

```
spawn_subagent(specialist="social_media_manager", wait=true, task="capabilities")
run_skill_script social_media_manager capabilities.py
```

Explicit TwexAPI on X:

```
spawn_subagent(
  specialist="social_media_manager",
  wait=true,
  task='{"medium":"twexapi","op":"search","site":"x","query":"sevn.bot"}'
)
```

Browser medium (Instagram example):

```
spawn_subagent(
  specialist="social_media_manager",
  wait=true,
  task='{"medium":"browser","op":"search","site":"instagram","query":"sevn.bot"}'
)
```

Browser medium returns a CDP `browser` tool plan (the parent turn should call
`browser` with `action=social`). TwexAPI medium executes the REST call inline on X.

## Configuration example (not shipped as default)

Specialists default to **empty** — operator must opt in explicitly:

```json
"skills": {
  "social_media_manager": {
    "default_medium": "browser",
    "twexapi": {
      "enabled": false,
      "api_key": "${SECRET:SEVN_SECRET_TWEXAPI}",
      "base_url": "https://api.twexapi.io"
    },
    "platforms": {
      "x": { "medium": "browser" },
      "facebook": { "medium": "browser" }
    }
  }
},
"subagents": {
  "specialists": {
    "social_media_manager": {
      "model": "gpt-4o-mini",
      "provider": "openai",
      "assigned_to": ["tier_b"],
      "requestable_by": ["triager", "tier_b"],
      "max_concurrent": 2,
      "skill": "social_media_manager",
      "skills": [
        "social_media_manager", "x-use", "facebook-use", "linkedin-use",
        "playwright-browser", "browser-harness", "last30days", "yt-dlp",
        "media_generation", "scheduling"
      ],
      "tools": [
        "browser", "get_page_content", "web_fetch", "web_search", "serp",
        "load_skill", "run_skill_script", "send_file", "message"
      ]
    }
  }
}
```

Store the TwexAPI key as `SEVN_SECRET_TWEXAPI` or set `TWEXAPI_API_KEY`. Docs:
https://docs.twexapi.io/

## Browser session SSOT (D10 — wire existing auth)

Browser medium uses the **same profile/CDP paths** as other browser skills — no
separate social-media auth stack.

| Source | Precedence | Purpose |
|--------|------------|---------|
| `SEVN_CDP_URL` | Highest | Attach to an existing Chrome/Brave CDP endpoint |
| `SEVN_BROWSER_PROFILE_DIR` | Env override | Persistent Chrome profile directory |
| `skills.browser.profile_dir` | Config | Workspace profile path |
| `skills.social_browser.profile_dir` | Config | Social-browser profile path |
| `<workspace>/.sevn/browser-profiles/<session_id>` | Default | Session-scoped profile |

Run `scripts/session_status.py` (or `run_skill_script social_media_manager
session_status.py`) for TwexAPI key **yes/no**, CDP URL or profile dir, and optional
`--site` login hints. Output never includes secret values.

**Login tool:** use native `browser` with `action=login` and `credentials_ref`
pointing at a workspace secrets alias (never inline passwords). See
`sevn.browser.auth`.

**Cookie export/import:** seed-only portability via `browser` `action=export_cookies`
/ `action=import_cookies` — not a required persistence layer for this specialist.
Map exported cookies into TwexAPI write bodies with
`sevn.integrations.social_media.x_ops.cookies_for_twexapi` (never log cookie values).
`post_tweet_auto_cookie` uses TwexAPI's **pool** cookie on `medium=twexapi`; on
`medium=browser` it coerces to `create_tweet_or_reply` using the CDP profile session.

## Unified X ops facade (`x_ops`)

Every X/Twitter endpoint is a function on `sevn.integrations.social_media.x_ops`
and callable via `run_skill_script social_media_manager x_ops.py <OP>`. Each call
resolves medium (`task → platforms.x → default_medium → browser`), dispatches to
TwexAPI or a CDP `browser` plan, and returns:

```json
{"ok": true, "medium": "browser", "op": "home_timeline_collect", "data": {}}
```

On failure: `ok=false` plus `error` and/or `code` (never a raw exception). Write
ops require `tools.browser.social.x.allow_write=true` (browser) or TwexAPI
enabled + cookie (twexapi).

| Op | Medium notes | Key args |
|----|--------------|----------|
| `advanced_search_page` | both | `query` / `searchTerms`, `sortBy`, `next_cursor` |
| `search_hashtags` | both | `hashtags` / `query` |
| `like_tweet` / `unlike_tweet` | both (write) | `tweet_id` |
| `retweet` / `delete_retweet` | both (write) | `tweet_id` |
| `bookmark` / `delete_bookmark` | both (write) | `tweet_id` |
| `create_tweet_or_reply` | both (write) | `text` / `tweet_content`, `reply_tweet_id?` |
| `create_quote_tweet` | both (write) | `text`, quote target |
| `create_tweet_thread` | both (write) | `items` list |
| `delete_tweets` | both (write) | tweet id(s) / username |
| `post_tweet_auto_cookie` | twexapi pool cookie; browser coerces to create | `text` |
| `get_users_by_usernames` | both | `usernames` |
| `follow_user` | both (write) | `username` |
| `fetch_article_markdown` | both | `tweet_id` |
| `home_timeline_collect` | browser `home_feed`; twexapi `timeline_page` substitute | `screen_name?` |
| `session_status` | both | CDP reachability, profile, login probe, `twexapi_key_present` (boolean) |

```
run_skill_script social_media_manager x_ops.py home_timeline_collect --medium browser
run_skill_script social_media_manager x_tweet_actions.py like_tweet --tweet-id 1 --medium twexapi
```

When triage selects the `social_media_manager` skill, the gateway auto-grants this
specialist for the tier-B dispatch (W8.3 skill→specialist binding).

## Errors

When the specialist is missing, spawn/scripts return:
`configure subagents.specialists.social_media_manager`.
