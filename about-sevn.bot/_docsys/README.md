# about-docs — schema & architecture

The **about-docs system** is the public, machine-readable home for sevn.bot's
**product requirements** and **technical specifications**, living under
[`about-sevn.bot/`](../). It replaces the private, drifted design-doc trees at
the repo root (kept only as migration source data).

Each document is a **single Markdown file** with two halves:

- **YAML frontmatter** — structured, machine-validated fields. **Code-owned**:
  extracted/derived deterministically from source and validated against a
  published JSON Schema.
- **Markdown body** — narrative prose (purpose, rationale, design, use cases).
  **LLM-owned**: generated and refreshed by a model, reviewed by a human.

This mirrors the dominant 2025–2026 spec-driven-development convention
(GitHub Spec Kit, AWS Kiro, OpenSpec, Anthropic SKILL.md, Google DESIGN.md /
Open Knowledge Format): *YAML for the machine, Markdown for the human/LLM.*

---

## 1. Directory layout

```
about-sevn.bot/
  about-sevn.bot/prd/
    00-main.md                # one doc = frontmatter + body
    04-getting-things-done.md
    README.md                 # generated index (table of all PRDs)
  about-sevn.bot/specs/
    17-gateway.md
    25-cicd-full.md
    README.md                 # generated index (table of all specs)
  _docsys/                    # ← the system (this dir; meta, not a doc)
    README.md                 # this file: schema + architecture
    about-docs.schema.json    # exported JSON Schema (Draft 2020-12); IDE autocomplete
    manifest.toml             # registry: id → kind, sources, status, owner
    allowed-refs.txt          # the reference allowlist (gitignore-style; see §4)
```

The runtime lives in the **sevn package**, reusing the README-pipeline machinery:

```
src/sevn/docs/about/         # Pydantic models, extractor, generator, check gate
  model.py                   # AboutDoc Pydantic model (frontmatter schema)
  loader.py                  # parse/serialise frontmatter + body
  extract.py                 # deterministic field extraction (AST, globs, fingerprint)
  generate.py                # LLM prose (reuses sevn.docs.readme.providers)
  check.py                   # validate + drift + reference gate
  prompts/                   # per-kind prose prompt TOMLs (spec.*, prd.*)
scripts/check_about_docs_refs.py   # standalone reference-guard hook
```

`_docsys/` follows the existing `_sources/`, `_templates/`, `_standards/`
underscore-prefixed meta-dir convention under `about-sevn.bot/`.

---

## 2. Frontmatter schema (v1)

The single source of truth is the **Pydantic model** `AboutDoc` in
`src/sevn/docs/about/model.py`. `make about-docs-schema` exports it to
`_docsys/about-docs.schema.json`; editors pick that up for autocomplete and CI
re-checks that the export is current. `kind` discriminates `prd` vs `spec`.

### 2.1 Common fields

| Field | Type | Req | Owner | Notes |
|-------|------|-----|-------|-------|
| `id` | str | ✓ | human | Stable slug. Pattern `^(prd\|spec)-[a-z0-9-]+$` (e.g. `spec-17-gateway`). Used for **all** doc-to-doc links. |
| `kind` | `prd \| spec` | ✓ | human | Discriminator. |
| `title` | str | ✓ | human | Human title. |
| `status` | `draft \| scaffold \| ready \| done \| rejected` | ✓ | human | Keeps the existing status vocabulary. |
| `owner` | str | ✓ | human | Default `Alex`. |
| `summary` | str (≤ 200 chars) | ✓ | llm | One-line; rendered into the generated index. |
| `last_updated` | date (ISO) | ✓ | code | Set deterministically by `extract`/`generate`; humans don't hand-edit. |
| `sources` | list[source-glob] | ✓ (spec) / opt (prd) | code | Globs under allowed roots (§4) describing the code this doc covers. Drives the **fingerprint** drift gate. |
| `related` | list[doc-id] | opt | human | Cross-links to other about-docs **by `id`**, never by path. |
| `fingerprint` | str (sha256) | managed | code | Digest of `sources` at last regen. `check` fails when source drifts. Managed by `extract`/`generate` — do not hand-edit. |

### 2.2 `spec`-only fields

