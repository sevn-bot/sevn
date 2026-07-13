<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint subagents` -->
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

Implementation lives under `src/sevn/agent/`. The package contains 14 Python module(s); primary entry points include `src/sevn/agent/subagents/__init__.py`, `src/sevn/agent/subagents/media_minimax.py`, `src/sevn/agent/subagents/media_worker.py`, `src/sevn/agent/subagents/models.py`, and 2 more.

### Data and control flow

Sub-agents sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. See `about-sevn.bot/sub-agents.html` and related gateway/triager docs on the about site. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/agent/subagents/media_minimax.py` — `generate_image_bytes`, `generate_video_bytes`, `generate_music_bytes`
- `src/sevn/agent/subagents/media_worker.py` — `parse_media_task`, `require_media_generator`, `resolve_minimax_api_key`, `execute_media_generator_task`
- `src/sevn/agent/subagents/models.py` — `generate_short_id`
- `src/sevn/agent/subagents/registry.py` — `RegistrySnapshot.counts`, `RegistrySnapshot.active_children`, `RegistrySnapshot.active_specialist`, `SubAgentRegistry.wire_trace`
- `src/sevn/agent/subagents/specialists.py` — `resolve_specialist`, `resolve_specialist_transport`, `resolve_specialist_executor`, `specialist_spawn_allowed`

### Spec context

From about-sevn.bot/sub-agents.html:
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

Primary source tree: `src/sevn/agent/` (14 Python files). Operator design: `about-sevn.bot/sub-agents.html`.

### Module inventory

- `src/sevn/agent/subagents/__init__.py` — """Level-1/level-2 sub-agent orchestration (D1-D16, 'about-sevn.bot/sub-agents.html').
- `src/sevn/agent/subagents/media_minimax.py` — """MiniMax media REST adapter for the ''media_generator'' specialist (W8.2).
- `src/sevn/agent/subagents/media_worker.py` — """Execute ''media_generator'' specialist tasks and persist artifacts (W8.1/W8.2).
- `src/sevn/agent/subagents/models.py` — """Domain model for the level-1/level-2 sub-agent registry (D1/D3/D5).
- `src/sevn/agent/subagents/registry.py` — """Async-safe in-memory registry of tracked sub-agent runs (D3).
- `src/sevn/agent/subagents/specialists.py` — """Resolve specialist level-2 configs to executor settings and enforce gating (D8/W3.4).
- `src/sevn/agent/subagents/storage.py` — """''subagent_runs'' persistence: write-through, boot orphan sweep, retention prune (D10).
- `src/sevn/agent/subagents/supervisor.py` — """Spawn, kill, and complete tracked sub-agent runs against the registry (D4/D5/D9/D11).
- `src/sevn/cli/commands/subagents_cmd.py` — """''sevn subagents'' — list, kill, and limit controls (D13).
- `src/sevn/config/sections/subagents.py` — """Sub-agents (L1/L2) subtree models for ''sevn.json''.
- `src/sevn/gateway/mission_subagents_snapshot.py` — """Mission Control sub-agent snapshot assembly (registry + telemetry + storage).
- `src/sevn/gateway/queue_multi.py` — """''multi'' queue-mode orchestration helpers (D6, 'about-sevn.bot/sub-agents.html').
- … and 2 more Python modules

### Media Minimax (`src/sevn/agent/subagents/media_minimax.py`)

Public entry points:
- `generate_image_bytes` — see `src/sevn/agent/subagents/media_minimax.py`
- `generate_video_bytes` — see `src/sevn/agent/subagents/media_minimax.py`
- `generate_music_bytes` — see `src/sevn/agent/subagents/media_minimax.py`

### Media Worker (`src/sevn/agent/subagents/media_worker.py`)

