# sevn.bot README pipeline — authoring standard

> **Status:** Wave 0 contract (2026-06-13). Locked after operator REVIEW GATE approval.
> **Normative for:** `docs/readmes/*.md`, root `README.md`, generator (`src/sevn/docs/readme/`), CI gate (`make readme-check`).
> **Inputs:** merged from the readme-system reference pack (GFM/HTML, templates, generators, doc principles, MarkedDown badges).

This document is the **verbatim authoring contract** for the README pipeline. Later waves implement it; they do not relitigate structure, profiles, or brand palette.

---

## A. Document set & layout

```
README.md                      ← root: brand + value prop + highlights + map (high-level only)
docs/readmes/
  STANDARD.md                  ← this standard (authoring contract) incl. profile schemas (§C0)
  INDEX.md                     ← generated catalog: every README + 1-line summary + profile + freshness status (`fresh` / `stale`)
  manifest.toml                ← README ⇄ profile ⇄ source-globs ⇄ spec links ⇄ owner tier
  _fingerprints.json           ← stored source fingerprints (staleness gate)
  _mock-root-header.md         ← REVIEW GATE mock header snippet (operator preview; not shipped in W5)
  gateway.md  agent.md  channels.md  tools.md  skills.md  ui-mission-control.md
  security.md  secrets.md  proxy-egress.md  tracing.md  memory-context.md
  second-brain.md  voice.md  triggers.md  config-workspace.md  storage.md
  code-understanding.md  self-improve.md  integrations.md  onboarding.md
  …                            ← curated set in manifest.toml (≈18–22 slugs, NOT one-per-package)
docs/brand/
  README.md                    ← brand usage for docs (reuses styles/sevn tokens)
  badges.md                    ← canonical shields.io badge-button palette + snippets
  assets/                      ← logo refs + hero/demo/diagram/social-card placeholders + MANIFEST.md
```

**Locked decision:** centralized `docs/readmes/` tree (not co-located per-package). `manifest.toml` is the bridge: each README declares its **profile** (§C0) and **source globs** it covers, so the gate validates against the right schema *and* answers “did this code change without the doc?” — without README files living inside every package.

**Every generated README** must include a generation stamp immediately after the opening (HTML comment):

```markdown
<!-- generated: do not edit by hand; run `sevn readme update <slug>` -->
```

**Curated READMEs** (`curated = true` in `manifest.toml`) are hand-authored at Levels 1–2 and use a different stamp:

```markdown
<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint <slug>` -->
```

The pipeline **never overwrites** curated bodies during `make readme`, `make readme-scaffold`, `sevn readme generate --all`, or the `sevn-readme-sync` pre-commit hook — those paths only refresh `_fingerprints.json` via `sevn readme fingerprint`. To regenerate a curated body deliberately, run `sevn readme update <slug> --force`. Non-curated READMEs use `sevn readme update <slug>` after source changes.

### A1. Templates & agent curation (curated entries)

Every curated entry maps to a **template** in [`_templates/`](_templates/) — `_templates/<slug>.md` by convention, or an explicit `template = "…"` manifest key. Templates pin the *outline* (the required heading skeleton) and are validated by `sevn readme check`: the README must contain every template heading, at the same level, in the same order (a subsequence — extra per-module `###` sections are allowed). See [`_templates/README.md`](_templates/README.md) for the markup contract (`<!-- fill: … -->` guidance, `<!-- generated -->` pipeline-owned regions, `# <Title>` wildcards).

Rather than hand-editing curated prose after a code change, drive the **`readme-curator`** agent:

```
sevn readme curate <slug>            # feeds the source diff + template + README to cursor-agent/claude, then validates
sevn readme curate <slug> --dry-run  # print the assembled prompt only (no runner)
make readme-curate SLUG=<slug>       # curate + git add
```

The runner is pluggable (auto-detects `cursor-agent`/`claude`; override with `--runner` or `SEVN_README_RUNNER`). The `sevn-readme-sync` pre-commit hook, when a curated slug's source is staged, runs the curator **inline** (auto-edit & stage) and re-stamps the fingerprint. Controls:

