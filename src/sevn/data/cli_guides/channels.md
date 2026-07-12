# Channels CLI

Use `sevn channels` to inspect Telegram/WebChat adapters from the gateway.

## Commands

- `sevn channels status` — runtime health and session counts (`GET /api/v1/channels/status`)
- `sevn channels config` — enablement flags from `sevn.json`

Add `--json` on any subcommand for machine-readable envelopes.

## Prerequisites

- Bound workspace (`SEVN_HOME` or cwd `sevn.json`)
- Gateway running locally (loopback `dashboard.local_open` or gateway token)
