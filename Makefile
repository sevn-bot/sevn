.DEFAULT_GOAL := help

# ``make lint`` chains **ruff check**, **ruff format --check** (enforces formatter
# output in CI and locally without writing files — use ``make format`` to fix),
# then ``scripts/check_docstrings.py`` (ADR inventory). ``make typecheck`` runs
# **mypy** plus ``scripts/check_type_hints.py``; an optional **pyright** job may
# duplicate ``typecheck`` later per ``specs/25-cicd-full.md`` §11.

UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
RUFF ?= $(UV) run ruff
MYPY ?= $(UV) run mypy
PYTEST ?= $(UV) run pytest
# Parallel unit tests: SEVN_PYTEST_JOBS=auto (default), N workers, or 0 to disable.
SEVN_PYTEST_JOBS ?= auto
PYTEST_XDIST := $(if $(filter 0,$(SEVN_PYTEST_JOBS)),,$(if $(SEVN_PYTEST_JOBS),-n $(SEVN_PYTEST_JOBS) --dist=loadgroup,))
BANDIT ?= $(UV) run bandit
PIP_AUDIT ?= $(UV) run pip-audit
PIP_AUDIT_CACHE ?= $(CURDIR)/.cache/pip-audit
# pullfrog-py ref for local `make review` (offline `pfpy diff-review`), pinned to
# the same SHA as the CI workflow (.github/workflows/pullfrog.yml) so local review
# runs the reviewed code, not whatever `main` currently is. Override with
# SEVN_PULLFROG_PY_REF=main (or another ref) to track a branch locally.
PULLFROG_PY_REF ?= $(if $(SEVN_PULLFROG_PY_REF),$(SEVN_PULLFROG_PY_REF),dc98633049a6f473124e013ffd1e446d7e10b70a)
PRE_COMMIT ?= $(UV) run pre-commit

.PHONY: help setup install install-git-guards check-git-guards snapshot-local install-snapshot-timer install-cli install-cli-browser sync-cli pdf-native-libs lockcheck lint lint-imports format typecheck pyright test test-integration coverage diff-cover stale-xfail-check md-links-check doctest security precommit commit-msg-check config-schema onboarding-capabilities-check onboarding-profiles-schema-check onboarding-profiles-schema infra-check schema-export skills-core-check skillspector-check skills-index-check tools-skills-inventory-check dreaming-allowlist-check telegram-menu-check telegram-menu-docs-check telegram-menu-docs-scaffold mission-control-docs-check mission-control-docs-scaffold mission-control-schema-check mission-control-schema-generate agent-context-manifest-check agent-context-manifest-generate about-site about-site-check subagents-chart subagents-chart-check changelog-check changelog-eval code-index code-index-check storage-golden-refresh styles-build ui-style-check build ci ci-static ci-core ci-infra ci-docs ci-skills ci-parity ci-changed ci-affected ci-steps ci-resume ci-reset partial-ci ci-quality ruff-extra typecheck-strict deadcode complexity spell deps-check docstring-coverage pullfrog-ref-check review golden-llm-ci v1-smoke v2-smoke run proxy proxy-env dash-build dash-test sandbox-integration docker-build-ci compose-ci-smoke compose-up compose-down compose-logs compose-restart log-explore telegram-checks telegram-e2e incomplete-tasks improve-evals find-stubs clean readme readme-check readme-scaffold readme-curate readme-curate-prompt readme-preview readme-render-fixtures printing-press-starter-pack printing-press-check wave-orchestrator-lint wave-orchestrator-typecheck wave-orchestrator-test wave-orchestrator-check about-docs-schema about-docs-check about-docs-migrate about-docs-index about-docs-extract about-docs-generate spec-check prd-check spec-sync prd-sync logo-mark-ascii logo-mark-animate logo-mark-ascii-dissolve


PROXY_ENV_FILE ?= .env.proxy

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

ensure-uv: ## Install uv on PATH when missing (https://docs.astral.sh/uv/)
	@if command -v uv >/dev/null 2>&1; then exit 0; fi
	@echo "uv not found — installing via astral.sh/install.sh ..."
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@test -x "$(HOME)/.local/bin/uv" || (echo "uv install failed: $(HOME)/.local/bin/uv missing" >&2; exit 1)

setup: ensure-uv ## Fresh checkout: sync deps, native PDF libs, pre-commit hooks, `sevn` on PATH
	# skillspector is included because `make ci` runs skillspector-check (ci-skills
	# tier) — `make setup` must install everything the gate needs (specs/00 §2.1).
	$(UV) sync --extra dev --extra browser-cdp --extra skillspector
	-$(MAKE) pdf-native-libs
	$(PRE_COMMIT) install
	$(PRE_COMMIT) install --hook-type commit-msg
	$(MAKE) install-git-guards
	$(MAKE) install-cli

install-git-guards: ## Block `git clean -x`/`-X` (protects gitignored plan/specs/prd)
	@chmod +x scripts/git_clean_guard.sh scripts/install_git_guards.sh
	@./scripts/install_git_guards.sh

check-git-guards: ## Verify alias.clean blocks git clean -x/-X
	$(UV) run python scripts/check_git_guards.py