- `SEVN_README_AGENT=0` — skip the agent, stamp-only (the pre-`curate` behaviour).
- `SEVN_README_AGENT=strict` — fail the commit on agent error or template drift.
- When no runner is available (offline / CLI missing) or the agent errors, the hook falls back to a fingerprint-only stamp — curated prose is never clobbered, and the commit proceeds.

---

## B. Root README skeleton (`profile: root`)

Order, with the GitHub-safe idiom for each:

1. `<a name="readme-top"></a>` anchor.
2. **Centered brand header** — `<div align="center">` with theme-aware logo (`<picture>` + `prefers-color-scheme` → `logo-all-white.svg` dark / `logo-primary.jpg` light from `styles/sevn/style/logos/`), wordmark, one-line tagline, and an **action badge-button row** (Docs · Quick Start · Architecture · Report Bug) using `docs/brand/badges.md`.
3. **Status badge row** — CI (live GitHub Actions badge: `https://github.com/sevn-bot/sevn/actions/workflows/ci.yml/badge.svg` → workflow page), license (MIT), Python 3.12+, package version, release channel — shields.io `for-the-badge` for non-CI badges, reference-style links at EOF.
4. **Hero** — product screenshot/GIF placeholder (`docs/brand/assets/hero.png` until replaced).
5. **Value prop** — 2–3 sentences (the “one bot you own” pitch).
6. **Collapsible TOC** — `<details><summary>`.
7. **Highlights** — feature grid (badge-prefixed bullets).
8. **Architecture at a glance** — one diagram placeholder + 3-bullet summary + link to `docs/readmes/INDEX.md` and `about-sevn.bot/ARCHITECTURE.md` (or `evolution/ARCHITECTURE.md`).
9. **Subsystem map** — table linking each `docs/readmes/*.md` with its one-line summary (generated from `manifest.toml`).
10. **Quick start** (TL;DR), **Security model** (condensed + link), **Install**, **Docs by goal**, **Community**, **License**, **Acknowledgements**.
11. Reference-style link/badge definitions + back-to-top.

Root README stays **high-level + links**. Deep detail lives in subsystem READMEs, never inlined at root.

---

## C0. README profiles (registry)

Not every README is a subsystem deep-dive. `manifest.toml` assigns each file a `profile`; the checker (W4) loads the matching schema below.

| Profile | Used for | Required sections | Tiers? | Symbol-ref check | Other checker fields |
|---------|----------|-------------------|--------|------------------|----------------------|
| `root` | root `README.md` | brand header · status badges · TOC · highlights · subsystem map · install · license (§B order) | no | no | no Summary required |
| `subsystem` | code subsystem (gateway, agent, security, …) | Summary · `## Level 1 — Overview` · `## Level 2 — How it works` · `## Level 3 — Deep dive` · References (§C) | **yes** | **yes** (L3) | — |
| `index` | `docs/readmes/INDEX.md` | title · generated entry table · freshness note | no | no | `requires_table` |
| `catalog` | inventories (tools, skills, runbooks index) | Summary · generated item table · optional per-item subsections | no | paths only | `requires_table`, `verify_path_refs` |
| `guide` | task/operator docs (onboarding, deployment) | Summary · task/step sections (≥1 `##`) · References | no | optional | `requires_step_sections` |
| `freeform` | one-off READMEs | Summary · GitHub-safe (§E) · links resolve | no | no | — |

**Shared across profiles except `root`:** a `Summary` block at top (see formats below). The root README uses a value-prop paragraph (§B) instead of a Summary block. All profiles must stay GitHub-safe (§E) with resolving relative links/anchors. Placeholders for unbuilt assets → `TODO` warning, not fail.

### Profile schema objects (checker loads these directly)

Each profile is a schema object with these fields:

