---
id: prd-01-conversational-experience
kind: prd
title: Conversational Experience — PRD
status: ready
owner: Alex
summary: The operator talks to sevn where they already chat—Telegram on phone, web/Mission
  Control on laptop—with shared sessions, voice, and one gateway turn spine.
last_updated: '2026-07-19'
fingerprint: sha256:ed59db8b9e56fd35626da284ff3b8f474423644f4f26a06eaf83656e2ab10786
related:
- prd-07-mission-control
- prd-10-generated-ui
sources:
- src/sevn/gateway/**
- src/sevn/channels/**
parent_prd: prd-00-main
specs:
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
| spec-17-gateway | draft |
| spec-18-channel-telegram | draft |
| spec-19-channel-webui | draft |
| spec-20-voice | draft |
| spec-37-openui | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

A personal AI is only useful if it lives in the conversational surfaces the operator
already uses, day in and day out. Consumer assistants trap you in one vendor app; switching
to a self-hosted gateway fails when the bot is not where your thumb already is.

- **Who:** A single-operator power user who carries Telegram on the phone and opens a
  browser on the laptop—the same person, two contexts, one assistant.
- **Pain:** Today, self-hosted bots often mean a separate web UI or CLI-only workflow.
  Context does not follow the operator across surfaces; voice notes and rich replies
  feel bolted on; long threads break on platform limits or formatting quirks.
- **Why now:** sevn's gateway spine, Telegram adapter, owner webchat, and voice pipelines
  are implemented—this PRD states the **product contract** for daily-driver
  conversational UX across those channels.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Mobile operator | Sends a text or voice note in Telegram DM | Gets a streaming reply with sane formatting, optional TTS, and session continuity |
| UJ-002 | Desktop operator | Opens Mission Control Chat or standalone webchat | Same assistant, shared session history with Telegram when scope matches |
| UJ-003 | Operator mid-task | Sends a follow-up while a turn is in flight | Sees busy/steer/cancel behavior per channel policy—not a silent duplicate or lost message |
| UJ-004 | Operator needing structure | Agent returns a form, table, or panel | Rich reply or OpenUI delivery on Telegram or web with safe fallback text |

**Narrative:**

- **UJ-001 — Telegram daily driver:** Operator messages the bot from Telegram on the way
  to work—text, voice note, or inline button tap. Replies stream with Markdown-safe
  formatting, chunked when needed, and optional voice playback when TTS mode allows.
  `/config` and inline menus adjust session, models, and voice without leaving chat.
- **UJ-002 — Laptop webchat:** Operator opens owner-only webchat (Mission Control Chat
  or gateway SPA), authenticates once, and continues the thread. Session scope aligns with
  Telegram via the shared session manager; explicit fork starts a parallel thread when
  needed.
- **UJ-003 — In-flight control:** While the agent works, the operator can steer or cancel
  per channel queue mode. Telegram shows typing/busy cues; webchat supports stop frames
  over the WebSocket.
- **UJ-004 — Rich surfaces:** When the agent emits structured UI, Telegram gets inline
  keyboards or rasterised previews; webchat renders sanitised HTML panels. If rich
  delivery fails, plain-text fallback keeps the turn usable.

## Goals

- **FR-001:** The product shall treat **Telegram** as the primary mobile conversational
  channel—DM and configured topics—with inbound normalisation, outbound chunking, and
  Markdown-safe rendering.
- **FR-002:** The product shall provide an **owner-only web conversational surface**
  (WebSocket webchat and Mission Control Chat) that shares session continuity with
  Telegram when session scope matches.
- **FR-003:** The gateway shall **normalise all channel ingress** into one turn spine
  (triage → executors → outbound routing) so behavior is consistent regardless of surface.
- **FR-004:** Operators shall receive **streaming replies** on Telegram and webchat with
  channel-appropriate busy, steer, and cancel semantics while a turn is active.
- **FR-005:** The product shall support **voice notes inbound** (STT) and **optional TTS
  outbound** on Telegram and webchat when voice is enabled and backends are configured.
- **FR-006:** Rich agent output (tables, forms, panels) shall **degrade gracefully** to
  plain text on each channel when rich or OpenUI delivery is unavailable or rejected.
- **FR-007:** Telegram `/config`, reply keyboard, and inline menus shall expose
  conversational controls (session, models, voice mode, quick actions) without requiring
  file edits.

## Non-Goals

- Building a **new chat client** or replacing Telegram—Telegram remains the mobile shell.
- **Discord, Slack, or multi-tenant** team chat as v1 daily-driver surfaces (adapters may
  exist as stubs; see Open Questions).
- **Public/anonymous webchat**—browser chat is owner-authenticated only.
- **Mission Control observability** panels (traces, providers, cron)—covered by
  `prd-07-mission-control`; Chat tab is in scope here, admin chrome is not.
- **OpenUI authoring semantics**—HTML sanitisation, CSP, and tool contracts live under
  `prd-10-generated-ui`; this PRD covers delivery on conversational channels only.

## Experience

- **Happy path (Telegram):** Operator sends a message in DM. Bot shows typing while the
  turn runs; reply streams in readable Markdown with optional Regen/feedback quick actions.
  Voice note in → transcribed text drives the turn; TTS mode `all` or `when_asked` may
  attach audio on outbound.
- **Happy path (web):** Operator logs into webchat or Mission Control Chat, sends a
  message over WebSocket, sees streamed tokens and rendered markdown. OpenUI panels embed
  in-page; stop ends the active turn.
- **Cross-surface continuity:** Same session key → shared history between Telegram and
  web when configured; fork on web starts a sibling session without corrupting the main
  thread.
- **Operator controls:** Telegram `/config` menu (session queue mode, TTS mode, model
  picks); web JWT mint/refresh; channel enable flags in config.
- **Degraded path:** Telegram rejects rich payload → fall back to plain text or chunked
  send. STT/TTS backend missing → clear operator-visible message, text path still works.
  Gateway restart → polling/webhook resumes; webchat reconnects with refreshed token.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Telegram DM round-trip on default config | Operator reply within first session after onboarding | onboarding E2E, `make telegram-e2e` |
| KPI-002 | Webchat owner login → first streamed reply | ≤60s on happy path | MC/webchat integration tests |
| KPI-003 | Shared-session history visible on second surface | Same scope shows prior turns on Telegram ↔ web | session manager tests |
| KPI-004 | Voice note STT → text turn completion | Works when voice backends configured | voice integration tests |
| KPI-005 | Rich/OpenUI failure fallback | 100% of rejected rich sends deliver plain-text fallback | channel adapter tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-17-gateway | Turn spine, channel router, session persistence, webchat auth, ingress/outbound normalisation |
| spec-18-channel-telegram | Telegram adapter—poll/webhook, formatting, menus, voice, inline callbacks |
| spec-19-channel-webui | Owner webchat SPA, WebSocket protocol, Mission Control Chat integration |
| spec-20-voice | STT/TTS pipelines, trigger keywords, provider chains shared by channels |
| spec-37-openui | Sanitised HTML and form callbacks delivered on Telegram and webchat |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new channel features.

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
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full Telegram/web/voice product contract | MODIFIED prd-01-conversational-experience (structure); traceability aligned to spec-17/18/19/20/29 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should Discord/Slack ship as first-class daily-driver channels in v1? | Alex | 2026-08-01 | resolved — Telegram + owner webchat remain primary; Discord/Slack stay stubbed until explicit operator demand |
| OQ-002 | Default cross-surface session model—always shared scope vs explicit fork on web? | Alex | 2026-08-01 | resolved — shared SessionManager scope by default; web/Mission Control exposes explicit fork for parallel threads |
