---
name: buzz
description: >-
  Buzz workspace integration — configure buzz-cli / buzz-acp, join channels,
  send replies, and run the sevn ACP runtime for managed agent membership.
version: "1.0.0"
see_also:
  - sevn-diagnostics
scripts:
  - path: scripts/_buzz_common.py
    description: Shared Buzz identity resolution and JSON envelope helpers.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/relay_status.py
    description: Probe the configured Buzz relay health endpoint.
    args_overview: "(no args)"
  - path: scripts/send_message.py
    description: Send a text message into a Buzz channel via the relay API.
    args_overview: "--channel-id ID --text BODY"
  - path: scripts/acp_runtime_cmd.py
    description: Print the recommended managed-runtime command for buzz-acp hosts.
    args_overview: "(no args)"
---

# buzz skill

Integrate sevn bots with Buzz workspaces using the Agent Client Protocol (ACP)
and the Buzz relay.

## Architecture

```text
Buzz relay/channel
  -> buzz-acp / managed runtime
  -> sevn acp (ACP stdio bridge)
  -> sevn gateway agent turn
  -> reply via BuzzChannelAdapter and/or buzz-cli
```

## Runtime command (buzz-acp)

Register this managed runtime command with Buzz:

```text
sevn acp
```

Install the optional extra when packaging a dedicated runtime venv:

```bash
uv sync --extra acp
```

## Configuration (secrets only — never plaintext in sevn.json)

Store credentials in the workspace secrets chain or export env vars before
starting the gateway:

| Secret logical key | Env fallback | Purpose |
| --- | --- | --- |
| `buzz.private_key` | `BUZZ_PRIVATE_KEY` | Agent signing key for relay auth |
| `buzz.relay_url` | `BUZZ_RELAY_URL` | Buzz relay base URL (no trailing slash) |

Example `channels.buzz` slice (refs only):

```json
{
  "channels": {
    "buzz": {
      "enabled": true,
      "private_key_ref": "${SECRET:keychain:buzz.private_key}",
      "relay_url_ref": "${ENV:BUZZ_RELAY_URL}"
    }
  }
}
```

Enable the adapter with `channels.buzz.enabled: true`. Gateway boot registers
`BuzzChannelAdapter` via the `sevn.channels` entry point.

## Skill scripts

Probe relay health:

```bash
python scripts/relay_status.py
```

Send a channel message (uses resolved identity):

```bash
python scripts/send_message.py --channel-id CHANNEL --text "hello from sevn"
```

Print the buzz-acp runtime command:

```bash
python scripts/acp_runtime_cmd.py
```

## buzz-cli

When `buzz-cli` is on `PATH`, operators can also manage membership and canvas
features directly; this skill focuses on relay send/status and documenting the
`sevn acp` runtime for Buzz-managed agents.
