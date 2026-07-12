# Docker images and Compose stacks

Operator and CI container definitions for sevn.bot.

Run from the **repository root**:

```bash
# Operator stack (proxy + gateway)
docker compose -f docker/docker-compose.yml up -d --build

# CI smoke (mock upstream + proxy + gateway)
docker compose -f docker/docker-compose.ci.yml up -d --build
```

| File | Purpose |
|------|---------|
| `Dockerfile.gateway` | HTTP gateway image |
| `Dockerfile.proxy` | Egress proxy image |
| `Dockerfile.sandbox` | Tier-B sandbox image |
| `Dockerfile.gateway.browser` | Gateway + Brave/Playwright (profile `browser`) |
| `Dockerfile.gateway.gui` | Gateway + noVNC (profile `gui`) |
| `docker-compose.yml` | Operator local stack |
| `docker-compose.ci.yml` | CI integration stack |
| `docker-compose.prod.yml` | Production resource limits overlay |
| `docker-compose.improve-evals.yml` | Self-improve eval graph |

Build context is always the repo root (`context: ..` in compose files).

Makefile shortcuts: `make compose-up`, `make compose-ci-smoke`, `make docker-build-ci`.
