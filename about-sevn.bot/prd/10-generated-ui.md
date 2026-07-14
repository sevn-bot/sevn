---
id: prd-10-generated-ui
kind: prd
title: Generated UI — PRD
status: ready
owner: Alex
summary: Text-only replies hit a wall fast—budget panels, side-by-side diffs, and
  model-pick forms are clearer as sanitised HTML primitives than walls of markdown
  in every channel.
last_updated: '2026-07-12'
fingerprint: sha256:bea823d693563b387c0227a26e81a81491fb872ae79aaa1e5fab82ed888727f7
related: []
sources:
- src/sevn/ui/openui/**
parent_prd: prd-00-main
depends_on: []
build_phase: null
interfaces: []
specs:
- spec-37-openui
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-20-voice
- spec-21-executor-tier-cd
personas:
- operator
prd_profile: standard
---

## Spec implementation status (W9 seed)

This PRD is `ready` while linked specs below are not normatively complete (`draft` / `scaffold` / `rejected`). Code may run ahead of spec prose.

| Spec | Status |
| --- | --- |
| spec-37-openui | draft |
| spec-17-gateway | draft |
| spec-18-channel-telegram | draft |
| spec-19-channel-webui | draft |
| spec-20-voice | draft |
| spec-21-executor-tier-cd | draft |

<!-- HUMAN-INPUT[owner=operator]: Reconcile PRD `ready` vs implementing spec maturity — downgrade PRD, or keep ready and finish normative spec bodies. -->

## Problem & Motivation

Many assistant tasks are **visual or interactive**—compare two RFCs side-by-side, pick a model
from a short list, skim a budget table, confirm a form before a tool runs. Describing those in
plain text works, but it is slow to parse, easy to misread, and impossible to act on in one tap
when the operator is on a phone.

sevn.bot already answers in Telegram, Web UI, and voice. Without a **generated UI** layer, tier
B/C agents either dump long markdown or skip richer layouts entirely. Operators lose clarity;
the product feels like a chat-only bot when the underlying model could render a small, safe HTML
panel instead.

- **Who:** Daily-driver operators who ask for structured output—tables, cards, simple forms,
  dashboards—and expect it to work on phone and laptop without opening a separate app.
- **Pain:** Text-only replies force the operator to scroll, copy values by hand, and re-type
  choices. Side-by-side diffs, multi-field forms, and dense tables become walls of markdown that
  do not survive Telegram's narrow viewport.
- **Why now:** OpenUI (explicit agent tool calls → sanitised HTML → channel-specific delivery)
  is implemented across gateway and channels; this PRD states the **product contract** for when
  and how generated panels appear, how forms rejoin the turn, and how non-web channels degrade
  gracefully.

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Web UI operator | Asks for a table, chart layout, or side-by-side comparison | Sees live sanitised HTML inline in chat with strict CSP—no separate page hunt |
| UJ-002 | Telegram operator | Same visual request from phone | Receives a readable cover (PNG or PDF) plus buttons to open the live panel in WebApp or browser |
| UJ-003 | Operator using forms | Agent offers choices or fields (model pick, confirm/cancel) | Submits the form; callback rejoins the **same executor turn** without starting a new session |
| UJ-004 | Security-conscious operator | Agent attempts rich HTML or oversized payload | Unsafe markup is stripped, size caps enforced, and plain-text fallback always delivers |

**Narrative:**

- **UJ-001 — Live web panel:** Operator asks *"show me this month's spend by provider."* The
  agent calls the OpenUI render tool with a small HTML table. Web UI embeds the live panel in
  the thread; the operator scans and continues the conversation without leaving chat.
- **UJ-002 — Telegram cover + deep link:** Same request on Telegram. The gateway rasterises a
  cover image (or PDF when configured), sends it with fallback text, and attaches inline buttons
  (*Open here* / *Open in browser*) when a public live URL is available.
- **UJ-003 — Form callback:** Agent renders a model-pick form. Operator selects a slot and
  submits. The signed callback token validates, the gateway dispatches back into the in-flight
  turn, and the agent continues with the chosen value—no orphaned one-off webhook session.
- **UJ-004 — Safe degradation:** Agent emits disallowed script or an oversized HTML blob.
  Sanitisation drops unsafe tags, caps trigger soft warn or hard reject, and the channel still
  receives `fallback_text` so the turn never ends blank.

## Goals

- **FR-001:** Tier B/C/D agents shall produce generated UI only via an **explicit OpenUI render
  tool call**—never silent HTML injection in markdown replies.
- **FR-002:** Every OpenUI emit shall include **fallback plain text** so all channels remain
  usable when live HTML, rasterisation, or public URL delivery fails.
- **FR-003:** **Web UI** shall display **live sanitised HTML** (allowlisted tags, strict CSP,
  no operator-supplied client JavaScript in v1) inline in the conversational surface.
- **FR-004:** **Telegram** (and other non-web channels) shall receive **rasterised cover**
  delivery (PNG or PDF per config) plus optional inline keyboard deep links to the live panel
  when a reachable public base URL exists.
- **FR-005:** **Interactive forms** in generated HTML shall submit through **signed, TTL-bound
  tokens** and rejoin the **same executor turn** on the gateway—deterministic callback routing,
  not a orphan HTTP handler.
- **FR-006:** The product shall enforce **size caps** (soft warn, hard reject) and **HTML
  sanitisation** with operator-visible drop reasons in traces/Mission Control—not raw unsanitised
  agent HTML on the wire.
- **FR-007:** OpenUI shall respect **operator workspace config** (token TTL, callback timeout,
  allowed asset origins, rasteriser choice) without requiring code changes to tune limits.
- **FR-008:** **Voice** and other non-visual channels shall not promise live HTML; they shall
  receive spoken or text fallback derived from the required fallback text (and optional summary),
  consistent with channel capabilities in sibling specs.

## Non-Goals

- A general-purpose **web app builder** or drag-and-drop UI designer for operators.
- **Client-side JavaScript** in v1 generated panels (no custom widgets, charts libraries, or
  arbitrary script tags—sanitiser allowlist only).
- Rendering **fetched external web pages** inside OpenUI; page capture belongs to web-fetch/pdf
  skills, not the OpenUI render tool.
- **Mission Control dashboard widgets** as a substitute for in-channel OpenUI (MC may *display*
  OpenUI records for ops; conversational delivery is the scope here).
- Pixel-perfect **WYSIWYG** parity across Telegram raster covers and live web HTML—covers are
  previews; live URL is the authoritative interactive surface on capable clients.
- Operator-authored static HTML sites hosted by the gateway outside an agent turn.

## Experience

- **Happy path (Web UI):** Operator asks for a structured view. Agent responds with brief prose
  plus an inline live panel (table, cards, simple form). Operator reads or submits; conversation
  continues in one thread.
- **Happy path (Telegram):** Same turn delivers fallback text, a raster cover when rasterisation
  succeeds, and *Open here* / *Open in browser* when tunnel/public URL health allows live view.
- **Operator controls:** Workspace OpenUI config (caps, TTL, allowed origins, rasteriser);
  channel enablement via gateway; kill/stop still aborts the parent turn including pending form
  callbacks.
- **Degraded path:** Sanitisation strips unsafe markup → panel may shrink but fallback text
  always sends. Hard size reject → fallback text only, trace notes the reject. Rasteriser missing
  or failing → text + live URL on web; Telegram may omit cover image but keeps buttons when URL
  works. Expired submit token → friendly error on form post, operator can ask agent to re-render.
  No public URL (local-only gateway) → web live embed still works on loopback; Telegram stays on
  cover + fallback without broken deep links.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | OpenUI tool emits include non-empty fallback text | 100% | tool contract tests, integration fixtures |
| KPI-002 | Web UI live HTML renders without CSP violations on happy-path panels | ≥ 99% of fixture HTML | webchat E2E, manual smoke |
| KPI-003 | Telegram delivery includes cover or fallback when rasterisation unavailable | 100% (no empty replies) | channel delivery tests |
| KPI-004 | Form submit callbacks rejoin the originating turn within callback timeout | ≥ 95% on happy path | gateway callback integration tests |
| KPI-005 | Sanitiser hard-reject and oversize payloads never ship raw agent HTML to clients | 100% | security fixtures, scanner-adjacent tests |
| KPI-006 | Operator can open live panel from Telegram inline keyboard when public URL healthy | Works on reference compose profile | telegram E2E checklist |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-37-openui | OpenUI tool, bridge, sanitiser, CSP, tokens, store, rasteriser, delivery metadata |
| spec-17-gateway | Turn spine, public URL/tunnel deps, callback dispatch into executor |
| spec-18-channel-telegram | Cover messages, inline keyboard, WebApp deep links |
| spec-19-channel-webui | Live HTML embed in WebSocket chat |
| spec-20-voice | Non-visual fallback behavior for OpenUI-accompanied turns |
| spec-21-executor-tier-cd | Tier C/D access to OpenUI tool in toolsets |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new OpenUI surfaces.

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
| 0.9 | 2026-07-07 | Scaffold six-section shell from about-docs pipeline | — |
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full OpenUI product contract | MODIFIED prd-10-generated-ui (structure); traceability aligned to spec-29/17/18/19/20/21 |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should v1 allow any client-side JavaScript in generated HTML beyond sanitiser allowlist? | Alex | 2026-08-01 | resolved — no client JS in v1; live HTML is static allowlist + CSP only |
| OQ-002 | When gateway has no public URL, should Telegram omit deep-link buttons entirely? | Alex | 2026-08-01 | resolved — omit broken URLs; deliver cover + fallback text; web loopback live embed unchanged |
| OQ-003 | Default raster output: PNG screenshot vs PDF cover for Telegram? | Alex | 2026-08-01 | resolved — PNG default; PDF when agent requests `output=pdf` or channel config prefers it |
