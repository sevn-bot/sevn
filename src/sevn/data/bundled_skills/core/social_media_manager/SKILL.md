---
name: social_media_manager
description: Monitor and interact with social media via TwexAPI, sevn CDP browser, and assigned social skills (x-use, facebook-use, linkedin-use).
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
scripts:
  - path: scripts/_common.py
    description: Shared TwexAPI / specialist helpers for social_media_manager scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/capabilities.py
    description: List assigned skills/tools and available TwexAPI + browser media.
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/session_status.py
    description: Report TwexAPI key readiness and CDP browser reachability.
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/twexapi_search.py
    description: Advanced X/Twitter search via TwexAPI (https://docs.twexapi.io/).
    args_overview: "QUERY [--max-items N] [--dry-run]"
    abortable: true
  - path: scripts/twexapi_users.py
    description: Look up X/Twitter users by username via TwexAPI.
    args_overview: "USERNAMES [--dry-run]"
    abortable: true
  - path: scripts/twexapi_call.py
    description: Call an allowlisted TwexAPI op with optional JSON body/params.
    args_overview: "OP [--body JSON] [--params JSON] [--path-params JSON] [--dry-run]"
    abortable: true
---

# social_media_manager skill

Level-2 **`social_media_manager`** specialist (`subagents.specialists.social_media_manager`)
for monitoring and interacting with social media across two media:

1. **TwexAPI** — `https://docs.twexapi.io/` (Bearer token REST for X/Twitter search,
   users, timelines, replies, trends, …)
2. **Browser (sevn CDP automator)** — native `browser` tool (`action=social`) plus
   `playwright-browser` / `browser-harness` and logged-in social skills

## Assigned core skills

| Skill | Role |
|-------|------|
| `social_media_manager` | This specialist binding + TwexAPI scripts |
| `x-use` | Logged-in X (Twitter) timeline / search via CDP profile |
| `facebook-use` | Logged-in Facebook feed / search |
| `linkedin-use` | LinkedIn Voyager scrapes via logged-in browser |
| `playwright-browser` | CDP-first Playwright scripts |
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
  task='{"medium":"twexapi","op":"search","query":"sevn.bot"}'
)
```

Other mediums:

```
spawn_subagent(specialist="social_media_manager", wait=true, task="capabilities")
spawn_subagent(
  specialist="social_media_manager",
  wait=true,
  task='{"medium":"browser","op":"search","site":"x","query":"AI agents"}'
)
```

Browser medium returns a CDP `browser` tool plan (the parent turn should call
`browser` with `action=social`). TwexAPI medium executes the REST call inline.

## Configuration example (not shipped as default)

```json
"skills": {
  "social_media_manager": {
    "twexapi": {
      "api_key": "${SECRET:SEVN_SECRET_TWEXAPI}",
      "base_url": "https://api.twexapi.io"
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

When triage selects the `social_media_manager` skill, the gateway auto-grants this
specialist for the tier-B dispatch (W8.3 skill→specialist binding).

## Errors

When the specialist is missing, spawn/scripts return:
`configure subagents.specialists.social_media_manager`.
