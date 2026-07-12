# 0001. Adopt mattpocock/skills into spec-kit-wave

**Status:** Accepted
**Date:** 2026-07-09
**Source:** [`docs/mattpocock-skills-integration.md`](../../docs/mattpocock-skills-integration.md) §5.5

## Context

[`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT) offers several prompt-only Claude Code
skills (`wayfinder`, `grilling`, `handoff`, `diagnosing-bugs`, `domain-modeling`, `codebase-design`,
`improve-codebase-architecture`) with no sevn equivalent. We adopted and adapted a subset into
`spec-kit-wave`, sevn's spec/wave-file pipeline kit, rather than vendoring them uncritically or building
parallel infrastructure. The full analysis lives in `docs/mattpocock-skills-integration.md`; this ADR
records only the resolved decisions (§5.5) so they aren't re-litigated wave to wave.

## Decisions

| # | Decision |
|---|----------|
| D1 | wayfinder tracker = **local-markdown** under `spec/<slug>/wayfinder/` (`MAP.md` + `tickets/NNNN-<slug>.md`); frontier computed by the skill, not a tracker UI. No GitHub/`gh` coupling. |
| D2 | `improve-codebase-architecture` = import + adapt; report phase rewritten to self-contained, no-CDN HTML via `render_report.py` (replaces the upstream Tailwind/Mermaid-CDN scaffold). |
| D3 | glossary → `about-sevn.bot/GLOSSARY.md`; ADRs → `about-sevn.bot/decisions/NNNN-*.md`; **non-published** — never added to `about-sevn.bot/_docsys/manifest.toml`, and `decisions/**` kept out of `_docsys/allowed-refs.txt`. Paths are read from `skw.toml [context]`, never hardcoded in a skill. |
| D4 | Integration home = **spec-kit-wave**. Skills live at `skills/*/SKILL.md`; harvested guidance lands in `agents/*.md` + `prompts/*.md`. `.cursor/skills/` and `.claude/skills/` are optional install targets via `make install-skills`, not separate canonicals. |
| D5 | Kit is Python-first: the upstream bash `hitl-loop.template.sh` is ported to `hitl_loop.py`; the report generator is `render_report.py`. Helper scripts are stdlib-only Python (or `sh` for install glue). |

## Consequences

- `spec-kit-wave/skw.toml` carries a `[context]` table (`glossary`, `decisions_dir`) and a `[wayfinder]`
  table (`maps_dir`) so the kit stays portable across host repos; `spec-kit-wave/scripts/context_paths.py`
  resolves them for skills loaded raw by an IDE (no `skw` package on `sys.path`).
- `about-sevn.bot/GLOSSARY.md` and `about-sevn.bot/decisions/` exist but are intentionally **not** wired
  into the about-site build — see [`decisions/README.md`](README.md).
- Later waves (1–5) add the adopted skills, harvested `agents/`/`prompts/` guidance, and the
  `make install-skills` / `make wayfinder` targets; see the wave plan for the scope owned by each wave.
