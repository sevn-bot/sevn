---
id: prd-02-personality-and-memory
kind: prd
title: Personality & Memory — PRD
status: ready
owner: Alex
summary: Operators need a bot that remembers who they are, keeps a stable voice across
  sessions, and surfaces controls when memory drifts or recalls wrong facts.
last_updated: '2026-07-12'
fingerprint: sha256:210a42748c1bfeebeabbfdf106fe758bf396797d2dabef09e51886ca62ec9c06
related: []
sources:
- src/sevn/memory/**
- src/sevn/lcm/**
parent_prd: prd-00-main
depends_on: []
build_phase: null
interfaces: []
specs:
- spec-15-memory-lcm
- spec-31-memory-dreaming
- spec-32-memory-honcho
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-20-voice
- spec-21-executor-tier-cd
- spec-29-openui
personas:
- operator
prd_profile: ai-native
---

## Problem & Motivation

A general-purpose AI assistant that forgets you between sessions is a stranger every
morning. The cost shows up in three places: the operator re-explains who they are,
the bot's tone snaps in and out of character, and long threads lose the thread when
context windows fill up.

- **Who:** Daily-driver operators who treat sevn as a personal assistant across
  Telegram, web chat, and voice—not a disposable chat tab.
- **Pain:** Consumer assistants reset personality and facts every session. Even
  self-hosted bots without deliberate memory force the operator to repeat preferences,
  re-teach boundaries, and manually paste context back in. When memory *does* exist,
  wrong recall or stale facts erode trust faster than no memory at all.
- **Why now:** sevn already stores lossless conversation history (LCM), workspace
  persona files (`SOUL.md`, `USER.md`, `MEMORY.md`), optional dreaming consolidation,
  and Honcho-style profile inference—this PRD makes the **product contract** for
  continuity, personality stability, and safe degradation explicit.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | New operator | First Telegram or web session | Bootstrap captures name, style, and boundaries into persona files; next session feels like the same bot |
| UJ-002 | Returning operator | Opens chat after days away | Bot greets with remembered preferences, recent context, and consistent tone—no re-introduction ritual |
| UJ-003 | Operator editing persona | Changes `SOUL.md` or `USER.md` in Mission Control or on disk | `personality_version` bumps; Triager cache invalidates; next turn reflects the edit |
| UJ-004 | Operator correcting memory | Bot cites a wrong or stale fact | Operator can deny topic, edit `USER.md`/`MEMORY.md`, or roll back dreaming batch; bot abstains or re-asks |
| UJ-005 | Long-session operator | Thread exceeds context budget | LCM compaction preserves searchable history; assembler still surfaces recent tail plus summaries |

**Narrative:**

- **UJ-001 — First run:** `BOOTSTRAP.md` (or placeholder `USER.md`) guides a short
  onboarding conversation. Answers land in `USER.md`, `SOUL.md`, and `IDENTITY.md`.
  The operator never hand-edits YAML to "install" a personality.
- **UJ-002 — Continuity:** A Monday morning Telegram message picks up Friday's project
  context because LCM retained the thread and `MEMORY.md` holds durable facts. Tone
  matches `SOUL.md` whether the turn routes through tier B or C.
- **UJ-004 — Wrong recall:** Honcho or dreaming promoted a stale preference. Operator
  thumbs-down or edits the file; deny-topic controls block re-injection until corrected.
  The bot acknowledges uncertainty rather than doubling down.

## Goals

- **FR-001:** The product shall inject workspace persona files (`SOUL.md`, `USER.md`,
  `IDENTITY.md`, `MEMORY.md`) into every qualifying agent turn so voice and operator
  context are consistent across channels.
- **FR-002:** The product shall persist **lossless** conversation history (LCM) per
  workspace session so operators can resume threads without re-pasting transcripts.
- **FR-003:** The product shall **compact** long sessions via summarisation without
  deleting source rows, assembling context from fresh tail plus newest-first summaries.
- **FR-004:** Operators shall edit persona and memory files via workspace files,
  Mission Control persona editor, Telegram `/config` surfaces, and onboarding wizard—
  with `personality_version` bumping on substantive edits.
- **FR-005:** The product shall offer **optional dreaming** consolidation that
  promotes scored facts into `MEMORY.md` on a configurable cadence, with operator
  review and rollback paths.
- **FR-006:** The product shall offer **optional Honcho-style** inferred profile
  accumulation (preferences stated in chat) without requiring manual `USER.md` edits
  for every drift—opt-in, throttle-gated, and operator-overridable.
- **FR-007:** When memory confidence is low or a fact is denied, the product shall
  **abstain or ask** rather than assert stale or invented recall.
- **FR-008:** Cross-channel turns (Telegram, web UI, voice, tier C/D executors) shall
  share the same workspace memory and persona version tokens.

## Non-Goals

- Replacing the **Second Brain** wiki/knowledge-base layer (`prd-09-knowledge-base`)—
  `MEMORY.md` and LCM are operator/session memory, not curated research corpora.
- Fully autonomous memory writes without operator visibility—dreaming auto-promote
  and Honcho inference remain bounded and reversible.
- Multi-user household profiles or per-contact persona splits in v1 (single-operator
  workspace assumption).
- Perfect factual recall—product targets **useful continuity** with explicit
  correction paths, not zero-hallucination guarantees.
- Embedding/RAG over arbitrary operator files beyond the defined persona/memory
  assembly contract.

## Experience

- **Happy path (returning operator):** Open Telegram or web chat; bot uses remembered
  name, tone from `SOUL.md`, and recent LCM context. Long threads stay coherent via
  compaction summaries. Voice turns inherit the same persona injection.
- **Happy path (persona edit):** Operator updates `SOUL.md` in Mission Control;
  next message reflects new boundaries. No gateway restart required.
- **Happy path (dreaming):** Nightly consolidation proposes `MEMORY.md` lines;
  operator reviews pending batch in CLI or Mission Control; promote or rollback.
- **Operator controls:** Edit persona files; enable/disable dreaming and Honcho;
  deny topics; roll back last dreaming batch; bootstrap wizard for first-run capture.
- **Degraded path (memory drift):** Bot hedges or asks when recall signal is weak;
  operator sees correction affordances (edit file, deny topic, thumbs feedback).
  Detail in Failure & Degradation.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Returning sessions load persona files before first agent turn | 100% on happy path | gateway integration tests |
| KPI-002 | `personality_version` bumps within one turn after persona file edit | ≥99% | LCM/user-model throttle tests |
| KPI-003 | LCM assembler includes fresh tail + summaries under budget | No silent truncation of-only summaries | assembler fixtures |
| KPI-004 | Wrong-recall eval regression rate (golden set) | ≤5% false assert rate | memory eval suite |
| KPI-005 | Dreaming rollback restores prior `MEMORY.md` state | 100% on scripted rollback | dreaming integration tests |
| KPI-006 | Cross-channel same-session continuity (Telegram → web) | Shared session id and context | channel E2E smoke |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-15-memory-lcm | Lossless store, compaction DAG, context assembly, search telemetry |
| spec-31-memory-dreaming | Scored consolidation into `MEMORY.md`, promote/review/rollback |
| spec-32-memory-honcho | Opt-in inferred user model, throttle, deny topics, profile render |
| spec-17-gateway | Turn spine, persona load, `personality_version`, triager cache |
| spec-18-channel-telegram | Telegram session continuity, `/config` persona surfaces |
| spec-19-channel-webui | Web chat session binding and persona parity |
| spec-20-voice | Voice turn persona injection and session linkage |
| spec-21-executor-tier-cd | Tier C/D executor context assembly from shared memory |
| spec-29-openui | Generated UI panels that respect workspace persona context |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new memory features.

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
| 0.9 | 2026-07-07 | Legacy six-section scaffold | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave; expanded personality, SOUL/USER memory, session continuity, eval/degradation | MODIFIED prd-02-personality-and-memory (structure); traceability aligned to spec-15/31/32 and channel specs |

## AI Behavior & Eval

**AI hypothesis:** We believe that if the system injects stable persona files plus
LCM-assembled context with confidence-gated recall, operators will experience a
consistent daily-driver assistant because tone and facts persist without manual
re-prompting every session.

**Eval ownership:** Memory subsystem owner · cadence: per release + weekly golden run ·
re-eval triggers: model change, dreaming prompt change, Honcho extractor update,
`SOUL.md` template change

| Eval | Good output | Bad output | Metric | Target |
| --- | --- | --- | --- | --- |
| Persona fidelity | Replies match `SOUL.md` tone and boundaries | Snaps to generic assistant voice | human/LLM judge score | ≥ 0.85 |
| Operator recall | Uses `USER.md` name and stated preferences | Asks for name again or invents traits | factuality vs golden | ≥ 0.90 |
| Session continuity | References prior thread facts correctly | Contradicts yesterday without ack | continuity check | ≥ 0.88 |
| Memory drift | Hedges when fact is stale or denied | Asserts contradicted `MEMORY.md` line | false assert rate | ≤ 0.05 |
| Dreaming promote | New lines are faithful to source turns | Hallucinated or over-generalised facts | promotion precision | ≥ 0.92 |

**Golden dataset:** Exists (fixtures + curated operator transcripts) · ~40 scenarios ·
owner: memory wave · refresh: quarterly or after prompt change

**Confidence thresholds (product-level):**

| Band | Threshold | Autonomy | Human checkpoint |
| --- | --- | --- | --- |
| High | ≥ 0.85 | Inject fact into reply | Audit via trace |
| Medium | 0.60–0.84 | Hedge ("I think you prefer…") | Operator confirms inline |
| Low | < 0.60 | Abstain from asserting; ask or omit | Edit `USER.md` / deny topic |

## Failure & Degradation

| Failure | Detection | User-facing behavior | Rollback / owner |
| --- | --- | --- | --- |
| Memory drift | Eval regression; operator thumbs-down | Hedge, offer correction, stop re-asserting denied topic | Deny topic + `USER.md` edit; memory owner |
| Wrong recall | Operator correction; contradicts `MEMORY.md` | Acknowledge mistake; do not repeat in session | Roll back dreaming batch if promoted; Honcho throttle |
| Stale persona cache | `personality_version` mismatch trace | Next turn reloads files | Automatic on version bump; gateway |
| Compaction loss | Assembler budget exceeded | Still serves fresh tail; may omit oldest summary detail | Tune compaction cadence; operator can search LCM |
| Honcho over-inference | Low-confidence extraction | Skip promote; no `USER.md` write | Disable Honcho; operator |
| Dreaming bad batch | Review queue flag | Hold promotion; show diff | `rollback_last_auto_batch`; operator |

**RISK register (product-level):**

| ID | Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- | --- |
| RISK-001 | Memory drift erodes trust | H | M | Confidence bands, deny topics, eval gate |
| RISK-002 | Wrong recall stated confidently | H | M | Abstain band, thumbs feedback, golden eval |
| RISK-003 | Persona files out of sync across channels | M | L | Shared `personality_version` on gateway turn |
| RISK-004 | Dreaming promotes PII or stale facts | H | L | Review queue, rollback manifest, llmignore filters |
| RISK-005 | Compaction drops actionable detail | M | M | Lossless source rows; search + summary assembly |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Mission Control show a live diff when Honcho proposes a `USER.md` append? | Alex | 2026-08-01 | resolved — v1 uses existing persona editor + trace; inline diff deferred |
| OQ-002 | Default dreaming cadence for new workspaces—nightly auto-promote or review-only? | Alex | 2026-08-01 | resolved — review-only default; operator opts into auto-promote |
| OQ-003 | Cross-workspace persona portability (export/import `SOUL.md` bundle)? | Alex | 2026-08-01 | resolved — defer; manual file copy sufficient for v1 |