snapshot-local: ## Back up local-only gitignored trees (.ignorelocal/spec-kit-wave/.cursor/.claude/docs/...) to ~/.sevn-local-backups
	@chmod +x scripts/snapshot_local.sh 2>/dev/null || true
	@./scripts/snapshot_local.sh

install-snapshot-timer: ## Install launchd timer: run snapshot-local every 3h (macOS; independent of git push)
	@chmod +x scripts/install_snapshot_timer.sh 2>/dev/null || true
	@./scripts/install_snapshot_timer.sh

install: ## Sync dev environment after dependency changes
	$(UV) sync --extra dev

# WeasyPrint (a main dependency) binds the GLib/pango/cairo *native* C libraries
# at import via cffi.dlopen — `uv sync` installs the Python wheel but cannot
# install those system libs, so a fresh checkout PDF-renders only via the
# degraded fpdf2 fallback (or not at all). Install the natives here. Best-effort
# and non-fatal in `setup` (`-` prefix); commands mirror
# `sevn.pdf.doctor_check.weasyprint_native_fix_commands` (source of truth).
pdf-native-libs: ## Install WeasyPrint native libs (pango/cairo/gobject) for PDF rendering
	@uname_s="$$(uname -s)"; \
	if [ "$$uname_s" = "Darwin" ]; then \
	  if command -v brew >/dev/null 2>&1; then \
	    echo "Installing WeasyPrint native libs via Homebrew (pango)…"; \
	    brew install pango || echo "⚠️  brew install pango failed — install manually, then re-run 'sevn doctor'"; \
	  else \
	    echo "⚠️  Homebrew not found. Install Homebrew, then run: brew install pango"; \
	  fi; \
	elif [ "$$uname_s" = "Linux" ]; then \
	  echo "Installing WeasyPrint native libs via apt-get (sudo)…"; \
	  sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 libffi8 fontconfig \
	    || echo "⚠️  apt-get install failed — install the libpango/cairo/libffi packages manually"; \
	else \
	  echo "⚠️  Unknown OS ($$uname_s). Install pango/cairo/gobject native libs manually, then run 'sevn doctor'."; \
	fi

sync-cli: install-cli-browser ## Operator `sevn sync`: editable CLI + browser-cdp (no pre-commit hooks)

install-cli: styles-build ## Install the `sevn` console script as a uv tool (on PATH via ~/.local/bin)
	@$(UV) tool install --reinstall --force --editable . >/dev/null
	@bin="$$($(UV) tool dir --bin 2>/dev/null)"; \
	echo "sevn installed to $$bin/sevn"; \
	case ":$$PATH:" in \
	  *":$$bin:"*) : ;; \
	  *) echo ""; \
	     echo "  NOTE: $$bin is not on your PATH."; \
	     echo "  Run 'uv tool update-shell' (or add the line above to your shell rc), open a new shell, then re-run 'sevn'."; ;; \
	esac

install-cli-browser: install-cli ## Gateway host: uv-tool `sevn` + browser-cdp extra
	@$(UV) sync --extra browser-cdp
	@$(UV) tool install --reinstall --force --editable . \
	  --with websockets>=12 >/dev/null

lockcheck: ## Fail if uv.lock is out of date
	$(UV) lock --check

lint-imports: ## Import-layer contracts (`specs/01-system-overview.md` §2.3)
	$(UV) run lint-imports

lint: ## Ruff check + formatting + ADR docstring inventory + import-linter
	$(RUFF) check src tests scripts
	$(RUFF) format --check src tests scripts
	$(UV) run python scripts/check_docstrings.py src/sevn scripts
	$(UV) run python scripts/check_cli_help_no_spec_refs.py
	$(UV) run python scripts/check_loguru_only.py
	$(MAKE) lint-imports

format: ## Auto-format with Ruff
	$(RUFF) format src tests scripts

typecheck: ## mypy strict + ADR type-hint script (public callables)
	$(MYPY) src/sevn
	$(UV) run python scripts/check_type_hints.py src/sevn

pyright: ## Supplemental Pyright pass (`specs/25-cicd-full.md` §11)
	$(UV) run pyright src/sevn

# Optional cross-runner sharding for CI: set SEVN_TEST_SPLITS=N and
# SEVN_TEST_GROUP=G (1..N) to run the G-th of N pytest-split shards. Unset
# locally → whole suite. Each shard still uses xdist within its runner.
PYTEST_SPLIT := $(if $(SEVN_TEST_SPLITS),--splits $(SEVN_TEST_SPLITS) --group $(SEVN_TEST_GROUP) --splitting-algorithm least_duration,)

test: styles-build ## Unit tests (parallel when SEVN_PYTEST_JOBS=auto; set 0 to disable)
	$(PYTEST) tests -v --tb=short --strict-markers -m "not integration" $(PYTEST_XDIST) $(PYTEST_SPLIT) \
		--randomly-seed=$${SEVN_PYTEST_RANDOM_SEED:-424242}

test-integration: ## Opt-in tests (``pytest -m integration``)
	$(PYTEST) tests -v --tb=short --strict-markers -m integration

