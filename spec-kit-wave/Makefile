.DEFAULT_GOAL := help

UV ?= uv
SKW_PY := $(UV) run python
REPO_ROOT ?= ..
SPEC_DIR ?= $(REPO_ROOT)/about-sevn.bot/specs
PRD_DIR ?= $(REPO_ROOT)/about-sevn.bot/prd
KIND ?= spec
DOCS_DIR ?= $(if $(filter prd,$(KIND)),$(PRD_DIR),$(SPEC_DIR))

.PHONY: help setup lint test spec-check prd-check docs-score

help: ## Show targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_.-]+:.*##/ { gsub(/^ /, "", $$2); printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

setup: ## Install uv-managed dev deps
	@$(UV) sync --extra dev

lint: ## Ruff check on src/ and tests/
	@$(UV) run ruff check src tests

test: ## Run pytest suite
	@$(UV) run pytest -q

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
