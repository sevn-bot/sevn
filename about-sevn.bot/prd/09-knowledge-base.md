---
id: prd-09-knowledge-base
kind: prd
title: Knowledge Base — PRD
status: ready
owner: Alex
summary: Without accumulated knowledge, every research thread starts at zero—operators
  need a provenance-backed wiki vault the assistant can search and cite in chat.
last_updated: '2026-07-12'
fingerprint: sha256:12c8243b0fcc82e791221e55eb0e0bf9567ac67714950e6a56b301a790a18944
related: []
sources:
- src/sevn/second_brain/**
parent_prd: prd-00-main
depends_on: []
build_phase: null
interfaces: []
specs:
- spec-27-second-brain
personas:
- operator
prd_profile: standard
---

## Problem & Motivation

A daily-driver AI loses most of its value when it has to start from zero on every research
thread. *"What did we say about the rate-limiting RFC last week?"* — without an accumulated
knowledge layer, the operator re-reads sources, re-summarises threads, or trusts a hallucinated
recall. Session memory (`MEMORY.md`, LCM compaction) helps with **who you are** and recent
context; it is the wrong shape for **curated research artifacts** with links, provenance, and
Obsidian-compatible files the operator can edit offline.

- **Who:** Self-hosted operators who run multi-day research, RFC reviews, project notes, or
  personal learning threads and want the assistant to **remember the corpus**, not just the last
  few turns.
- **Pain:** Chat-only recall is ephemeral and opaque. External note apps hold the truth but the
  bot cannot search them unless the operator copy-pastes. Without provenance, the assistant
  cannot point back to the raw source when challenged.
- **Why now:** sevn.bot already ships a Karpathy-style **Second Brain** vault (raw → wiki
  ingest, lint, search tools) and Mission Control knowledge surfaces—this PRD makes the
  **product contract** for accumulated knowledge explicit and separates it from personality
  memory (prd-02-personality-and-memory).

## Users & Use Cases

| ID | Persona | Trigger | Outcome |
| --- | --- | --- | --- |
| UJ-001 | Research operator | Finishes reading a long doc or thread | Source lands in `raw/`; structured wiki page exists with provenance the assistant can cite |
| UJ-002 | Returning operator | Asks about a topic discussed days ago | Assistant searches the vault and answers with wiki-backed context—not a blank slate |
| UJ-003 | Obsidian user | Edits notes locally and syncs the vault | Bidirectional sync resolves conflicts safely; bot reads the same wiki the operator sees |
| UJ-004 | Operator auditing trust | Wants to verify a claim | Assistant or Mission Control surfaces which wiki page and raw source backed the answer |

**Narrative:**

- **UJ-001 — Capture a research thread:** The operator drops a URL or file into `raw/`, runs
  ingest (skill script or agent tool flow), and gets an OKF-style wiki page plus index/log
  updates. The next chat turn can call `second_brain_query` or `wiki_search` instead of
  re-uploading the document.
- **UJ-002 — Recall without re-explaining:** A week later the operator asks about rate-limiting
  trade-offs. The triage/executor tier searches the vault first, returns an answer grounded in
  the filed wiki page, and names the slug—not a vague "I think we discussed this."
- **UJ-003 — Obsidian as editor of record:** The operator maintains the vault in Obsidian;
  sevn reads the synced tree. Merge conflicts surface as operator-visible errors with a git
  merge path rather than silent overwrites.
- **UJ-004 — Provenance check:** From Telegram or Mission Control Knowledge, the operator opens
  the wiki page, follows links to the ingest stub and raw hash, and confirms the assistant did
  not invent the citation.

## Goals

- **FR-001:** The product shall provide an **opt-in Second Brain vault** per workspace with
  per-scope `raw/`, `wiki/`, and `outputs/` trees the operator controls (default off until
  enabled in config).
- **FR-002:** Operators shall **ingest sources into structured wiki pages** via deterministic
  raw→wiki pipelines (skill scripts and native tools) with `index.md` and `log.md` kept current.
- **FR-003:** Wiki pages shall carry **provenance**—links or frontmatter back to raw sources
  and ingest metadata—so answers can be audited, not only believed.
- **FR-004:** The assistant shall **search and read the vault during turns** through registered
  tools (`wiki_search`, `wiki_get`, `second_brain_query`, and related surfaces) when Second Brain
  is enabled.
- **FR-005:** Operators shall **lint the wiki** for OKF/Obsidian conventions (missing `type`,
  orphan links) and receive actionable reports without manual grep.
- **FR-006:** The product shall support **Obsidian bidirectional sync** semantics: external
  edits merge safely; conflicts require explicit operator resolution—not silent clobber.
- **FR-007:** Mission Control shall expose a **Knowledge** view of vault layout, wiki index,
  and scope status when the dashboard is enabled—read-only inspection, not a second editor.
- **FR-008:** Second Brain shall remain **separate from session memory** (LCM, `MEMORY.md`,
  dreaming)—curated wiki knowledge does not replace personality memory or cross into dreaming
  promotion rules.

## Non-Goals

- Replacing Obsidian, Notion, or a full PKM suite—Second Brain **augments** the assistant;
  the operator may still use any external editor that syncs into the vault.
- Auto-ingesting the entire web or mailbox without operator curation—ingest is **intentional**
  (URL fetch, file drop, agent-file flows), not ambient surveillance.
- Storing provider API keys or secrets in wiki pages—vault content follows workspace redaction
  and `.llmignore` discipline (see prd-03-trust-and-control).
- Corporate multi-user wiki permissions, ACL matrices, or SaaS-style sharing—v1 is a **single
  operator workspace** vault.
- Full semantic search as a hard dependency—keyword/index-first search ships first; optional
  semantic indexing (e.g. witchcraft bridge) is an enhancement, not a gate for basic recall.
- Using the knowledge base as the **code-understanding** index—repo graphs and MYCODE live under
  prd-08-coding-companion, not this PRD.

## Experience

- **Happy path (enable):** Operator sets `second_brain.enabled` in config (onboarding capability
  or manual edit). Vault appears under the workspace. Optional `second_brain.paths.vault` points
  at an existing Obsidian folder (CLI `sevn second-brain setup --vault`, Telegram `/config`, or
  onboarding folder picker) without symlinks. They ingest a source, see a new wiki page
  and index line, and ask a follow-up question in Telegram—the bot searches the vault and cites
  the page.
- **Happy path (Obsidian):** Operator opens the vault folder in Obsidian, edits wikilinks and
  concept pages, syncs back. The bot's next query sees the updated tree after lint passes.
- **Operator controls:** Enable/disable Second Brain; per-scope roots; skill scripts for ingest,
  lint, and file-back; optional legacy ingest stub gated off by default; witchcraft semantic
  mode when installed and allowed.
- **Degraded path:** Second Brain disabled → tools absent, Mission Control shows disabled state,
  chat falls back to session memory only. Lint failures → operator-visible report, bot abstains
  from citing broken pages. Sync merge conflict → clear error with merge-needed guidance, not
  partial silent corruption. Search miss → assistant says it found nothing in the vault rather
  than confabulating prior research.

## Success Metrics

| ID | Metric | Target | Source |
| --- | --- | --- | --- |
| KPI-001 | Ingest of a fixture raw source produces a wiki page + index/log update | 100% on happy path | second_brain integration tests |
| KPI-002 | `second_brain_query` / `wiki_search` return the filed page for a known slug | ≥95% on fixture corpus | tool + skill tests |
| KPI-003 | Wiki lint catches missing OKF `type` and orphan links in fixture trees | 100% of seeded violations reported | lint_local tests |
| KPI-004 | Mission Control Knowledge API returns vault overview when enabled | Operator sees scopes + index without filesystem access | MC knowledge E2E |
| KPI-005 | Second Brain disabled → no vault tools registered | Zero tool exposure when `second_brain.enabled` is false | gateway boot tests |

## Traceability

### Implementing Specs

| Spec id | Scope |
| --- | --- |
| spec-27-second-brain | Vault layout, raw→wiki ingest, OKF wiki engine, search/query tools, lint, Obsidian merge path, witchcraft bridge |

Downstream: **PRD → specify → plan → tasks** in spec-kit-wave for net-new knowledge features.
Mission Control Knowledge panels inherit product intent from this PRD (see prd-07-mission-control).

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
| 1.0 | 2026-07-08 | Migrated to spec-kit-wave PRD standard; full Second Brain product framing | MODIFIED prd-09-knowledge-base (structure); traceability aligned to spec-27-second-brain |

## Open Questions

| ID | Question | Owner | Due | Status |
| --- | --- | --- | --- | --- |
| OQ-001 | Should PDF URL ingest ship in v1 or stay preview until v1.1? | Alex | 2026-08-01 | resolved — preview only for v1; operator uses raw file drop + ingest; PDF URL deferred |
| OQ-002 | Default vault scope: single shared wiki vs per-user scopes for multi-device operators? | Alex | 2026-08-01 | resolved — shared workspace vault with optional scope roots; multi-tenant scopes deferred |
| OQ-003 | Require witchcraft semantic search before marking Second Brain "daily-driver ready"? | Alex | 2026-08-01 | resolved — keyword/index-first search is sufficient for v1; semantic mode optional enhancement |
