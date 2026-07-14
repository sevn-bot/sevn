# Getting started with the sevn CLI

The `sevn` CLI is the operator surface for workspace setup, health checks, and local services. Commands are grouped into **eight Mission Control panels** (run `sevn --help` on a TTY to see them).

## First steps

1. **Bind a workspace** — run `sevn onboard` (or `sevn onboard --config` for a fast path) from your operator home.
2. **Health check** — `sevn doctor` (add `--json` for automation).
3. **Start services** — `sevn gateway start` and `sevn proxy start` when you need the gateway and egress proxy.
4. **Observe** — `sevn logs --all` and `sevn traces --last 20` for unified logs and span trees.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Usage / argv |
| 3 | Auth |
| 4 | Precondition or not implemented |

## Examples

```bash
sevn doctor --json | jq .ok
sevn gateway status
sevn logs --source gateway --lines 100 --no-follow
sevn guide doctor
```

## See also

- `sevn config` — interactive Textual section picker mirroring Telegram `/config` (`config_menu.py`)
- `sevn guide config` — config guide (this doc's companion)
- `specs/23-cli.md` — normative CLI contract