| Field | Type | Meaning |
|-------|------|---------|
| `required_headings` | `list[str]` | Exact `##` heading text required in order (after Summary). Empty for profiles that only check Summary + generated blocks. |
| `needs_tiers` | `bool` | When true, enforce L1/L2/L3 tier headings (`subsystem` only). |
| `verify_symbol_refs` | `bool` | When true, parse Level 3 for `src/...` paths and optional `Class.method()` symbols; fail if missing. |
| `allow_extra_headings` | `bool` | When true, extra `##` sections beyond `required_headings` are allowed (default true for `subsystem`, `guide`, `freeform`). |
| `requires_summary` | `bool` | When false, skip Summary block requirement (`root` only). |
| `requires_table` | `bool` | When true, require a markdown table (`index`, `catalog`). |
| `requires_step_sections` | `bool` | When true, require at least one task `##` section (`guide`). |
| `verify_path_refs` | `bool` | When true, validate cited `src/...py` paths (`catalog`). |

```yaml
# Canonical profile registry — copy into checker config or load from this section.
profiles:
  root:
    required_headings:
      - "Highlights"
      - "Architecture at a glance"
      - "Subsystem map"
      - "Quick start"
      - "Install"
      - "License"
    needs_tiers: false
    verify_symbol_refs: false
    allow_extra_headings: true
    requires_summary: false

  subsystem:
    required_headings:
      - "Level 1 — Overview"
      - "Level 2 — How it works"
      - "Level 3 — Deep dive"
      - "References"
    needs_tiers: true
    verify_symbol_refs: true
    allow_extra_headings: true

  index:
    required_headings: []
    needs_tiers: false
    verify_symbol_refs: false
    allow_extra_headings: true
    requires_table: true

  # INDEX status column: ``fresh`` means the stored source fingerprint matches the
  # current ``source_globs`` digest; ``stale`` means regenerate or fingerprint.
  # Freshness ≠ semantic accuracy — a ``fresh`` row can still carry a wrong
  # manifest ``summary`` until ``lint_summaries`` (``make readme-check``) passes.

  catalog:
    required_headings: []
    needs_tiers: false
    verify_symbol_refs: false
    allow_extra_headings: true
    requires_table: true
    verify_path_refs: true

  guide:
    required_headings: []
    needs_tiers: false
    verify_symbol_refs: false
    allow_extra_headings: true
    requires_step_sections: true

  freeform:
    required_headings: []
    needs_tiers: false
    verify_symbol_refs: false
    allow_extra_headings: true
```

**Summary block formats** (checker accepts any one):

```markdown
> **Summary.** 2–4 sentences…
```

```markdown
## Summary

2–4 sentences…
```

Adding a profile = manifest entry + schema object here — not new checker code.

---

## C. `subsystem` profile skeleton (three-tier model)

```markdown
<!-- generated: do not edit by hand; run `sevn readme update <slug>` -->
# <Subsystem> — <one-line role>

[badge-button row: spec · source dir · related READMEs]

> **Summary.** 2–4 sentences: what this subsystem is, why it exists, and where it
> sits in the turn spine. (Always present, always at top.)

## Level 1 — Overview (non-technical)
Plain-language: what it does and why it matters to an operator. No jargon
without a definition. (Documentation-Compendium inclusivity rules apply.)

## Level 2 — How it works (technical)
Medium depth: key components, the main data/flow, configuration surface,
how it connects to neighbours. Diagrams/tables welcome.

## Level 3 — Deep dive (low-level, technical)
Exhaustive: module-by-module, key classes/functions, invariants, edge cases,
extension points. **Must cite real paths** — `src/sevn/<sub>/<file>.py` — and,
where stated, `Class.method()` symbols. The checker verifies these exist.

## References
Specs, runbooks, related READMEs (reference-style links).
```

**Documentation-Compendium principles** (apply to all profiles):

- Accessible, conversational voice; define jargon on first use.
- Progressive structure: gentle introduction before deep dives.
- Gender-neutral pronouns; avoid idioms; abundant CLI examples.
- Link supplementary detail; inline what the reader needs for the current task.

---

## D. Brand / badge palette

Source of truth: `styles/sevn/style/tokens/colors.css` and `styles/sevn/style/logos/`. **Do not invent a new palette.**

