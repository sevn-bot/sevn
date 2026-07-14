---
id: prd-00-main
kind: prd
title: sevn.bot — Umbrella PRD
status: ready
owner: Alex
summary: Self-hosted personal AI gateway—multi-channel, memory-rich, operator-owned—with
  tools, transparency, and control instead of vendor lock-in.
last_updated: '2026-07-14'
fingerprint: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
related: []
sources: []
parent_prd: null
personas:
- operator
prd_profile: standard
---

## Problem & Motivation

Most consumer AI assistants are tied to one app, one model vendor, and one billing model. They
forget who you are between sessions, cannot be steered mid-flight, cannot reach into your tools,
and ask you to trust a black box with your keys and your data. Power users who want a **daily
driver** hit the ceiling fast: no Telegram-native life, no durable personality, no visibility
into what the bot just did, and no graceful path when a provider blips.

sevn.bot exists to be an **ownable, self-hosted personal AI gateway**—your rules, your
workspace, your channels, your providers—without giving up the conversational fluency people
expect from modern assistants.

- **Who:** Self-hosted operators who want one assistant across phone and laptop, with memory,
  tools, and cost they can see and control.
- **Pain:** Hosted assistants optimize for the vendor's funnel, not the operator's life: single
  channel lock-in, amnesia between sessions, opaque spend, and brittle trust when the model can
  act on your behalf.
- **Why now:** Model quality and tool use are good enough for daily work; what is missing is a
  product shape that treats **ownership, observability, and operator control** as first-class—
  not afterthoughts bolted onto a chat widget.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Daily-driver operator | Reaches for AI from phone or laptop during the day | Gets a consistent assistant in Telegram, Web UI, or voice without re-explaining context |
| UJ-002 | Power operator | Wants the bot to *do* things—fetch, code, automate, notify | Completes real tasks via tools and skills with approvals and kill switches when risk rises |
| UJ-003 | Security-conscious operator | Considers letting the bot touch secrets, shell, or the network | Stays in control via sandboxing, egress isolation, scanning, and visible traces—not blind trust |
| UJ-004 | Cost-aware operator | Pays per token or via subscription slots | Chooses providers, sees spend signals, and survives vendor outages without rebuilding the stack |

**Narrative:**

- **UJ-001 — Conversational daily driver:** The operator onboarded once, talks from Telegram on
  the go and Mission Control or Web UI at the desk, and the assistant remembers tone and context
  instead of greeting a stranger each morning.
- **UJ-002 — Getting things done:** A question becomes an action: a page fetch, a cron digest, a
  PR comment, a generated panel—bounded by what the operator enabled and what Mission Control
  can show afterward.
- **UJ-003 — Trust with teeth:** Before high-impact execution, the operator sees what will run,
  can steer or stop a turn, and relies on paired proxy and secrets patterns so provider keys never
  live in the gateway process.
- **UJ-004 — Sustainable cost:** The operator mixes API keys and subscription-backed slots,
  gets warned before credentials expire, and shifts traffic when a vendor is down or too
  expensive—without migrating to a different product.

## Goals

- **FR-001:** Deliver a **multi-channel gateway** so the same assistant is reachable from
  Telegram, Web UI, and voice hooks—the surfaces operators already live in.
- **FR-002:** Provide **persistent personality and memory** so context, tone, and operator
  preferences accumulate across sessions instead of resetting daily.
- **FR-003:** Make **trust and control** explicit: security scanning, sandboxed execution,
  secrets hygiene, and operator-visible approval paths before consequential action.
- **FR-004:** Enable **getting things done** through a tiered agent runtime, tools registry,
  skills, and non-interactive triggers when events—not chat—start the work.
- **FR-005:** Support **cost and provider choice** with multi-vendor slots, credential health
  signals, and graceful degradation—not single-vendor lock-in.
- **FR-006:** Offer **setup and operations** that pass the first-ten-minutes test: onboard,
  doctor, run, and recover without becoming a part-time SRE.
- **FR-007:** Expose **Mission Control** so operators can see traces, provider status, and ops
  surfaces instead of flying blind after each turn.
- **FR-008:** Extend into **coding companion**, **knowledge base**, **generated UI**,
  **automation**, **self-improvement**, and **extensibility** as domain PRDs—without collapsing
  them into one monolith document.

## Non-Goals

