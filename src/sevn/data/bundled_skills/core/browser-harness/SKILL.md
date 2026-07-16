---
name: browser-harness
description: Thin CDP harness with extendable helpers.py for open-ended browser control.
version: "0.1.0"
see_also:
  - browser
egress:
  - "*"
scripts:
  - path: scripts/probe.py
    description: Probe CDP HTTP endpoints (/json/version, /json/list) without WebSocket.
    args_overview: "[cdp_url]"
    abortable: true
  - path: scripts/cdp.py
    description: Raw Chrome DevTools Protocol call via helpers.browser_cdp (PermissionConfig.tools.browser.cdp).
    args_overview: "<method> [--params JSON] [--session-id ID]"
    abortable: false
  - path: scripts/run.py
    description: Execute a Python file with helpers.py preloaded (extend helpers mid-task).
    args_overview: "<path/to/script.py> [args...]"
    abortable: false
---

# browser-harness skill

Minimal CDP harness: **`helpers.py`** exposes starter primitives and **`browser_cdp`**
raw passthrough. The agent may **edit `helpers.py` mid-task** to add missing helpers.

Prefer the native **`browser`** tool for stable automation; use **browser-harness**
for exploratory flows or one-off CDP behaviour.

## Files

| Path | Role |
|------|------|
| `helpers.py` | Callable surface; safe to extend in-session |
| `scripts/run.py` | Run Python with helpers injected into globals |
| `scripts/cdp.py` | CLI wrapper for `browser_cdp` |
| `scripts/probe.py` | CDP HTTP health probe |

## Authorisation

`browser_cdp` is gated by **`PermissionConfig.tools.browser.cdp: true`** (default **false**).

## Requirements

Chrome with remote debugging on **`SEVN_CDP_URL`** (default `http://127.0.0.1:9222`), plus:

```bash
uv sync --extra browser-cdp
```

## Egress

CDP control traffic stays on loopback. Outbound HTTP triggered by page navigation still
follows workspace proxy / sandbox egress posture (`specs/08-sandbox.md`).