coverage: styles-build ## Unit test coverage report (HTML + terminal; advisory baseline)
	$(PYTEST) tests -v --tb=short --strict-markers -m "not integration" $(PYTEST_XDIST) \
		--cov=sevn --cov-report=term-missing:skip-covered --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-branch

diff-cover: ## Fail when changed lines fall below DIFF_COVER_MIN (default 80%; ci-quality-coverage)
	@test -f coverage.xml || (echo "Run 'make coverage' first to generate coverage.xml" >&2; exit 1)
	@base="$${SEVN_CI_BASE:-origin/test-pre}"; \
	min="$${DIFF_COVER_MIN:-80}"; \
	$(UV) run diff-cover coverage.xml --compare-branch "$$base" --fail-under "$$min"

stale-xfail-check: ## Fail on strict=False or wave-scaffolding xfail markers (ci-quality)
	$(UV) run python scripts/quality/check_stale_xfail.py

md-links-check: ## Advisory markdown link check outside about-sevn.bot (D18; ci-quality)
	$(UV) run python scripts/check_markdown_links.py

golden-llm-ci: styles-build ## Tokenless golden_llm pydantic-evals gate (W12)
	$(PYTEST) tests/fixtures/golden_llm/runner/test_golden_llm_eval.py -v --tb=short --strict-markers

doctest: ## Doctest src/sevn and scripts/check_docstrings.py (fails if nothing collected)
	@rm -rf .pytest_cache
	# -p no:randomly: doctests are order-independent examples, but a few modules
	# register into process-global registries at import (e.g. telemetry boot
	# hooks), so random module ordering could make an idempotent-looking example
	# see state a sibling module already registered. Pin deterministic order.
	@ec=0; $(PYTEST) --doctest-modules src/sevn scripts/check_docstrings.py -v --tb=short --strict-markers \
		-p no:randomly \
		--ignore=src/sevn/data/bundled_skills || ec=$$?; \
	if [ $$ec -eq 5 ]; then echo "doctest: no examples collected (pytest exit 5)" >&2; exit 1; fi; \
	exit $$ec

security: ## Bandit + dependency audit (OSV.dev backend, retried on transient network errors)
	$(BANDIT) -c pyproject.toml -r src/sevn
	@$(UV) run python scripts/pip_audit_ignore_args.py >/dev/null
	@PIP_AUDIT_IGNORE="$$($(UV) run python scripts/pip_audit_ignore_args.py)"; \
	for attempt in 1 2 3; do \
	  if $(PIP_AUDIT) --vulnerability-service=osv --timeout 60 --cache-dir $(PIP_AUDIT_CACHE) $$PIP_AUDIT_IGNORE; then \
	    exit 0; \
	  fi; \
	  echo "pip-audit attempt $$attempt failed; retrying in 5s..." >&2; \
	  sleep 5; \
	done; \
	echo "pip-audit failed after 3 attempts" >&2; exit 1

precommit: ## Run pre-commit on all files
	$(PRE_COMMIT) run --all-files

commit-msg-check: ## Validate MSG= against Conventional Commits (commit-msg hook)
	@test -n "$(MSG)" || (echo 'Usage: make commit-msg-check MSG="feat(scope): description"' >&2; exit 1)
	$(UV) run python scripts/check_conventional_commit.py --message "$(MSG)"

