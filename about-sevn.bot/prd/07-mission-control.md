---
id: prd-07-mission-control
kind: prd
title: Mission Control — PRD
status: ready
owner: Alex
summary: Operator dashboard for traces, spend, provider health, and in-flight runs—so
  a capable self-hosted bot stays livable instead of flying blind after each turn.
last_updated: '2026-07-21'
fingerprint: sha256:e08b384f7e425c49a1f50b406ced80cd3eeeb531d8f1916da4a41064a6e89a57
related:
- prd-05-cost-and-providers
sources:
- src/sevn/ui/**
parent_prd: prd-00-main
specs:
- spec-04-tracing
- spec-07-egress-proxy
- spec-24-dashboard
- spec-35-bot-evolution
personas:
- operator
prd_profile: standard
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-04-tracing | draft |
| spec-07-egress-proxy | draft |
| spec-24-dashboard | draft |
| spec-35-bot-evolution | scaffold |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

A self-hosted AI bot that *can* do a lot is hard to live with unless you can *see* what it just
did. Three failure modes show up immediately:

1. **Turn blindness** — the operator gets a reply in Telegram or Web UI but cannot tell which
   tools ran, what failed, or what was redacted before delivery.
2. **Cost and credential drift** — token spend and provider or OAuth health stay invisible until
   a turn fails mid-conversation or the monthly bill surprises.
3. **Ops archaeology** — diagnosing proxy pairing, channel status, or a stuck in-flight run
   means opening SQLite, tailing logs, or SSH—not a product experience.

sevn.bot already emits structured traces and runs a same-process gateway; Mission Control is the
**operator-facing dashboard** that turns that telemetry into inspectable panels instead of
forensics.

- **Who:** Self-hosted operators who run the gateway daily and need visibility after each turn,
  not only when something breaks.
- **Pain:** Without a dashboard, trust erodes: you cannot verify approvals, replay a failure,
  nudge a reauth, or confirm the paired egress proxy is healthy before blaming the model.
- **Why now:** Tracing, provider slots, OAuth, evolution pipelines, and OpenUI delivery all
  produce operator-relevant signals—this PRD makes **visibility and light control** the product
  contract for the web dashboard at `/mission/`.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Daily operator | Wants to know what the bot did on the last turn | Opens Traces or Audit and sees tool calls, tiers, and redaction without reading raw logs |
| UJ-002 | Cost-aware operator | Monthly spend or a noisy model slot feels wrong | Reviews Budget and Cost and provider panels before changing assignments |
| UJ-003 | Ops-minded operator | Turn failed, proxy blipped, or OAuth is near expiry | Sees provider, egress, and channel health in Observability; recovers via reauth or doctor-aligned prompts |
| UJ-004 | Power operator | Long-running job, evolution pipeline, or coding-agent run is in flight | Inspects run status, approvals, and evolution traces; can steer or stop from dashboard surfaces where exposed |

**Narrative:**

- **UJ-001 — After-turn inspection:** A Telegram reply looked wrong. The operator opens Mission
  Control Traces, filters to the session, and sees triage → executor → tool spans with
  redaction applied at query time—enough to decide whether to regen, steer, or fix config.
- **UJ-002 — Spend sanity check:** Before assigning a heavier model slot, the operator checks
  Budget and Cost rollups derived from trace events, then adjusts assignments in Agent or
  Providers panels without editing JSON by hand.
- **UJ-003 — Credential and proxy hygiene:** Doctor warned about OAuth expiry; Mission Control
  Providers panel shows the same signal and offers a reauth path. Egress proxy health is
  visible alongside gateway status so outbound failures are not misread as model bugs.
- **UJ-004 — Control-plane recovery:** After gateway restart, boot-resume prompts and workspace
  layout validation surface in Ops panels; evolution issues and pipeline approvals stay
  inspectable instead of disappearing into background jobs.

## Goals

- **FR-001:** Deliver **Mission Control** as an owner-only web dashboard served at `/mission/`
  on the gateway process, with password auth for non-loopback access.
- **FR-002:** Operators shall **inspect traces and audit timelines** for recent turns—tool
  calls, approvals, provider events, and mission operations—without opening SQLite manually.
- **FR-003:** The product shall expose **budget and cost rollups** from trace telemetry so
  operators can sanity-check spend before changing model slots.
- **FR-004:** **Provider, channel, and egress-proxy health** shall be visible in Observability
  and Ops groups, including OAuth reauth affordances aligned with prd-05-cost-and-providers.
- **FR-005:** Operators shall **configure agent, skills, channels, and workspace artifacts**
  through dashboard panels where wired—reducing raw `sevn.json` edits for day-2 ops.
- **FR-006:** **In-flight and post-hoc run inspection** shall cover webchat console, coding
  agents, cron jobs, and evolution pipelines with enough status to decide whether to wait,
  approve, or intervene.
- **FR-007:** **Boot-resume and layout validation** signals shall reach the operator through
  Mission Control or CLI-aligned panels so restarts do not silently drop workspace state.
- **FR-008:** Sensitive values shall be **redacted at query time** in trace and audit views—
  the dashboard must not become a secrets leak surface.
- **FR-009:** Gateway **shutdown browser reap failures** and **issue-watch / cron operator
  notify** shall be observable (logged reap errors; owner Telegram sink when wired at boot)
  so session-tooling teardown and non-interactive alerts are not silent.
- **FR-010:** **Turn-stage latency attribution** shall reach Mission Control when wired; when
  the MC hook is missing, the gateway shall log the no-op (`agent_turn_stage_latency_unwired`)
  so high-latency stage samples are not dropped invisibly.

## Non-Goals

- A multi-tenant SaaS admin console or org-wide RBAC suite—v1 centers the **single owner**
  workspace (team dashboards deferred).
- Replacing Telegram `/config` or the CLI for every operation—Mission Control complements
  mobile and terminal workflows; it does not need parity on day one for every menu row.
- Real-time accounting, invoicing, or finance-system integrations—**visibility** from traces
  is in scope; corporate billing is not.
- A full hosted observability stack (Grafana/Loki required)—export hooks may exist in specs,
  but the product default is an integrated same-process dashboard.
- Unauthenticated public dashboards—remote access requires owner auth even when tabs are
  read-only.

## Experience

- **Happy path:** Operator completes onboarding, opens `http://127.0.0.1:<port>/mission/` (or
  a tunneled URL), signs in when required, and lands on Core or Observability. Latest traces
  and provider status are one or two clicks away; config edits persist back to `sevn.json`
  through validated API paths.
- **Operator controls:** Dashboard password and `dashboard.local_open` loopback policy; tab
  groups (Core, Observability, Agent, Knowledge, Self-improve, Evolution, Ops, Surfaces);
  in-dashboard webchat with stop/fork; CLI console for bounded `sevn` subcommands; provider
  reauth; evolution approval actions where wired. **System** menu shows read-only **Version id**
  from `GET /api/v1/config` (build identity persisted in `sevn.json`; orthogonal to deployment id).
- **Degraded path:** Trace sink unavailable → panels show explicit empty or error states, not
  stale fabrications. Expired OAuth → Providers panel nudges reauth before hard turn failure.
  Proxy unhealthy → Egress panel shows paired-daemon status. Unwired tab → “coming soon” in live
  UI; help preview may still document intent.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Operator inspects latest turn outcome without reading raw gateway logs | Trace or audit view within one navigation step from dashboard home | MC E2E, manual QA |
| KPI-002 | Provider or OAuth misconfiguration visible before first failed turn | ≥95% of fixture misconfigs surfaced in Providers or doctor-aligned panels | doctor/validate + MC fixtures |
| KPI-003 | Budget/cost rollup loads from trace DB on reference workspace | P95 load ≤ 3s on CI fixture | MC API smoke |
| KPI-004 | Owner-only auth enforced on non-loopback dashboard access | 100% of unauthenticated remote requests rejected | auth integration tests |
| KPI-005 | Redaction applied in trace detail API responses | Zero raw secret values in MC trace fixtures | security/trace tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-04-tracing | Trace sinks, event schema, query-time redaction feeding MC observability panels |
| spec-07-egress-proxy | Paired proxy health, provider outbound path, token lifecycle surfaces in Ops |
| spec-24-dashboard | Mission Control SPA, tab registry, REST API, auth, and panel wiring |
| spec-35-bot-evolution | Evolution issues, pipelines, approvals, and evolution trace panels |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new dashboard tabs.

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
| 0.9 | 2026-07-07 | Scaffolded six-section PRD shell from about-docs pipeline | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave standard; expanded visibility, traces, and ops framing | MODIFIED prd-07-mission-control (structure); traceability aligned to spec-04/07/24/35 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Mission Control show estimated per-turn cost for OAuth-backed turns when OpenAI exposes usage? | Alex | 2026-08-01 | resolved — defer to tracing rollups; OAuth path ships without per-turn estimate UI (see prd-05-cost-and-providers OQ-001) |
| OQ-002 | Default tab on first login—Core Overview vs Observability Traces? | Alex | 2026-08-01 | resolved — Observability-first when traces exist; Core Overview otherwise |
| OQ-003 | Expose full terminal shell in dashboard or keep bounded CLI console only? | Alex | 2026-08-01 | resolved — bounded CLI console for v1; full terminal tab stays unwired until sandbox story is explicit |
