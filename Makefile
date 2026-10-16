# W0 toolchain. Later waves append targets; they do not rename these.
# pytest exits 5 when it collects nothing. The empty skeleton treats that as success.

.PHONY: setup format lint typecheck test test-host test-web test-link test-edge test-apple ci-fast ci

PYTEST_ARGS ?=
RUN_MARKED ?=
LIVE ?=

PYTEST_FLAGS :=
ifeq ($(RUN_MARKED),1)
PYTEST_FLAGS += --runxfail
endif
ifneq ($(LIVE),1)
PYTEST_FLAGS += -m "not live"
endif

setup:
	uv sync --all-packages --all-groups --python 3.13
	@if [ -f web/package.json ]; then pnpm --dir web install; else echo "skip: web not present"; fi
	@if [ -f edge/package.json ]; then pnpm --dir edge install; else echo "skip: edge not present"; fi
	@if [ -f link/Cargo.toml ]; then cargo fetch --manifest-path link/Cargo.toml; else echo "skip: link not present"; fi
	uv run pre-commit install

format:
	uv run ruff format .
	uv run ruff check --fix .
	@if [ -f web/biome.json ]; then pnpm --dir web exec biome check --write .; else echo "skip: web not present"; fi

lint:
	uv run ruff check .
	uv run ruff format --check .
	@if [ -f web/biome.json ]; then pnpm --dir web exec biome check .; else echo "skip: web not present"; fi
	@if [ -d link ]; then cargo fmt --check --manifest-path link/Cargo.toml && cargo clippy --manifest-path link/Cargo.toml --all-targets -- -D warnings; else echo "skip: link not present"; fi
	@if [ -d edge ]; then pnpm --dir edge exec biome check .; else echo "skip: edge not present"; fi
	@if [ -d apps/apple ]; then swiftlint lint --strict --quiet apps/apple; else echo "skip: apple not present"; fi

typecheck:
	uv run pyright
	@if [ -f web/tsconfig.app.json ]; then pnpm --dir web exec tsc --noEmit -p tsconfig.app.json && pnpm --dir web exec tsc --noEmit -p tsconfig.node.json; else echo "skip: web not present"; fi
	@if [ -d edge ]; then pnpm --dir edge exec tsc --noEmit; else echo "skip: edge not present"; fi

test: test-host test-web test-link test-edge test-apple

test-host:
	@status=0; \
	uv run pytest $(PYTEST_FLAGS) $(PYTEST_ARGS) || status=$$?; \
	if [ $$status -eq 5 ]; then exit 0; fi; \
	exit $$status

test-web:
	@if [ ! -f web/package.json ]; then echo "skip: web not present"; exit 0; fi; \
	cd web && SEVN_RUN_MARKED="$(RUN_MARKED)" pnpm exec vitest run --passWithNoTests

test-link:
	@if [ ! -d link ]; then echo "skip: link not present"; exit 0; fi; \
	cargo test --manifest-path link/Cargo.toml

test-edge:
	@if [ ! -d edge ]; then echo "skip: edge not present"; exit 0; fi; \
	pnpm --dir edge exec vitest run --passWithNoTests

test-apple:
	@if [ ! -d apps/apple ]; then echo "skip: apple not present"; exit 0; fi; \
	xcodebuild test -project apps/apple/Sevn.xcodeproj -scheme Sevn-macOS -destination 'platform=macOS'

ci-fast: lint typecheck

ci: ci-fast test
