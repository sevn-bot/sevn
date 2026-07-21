---
id: prd-04-getting-things-done
kind: prd
title: Getting Things Done — PRD
status: ready
owner: Alex
summary: A general-purpose AI assistant earns its keep by doing things—answering questions,
  fetching pages, opening PRs, and acting on the operator's behalf via tools, skills,
  and tiered executors.
last_updated: '2026-07-21'
fingerprint: sha256:13314781f75a75a93d7874ddd46b318635a3ef07b8acb2b905865dc7330d3f96
related:
- prd-03-trust-and-control
- prd-08-coding-companion
- prd-11-automation-and-triggers
- prd-13-extensibility
sources:
- src/sevn/agent/**
- src/sevn/tools/**
parent_prd: prd-00-main
specs:
- spec-10-schema-ontology
- spec-11-tools-registry
- spec-12-skills-system
- spec-13-rlm-triager
- spec-14-executor-tier-b
- spec-16-harness-discipline
- spec-21-executor-tier-cd
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-20-voice
- spec-37-openui
- spec-36-sub-agents
personas:
- operator
prd_profile: standard
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-10-schema-ontology | draft |
| spec-11-tools-registry | draft |
| spec-12-skills-system | draft |
| spec-13-rlm-triager | draft |
| spec-14-executor-tier-b | draft |
| spec-16-harness-discipline | draft |
| spec-21-executor-tier-cd | draft |
| spec-17-gateway | draft |
| spec-18-channel-telegram | draft |
| spec-19-channel-webui | draft |
| spec-20-voice | draft |
| spec-37-openui | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

Chat-only assistants stop at advice. A daily-driver personal AI has to **finish work** on the
operator's behalf: answer a quick question, fetch a page, open a PR, schedule a cron, send a
Telegram message, summarise a long thread, or run a multi-step workflow without the operator
becoming the integration layer.

- **Who:** Self-hosted operators who already talk to sevn from Telegram, Web UI, or voice and
  expect the bot to **act**, not only opine—within the trust boundaries in prd-03-trust-and-control.
- **Pain:** Without a coherent tools/skills surface and tiered executors, every "do this for me"
  request either fails ("I can't access that") or turns into a fragile one-off prompt chain the
  operator cannot steer, cancel, or audit afterward.
- **Why now:** The gateway, triager, tool registry, and executor harnesses are implemented enough
  that the **product contract** for *getting things done*—routing, approvals, mid-flight control,
  and delivery back to the channel—should be explicit before adding more integrations or automation.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Operator on the go | Asks a quick factual or conversational question | Gets a direct reply without unnecessary tool fanfare (tier A or light tier B) |
| UJ-002 | Operator delegating a task | "Fetch this page", "search my notes", "read that file" | Bot uses tools/skills and returns a concise result in the same thread |
| UJ-003 | Operator with a multi-step goal | "Refactor X", "open a PR for Y", "run this plan across the repo" | Triager routes to planned-work executor; operator approves plan when required, then sees progress |
| UJ-004 | Operator mid-flight | Long run is wrong, slow, or no longer needed | Steers with a follow-up message or cancels; harness stops work and reports state clearly |
| UJ-005 | Power operator | Enables bundled or custom skills and optional MCP servers | Triager can name relevant skills; executors load only what the turn needs |

**Narrative:**

- **UJ-001 — Quick answer:** A greeting or simple question gets a fast tier-A style reply or a
  short tier-B turn without spinning up a full planner—the operator is not forced through plan
  approval for trivia.
- **UJ-002 — Single-shot action:** The operator asks for a page summary or file lookup. The bot
  picks tools, respects sandbox and scanner gates from prd-03-trust-and-control, and posts the
  outcome with enough context to continue the thread.
- **UJ-003 — Planned work:** A complex request produces a structured plan surfaced in Telegram
  (inline approve/reject) or Mission Control. After approval, tier C/D execution runs with
  checkpoints; artifacts and traces remain inspectable afterward.
- **UJ-004 — Steer and cancel:** During a long tier-B or tier-C/D run, the operator sends a
  correction or hits cancel. The gateway honours the signal, finalises partial work honestly, and
  does not leave a silent zombie run.
- **UJ-005 — Skills and integrations:** The operator installs or enables skills in the workspace.
  The triager references skill **names** for routing; executors load instructions and tool subsets
  lazily. MCP and external integrations stay **opt-in**, not on by default.

## Goals

- **FR-001:** Each inbound message shall be **classified and routed** (intent, complexity,
  skills, tools) through a dedicated triager step before executor dispatch—no monolithic
  one-size-fits-all agent for every turn.
- **FR-002:** The product shall expose a **unified tools registry** so every executor tier calls
  the same tool implementations with consistent envelopes, spill handling, and permission checks.
- **FR-003:** The product shall support **workspace skills**—discovered, validated, and indexed
  for routing—so operators can extend capability without forking core gateway code.
- **FR-004:** **Tier B** shall be the default "do work" path for moderate-complexity turns: a
  conversational agent loop with narrowed tool/skill exposure appropriate to the triage result.
- **FR-005:** **Tier C/D** shall handle **planned multi-step work** with structured plans and
  **operator plan approval** when policy requires it—especially for consequential or repo-wide
  changes.
- **FR-006:** **Harness discipline** shall apply across tiers: active-run snapshots, boot-resume
  prompts after restart, and **steer/cancel** semantics the operator can rely on mid-flight.
- **FR-007:** Task outcomes shall be **delivered on the originating channel** (Telegram, Web UI,
  voice, or generated UI surfaces) with actionable follow-ups where the channel supports them
  (e.g. plan approval buttons, file links, OpenUI panels).
- **FR-008:** Optional **MCP and external integrations** shall remain operator-enabled opt-ins;
  the default install path must not silently widen the attack surface.
- **FR-009:** Bundled **Proton** management (`proton-management` / `proton-cli`) shall support
  Pass vault/item read and write journeys with correct module-mode `--profile` argv ordering and
  mocked behavioral coverage for `pass vaults` / `items` / `secrets` (including create +
  `secrets get` → stdout credential emit), plus Mail CLI (`messages` search/read/send/trash/
  delete/move and `labels list`), `mail_list`/`mail_read` dry-run scripts, stdin secret
  resolution, SRP HV retry / `PROTON_HV_TOKEN`, `run_proton_cli_async` argv/timeout, Drive
  CLI (`items` list/upload/download/trash/delete, `folders create`, `trash` list/restore/empty)
  with decrypt/link failures surfaced at warning, Calendar/Contacts
  (`events` list/get/delete, `contacts` list/get/create/delete, card decrypt) with decrypt drops
  logged, unrecognized card types raised, and empty create `Responses` failing loudly, and
  polish CLI (`status` / `api` runnable without a nested subcommand, legacy `session.json`
  fallback on `status`, `settings set <key>` rejecting a missing value before auth), and
  deferred surfaces (`events` create/respond, `contacts` groups/pin-key, mail `--attach` +
  attachments list/download, pinned-key recipient classification, HV-helper crash logging)
  (live Proton Calendar/Contacts/Drive/RSVP/attachment/HV-webview E2E deferred without credentials).
- **FR-010:** Bundled **Google Workspace** (`google-workspace`) shall honour
  `skills.google_workspace.prefer_gws` (§3.3): prefer the `gws` CLI via `use_gws_backend` /
  `run_gws` when on PATH, with an observable Python-client fallback and a behavioral
  `gws_bridge` token-env test.

## Non-Goals

- **Unbounded autonomy** without approvals, sandboxing, or scanner gates—consequential action
  stays under prd-03-trust-and-control, not "YOLO agent."
- **Replacing a full IDE or CI system** for all software work—deep coding companion flows live in
  prd-08-coding-companion; this PRD covers the general task-completion spine.
- **Event-driven automation** (cron, webhooks, notify-only triggers)—see prd-11-automation-and-triggers.
- **Building every third-party integration in core**—org-specific glue and plugin hooks are
  prd-13-extensibility; v1 ships bundled tools/skills plus opt-in extension points.
- **Hiding complexity tiers from observability**—operators may not need tier labels in every chat
  bubble, but Mission Control and traces must remain explainable.

## Experience

- **Happy path (quick):** Operator sends a question in Telegram or Web UI; bot replies in-thread
  within seconds. No plan gate, no unexplained tool spam.
- **Happy path (action):** Operator asks for a concrete task; bot announces progress proportionally
  (channel-appropriate), uses tools behind trust gates, and returns a readable summary plus
  attachments or links when useful.
- **Happy path (planned):** Operator requests multi-step work; bot presents a plan with approve /
  reject affordances on Telegram or equivalent in Web UI. Approved plans execute with visible
  milestones; rejection returns a clear reason without partial silent side effects.
- **Parallel sub-agents:** With `gateway.queue_mode: multi`, unrelated follow-up
  messages while a session is busy can spawn a new tier-B sub-agent instead of only
  steering or cancelling the in-flight run (spec-36-sub-agents).
- **Media via specialist:** Image/video/music generation routes through the
  `media_generator` level-2 specialist and `media_generation` bundled skill.
- **Social monitoring via specialist:** Browser-first monitoring and interaction
  across six platforms (`x`, `facebook`, `instagram`, `linkedin`, `reddit`,
  `tiktok`) routes through the `social_media_manager` level-2 specialist and
  bundled skill. Operators configure per-platform default medium under
  `skills.social_media_manager` from Telegram **`/config → Skills → Social Media
  Manager`**. **Browser (CDP `browser` tool, `action=social`)** is always
  available; **TwexAPI** is an optional extra on **X only** when enabled and
  keyed. Specialists remain opt-in — `subagents.specialists` defaults empty.
- **Operator controls:** Enable/disable tools and skills; approve or reject plans; steer or
  cancel active runs; kill running sub-agents from Mission Control, Telegram
  `/config → Sub-agents → Running`, or `sevn subagents kill` (view limits and live
  counts on the same surfaces); opt into MCP servers and coding-agent skills explicitly.
- **Degraded path:** Tool failure → structured error in-thread, not a stack trace dump. Plan
  timeout or rejection → execution does not proceed. Triager unavailable → honest failure message
  and doctor signal, not a random tier guess. Cancel → run stops and channel state recovers.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Tier-B fixture turns complete with operator-visible outcome (no silent empty reply) | ≥ 95% on curated happy-path set | agent integration tests |
| KPI-002 | Plan approval flow: presented plan → operator approve → execution starts | 100% on Telegram and Web UI smoke paths | E2E fixtures, manual checklist |
| KPI-003 | Steer/cancel during active tier-B or tier-C/D run stops work and finalises channel state | ≤ 5 s to acknowledged cancel on reference hardware | gateway harness tests |
| KPI-004 | Triager routes complexity-A/B/C/D labels consistently on frozen routing fixture set | ≥ 90% agreement with labeled corpus | triager eval fixtures |
| KPI-005 | Enabled skills appear in triage output and narrow executor exposure (no full skill dump every turn) | Directional reduction vs load-all baseline | trace sampling, MC inspection |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-10-schema-ontology | TriageResult ontology, complexity and intent enums, shared labels for dispatch |
| spec-11-tools-registry | Layer-3 tool callables, framework adapters, session-scoped ToolSet |
| spec-12-skills-system | Workspace skill discovery, validation, indexing, and routing names |
| spec-13-rlm-triager | Tool-less triager generation step consumed by tier A/B/C/D dispatch |
| spec-14-executor-tier-b | Default pydantic-ai executor loop for complexity B "do work" turns |
| spec-16-harness-discipline | Cross-tier invariants, ActiveRunSnapshot, boot-resume, steer/cancel |
| spec-21-executor-tier-cd | Planned-work executor, PlanGate approval, sandboxed multi-step backends |
| spec-17-gateway | Turn dispatcher, session queue, steer/cancel integration with executors |
| spec-18-channel-telegram | Inbound/outbound Telegram delivery, plan approval inline keyboards |
| spec-19-channel-webui | WebSocket chat and session continuity for task outcomes |
| spec-20-voice | Voice ingress/egress hooks for spoken task requests and replies |
| spec-37-openui | Structured HTML panels when a text reply is not enough for the outcome |
| spec-36-sub-agents | Level-1/level-2 sub-agents, `multi` queue, specialists, kill surfaces |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new executor or tool
surfaces.

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
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave standard; expanded tools/skills/executor product contract | MODIFIED prd-04-getting-things-done (structure); traceability aligned to spec-10–21 and delivery specs |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should every channel surface show complexity tier (A/B/C/D) inline, or only in traces/Mission Control? | Alex | 2026-08-01 | resolved — traces and Mission Control for v1; chat bubbles stay outcome-focused |
| OQ-002 | Default stance on MCP servers at first onboarding—prompted opt-in vs disabled until config? | Alex | 2026-08-01 | resolved — disabled until operator enables; aligns with prd-13-extensibility |
| OQ-003 | When triager and operator disagree on complexity, allow manual tier override per message? | Alex | 2026-08-01 | resolved — defer explicit override UI; steer/cancel plus config knobs suffice for v1 |