config-schema: ## Validate per-version config goldens against infra/sevn.schema.json
	$(UV) run check-jsonschema --schemafile infra/sevn.schema.json tests/fixtures/config/schema_v1_min.json tests/fixtures/config/schema_v2_min.json
	$(UV) run check-jsonschema --schemafile infra/onboarding_profiles_catalog.schema.json src/sevn/data/onboarding_profiles/onboarding_profiles.json
	@set -e; for f in src/sevn/data/onboarding_profiles/fragments/*.json; do \
		$(UV) run check-jsonschema --schemafile infra/onboarding_profiles_fragment.schema.json "$$f"; \
	done
	$(MAKE) onboarding-capabilities-check

cli-help-docs-check: ## CLI help panels + bundled sevn guide topics (cli W7)
	$(UV) run python scripts/check_cli_help_docs.py

doctor-solutions-check: ## Doctor solutions catalog schema + coverage (cli W3)
	$(UV) run check-jsonschema --schemafile infra/doctor_solutions.schema.json src/sevn/data/doctor_solutions.json
	$(UV) run python scripts/check_doctor_solutions.py

onboarding-capabilities-check: ## Manifest ↔ sevn.schema paths ↔ skills INDEX (`onboarding-comprehensive-setup` W1)
	$(UV) run check-jsonschema --schemafile infra/onboarding_capabilities.schema.json src/sevn/data/onboarding_capabilities.json
	$(UV) run python scripts/check_onboarding_capabilities.py

onboarding-profiles-schema-check: ## Catalog + fragment schema + capabilities_defaults parity (`onboarding-comprehensive-setup` W10)
	$(UV) run check-jsonschema --schemafile infra/onboarding_profiles_catalog.schema.json src/sevn/data/onboarding_profiles/onboarding_profiles.json
	@set -e; for f in src/sevn/data/onboarding_profiles/fragments/*.json; do \
		$(UV) run check-jsonschema --schemafile infra/onboarding_profiles_fragment.schema.json "$$f"; \
	done
	$(UV) run python scripts/check_onboarding_profiles.py

onboarding-profiles-schema: ## Validate packaged onboarding catalog + preset fragments
	$(UV) run check-jsonschema --schemafile infra/onboarding_catalog.schema.json src/sevn/data/onboarding_profiles/onboarding_profiles.json
	@set -e; for f in src/sevn/data/onboarding_profiles/fragments/*.json; do \
	  $(UV) run check-jsonschema --schemafile infra/onboarding_fragment.schema.json "$$f"; \
	done

infra-check: ## Fail when infra/ JSON metadata drifts from golden fixtures (see scripts/check_infra_parity.py)
	$(UV) run python scripts/check_infra_parity.py
	$(UV) run python scripts/export_triage_schema.py

pullfrog-ref-check: ## Fail when the pullfrog-py pin drifts between pullfrog.yml and PULLFROG_PY_REF
	$(UV) run python scripts/check_pullfrog_ref_parity.py

schema-export: ## Refresh infra/triage_result.schema.json from TriageResult (`specs/10-schema-ontology.md` §11)
	$(UV) run python scripts/export_triage_schema.py --write

printing-press-starter-pack: ## Install Printing Press starter-pack CLIs (espn, flight-goat, movie-goat, recipe-goat)
	npx -y @mvanhorn/printing-press-library install starter-pack

printing-press-check: ## Verify 4 Printing Press starter-pack binaries are on PATH
	@for bin in espn-pp-cli flight-goat-pp-cli movie-goat-pp-cli recipe-goat-pp-cli; do \
		if command -v "$$bin" >/dev/null 2>&1; then \
			echo "  ok: $$bin at $$(command -v $$bin)"; \
		else \
			echo "  MISSING: $$bin — run: make printing-press-starter-pack" >&2; \
		fi; \
	done

skills-core-check: ## Bundled core skills: SKILL.md scripts: rows match scripts/*.py on disk
	$(UV) run python scripts/check_skills_core_manifest.py

skillspector-check: ## SkillSpector static scan (bundled + repo skills + tool docs)
	$(UV) run python scripts/check_skillspector.py

skills-index-check: ## src/sevn/data/skills/INDEX.md ↔ bundled_skills/core/ parity
	$(UV) run python scripts/check_skills_index.py

onboarding-skills-check: ## Onboarding seed copies all required bundled core skills (>=20)
	$(UV) run python scripts/check_onboarding_core_skills.py

tools-skills-inventory-check: ## Worksheet Keep rows vs registry / bundled SKILL.md (TFI Wave 0)
	$(UV) run python scripts/check_tools_skills_inventory.py

dreaming-allowlist-check: ## Dreaming code must not target wiki/ USER.md Honcho stores (spec 31)
	$(UV) run python scripts/check_dreaming_allowlist.py

telegram-menu-check: ## Telegram menu + TMF registry gate (plan/telegram-menu-full-wiring-wave-plan.md Wave 0+)
	$(UV) run python scripts/check_telegram_menu.py

telegram-menu-docs-check: ## Dev Telegram Menu.html vs live /config keyboards
	$(UV) run python scripts/check_telegram_menu_docs.py

telegram-menu-docs-scaffold: ## Insert WIP/TODO stubs into Telegram Menu.html for missing menu rows
	$(UV) run python scripts/check_telegram_menu_docs.py --scaffold

mission-control-docs-check: ## Dev Mission Control.html vs tab_registry.py
	$(UV) run python scripts/check_mission_control_docs.py

mission-control-docs-scaffold: ## Insert WIP/TODO stubs into Mission Control.html for missing tabs
	$(UV) run python scripts/check_mission_control_docs.py --scaffold

mission-control-schema-check: ## Dashboard schema golden vs live registry/routes/selectors
	$(UV) run python scripts/check_mission_control_schema.py

mission-control-schema-generate: ## Regenerate infra/mission-control.schema.json golden
	$(UV) run python scripts/generate_mission_control_schema.py --write

agent-context-manifest-check: ## Agent context manifest golden vs live slot order
	$(UV) run python scripts/generate_agent_context_manifest.py

agent-context-manifest-generate: ## Regenerate infra/agent-context.manifest.json golden
	$(UV) run python scripts/generate_agent_context_manifest.py --write

readme-render-fixtures: ## Render README templates with fixture data; validate GitHub-safe output (exit 0)
	$(UV) run python scripts/readme_render_fixtures.py

readme: ## Offline regenerate all READMEs from manifest.toml
	$(UV) run sevn readme generate --all --offline --repo .

readme-check: ## README structure + staleness gate (exit non-zero on failure)
	$(UV) run sevn readme check --repo .

readme-scaffold: ## Offline regenerate missing/stale READMEs + insert section stubs
	$(UV) run sevn readme scaffold

readme-curate: ## Agent-curate one curated README from its source diff (SLUG=gateway [BASE=ref])
	$(UV) run sevn readme curate $(SLUG) $(if $(BASE),--base $(BASE),) --stage --repo .

readme-curate-prompt: ## Print the curator prompt without invoking a runner (SLUG=gateway)
	$(UV) run sevn readme curate $(SLUG) --dry-run --repo .

readme-preview: readme-render-fixtures ## Render README template previews to /tmp/sevn-readme-preview (no LLM)
	@echo "Preview files written to /tmp/sevn-readme-preview"

about-docs-schema: ## Export about-docs JSON Schema to about-sevn.bot/_docsys/about-docs.schema.json
	$(UV) run sevn about-docs schema

about-docs-check: ## Validate about-docs + skw spec/prd folder gates
	PYTHONPATH=. $(UV) run sevn about-docs check --repo .
	$(MAKE) spec-check
	$(MAKE) prd-check

spec-check: ## Validate+score every spec in about-sevn.bot/specs (skw docs validate)
	@if [ -d spec-kit-wave ]; then \
		$(MAKE) -C spec-kit-wave spec-check REPO_ROOT="$(CURDIR)"; \
	else \
		echo "spec-check: skipped (spec-kit-wave not present)"; \
	fi

changelog-check: ## Changelog gate: Keep-a-Changelog lint + Unreleased diff gate (SEVN_CI_BASE=<ref>)
	@if [ -d spec-kit-wave/src ]; then \
		python3 scripts/changelog_validate.py --repo . --base $${SEVN_CI_BASE:-origin/main}; \
	else \
		echo "changelog-check: skipped (spec-kit-wave not present)"; \
	fi

changelog-eval: ## Advisory LLM double-score of Unreleased entries (not in CI; needs model access — MODEL=, BASE=)
	@if [ -d spec-kit-wave/src ]; then \
		PYTHONPATH=spec-kit-wave/src $(UV) run python -m skw.changelog_eval --repo . \
			$(if $(MODEL),--model $(MODEL),) $(if $(BASE),--base $(BASE),); \
	else \
		echo "changelog-eval: skipped (spec-kit-wave not present)"; \
	fi

about-docs-migrate: ## Migrate legacy root prd/specs seed into about-sevn.bot/
	PYTHONPATH=. $(UV) run sevn about-docs migrate --repo .

about-docs-index: ## Render prd/spec README index tables
	PYTHONPATH=. $(UV) run sevn about-docs index --repo .

about-docs-extract: ## Extract code-owned frontmatter for one doc (DOC_ID=spec-17-gateway)
	@test -n "$(DOC_ID)" || (echo "usage: make about-docs-extract DOC_ID=spec-17-gateway" && exit 1)
	PYTHONPATH=. $(UV) run sevn about-docs extract $(DOC_ID) --repo .

about-docs-generate: ## Generate offline body for one doc (DOC_ID=spec-17-gateway)
	@test -n "$(DOC_ID)" || (echo "usage: make about-docs-generate DOC_ID=spec-17-gateway" && exit 1)
	PYTHONPATH=. $(UV) run sevn about-docs generate $(DOC_ID) --repo .

spec-sync: ## Refresh spec frontmatter in about-sevn.bot/specs (skw docs sync)
	@if [ -d spec-kit-wave ]; then \
		$(MAKE) -C spec-kit-wave spec-sync; \
	else \
		echo "spec-sync: skipped (spec-kit-wave not present)"; \
	fi

prd-sync: ## Refresh PRD frontmatter in about-sevn.bot/prd (skw docs sync)
	@if [ -d spec-kit-wave ]; then \
		$(MAKE) -C spec-kit-wave prd-sync; \
	else \
		echo "prd-sync: skipped (spec-kit-wave not present)"; \
	fi

prd-check: ## Validate+score every PRD in about-sevn.bot/prd (skw docs validate)
	@if [ -d spec-kit-wave ]; then \
		$(MAKE) -C spec-kit-wave prd-check REPO_ROOT="$(CURDIR)"; \
	else \
		echo "prd-check: skipped (spec-kit-wave not present)"; \
	fi

spec-kit-wave-test: ## Run spec-kit-wave pytest suite (skw validators + sync contracts)
	@if [ -d spec-kit-wave ]; then \
		$(MAKE) -C spec-kit-wave test REPO_ROOT="$(CURDIR)"; \
	else \
		echo "spec-kit-wave-test: skipped (spec-kit-wave not present)"; \
	fi

subagents-chart: ## Regenerate deterministic sub-agents topology SVG (D14)
	$(UV) run python scripts/gen_subagents_chart.py

subagents-chart-check: ## Fail when about-sevn.bot/assets/subagents-chart.svg is stale
	$(UV) run python scripts/gen_subagents_chart.py --check

about-site: subagents-chart ## Regenerate about-sevn.bot user help HTML + assets
	$(UV) run python scripts/build_about_site.py build

about-site-check: ## Fail when about-sevn.bot HTML is stale or contains forbidden internal refs
	$(UV) run python scripts/build_about_site.py --check

code-index: ## Regenerate .index/code_index/INDEX.md from src/sevn/
	$(UV) run python scripts/build_code_index.py

code-index-check: ## Fail when .index/code_index/INDEX.md is stale, missing docstrings, or has orphan entries
	$(UV) run python scripts/build_code_index.py --check --require-docstrings --check-orphans

storage-golden-refresh: ## Refresh tests/fixtures/storage/golden/migration_<NN>.sql for the current head (`specs/03-storage.md` §10.7)
	$(UV) run python -m scripts.dump_storage_golden --write

styles-build: ## Copy ``styles/sevn/style/`` into packaged ``src/sevn/ui/style/`` (run before build/CI)
	@test -d styles/sevn/style || { echo "Missing styles/sevn/style — add design source tree." >&2; exit 1; }
	rm -rf src/sevn/ui/style/tokens src/sevn/ui/style/components src/sevn/ui/style/utils src/sevn/ui/style/logos
	rm -f src/sevn/ui/style/*.css src/sevn/ui/style/*.html src/sevn/ui/style/*.js src/sevn/ui/style/tailwind.config.js
	cp -R styles/sevn/style/. src/sevn/ui/style/
	@test -f src/sevn/ui/style/index.css
	cp infra/sevn_config_long_description.json src/sevn/data/sevn_config_long_description.json

build: styles-build ## Build wheel and sdist (``uv build``)
	$(UV) build

ci-static: lockcheck lint typecheck pyright doctest build doctor-solutions-check ## Static/build tier (ci-core minus test & security) — PR gate

ci-core: lockcheck lint typecheck pyright test doctest security build doctor-solutions-check ## Core verify tier (~tests + typecheck)

ci-infra: config-schema onboarding-profiles-schema infra-check mission-control-schema-check check-git-guards agent-context-manifest-check ## Schema / infra drift tier

ci-docs: telegram-menu-check telegram-menu-docs-check cli-help-docs-check readme-check subagents-chart-check about-site-check about-docs-check about-docs-schema spec-kit-wave-test changelog-check ## Docs / menu HTML tier

ci-skills: skills-core-check skillspector-check skills-index-check dreaming-allowlist-check ## Skills inventory tier

ci-parity: code-index deploy-remote-report-check code-index-check pullfrog-ref-check ## Parity tier (public)

ci: ci-core ci-infra ci-docs ci-skills ci-parity ## Full gate (same as CI)

# Ordered expansion of `make ci`, consumed by the resumable runner (scripts/ci_resume.sh).
# Keep in sync with the ci-core/ci-infra/ci-docs/ci-skills/ci-parity tiers above.
CI_STEPS := lockcheck lint typecheck pyright test doctest security build doctor-solutions-check \
	config-schema onboarding-profiles-schema infra-check mission-control-schema-check check-git-guards agent-context-manifest-check \
	telegram-menu-check telegram-menu-docs-check cli-help-docs-check readme-check subagents-chart-check about-site-check about-docs-check about-docs-schema spec-kit-wave-test changelog-check \
	skills-core-check skillspector-check skills-index-check dreaming-allowlist-check \
	code-index deploy-remote-report-check code-index-check

ci-steps: ## Print the ordered `make ci` step list (consumed by ci-resume)
	@echo $(CI_STEPS)

ci-resume: ## Resumable gate: run ci steps in order, checkpoint passes, stop at first failure, resume on re-run
	@chmod +x scripts/ci_resume.sh 2>/dev/null || true
	@./scripts/ci_resume.sh

ci-reset: ## Clear the ci-resume checkpoint (start the gate over)
	@chmod +x scripts/ci_resume.sh 2>/dev/null || true
	@./scripts/ci_resume.sh --reset

ci-changed: ## Partial Python gate (ruff, mypy, pyright, scoped tests); set SEVN_CI_BASE
	$(UV) run python scripts/ci_changed.py

ci-affected: ## Path-aware partial gate (Python + mapped make targets); set SEVN_CI_BASE
	$(UV) run python scripts/ci_affected.py

partial-ci: ci-affected ## Alias for ci-affected (per-wave local gate)

ci-quality: ruff-extra typecheck-strict deadcode complexity spell deps-check docstring-coverage stale-xfail-check md-links-check ## Advisory quality tier (baseline + ratchet; not in `ci`)

ci-quality-coverage: coverage diff-cover ## Advisory coverage + diff-cover (run after code changes)
ruff-extra: ## Ruff advisory families ratchet (D3; `scripts/quality/ruff_advisory_gate.py`)
	$(UV) run python scripts/quality/ruff_advisory_gate.py
typecheck-strict: ## mypy strict + pydantic.mypy plugin (mirrors blocking `typecheck`; ci-quality tier)
	$(MYPY) src/sevn
deadcode: ## Vulture dead-code gate (advisory; `ci-quality`)
	$(UV) run vulture
complexity: ## Xenon cyclomatic-complexity gate (advisory; `ci-quality`)
	$(UV) run xenon src \
		-b F \
		-m F \
		-a A \
		--max-average-num 5 \
		-i '*/bundled_skills/*'
spell: ## Codespell gate (advisory; `ci-quality`)
	$(UV) run codespell src tests scripts
deps-check: ## Deptry gate (advisory; `ci-quality`)
	$(UV) run deptry src scripts
docstring-coverage: ## Interrogate docstring-coverage gate (advisory; `ci-quality`)
	$(UV) run interrogate src scripts

review: ## Advisory offline review vs SEVN_CI_BASE via pullfrog-py (needs CLAUDE_CODE_OAUTH_TOKEN in `.env`)
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	if [ -z "$${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "$${ANTHROPIC_API_KEY:-}" ]; then \
		printf 'Neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY set — add one to `.env` (see `.env.example`). Advisory review skipped.\n' >&2; \
		exit 0; \
	fi; \
	base="$${SEVN_CI_BASE:-origin/main}"; \
	echo "Running pullfrog-py diff-review (base=$$base, ref=$(PULLFROG_PY_REF))…"; \
	$(UV) tool run --python 3.14 --from git+https://github.com/alexhawat/pullfrog-py@$(PULLFROG_PY_REF) \
		pfpy diff-review --base "$$base"

v1-smoke: dash-build ## Seven v1 user paths (`plan/v1-release-scope.md`); sequential pytest gates
	$(UV) run python scripts/v1_smoke.py

v2-smoke: ## v2 gates (`plan/v2-release-scope.md`); skeleton until v2 Wave 13
	@echo "v2-smoke not yet implemented"

sandbox-integration: ## Optional Docker contract tests (needs Docker; sets SEVN_CI_SANDBOX_DOCKER=1)
	SEVN_CI_SANDBOX_DOCKER=1 $(PYTEST) tests/sandbox -v --tb=short --strict-markers -m sandbox_docker

docker-build-ci: ## Build docker/Dockerfile.* images (sandbox, proxy, gateway, browser, gui)
	docker build -f docker/Dockerfile.sandbox -t sevn-sandbox:local .
	docker build -f docker/Dockerfile.proxy -t sevn-proxy:local .
	docker build -f docker/Dockerfile.gateway -t sevn-gateway:local .
	docker build -f docker/Dockerfile.gateway.browser -t sevn-gateway-browser:local .
	docker build -f docker/Dockerfile.gateway.gui -t sevn-gateway-gui:local .

compose-gui-up: ## Start operator stack with GUI gateway (noVNC on 6080)
	@test -f .env || { printf 'Missing .env — copy .env.example and set tokens.\n' >&2; exit 1; }
	docker compose -f $(COMPOSE_FILE) --profile gui up -d --build

compose-ci-smoke: ## Build and smoke docker/docker-compose.ci.yml + proxy transport round-trip (needs Docker)
	docker compose -f docker/docker-compose.ci.yml build
	docker compose -f docker/docker-compose.ci.yml up -d
	@sleep 8
	curl -fsS http://127.0.0.1:18787/healthz >/dev/null
	curl -fsS http://127.0.0.1:13001/health >/dev/null
	SEVN_CI_PROXY_URL=http://127.0.0.1:18787 $(PYTEST) tests/integration/test_proxy_transport_compose_roundtrip.py -v --tb=short --strict-markers -m integration
	docker compose -f docker/docker-compose.ci.yml down -v

COMPOSE_FILE ?= docker/docker-compose.yml

compose-up: ## Start operator sevn-proxy + sevn-gateway (plan/telegram-e2e-wave-plan.md TE-5)
	@test -f .env || { printf 'Missing .env — copy .env.example and set tokens.\n' >&2; exit 1; }
	docker compose -f $(COMPOSE_FILE) up -d --build

compose-down: ## Stop operator compose stack and remove containers
	docker compose -f $(COMPOSE_FILE) down

compose-logs: ## Follow logs from operator compose stack
	docker compose -f $(COMPOSE_FILE) logs -f --tail=200

compose-restart: ## Restart operator compose services
	docker compose -f $(COMPOSE_FILE) restart

log-explore: ## Explore gateway.log (CMD=signal|turns|tools|errors|tool-usage|context-drift|failures [LOG=gateway.log])
	$(UV) run python tools/explore_gateway_log.py $(CMD) $(or $(LOG),gateway.log)

telegram-checks: ## Host Telegram Bot-API getMe smoke via telegram_checks (replaces retired telegram-e2e)
	$(UV) run python -m sevn.browser.recipes.telegram_checks $(ARGS)

telegram-e2e: telegram-checks ## Alias — host Telegram verification via telegram_checks

onboard-telegram-e2e: ## Onboarding Telegram CDP smoke (requires SEVN_ONBOARD_E2E=1)
	@if [ "$$SEVN_ONBOARD_E2E" != "1" ]; then \
	  echo "Set SEVN_ONBOARD_E2E=1 to run onboarding Telegram automation smoke"; \
	  exit 0; \
	fi
	$(PYTEST) tests/onboarding/test_telegram_onboarding.py -m onboard_e2e -v --tb=short --strict-markers

improve-evals: ## Docker-first improve eval graph (`specs/33-self-improvement.md` §10.5)
	@if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \
		$(MAKE) improve-evals-docker; \
	else \
		printf 'warning: Docker unavailable — falling back to in-process pytest\n' >&2; \
		$(MAKE) improve-evals-pytest; \
	fi

improve-evals-docker: ## Run improve eval graph via docker/docker-compose.improve-evals.yml
	@mkdir -p .sevn/improve/eval-smoke/bundle
	docker compose -f docker/docker-compose.improve-evals.yml run --rm improve-evals .sevn/improve/eval-smoke/bundle
	$(MAKE) improve-evals-pytest

improve-evals-pytest: ## In-process improve eval regression tests (CI sets SEVN_IMPROVE_EVAL_IN_PROCESS=1)
	SEVN_IMPROVE_EVAL_IN_PROCESS=1 SEVN_REPO_ROOT=$(CURDIR) $(PYTEST) tests/self_improve/test_eval_graph.py tests/self_improve/test_eval_contract.py tests/self_improve/test_eval_docker_gate.py -v --tb=short --strict-markers

run: ## Run HTTP gateway (needs sevn.json under cwd); optional SEVN_GATEWAY_TOKEN
	$(UV) run uvicorn sevn.gateway.http_server:create_app --factory --host 127.0.0.1 --port 3001

proxy: ## Run egress LLM proxy (127.0.0.1:8787); factory boot from SEVN_HOME when bound
	$(UV) run --no-env-file uvicorn sevn.proxy.app:create_app --factory --host 127.0.0.1 --port 8787

proxy-env: ## Run proxy with variables from .env.proxy (gitignored); see .env.proxy.example
	@test -f $(PROXY_ENV_FILE) || { printf 'Missing %s — copy .env.proxy.example and set keys.\n' '$(PROXY_ENV_FILE)' >&2; exit 1; }
	$(UV) run --no-env-file --env-file $(PROXY_ENV_FILE) uvicorn sevn.proxy.app:create_app --factory --host 127.0.0.1 --port 8787

ui-style-check: styles-build ## Enforce operator UI design-system contract (surface CSS + HTML)
	$(UV) run python scripts/check_ui_style.py

dash-build: styles-build ## Validate Mission Control SPA + shared style package
	@test -f src/sevn/ui/spa/dashboard/index.html
	@test -f src/sevn/ui/spa/dashboard/app.js
	@test -f src/sevn/ui/spa/dashboard/style.css
	@test -f src/sevn/ui/style/index.css
	@test -f src/sevn/ui/shared/theme.js
	@grep -q '<title>sevn.bot Mission Control</title>' src/sevn/ui/spa/dashboard/index.html
	@test ! -d src/sevn/data/mission_control_dist || \
		(echo "ERROR: remove legacy src/sevn/data/mission_control_dist/ (MC-14)" >&2; exit 1)

dash-test: ## Run Mission Control dashboard tests
	$(PYTEST) tests/ui/dashboard -v --tb=short --strict-markers

incomplete-tasks: ## Requires private specs in .ignorelocal/design/specs/ (operator checkout only)
	@test -d .ignorelocal/design/specs || (echo "incomplete-tasks: .ignorelocal/design/specs not present" >&2; exit 2)
	$(UV) run python scripts/list_incomplete_spec_tasks.py --specs-dir .ignorelocal/design/specs $(INCOMPLETE_TASKS_ARGS)

find-stubs: ## Rebuild reports/stubs.{md,tsv} via scripts/find_stubs.py (`plan/stubs-closure-wave-plan.md` Wave 0A)
	$(UV) run python scripts/find_stubs.py

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .cache build dist .coverage htmlcov
	find . \( -path './.venv' -prune \) -o \( -path './.git' -prune \) -o -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

.PHONY: deploy-remote deploy-remote-check deploy-remote-dry-run deploy-remote-report-check

HOST ?= prod-vps
BUNDLE ?= bot.env

deploy-remote-check: ## SSH preflight for deploy inventory host (HOST=prod-vps)
	$(UV) run sevn deploy check --host $(HOST)

deploy-remote-dry-run: ## Print remote deploy plan without executing (BUNDLE=bot.env HOST=prod-vps)
	$(UV) run sevn deploy remote --host $(HOST) --bundle $(BUNDLE) --dry-run

deploy-remote: ## Full remote deploy from export bundle → reports/remote-deploy-*.json
	$(UV) run sevn deploy remote --host $(HOST) --bundle $(BUNDLE)

deploy-remote-report-check: ## Validate latest remote deploy JSON report against schema
	$(UV) run python scripts/check_remote_deploy_report.py

# ---------------------------------------------------------------------------
# wave-orchestrator — delegates to wave-orchestrator/Makefile
# ---------------------------------------------------------------------------

wave-orchestrator-lint: ## Ruff check + format check for wave-orchestrator/
	$(MAKE) -C wave-orchestrator lint

wave-orchestrator-typecheck: ## mypy strict for waveorch package
	$(MAKE) -C wave-orchestrator typecheck

wave-orchestrator-test: ## pytest for wave-orchestrator/tests/
	$(MAKE) -C wave-orchestrator test

wave-orchestrator-check: ## Lint + typecheck + test for wave-orchestrator (required gate)
	$(MAKE) -C wave-orchestrator check

# ---------------------------------------------------------------------------
# Logo ASCII — delegates to scripts/Makefile
# ---------------------------------------------------------------------------

logo-mark-ascii: ## Generate plain/ANSI/HTML logo under about-sevn.bot/assets/logos/
	$(MAKE) -C scripts logo-mark-ascii

logo-mark-animate: ## Trot the pixel unicorn left-to-right on stdout
	$(MAKE) -C scripts logo-mark-animate

logo-mark-ascii-dissolve: ## Play char-stagger dissolve logo animation on stdout
	$(MAKE) -C scripts logo-mark-ascii-dissolve
