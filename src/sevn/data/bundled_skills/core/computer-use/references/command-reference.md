# CUA command reference (computer-use)

Complete argument syntax for `cua do` and `cua trajectory` commands used by the **computer-use**
drive skill. Adapted from upstream [`trycua/cua` gui-automation](https://github.com/trycua/cua).

## Global flags

| Flag | Effect |
| ---- | ------ |
| `--no-record` | Disable trajectory recording for this command |

Usage: `cua do --no-record <action> [args]`

## Target management

```
cua do switch <provider> [name]
```

Providers: `cloud`, `cloudv2`, `docker`, `lume`, `lumier`, `winsandbox`, `host`

- `name` is required for all providers except `host` and `winsandbox`
- Target persists in `~/.cua/do_target.json` — set once, then operate
- Align `skills.computer_use.target` with the provider you switch to

```
cua do status
```

Show the current target and zoom state.

```
cua do ls [provider]
```

List VMs for a provider. If `provider` is omitted, uses the current target's provider.

## Host consent

```
cua do-host-consent
```

One-time consent to grant AI control of the local machine. Creates `~/.cua/host_consented`.
Required before `cua do switch host` when using the CLI path (alternative to cua-driver MCP).

## Screenshot and snapshot

```
cua do screenshot [--save PATH]
```

Take a screenshot. Returns the image path.

```
cua do snapshot ["extra instructions"]
```

Screenshot plus AI-powered screen summary (JSON with `summary` and `elements` with coordinates).
Requires `ANTHROPIC_API_KEY`. Controlled by `skills.computer_use.snapshot.annotate`.

## Window zoom

```
cua do zoom "Window Name"
cua do unzoom
```

Crop subsequent screenshots to a named window (window-relative coordinates) or restore full desktop.

## Input actions

```
cua do click <x> <y> [left|right|middle]
cua do dclick <x> <y>
cua do move <x> <y>
cua do type "text"
cua do key <key>
cua do hotkey <combo>
cua do scroll <direction> [amount]
cua do drag <x1> <y1> <x2> <y2>
```

Common keys: `enter`, `escape`, `tab`, `space`, `backspace`, `delete`, arrow keys, `f1`–`f12`.
Hotkey examples: `cmd+c`, `ctrl+shift+s`, `alt+f4`.

## Shell and open

```
cua do shell "command"
cua do open <url|path>
```

## Window management

```
cua do window ls [app]
cua do window focus <id>
cua do window activate <id>
cua do window unfocus
cua do window minimize <id>
cua do window maximize <id>
cua do window close <id>
cua do window resize <id> <width> <height>
cua do window move <id> <x> <y>
cua do window info <id>
```

## Trajectory commands

All under `cua trajectory` (alias: `cua traj`).

```
cua trajectory ls [machine] [--json]
cua trajectory view [target] [--port PORT]
cua trajectory share [target] [--no-open] [--api-url URL]
cua trajectory export [target] [--output PATH] [--quality N] [--no-open]
cua trajectory clean [--older-than DAYS] [--machine NAME] [-y]
cua trajectory stop
```

Sessions are stored under `~/.cua/trajectories/{machine}/{session}/`.
Use `cua trajectory share` at the end of a drive session and surface the HTTPS link to the operator.
Configure export directory via `skills.computer_use.trajectory.export_dir`.
