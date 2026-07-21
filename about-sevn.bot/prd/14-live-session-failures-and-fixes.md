---
id: prd-14-live-session-failures-and-fixes
kind: prd
title: Live-session failures & fixes — PRD
status: draft
owner: Alex
summary: Catalog of real operator-session failures—grounding loops, PDF degradation,
  tool/skill routing—and the product fixes that stop silent hangs and fabricated answers.
last_updated: '2026-07-21'
fingerprint: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
related: []
sources: []
parent_prd: prd-00-main
specs:
- spec-11-tools-registry
- spec-12-skills-system
- spec-14-executor-tier-b
- spec-16-harness-discipline
- spec-17-gateway
personas:
- operator
prd_profile: standard
---

## Problem & Motivation

sevn.bot is exercised in long **live Telegram and web-chat sessions** where small integration
gaps compound into operator-visible failures: twenty-minute loops on a PDF that can never render,
answers that claim files were sent without any tool dispatch, or motion-only replies that never
run a tool. These incidents were captured in session transcripts (message ids cited below as
**msg N**) and gateway logs during the June 2026 reliability wave.

- **Who:** Daily operators who depend on the bot for real tasks—rendering documents, running
  commands, fetching live facts—and who cannot afford silent degradation or hallucinated
  completion.
- **Pain:** Failures often surface late (mid-turn hang, bare promise text, wrong identity
  label) because degraded subsystems report success or errors are masked before the agent sees
  them. The operator experiences lost time and eroded trust, not a crisp actionable error.
- **Why now:** A concentrated live-session wave (2026-06-04 through 2026-06-19) produced a
  repeatable failure catalog; fixes landed across grounding, skills, tools, and gateway boot
  paths. This PRD captures the **product contract** for those fixes so future regressions are
  caught by doctor, boot warnings, and harness steer-inject—not rediscovered in production chat.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Operator in Telegram | Asks to render markdown to PDF | Receives a PDF or a clear, immediate error—not a multi-turn loop |
| UJ-002 | Operator debugging a hang | Session stalls with motion-only replies | Harness reclassifies the turn as failed and steers a retry with real tool use |
| UJ-003 | Operator asking identity | "Who are you?" in early session | Reply uses workspace identity name from IDENTITY.md, not the product label |
| UJ-004 | Operator fetching live facts | Score, schedule, or weather question | Answer is grounded on web retrieval or blocked with an honest limitation |
| UJ-005 | Maintainer closing the wave | Reviewing transcript failures | Each failure mode maps to a spec-owned fix and a regression test |

**Narrative:**

- **UJ-001 — PDF render (msg 14–msg 31):** Operator requests a PDF export. Gateway accepts the
  turn; the agent loops on render retries because native PDF libraries are missing but only a
  silent fallback is active. After fix: boot emits a visible degradation warning; skill stdout
  stays a single JSON envelope; structured `RENDER_FAILED` surfaces before retry exhaustion.
- **UJ-002 — Motion without action (msg 8, msg 22):** Model finalizes with "On it — rendering
  now" or "Talking is done. Doing." without dispatching tools. Harness treats this as a failed
  turn, injects steer text, and widens retry instead of shipping the bare promise.
- **UJ-003 — Identity drift (msg 5):** Two consecutive "who are you?" turns return different
  names—product label vs workspace identity. Deterministic identity reply path resolves
  IDENTITY.md before tier-B generation.
- **UJ-004 — Ungrounded live facts (msg 19):** Agent states an NBA series score without calling
  web tools. Grounding guard blocks or prefixes the claim unless retrieval tools succeeded.

## Goals

- **FR-001:** The product shall **surface PDF render degradation at gateway boot** when native
  render libraries are missing, so operators see the failure before the first PDF turn—not only
  after running doctor manually.
- **FR-002:** Skill script failures shall return **structured, actionable envelopes** (including
  when stderr is non-empty) so the agent never loops on a masked or corrupted stdout payload.
- **FR-003:** Tier-B finals shall **fail closed on motion-only promises**—zero-tool turns that
  only promise action must not ship as success; harness shall steer a tool-backed retry.
- **FR-004:** Outbound text shall be **grounding-guarded** for file-delivery claims, live
  factual content, false tool-failure claims, and audit embellishment unless matching tools
  succeeded in the same turn.
- **FR-005:** Tools that are also registered native tools shall **route to the native tool**
  with a clear `SKILL_IS_ACTUALLY_TOOL` signal when mis-invoked via the skill path—never a
  silent skill miss.
- **FR-006:** Unknown or unsupported tool actions shall **fail loudly** (`ok: false`)—never
  serialize as empty success that the agent interprets as "tool silenced."
- **FR-007:** Pure identity turns shall return **workspace-resolved identity** from
  IDENTITY.md consistently across repeated asks in the same session.
- **FR-008:** Session artifact and spill paths shall **stay confined** to the active session
  workspace so live-session file churn does not leak across sessions or omit GC for ended
  sessions.
- **FR-009:** Each catalogued failure mode below shall retain a **regression anchor** (transcript
  msg id or log signature) traceable to an implementing spec and test suite entry.

## Non-Goals