- A hosted multi-tenant SaaS that competes with consumer ChatGPT subscriptions on convenience
  alone—sevn.bot optimizes for **self-hosted ownership**, not mass-market onboarding funnels.
- Enterprise org-wide identity, billing, and RBAC suites—v1 centers the **single operator**
  workspace.
- Fully autonomous self-modification without operator review—improvement loops stay gated
  (see prd-12-self-improvement).
- Replacing best-in-class IDEs or note apps—coding and second-brain features **augment** the
  assistant; they do not need to win every category outright.
- Real-time accounting or invoice systems—cost **visibility** for operators is in scope;
  corporate finance integrations are not.

## Experience

- **Happy path:** Clone, `make setup`, `sevn onboard`, `sevn doctor`, start the gateway—first
  Telegram or Web UI reply within minutes. Day two feels like the same assistant: memory sticks,
  channels match, Mission Control shows what happened.
- **Operator controls:** Workspace config, provider and model slots, tool/skill enablement,
  channel pairing, steer/stop during long turns, automation triggers, and improvement jobs—all
  operator-owned artifacts, not hidden vendor toggles.
- **Degraded path (product-level):** Provider outage → failover slot or clear error, not a
  silent hang. Expired credentials → doctor warning before the embarrassing mid-conversation
  failure. Risky tool call → block or approval path with plain-language explanation. Low
  confidence → abstain or ask rather than confabulate.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Median time from fresh clone to first successful channel reply (onboarding happy path) | ≤ 15 minutes on reference hardware | onboarding smoke, operator checklist |
| KPI-002 | Operator can inspect the latest turn outcome without reading raw logs | Mission Control or trace export surfaces last turn within one navigation step | MC E2E, manual QA |
| KPI-003 | Misconfigured credentials caught before first failed turn | ≥ 90% of fixture misconfigs warned by doctor/validate | doctor/validate suites |
| KPI-004 | Documented domain PRDs trace to this umbrella with `parent_prd: prd-00-main` | 100% of shipped product PRDs (excl. draft/evidence) | prd index, validator |
| KPI-005 | Operator-reported "feels like same assistant across channels" on memory-enabled profiles | Directional improvement vs cold-start baseline | feedback, session replay samples |

## Traceability

### Implementing Specs

The umbrella PRD does not map 1:1 to engineering specs. **Domain PRDs** below decompose product
intent; each links `spec-NN-slug` entries in its own Traceability section.

| PRD id | Scope |
| --- | --- |
| prd-01-conversational-experience | Telegram, Web UI, voice, and OpenUI conversational surfaces |
| prd-02-personality-and-memory | Tone, user model, LCM, dreaming, Honcho opt-ins |
| prd-03-trust-and-control | Secrets, proxy, sandbox, scanner, approvals |
| prd-04-getting-things-done | Tools, skills, executors, sandboxes, task completion |
| prd-05-cost-and-providers | Multi-provider slots, OAuth/API auth, spend visibility |
| prd-06-setup-and-operations | Onboard, doctor, CLI ops, daemon install |
| prd-07-mission-control | Dashboard, traces, ops panels, provider status |
| prd-08-coding-companion | Repo orientation, agents, coding workflows |
| prd-09-knowledge-base | Second brain, wiki, ingest, provenance |
| prd-10-generated-ui | OpenUI panels and structured HTML delivery |
| prd-11-automation-and-triggers | Webhooks, cron, dedupe, notify-only automation |
| prd-12-self-improvement | Eval loops, harness upgrades, gated self-change |
| prd-13-extensibility | Plugins, hooks, org-specific glue |

Downstream flow: **PRD → specify → plan → tasks** in spec-kit-wave; normative acceptance
criteria live in `about-sevn.bot/specs/`, not here.

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
| 0.9 | 2026-06-19 | Scaffolded six-section PRD shell from about-docs pipeline | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave standard; expanded umbrella product prose and domain PRD map | MODIFIED prd-00-main (structure) |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should the umbrella PRD list engineering `spec-*` ids directly, or only domain PRDs? | Alex | 2026-07-08 | resolved — domain PRDs own spec traceability; umbrella keeps `specs: []` |
| OQ-002 | Primary persona: solo operator only, or small team shared workspace? | Alex | 2026-07-08 | resolved — solo self-hosted operator is v1; team/shared workspace deferred |
| OQ-003 | Include prd-14-live-session-failures in the domain map while still draft? | Alex | 2026-07-08 | resolved — omit from Implementing Specs table until status leaves draft |
