---
name: sessions_management
description: Gateway sessions, history, send, spawn, yield, and status (`specs/17-gateway.md`).
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/list.py
    description: List visibility-scoped gateway sessions (replaces sessions_list).
    args_overview: "[--session-id ID] [--channel CH] [--user-id UID] [--date-from ISO] [--date-to ISO] [--limit N]"
  - path: scripts/history.py
    description: Fetch or search session message history (replaces sessions_history).
    args_overview: "[--session-id ID] [--query STR] [--limit N] [--offset N] [--full]"
  - path: scripts/send.py
    description: Post a line to another session (replaces sessions_send).
    args_overview: "--session-id ID --text STR [--role user|system]"
  - path: scripts/spawn.py
    description: Mint an isolated subagent session (replaces sessions_spawn).
    args_overview: "--parent-session-id ID [--system-prompt STR] [--tool TOOL ...]"
  - path: scripts/yield.py
    description: Record yield payload and optional delegation (replaces sessions_yield).
    args_overview: "--session-id ID [--reason STR] [--delegate-to ID] [--delegate-message STR] [--payload-json JSON]"
  - path: scripts/status.py
    description: Run-state snapshot from gateway SQLite (replaces session_status).
    args_overview: "--session-id ID"
  - path: scripts/sessions.py
    description: Legacy alias for list / send / get (replaces sessions).
    args_overview: "--action list|send|get [--session-id ID] [--text STR] [--channel CH] [--limit N]"
---

# Sessions management skill

Use native **`load_skill`** + **`run_skill_script`** to inspect and coordinate gateway
sessions stored in workspace ``sevn.db``. Scripts emit a single JSON envelope on stdout
per [`specs/12-skills-system.md`](../../../specs/12-skills-system.md) §2.4.

Set **`SEVN_WORKSPACE`** (injected by the skill runner) and pass **`--session-id`**
(or **`SEVN_SESSION_ID`**) for visibility-scoped list/history/send operations.
