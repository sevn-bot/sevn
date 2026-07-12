---
name: cua-agent
description: >-
  Autonomous GUI loop via cua-agent — model drives the screen toward a goal;
  requires computer-use enabled and explicit per-run operator approval (HITL).
see_also: [load_skill, run_skill_script, computer-use, lume]
version: "1.0.0"
requires:
  host_os: [darwin]
  workspace_flag: skills.cua_agent.enabled
  binary: cua
scripts:
  - path: scripts/run_agent.py
    description: >-
      Run the cua-agent autonomous loop toward a goal (mutating; requires
      --approved after operator HITL confirmation).
    args_overview: "--goal STR [--model MODEL] [--max-steps N] --approved"
    abortable: false
---

# cua-agent

**Autonomous computer-use loop** — the model observes the screen and acts toward a
goal without step-by-step operator guidance. Wraps the upstream **`cua-agent`**
`ComputerAgent` loop on the active **`computer-use`** target (default **host**).

Normative spec: `plan/architecture/04b-skills.md` §17a. Security: `plan/architecture/05-security-sandbox.md` §8a.

## Activation

The harness exposes this skill **only** when **all** of the following hold:

1. `skills.cua_agent.enabled === true` (default **false**).
2. `skills.computer_use.enabled === true` when `require_computer_use` is true (default).
3. `platform.system() == "Darwin"` on the gateway host.
4. `cua` on `PATH` (`pip install cua`).

If the flag is true but preconditions fail, the skill **fails fast** at load.

## Per-run approval (HITL)

Because the default **`computer-use`** target is the operator's **real macOS desktop**,
each autonomous run requires **explicit operator approval** before the loop starts:

- Config: `skills.cua_agent.approval: per_run` (only supported mode in v1).
- Script: pass **`--approved`** only after the operator confirms the goal and target.

The agent must **not** call `run_agent.py` without prior operator consent on that turn.

## Prerequisites

1. Enable **`skills.computer_use.enabled`** and satisfy computer-use host checks (TCC, binary).
2. Enable **`skills.cua_agent.enabled`**.
3. Install deps: `pip install cua` (CLI + trajectory) and `pip install cua-agent` (autonomous loop).
4. Set a model provider API key (e.g. `ANTHROPIC_API_KEY`) for the chosen `--model`.

## Workflow — goal → loop → trajectory

```bash
# Operator confirms goal + target, then:
run_skill_script cua-agent scripts/run_agent.py \
  --goal "Open Safari and search for sevn.bot" \
  --model anthropic/claude-sonnet-4-5-20250929 \
  --approved
```

Inside the loop the agent follows **Look → Act → Verify** (same primitives as **`computer-use`**):

1. Observe the screen (snapshot / screenshot via active computer-use backend).
2. Act (click, type, key) toward the goal.
3. Verify progress; repeat until done or `--max-steps`.

On success the script runs **`cua trajectory share`** and returns a **trajectory URL** in the
JSON envelope so the operator can replay the session.

Tell the operator: `"Here is the trajectory of my session: {trajectory_url}"`

## Relationship to computer-use

| Skill | Role |
| ----- | ---- |
| **`computer-use`** | Stepwise drive — operator or tier-B agent invokes look/act/verify primitives |
| **`cua-agent`** | Autonomous loop — model plans and executes steps toward a goal |

Both share the active **`skills.computer_use.target`** (host / docker / cloud / lume).

## Security — operator-beware

Same envelope as **`computer-use`** for the active target. Host runs on the **real desktop**
with no sandbox isolation. Default flags are **`false`**; per-run approval is mandatory.

Full discussion: `plan/architecture/05-security-sandbox.md` §8a.
