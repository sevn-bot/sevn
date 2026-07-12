---
name: computer-use
description: >-
  Drive a computer via trycua/cua — host cua-driver MCP passthrough plus sandbox
  providers (docker/cloud/lume) through the cua CLI; opt-in; macOS-only
see_also: [load_skill, run_skill_script, run_skill_runnable, playwright-browser, lume]
version: "2.0.0"
requires:
  host_os: [darwin]
  workspace_flag: skills.computer_use.enabled
  binary: cua-driver
mcp_passthrough:
  server: cua-driver
  when: skills.computer_use.target == host
---

# computer-use

**Eyes and hands on a real computer** — see the screen, move the mouse, click, type, and verify
layouts. One bundled skill, **target-selected**:

| Target | Backend | Operator action |
| ------ | ------- | ---------------- |
| `host` (default) | **cua-driver** MCP passthrough | Grant TCC; agent calls MCP tools directly |
| `docker` / `cloud` / `lume` | **`cua` CLI** (`cua do …`) | `pip install cua`; `cua do switch <provider>` |

Normative spec: `plan/architecture/04b-skills.md` §17. Security: `plan/architecture/05-security-sandbox.md` §8a.
Onboarding: `plan/architecture/11-onboarding.md`.

## Activation

The harness exposes this skill **only** when **all** of the following hold:

1. `skills.computer_use.enabled === true` in the resolved `sevn.json`.
2. `platform.system() == "Darwin"` on the host running the harness.
3. **Host target:** `cua-driver` on `PATH` (or `skills.computer_use.command` override).
4. **Sandbox target** (`docker` / `cloud` / `lume`): `cua` on `PATH` (or command override).

Set `skills.computer_use.target` to choose the provider (default **`host`**). If the flag is true but
preconditions fail, the skill **fails fast** at load — the harness must not silently disable.

## Host target — MCP passthrough (no scripts)

When `skills.computer_use.target` is **`host`**, the harness registers the Cua Driver MCP server and
the agent calls its tools via standard MCP plumbing (`plan/architecture/04-tools.md` §6). This skill
ships **without `scripts/`** on the host path — tools come from upstream `cua-driver mcp`.

Tool surface: whatever the Cua Driver MCP server publishes — see
[`libs/cua-driver/README.md`](https://github.com/trycua/cua/tree/main/libs/cua-driver).

## Sandbox targets — `cua do` CLI

When `target` is `docker`, `cloud`, or `lume`, use the **`cua`** CLI instead of MCP passthrough:

```bash
cua --version
cua do switch docker my-container    # or cloud / lume — see Providers below
cua do status
```

For **host** via the CLI (alternative to MCP): one-time consent then switch:

```bash
cua do-host-consent && cua do switch host
```

> `ANTHROPIC_API_KEY` is optional. With it, `cua do snapshot` returns AI-annotated element
> coordinates. Without it, use `cua do screenshot` and read the image. Toggle preference via
> `skills.computer_use.snapshot.annotate`.

## Workflow — Look → Act → Verify

Repeat until the task is done, then share the trajectory:

```bash
cua do screenshot
cua do click 450 280
cua do screenshot
cua trajectory share
```

Re-screenshot after every UI change — coordinates go stale when the screen changes.

### Zoom for precision (host or small targets)

```bash
cua do zoom "Google Chrome"
cua do screenshot
cua do click 112 44
cua do unzoom
```

### Providers

| Provider | Example switch |
| -------- | -------------- |
| `host` | `cua do switch host` |
| `docker` | `cua do switch docker my-container` |
| `cloud` | `cua do switch cloud my-vm` |
| `lume` | `cua do switch lume my-vm` (see **`lume`** skill for VM lifecycle) |

Full command syntax: [references/command-reference.md](references/command-reference.md).

## Trajectory

Every `cua do` action is auto-recorded under `~/.cua/trajectories/{machine}/{session}/`.

```bash
cua trajectory share      # upload and return HTTPS link — share with the operator
cua trajectory ls
cua trajectory export     # self-contained HTML report
```

Config knobs: `skills.computer_use.trajectory.enabled`, `.share`, `.export_dir`.

## Install (operator / onboarding)

**Host MCP (`cua-driver`):**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"
```

Grant **Accessibility**, **Screen Recording**, and **Automation** in System Settings → Privacy & Security.
`sevn doctor` warns when entitlements are missing.

**Sandbox CLI + snapshot/trajectory:**

```bash
pip install cua
```

## Security — operator-beware

**Host target** operates **outside** the sandbox / proxy envelope:

- No VM, no container — runs on the operator's real macOS desktop.
- Sees what the operator sees; acts as the operator; host-network egress.

**Sandbox targets** (`docker` / `cloud`) isolate GUI automation inside the selected provider.
**`lume`** runs local Apple-Silicon VMs. The workspace flag defaults **`false`** for all paths.
Full discussion: `plan/architecture/05-security-sandbox.md` §8a.

## Quick reference

| Action | Command |
| ------ | ------- |
| Connect | `cua do switch <provider> [name]` |
| Screenshot | `cua do screenshot` |
| AI-annotated screen | `cua do snapshot ["instructions"]` |
| Click | `cua do click <x> <y> [button]` |
| Type | `cua do type "text"` |
| Key / hotkey | `cua do key <key>` / `cua do hotkey <combo>` |
| Zoom / unzoom | `cua do zoom "App"` / `cua do unzoom` |
| Share session | `cua trajectory share` |
