# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every user-visible code change adds a datestamped bullet under `## [Unreleased]`; those bullets
are cut into a dated, versioned section at release time.

## [Unreleased]

### Added

- [2026-07-16] `make install-snapshot-timer` installs a launchd agent that runs the local gitignored-tree snapshot every 3 hours, so operator-only plans, specs, and agent config are protected on a schedule instead of only on `git push`
- [2026-07-16] Local snapshot backup covers whole gitignored trees (`.ignorelocal`, `spec-kit-wave`, `build-plan-from-review`, `.cursor`, `.claude` agent config, `docs`) and excludes secrets and regenerable indexes (`.env`/`.env.*`, `graphify-out`, `MyCodeGraph`, `.venv`, caches) while keeping `.env.example` templates
- [2026-07-15] PARA/Obsidian-native Second Brain vault layout via `second_brain.layout: "legacy" | "para"` with a configurable `second_brain.para` folder profile (Inbox, Projects, Areas, Resources, Archive, Templates) and non-destructive adoption of existing Obsidian vaults
- [2026-07-15] `sevn second-brain setup --layout {auto,legacy,para}` detects or selects the vault layout, bootstraps PARA role folders and Obsidian templates, and exposes resolved role paths via `sevn config second-brain` and `sevn doctor`
- [2026-07-15] Layout-aware Second Brain ingest, search, Witchcraft indexing, and lint operate across PARA content roots (Inbox/Projects/Areas/Resources) while legacy `wiki/raw/outputs` installs remain byte-for-byte unchanged
- [2026-07-14] `skw spec_validate` and `make spec-check` validate the committed 7-section about-sevn.bot spec format with deterministic 0–100 validity scores (`make docs-score`, folder rollup)
- [2026-07-14] `docs-folder-author` agent (`.cursor/agents/` + `spec-kit-wave/agents/`) validates and updates whole `about-sevn.bot/specs/` or `about-sevn.bot/prd/` folders against code and template rules
- [2026-07-14] Unreleased changelog bullets require a leading `[YYYY-MM-DD]` datestamp enforced by `make changelog-check`
- [2026-07-14] Changelog templates, standards, and author skills under `spec-kit-wave/` document the datestamp contract
- [2026-07-15] `make spec-kit-wave-test` runs the skw pytest suite in `ci-docs` so validator regressions cannot slip through partial iteration
- [2026-07-15] `make ci-affected` triggers `about-docs-check` when `about-sevn.bot/specs/`, `about-sevn.bot/prd/`, or `spec-kit-wave/` paths change
- [2026-07-15] Gateway README Level 3 module inventory lists every gateway subpackage module with docstring prose and symbol anchors for operator and LLM readers
- [2026-07-15] Telegram session mirror paths under `sessions/telegram/chats/` include sanitized group and forum topic titles with `--{id}` suffixes for uniqueness; group titles persist in `telegram_chat_names`; ID-only segments when names are unknown; existing JSONL folders are not moved (#21)
- [2026-07-15] Browser-first `social_media_manager` L2 specialist with per-platform medium under `skills.social_media_manager`, TwexAPI optional on X only, Telegram `/config → Skills → Social Media Manager`, and six-site CDP browser matrix

- [2026-07-14] `skw docs sync` refreshes about-doc frontmatter and scaffolds missing PRD/spec files via `make spec-sync` and `make prd-sync`
- [2026-07-13] `sevn dashboard set-login-password` stores the Mission Control owner password in the workspace secrets chain and stamps `dashboard.login_password` with a `${SECRET:…}` ref
- [2026-07-13] README curated templates (`docs/readmes/_templates/<slug>.md`) with outline validation in `sevn readme check`, plus `sevn readme curate <slug>` and a `readme-curator` agent (`.claude`/`.cursor`) that edits a curated README from its source diff via a pluggable runner (`cursor-agent`/`claude`); the `sevn-readme-sync` pre-commit hook auto-curates and stages curated slugs (`SEVN_README_AGENT=0`/`strict` controls, `make readme-curate`)
- [2026-07-13] README `curated` manifest flag and `sevn readme fingerprint` command so hand-authored subsystem READMEs are stamped without body rewrites
- [2026-07-13] Advisory `make md-links-check` markdown link checker for tracked docs outside `about-sevn.bot/` (`scripts/check_markdown_links.py`; `ci-quality` tier only)
- [2026-07-12] Bundled skills, workspace templates, doctor solutions, docs site (`about-sevn.bot/`), readme pipeline (`docs/readmes/`), brand assets, and remaining test suites for the pre-0.0.1 migration import (I5)
- [2026-07-12] Core runtime packages for the pre-0.0.1 migration import (config, storage, workspace, gateway, agent, security, proxy, and related tests)
- [2026-07-12] Configurable Second Brain vault path via `second_brain.paths.vault` (CLI setup, Telegram `/config`, onboarding, doctor)
- [2026-07-14] Witchcraft semantic reindex for the Second Brain vault via `sevn second-brain setup --reindex` and opt-in `witchcraft.reindex_on_startup` (default false)
- [2026-07-12] Logfire trace export: `tracing.sinks[]` logfire sink with secrets-managed token, `sevn tracing` / `sevn config tracing` CLI, Telegram `/config → Logs` toggle and token form, and Mission Control ops endpoints
- [2026-07-12] Sub-agents orchestration with level-1 role runs, level-2 workers and specialists, `multi` queue mode, Mission Control and Telegram kill surfaces, and `media_generation` skill via the `media_generator` specialist

### Changed

- [2026-07-15] Telegram `/config`, onboarding wizard, and Mission Control Knowledge view expose Second Brain layout selection and resolved PARA role paths instead of assuming legacy `wiki/raw/outputs` folders
- [2026-07-14] The about-docs generator no longer writes `interfaces`, `depends_on`, or `build_phase` into `kind: prd` frontmatter (spec-only keys; aligns with `skw prd-validate`)
- [2026-07-14] `make about-docs-check` chains `make spec-check` and `make prd-check` so CI catches doc regressions; about-docs check rejects specs with `status: done` over scaffold placeholder bodies
- [2026-07-14] Changelog validator canonical implementation lives in `spec-kit-wave/src/skw/changelog_validate.py`; `scripts/changelog_validate.py` is a shim
- [2026-07-15] Gateway README Level 1–2 rewrite uses plain-language operator prose and links FastAPI on first mention for non-technical readers
- [2026-07-15] Gateway package reorganized into 29 domain subpackages (85 modules moved, 10 core modules remain at `src/sevn/gateway/` root); import paths only with no runtime behavior change
- [2026-07-15] `spec-kit-wave` modules and tests carry the full docstring schema with `<Examples:` sections required by `make doctest`

- [2026-07-14] Authored code-true 7-section bodies for nine high-traffic specs (`00-foundation`, `01-system-overview`, `02-config-and-workspace`, `10-schema-ontology`, `11-tools-registry`, `13-rlm-triager`, `14-executor-tier-b`, `17-gateway`, `25-cicd-full`); remaining specs stay honestly `scaffold` with `## Human-input needed`
- [2026-07-14] README L3 primary source tree lists every manifest ``source_globs`` root when multiple trees apply
- [2026-07-14] README fingerprints skip timestamp-only rewrites when source digests are unchanged
- [2026-07-14] README pipeline refactor splits offline sections, L2 policy, text utils, module index, and scan context; scanner uses single-pass module indexes
- [2026-07-14] README regeneration skips rewriting files when rendered markdown is unchanged, keeping pre-commit manifest sync idempotent
- [2026-07-14] README `make readme-check` runs manifest `lint_summaries` and validates curated Level 1–2 symbol cites; INDEX status column shows `fresh`/`stale` with a freshness ≠ accuracy note
- [2026-07-14] README generator drops the hardcoded gateway key-load clause unless `provider_keys_via_proxy` is set on the manifest row; non–turn-spine L2 uses module-graph prose instead of a generic stub
- [2026-07-14] README L3 deep dives lead with full module docstrings, definition-site markdown links (`#L` anchors), and a unified 12-file symbol window aligned with `extract_module_symbols`
- [2026-07-13] README LLM profile wiring (root value prop + highlights, guide steps, catalog intro) with offline default unchanged; root README loads `value_prop` from brand TOML and uses live GitHub Actions CI badge
- [2026-07-13] README offline scaffold quality: turn-spine paragraph gated on `turn_spine`, sentence-boundary truncation, true path-list remainders, docstring-derived module inventory, and narrowed PLACEHOLDER warnings
- [2026-07-13] README pipeline emits file-relative links and retargets manifest spec paths to `about-sevn.bot/specs/`; link checker resolves paths from each README directory only
- [2026-07-13] README catalog kinds: manifest `catalog = "modules" | "skills"` with modules cap 200 (+N overflow row) and skills two-table layout (bundled SKILL.md frontmatter + runtime loaders)
- [2026-07-14] CLI getting-started and config guides drop stale M1/M2 milestone framing; the `sevn config` interactive menu is documented as shipped
- [2026-07-14] Subsystem README catalog adds `evolution` and `plugins` manifest rows with generated subsystem docs; `tools` migrated from catalog to curated subsystem profile; `browser/` remains documented as out-of-catalog in STANDARD

### Deprecated

### Removed

- [2026-07-14] `about-sevn.bot/DOC-VS-CODE-ANALYSIS.md` — operator audit belongs in `.ignorelocal/`; its presence broke `about-site-check` for PRs merging `pre-0.0.1`

### Fixed

- [2026-07-14] Bundled skill seeding skips `__pycache__` when copying packaged skills, avoiding parallel-test flakes on transient `.pyc` files
- [2026-07-15] Telegram session mirror title lookup is best-effort when SQLite errors occur; group titles also persist from inline-keyboard callbacks (#21)
- [2026-07-15] Restored spec-36 sub-agent amendment cross-reference in `14-executor-tier-b.md` after W9 body rewrite
- [2026-07-15] `scripts/changelog_validate.py` shim re-exports `load_changelog_rules`, `validate_changelog`, and `check_staged_gate` for backward compatibility
- [2026-07-15] Gateway README module count and `build_agent_run_turn` line anchors updated after W12 subpackage reorg
- [2026-07-14] Gateway telegram printing-press inline loader resolves bundled `_pp_cli.py` from the `sevn` package root after W12 subpackage moves; `ci-affected` doctest skips bundled skill script paths
- [2026-07-14] `ci-affected` runs `make doctest` when more than 100 `src/sevn` files change, avoiding doctest context pollution from huge per-file pytest invocations on long-lived wave branches
- [2026-07-14] Onboarding web and TUI wizards expose `gateway.queue_mode=multi` in capabilities (matches runtime and spec-36)
- [2026-07-14] README pre-commit stages `_fingerprints.json` when source digests change but rendered markdown is unchanged
- [2026-07-14] Curated Level 1–2 symbol validation flags bare `` `function_name` `` cites absent from cited Python files (line-scoped, snake_case only)
- [2026-07-14] Skills catalog README no longer leaks YAML folded-scalar `>-` markers from bundled SKILL.md frontmatter
- [2026-07-13] `list your skills` reply no longer truncates skill descriptions at ~80 chars: `compose_list_skills_reply` now prefers the full manifest description from the skill inventory over the clipped Triager routing-index line
- [2026-07-13] `log_query` accepts a `[start, end]` integer pair and a bracketed `"[start, end]"` string as one inclusive range, instead of rejecting them with an "invalid range" error that leaked into replies; unparseable ranges now mark the diagnostic internal so the model corrects the call rather than quoting it to the user
- [2026-07-13] Tier-B empty-output retry exhaustion (`Exceeded maximum output retries`) is treated as a deterministic harness failure, skipping the wasteful widened full-index retry that reproduced it and contributed to `executor_timeout_cancel` (the summarize / partial-progress path still runs)
- [2026-07-13] Tier-B blocks a single tool after `TIER_B_TOOL_FAILURE_HARD_CAP` (5) errors in one turn with a terminal synthesis steer, stopping loops where the model varies arguments each attempt (e.g. guessing CLI subcommands or rewriting `run_code`) that previously ground to the round/timeout budget
- [2026-07-13] Printing Press skill wrappers (`espn`, `flight_goat`, `movie_goat`, `recipe_goat`) tokenise `--query` on whitespace with quotes respected, so multi-word subcommands like `news soccer fifa.world` reach the CLI as separate argv instead of one bogus subcommand token; `--query` help and `references/espn.md` document the `news <sport> <league>` form (e.g. World Cup = `news soccer fifa.world`)
- [2026-07-13] Mission Control owner login resolves `${SECRET:…}` dashboard and gateway password refs at boot instead of comparing against placeholder strings
- [2026-07-14] `sevn dashboard set-login-password` stamps `sevn.json` only after the secrets write succeeds; doctest mocks frozen `GatewayTokenBootstrap.chain` correctly
- [2026-07-13] README curation: strict pre-commit mode no longer stamps fingerprints when agent curation fails; curator runner subprocess uses minimal env and redacts error output
- [2026-07-13] README `make readme-scaffold` protects curated bodies: stale slugs get fingerprint-only stamps, never body rewrites or section stubs
- [2026-07-13] README `_write_entries` doctest uses non-curated `storage` row after gateway manifest curation
- [2026-07-12] Self-improve trajectory ingest circular import: move `ensure_trace_connection` to `agent.tracing.traces_migrate` and rewrite `docs/readmes/self-improve.md` Level 1–2 with preset-C audit
- [2026-07-12] CI failures from `secrets.*` gitignore rule excluding `src/sevn/config/sections/secrets.py` (ModuleNotFoundError and mypy `no-any-return` on CI)
- [2026-07-12] PR #6 CI gates: skip optional `wave-orchestrator/` about-docs paths on public clones, defer spec-36 until F3, remove premature `subagents_registry` doctor catalog entry, and mock CDP attach in onboarding browser context-manager test
- [2026-07-12] PR #6 CI: vendor changelog validator into tracked `scripts/` + `infra/`, stabilize GitHub webhook dedupe test with file-backed sqlite, disable replay worker in dashboard CSRF gate test to avoid xdist hang, and generate code index before `ci-parity` drift gate

### Security

- [2026-07-14] Bump setuptools to 83.0.0 to clear PYSEC-2026-3447 from pip-audit

## [0.0.1] - 2026-07-08

First public release on [github.com/sevn-bot/sevn](https://github.com/sevn-bot/sevn).

### Added

- Multi-channel AI gateway (Telegram, Web UI) with tiered agent runtime
- Paired egress proxy, secrets backends, Mission Control dashboard, and workspace memory
- Onboarding wizard (`sevn onboard`), CLI, and `make setup` developer bootstrap
- Full Python package under `src/sevn/` with CI via `make ci`

### Changed

- Repository canonical home moved from the private `sevn-bot/sevn.bot` checkout to the public `sevn-bot/sevn` repo
