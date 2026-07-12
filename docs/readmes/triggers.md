<!-- generated: do not edit by hand; run `sevn readme update triggers` -->
# Non-interactive triggers — Webhooks, cron, dedupe, dispatcher, and notify-only automation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Webhooks, cron, dedupe, dispatcher, and notify-only automation.

## Level 1 — Overview (non-technical)

**Non-interactive triggers** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Webhooks, cron, dedupe, dispatcher, and notify-only automation.

In everyday use, non-interactive triggers helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver non-interactive dispatch: external events (“something happened”) and schedules (“tick”) compile to DispatchRequest, optionally pass through notify_only (zero LLM, zero sandbox boot), otherwise

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/triggers/`. The package contains 19 Python module(s); primary entry points include `src/sevn/triggers/__init__.py`, `src/sevn/triggers/api_router.py`, `src/sevn/triggers/auth.py`, `src/sevn/triggers/coding_agent_loop.py`, and 2 more.

### Data and control flow

Non-interactive triggers sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/30-non-interactive-triggers.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/triggers/api_router.py` — `build_api_router`
- `src/sevn/triggers/auth.py` — `triggers_api_auth_required`, `verify_triggers_api_bearer`
- `src/sevn/triggers/coding_agent_loop.py` — `mine_session_trajectories`, `coding_agent_loop_trigger`
- `src/sevn/triggers/cron.py` — `format_next_fire_at_iso`, `cron_job_to_dict`, `cron_job_to_list_dict`, `SqliteCronStore.list_due`
- `src/sevn/triggers/dedupe.py` — `try_insert_webhook_dedupe`, `prune_webhook_dedupe_expired`

### Spec context

From specs/30-non-interactive-triggers.md:
Deliver non-interactive dispatch: external events (“something happened”) and schedules (“tick”) compile to DispatchRequest, optionally pass through notify_only (zero LLM, zero sandbox boot), otherwise

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/triggers/` (19 Python files). Normative design: `specs/30-non-interactive-triggers.md`.

### Module inventory

- `src/sevn/triggers/__init__.py` — """Non-interactive triggers ('specs/30-non-interactive-triggers.md').
- `src/sevn/triggers/api_router.py` — """HTTP API for non-interactive runs ('specs/30-non-interactive-triggers.md' §2.2).
- `src/sevn/triggers/auth.py` — """Triggers API bearer verification ('specs/30-non-interactive-triggers.md' §2.2, §11).
- `src/sevn/triggers/coding_agent_loop.py` — """Coding agent loop trigger — ALRCA background loop + session-mining hook (CA6.3).
- `src/sevn/triggers/cron.py` — """SQLite-backed cron job store ('specs/30-non-interactive-triggers.md' §2.4, §3.2).
- `src/sevn/triggers/dedupe.py` — """Webhook dedupe persistence ('specs/30-non-interactive-triggers.md' §3.2).
- `src/sevn/triggers/delivery.py` — """Result fan-out for trigger dispatches ('specs/30-non-interactive-triggers.md' §4.6).
- `src/sevn/triggers/dispatcher.py` — """Core trigger dispatch ('specs/30-non-interactive-triggers.md' §2.1).
- `src/sevn/triggers/hooks.py` — """See :mod:'sevn.plugins.registry' and :mod:'sevn.plugins.trigger_mux' ('specs/34-plugin-hooks.md')."""
- `src/sevn/triggers/hooks_protocol.py` — """Minimal hook surface for trigger ingress ('specs/34-plugin-hooks.md' §4.7 stub).
- `src/sevn/triggers/inbox.py` — """Trigger inbox spill + retention ('specs/30-non-interactive-triggers.md' §3.3).
- `src/sevn/triggers/request.py` — """Dispatch envelopes for non-interactive runs ('specs/30-non-interactive-triggers.md' §3.1).
- … and 7 more Python modules

### Api Router (`src/sevn/triggers/api_router.py`)

Public entry points:
- `build_api_router` — see `src/sevn/triggers/api_router.py`

### Auth (`src/sevn/triggers/auth.py`)

Public entry points:
- `triggers_api_auth_required` — see `src/sevn/triggers/auth.py`
- `verify_triggers_api_bearer` — see `src/sevn/triggers/auth.py`

### Coding Agent Loop (`src/sevn/triggers/coding_agent_loop.py`)

Public entry points:
- `mine_session_trajectories` — see `src/sevn/triggers/coding_agent_loop.py`
- `coding_agent_loop_trigger` — see `src/sevn/triggers/coding_agent_loop.py`

### Cron (`src/sevn/triggers/cron.py`)

Public entry points:
- `format_next_fire_at_iso` — see `src/sevn/triggers/cron.py`
- `cron_job_to_dict` — see `src/sevn/triggers/cron.py`
- `cron_job_to_list_dict` — see `src/sevn/triggers/cron.py`
- `SqliteCronStore.list_due` — see `src/sevn/triggers/cron.py`
- `SqliteCronStore.update_schedule` — see `src/sevn/triggers/cron.py`
- `SqliteCronStore.list_jobs` — see `src/sevn/triggers/cron.py`
- `SqliteCronStore (+4 methods)` — see `src/sevn/triggers/cron.py`
- `list_cron_jobs` — see `src/sevn/triggers/cron.py`

### Dedupe (`src/sevn/triggers/dedupe.py`)

Public entry points:
- `try_insert_webhook_dedupe` — see `src/sevn/triggers/dedupe.py`
- `prune_webhook_dedupe_expired` — see `src/sevn/triggers/dedupe.py`

### Delivery (`src/sevn/triggers/delivery.py`)

Public entry points:
- `trigger_runs_dir` — see `src/sevn/triggers/delivery.py`
- `write_log_result` — see `src/sevn/triggers/delivery.py`

### Dispatcher (`src/sevn/triggers/dispatcher.py`)

Public entry points:
- `agent_dispatch_kwargs` — see `src/sevn/triggers/dispatcher.py`
- `TriggerDispatchGate.limit` — see `src/sevn/triggers/dispatcher.py`
- `TriggerDispatchGate.acquire_api_slot` — see `src/sevn/triggers/dispatcher.py`
- `TriggerDispatchGate.release_api_slot` — see `src/sevn/triggers/dispatcher.py`
- `TriggerDispatchGate (+3 methods)` — see `src/sevn/triggers/dispatcher.py`
- `dispatch_notify_only` — see `src/sevn/triggers/dispatcher.py`
- `dispatch_run` — see `src/sevn/triggers/dispatcher.py`

### Hooks Protocol (`src/sevn/triggers/hooks_protocol.py`)

Public entry points:
- `TriggerPluginHookSurface.trigger_before_receive` — see `src/sevn/triggers/hooks_protocol.py`
- `TriggerPluginHookSurface.trigger_after_dispatch` — see `src/sevn/triggers/hooks_protocol.py`

### Additional modules

7 more Python files under `src/sevn/triggers/` — including `src/sevn/triggers/settings.py`, `src/sevn/triggers/sources/__init__.py`, `src/sevn/triggers/sources/github.py`, `src/sevn/triggers/trace_util.py`.

### Extension and invariants

Follow `specs/30-non-interactive-triggers.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/triggers/`, run `sevn readme update triggers` and `make readme-check`.

## References

- [specs/30-non-interactive-triggers.md](specs/30-non-interactive-triggers.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/30-non-interactive-triggers.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/triggers/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
