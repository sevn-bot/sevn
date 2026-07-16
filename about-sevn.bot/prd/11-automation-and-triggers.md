---
id: prd-11-automation-and-triggers
kind: prd
title: Automation and Triggers — PRD
status: ready
owner: Alex
summary: Events and schedules—not chat—start work via webhooks, cron, dedupe, and
  notify-only paths so operators automate digests, alerts, and agent runs safely.
last_updated: '2026-07-16'
fingerprint: sha256:0c329b0fe8ab679f7e7267014d9ea5775c2471c13d328b7255006e6932159ca6
related:
- prd-07-mission-control
- prd-13-extensibility
sources:
- src/sevn/triggers/**
parent_prd: prd-00-main
specs:
- spec-30-non-interactive-triggers
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-20-voice
- spec-21-executor-tier-cd
personas:
- operator
prd_profile: standard
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-30-non-interactive-triggers | draft |
| spec-17-gateway | draft |
| spec-18-channel-telegram | draft |
| spec-19-channel-webui | draft |
| spec-20-voice | draft |
| spec-21-executor-tier-cd | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

Interactive chat is the daily-driver path, but real work also arrives as **events**: a PR
merges, a calendar window opens, a monitoring system pages, or a clock tick says "do the
Sunday digest." A chat-only assistant forces the operator to copy alerts in by hand, run
fragile side scripts that bypass sandbox and trace visibility, or stay online for routine
jobs.

- **Who:** Self-hosted operators who want the same assistant to react when something
  happens—not only when they type in Telegram or webchat.
- **Pain:** External cron wrappers and webhook glue bypass sevn's security posture, duplicate
  deliveries burn tokens on retries, and low-value alerts should not boot a full agent turn
  every time.
- **Why now:** Webhooks, SQLite cron, dedupe, a triggers HTTP API, and two delivery modes
  (`agent_pass` vs `notify_only`) are implemented—this PRD states the **product contract**
  for non-interactive automation.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Scheduled-digest operator | Cron fires (e.g. Sunday morning) | Digest or report arrives on the configured channel without a manual prompt |
| UJ-002 | Webhook integrator | GitHub, monitoring, or custom HTTP posts an event | One dispatch per logical event—deduped on retries—with agent or template delivery |
| UJ-003 | API caller | Operator or script POSTs to the triggers API with bearer auth | Programmatic run with traceable outcome and channel fan-out |
| UJ-004 | Cost-conscious operator | High-volume or low-signal alert stream | `notify_only` renders a template to Telegram or web with zero LLM and zero sandbox boot |

**Narrative:**

- **UJ-001 — Scheduled work:** Operator registers a recurring cron job or one-shot reminder
  during setup or via CLI/API. When the schedule fires, the gateway dispatches a run with the
  stored prompt; results land on Telegram, webchat, logs, or voice when configured.
- **UJ-002 — Event-driven work:** Operator points GitHub or a monitoring tool at the gateway
  webhook URL with a signing secret. Verified payloads compose a prompt; dedupe suppresses
  double fires from vendor retries. Mission Control and traces show what ran—not a black-box
  script on the side.
- **UJ-003 — Programmatic automation:** Operator mints a triggers API bearer token and POSTs
  run bodies from CI or home automation. Auth failures reject early; successful runs follow
  the same dispatcher path as webhooks and cron.
- **UJ-004 — Lightweight alerts:** Operator routes noisy pings through `notify_only` so a
  template message reaches Telegram without spending tokens on triage and executors.

## Goals

- **FR-001:** The product shall accept **non-interactive ingress** from **webhooks**,
  **schedules (cron/reminders)**, and an **authenticated triggers HTTP API**—all compiling
  to one dispatch envelope before execution.
- **FR-002:** Operators shall choose **two delivery modes** per trigger: **`agent_pass`**
  (full gateway executor run) and **`notify_only`** (template render with zero LLM and zero
  sandbox boot).
- **FR-003:** Webhook ingress shall **dedupe** retried deliveries so the same logical event
  does not spawn duplicate runs or duplicate notifications.
- **FR-004:** Dispatch results shall **fan out** to operator-configured channels—Telegram,
  owner webchat, structured logs, and voice when enabled—using the same visibility expectations
  as interactive turns.
- **FR-005:** Triggers HTTP API and webhook surfaces shall require **operator-controlled
  authentication** (bearer token, signing secrets)—no anonymous public trigger endpoints.
- **FR-006:** Operators shall **manage cron jobs and reminders** (create, edit, delete, list,
  next-fire visibility) without editing raw database files.
- **FR-007:** The product shall enforce **concurrency and size limits** on trigger dispatches
  (inline prompt caps, spill to inbox, dispatch gate) so runaway automation cannot exhaust the
  gateway.
- **FR-008:** **`agent_pass`** dispatches shall integrate with the gateway **executor tiers**
  (triage → tier B/C) so automated runs behave like operator-initiated work—bounded by the
  same tool, sandbox, and approval posture.

## Non-Goals

- A **visual workflow builder** or Zapier-class integration marketplace—v1 is config, CLI,
  API, and signed webhooks.
- **Anonymous or unsigned** webhook endpoints exposed to the public internet without operator
  secrets.
- **Automatic agent runs** on every inbound event without explicit operator configuration of
  source, prompt, and delivery mode.
- **Mission Control observability chrome** for cron editing and run history—admin panels live
  under `prd-07-mission-control`; this PRD covers automation behavior and delivery.
- **Multi-tenant trigger routing** or per-guest webhook namespaces—v1 is single-operator
  workspace scope.

## Experience

- **Happy path (webhook):** Operator configures a GitHub (or generic) webhook with signing
  secret. On merge, the gateway verifies, dedupes, composes a prompt, runs `agent_pass`, and
  posts a summary to Telegram. Traces and trigger run records show success.
- **Happy path (cron):** Operator adds "Sunday digest" cron via CLI or API. At fire time the
  gateway dispatches without manual chat input; the operator reads the digest on their phone.
- **Happy path (notify_only):** Monitoring tool posts a low-signal event; gateway renders a
  template to Telegram instantly—no model call, no sandbox startup.
- **Operator controls:** Triggers API bearer token rotation; webhook signing secrets; per-job
  delivery mode and result channel; cron enable/disable; concurrency and inline-size limits in
  config; plugin hook surface for org-specific ingress (see `prd-13-extensibility`).
- **Degraded path:** Dedupe hit → acknowledge vendor retry without redispatch. Auth or
  signature failure → reject with clear HTTP status, no partial run. Concurrency gate full →
  bounded wait or explicit rejection—not silent drop. `agent_pass` failure → error surfaced on
  configured channel and in traces; `notify_only` template error → logged with operator-visible
  fallback text when possible.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Verified webhook delivers exactly one run per logical event on vendor retry storm | 100% dedupe on fixture replay | dedupe integration tests |
| KPI-002 | `notify_only` dispatch completes without LLM or sandbox boot | Zero model/sandbox spans on happy path | trace assertions, dispatcher tests |
| KPI-003 | Cron job fires within one tick window of scheduled next-fire | ≥99% on reference hardware | cron tick tests |
| KPI-004 | Triggers API rejects missing/invalid bearer before dispatch | 100% on auth fixtures | triggers API tests |
| KPI-005 | `agent_pass` automated run visible in traces and result channel | Operator can answer "what ran?" without raw logs | integration tests, manual checklist |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-30-non-interactive-triggers | Webhooks, cron store, dedupe, dispatcher, triggers API, delivery modes, inbox spill |
| spec-17-gateway | Boot/cron reconcile hooks, turn spine integration for automated dispatches |
| spec-18-channel-telegram | Telegram fan-out for trigger results and notify-only messages |
| spec-19-channel-webui | Owner webchat and WebSocket topics for trigger run visibility |
| spec-20-voice | Voice-capable result delivery when triggers target voice channels |
| spec-21-executor-tier-cd | Tier C/D executor paths for `agent_pass` automated runs |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new trigger sources.

### Stable ID Index

| Prefix | Meaning | Example |
| --- | --- | --- |
| UJ- | User journey | UJ-001 |
| FR- | Product functional requirement | FR-001 |
| KPI- | Success metric | KPI-001 |
| OQ- | Open question | OQ-001 |

### Change Log

| Version | Date | Summary | Spec deltas |
| --- | --- | --- | --- |
| 0.9 | 2026-06-19 | Legacy six-section scaffold with truncated summary | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full automation product contract | MODIFIED prd-11-automation-and-triggers (structure); traceability aligned to spec-30/17/18/19/20/21 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should first fire of a new cron job require explicit operator confirmation? | Alex | 2026-08-01 | resolved — configured jobs fire automatically; one-shot reminders use a separate explicit flow |
| OQ-002 | Default delivery mode when a webhook source is not yet configured—reject vs notify_only? | Alex | 2026-08-01 | resolved — unconfigured or unsigned sources reject; operator must set prompt, secret, and mode per source |
| OQ-003 | Expose cron CRUD in Mission Control v1 or CLI/API only? | Alex | 2026-08-01 | resolved — CLI/API and config paths ship first; Mission Control panels deferred to prd-07-mission-control |
