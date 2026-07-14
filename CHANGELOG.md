# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every user-visible code change adds a bullet under `## [Unreleased]`; those bullets
are cut into a dated, versioned section at release time.

## [Unreleased]

### Added

- `sevn dashboard set-login-password` stores the Mission Control owner password in the workspace secrets chain and stamps `dashboard.login_password` with a `${SECRET:…}` ref
- README `curated` manifest flag and `sevn readme fingerprint` command so hand-authored subsystem READMEs are stamped without body rewrites
- Advisory `make md-links-check` markdown link checker for tracked docs outside `about-sevn.bot/` (`scripts/check_markdown_links.py`; `ci-quality` tier only)
- Bundled skills, workspace templates, doctor solutions, docs site (`about-sevn.bot/`), readme pipeline (`docs/readmes/`), brand assets, and remaining test suites for the pre-0.0.1 migration import (I5)
- Core runtime packages for the pre-0.0.1 migration import (config, storage, workspace, gateway, agent, security, proxy, and related tests)
- Configurable Second Brain vault path via `second_brain.paths.vault` (CLI setup, Telegram `/config`, onboarding, doctor)
- Witchcraft semantic reindex for the Second Brain vault via `sevn second-brain setup --reindex` and automatically at gateway boot
- Logfire trace export: `tracing.sinks[]` logfire sink with secrets-managed token, `sevn tracing` / `sevn config tracing` CLI, Telegram `/config → Logs` toggle and token form, and Mission Control ops endpoints
- Sub-agents orchestration with level-1 role runs, level-2 workers and specialists, `multi` queue mode, Mission Control and Telegram kill surfaces, and `media_generation` skill via the `media_generator` specialist

### Changed

- README LLM profile wiring (root value prop + highlights, guide steps, catalog intro) with offline default unchanged; root README loads `value_prop` from brand TOML and uses live GitHub Actions CI badge
- README offline scaffold quality: turn-spine paragraph gated on `turn_spine`, sentence-boundary truncation, true path-list remainders, docstring-derived module inventory, and narrowed PLACEHOLDER warnings
- README pipeline emits file-relative links and retargets manifest spec paths to `about-sevn.bot/specs/`; link checker resolves paths from each README directory only
- README catalog kinds: manifest `catalog = "modules" | "skills"` with modules cap 200 (+N overflow row) and skills two-table layout (bundled SKILL.md frontmatter + runtime loaders)

### Deprecated

### Removed

### Fixed

- Mission Control owner login resolves `${SECRET:…}` dashboard and gateway password refs at boot instead of comparing against placeholder strings
- `sevn dashboard set-login-password` stamps `sevn.json` only after the secrets write succeeds; doctest mocks frozen `GatewayTokenBootstrap.chain` correctly
- README `_write_entries` doctest uses non-curated `storage` row after gateway manifest curation
- Self-improve trajectory ingest circular import: move `ensure_trace_connection` to `agent.tracing.traces_migrate` and rewrite `docs/readmes/self-improve.md` Level 1–2 with preset-C audit
- CI failures from `secrets.*` gitignore rule excluding `src/sevn/config/sections/secrets.py` (ModuleNotFoundError and mypy `no-any-return` on CI)
- PR #6 CI gates: skip optional `wave-orchestrator/` about-docs paths on public clones, defer spec-36 until F3, remove premature `subagents_registry` doctor catalog entry, and mock CDP attach in onboarding browser context-manager test
- PR #6 CI: vendor changelog validator into tracked `scripts/` + `infra/`, stabilize GitHub webhook dedupe test with file-backed sqlite, disable replay worker in dashboard CSRF gate test to avoid xdist hang, and generate code index before `ci-parity` drift gate

### Security

## [0.0.1] - 2026-07-08

First public release on [github.com/sevn-bot/sevn](https://github.com/sevn-bot/sevn).

### Added

- Multi-channel AI gateway (Telegram, Web UI, voice hooks) with tiered agent runtime
- Paired egress proxy, secrets backends, Mission Control dashboard, and workspace memory
- Onboarding wizard (`sevn onboard`), CLI, and `make setup` developer bootstrap
- Full Python package under `src/sevn/` with CI via `make ci`

### Changed

- Repository canonical home moved from the private `sevn-bot/sevn.bot` checkout to the public `sevn-bot/sevn` repo