Public entry points:
- `parse_media_task` — see `src/sevn/agent/subagents/media_worker.py`
- `require_media_generator` — see `src/sevn/agent/subagents/media_worker.py`
- `resolve_minimax_api_key` — see `src/sevn/agent/subagents/media_worker.py`
- `execute_media_generator_task` — see `src/sevn/agent/subagents/media_worker.py`
- `execute_media_generator_for_context` — see `src/sevn/agent/subagents/media_worker.py`

### Models (`src/sevn/agent/subagents/models.py`)

Public entry points:
- `generate_short_id` — see `src/sevn/agent/subagents/models.py`

### Registry (`src/sevn/agent/subagents/registry.py`)

Public entry points:
- `RegistrySnapshot.counts` — see `src/sevn/agent/subagents/registry.py`
- `RegistrySnapshot.active_children` — see `src/sevn/agent/subagents/registry.py`
- `RegistrySnapshot.active_specialist` — see `src/sevn/agent/subagents/registry.py`
- `SubAgentRegistry.wire_trace` — see `src/sevn/agent/subagents/registry.py`
- `SubAgentRegistry.register` — see `src/sevn/agent/subagents/registry.py`
- `SubAgentRegistry.register_if` — see `src/sevn/agent/subagents/registry.py`
- `SubAgentRegistry (+10 methods)` — see `src/sevn/agent/subagents/registry.py`

### Specialists (`src/sevn/agent/subagents/specialists.py`)

Public entry points:
- `resolve_specialist` — see `src/sevn/agent/subagents/specialists.py`
- `resolve_specialist_transport` — see `src/sevn/agent/subagents/specialists.py`
- `resolve_specialist_executor` — see `src/sevn/agent/subagents/specialists.py`
- `specialist_spawn_allowed` — see `src/sevn/agent/subagents/specialists.py`
- `merge_specialist_grants` — see `src/sevn/agent/subagents/specialists.py`

### Storage (`src/sevn/agent/subagents/storage.py`)

Public entry points:
- `list_recent_subagent_runs` — see `src/sevn/agent/subagents/storage.py`
- `persist_subagent_run` — see `src/sevn/agent/subagents/storage.py`
- `sqlite_persist_hook` — see `src/sevn/agent/subagents/storage.py`
- `sweep_orphaned_subagent_runs` — see `src/sevn/agent/subagents/storage.py`
- `prune_subagent_runs` — see `src/sevn/agent/subagents/storage.py`

### Supervisor (`src/sevn/agent/subagents/supervisor.py`)

Public entry points:
- `SubAgentSupervisor.registry` — see `src/sevn/agent/subagents/supervisor.py`
- `SubAgentSupervisor.config` — see `src/sevn/agent/subagents/supervisor.py`
- `SubAgentSupervisor.spawn` — see `src/sevn/agent/subagents/supervisor.py`
- `SubAgentSupervisor (+2 methods)` — see `src/sevn/agent/subagents/supervisor.py`

### Subagents Cmd (`src/sevn/cli/commands/subagents_cmd.py`)

Public entry points:
- `show_subagents_config` — see `src/sevn/cli/commands/subagents_cmd.py`
- `register` — see `src/sevn/cli/commands/subagents_cmd.py`

### Subagents (`src/sevn/config/sections/subagents.py`)

Public entry points:
- `resolve_limits` — see `src/sevn/config/sections/subagents.py`

### Additional modules

2 more Python files under `src/sevn/agent/` — including `src/sevn/gateway/subagents_announce.py`, `src/sevn/tools/subagent_spawn.py`.

### Extension and invariants

Follow `about-sevn.bot/sub-agents.html` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/agent/`, run `sevn readme update subagents` and `make readme-check`.

## References

- [about-sevn.bot/sub-agents.html](about-sevn.bot/sub-agents.html)
- [docs/readmes/gateway.md](docs/readmes/gateway.md)
- [about-sevn.bot/mission-control.html](about-sevn.bot/mission-control.html)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: about-sevn.bot/sub-agents.html
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/agent/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
