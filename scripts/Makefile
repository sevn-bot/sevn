.DEFAULT_GOAL := help

# scripts/ — logo ASCII generator (repo checkout assets).
# Repo root delegates: make logo-mark-ascii | make logo-mark-animate

UV ?= uv
REPO_ROOT := $(abspath ..)

.PHONY: help logo-mark-ascii logo-mark-animate logo-mark-ascii-dissolve

help: ## Show script-local make targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

logo-mark-ascii: ## Write plain/ANSI/HTML logo under about-sevn.bot/assets/logos/
	cd $(REPO_ROOT) && $(UV) run python scripts/logo_mark_ascii.py

logo-mark-animate: ## Trot the pixel unicorn left-to-right on stdout
	cd $(REPO_ROOT) && $(UV) run python scripts/logo_mark_ascii.py --trot --fps 18 --step 2

logo-mark-ascii-dissolve: ## Play dissolve (char-stagger) row reveal animation
	cd $(REPO_ROOT) && $(UV) run python scripts/logo_mark_ascii.py --animate --transition dissolve --fps 12
