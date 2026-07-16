---
id: prd-03-trust-and-control
kind: prd
title: Trust & Control — PRD
status: ready
owner: Alex
summary: Operators delegate real work only when prompt injection, secrets, sandbox,
  and approvals are bounded—scan hostile input, isolate credentials and egress, and
  gate risky tools.
last_updated: '2026-07-16'
fingerprint: sha256:c6bf002ea9ef3a0bbe03928eadea42de49dceb28ca53280025a59dcc5d516878
related:
- prd-07-mission-control
sources:
- src/sevn/security/**
- src/sevn/secrets/**
parent_prd: prd-00-main
specs:
- spec-06-secrets
- spec-07-egress-proxy
- spec-08-sandbox
- spec-09-security-scanner
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-20-voice
- spec-37-openui
personas:
- operator
prd_profile: standard
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-06-secrets | draft |
| spec-07-egress-proxy | draft |
| spec-08-sandbox | draft |
| spec-09-security-scanner | draft |
| spec-17-gateway | draft |
| spec-18-channel-telegram | draft |
| spec-19-channel-webui | draft |
| spec-20-voice | draft |
| spec-37-openui | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

A personal AI is only useful if you can let it act on your behalf. The moment it can act,
three failure modes get serious fast:

- **(a) Prompt injection** — hostile text in a message, attachment, or tool result can steer
  the model toward exfiltrating workspace data, abusing tools, or bypassing operator intent.
- **(b) Credential exposure** — provider keys and integration tokens must not live in the same
  process that reads untrusted chat content or runs agent tool loops.
- **(c) Unbounded execution** — shell, filesystem, and network access without sandbox posture
  turns a helpful assistant into an accidental insider threat.

Consumer assistants hide these tradeoffs behind vendor trust. sevn.bot is **self-hosted**:
the operator owns the blast radius and needs **defense in depth** they can see and tune—not
a black-box "safe mode."

- **Who:** Self-hosted operators who enable tools, secrets, shell, browser, and outbound
  network access for daily work.
- **Pain:** Without explicit trust boundaries, one bad webpage or group-chat injection can
  cascade into secret leaks, irreversible deletes, or silent outbound calls—often discovered
  only after the damage.
- **Why now:** Tool-using agents are default for power users; scanning, sandboxing, paired
  egress, and human approvals are the product contract that makes delegation tolerable.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Security-conscious operator | Enables API keys, OAuth, and integrations | Credentials resolve through a paired egress proxy and encrypted backends—never pasted into chat or held casually in the gateway |
| UJ-002 | Operator in an untrusted channel | Receives a message with injection or policy-violating content | Inbound scan blocks or quarantines before the Triager or executor models consume the text; operator gets a plain-language block notice |
| UJ-003 | Operator delegating risky work | Agent attempts delete, shell, outbound fetch, or other gated action | Approval prompt on Telegram or Mission Control; turn waits until approve/deny or times out safely |
| UJ-004 | Operator mid-incident | Turn feels wrong or scanner noise spikes | Steer, stop, or owner kill-switch halts execution; traces show what was about to run |

**Narrative:**

- **UJ-001 — Trust boundary for secrets:** During onboarding, the operator pairs an egress
  proxy daemon and chooses a secrets backend. Assigned models and integrations work without
  the gateway process holding raw provider keys. Doctor warns when pairing or unlock is broken
  before the first failed turn.
- **UJ-002 — Hostile inbound content:** A group message embeds "ignore prior instructions."
  LLM Guard classifies the inbound text (and selected tool output on rescan) before routing.
  Blocked content lands in a quarantine zone with operator notification—not silently dropped
  without a trail.
- **UJ-003 — Consequential tool gate:** Tier B/C requests a destructive filesystem operation.
  When policy requires human approval, Telegram surfaces approve/deny buttons; Mission Control
  shows the pending tool and arguments. Deny aborts the tool call with an operator-visible reason.
- **UJ-004 — Kill switch under fire:** A long tier-C plan starts looping. The operator sends
  stop/steer from Telegram or halts from Mission Control; the gateway drains the active run
  without leaving orphaned sandbox containers when sweeper policies apply.

## Goals

- **FR-001:** The product shall **scan inbound user-visible text** (and configured tool-output
  paths) for prompt-injection and policy violations **before** the Triager or executor models
  consume that content.
- **FR-002:** When content is blocked, the product shall **quarantine** artifacts and **notify**
  the operator with a plain-language reason—not fail open into the agent loop.
- **FR-003:** The product shall keep **raw provider and integration credentials** out of the
  gateway agent process by resolving secrets through **encrypted backends** and a **paired egress
  proxy** for outbound LLM and vendor calls.
- **FR-004:** The product shall route **risky tool execution** (shell, sandboxed code, skill
  subprocesses when configured) through a **single sandbox subsystem** with operator-configurable
  drivers and resource ceilings—not unconstrained host execution by default.
- **FR-005:** The product shall support **human-in-the-loop approval** for consequential tool
  calls and plan gates when workspace policy or tier requires it, on Telegram, Web UI, and
  Mission Control surfaces.
- **FR-006:** The product shall expose **operator kill switches**: steer/stop during active
  turns, owner-only maintenance commands on Telegram, and configurable scanner or automation
  disable paths that fail closed on high-risk actions when disabled.
- **FR-007:** **Doctor** and **config validate** shall surface broken trust posture—unpaired
  proxy, missing secrets unlock, sandbox driver unavailable—**before** the first consequential
  failure when fixtures cover the misconfiguration.

## Non-Goals

- **Perfect** prompt-injection immunity—defense in depth and operator visibility, not a
  cryptographic guarantee against adaptive attacks.
- Enterprise **multi-tenant RBAC**, SOC2 audit packages, or org-wide IAM—v1 centers a **solo
  operator** workspace with owner gates, not delegated admin roles.
- Silent **auto-approval** of all tool calls to maximize convenience—risk tiers stay
  operator-configurable; consequential paths default to caution.
- A standalone **SIEM** or full incident-response platform—Mission Control shows traces and
  blocks; deep security analytics live in sibling prd-07-mission-control scope.
- Replacing the operator's obligation to curate **who can message the bot** in group channels—
  channel allowlists and pairing remain conversational PRD concerns.

## Experience

- **Happy path:** Operator completes onboarding with paired proxy and secrets backend. Daily
  turns flow through scan → triage → tools. Destructive operations that require approval show
  a clear prompt; approve once and the turn continues with trace evidence.
- **Operator controls:** Security scanner enablement and model slot; sandbox driver and mode;
  tool approval policies; egress proxy pairing; secrets backend choice; Telegram owner commands;
  `.llmignore` quarantine review; optional rescan via agent-initiated guard tool when enabled.
- **Degraded path:** Scanner unavailable → configurable fail-open vs fail-closed per policy,
  never silent for high-risk tools. Unpaired proxy → doctor warning, then blocked outbound LLM
  calls with actionable fix steps. Approval timeout → tool call denied with reason in chat and
  trace. Sandbox driver missing → exec routes error clearly rather than running on host silently.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Known injection fixtures blocked before Triager consumes inbound text | 100% on regression corpus | scanner integration tests |
| KPI-002 | Gateway agent process does not retain resolved provider API keys on default proxy path | Zero key material in gateway memory probes | secrets/proxy fixtures |
| KPI-003 | Destructive tools respect approval policy when enabled | 100% pending until operator decision | tool-approval E2E |
| KPI-004 | Doctor/validate warn on unpaired proxy or secrets unlock failure | ≥95% of fixture misconfigs pre-turn | doctor/validate suites |
| KPI-005 | Operator can stop an active long turn from Telegram or Mission Control | Stop/steer acknowledged within one user action | gateway harness smoke |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-06-secrets | Encrypted backends, logical keys, TTL cache; credentials never in gateway process |
| spec-07-egress-proxy | Paired daemon, outbound LLM/vendor auth injection, session tokens |
| spec-08-sandbox | Tool-execution sandbox drivers, shadow workspace, egress firewall inside namespace |
| spec-09-security-scanner | LLM Guard pipeline, `.llmignore/` quarantine, block-and-notify |
| spec-17-gateway | Turn spine, channel router wiring for scan + tool-approval bridge |
| spec-18-channel-telegram | Owner commands, approval buttons, scanner kill-switch UX on Telegram |
| spec-19-channel-webui | Webchat approval and security copy for blocked content |
| spec-20-voice | Voice path inherits scan and credential boundaries |
| spec-37-openui | Generated UI delivery respects same trust surfaces as web channel |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave; normative acceptance criteria
live in implementing specs, not here.

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
| 0.9 | 2026-07-07 | Scaffolded six-section shell from about-docs pipeline | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full trust/control product prose | MODIFIED prd-03-trust-and-control (structure); traceability aligned to spec-06/07/08/09/17/18/19/20/29 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Default scanner posture when LLM Guard model fails to load—fail open or fail closed for chat-only turns? | Alex | 2026-08-01 | resolved — operator-configurable; high-risk tools remain gated regardless |
| OQ-002 | Should Mission Control expose a unified quarantine inbox for `.llmignore/` blocks? | Alex | 2026-08-01 | resolved — defer UI polish to prd-07-mission-control; v1 ships block-and-notify in channel |
| OQ-003 | Auto-approve repeat approvals for the same tool+target within a session? | Alex | 2026-08-01 | resolved — no session-wide auto-approve in v1; operator must confirm each gated call |