| Field | Type | Req | Owner | Notes |
|-------|------|-----|-------|-------|
| `parent_prd` | doc-id \| null | ✓ | human | The PRD this spec implements. |
| `depends_on` | list[doc-id] | opt | human | Other specs that must exist first. |
| `build_phase` | str | opt | human | e.g. `Phase 2`. |
| `interfaces` | list[Interface] | opt | code | Public symbols, **extracted from AST**. Each: `{ name, file, symbol? }` where `file` is a real source path under §4. |

### 2.3 `prd`-only fields

| Field | Type | Req | Owner | Notes |
|-------|------|-----|-------|-------|
| `parent_prd` | doc-id \| null | ✓ | human | Umbrella PRD (or null for `prd-00-main`). |
| `specs` | list[doc-id] | opt | human | Implementing specs, by `id`. |
| `personas` | list[str] | opt | human | Named personas referenced in the body. |

### 2.4 Body (LLM-owned prose)

The body is free Markdown, but the generator enforces a recommended H2 outline
per kind (configurable in the prompt TOMLs):

- **spec:** `Purpose` · `Public Interface` · `Data Model` · `Internal Architecture` · `Behavior` · `Failure Modes` · `Test Strategy`
- **prd:** `Problem & Motivation` · `Users & Use Cases` · `Goals` · `Non-Goals` · `Experience` · `Success Metrics`

### 2.5 Example

```markdown
---
id: spec-17-gateway
kind: spec
title: Gateway
status: done
owner: Alex
summary: Per-session turn spine that routes inbound messages to triage and executor tiers.
last_updated: 2026-06-19
parent_prd: prd-01-conversational-experience
depends_on: [spec-13-rlm-triager, spec-14-executor-tier-b]
build_phase: Phase 2
sources:
  - src/sevn/gateway/**
interfaces:
  - name: agent_turn
    file: src/sevn/gateway/agent_turn.py
    symbol: run_turn
related: [spec-18-channel-telegram]
fingerprint: sha256:8f3c…
---

## Purpose

The gateway owns the per-session turn lifecycle …  ← LLM prose, human-reviewed
```

---

## 3. Sync architecture — code-authoritative + drift gate

Code is the source of truth. The doc is regenerated *from* code; CI fails when
the doc no longer matches the code it claims to describe. The reverse direction
(spec → code) is **advisory**: an agent reads the doc as context to guide edits,
but the doc never silently rewrites code.

```
            ┌─────────────────────────── extract (deterministic) ──────────────┐
            │  AST → interfaces[]   globs → file set   sha256 → fingerprint     │
 source ────┤                                                                   ├──► frontmatter
 (src/**,   │  status/owner/related/ids: preserved from existing frontmatter    │
  waveorch) └───────────────────────────────────────────────────────────────────┘
            ┌─────────────────────────── generate (LLM) ───────────────────────┐
 source ────┤  prose body from source + frontmatter (reuses readme providers)  ├──► body
            └───────────────────────────────────────────────────────────────────┘

 check (CI gate)  ─► schema valid? ─► sources resolve? ─► fingerprint current?
                  ─► references legal (§4)? ─► doc-ids resolve? ─► index current?

 context (advisory) ─► emit doc as agent context to steer a code change (spec→code)
```

### CLI / Make surface

| Command | Make target | Role |
|---------|-------------|------|
| `sevn about-docs extract <id>` | `make about-docs-extract` | Refresh **code-owned** frontmatter fields from source; recompute fingerprint. |
| `sevn about-docs generate <id>` | `make about-docs-generate` | Regenerate the **LLM prose** body (offline stub when no key, like the README pipeline). |
| `sevn about-docs check` | `make about-docs-check` | The CI gate (validation + drift + reference + index). **Wired into `ci-docs`.** |
| `sevn about-docs schema` | `make about-docs-schema` | Export + verify `about-docs.schema.json` from the Pydantic model. |
| `sevn about-docs index` | (part of `check`) | Regenerate generated index tables under `about-sevn.bot/`. |
| `sevn about-docs context <id>` | — | Print the doc as agent context (spec→code, advisory). |

**Drift loop (authoring):** edit code → `extract` → `generate` → review the prose
diff → commit. **Drift loop (CI):** `check` fails with *"stale: run extract/generate"*
when source moved under a doc's `sources` without the doc being regenerated.

