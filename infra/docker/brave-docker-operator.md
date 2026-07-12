# Brave Browser in Docker — operator guide

Brave is the default Chromium-compatible browser in sevn Docker **browser** and **GUI** gateway images (multi-arch `linux/amd64` + `linux/arm64`).

## Compose profiles

| Profile | Service | Use case |
|---------|---------|----------|
| (default) | `sevn-gateway` | Slim gateway, no browser |
| `browser` | `sevn-gateway-browser` | Headless Brave + Playwright fallback |
| `gui` | `sevn-gateway-gui` | Headed Brave + noVNC (via gateway `/gui`) |

Profiles **`browser`** and **`gui`** are mutually exclusive — do not enable both at once.

```bash
docker compose --profile browser up -d --build
docker compose --profile gui up -d --build
# Open authenticated viewer: http://localhost:3001/gui?token=<gateway-token>
# (or send Authorization: Bearer). A session cookie is minted for assets + WebSocket.
# VNC WebSocket is proxied at /gui/websockify — port 6080 stays internal.
```

Port **6080** (noVNC) listens on container loopback only; compose publishes **3001** for the gateway (including `/gui`).

Production overlay: `docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml --profile browser up -d`

## Config / env

- `skills.browser.engine`: `auto` | `chrome` | `chromium` | `brave`
- `SEVN_CHROME_EXECUTABLE`, `SEVN_BROWSER_ENGINE`, `SEVN_BROWSER_EXTRA_ARGS`
- `SEVN_BROWSER_HEADLESS` — wins over `skills.browser.headless` when set (GUI image sets `0`)

Proxy and ci-mock-openai images **exclude** Brave (no browser code path).

## Verification

```bash
make docker-build-ci
docker run --rm sevn-gateway-browser:local brave-browser --version
sevn doctor
```

GHCR: `gateway.browser`, `gateway.gui` (multi-arch on main / `v*` tags).
