<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint triggers` -->
# Non-interactive triggers — Webhooks, cron, dedupe, dispatcher, and notify-only automation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Webhooks, cron, dedupe, dispatcher, and notify-only automation.

## Level 1 — Overview (non-technical)

**Non-interactive triggers** wake sevn.bot without a live chat turn: inbound webhooks (GitHub, Slack, Stripe), scheduled cron jobs, and the HTTP triggers API. Each run either passes a prompt to the agent (**agent_pass**) or renders a template notification only (**notify_only**).

Bearer auth protects the triggers API; webhook dedupe prevents double-processing the same delivery.

## Level 2 — How it works (technical)

Package [`src/sevn/triggers/`](../../src/sevn/triggers/). [`build_api_router`](../../src/sevn/triggers/api_router.py#L112) mounts the HTTP API; [`build_webhook_router`](../../src/sevn/triggers/webhook_router.py#L309) adds explicit provider webhook paths on the gateway app.

### Webhook routes and delivery modes

| Route | Handler module | Purpose |
| --- | --- | --- |
| `POST /webhook/github` | [`webhook_router.py`](../../src/sevn/triggers/webhook_router.py#L320) | GitHub deliveries |
| `POST /webhook/slack` | [`webhook_router.py`](../../src/sevn/triggers/webhook_router.py#L324) | Slack events |
| `POST /webhook/stripe` | [`webhook_router.py`](../../src/sevn/triggers/webhook_router.py#L335) | Stripe webhooks |

**Delivery modes** ([`DeliveryMode`](../../src/sevn/triggers/request.py#L26)):
- **`agent_pass`** (default) — enqueue a full agent turn via [`_dispatch_run_agent_pass`](../../src/sevn/triggers/dispatcher.py#L396)
- **`notify_only`** — template render + LOG channel via [`dispatch_notify_only`](../../src/sevn/triggers/dispatcher.py#L197); cron jobs store `notify_only` in SQLite ([`cron.py`](../../src/sevn/triggers/cron.py) [`_normalize_delivery_mode`](../../src/sevn/triggers/cron.py))

**API bearer auth:** [`verify_triggers_api_bearer`](../../src/sevn/triggers/auth.py#L42) / [`triggers_api_auth_required`](../../src/sevn/triggers/auth.py#L19) guard `/api/v1/triggers/*`.

**Dedupe:** [`try_insert_webhook_dedupe`](../../src/sevn/triggers/dedupe.py#L25) inserts idempotency keys; [`prune_webhook_dedupe_expired`](../../src/sevn/triggers/dedupe.py#L73) cleans stale rows.

### Key modules

- [`dispatcher.py`](../../src/sevn/triggers/dispatcher.py) — agent_pass vs notify_only dispatch
- [`webhook_router.py`](../../src/sevn/triggers/webhook_router.py) — explicit `/webhook/<provider>` paths
- [`cron.py`](../../src/sevn/triggers/cron.py) — SQLite cron store + due-job polling
- [`dedupe.py`](../../src/sevn/triggers/dedupe.py) — webhook idempotency
- [`auth.py`](../../src/sevn/triggers/auth.py) — triggers API bearer verification

Normative spec: [`30-non-interactive-triggers.md`](../../about-sevn.bot/specs/30-non-interactive-triggers.md).


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
