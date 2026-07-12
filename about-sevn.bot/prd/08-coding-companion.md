---
id: prd-08-coding-companion
kind: prd
title: Coding Companion — PRD
status: ready
owner: Alex
summary: A daily-driver AI must help you code—from repo Q&A and orientation through
  tier B quick fixes to tier C/D plans, workspace mirror, and PR workflows.
last_updated: '2026-07-12'
fingerprint: sha256:5a97e9841a414ba088717f40956b00e55c59c77add891779e0555da9bb2c9f93
related: []
sources:
- src/sevn/code_understanding/**
parent_prd: prd-00-main
depends_on: []
build_phase: null
interfaces: []
specs:
- spec-21-executor-tier-cd
- spec-26-claude-agent
- spec-28-code-understanding
personas:
- operator
prd_profile: standard
---

## Problem & Motivation

A daily-driver AI that cannot help you code is half a daily driver. *Helping you code*
covers a long ramp: a one-line "where is X defined?" in Telegram, a multi-file fix with
tests from the laptop, a planned refactor that needs approval gates, and eventually a pull
request the operator can review—not a pasted diff in chat.

Consumer assistants treat code as generic text: no durable repo context, no workspace
mirror, no orientation indexes, and no path from "explain this module" to "open a PR."
Self-hosted operators who live in sevn for everything else still bounce to a separate IDE
agent for serious work.

- **Who:** A single-operator developer who already runs sevn as a daily driver and wants
  the same assistant to orient in their repos, answer code questions, and carry multi-step
  coding work when complexity warrants tier C/D.
- **Pain:** Without code orientation, every turn re-discovers layout from scratch—slow,
  token-heavy, and error-prone. Without tier-appropriate execution, either everything is
  a shallow tool loop (unsafe for big changes) or every question triggers a heavyweight
  plan (too slow for quick lookups). Without a workspace mirror, the bot cannot reliably
  read the operator's sevn.bot checkout or project tree the way the operator expects.
- **Why now:** The code-understanding stack, workspace `source_code/` mirror, tier B/C/D
  executors, and coding-agent hooks exist in brownfield form—this PRD states the **product
  contract** for code-aware help across that ramp.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Operator on mobile | Asks "where is triage routing?" about their mirrored repo | Gets a grounded answer using orientation indexes without pasting files manually |
| UJ-002 | Operator at desk | Wants a small fix—edit one module, run tests | Tier B executor completes via file tools and sandbox with visible progress in chat |
| UJ-003 | Operator planning work | Requests a multi-step feature or refactor | Triager routes to tier C/D; operator sees plan, approves or steers before wide edits |
| UJ-004 | Operator shipping code | Asks to prepare a branch and open a PR | Goal completes with reviewable artifacts and GitHub integration when enabled |
| UJ-005 | Operator in a coding session | Opens or binds a dedicated coding topic/thread | Long-running codegen stays scoped—history, artifacts, and status separate from casual chat |

**Narrative:**

- **UJ-001 — Repo Q&A:** Operator messages from Telegram while away from the IDE. The
  assistant uses orientation context (indexes, graph summaries) over the workspace mirror
  to answer where symbols live and how modules connect—plain language, not a raw dump.
- **UJ-002 — Quick fix (tier B):** Operator asks for a targeted change. Tier B runs a
  tool loop with read/search/edit and optional sandbox verification; replies stream in the
  same conversational surface with steer/cancel per `prd-01-conversational-experience`.
- **UJ-003 — Planned codegen (tier C/D):** Operator describes a larger change. Triager
  classifies complexity C or D; executor presents a structured plan, waits for approval
  when configured, then executes with harness discipline and artifact retention.
- **UJ-004 — To PR:** After edits, operator asks to commit conventionally and open a PR.
  Bundled GitHub skills and tier C/D artifact vault give a reviewable trail—not only chat
  text.
- **UJ-005 — Dedicated coding topic:** Operator routes coding traffic to a bound Telegram
  topic or agent session so ALRCA-style goals, run artifacts, and Mission Control panels
  stay inspectable without polluting the main daily-driver thread.

## Goals

- **FR-001:** The product shall provide **code orientation** for mirrored repos—indexes,
  graph summaries, and triager-facing context—so repo questions do not start from zero
  each turn.
- **FR-002:** The workspace shall expose a **read-only source mirror** refreshed on gateway
  restart so executors and tier B tools can read operator checkout layout consistently.
- **FR-003:** **Tier B** shall handle low-complexity coding tasks (lookup, small edits,
  single-file fixes) in the normal conversational turn spine without forcing a full plan
  gate every time.
- **FR-004:** **Tier C/D** shall handle higher-complexity coding work with structured
  planning, optional operator approval, verifiers, and retained run artifacts when
  triage classifies complexity accordingly.
- **FR-005:** Operators shall be able to **bind dedicated coding sessions** (Telegram
  topic or registered coding agent) so long codegen runs are scoped, resumable, and
  inspectable separately from casual chat.
- **FR-006:** Coding workflows shall **integrate with GitHub** (branch, commit message
  conventions, PR open) when the operator enables bundled GitHub skills—never silent
  push without explicit intent.
- **FR-007:** **Doctor and bootstrap** shall surface stale or missing orientation indexes
  with actionable refresh hints before the operator discovers failure mid-turn.

## Non-Goals

- Replacing **Cursor, Claude Code, or a full IDE** as the primary editing surface—sevn
  augments daily-driver chat with code capability; it does not need to win every IDE feature.
- **Fully autonomous merge** to main without operator review—PR workflows stop at open/review
  unless the operator explicitly approves further steps.
- **Multi-tenant code review** or org-wide RBAC over repositories—v1 centers the single
  operator workspace and their mirrored checkout.
- Normative **EARS acceptance criteria** or module-level design—those live in implementing
  specs (`spec-28-code-understanding`, `spec-21-executor-tier-cd`, `spec-26-claude-agent`).
- Shipping every optional orientation backend (Memgraph CGR, roam-code, etc.) as mandatory—
  operators enable subsets; doctor reports what is missing.

## Experience

- **Happy path (Q&A):** Operator asks about mirrored repo structure. Reply cites orientation
  context in readable prose; if indexes are stale, a short nudge explains how to refresh
  without blocking a best-effort answer.
- **Happy path (tier B fix):** Operator describes a small change. Turn streams progress;
  file edits land under workspace conventions; sandbox or test hints appear when configured.
  Operator can steer or cancel mid-turn.
- **Happy path (tier C/D):** Operator requests a feature. Plan appears before wide edits
  when approval is required; after acceptance, executor runs with visible checkpoints and
  artifacts stored for Mission Control inspection.
- **Happy path (coding topic):** Operator opens or selects a bound coding topic. Subsequent
  codegen messages route to the registered agent/session; run status and artifacts remain
  scoped to that thread.
- **Operator controls:** Enable/disable orientation backends in config; triage complexity
  thresholds; tier C/D approval gates; GitHub skill availability; coding-agent bindings
  and topic routing in Telegram.
- **Degraded path:** Mirror empty → clear message to set repo path and restart gateway.
  Orientation tool unavailable → fall back to direct file read/search with explicit limitation.
  Tier C/D rejected plan → executor stops without silent edits. GitHub skill disabled →
  local edits complete but PR step explains what is missing.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Repo Q&A turns use orientation context when mirror and indexes are healthy | ≥90% of code-intent turns attach orientation block | triage/orientation integration tests |
| KPI-002 | Tier B completes single-file fix without spurious tier C escalation | ≥85% on fixture "small edit" prompts | triage + executor fixtures |
| KPI-003 | Tier C/D plan shown before bulk edits when approval required | 100% on approval-gated configs | harness discipline tests |
| KPI-004 | Doctor warns on missing/stale MYCODE or Graphify before first failed code turn | ≥95% of misconfigurations caught pre-turn | doctor/bootstrap fixtures |
| KPI-005 | Coding-topic-bound session retains artifacts inspectable in Mission Control | Operator can list run artifacts for bound session | MC/manual checklist, vault tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-28-code-understanding | MYCODE, Graphify, code-review-graph MCP, CGR, roam-code—orientation stack, triager prefix, doctor checks |
| spec-21-executor-tier-cd | Tier C/D planned execution, approval gates, ALRCA loop worker, verifiers, artifact vault for coding goals |
| spec-26-claude-agent | Dedicated coding-agent registry, Telegram topic bindings, legacy migration—**rejected** for v0.0.2; brownfield hooks retained for future waves |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new coding-companion
features.

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
| 0.9 | 2026-07-07 | Legacy six-section scaffold with summary only | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full coding companion product contract (orientation, tier B/C/D, workspace, PRs) | MODIFIED prd-08-coding-companion (structure); traceability aligned to spec-28/21/26 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should spec-26-claude-agent remain in implementing specs while status is rejected? | Alex | 2026-07-08 | resolved — keep in traceability with explicit rejected note until revive or REMOVED delta |
| OQ-002 | Default coding traffic: always main session vs auto-bind when complexity ≥ C? | Alex | 2026-08-01 | resolved — main session for B and casual Q&A; operator opt-in topic binding for long C/D runs |
| OQ-003 | Mandatory orientation backend for v1—Graphify only or MYCODE+Graphify minimum? | Alex | 2026-08-01 | resolved — MYCODE scan + Graphify when checkout present; other backends optional with doctor hints |
