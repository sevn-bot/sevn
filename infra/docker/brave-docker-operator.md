# Brave Browser in Docker — operator guide

Brave is the default Chromium-compatible browser in sevn Docker **browser** and **GUI** gateway images (multi-arch `linux/amd64` + `linux/arm64`).

## Compose override files

| Override | Service | Use case |
|----------|---------|----------|
| (default) | `sevn-gateway` | Slim gateway, no browser |
| `docker-compose.browser.yml` | `sevn-gateway` (browser image) | Headless Brave + native CDP (`browser-cdp`) |
| `docker-compose.gui.yml` | `sevn-gateway` (GUI image) | Headed Brave + noVNC (via gateway `/gui`) |

**Browser** and **GUI** override files are mutually exclusive — do not combine them.

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.browser.yml up -d --build
docker compose -f docker/docker-compose.yml -f docker/docker-compose.gui.yml up -d --build
# or: make compose-browser-up / make compose-gui-up
# Open authenticated viewer: http://localhost:3001/gui?token=<gateway-token>
# (or send Authorization: Bearer). A session cookie is minted for assets + WebSocket.
# VNC WebSocket is proxied at /gui/websockify — port 6080 stays internal.
```

Port **6080** (noVNC) listens on container loopback only; compose publishes **3001** for the gateway (including `/gui`).

Production overlay:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.browser.yml -f docker/docker-compose.prod.yml up -d
```

Legacy `--profile browser|gui` and `COMPOSE_PROFILES=browser|gui` without the matching override file are rejected by `scripts/check-compose-default.sh`.

## Config / env

- `skills.browser.engine`: `auto` | `chrome` | `chromium` | `brave`
- `SEVN_CHROME_EXECUTABLE`, `SEVN_BROWSER_ENGINE`, `SEVN_BROWSER_EXTRA_ARGS`
- `SEVN_BROWSER_HEADLESS` — wins over `skills.browser.headless` when set (GUI image sets `0`)
- `SEVN_GATEWAY_TOKEN` — required; copy `.env.example` to `.env` and set a non-sentinel value

Proxy and ci-mock-openai images **exclude** Brave (no browser code path).

## Verification

```bash
make docker-build-ci
docker run --rm sevn-gateway-browser:local brave-browser --version
sevn doctor
```

GHCR: `gateway.browser`, `gateway.gui` (multi-arch on main / `v*` tags).