- Replacing tier-B/C executor architecture or triage policy—this PRD documents reliability
  fixes within the existing turn spine.
- Full Mission Control incident dashboards or post-hoc transcript replay UI (doctor, boot
  warnings, and logs remain the v1 surfaces).
- Automatic remediation of every failure without operator visibility—some fixes are
  steer-and-retry, not silent auto-heal.
- New channel surfaces beyond Telegram and web chat covered by the June 2026 sessions.

## Experience

- **Happy path:** Operator request completes with tool-backed evidence in the reply (file
  attached, command output shown, web snippet cited). Turn latency stays bounded; no repeated
  identical skill invocations across widened retries.
- **Operator controls:** `sevn doctor` and gateway boot warnings for environment gaps; config
  and skills layout unchanged for operators who already fixed native PDF deps.
- **Degraded path — PDF:** Boot log warning names missing native libs; first PDF turn returns
  explicit render-unavailable guidance (including doctor hint) rather than looping.
- **Degraded path — grounding:** User sees either a corrected answer after steer-retry, a
  prefixed unverified disclaimer, or a typed no-answer path—not a confident fabrication.
- **Degraded path — routing:** Misrouted skill-to-tool attempts surface a structured routing
  error; agent can retry via the native tool name.
- **Failure catalog (product-level, transcript-backed):**

| Failure | Transcript / log anchor | Operator-visible symptom | Product fix |
| --- | --- | --- | --- |
| Silent PDF native-lib miss | msg 14–31; boot 2026-06-04 | ~20 min loop on "render to PDF" | Boot degradation warning; clean skill JSON stdout; prefer structured `RENDER_FAILED` over stderr mask |
| Motion-only finalize | msg 8, msg 22 | "Doing now" with no file or output | Harness P4: fail turn + steer retry |
| Fabricated file send | msg 17 | "Sending PDF now" with no attachment | File-delivery grounding guard |
| Ungrounded live score | msg 19 | NBA score stated without lookup | Live-factual grounding guard |
| Skill shadow path miss | msg 26 | PDF skill cannot see workspace file | Skill execution cwd/env contract |
| Tool-as-skill SERP | msg 12 | Skill wrapper when native search exists | `SKILL_IS_ACTUALLY_TOOL` + optional auto-route |
| process `action=run` hole | msg 11 | Empty success; agent abandons fallback | Reject unknown actions with `ok: false` |
| Identity label vs name | msg 5 | Inconsistent "who are you?" answers | Deterministic IDENTITY.md reply |
| Eager hydration SERP repeat | msg 33 | Duplicate search hydration across turns | Intro prompt / hydration recurrence guard |
| Artifact spill outside session | msg 40; log P10 | Files written outside session tree | Artifact output confinement |
| Silent browser reap on shutdown | PR #46 / gateway shutdown | Chrome/profile leftovers after restart with no log | Log `browser_reap_on_shutdown_failed`; do not `suppress` reap exceptions |
| Issue-watch notify unwired | PR #46 / cron | Diffs detected but operator never notified | Boot `wire_operator_notify` → `route_outgoing`; LOG fallback when no owner |

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | PDF turn completes or fails with explicit error within one widened-retry cycle | ≤ 2 min wall clock on degraded host | live-session regression tests, operator smoke |
| KPI-002 | Motion-only zero-tool finals shipped to operator | 0% (all steered or failed) | harness P4 tests |
| KPI-003 | Ungrounded file-delivery or live-factual claims in outbound channel text | 0% on guarded patterns | grounding unit + integration tests |
| KPI-004 | Unknown tool `action` values returning `ok: true` with empty payload | 0 | process/terminal regression tests |
| KPI-005 | Repeated "who are you?" identity name consistency | 100% same resolved name | identity reply tests |
| KPI-006 | Catalog rows with spec + test traceability | 100% of rows in Experience table | PRD traceability review |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-11-tools-registry | Native vs skill routing, `SKILL_IS_ACTUALLY_TOOL`, process/terminal action validation |
| spec-12-skills-system | PDF skill JSON contract, shadow execution environment, structured failure envelopes |
| spec-14-executor-tier-b | Grounding guards (file delivery, live facts, audit/tool claims), steer-inject paths |
| spec-16-harness-discipline | Motion-only (P4) failure classification, widened retry, loop integrity |
| spec-17-gateway | Boot PDF degradation warning, first-session identity/bootstrap surfaces |

Downstream: **PRD → specify → plan → tasks** for any net-new failure class not yet covered by
the specs above.

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
| 0.1 | 2026-06-19 | Transcript-backed failure catalog scaffold (legacy six-section shell) | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave standard; expanded failure table and reliability FRs | MODIFIED prd-14-live-session-failures-and-fixes (structure); traceability aligned to spec-11/12/14/16/17 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Mission Control expose a live-session "last failure class" panel derived from harness steer codes? | Alex | 2026-08-15 | open |
| OQ-002 | Promote this PRD to `ready` and add to prd-00-main domain map once KPI-006 traceability audit completes? | Alex | 2026-08-01 | open |
| OQ-003 | Auto-run doctor PDF probe on gateway boot vs warn-only—does warn-only leave enough signal for operators who never read logs? | Alex | 2026-08-15 | open |
