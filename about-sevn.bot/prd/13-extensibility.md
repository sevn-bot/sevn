---
id: prd-13-extensibility
kind: prd
title: Extensibility — PRD
status: ready
owner: Alex
summary: Built-in capabilities cover common paths; deployments need org glue—ticketing,
  LDAP, formatters, policy hooks—via plugins, skills, and hooks without forking core.
last_updated: '2026-07-08'
related: []
sources:
- src/sevn/plugins/**
- src/sevn/skills/**
parent_prd: prd-00-main
specs:
- spec-34-plugin-hooks
- spec-11-tools-registry
- spec-12-skills-system
- spec-01-system-overview
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-20-voice
- spec-21-executor-tier-cd
- spec-30-non-interactive-triggers
personas:
- operator
- power-operator
prd_profile: standard
---

## Problem & Motivation

sevn.bot ships bundled tools, skills, and channel adapters that cover most personal-assistant
workloads. Real deployments still diverge: an operator's company runs Jira or ServiceNow, HR
data lives behind LDAP, finance wants bespoke report formatters, and platform teams need policy
wrappers ("never let kubectl delete production namespaces") without maintaining a fork of the
gateway.

- **Who:** Self-hosted operators and power users who treat sevn as infrastructure—not a
  disposable chat widget—and need organisation-specific glue on top of the core product.
- **Pain:** Without a first-class extension surface, every custom integration becomes a core
  patch, a fragile sidecar, or an abandoned fork. Operators either give up on the integration
  or carry merge debt every release.
- **Why now:** Plugin hooks, channel plugins, workspace skills, and trigger ingress are already
  wired into the gateway runtime; this PRD makes the **product contract** for extending sevn
  without forking explicit—what operators can plug in, how trust is gated, and where core ends.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Platform operator | Needs org policy on tool calls (block, rewrite, audit) | Installs a hook package; dangerous commands are blocked or rewritten before execution |
| UJ-002 | Integration operator | Wants internal ticketing or HR lookup in chat | Adds a workspace skill or plugin slash command; operators reach internal systems without core changes |
| UJ-003 | Channel operator | Needs a bespoke messaging surface or rich adapter | Registers a channel plugin; gateway routes through the adapter with the same turn spine |
| UJ-004 | Automation operator | Event fires (webhook, cron) and org-specific side effects are required | Trigger hooks observe or enrich ingress/egress without a parallel automation stack |
| UJ-005 | Power operator | Wants custom tools beyond the bundled registry | Extends via workspace skills and sanctioned extension points—not by patching core |

**Narrative:**

- **UJ-001 — Policy wrapper:** Before a shell or cluster tool runs, the operator's hook inspects
  arguments and returns block, continue, or replace. The model sees a clear rejection reason
  instead of a silent failure or a forked gateway build.
- **UJ-002 — Org glue:** A workspace skill wraps the internal REST API for leave balances or
  ticket creation. Telegram and Web UI turns stay in the normal conversational flow; secrets
  resolve through the standard operator-controlled path.
- **UJ-003 — Channel plugin:** A third-party adapter registers as a channel plugin. Messages
  normalize into the same gateway turn pipeline; Mission Control and traces stay coherent.
- **UJ-004 — Trigger sidecar:** A webhook arrives; a trigger hook logs correlation metadata or
  fans out to an internal notifier before the notify-only or agent-pass arm runs.
- **UJ-005 — Power-user extension:** The operator authors a skill with scripts and manifest
  metadata in the workspace tree. Doctor and validate surface broken entry points before the
  gateway fails mid-turn.

## Goals

- **FR-001:** The product shall offer an **in-process extension layer** (plugin hooks) that
  intercepts tool calls, tool results, terminal output, trigger ingress/egress, and dispatcher
  commands—without requiring core patches for org-specific behavior.
- **FR-002:** Operators shall **enable, disable, and order** hook packages from workspace
  config, including trust-level gates for interception and plugin-owned slash commands.
- **FR-003:** The product shall support **channel plugins** so third-party adapters can register
  alongside built-in Telegram, Web UI, and voice surfaces.
- **FR-004:** The product shall support **workspace skills and custom tools** as the primary
  path for operator-authored capabilities that do not belong in core.
- **FR-005:** **Doctor and validate** shall report broken or misconfigured extension entry points
  before gateway startup fails—or offer a documented dev-only partial-load escape hatch.
- **FR-006:** Extension points shall **compose with the existing turn spine** (triage, tier B/C
  executors, triggers) so plugins augment behavior rather than replacing gateway semantics.
- **FR-007:** The product shall **fail closed on trust**: high-impact hook surfaces require
  explicit operator trust configuration; silent broad interception is not the default.

## Non-Goals

- Forking or vendoring core gateway code as the recommended integration path—extensions ship as
  installable packages or workspace artifacts.
- A public plugin marketplace, billing, or third-party review program in v1.
- Arbitrary in-process code execution without workspace gates—extensions remain operator-installed
  and config-gated (see prd-03-trust-and-control).
- Replacing the bundled tools registry or skills catalog with "bring your own everything"—built-ins
  stay the default; extensions fill org-specific gaps.
- MCP server hosting inside the gateway process as a v1 product promise—MCP may integrate via
  skills or future specs; this PRD does not mandate a first-class MCP runtime.
- Multi-tenant org RBAC or per-seat plugin licensing—v1 centers the single-operator workspace.

## Experience

- **Happy path (hook):** Operator installs a hook distribution, adds a workspace config row
  (`enabled`, optional `runs_after`, `trust_level`), restarts the gateway. Tool calls pass
  through the ordered hook chain; Mission Control and traces show normal turns.
- **Happy path (skill):** Operator adds a workspace skill directory with manifest and scripts.
  The skill appears in the catalog; turns invoke it like any bundled skill.
- **Happy path (channel plugin):** Operator installs a channel adapter package and enables it in
  config. Messages on that surface use the same session and turn UX patterns as built-in channels.
- **Operator controls:** Per-plugin enable/disable; trust level for interception and slash
  dispatch; ordering hints; doctor/validate before production boot.
- **Degraded path:** Broken hook import → doctor warning or fail-fast boot (per operator policy);
  blocked tool call → model-visible reason; disabled plugin → skipped silently in the chain.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Org policy hook blocks or rewrites targeted tool calls without core patch | 100% on configured deny/rewrite rules | plugin hook integration tests |
| KPI-002 | Doctor/validate detect broken extension entry points before first failed turn | ≥95% of misconfigurations caught pre-boot | doctor/validate fixtures |
| KPI-003 | Workspace skill or plugin slash command reachable from Telegram/Web UI | Operator completes flow without editing core | manual smoke, channel E2E |
| KPI-004 | Gateway boot with only built-ins unaffected by extension rollout | Zero regressions when `plugin_hooks` empty | CI, backward-compat tests |
| KPI-005 | Trigger hook observes ingress/egress without duplicating trigger transport | Hooks fire on webhook/cron paths when enabled | trigger mux tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-34-plugin-hooks | Hook protocol, entry-point discovery, ordering, trust gates, channel plugins, trigger mux |
| spec-11-tools-registry | Tool dispatch path that hooks intercept; plugin-owned dispatch keys |
| spec-12-skills-system | Workspace skills as operator extension path |
| spec-01-system-overview | Extension layer placement in the gateway architecture |
| spec-17-gateway | Turn spine wiring for hook chain and channel plugin load |
| spec-18-channel-telegram | Built-in channel baseline; plugin adapters normalize to same router |
| spec-19-channel-webui | Web UI channel baseline and extension coexistence |
| spec-20-voice | Voice channel path shares gateway extension hooks |
| spec-21-executor-tier-cd | Tier C/D execution surfaces that honor tool interception |
| spec-30-non-interactive-triggers | Trigger ingress/egress hook surfaces and mux |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new extension surfaces.

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
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full extensibility product intent | MODIFIED prd-13-extensibility (structure); traceability aligned to spec-34/11/12/17/30 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Mission Control expose per-plugin health badges for loaded hook and channel packages? | Alex | 2026-08-01 | resolved — defer to prd-07-mission-control; v1 relies on doctor/validate signals |
| OQ-002 | First-class MCP server registry in gateway vs workspace skills only? | Alex | 2026-08-01 | resolved — workspace skills and integration_call paths for v1; dedicated MCP spec deferred |
| OQ-003 | Default trust_level for new plugin_hooks entries—owner-only interception vs opt-in default? | Alex | 2026-08-01 | resolved — owner trust required for pre_tool_call and dispatch_tool per spec-34-plugin-hooks |