| Role | Hex | CSS token | Badge use |
|------|-----|-----------|-----------|
| Primary CTA | `#5fb1f7` | `--sevn-primary` | Docs, Quick Start, primary actions |
| Secondary | `#2a7fc6` | `--sevn-primary-dark` | Architecture, secondary nav |
| Critical/action only | `#ff3b3b` | `--sevn-accent` | Security, kill-switch, Report Bug — sparingly |
| Base/dark | `#0c0a09` | `--sevn-base-050` | Logo backgrounds, dark badges |
| Success | `#6a9c78` | `--sevn-success` | Status: passing/stable |
| Warning | `#c89a52` | `--sevn-warning` | Status: pre/WIP |

Canonical badge-button form (MarkedDown/shields.io, reference-style):

```markdown
[![Docs][docs-badge]][docs-link]   [![Architecture][arch-badge]][arch-link]
<!-- … EOF … -->
[docs-badge]: https://img.shields.io/badge/Docs-5fb1f7?style=for-the-badge&logo=readthedocs&logoColor=white
[docs-link]: docs/readmes/INDEX.md
```

Full snippets: `docs/brand/badges.md`.

---

## E. GitHub-safe rendering allowlist

**ALLOWED:** `<picture>` + `prefers-color-scheme`, `<details>/<summary>`, `<kbd>`, `<sub>/<sup>/<ins>`, `<div align>`, `<img width>`, GFM alerts `> [!NOTE|TIP|IMPORTANT|WARNING|CAUTION]`, task lists, footnotes, reference-style links, SVG `<foreignObject>` for custom CSS inside SVG.

**FORBIDDEN** (silently stripped — linter rejects):

- `<script>`, `<iframe>`, inline `style=`, top-level `<style>` (outside SVG), `class=`-CSS, event handlers, `<form>/<input>`, `href="javascript:"`.

Relative image paths must resolve within the repo. External URLs allowed when hotlinking is acceptable.

---

## F. Generation model & architecture contract

Two-stage, section-by-section, provider-agnostic, offline-capable:

```
repo scan (pyproject.toml · sevn.json · CLAUDE.md · about-sevn.bot/specs index · graphify-out/
           · subsystem source_globs from manifest.toml)
   → structured context per README
   → per-section render:  offline = Jinja2 template only
                          llm     = template + section prompt + context → Transport (via egress proxy)
   → assemble → write file (+ stamp source fingerprint into _fingerprints.json)
```

### Module layout (`src/sevn/docs/readme/`)

Ships in the wheel; unit-tested; invoked by `sevn readme` CLI (W3). The Claude skill is a **thin wrapper** — never a fork of this logic.

| Module / path | Responsibility |
|---------------|----------------|
| `__init__.py` | Public exports: `PROFILE_TEMPLATES`, `render_profile`, `render_all_fixtures`, `templates_dir`, `prompts_dir`. |
| `manifest.py` | Parse `manifest.toml`; validate profile names against §C0 registry. |
| `scanner.py` | Repo/metadata scan: `pyproject.toml`, `sevn.json`, `CLAUDE.md`, specs index, optional `graphify-out/graph.json`, manifest `source_globs` → structured context dict. |
| `model.py` | Section/tier data model + assembly (Summary + L1/L2/L3 per profile). |
| `fingerprint.py` | Compute/read/write source fingerprints; `_fingerprints.json` I/O. |
| `providers.py` | LLM abstraction: **offline** (template-only) + **llm** via egress proxy + `Transport`. Generator **never** reads provider API keys. |
| `render.py` | Section-by-section render → assemble → write; picks template by profile; GitHub-safe allowlist (§E). |
| `check.py` | Structure/validity per profile + staleness gate (W4) + curated template validation (§A1). |
| `templates.py` | Per-README outline validation against `docs/readmes/_templates/<slug>.md` (§A1). |
| `curate.py` | Agent-driven curation: source diff → prompt → pluggable runner (`cursor-agent`/`claude`) → validate (§A1). |
| `templates/` | Jinja2: `root.md.j2`, `subsystem.md.j2`, `index.md.j2`, `catalog.md.j2`, `guide.md.j2`, `freeform.md.j2`. |
| `prompts/` | One file per section/tier (not hardcoded in Python). |

