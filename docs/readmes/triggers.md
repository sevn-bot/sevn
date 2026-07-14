<!-- generated: do not edit by hand; run `sevn readme update triggers` -->
# Non-interactive triggers — Webhooks, cron, dedupe, dispatcher, and notify-only automation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Webhooks, cron, dedupe, dispatcher, and notify-only automation.

## Level 1 — Overview (non-technical)

**Non-interactive triggers** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Webhooks, cron, dedupe, dispatcher, and notify-only automation.

In everyday use, non-interactive triggers helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/triggers/`. The package contains 19 Python module(s); primary entry points include `src/sevn/triggers/__init__.py`, `src/sevn/triggers/api_router.py`, `src/sevn/triggers/auth.py`, `src/sevn/triggers/coding_agent_loop.py`, `src/sevn/triggers/cron.py`, `src/sevn/triggers/dedupe.py`, and 13 more.

### Data and control flow

Non-interactive triggers is organized around `  init  `, `api router`, `auth`, `coding agent loop`, and 2 more under `src/sevn/triggers/` with 19 Python module(s) in the scanned tree. Primary entry points include api_router.py (build_api_router), auth.py (triggers_api_auth_required), coding_agent_loop.py (mine_session_trajectories), cron.py (format_next_fire_at_iso).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/30-non-interactive-triggers.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/triggers/api_router.py` — `build_api_router`
- `src/sevn/triggers/auth.py` — `triggers_api_auth_required`, `verify_triggers_api_bearer`
- `src/sevn/triggers/coding_agent_loop.py` — `mine_session_trajectories`, `coding_agent_loop_trigger`
- `src/sevn/triggers/cron.py` — `format_next_fire_at_iso`, `cron_job_to_dict`, `cron_job_to_list_dict`, `SqliteCronStore.list_due`
- `src/sevn/triggers/dedupe.py` — `try_insert_webhook_dedupe`, `prune_webhook_dedupe_expired`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/triggers`](../../src/sevn/triggers/) (19 Python files). Normative design: `about-sevn.bot/specs/30-non-interactive-triggers.md`.

### Module inventory

Non-interactive triggers (about-sevn.bot/specs/30-non-interactive-triggers.md).

Public entrypoints are mounted from :mod:sevn.gateway.http_server.

Working with [`__init__.py`](../../src/sevn/triggers/__init__.py): inspect the public entry points below.

HTTP API for non-interactive runs (about-sevn.bot/specs/30-non-interactive-triggers.md §2.2).

Working with [`api_router.py`](../../src/sevn/triggers/api_router.py): inspect the public entry points below.
Start with [`build_api_router`](../../src/sevn/triggers/api_router.py#L112).

Triggers API bearer verification (about-sevn.bot/specs/30-non-interactive-triggers.md §2.2, §11).

Working with [`auth.py`](../../src/sevn/triggers/auth.py): inspect the public entry points below.
Start with [`triggers_api_auth_required`](../../src/sevn/triggers/auth.py#L19), then [`verify_triggers_api_bearer`](../../src/sevn/triggers/auth.py#L42).

Coding agent loop trigger — ALRCA background loop + session-mining hook (CA6.3).

Working with [`coding_agent_loop.py`](../../src/sevn/triggers/coding_agent_loop.py): inspect the public entry points below.
Start with [`mine_session_trajectories`](../../src/sevn/triggers/coding_agent_loop.py#L31), then [`coding_agent_loop_trigger`](../../src/sevn/triggers/coding_agent_loop.py#L62).

SQLite-backed cron job store (about-sevn.bot/specs/30-non-interactive-triggers.md §2.4, §3.2).

Working with [`cron.py`](../../src/sevn/triggers/cron.py): inspect the public entry points below.
Start with [`format_next_fire_at_iso`](../../src/sevn/triggers/cron.py#L231), then [`cron_job_to_dict`](../../src/sevn/triggers/cron.py#L252), [`cron_job_to_list_dict`](../../src/sevn/triggers/cron.py#L293), [`SqliteCronStore.list_due`](../../src/sevn/triggers/cron.py#L339).

Webhook dedupe persistence (about-sevn.bot/specs/30-non-interactive-triggers.md §3.2).

Working with [`dedupe.py`](../../src/sevn/triggers/dedupe.py): inspect the public entry points below.
Start with [`try_insert_webhook_dedupe`](../../src/sevn/triggers/dedupe.py#L25), then [`prune_webhook_dedupe_expired`](../../src/sevn/triggers/dedupe.py#L73).

Result fan-out for trigger dispatches (about-sevn.bot/specs/30-non-interactive-triggers.md §4.6).

Working with [`delivery.py`](../../src/sevn/triggers/delivery.py): inspect the public entry points below.
Start with [`trigger_runs_dir`](../../src/sevn/triggers/delivery.py#L25), then [`write_log_result`](../../src/sevn/triggers/delivery.py#L43).

Core trigger dispatch (about-sevn.bot/specs/30-non-interactive-triggers.md §2.1).

Working with [`dispatcher.py`](../../src/sevn/triggers/dispatcher.py): inspect the public entry points below.
Start with [`agent_dispatch_kwargs`](../../src/sevn/triggers/dispatcher.py#L40), then [`TriggerDispatchGate.limit`](../../src/sevn/triggers/dispatcher.py#L85), [`TriggerDispatchGate.acquire_api_slot`](../../src/sevn/triggers/dispatcher.py#L98), [`TriggerDispatchGate.release_api_slot`](../../src/sevn/triggers/dispatcher.py#L119).

See :mod:sevn.plugins.registry and :mod:sevn.plugins.trigger_mux (about-sevn.bot/specs/34-plugin-hooks.md).

Working with [`hooks.py`](../../src/sevn/triggers/hooks.py): inspect the public entry points below.

Minimal hook surface for trigger ingress (about-sevn.bot/specs/34-plugin-hooks.md §4.7 stub).

Working with [`hooks_protocol.py`](../../src/sevn/triggers/hooks_protocol.py): inspect the public entry points below.
Start with [`TriggerPluginHookSurface.trigger_before_receive`](../../src/sevn/triggers/hooks_protocol.py#L24), then [`TriggerPluginHookSurface.trigger_after_dispatch`](../../src/sevn/triggers/hooks_protocol.py#L45).

Trigger inbox spill + retention (about-sevn.bot/specs/30-non-interactive-triggers.md §3.3).

Working with [`inbox.py`](../../src/sevn/triggers/inbox.py): inspect the public entry points below.
Start with [`inbox_dir`](../../src/sevn/triggers/inbox.py#L25), then [`maybe_spill_prompt_to_inbox`](../../src/sevn/triggers/inbox.py#L40), [`prune_inbox_spill`](../../src/sevn/triggers/inbox.py#L80).

Dispatch envelopes for non-interactive runs (about-sevn.bot/specs/30-non-interactive-triggers.md §3.1).

Working with [`request.py`](../../src/sevn/triggers/request.py): inspect the public entry points below.

7 more Python files under [`src/sevn/triggers`](../../src/sevn/triggers/) — including `src/sevn/triggers/settings.py`, `src/sevn/triggers/sources/__init__.py`, `src/sevn/triggers/sources/github.py`, `src/sevn/triggers/trace_util.py`.

### Extension and invariants

Follow [`30-non-interactive-triggers.md`](../../about-sevn.bot/specs/30-non-interactive-triggers.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/triggers`](../../src/sevn/triggers/), run `sevn readme update triggers` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/30-non-interactive-triggers.md](../../about-sevn.bot/specs/30-non-interactive-triggers.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/30-non-interactive-triggers.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/triggers/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
