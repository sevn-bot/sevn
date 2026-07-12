---
id: prd-05-cost-and-providers
kind: prd
title: Cost & Providers — PRD
status: ready
owner: Alex
summary: Operators choose how they pay for models—API keys, ChatGPT subscription via
  OAuth, and multi-provider slots—with spend visible and graceful degradation when
  a vendor fails.
last_updated: '2026-07-12'
fingerprint: sha256:c845bab0e908bf0e3a85ad7803357000a7456bb1f43d7973085d41a7654d748a
related: []
sources:
- src/sevn/proxy/**
- src/sevn/voice/**
parent_prd: prd-00-main
depends_on: []
build_phase: null
interfaces: []
specs:
- spec-05-llm-transports
- spec-06-secrets
- spec-07-egress-proxy
- spec-20-voice
personas:
- operator
prd_profile: standard
---

## Problem & Motivation

Most consumer AI assistants lock you to one vendor, hide true cost behind a flat subscription,
and stop working when that vendor has an outage. sevn.bot targets **power users** who pay
differently: per-token API keys, ChatGPT Plus/Pro/Team subscriptions, and multiple model slots
for failover.

- **Who:** Self-hosted operators who run sevn daily and care about spend, credential hygiene,
  and not losing a working bot when one provider blips.
- **Pain:** Today, using a ChatGPT subscription inside a gateway usually means brittle
  unofficial bridges—or giving up and buying a second API key. Operators also lack early
  warning when credentials expire until a turn fails mid-conversation.
- **Why now:** OpenAI's sanctioned Codex OAuth path lets a subscription-backed operator run
  turns without an API key, while sevn's multi-provider model slots and egress proxy already
  support mixing vendors—this PRD makes the **product contract** for cost and credentials
  explicit.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Subscription operator | Wants ChatGPT Plus/Pro/Team to fund OpenAI turns | Signs in once; assigned OpenAI models route via subscription without an API key |
| UJ-002 | API-key operator | Already has OpenAI/Anthropic/MiniMax keys | Configures keys or env buckets; behavior unchanged from legacy setups |
| UJ-003 | Operator maintaining uptime | Provider outage or expired OAuth token | Doctor/validate warn before failure; Mission Control surfaces reauth; failover slot can take over if configured |

**Narrative:**

- **UJ-001 — Subscription-backed OpenAI:** During onboarding or from CLI, the operator
  completes ChatGPT sign-in, sets OpenAI slots to subscription auth, and assigns catalog models.
  Turns complete without configuring a pay-as-you-go key. Near expiry, Mission Control nudges
  reauth before the first hard failure.
- **UJ-002 — API-key path:** Operator leaves default API-key auth, sets keys in config or
  secrets, and assigns models as today—no OAuth flow required.
- **UJ-003 — Credential hygiene:** Before a long session, `sevn doctor` reports missing or
  stale OAuth credentials as warnings; `--fix` can prompt reauth. Validate surfaces the same
  signals in CI-style checks.

## Goals

- **FR-001:** The product shall support **two OpenAI auth modes** per operator choice:
  pay-as-you-go **API key** (default, backward compatible) and **subscription OAuth**
  (sanctioned Codex flow)—never unofficial ChatGPT scraping.
- **FR-002:** Subscription operators shall complete OpenAI turns on assigned model slots
  without configuring an OpenAI API key when OAuth credentials are valid.
- **FR-003:** The product shall **refresh OAuth tokens** on the operator's behalf (proxy-owned
  lifecycle) so short-lived credentials do not require manual paste-in.
- **FR-004:** **Config validate** and **doctor** shall surface missing or expired OAuth
  credentials as **non-fatal warnings** before the first failed turn; doctor `--fix` shall
  offer a reauth path.
- **FR-005:** Operators shall see **provider and credential status** in Mission Control
  (Providers panel)—including reauth when a token is near expiry.
- **FR-006:** The product shall allow **multiple provider slots** and model assignment so
  operators can shift traffic when a vendor is down or too expensive—details in implementing
  specs, not a single-vendor lock-in.

## Non-Goals

- Scraping, reverse-engineering, or unofficial ChatGPT web bridges.
- Replacing MiniMax, Anthropic, or other provider credential paths covered by sibling specs.
- Real-time **billing dashboards** or invoice ingestion (cost *visibility* for tokens is
  in scope via tracing/Mission Control; accounting systems are not).
- Automatic **cheapest-model routing** without operator configuration (no silent vendor
  switching that could change behavior or compliance posture).

## Experience

- **Happy path (subscription):** Sign in with ChatGPT during onboarding or via
  `sevn providers oauth login`. Assign OpenAI models in config. Telegram and web chat work;
  Mission Control Providers panel shows connected state.
- **Happy path (API key):** Configure provider keys as today; no OAuth UI required.
- **Operator controls:** Auth mode per OpenAI provider config; model slot assignment;
  optional failover ordering across slots (when configured).
- **Degraded path:** Expired OAuth → doctor warning first, then user-visible turn failure
  if ignored; Mission Control offers reauth. Provider outage → failover slot if configured,
  otherwise clear error—not a silent hang.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | OAuth-assigned OpenAI slots complete turns without API key configured | 100% on happy path | integration tests, operator smoke |
| KPI-002 | Doctor/validate warn on missing OAuth before first failed turn | ≥95% of misconfigurations caught pre-turn | doctor/validate fixtures |
| KPI-003 | Reauth completion from Mission Control Providers panel | Operator can recover without editing files manually | MC E2E / manual checklist |
| KPI-004 | API-key operators unaffected by OAuth rollout | Zero regressions on default auth_mode | CI, backward-compat tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-05-llm-transports | Provider auth modes, Codex OAuth routing, model slots, transport normalization |
| spec-06-secrets | OAuth credential storage, refresh, and resolution at request time |
| spec-07-egress-proxy | Proxy-owned token lifecycle and outbound provider calls |
| spec-20-voice | Voice provider paths that share credential and cost surfaces |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new provider features.

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
| 0.9 | 2026-07-07 | OAuth-focused draft (legacy six-section shape) | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; expanded cost/multi-provider framing | MODIFIED prd-05-cost-and-providers (structure); traceability aligned to spec-05/06/07/20 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Mission Control show estimated per-turn cost for OAuth-backed turns when OpenAI exposes usage? | Alex | 2026-08-01 | resolved — defer to tracing/Mission Control PRD; OAuth path ships without cost estimate UI |
| OQ-002 | Default failover order when multiple OpenAI slots exist—operator-configured only or smart default? | Alex | 2026-08-01 | resolved — operator-configured only for v1; no silent failover |