### Section-prompt directory (`src/sevn/docs/readme/prompts/`)

Mirrors readme-ai’s `prompts.toml` approach — tunable without code changes.

| Prompt file | Used for |
|-------------|----------|
| `summary.toml` | Summary block (`subsystem`, `catalog`, `guide`, `freeform`). |
| `overview.toml` | Subsystem Level 1. |
| `how-it-works.toml` | Subsystem Level 2. |
| `deep-dive.toml` | Subsystem Level 3 (path/symbol citations). |
| `root-valueprop.toml` | Root value prop paragraph (`profile: root`, LLM mode). |
| `highlights.toml` | Root highlights grid (`profile: root`, LLM mode). |
| `catalog-table.toml` | Catalog profile table intro (`profile: catalog`, LLM mode). |
| `guide-steps.toml` | Guide profile task sections (`profile: guide`, LLM mode). |

`profile: index` stays offline-only (no section prompts). Offline mode skips LLM and uses template stubs only.

### Transport / egress proxy integration

LLM mode routes through the **paired egress proxy** (`about-sevn.bot/specs/07-egress-proxy.md`) using existing `Transport` shapes (`about-sevn.bot/specs/05-llm-transports.md`):

- Config: `sevn.json → docs.readme.transport` (enum: `anthropic`, `openai_chat`, `openai_responses`, `bedrock_converse`).
- Config: `docs.readme.model` — LiteLLM model id resolved like other gateway agents.
- HTTP: proxy base from `SEVN_PROXY_URL` / `ProcessSettings.proxy_url`; per-run `SEVN_SESSION_TOKEN` when invoked from gateway context; CLI uses operator proxy URL from env/config.
- **No provider keys in the generator process** — same security spine as triage/executors.

Offline mode (`offline_default: true`, `--offline`) never opens an LLM connection.

### Fingerprint format (`docs/readmes/_fingerprints.json`)

Staleness gate idiom matches `make mission-control-docs-check` / `make telegram-menu-docs-check`: recompute digest from source; compare to stored value; fail on mismatch with fix command.

**Algorithm:**

1. For each manifest entry, expand `source_globs` relative to repo root.
2. Collect matching files (exclude `__pycache__`, `.pyc`, binary noise — same hygiene as skills registry fingerprint).
3. Build stable lines: `relative_path<TAB>sha256(file_bytes)` sorted by path.
4. Digest = `sha256("\n".join(lines)).hexdigest()` (lowercase hex, 64 chars).

**Stored JSON schema (`version: 1`):**

```json
{
  "version": 1,
  "entries": {
    "gateway": {
      "algorithm": "sha256_glob_aggregate",
      "digest": "64-char-hex",
      "computed_at": "2026-06-13T12:00:00Z",
      "source_globs": ["src/sevn/gateway/**"]
    }
  }
}
```

- `entries` keys = manifest `slug`.
- Regeneration updates `digest` and `computed_at` for touched slugs.
- Checker fails when live digest ≠ stored digest and the README body was not regenerated in the same change.

### `sevn.json → docs.readme.*` config schema

Draft (added to `infra/sevn.schema.json` at W0; loaded at W3):

```json
{
  "docs": {
    "readme": {
      "enabled": true,
      "manifest_path": "docs/readmes/manifest.toml",
      "offline_default": true,
      "transport": "anthropic",
      "model": "claude-sonnet-4-6",
      "temperature": 0.2
    }
  }
}
```

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `true` | Master toggle for generator + gate. |
| `manifest_path` | `docs/readmes/manifest.toml` | Curated README set. |
| `offline_default` | `true` | Default to template-only (CI-safe). |
| `transport` | `anthropic` | Transport shape for LLM mode. |
| `model` | `claude-sonnet-4-6` | LiteLLM model id for `--llm`. |
| `temperature` | `0.2` | LLM sampling temperature. |

