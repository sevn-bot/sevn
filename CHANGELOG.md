# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every user-visible code change adds a datestamped bullet under `## [Unreleased]`; those bullets
are cut into a dated, versioned section at release time.

## [Unreleased]

### Added

- [2026-07-18] Discogs skills operator README with per-script examples and User-token + OAuth auth walkthroughs; skills INDEX polish, onboarding Group-B `skill.discogs` row, and `[discogs]` extra install action
- [2026-07-18] Discogs OAuth 1.0a authorization flow from Telegram Setup — consumer key/secret capture, authorize URL + verifier exchange, and access-token storage with auth_method flip
- [2026-07-18] Telegram config menu for Discogs skills — group and per-skill toggles, Setup submenu with user-token wizard, and whoami auth smoke-test
- [2026-07-18] Discogs identity skill — whoami auth smoke-test, user profile, lists, search, and contributions subprocess scripts
- [2026-07-18] Discogs wantlist skill — browse/search wantlist plus add, remove, and edit subprocess scripts with confirm-gated writes
- [2026-07-18] Discogs collection skill — folder listing, collection search, value stats, and confirm-gated add/remove/move/rate subprocess scripts
- [2026-07-18] Discogs marketplace skill — inventory search, listings CRUD, orders, messages, and fee subprocess scripts with confirm-gated writes
- [2026-07-18] Discogs database catalog skill — search plus artist/release/master/label lookups, price suggestions, and marketplace stats subprocess scripts with JSON envelopes
- [2026-07-18] Optional Discogs skill group foundation — typed ``skills.discogs`` config, group gate, secrets→env injection, shared ``_discogs_common.py`` runtime, and ``python3-discogs-client`` optional extra
- [2026-07-16] Unified X ops facade (`sevn.integrations.social_media.x_ops`) exposes every X/Twitter endpoint as a callable over browser|twexapi with a normalized envelope, write-gates, cookie bridge, and `social_media_manager` skill scripts
- [2026-07-16] Browser `social` X ops `timeline_collect` / `home_feed` / `read` return structured posts with status permalinks and tweet text instead of raw HTML noise
- [2026-07-16] Bundled Obsidian second-brain skills from `kepano/obsidian-skills` (`defuddle`, `json-canvas`, `obsidian-bases`, `obsidian-cli`, `obsidian-markdown`) so sevn can load Obsidian-native markdown, Canvas, Bases, vault CLI, and web-to-markdown workflows out of the box
- [2026-07-16] `gh-issues` authenticated read/watch/track via `gh` (`issue_view`/`issue_watch`/`issue_track`) with `.sevn/gh-watch/` state and a `gh-issue-watch` cron scope (~15 min) that notifies on issue changes via the `message` tool
- [2026-07-16] `gh-issues` `issue_create` creates issues in one call via authenticated `gh` with `templates/{feature,bug,chore}.md` (default `feature`), defaults `--repo` from `my_sevn.repo_url`, returns `{url,number,repo}`, falls back to the egress proxy only when `gh` is absent, and maps failures to precise messages instead of bare `proxy status 404`
- [2026-07-16] Bundled `proton-management` skill with Python `proton-cli` foundation (Pass read, session/SRP auth) and onboarding manifest registration
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

### Fixed

