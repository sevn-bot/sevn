<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint subagents` -->
# Sub-agents — Level-1 role runs, level-2 workers, specialists, multi queue mode, registry, and kill surfaces

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Level-1 role runs, level-2 workers, specialists, multi queue mode, registry, and kill surfaces.

## Level 1 — Overview (non-technical)

**Sub-agents** give sevn a **two-level delegation model**. A **level-1** run is a tracked, concurrent, killable execution of an existing tier role (`triager`, tier B/C/D). It may spawn **level-2** workers — generic helpers or named **specialists** (for example the MiniMax `media_generator`) — with a hard depth cap at level 2 (no level-3 nesting).

When `gateway.queue_mode` is **`multi`**, a message that arrives while a session is busy is classified as steer, cancel/supersede, or a **new level-1 task**. Every run is registered, traced, and killable from Mission Control, Telegram `/config`, and the `sevn subagents` CLI (limits are configurable under `subagents` in `sevn.json`).

## Level 2 — How it works (technical)

### Components and layout

Implementation spans [`src/sevn/agent/subagents/`](../../src/sevn/agent/subagents/) (registry, supervisor, storage, specialists, media workers), [`queue_multi.py`](../../src/sevn/gateway/queue_multi.py), [`subagent_spawn.py`](../../src/sevn/tools/subagent_spawn.py), and [`subagents_cmd.py`](../../src/sevn/cli/commands/subagents_cmd.py).

### Level-1 and level-2 runs

In [`supervisor.py`](../../src/sevn/agent/subagents/supervisor.py), [`SubAgentSupervisor.spawn`](../../src/sevn/agent/subagents/supervisor.py#L231) registers runs in [`SubAgentRegistry`](../../src/sevn/agent/subagents/registry.py#L165), persists through [`persist_subagent_run`](../../src/sevn/agent/subagents/storage.py#L119), and completes or kills via supervisor hooks. Level-2 specialists resolve through [`resolve_specialist`](../../src/sevn/agent/subagents/specialists.py#L56); the `media_generator` path executes in [`execute_media_generator_task`](../../src/sevn/agent/subagents/media_worker.py#L294).

### Multi queue mode

When the gateway is in `multi` mode, [`queue_multi.py`](../../src/sevn/gateway/queue_multi.py) classifies busy-session input (steer vs supersede vs spawn a fresh level-1 tier-B run on the same session/channel). Announcements and Mission Control snapshots flow through [`subagents_announce.py`](../../src/sevn/gateway/subagents_announce.py) and [`mission_subagents_snapshot.py`](../../src/sevn/gateway/mission_subagents_snapshot.py).

### Configuration (`sevn.json` → `subagents`)

Limits (defaults: five level-1 per role, three level-2 per level-1), enablement, and specialist grants live under the `subagents` subtree ([`config/sections/subagents.py`](../../src/sevn/config/sections/subagents.py)). Inspect with **`sevn config subagents`**; adjust via Telegram `/config`, Mission Control, or **`sevn subagents`**.

### Key modules

- [`registry.py`](../../src/sevn/agent/subagents/registry.py) — in-memory tracked runs + trace wiring
- [`supervisor.py`](../../src/sevn/agent/subagents/supervisor.py) — spawn, kill, complete lifecycle
- [`storage.py`](../../src/sevn/agent/subagents/storage.py) — SQLite `subagent_runs` persistence + retention
- [`specialists.py`](../../src/sevn/agent/subagents/specialists.py) — specialist resolution + spawn gating
- [`media_worker.py`](../../src/sevn/agent/subagents/media_worker.py) — `media_generator` task execution
- [`subagents_cmd.py`](../../src/sevn/cli/commands/subagents_cmd.py) — `sevn subagents` list/kill/limits

Normative spec: [`about-sevn.bot/specs/36-sub-agents.md`](../../about-sevn.bot/specs/36-sub-agents.md).

### Spec context

From [`about-sevn.bot/specs/36-sub-agents.md`](../../about-sevn.bot/specs/36-sub-agents.md): level-1 sub-agents are tracked, concurrent, killable tier-role runs; level-2 workers include generic helpers and named specialists; `gateway.queue_mode=multi` adds busy-session triage for steer/supersede/new-task; limits and kill surfaces are operator-configurable across MC, Telegram, and CLI.

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

- [Spec 36 — sub-agents](../../about-sevn.bot/specs/36-sub-agents.md)
- [Gateway README](gateway.md)
- [Mission Control spec](../../about-sevn.bot/specs/24-dashboard.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/36-sub-agents.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/agent/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
