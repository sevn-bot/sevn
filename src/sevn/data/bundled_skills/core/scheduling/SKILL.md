---
name: scheduling
description: Cron jobs and one-shot reminders via workspace trigger store (`specs/30-non-interactive-triggers.md`).
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/cron_list.py
    description: List persisted cron jobs and reminders (replaces cron_list). Use for "what is scheduled?" and job status reads — same data as the ``cron_status`` alias.
    args_overview: "[--enabled-only]"
  - path: scripts/cron_add.py
    description: Add a recurring cron job (replaces cron_add).
    args_overview: "--job-id ID --cron-expr EXPR [--timezone TZ] [--payload-template STR] [--delivery-mode agent_pass|notify_only] [--routing-mode fixed|auto_route] [--permission-template-ref REF] [--overlap-policy skip|queue|allow] [--allow-tier-cd] [--disabled]"
  - path: scripts/cron_edit.py
    description: Edit an existing cron job (replaces cron_edit).
    args_overview: "--job-id ID [--cron-expr EXPR] [--timezone TZ] [--payload-template STR] [--enabled|--disabled] [--recompute-schedule] [other cron_add flags]"
  - path: scripts/cron_delete.py
    description: Delete a cron job (replaces cron_delete).
    args_overview: "--job-id ID"
  - path: scripts/reminder.py
    description: One-shot reminder at an absolute datetime (replaces reminder).
    args_overview: "--at ISO8601 --prompt STR [--job-id ID] [--timezone TZ] [--delivery-mode agent_pass|notify_only]"
---

# Scheduling skill

Use native **`load_skill`** + **`run_skill_script`** to manage **`trigger_cron_jobs`**
rows in workspace ``sevn.db``. Scripts delegate to **`sevn.triggers.cron`** and emit a
single JSON envelope on stdout per [`specs/12-skills-system.md`](../../../specs/12-skills-system.md) §2.4.

Set **`SEVN_WORKSPACE`** (injected by the skill runner). Gateway **`cron_tick`** dispatches
due rows; this skill only authors persistence.

## Script names

- Accept **bare stems** (`cron_list`, `cron_add`, …) or full paths (`scripts/cron_list.py`).
- **`cron_status`** is an alias for **`scripts/cron_list.py`** — there is no separate status runnable; listing jobs is the supported status read.

## Scheduled vs operational

- **Scheduled / configured:** rows returned by **`cron_list`** (or **`cron_status`**) — jobs exist in ``sevn.db``, with ``next_fire_at`` (ISO UTC) and ``last_status`` from prior fires when present.
- **Scheduler operational (gateway running):** requires evidence that **`cron_tick`** is firing due jobs (recent ``last_correlation_id`` / ``last_status`` updates, or gateway health). Do **not** claim "cron is running" from a list alone — only that jobs are **scheduled** and what the last run recorded.
