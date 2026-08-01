---
name: reddit-karma-loop
description: >-
  Draft-only Reddit karma loop — browser discovery (site=reddit), quality gate,
  wiki/second-brain-grounded comment drafts, rate limits, and structured logging.
  No auto_post (D11); operator confirms before any live post.
version: "1.0.0"
see_also:
  - social_media_manager
  - last30days
  - scheduling
  - browser
egress:
  - reddit.com
  - old.reddit.com
scripts:
  - path: scripts/_reddit_runtime.py
    description: Draft-only runtime helpers (confirm gate, caps, cooldowns).
    args_overview: "(library module — not invoked directly)"
  - path: scripts/_common.py
    description: Shared dry-run and template helpers.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/discover.py
    description: Emit browser discovery plan for Reddit (no new API — D10).
    args_overview: "[--subreddit SUB] [--query Q] [--dry-run]"
    abortable: true
  - path: scripts/quality_gate.py
    description: Evaluate one candidate JSON object through the quality gate.
    args_overview: "--candidate-json JSON"
    abortable: true
  - path: scripts/run_loop.py
    description: Discover → gate → draft loop with JSONL decision logging.
    args_overview: "[--candidates-json ARRAY] [--dry-run]"
    abortable: true
  - path: scripts/post_comment.py
    description: Draft-only post path — CONFIRM_REQUIRED without --confirm (D11).
    args_overview: "--subreddit SUB --url URL --body TEXT [--confirm] [--dry-run]"
    abortable: true
  - path: scripts/ensure_cron.py
    description: Reconcile ``reddit-karma-loop`` row in ``trigger_cron_jobs``.
    args_overview: "(no args)"
    abortable: true
---

# reddit-karma-loop skill

Built for [#74](https://github.com/sevn-bot/sevn/issues/74). **D11 draft-only:** discovers
threads, gates candidates, and drafts grounded comments — it never auto-posts.

## Modes (D11)

| Mode | Status |
| --- | --- |
| `draft_only` | **Only enabled mode** — default for all scripts |
| `auto_post` | **Not implemented** — intentionally absent |
| `ask_before_post` | Scaffolded in config, default **off**; `--confirm` / `CONFIRM_REQUIRED` is the write gate |

## Discovery (D10)

Use the existing browser path — same as `social_media_manager` for Reddit:

```text
browser action=social site=reddit op=search|read|reply
```

`scripts/discover.py` returns the browser plan envelope for the parent turn. No new Reddit API
or paid dependency is introduced.

## Quality gate (W33.4)

`scripts/quality_gate.py` / `run_loop.py` enforce:

- recency (default ≤ 72h)
- topic relevance
- configured subreddit allow-list
- no duplicate sevn comment on thread
- promotional-risk ceiling
- source-backed expertise (wiki / second-brain)

## Grounding (W33.5)

Drafts reference approved operator content via existing tools:

- `wiki_search` / `wiki_read`
- `second_brain_query`

Pass grounding snippets in candidate JSON (`grounding_snippet`) or let the agent gather them
before calling `run_loop.py`.

## Draft-only posting (W33.6)

`scripts/post_comment.py` mirrors the Discogs confirmation envelope:

- without `--confirm` → `CONFIRM_REQUIRED` + `would_do` preview
- `--dry-run` / `SEVN_REDDIT_KARMA_DRY_RUN=1` → plan only
- with `--confirm` → records the action and returns a browser reply plan (still operator-driven)

## Logging (W33.7)

Every candidate, skip reason, draft, action, URL, and outcome appends to:

```text
<workspace>/.sevn/reddit-karma-loop/decisions.jsonl
```

## Safeguards (W33.8)

- `max_comments_per_day` and `cooldown_seconds` (config + runtime enforcement)
- `allow_links: false` strips URLs from drafts unless explicitly enabled
- `stop_on_mod_action: true` — halt loop when mod removal/feedback is recorded in the log

## Scheduling (W33.9)

Register the cron row with `scripts/ensure_cron.py` or gateway boot reconcile
(`reddit-karma-loop` job id). Uses the shared `trigger_cron_jobs` store — not a bespoke loop.

Default schedule: `0 9,15 * * *` UTC (twice daily). Override with `skills.reddit_karma_loop.cron_expr`.

## Configuration (default off)

```json
{
  "skills": {
    "reddit_karma_loop": {
      "enabled": false,
      "subreddits": ["python", "selfhosted"],
      "topics": ["ai assistant", "home lab"],
      "source_paths": ["wiki", "second_brain"],
      "cron_expr": "0 9,15 * * *",
      "max_comments_per_day": 5,
      "cooldown_seconds": 3600,
      "allow_links": false,
      "ask_before_post": false,
      "stop_on_mod_action": true
    }
  }
}
```

## Setup & credentials

1. Enable browser medium for Reddit (`social_media_manager` / `tools.browser.social.reddit`).
2. Log into Reddit in the configured Chrome profile (headed browser session).
3. Set `tools.browser.social.reddit.allow_write=true` **only** when the operator intends to post.
4. Enable this skill (`skills.reddit_karma_loop.enabled=true`) and run `ensure_cron.py`.
5. Review drafts in `.sevn/reddit-karma-loop/decisions.jsonl` before `--confirm` posts.

## Reddit policy

Follow each subreddit's rules, Reddit's content policy, and anti-spam guidance. This skill is
for genuine, source-backed participation — not promotion or karma farming. The operator is
responsible for every confirmed post.
