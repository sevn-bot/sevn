.DEFAULT_GOAL := help

UV ?= uv
SKW_PY := $(UV) run python
REPO_ROOT ?= ..
SPEC_DIR ?= $(REPO_ROOT)/about-sevn.bot/specs
PRD_DIR ?= $(REPO_ROOT)/about-sevn.bot/prd
KIND ?= spec
DOCS_DIR ?= $(if $(filter prd,$(KIND)),$(PRD_DIR),$(SPEC_DIR))

.PHONY: help setup lint test spec-check prd-check docs-score spec-sync prd-sync install-skills github-issue-triage github-issue-triage-run

help: ## Show targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_.-]+:.*##/ { gsub(/^ /, "", $$2); printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

setup: ## Install uv-managed dev deps
	@$(UV) sync --extra dev

lint: ## Ruff check on src/ and tests/
	@$(UV) run ruff check src tests
	@cd $(REPO_ROOT) && $(UV) run python scripts/check_docstrings.py \
		spec-kit-wave/src/skw/doc_score.py \
		spec-kit-wave/src/skw/doc_folder.py \
		spec-kit-wave/src/skw/spec_validate.py \
		spec-kit-wave/src/skw/changelog_validate.py \
		spec-kit-wave/src/skw/cli.py \
		spec-kit-wave/src/skw/doc_validate.py \
		spec-kit-wave/tests

test: ## Run pytest suite (uses parent repo uv env for about-docs sync imports)
	@cd $(REPO_ROOT) && $(UV) run pytest -q spec-kit-wave/tests

spec-check: ## Validate+score every spec in SPEC_DIR (default about-sevn.bot/specs)
	@$(SKW_PY) -m skw.doc_folder validate --kind spec --dir $(SPEC_DIR) --repo-root $(REPO_ROOT)

prd-check: ## Validate+score every PRD in PRD_DIR (SCORE=1 for score-only gate)
	@if [ "$(SCORE)" = "1" ]; then \
		$(SKW_PY) -m skw.doc_folder score --kind prd --dir $(PRD_DIR) --repo-root $(REPO_ROOT); \
	else \
		$(SKW_PY) -m skw.doc_folder validate --kind prd --dir $(PRD_DIR) --repo-root $(REPO_ROOT); \
	fi

docs-score: ## Score every doc in DOCS_DIR for KIND=spec|prd
	@$(SKW_PY) -m skw.doc_folder score --kind $(KIND) --dir $(DOCS_DIR) --repo-root $(REPO_ROOT)

spec-sync: ## Refresh frontmatter + scaffold missing specs in SPEC_DIR (D6/D8)
	@cd $(REPO_ROOT) && PYTHONPATH=src:spec-kit-wave/src $(UV) run python -m skw.doc_folder sync --kind spec --dir about-sevn.bot/specs --repo-root .

prd-sync: ## Refresh frontmatter + scaffold missing PRDs in PRD_DIR (D6/D8)
	@cd $(REPO_ROOT) && PYTHONPATH=src:spec-kit-wave/src $(UV) run python -m skw.doc_folder sync --kind prd --dir about-sevn.bot/prd --repo-root .

KIT_ROOT := $(abspath $(CURDIR))
SKW_RENDER := $(UV) run python -m skw.render
CONTEXT ?=
PATHS ?=
ISSUE ?=
QUEUE ?=

install-skills: ## Install skills/* into ../.cursor/skills + ../.claude/skills — [COPY=1] to copy
	@_copy='$(COPY)'; \
	for _dir in "$(KIT_ROOT)"/skills/*/; do \
	  _name="$$(basename "$$_dir")"; \
	  _src="$(KIT_ROOT)/skills/$$_name"; \
	  for _target_root in "$(REPO_ROOT)/.cursor/skills" "$(REPO_ROOT)/.claude/skills"; do \
	    mkdir -p "$$_target_root"; \
	    _dst="$$_target_root/$$_name"; \
	    rm -rf "$$_dst"; \
	    if [ -n "$$_copy" ]; then cp -R "$$_src" "$$_dst"; echo "copied  $$_name -> $$_dst"; \
	    else ln -s "$$_src" "$$_dst"; echo "linked  $$_name -> $$_dst"; fi; \
	  done; \
	done

_github_issue_triage_args = $(SKW_RENDER) --stage github-issue-triage \
	  $(if $(CONTEXT),--context '$(CONTEXT)',) $(if $(PATHS),--paths '$(PATHS)',) \
	  $(if $(ISSUE),--issue '$(ISSUE)',) $(if $(QUEUE),--queue,) \
	  --kit-root "$(KIT_ROOT)"

github-issue-triage: ## Render github-issue-triage prompt — [ISSUE=] [QUEUE=1] [CONTEXT=] [PATHS=]
	@$(call _github_issue_triage_args)

github-issue-triage-run: ## Headless github-issue-triage — [ISSUE=] [QUEUE=1] [CONTEXT=] [PATHS=]
	@command -v cursor-agent >/dev/null 2>&1 || { echo "cursor-agent not on PATH" >&2; exit 1; }; \
	_stage_dir="$(KIT_ROOT)/.loop/stage-$$(date +%s)"; mkdir -p "$$_stage_dir"; \
	_out="$$_stage_dir/prompt.md"; \
	$(call _github_issue_triage_args) --output "$$_out"; \
	SKW_WORKSPACE='$(REPO_ROOT)' SKW_RESOLVE_STAGE=github-issue-triage bash "$(KIT_ROOT)/scripts/agent.sh" --rendered "$$_out"
