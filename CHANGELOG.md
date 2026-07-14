# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every user-visible code change adds a bullet under `## [Unreleased]`; those bullets
are cut into a dated, versioned section at release time.

## [Unreleased]

### Added

- `sevn dashboard set-login-password` stores the Mission Control owner password in the workspace secrets chain and stamps `dashboard.login_password` with a `${SECRET:…}` ref
- README curated templates (`docs/readmes/_templates/<slug>.md`) with outline validation in `sevn readme check`, plus `sevn readme curate <slug>` and a `readme-curator` agent (`.claude`/`.cursor`) that edits a curated README from its source diff via a pluggable runner (`cursor-agent`/`claude`); the `sevn-readme-sync` pre-commit hook auto-curates and stages curated slugs (`SEVN_README_AGENT=0`/`strict` controls, `make readme-curate`)
- README `curated` manifest flag and `sevn readme fingerprint` command so hand-authored subsystem READMEs are stamped without body rewrites
- Advisory `make md-links-check` markdown link checker for tracked docs outside `about-sevn.bot/` (`scripts/check_markdown_links.py`; `ci-quality` tier only)
- Bundled skills, workspace templates, doctor solutions, docs site (`about-sevn.bot/`), readme pipeline (`docs/readmes/`), brand assets, and remaining test suites for the pre-0.0.1 migration import (I5)
- Core runtime packages for the pre-0.0.1 migration import (config, storage, workspace, gateway, agent, security, proxy, and related tests)
- Configurable Second Brain vault path via `second_brain.paths.vault` (CLI setup, Telegram `/config`, onboarding, doctor)
- Witchcraft semantic reindex for the Second Brain vault via `sevn second-brain setup --reindex` and opt-in `witchcraft.reindex_on_startup` (default false)
- Logfire trace export: `tracing.sinks[]` logfire sink with secrets-managed token, `sevn tracing` / `sevn config tracing` CLI, Telegram `/config → Logs` toggle and token form, and Mission Control ops endpoints
- Sub-agents orchestration with level-1 role runs, level-2 workers and specialists, `multi` queue mode, Mission Control and Telegram kill surfaces, and `media_generation` skill via the `media_generator` specialist

### Changed

- README generator refactors L3 prose into `l3_prose.py` with shared `prose`/`symbols` helpers; `lint_summaries` classifies backtick config keys and paths correctly; manifest `l2_flow_suffix` carries optional turn-spine flow suffix text
- README regeneration skips rewriting files when rendered markdown is unchanged, keeping pre-commit manifest sync idempotent
- README `make readme-check` runs manifest `lint_summaries` and validates curated Level 1–2 symbol cites; INDEX status column shows `fresh`/`stale` with a freshness ≠ accuracy note
- README generator drops the hardcoded gateway key-load clause unless `provider_keys_via_proxy` is set on the manifest row; non–turn-spine L2 uses module-graph prose instead of a generic stub
- README L3 deep dives lead with full module docstrings, definition-site markdown links (`#L` anchors), and a unified 12-file symbol window aligned with `extract_module_symbols`
- README LLM profile wiring (root value prop + highlights, guide steps, catalog intro) with offline default unchanged; root README loads `value_prop` from brand TOML and uses live GitHub Actions CI badge
- README offline scaffold quality: turn-spine paragraph gated on `turn_spine`, sentence-boundary truncation, true path-list remainders, docstring-derived module inventory, and narrowed PLACEHOLDER warnings
- README pipeline emits file-relative links and retargets manifest spec paths to `about-sevn.bot/specs/`; link checker resolves paths from each README directory only
- README catalog kinds: manifest `catalog = "modules" | "skills"` with modules cap 200 (+N overflow row) and skills two-table layout (bundled SKILL.md frontmatter + runtime loaders)
- CLI getting-started and config guides drop stale M1/M2 milestone framing; the `sevn config` interactive menu is documented as shipped
- Subsystem README catalog adds `evolution` and `plugins` manifest rows with generated subsystem docs; `browser/` remains documented as out-of-catalog in STANDARD

### Deprecated

