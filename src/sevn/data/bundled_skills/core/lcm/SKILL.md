---
name: lcm
description: Lossless context search, drill-back, and conversation index (`specs/15-memory-lcm.md`).
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/status.py
    description: Canonical health/status snapshot for LCM tables and latest summary.
    args_overview: "(no args)"
  - path: scripts/grep.py
    description: Keyword search over visible LCM messages (replaces lcm_grep).
    args_overview: "--query STR [--session-key KEY] [--scope workspace|conversation|same_telegram_topic] [--limit N]"
  - path: scripts/describe.py
    description: Metadata for a message, summary, or large-file id (replaces lcm_describe).
    args_overview: "--id ID [--kind auto|message|summary|large_file]"
  - path: scripts/expand_query.py
    description: Multi-term grep expansion with short synthesis (replaces lcm_expand_query).
    args_overview: "--query STR [--session-key KEY] [--scope SCOPE] [--limit N]"
  - path: scripts/expand.py
    description: Walk summary DAG and return covered messages (replaces lcm_expand).
    args_overview: "--summary-id ID"
  - path: scripts/fetch.py
    description: Fetch one message by id or recent verbatim tail (replaces lcm_fetch).
    args_overview: "[--message-id N] [--session-key KEY] [--limit N]"
  - path: scripts/conversations_meta.py
    description: Conversation metadata and counts (replaces lcm_conversations_meta).
    args_overview: "--conversation-id ID [--conversation-id ID ...]"
  - path: scripts/list_conversations.py
    description: Light conversation index (replaces lcm_list_conversations).
    args_overview: "[--date-from ISO] [--date-to ISO] [--limit N]"
  - path: scripts/search_summaries.py
    description: Keyword search session-end summaries (replaces lcm_search_summaries).
    args_overview: "--query STR [--session-key KEY] [--scope SCOPE] [--date-from ISO] [--date-to ISO] [--limit N]"
---

# LCM skill

Use native **`load_skill`** + **`run_skill_script`** to search and drill into lossless
context stored in workspace ``sevn.db``. Scripts emit a single JSON envelope on stdout
per [`specs/12-skills-system.md`](../../../specs/12-skills-system.md) §2.4.

Set **`SEVN_WORKSPACE`** (injected by the skill runner) and pass **`--session-key`**
(or **`SEVN_SESSION_KEY`**) for conversation-scoped operations.

## About

- Canonical status check: `run_skill_script skill=lcm script=status`
- Search messages quickly: `run_skill_script skill=lcm script=grep -- --query "..." --session-key <key>`