Explicit operator action for LLM spend: `sevn readme generate --llm`. CI uses `offline_default: true` only.

### Keeping docs current (W4 gate)

`make readme-check` performs:

1. **Structure/validity** — every manifest README exists; profile schema (§C0); GitHub-safe checks in `render.py` (§E); link resolution. Placeholders → `TODO` warning.
2. **Staleness** — fingerprint mismatch → fail. Curated entries (`curated = true`): run `sevn readme fingerprint <slug>` after reviewing the body. Generated entries: run `sevn readme update <slug>`.

Scaffold path: `make readme-scaffold` (parallel to `*-docs-scaffold`). Curated slugs are fingerprint-only on scaffold; generated slugs are regenerated and stubbed as needed.

### Out-of-catalog packages (D19)

Some load-bearing trees intentionally have **no** manifest row. They are documented elsewhere rather than duplicated in the README pipeline:

| Package | Rationale | Where to read |
|---------|-----------|---------------|
| `src/sevn/browser/` | Optional **`browser`** / **`browser-cdp`** extras; Playwright/CDP skills and recipes ship under bundled skills — not a core subsystem catalog entry. | `CLAUDE.md` optional extras; bundled skills (`playwright-browser`, `x-use`, …); `about-sevn.bot/specs/12-skills-system.md` |

Adding a manifest row for an out-of-catalog package requires an operator decision at a catalog-coverage gate — default is the table above.

### Operator clarity (§9.4)

Cross-cutting topics that confuse readers if only implied by generated prose:

| Topic | Meaning | Authoritative README |
|-------|---------|---------------------|
| Secrets gateway vs egress proxy | Channel/gateway/MC credentials resolve in the **gateway**; LLM provider keys resolve on the **egress proxy**. | [`secrets.md`](secrets.md) Level 2 — *Gateway vs egress proxy* |
| Channel stub vs production | Telegram/WebChat are production paths; Discord/Slack are narrower stubs until specs mature. | [`channels.md`](channels.md) Level 2 — *Stub vs production adapters* |
| INDEX `fresh` status | Fingerprint match only — **not** semantic accuracy. Run `make readme-check` for summary lint + symbol validation. | This file §C0 INDEX note; [`INDEX.md`](INDEX.md) Summary |
| Schema vs Pydantic | `infra/sevn.schema.json` may lag typed section models (`provisioning`, `coding_agents`, …). | [`config-workspace.md`](config-workspace.md) Level 2 — *Schema vs Pydantic gaps* |

---

## REVIEW GATE artefact

Operator preview of the root brand header: `docs/readmes/_mock-root-header.md`.

---

## Changelog

| Date | Wave | Change |
|------|------|--------|
| 2026-07-14 | W10 | D19 catalog coverage: ``evolution`` + ``plugins`` subsystem rows; ``browser/`` out-of-catalog table; §9.4 operator-clarity pointers. |
| 2026-07-14 | W4 | Manifest summary sweep (D10): seven wrong `summary` rows rewritten; `integrations.specs` → `29-cursor-cloud-agent`; §F public-export list + §C0 profile-schema block reconciled to live code. |
| 2026-07-14 | W3 | INDEX status column uses ``fresh`` (not ``ok``); Summary documents freshness ≠ semantic accuracy; ``lint_summaries`` gate (D7). |
| 2026-07-13 | W9 | §A1 curated templates (`_templates/`) + `templates.py` validation in the gate; `sevn readme curate` + `readme-curator` agent; pre-commit auto-edit & stage with `SEVN_README_AGENT` controls. |
| 2026-07-13 | W6 | §B live CI badge; §C0 root Summary exemption; §F module table (`render.py` owns §E checks); prompt-wiring table matches D15 profile map. |
| 2026-07-13 | W2 | §A curated flag semantics, fingerprint-only refresh, header stamp split. |
| 2026-06-13 | W0 | Initial standard from merged references + wave plan §A–F. |
