---
name: lume
description: >-
  Apple-Silicon VM lifecycle via the lume CLI (run/stop/ls/pull); opt-in;
  also a computer-use sandbox target via `cua do switch lume`
see_also: [load_skill, run_skill_script, computer-use, cua-agent]
version: "1.0.0"
requires:
  host_os: [darwin]
  host_arch: [arm64]
  workspace_flag: skills.lume.enabled
  binary: lume
scripts:
  - path: scripts/_common.py
    description: Internal shared helpers for lume script wrappers (not invoked directly).
    abortable: true
  - path: scripts/run.py
    description: Start a Lume VM from an image or existing VM name (mutating).
    args_overview: "--name IMAGE_OR_VM [--no-display]"
    abortable: false
  - path: scripts/stop.py
    description: Stop a running Lume VM by name (mutating).
    args_overview: "--name VM_NAME"
    abortable: false
  - path: scripts/ls.py
    description: List Lume VMs (read-only).
    args_overview: "[--format json|text]"
    abortable: true
  - path: scripts/pull.py
    description: Pull a macOS VM image from the registry (mutating).
    args_overview: "--image NAME:TAG [--vm-name NAME]"
    abortable: false
---

# lume

**Apple-Silicon VM lifecycle** — pull macOS images, list VMs, start and stop local sandboxes
using the upstream [**Lume**](https://github.com/trycua/cua/tree/main/libs/lume) CLI.

Normative spec: `plan/architecture/04b-skills.md` §17b. Security: `plan/architecture/05-security-sandbox.md` §8a.
Onboarding: `plan/architecture/11-onboarding.md`.

## Activation

The harness exposes this skill **only** when **all** of the following hold:

1. `skills.lume.enabled === true` (default **false**).
2. `platform.system() == "Darwin"` on the gateway host.
3. `platform.machine()` is Apple Silicon (`arm64` / `aarch64`).
4. `lume` on `PATH` (or `skills.lume.command` override).

If the flag is true but preconditions fail, the skill **fails fast** at load.

## Relationship to computer-use

| Skill | Role |
| ----- | ---- |
| **`lume`** | VM lifecycle — `pull`, `ls`, `run`, `stop` on local Apple-Silicon VMs |
| **`computer-use`** | Drive the active target — when `skills.computer_use.target` is **`lume`**, switch with `cua do switch lume <vm>` |

After starting a VM with **`lume`**, enable **`computer-use`** with target **`lume`** (or run
`cua do switch lume <vm-name>`) to drive the guest desktop via the **`cua`** CLI.

## Workflow — pull → run → switch → drive

```bash
# Pull a Cua macOS image (once)
run_skill_script lume scripts/pull.py --image macos-sequoia-cua:latest

# List local VMs
run_skill_script lume scripts/ls.py

# Start a VM
run_skill_script lume scripts/run.py --name macos-sequoia-cua:latest

# Point computer-use at the running VM (requires computer-use enabled + cua on PATH)
cua do switch lume macos-sequoia-cua:latest
cua do screenshot

# Stop when done
run_skill_script lume scripts/stop.py --name macos-sequoia-cua:latest
```

VMs live under `~/.lume`; cached images under `~/.lume/cache`.

## Install (operator / onboarding)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/lume/scripts/install.sh)"
lume --help
```

Then set `skills.lume.enabled: true` in `sevn.json` (or use the gateway menu toggle when wired).

## Security — local VM scope

Lume VMs run **locally** on Apple Silicon using the Virtualization framework. They are **not**
routed through the sevn proxy envelope. Default flag is **`false`**. Pair with **`computer-use`**
only when the operator accepts sandbox drive on the selected VM target.