---

## 4. Reference rule (the hook + `allowed-refs.txt`)

Goal: a clone of the public repo must never hit a dangling reference. **Which
folders a doc may reference is data, not code** — it lives in a single
gitignore-style allowlist file, `_docsys/allowed-refs.txt`, that the hook reads.
Edit that file to widen/narrow the allowed roots; no code change needed.

### 4.1 `allowed-refs.txt`

One pattern per line, gitignore glob syntax. `#` comments and blank lines ignored.
A trailing `/` or `/**` means "anything under this folder". Patterns match
**file-path references** found in a doc (markdown link targets, `sources`,
`interfaces[].file`). The system seeds it on first run with:

```gitignore
# about-docs reference allowlist — folders/paths a published doc may cite.
# Gitignore glob syntax. The hook (scripts/check_about_docs_refs.py) reads this.
# Doc-to-doc links (by id) and https:// URLs are always allowed and not listed here.

src/**                 # sevn source — cited by sources / interfaces[].file
wave-orchestrator/**   # waveorch source
about-sevn.bot/**      # assets, sibling docs, this system
```

### 4.2 What the hook enforces

Beyond the file-path allowlist, two reference kinds are **always** legal and are
**not** file paths (so they are never listed in `allowed-refs.txt`):

- **Other about-docs by `id`** (via `related` / `specs` / `parent_prd` /
  `depends_on`) — the generator resolves an `id` to its rendered link; raw `.md`
  paths to other docs are **forbidden**.
- **External `https://` URLs**.

`scripts/check_about_docs_refs.py` (scoped via `.pre-commit-config.yaml` to
`about-sevn.bot/prd/**` and `about-sevn.bot/specs/**`) fails a doc when a cited
file path (a) does not match any `allowed-refs.txt` pattern, or (b) matches but
does **not resolve to a real file** on disk:

| Allowed (matches `allowed-refs.txt` + exists) | Forbidden |
|-----------------------------------------------|-----------|
| `src/sevn/gateway/agent_turn.py` | gitignored design-doc trees (not in allowlist) |
| `wave-orchestrator/src/waveorch/engine.py` | `prompts/…`, `examples/…`, any path outside the allowlist |
| `[Telegram](spec-18-channel-telegram)` (by id) | `[Telegram](18-channel-telegram.md)` (by path) |
| `https://example.com` | `src/sevn/gone.py` (allowed root but file missing) |

This generalises the existing `scripts/check_no_design_doc_refs.py` (a hardcoded
denylist) into a **file-driven allowlist** plus a *must-resolve* check; the two
hooks share `find_violations`-style structure.

---

## 5. Validation stack

- **Runtime:** `AboutDoc` Pydantic model validates every doc's frontmatter on load.
- **Published schema:** `make about-docs-schema` exports Draft 2020-12 JSON Schema
  to `_docsys/about-docs.schema.json`; CI fails if the checked-in copy is stale
  (same pattern as `infra/sevn.schema.json` / `make config-schema`).
- **Editor DX:** point your editor's YAML/JSON-Schema association at
  `about-docs.schema.json` for frontmatter autocomplete and inline errors.
- **Gate composition:** `make about-docs-check` joins `ci-docs`; never run
  mid-wave full `make ci` — use `make ci-affected`.

---

## 6. Relationship to existing pipelines

This system deliberately **reuses**, not forks, the repo's doc machinery:

| Need | Reused from |
|------|-------------|
| Source-glob expansion + `sha256` drift digest | `sevn.docs.readme.fingerprint` (`expand_source_globs`, `compute_digest`) |
| LLM vs offline prose providers | `sevn.docs.readme.providers` (`build_provider`, prompt TOMLs) |
| Manifest registry pattern | `sevn.docs.readme.manifest` (`manifest.toml`, `source_globs`) |
| Reference-guard hook shape | `scripts/check_no_design_doc_refs.py` |
| Schema-export gate pattern | `make config-schema` / `infra/sevn.schema.json` |
| Static-data → template render | `about-sevn.bot/_sources` + `_templates` + `scripts/build_about_site.py` |

See the about-docs-system wave plan in local design docs for the build order.
