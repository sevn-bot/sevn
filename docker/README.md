# Docker images and Compose stacks

Operator and CI container definitions for sevn.bot.

Run from the **repository root**:

```bash
# Operator stack (proxy + gateway) — requires .env (see below)
make compose-up
# or: docker compose -f docker/docker-compose.yml up -d --build

# CI smoke (mock upstream + proxy + gateway)
make compose-ci-smoke
# or: docker compose -f docker/docker-compose.ci.yml up -d --build
```

## Makefile shortcuts

| Target | Purpose |
|--------|---------|
| `make compose-up` | Start operator `sevn-proxy` + default `sevn-gateway` |
| `make compose-gui-up` | Operator stack with **GUI** gateway (noVNC on port 6080) |
| `make compose-down` | Stop operator stack and remove containers |
| `make compose-logs` | Follow operator stack logs (`--tail=200`) |
| `make compose-restart` | Restart operator compose services |
| `make compose-ci-smoke` | Build + health-check `docker-compose.ci.yml` |
| `make docker-build-ci` | Build sandbox, proxy, gateway, browser, and gui images |

All operator targets use `COMPOSE_FILE=docker/docker-compose.yml` and fail fast when
`.env` is missing (`cp .env.example .env` first).

## Compose profiles

Optional gateway variants swap Dockerfiles via profiles (mutually exclusive):

```bash
# Browser CDP gateway (Brave + browser-cdp) — profile browser
docker compose -f docker/docker-compose.yml --profile browser up -d --build

# Headed GUI gateway + noVNC — profile gui
docker compose -f docker/docker-compose.yml --profile gui up -d --build
# or: make compose-gui-up
```

Default `docker compose up` (no profile) uses the slim `Dockerfile.gateway` image.
Profiles `browser` and `gui` each exclude the other.

Production resource limits overlay:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml --profile browser up -d
```

## Environment prerequisites

Copy [`.env.example`](../.env.example) to `.env` in the repo root before
`make compose-up` or profile invocations. Minimum operator vars:

| Variable | Purpose |
|----------|---------|
| `SEVN_TELEGRAM_BOT_TOKEN` | Telegram bot token (optional for local HTTP-only dev) |
| `OPENAI_API_KEY` | Provider key injected into the proxy container |
| `SEVN_GATEWAY_PORT` | Host port for gateway HTTP (default `3001`) |
| `SEVN_GATEWAY_TOKEN` | Gateway bearer for `/login` and authenticated routes |
| `SEVN_SECRETS_PASSPHRASE` | Secrets-store passphrase fallback |
| `SEVN_PROXY_URL` | Gateway → proxy base URL (compose sets `http://sevn-proxy:8787` internally) |

When the egress proxy shared-secret guard is enabled, set matching
`SEVN_PROXY_SHARED_SECRET` on **both** gateway and proxy (see
[`docs/readmes/proxy-egress.md`](../docs/readmes/proxy-egress.md)). Empty/unset skips
the guard (dev-only).

## Image and compose files

| File | Purpose |
|------|---------|
| `Dockerfile.gateway` | HTTP gateway image |
| `Dockerfile.proxy` | Egress proxy image |
| `Dockerfile.sandbox` | Tier-B sandbox image |
| `Dockerfile.gateway.browser` | Gateway + Brave/browser-cdp (profile `browser`) |
| `Dockerfile.gateway.gui` | Gateway + noVNC (profile `gui`) |
| `docker-compose.yml` | Operator local stack |
| `docker-compose.ci.yml` | CI integration stack |
| `docker-compose.prod.yml` | Production resource limits overlay |
| `docker-compose.improve-evals.yml` | Self-improve eval graph |

Build context is always the repo root (`context: ..` in compose files).