- [2026-07-18] Scrub residual Playwright wording from `browser.chrome` docs and triager classifier fixture text so the zero-driver repo grep stays clean after merging latest `pre-0.0.1`
- [2026-07-16] Bump transitive `mcp` 1.27.1 → 1.28.1 to clear CVE-2026-52870 (missing authorization in experimental tasks API)
- [2026-07-16] `social_media_manager` pins trusted `content_root` after merging task params/body (blocks override), leaves omitted JSON `medium` unset so `default_medium`/`platforms.<site>.medium` resolve, and X ops reject missing `tweet_id` with `TWEET_ID_REQUIRED` instead of path ``0``
- [2026-07-16] X ops `fetch_article_markdown` and `get_users_by_usernames` reject `medium=browser` with `BROWSER_OP_UNSUPPORTED` instead of returning a false-success home scrape plan
- [2026-07-16] `social_media_manager` worker forwards `tools.browser` from workspace `JsonDict` config (`.get("browser")`) so `allow_write=true` reaches the X ops write gate instead of always returning `WRITE_DISABLED`
- [2026-07-16] Worker browser plans expose SocialRecipe `op` (e.g. `home_feed`/`post`) at the top level with facade name under `facade_op`, so `action=social` callers do not hit `unknown social op`
- [2026-07-16] `browser-harness` WebSocket connects with `max_size=256MiB` matching core CDPConnection so large screenshots/DOM payloads do not fail
- [2026-07-16] X ops facade resolves TwexAPI keys via `resolve_twexapi_api_key` (`KEY_MISSING` when absent), gates TwexAPI on workspace `settings.enabled`, rejects tweet-action/quote ops on `medium=browser` with `BROWSER_OP_UNSUPPORTED`, and puts thread `items`/`texts` into browser plans
- [2026-07-16] `browser-harness` `browser_cdp` uses the `websockets` package from the `browser-cdp` extra (no `websocket-client`); profile lock cleanup only runs under `.sevn/browser-profiles/` (or `SEVN_BROWSER_PROFILE_DIR`)

### Changed

