---
id: prd-06-setup-and-operations
kind: prd
title: Setup & Operations — PRD
status: ready
owner: Alex
summary: Local-first bots are judged in the first ten minutes—clone, three setup commands,
  and a Telegram reply, or the operator returns to a hosted assistant.
last_updated: '2026-07-16'
fingerprint: sha256:2d0974ead33951470423257d80ad6bfb501e8ab00ac2c0d966f2eaa4b2db9e94
related:
- prd-07-mission-control
sources:
- src/sevn/config/**
- src/sevn/cli/**
- src/sevn/onboarding/**
parent_prd: prd-00-main
specs:
- spec-02-config-and-workspace
- spec-07-egress-proxy
- spec-22-onboarding
- spec-23-cli
- spec-24-dashboard
- spec-25-cicd-full
personas:
- operator
prd_profile: standard
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-02-config-and-workspace | draft |
| spec-07-egress-proxy | draft |
| spec-22-onboarding | draft |
| spec-23-cli | draft |
| spec-24-dashboard | draft |
| spec-25-cicd-full | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

Local-first AI bots are judged in the **first ten minutes**. The operator opens the README,
follows a short command sequence, and either gets a Telegram or Web UI reply within minutes—or
gives up and returns to a hosted assistant that "just works." Self-hosted products lose on
**time-to-first-reply**, not on feature checklists buried in docs.

- **Who:** Self-hosted operators trying sevn.bot for the first time, and the same person on
  day thirty doing upgrades, health checks, and recovery without becoming a part-time SRE.
- **Pain:** Fragmented setup—hand-editing config, guessing which daemon to start, discovering
  missing credentials only when a turn fails, or fighting Docker volumes without a guided path.
- **Why now:** The gateway, paired egress proxy, onboarding wizard, and doctor probes already
  exist in code; this PRD makes the **product contract** for install, first conversation, and
  ongoing operations explicit so every path shares one validation and promotion pipeline.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | First-time operator | Clones the repo and wants a working bot tonight | Completes setup wizard, passes doctor, sends first channel message |
| UJ-002 | Host-native operator | Prefers macOS/Linux with local daemons | Onboarding installs gateway + proxy units; CLI manages lifecycle |
| UJ-003 | Docker operator | Wants containerized gateway + proxy for testing or VPS | Compose stack boots; onboarding seeds workspace on shared volume |
| UJ-004 | Returning operator | Pulls an upgrade or rotated credentials | `sevn sync`, doctor, and validate catch misconfig before chat fails |

**Narrative:**

- **UJ-001 — First ten minutes:** Operator runs `make setup`, `sevn onboard`, `sevn doctor`.
  The wizard collects providers, Telegram pairing, and workspace layout—without hand-editing
  `sevn.json` on day one. Doctor reports green checks; the operator messages the bot in
  Telegram or opens the Web UI URL shown at the end of onboarding.
- **UJ-002 — Daemon day two:** Gateway and proxy run as installed services. The operator uses
  `sevn gateway` and `sevn proxy` subcommands for start/stop/status/logs instead of memorizing
  unit file paths.
- **UJ-003 — Docker path:** Operator brings up the slim compose stack, runs onboarding inside
  the gateway container with a shipped profile, and hits `/ready` before exposing anything
  remotely. Browser-heavy skills stay on the host; container path optimizes gateway + proxy.
- **UJ-004 — Stay current:** After `sevn sync --latest`, doctor and config validate surface
  stale OAuth, missing secrets, or proxy pairing drift as warnings—with `--fix` where safe.

## Goals

- **FR-001:** The product shall offer a **three-command happy path** from fresh clone to health
  check: `make setup`, `sevn onboard`, `sevn doctor`—documented in README and Getting started.
- **FR-002:** **Onboarding** shall be the default first-time config surface (web wizard; CLI
  TUI via `--cli`); it shall merge, validate, and promote into workspace `sevn.json` rather
  than requiring manual JSON editing.
- **FR-003:** Onboarding shall **register gateway and proxy daemons by default** on host installs
  so the operator is not left to wire systemd/launchd by hand.
- **FR-004:** **Doctor** shall report install health (config, secrets, proxy pairing, channels,
  provider credentials) with human-readable output and optional `--json` for support threads.
- **FR-005:** Doctor and config **validate** shall warn on misconfiguration **before** the first
  failed turn when probes can detect the issue; doctor `--fix` shall offer safe remediation paths.
- **FR-006:** The **CLI** shall be the primary operator surface for install, upgrades, workspace
  lifecycle, gateway/proxy control, and scriptable inspection—not the in-harness agent tool API.
- **FR-007:** A **Docker operator stack** (gateway + proxy, optional browser/gui profiles) shall
  support local testing and VPS-style deploy without a separate undocumented compose recipe.
- **FR-008:** Onboarding and CLI logs shared for support shall **redact** bearer tokens, Telegram
  bot tokens, and webhook secrets so operators can paste logs safely.
- **FR-009:** **Remote deploy** shall remain an optional advanced path (inventory + export bundle)
  without blocking the first-ten-minutes host-native flow.

## Non-Goals

- One-click hosted SaaS provisioning—sevn.bot optimizes for **self-hosted ownership**, not a
  vendor-managed funnel (see prd-00-main Non-Goals).
- Replacing Mission Control for day-two observability—setup gets you running; prd-07-mission-control
  owns traces, provider panels, and ops surfaces.
- Running Playwright Telegram E2E **inside** the default gateway container—host-side smoke stays
  the developer path; Docker ships gateway + proxy, not headed browser automation by default.
- Enterprise fleet management (MDM, multi-tenant RBAC, org-wide billing)—v1 centers the **solo
  operator** workspace.
- Hand-editing `sevn.json` as the recommended first-time path—advanced edits are supported, but
  onboarding is the product default.

## Experience

- **Happy path (host):** Clone → `make setup` (uv, Python 3.12+, deps, CLI on PATH) →
  `sevn onboard` (browser wizard or `--cli`) → `sevn doctor` → message bot in Telegram or
  open Web UI. Median target: first reply within **fifteen minutes** on reference hardware.
- **Happy path (Docker):** Copy env template → `make compose-up` → onboarding run inside
  gateway container with shipped profile → curl `/ready` → first message via Telegram or Web UI.
- **Operator controls:** Onboarding profile selection, capability toggles, daemon install opt-out,
  `--no-start-services`, export bundle for remote deploy, `sevn sync --latest` for manual upgrades.
- **Degraded path:** Missing API key or expired OAuth → doctor warning before chat embarrassment.
  Proxy not paired → clear doctor section, not a silent LLM timeout. Onboarding draft conflict →
  lock message with recovery steps. Docker without secrets → fail fast at compose with documented
  env vars, not a crash loop without explanation.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Median time from fresh clone to first successful channel reply (onboarding happy path) | ≤ 15 minutes on reference hardware | onboarding smoke, operator checklist |
| KPI-002 | Three-command path documented and exercised in CI smoke | README + Getting started match implemented flow | docs checks, onboarding E2E |
| KPI-003 | Misconfigurations caught by doctor/validate before first failed turn | ≥ 90% of fixture misconfigs warned pre-turn | doctor/validate suites |
| KPI-004 | Docker compose CI stack passes gateway `/ready` after onboard profile | Green on default CI matrix | docker workflow, compose-ci-smoke |
| KPI-005 | Support log paste safe—no raw tokens in onboard/doctor `--log-file` output | 100% redaction on fixture logs | onboarding + CLI log tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-02-config-and-workspace | Locate and validate `sevn.json`, workspace layout, schema gates before boot |
| spec-07-egress-proxy | Paired proxy daemon install, onboarding validation, operator deploy pairing |
| spec-22-onboarding | Merge + validate + promote pipeline; web/CLI wizards; live validation probes |
| spec-23-cli | `sevn` command surface: doctor, onboard, gateway/proxy lifecycle, sync, deploy helpers |
| spec-24-dashboard | Mission Control entry URL and dashboard handoff from onboarding completion |
| spec-25-cicd-full | Validated Dockerfiles and compose stacks that guard operator install paths in CI |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new setup flows.

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
| 0.9 | 2026-07-07 | Scaffolded six-section PRD from about-docs pipeline | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave standard; onboarding, doctor, Docker, first-ten-minutes contract | MODIFIED prd-06-setup-and-operations (structure); traceability aligned to spec-02/07/22/23/24/25 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Docker onboarding be the default path in public README, or host-native first? | Alex | 2026-08-01 | resolved — host-native first in README; Docker documented as secondary operator path |
| OQ-002 | Auto-run doctor at end of onboarding vs explicit operator step? | Alex | 2026-08-01 | resolved — wizard summarizes next steps including doctor; not forced blocking gate in v1 |
| OQ-003 | Ship browser/gui compose profiles in Getting started or keep advanced-only? | Alex | 2026-08-01 | resolved — advanced-only; default compose stays slim gateway + proxy |
