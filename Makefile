# W0 toolchain. Later waves append targets; they do not rename these.
# pytest exits 5 when it collects nothing. The empty skeleton treats that as success.

.PHONY: setup format lint typecheck test test-host test-web test-link test-edge test-apple db-heads ci-fast ci contracts contracts-check e2e dev build-web build

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

db-heads:
	@heads=$$(uv run alembic -c host/alembic.ini heads); \
	status=$$?; \
	printf '%s\n' "$$heads"; \
	if [ $$status -ne 0 ]; then exit $$status; fi; \
	count=$$(printf '%s\n' "$$heads" | grep -cve '^[[:space:]]*$$'); \
	if [ "$$count" -ne 1 ]; then \
		printf 'expected exactly one alembic head, found %s\n' "$$count" >&2; \
		exit 1; \
	fi

ci-fast: lint typecheck db-heads contracts-check

contracts:
	uv run sevn contracts export
	uv run python scripts/gen_frame_vectors.py
	uv run python scripts/check_contracts.py --write-ts

contracts-check:
	uv run python scripts/check_contracts.py

dev:
	@pid=; \
	SEVN_DEV=1 uv run sevn serve & pid=$$!; \
	trap 'kill $$pid 2>/dev/null || true' EXIT INT TERM; \
	pnpm --dir web dev

build-web:
	pnpm --dir web run build
	rm -rf host/src/sevn/_web
	mkdir -p host/src/sevn/_web
	cp -R web/dist/. host/src/sevn/_web/

e2e:
	pnpm --dir web run build
	cd web && SEVN_RUN_MARKED="$(RUN_MARKED)" pnpm exec playwright test --config e2e/playwright.config.ts

build: build-web

# Full pre-merge gate: ci-fast, unit tests, e2e, and the web build.
ci: ci-fast test e2e build
