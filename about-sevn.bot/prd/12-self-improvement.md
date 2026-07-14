---
id: prd-12-self-improvement
kind: prd
title: Self-Improvement — PRD
status: ready
owner: Alex
summary: Operators turn traces and feedback into bounded, eval-gated patch proposals—with
  explicit approval before merge—so prompts and skills improve without silent drift.
last_updated: '2026-07-14'
fingerprint: sha256:b6b6582757fd76c55bfc0be5f46765cebbf119bb8f422676f5e40774240cd753
related: []
sources:
- src/sevn/self_improve/**
parent_prd: prd-00-main
specs:
- spec-33-self-improvement
- spec-17-gateway
- spec-24-dashboard
- spec-19-channel-webui
- spec-18-channel-telegram
- spec-20-voice
- spec-21-executor-tier-cd
- spec-04-tracing
personas:
- operator
prd_profile: ai-native
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-33-self-improvement | draft |
| spec-17-gateway | draft |
| spec-24-dashboard | draft |
| spec-19-channel-webui | draft |
| spec-18-channel-telegram | draft |
| spec-20-voice | draft |
| spec-21-executor-tier-cd | draft |
| spec-04-tracing | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

A self-hosted assistant that never improves becomes stale: Triager prompts drift from real
usage, bundled skills accumulate rough edges, and recurring routing mistakes quietly burn
tokens. Fully automatic self-modification is unsafe—one bad patch can exfiltrate secrets,
wipe workspace memory, or degrade every channel at once.

- **Who:** Daily-driver operators who run sevn long enough to see repeat failure patterns
  and want the harness—not just the model—to get better over time.
- **Pain:** Today, fixing a bad prompt or skill means manual grep, edit, and hope. There is
  no structured loop from "that turn was wrong" to a reviewed, eval-checked patch. Operators
  either ignore drift or take risky ad-hoc edits outside audit trails.
- **Why now:** Tracing, trajectory ingest, golden routing replay, and spec-kit plan stages
  already exist in the codebase—the product contract must make **bounded propose-only**
  improvement, **eval gates**, and **operator approval** explicit before wider rollout.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Operator tuning harness quality | Recurring mis-routes or thumbs-down feedback | Shortlisted turns become a reviewable patch proposal within allowed globs |
| UJ-002 | Operator in observe mode | Wants telemetry before trusting auto-propose | Preset A ingests trajectories and surfaces shortlists without authoring patches |
| UJ-003 | Operator approving change | Improve job reaches plan or patch stage | Reviews diff in Mission Control or Telegram; approve, reject, or abort before merge |
| UJ-004 | Operator during incident | Bad patch or runaway eval spend | Kill switches stop auto-merge and enqueue; last-known-good baseline blocks promotion |

**Narrative:**

- **UJ-001 — Feedback to proposal:** Operator thumbs-down a turn or leaves structured
  feedback. Nightly ingest (and optional per-turn ingest) builds trajectory facts; the sampler
  shortlists candidates with coverage caps across channel, intent, and tier. Preset B/C runs
  the patch author against allowed prompt/skill globs only; the operator sees a unified diff,
  not a silent file write.
- **UJ-002 — Observe first:** Operator enables self-improve with preset A. Trajectory ingest
  and shortlist allocation run; Mission Control shows job history without proposer spend.
  When comfortable, they step up to preset B for propose-only jobs.
- **UJ-003 — Approval gate:** With spec-kit plan stage enabled, the operator reviews a plan
  before patch author runs; `plan_approved` must exist when HITL is required. Patch merge
  waits on explicit approval unless preset C auto-merge is enabled **and** eval passed.
- **UJ-004 — Fail-safe:** Operator sets incident env or dashboard toggle to disable
  auto-merge or the whole improve loop. Eval may still run for diagnosis; promotion paths fail
  closed.

## Goals

- **FR-001:** The product shall provide an **opt-in self-improve loop** (default off) that
  ingests traces, session artefacts, and explicit feedback into trajectory facts for later
  sampling—without modifying operator files until a gated job completes successfully.
- **FR-002:** The product shall support **presets A / B / C**: A observe-only (sampler +
  shortlist), B propose-only patches, C propose with optional auto-merge after eval pass.
- **FR-003:** Patch proposals shall be **bounded by allow/deny globs** defaulting to
  workspace prompts and skills; dependency, config, and LCM memory changes shall remain
  off unless explicitly allowed.
- **FR-004:** The product shall run an **eval stage** (golden routing replay and/or Docker
  eval graph) before promotion; preset C auto-merge shall fail closed when eval did not pass.
- **FR-005:** Operators shall **approve or reject** patches and optional spec-kit plans via
  Mission Control and channel surfaces; `require_human_approval` shall force review even when
  auto-merge is configured.
- **FR-006:** The product shall expose **kill switches** (env and config) to disable
  auto-merge or the entire improve subsystem during incidents while preserving audit telemetry.
- **FR-007:** Improve jobs shall respect **daily token and git-operation budgets** so eval
  and proposer spend cannot silently exhaust operator limits.
- **FR-008:** Recalled **lessons** from prior improve cycles shall inform later proposals
  without bypassing glob policy or approval gates.

## Non-Goals

- Fully autonomous self-modification without operator review or passing eval (see prd-00-main
  non-goals).
- Editing sevn core source, gateway code, or secrets stores through the improve loop—patches
  target operator workspace harness artefacts unless a future PRD expands scope.
- Replacing external CI/CD or GitHub Actions for repo-wide releases—improve hub integration
  may open PRs; it does not subsume the project's main merge gate.
- Exporting operator trajectories for third-party model training by default—export remains
  opt-in with PII controls.
- Auto-tuning model provider slots or billing—cost surfaces live under prd-05-cost-and-providers.

## Experience

- **Happy path (preset B):** Operator enables self-improve, sets preset B, and optionally
  enables spec-kit plan stage. Cron or manual job enqueues; Mission Control Improve panel
  shows state transitions. Operator reviews plan (if enabled) then patch diff; approves;
  eval runs; on pass, changes land in workspace prompts/skills with audit log entry. Telegram
  notifies on key transitions when configured.
- **Happy path (preset A):** Same ingest and shortlist UX without proposer LLM spend—useful
  for calibration before trusting proposals.
- **Operator controls:** `self_improve.enabled`, preset, allow/deny globs, `require_human_approval`,
  `auto_merge_enabled`, eval network mode, token budget, spec-kit HITL flags, incident env
  overrides, and abort job action.
- **Degraded path:** Eval failure → job blocked from promotion; operator sees report deltas vs
  last-known-good. Budget exhausted → proposer skips with clear reason. Kill switch active →
  enqueue refused; in-flight jobs may abort. Low-confidence or out-of-scope patch → rejected
  by glob/policy checks before operator review.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Unapproved patches merged to workspace | 0 when `require_human_approval` is true | improve audit log, job store |
| KPI-002 | Preset C auto-merge attempts without eval pass | 0 | facade eval gate tests |
| KPI-003 | Patch touches outside allowed globs | 0 on policy-enforced paths | patch author fixtures |
| KPI-004 | Operator can abort in-flight improve job from MC or CLI | 100% on supported states | MC E2E, facade tests |
| KPI-005 | Golden routing replay regression caught pre-merge | ≥ 95% of fixture regressions block promotion | eval graph, replay suite |
| KPI-006 | Trajectory ingest reconciliation after cron backfill | ≥ 90% of sampled turns ingested within 24h | ingest metrics, doctor |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-33-self-improvement | Trajectory ingest, sampler, proposer, eval graph, jobs, lessons, spec-kit stage |
| spec-17-gateway | Turn hooks scheduling ingest; improve job delegation from gateway |
| spec-24-dashboard | Mission Control Improve panel, job WS events, approval UX |
| spec-19-channel-webui | Web chat feedback mirroring into improve feedback events |
| spec-18-channel-telegram | Owner-facing improve job copy and approval affordances |
| spec-20-voice | Voice turns included in trajectory coverage caps |
| spec-21-executor-tier-cd | Tier C/D turns as sampler sources with tier coverage limits |
| spec-04-tracing | Trace export feeding trajectory ingest and eval replay |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new improve surfaces.

### Stable ID Index

| Prefix | Meaning | Example |
| --- | --- | --- |
| UJ- | User journey | UJ-001 |
| FR- | Product functional requirement | FR-001 |
| KPI- | Success metric | KPI-001 |
| RISK- | Product risk | RISK-001 |
| OQ- | Open question | OQ-001 |

### Change Log

| Version | Date | Summary | Spec deltas |
| --- | --- | --- | --- |
| 0.9 | 2026-06-19 | Legacy six-section scaffold | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave ai-native PRD; eval, degradation, approval gates | MODIFIED prd-12-self-improvement (structure); traceability aligned to spec-33 and channel specs |

## AI Behavior & Eval

**AI hypothesis:** We believe that if the system proposes **small, glob-bounded** prompt and
skill edits from **shortlisted failure turns**, operators will ship harness fixes faster
because each change is paired with replay eval and an explicit approval step—reducing silent
drift and catastrophic wide edits.

**Eval ownership:** Operator (primary) · cadence: per improve job and weekly golden replay
smoke · re-eval triggers: prompt/skill patch merged, preset change, model slot change,
bundled skill bundle update.

| Eval | Good output | Bad output | Metric | Target |
| --- | --- | --- | --- | --- |
| Golden routing replay | Same tier/intent routing as baseline on fixture corpus | Mis-route or tier collapse on known turns | routing accuracy vs LKG | ≥ baseline (no regression) |
| Patch quality review | Actionable diff within allowed globs | Deletes skill tree or edits config/secrets | human review pass | ≥ 90% approved on sample |
| Plan HITL (spec-kit) | Plan matches shortlist root cause | Plan scopes repo-wide refactor | operator plan approval rate | ≥ 80% approved when enabled |
| Proposer abstention | Skips when budget or policy blocks | Authors patch outside globs | policy rejection rate | 100% blocked pre-write |

**Golden dataset:** Golden routing fixture exists in-repo; owner: operator · refresh: when
routing taxonomy or triage prompts change materially · size: bounded replay corpus (not full
production logs).

**Confidence thresholds (product-level):**

| Band | Threshold | Autonomy | Human checkpoint |
| --- | --- | --- | --- |
| High | Eval pass + within globs + preset B | Propose only; no merge | Operator approves merge |
| Medium | Eval pass + preset C + auto_merge enabled | May auto-merge workspace patch | Audit log + MC notification |
| Low | Eval fail, budget exhausted, or policy reject | No promotion | Operator inspects report; manual fix |

## Failure & Degradation

| Failure | Detection | User-facing behavior | Rollback / owner |
| --- | --- | --- | --- |
| Eval regression vs last-known-good | eval_report.json deltas | Job blocked; MC shows failing segment | Operator; revert patch bundle |
| Patch violates glob/policy | pre-write reject_patch_* | Job fails with scope message; no file touch | Operator adjusts allowlist or rejects job |
| Proposer token budget exhausted | daily ledger | Proposer stage skipped; job queued for next window | Operator raises budget or waits |
| Preset C auto-merge without pass | ensure_preset_c_auto_merge_allowed | Runtime block; clear error in job log | Operator fixes eval or disables auto-merge |
| Runaway job / bad proposal | operator abort or kill switch | Job aborted; auto-merge disabled globally if env set | Operator; SEVN_DISABLE_AUTO_MERGE |
| Trajectory ingest lag | reconciliation metric low | Shortlist under-represents recent failures | Operator checks cron; manual ingest trigger |

**RISK register (product-level):**

| ID | Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- | --- |
| RISK-001 | Destructive self-edit wipes skills or prompts | H | L | Glob allowlist, diff review, eval gate, default preset A |
| RISK-002 | Auto-merge promotes regressed routing | H | M | LKG baseline, golden replay, preset C eval requirement |
| RISK-003 | Eval spend exhausts daily token budget | M | M | token_budget_daily, docker/offline modes |
| RISK-004 | Feedback or trajectories leak PII into export | H | L | export opt-in, allow_user_lines false by default |
| RISK-005 | Operator confusion on preset semantics | M | M | MC copy, doctor hints, default off + preset A |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should preset C ever auto-merge without a human approval step when eval passes? | Alex | 2026-08-01 | resolved — allowed only when operator explicitly sets `auto_merge_enabled` and eval passed; `require_human_approval` overrides |
| OQ-002 | Should improve jobs ever modify LCM memory files? | Alex | 2026-08-01 | resolved — default deny via `allow_lcm_memory_changes=false`; prompts/skills only unless operator opts in |
| OQ-003 | Is trajectory export for external training in v1 scope? | Alex | 2026-08-01 | resolved — defer; export scaffold stays opt-in with PII gates, not a product promise |