### Removed

- `about-sevn.bot/DOC-VS-CODE-ANALYSIS.md` — operator audit belongs in `.ignorelocal/`; its presence broke `about-site-check` for PRs merging `pre-0.0.1`

### Fixed

- Onboarding web wizard accepts `gateway.queue_mode=multi` (matches runtime and spec-36)
- Skills catalog README no longer leaks YAML folded-scalar `>-` markers from bundled SKILL.md frontmatter
- `list your skills` reply no longer truncates skill descriptions at ~80 chars: `compose_list_skills_reply` now prefers the full manifest description from the skill inventory over the clipped Triager routing-index line
- `log_query` accepts a `[start, end]` integer pair and a bracketed `"[start, end]"` string as one inclusive range, instead of rejecting them with an "invalid range" error that leaked into replies; unparseable ranges now mark the diagnostic internal so the model corrects the call rather than quoting it to the user
- Tier-B empty-output retry exhaustion (`Exceeded maximum output retries`) is treated as a deterministic harness failure, skipping the wasteful widened full-index retry that reproduced it and contributed to `executor_timeout_cancel` (the summarize / partial-progress path still runs)
- Tier-B blocks a single tool after `TIER_B_TOOL_FAILURE_HARD_CAP` (5) errors in one turn with a terminal synthesis steer, stopping loops where the model varies arguments each attempt (e.g. guessing CLI subcommands or rewriting `run_code`) that previously ground to the round/timeout budget
- Printing Press skill wrappers (`espn`, `flight_goat`, `movie_goat`, `recipe_goat`) tokenise `--query` on whitespace with quotes respected, so multi-word subcommands like `news soccer fifa.world` reach the CLI as separate argv instead of one bogus subcommand token; `--query` help and `references/espn.md` document the `news <sport> <league>` form (e.g. World Cup = `news soccer fifa.world`)
- Mission Control owner login resolves `${SECRET:…}` dashboard and gateway password refs at boot instead of comparing against placeholder strings
- `sevn dashboard set-login-password` stamps `sevn.json` only after the secrets write succeeds; doctest mocks frozen `GatewayTokenBootstrap.chain` correctly
- README curation: strict pre-commit mode no longer stamps fingerprints when agent curation fails; curator runner subprocess uses minimal env and redacts error output
- README `make readme-scaffold` protects curated bodies: stale slugs get fingerprint-only stamps, never body rewrites or section stubs
- README `_write_entries` doctest uses non-curated `storage` row after gateway manifest curation
- Self-improve trajectory ingest circular import: move `ensure_trace_connection` to `agent.tracing.traces_migrate` and rewrite `docs/readmes/self-improve.md` Level 1–2 with preset-C audit
- CI failures from `secrets.*` gitignore rule excluding `src/sevn/config/sections/secrets.py` (ModuleNotFoundError and mypy `no-any-return` on CI)
- PR #6 CI gates: skip optional `wave-orchestrator/` about-docs paths on public clones, defer spec-36 until F3, remove premature `subagents_registry` doctor catalog entry, and mock CDP attach in onboarding browser context-manager test
- PR #6 CI: vendor changelog validator into tracked `scripts/` + `infra/`, stabilize GitHub webhook dedupe test with file-backed sqlite, disable replay worker in dashboard CSRF gate test to avoid xdist hang, and generate code index before `ci-parity` drift gate

### Security

- Bump setuptools to 83.0.0 to clear PYSEC-2026-3447 from pip-audit
## [0.0.1] - 2026-07-08

First public release on [github.com/sevn-bot/sevn](https://github.com/sevn-bot/sevn).

### Added

- Multi-channel AI gateway (Telegram, Web UI) with tiered agent runtime
- Paired egress proxy, secrets backends, Mission Control dashboard, and workspace memory
- Onboarding wizard (`sevn onboard`), CLI, and `make setup` developer bootstrap
- Full Python package under `src/sevn/` with CI via `make ci`

### Changed

- Repository canonical home moved from the private `sevn-bot/sevn.bot` checkout to the public `sevn-bot/sevn` repo
