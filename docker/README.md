# Docker images and Compose stacks

Operator and CI container definitions for sevn.bot.

Run from the **repository root**:

```bash
# Operator stack (proxy + gateway) — requires .env (see below)
make compose-up
# or: docker compose -f docker/docker-compose.yml up -d --build

# First boot: gateway entrypoint auto-materializes workspace/sevn.json from
# infra/docker-onboard.json (mounted at /bootstrap/onboard-compose.json).
# Optional manual path:
#   docker compose run --rm sevn-gateway sevn onboard \
#     --config /bootstrap/onboard-compose.json --profile good_value_docker \
#     --no-install-daemon --no-start-services --no-prompt-bot-name --bot-name Sevn

# CI smoke (mock upstream + proxy + gateway)
make compose-ci-smoke
# or: docker compose -f docker/docker-compose.ci.yml up -d --build
```

## Makefile shortcuts

| Target | Purpose |
|--------|---------|
| `make compose-up` | Start operator `sevn-proxy` + default `sevn-gateway` |
| `make compose-browser-up` | Operator stack with **browser CDP** gateway (Brave) |
| `make compose-gui-up` | Operator stack with **GUI** gateway (noVNC on port 6080) |
| `make compose-down` | Stop operator stack and remove containers |
| `make compose-logs` | Follow operator stack logs (`--tail=200`) |
| `make compose-restart` | Restart operator compose services |
| `make compose-ci-smoke` | Build + health-check `docker-compose.ci.yml` |
| `make docker-build-ci` | Build sandbox, proxy, gateway, browser, and gui images |

Default operator targets use `COMPOSE_FILES=-f docker/docker-compose.yml` (via
`COMPOSE_FILE=docker/docker-compose.yml`) and fail fast when `.env` is missing
(`cp .env.example .env` first). Variant targets pass the full `-f` set inline so
exactly one gateway service binds `${SEVN_GATEWAY_PORT}`.

## Gateway variant override files

Browser and GUI gateways are **override files** that replace `sevn-gateway` (same
service name — never a second gateway on port 3001):

```bash
# Browser CDP gateway (Brave + browser-cdp)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.browser.yml up -d --build
# or: make compose-browser-up

# Headed GUI gateway + noVNC
docker compose -f docker/docker-compose.yml -f docker/docker-compose.gui.yml up -d --build
# or: make compose-gui-up
```

Default `docker compose -f docker/docker-compose.yml up` uses the slim
`Dockerfile.gateway` image. Do not combine the browser and GUI override files in
one invocation — each file set defines its own `sevn-gateway` variant.

Production resource limits overlay (W3 updates service keys in `docker-compose.prod.yml`):

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.browser.yml -f docker/docker-compose.prod.yml up -d
```

## Environment prerequisites

Copy [`.env.example`](../.env.example) to `.env` in the repo root before
`make compose-up` or variant invocations. Minimum operator vars:

| Variable | Purpose |
|----------|---------|
| `SEVN_TELEGRAM_BOT_TOKEN` | Telegram bot token (optional for local HTTP-only dev) |
| `OPENAI_API_KEY` | Provider key injected into the proxy container as a **plain env var** (`docker-compose.yml` `sevn-proxy.environment`). Docker secrets / mounted secret files are a tracked follow-up — not shipped in this stack. |
| `SEVN_GATEWAY_PORT` | Host port for gateway HTTP (default `3001`) |
| `SEVN_GATEWAY_TOKEN` | Gateway bearer for `/login` and authenticated routes |
| `SEVN_SECRETS_PASSPHRASE` | Secrets-store passphrase fallback |
| `SEVN_PROXY_URL` | Gateway → proxy base URL (compose sets `http://sevn-proxy:8787` internally) |

When the egress proxy shared-secret guard is enabled, set matching
`SEVN_PROXY_SHARED_SECRET` on **both** gateway and proxy (see
[`docs/readmes/proxy-egress.md`](../docs/readmes/proxy-egress.md)). Onboarding
generates and stores the secret automatically; without it, guarded routes return
**503** unless `SEVN_PROXY_ALLOW_UNAUTHENTICATED=1` (dev-only, loudly logged).

**Mission Control on loopback:** opening `http://127.0.0.1:${SEVN_GATEWAY_PORT}/mission/…`
without the boot `dashboard-local-token` is denied when local-open is effective.
Use `sevn dashboard` (CLI appends the token) or set `dashboard.local_open_trust_address:
true` in `sevn.json` only when you intentionally want tokenless direct-loopback access.

## Image and compose files

| File | Purpose |
|------|---------|
| `Dockerfile.gateway` | HTTP gateway image |
| `Dockerfile.proxy` | Egress proxy image |
| `Dockerfile.sandbox` | Tier-B sandbox image |
| `Dockerfile.gateway.browser` | Gateway + Brave/browser-cdp (browser override) |
| `Dockerfile.gateway.gui` | Gateway + noVNC (gui override) |
| `docker-compose.yml` | Operator local stack (default gateway) |
| `docker-compose.browser.yml` | Browser CDP gateway override (`sevn-gateway` replacement) |
| `docker-compose.gui.yml` | Headed GUI gateway override (`sevn-gateway` replacement) |
| `docker-compose.ci.yml` | CI integration stack |
| `docker-compose.prod.yml` | Production resource limits overlay |
| `docker-compose.improve-evals.yml` | Self-improve eval graph |

Build context is always the repo root (`context: ..` in compose files).

## GHCR image tags (operator default)

CI (`ci-cd.yml`) publishes images with a **quarantine → scan → sign → promote by digest**
lifecycle (C12.3 / C13.1 / D45):

| Tag | When it appears | Operator use |
|-----|-----------------|--------------|
| `:quarantine-<sha>` | Immediately after build, before Trivy | **Not consumable** — pre-scan only |
| `:<sha>` | After supply-chain promotes by digest | Prefer this (or `@sha256:…`) |
| `:vX.Y.Z` | Same promote step on `v*` tag builds | Prefer digest pin in prod |
| `:latest` | **Not written** from `main` while phase4/5 are stubs | Treat any pre-existing `:latest` as **unverified** |

**Operator default:** pin by digest (`ghcr.io/<owner>/<repo>/<image>@sha256:…`), never
`:latest`. Compose / sandbox defaults that still say `:dev` / mutable tags are being
replaced by Batch B's single build-stamped constant
(`DEFAULT_SANDBOX_IMAGE` in `src/sevn/security/sandbox_runtime.py`, plan D42) — **do not**
add a second pinned-digest constant here. Until Batch B merges, override with
`rlm.docker_image` (schema) pointing at a digest you trust from a promoted SHA tag.
