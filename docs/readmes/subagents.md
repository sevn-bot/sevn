<!-- generated: do not edit by hand; run `sevn readme update subagents` -->
# Sub-agents — Level-1 role runs, level-2 workers, specialists, multi queue mode, registry, and kill surfaces

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Level-1 role runs, level-2 workers, specialists, multi queue mode, registry, and kill surfaces. Level-1 sub-agents (tracked, concurrent, killable role runs) that may spawn level-2 workers (incl.

## Level 1 — Overview (non-technical)

**Sub-agents** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Level-1 role runs, level-2 workers, specialists, multi queue mode, registry, and kill surfaces.

In everyday use, sub-agents helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Level-1 sub-agents (tracked, concurrent, killable role runs) that may spawn level-2 workers (incl. specialists); multi queue mode; limits, tracing, kill surfaces, media_generation skill.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/agent/`. The package contains 0 Python module(s); primary entry points include (see source tree).

### Data and control flow

Sub-agents sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/36-sub-agents.md`, `specs/17-gateway.md`, `specs/13-rlm-triager.md`, `specs/14-executor-tier-b.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Spec context

From specs/36-sub-agents.md:
Level-1 sub-agents (tracked, concurrent, killable role runs) that may spawn level-2 workers (incl. specialists); multi queue mode; limits, tracing, kill surfaces, media_generation skill.

Give sevn.bot a two-level sub-agent system. **Level-1 sub-agents** are tracked,
concurrent, killable runs of the existing tier roles (`triager`, `tier_b`,
`tier_c`, `tier_d`); **level-2 sub-agents** are workers a level-1 run spawns
(generic or a named **specialist**, e.g. a MiniMax-3 `media_generator`), with a
hard depth cap at level 2 (OpenClaw-style flat-below-L1; no level-3 nesting).
`gateway.queue_mode` gains a third option, `multi`, where a message arriving
while a session is busy is classified by the triager as *steer*, *cancel /
supersede*, or *new task* (spawn a fresh level-1 tier-B run bound to the same
session/channel). Every sub-agent run is registered, traced, countable by
role/level, and killable from Mission Control, Telegram `/config`, and the
`sevn` CLI. Limits (default 5 level-1 per role, 3 level-2 per level-1, plus a
global override) are configurable from `sevn.json`, Telegram `/config`,
Mission Control, and the CLI. `about-sevn.bot` documents the sys

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/agent/` (0 Python files). Normative design: `specs/36-sub-agents.md`, `specs/17-gateway.md`, `specs/13-rlm-triager.md`, `specs/14-executor-tier-b.md`.

### Extension and invariants

Follow `specs/36-sub-agents.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/agent/`, run `sevn readme update subagents` and `make readme-check`.

## References

- [specs/36-sub-agents.md](specs/36-sub-agents.md)
- [specs/17-gateway.md](specs/17-gateway.md)
- [specs/13-rlm-triager.md](specs/13-rlm-triager.md)
- [specs/14-executor-tier-b.md](specs/14-executor-tier-b.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/36-sub-agents.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/agent/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