- [2026-07-16] Social media manager defaults and per-site skill hints drop retired platform browser skills; package-install routing detects `browser-cdp` instead of the old driver install phrasing
- [2026-07-16] Docs/prompt sync: `social_media_manager` X ops catalog finalized, onboarding/INDEX/`browser` tool docs drop removed social/Telegram-test skills, and residual Playwright wording scrubbed from operator docs
- [2026-07-16] Remove the Playwright E2E harness and `telegram-tester`, replacing Telegram Web checks with the browser `telegram_web` recipe (+ Bot-API `getMe` helper); park webchat/onboarding/Mission Control journeys pending re-home (#37)
- [2026-07-16] `computer-use` skill `see_also` drops the removed `playwright-browser` reference; docker gateway browser/gui images install `browser-cdp` only
- [2026-07-16] Residual Playwright symbols renamed to browser_tool (routing/grounding), deprecated prompt aliases dropped, OpenUI rasteriser is weasyprint-only, and docker/.env install paths use `browser-cdp` without `playwright install`
- [2026-07-18] `media_generation` v2.2.0 hardens `media_generator`: voice speaks literal `speech_text`/`preview_text`, unique artifact filenames, `file_id` int|str, lean prompts (fail unknown template), path containment, and S2V/FL2V skill scripts
- [2026-07-15] Telegram `/config`, onboarding wizard, and Mission Control Knowledge view expose Second Brain layout selection and resolved PARA role paths instead of assuming legacy `wiki/raw/outputs` folders
- [2026-07-16] Remove Playwright browser extra and Playwright-based skills (`playwright-browser`, `facebook-use`, `linkedin-use`, `x-use`); install/sync paths prefer `browser-cdp` only (WIP on `remove/playwright`)
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

- [2026-07-16] README fingerprint stamps skip rewriting `_fingerprints.json` when the source digest is unchanged, so curated pre-commit sync no longer loops on timestamp-only churn
- [2026-07-16] Browser spawn defaults include AutomationControlled and hygiene flags so Google/X sign-in is not blocked; closing then reopening the same profile clears stale CDP port and Singleton locks and ignores outdated DevToolsActivePort files
- [2026-07-16] Thermos iter6 residual: Brave-spawned browsers pass `pid_matches_sevn_chrome_profile` (close/reap/shutdown can kill and clear Singleton locks) while still requiring bounded `--user-data-dir=` equality
- [2026-07-16] Thermos iter5: Chrome profile identity matches a bounded `--user-data-dir=` argv token (prefix profiles no longer cross-match); browser registry/spawn/CDP helpers live in `sevn.browser` so lifecycle/process no longer import skills; issue-watch cron seed no longer force-reenables a disabled job on every boot
- [2026-07-16] Thermos iter4: `run_gh` times out hung `gh` (60s) so issue-watch/cron cannot pin the gateway; `spawn_chrome` returns Popen only (no fake `:0` CDP URL) with shared `await_cdp_after_spawn`; onboarding uses `clear_profile_singleton_locks` + that wait path; generic `pid_is_alive`/`terminate_pid` live in `sevn.util.process` (gateway teardown imports util; Chrome identity/reap stay in `browser.process`); drop thin `pid_*` re-exports from `browser_session`
- [2026-07-16] Thermos iter3: browser restart fails clearly under attach-only `SEVN_CDP_URL` (no stale registry success); Chrome terminate/close runs off the event loop; identity-fail kills leave the registry intact; issue-watch continues after per-issue `gh` errors; Playwright attach uses lifecycle spawn SSOT; process/reap lives in `sevn.browser.process`; operator-notify wiring and issue-watch notify moved out of `http_server` / general dispatcher
- [2026-07-16] Thermos iter2: operator notify skips a no-op Telegram sink when no owner is configured (LOG under `.sevn/trigger_runs/` instead); issue-watch cron and Chrome reap run off the event loop; one `terminate_sevn_chrome` / shutdown path; issue-watch extracted from `cron.py`; `gh` CLI lives in `gh_cli.py`; spawn no longer stacks dual DevTools waits; restart uses hardened lifecycle spawn
- [2026-07-16] Thermos D16: issue-watch cron delivers via injectable operator notify (gateway Telegram / LOG artefact) instead of a fake `message_tool` stub; watch/track live in `sevn.integrations.github_skill.watch` (no `importlib` from cron); `gh-issue-watch` cron job is seeded at gateway boot
- [2026-07-16] Thermos D16: spawn-path Chrome reap waits after SIGTERM before clearing locks; single `pid_is_alive` + cmdline profile identity before kill; remove TypeError spawn kwargs fallback; always-await CDP attach
- [2026-07-16] Thermos D16: `default_github_repo_slug` parses SCP `git@host:owner/repo.git`; `log_query` pattern paging uses match-set `offset_from_tail`; `process` restores typed `ProcessAction` / `ProcessActionInput`
- [2026-07-16] Mark intentional fixed-argv `gh` subprocess calls in `github_manager` with Bandit `# nosec` so the W5/W6 CLI create/view path passes `make security`
- [2026-07-16] On classifier timeout, the queue relatedness path treats the message as its own turn (`new_task`) instead of merging it into an unrelated in-flight task via `related_steer`
- [2026-07-16] Skill registry and `load_skill` share one source of truth: `list_registry` advertises only non-quarantined skills from the live `SkillsManager` scan (no unloadable `DEFAULT_SKILL_MANIFESTS` stubs), and skills whose manifests fail to parse are flagged `quarantine:true` so listed skills never return `SKILL_NOT_FOUND`
- [2026-07-16] `read_transcript` no longer crashes on tool-heavy turns with small limits when mirrored tool results are bare JSON scalars; `log_query` with a `pattern` returns matching lines (paged under the inline budget) instead of collapsing to a `tail_summary` sample
- [2026-07-16] `process` accepts `action=read` as an alias for `output`, keeps `run` returning `did_you_mean`, and wrong-action errors include the referenced job's current status; workspace `sevn.bot.md` surfaces `my_sevn.repo_url` so agents never need `git remote` against the read-only mirror
- [2026-07-16] Browser spawn survives concurrent retries and gateway restarts: stale sevn Chrome is reaped, profile singleton/port locks cleared, CDP wait is adaptive with one clean retry, Chrome stderr lands in `logs/chrome-<session>.log`, and the session registry only stores confirmed live CDP endpoints
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
