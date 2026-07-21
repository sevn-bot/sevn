---
id: spec-36-sub-agents
kind: spec
title: Sub-agents (L1/L2) — Spec
status: done
owner: Alex
summary: Level-1 sub-agents (tracked, concurrent, killable role runs) that may spawn
  level-2 workers (incl. specialists); multi queue mode; limits, tracing, kill surfaces,
  media_generation skill.
last_updated: '2026-07-21'
fingerprint: sha256:99f5f915a859fe600718cdae777712488e7846cd042c5af6bb5d1d06bc25916b
related: []
sources:
- src/sevn/agent/subagents/**
- src/sevn/config/sections/subagents.py
- src/sevn/cli/commands/subagents_cmd.py
- src/sevn/data/bundled_skills/core/media_generation/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
- spec-04-tracing
- spec-12-skills-system
- spec-13-rlm-triager
- spec-14-executor-tier-b
- spec-17-gateway
- spec-18-channel-telegram
- spec-21-executor-tier-cd
- spec-23-cli
- spec-24-dashboard
build_phase: null
interfaces:
- name: MiniMaxMediaError
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: MiniMaxMediaError
- name: clone_voice_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: clone_voice_bytes
- name: generate_image_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_image_bytes
- name: generate_image_from_reference_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_image_from_reference_bytes
- name: generate_music_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_music_bytes
- name: generate_video_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_bytes
- name: generate_video_first_last_frame_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_first_last_frame_bytes
- name: generate_video_from_image_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_from_image_bytes
- name: generate_video_subject_reference_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_subject_reference_bytes
- name: generate_video_template_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_template_bytes
- name: synthesize_speech_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: synthesize_speech_bytes
- name: upload_file_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: upload_file_bytes
- name: MediaPromptVars
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: MediaPromptVars
- name: PromptTemplateMeta
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: PromptTemplateMeta
- name: VideoAgentTemplate
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: VideoAgentTemplate
- name: augment_prompt
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: augment_prompt
- name: build_media_trace
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: build_media_trace
- name: list_prompt_templates
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: list_prompt_templates
- name: list_video_agent_templates
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: list_video_agent_templates
- name: resolve_video_agent_template
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: resolve_video_agent_template
- name: MediaTask
  file: src/sevn/agent/subagents/media_worker.py
  symbol: MediaTask
- name: execute_media_generator_for_context
  file: src/sevn/agent/subagents/media_worker.py
  symbol: execute_media_generator_for_context
- name: execute_media_generator_task
  file: src/sevn/agent/subagents/media_worker.py
  symbol: execute_media_generator_task
- name: parse_media_task
  file: src/sevn/agent/subagents/media_worker.py
  symbol: parse_media_task
- name: require_media_generator
  file: src/sevn/agent/subagents/media_worker.py
  symbol: require_media_generator
- name: resolve_minimax_api_key
  file: src/sevn/agent/subagents/media_worker.py
  symbol: resolve_minimax_api_key
- name: SubAgentLimitExceeded
  file: src/sevn/agent/subagents/models.py
  symbol: SubAgentLimitExceeded
- name: SubAgentRun
  file: src/sevn/agent/subagents/models.py
  symbol: SubAgentRun
- name: SubAgentStatus
  file: src/sevn/agent/subagents/models.py
  symbol: SubAgentStatus
- name: generate_short_id
  file: src/sevn/agent/subagents/models.py
  symbol: generate_short_id
- name: RegistrySnapshot
  file: src/sevn/agent/subagents/registry.py
  symbol: RegistrySnapshot
- name: SubAgentRegistry
  file: src/sevn/agent/subagents/registry.py
  symbol: SubAgentRegistry
- name: SocialMediaManagerError
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: SocialMediaManagerError
- name: SocialMediaTask
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: SocialMediaTask
- name: assigned_skills_for
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: assigned_skills_for
- name: assigned_tools_for
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: assigned_tools_for
- name: execute_social_media_manager_for_context
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: execute_social_media_manager_for_context
- name: execute_social_media_manager_task
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: execute_social_media_manager_task
- name: parse_social_media_task
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: parse_social_media_task
- name: require_social_media_manager
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: require_social_media_manager
- name: ResolvedSpecialist
  file: src/sevn/agent/subagents/specialists.py
  symbol: ResolvedSpecialist
- name: merge_specialist_grants
  file: src/sevn/agent/subagents/specialists.py
  symbol: merge_specialist_grants
- name: resolve_specialist
  file: src/sevn/agent/subagents/specialists.py
  symbol: resolve_specialist
- name: resolve_specialist_executor
  file: src/sevn/agent/subagents/specialists.py
  symbol: resolve_specialist_executor
- name: resolve_specialist_transport
  file: src/sevn/agent/subagents/specialists.py
  symbol: resolve_specialist_transport
- name: specialist_spawn_allowed
  file: src/sevn/agent/subagents/specialists.py
  symbol: specialist_spawn_allowed
- name: list_recent_subagent_runs
  file: src/sevn/agent/subagents/storage.py
  symbol: list_recent_subagent_runs
- name: persist_subagent_run
  file: src/sevn/agent/subagents/storage.py
  symbol: persist_subagent_run
- name: prune_subagent_runs
  file: src/sevn/agent/subagents/storage.py
  symbol: prune_subagent_runs
- name: sqlite_persist_hook
  file: src/sevn/agent/subagents/storage.py
  symbol: sqlite_persist_hook
- name: sweep_orphaned_subagent_runs
  file: src/sevn/agent/subagents/storage.py
  symbol: sweep_orphaned_subagent_runs
- name: SubAgentHandle
  file: src/sevn/agent/subagents/supervisor.py
  symbol: SubAgentHandle
- name: SubAgentSpec
  file: src/sevn/agent/subagents/supervisor.py
  symbol: SubAgentSpec
- name: SubAgentSupervisor
  file: src/sevn/agent/subagents/supervisor.py
  symbol: SubAgentSupervisor
- name: register
  file: src/sevn/cli/commands/subagents_cmd.py
  symbol: register
- name: show_subagents_config
  file: src/sevn/cli/commands/subagents_cmd.py
  symbol: show_subagents_config
- name: SpecialistConfig
  file: src/sevn/config/sections/subagents.py
  symbol: SpecialistConfig
- name: SubAgentRoleLimits
  file: src/sevn/config/sections/subagents.py
  symbol: SubAgentRoleLimits
- name: SubAgentsWorkspaceConfig
  file: src/sevn/config/sections/subagents.py
  symbol: SubAgentsWorkspaceConfig
- name: resolve_limits
  file: src/sevn/config/sections/subagents.py
  symbol: resolve_limits
- name: add_prompt_var_args
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: add_prompt_var_args
- name: content_root_from_env
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: content_root_from_env
- name: main_guard
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: main_guard
- name: prompt_vars_from_args
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: prompt_vars_from_args
- name: run_media_generation
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: run_media_generation
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_image.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_image_from_reference.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_music.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_video.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_video_first_last.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_video_from_image.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_video_subject.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_video_template.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/list_prompt_templates.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/list_video_templates.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/replicate_voice.py
  symbol: main
---

## Purpose

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
Mission Control, and the CLI. `about-sevn.bot` documents the system with a
deterministically generated chart. This spec is the normative home for the
registry, levels, limits, specialists, kill semantics, and the `multi` queue
mode; see `depends_on` for the specs whose sections this design amends in
place (queue semantics, tracing spans, storage migration, dashboard panel,
Telegram menu, CLI surface, skills binding).

Full authoring (architecture, registry lifecycle state machine, `multi` flow,
specialist contract) is recorded in this spec's prose and §10 build checklist;
the original orchestration wave plan was operator-local design history (not
shipped in-repo). Locked decisions below are load-bearing for implementation
waves W1–W9.

## Locked decisions (D1–D16)

Copied from the operator-local sub-agents orchestration wave plan ("Decisions
baked into this plan" table) as of 2026-07-11 — operator-approved, do not
re-derive during later waves. (Design history, local-only — not available on a
clean clone.)

| # | Topic | Decision |
|---|-------|----------|
| D1 | Terminology | **Level-1 sub-agent** = one tracked concurrent run of an existing role: `triager`, `tier_b`, `tier_c`, `tier_d`. **Level-2 sub-agent** = worker spawned by a level-1 run (generic or specialist). Hard depth cap: level 2 cannot spawn (OpenClaw-style flat below L1). |
| D2 | Config shape | New top-level `subagents` subtree: `enabled` (default `true`), `max_level1_default: 5`, `max_level2_default: 3`, `max_override: int \| null` (when set, caps **every** limit), `agents.{triager,tier_b,tier_c,tier_d}.{max_level1,max_level2}` (null → default), `specialists.<name>` (D8). Precedence: `max_override` (as ceiling) → `agents.<role>.*` → `*_default`. |
| D3 | Registry | `SubAgentRegistry` (in `src/sevn/agent/subagents/registry.py`): authoritative in-memory async-safe map `{id → SubAgentRun}` with fields `id` (short, e.g. `a1f3`), `level`, `role`, `specialist`, `parent_id`, `session_id`, `channel`, `task_summary`, `status` (`pending/running/done/failed/killed`), `started_at`, `finished_at`, `trace_id`. Snapshot-persisted to storage (D10) for restart reconciliation; boot marks stale `running` rows as `orphaned`. |
| D4 | Supervisor | `SubAgentSupervisor` owns spawn (limit check → registry insert → asyncio task), completion callbacks, and **kill** = cooperative `task.cancel()` + status `killed` + trace event. Kill of an L1 cascades to its L2 children. |
| D5 | Limit enforcement | Spawn beyond a cap returns a typed `SubAgentLimitExceeded` result (never raises into the turn); caller falls back (queue-multi → steer with operator notice; L2 spawn tool → tool error text the model can act on). |
| D6 | `multi` queue mode | `gateway.queue_mode` Literal gains `"multi"`; `channels.busy_input_mode` gains `"multi"`; `resolve_busy_input_mode` maps it through. In `enqueue_dispatch`, when busy + `multi`: run a bounded triager **relatedness classification** (`related_steer` / `supersede_cancel` / `new_task`) over the in-flight task summary + new message; `related_steer` → existing steer inject; `supersede_cancel` → existing cancel path; `new_task` → spawn new L1 tier-B sub-agent bound to the same session/channel. Classifier timeout/failure → fall back to `steer` (never drop a message). |
| D7 | Reply attribution | Each L1 sub-agent's outbound replies carry a routing-footer tag with its short id (extend `routing_footer.py`), so parallel replies in one Telegram chat are attributable. |
| D8 | Specialists | `subagents.specialists.<name>`: `{model, provider, assigned_to: [roles], requestable_by: [roles], max_concurrent, system_prompt_ref?, skill?}`. First entry: `media_generator` → `provider: "minimax"`, `model: "minimax-3"` (alias resolved via `providers.models` catalog), `assigned_to: ["tier_b"]`, `requestable_by: ["triager","tier_b"]`, `max_concurrent: 2`. Triager can attach a specialist grant to the tier-B dispatch it produces ("requested/sent"). |
| D9 | L1→L2 spawn surface | New tool `spawn_subagent(task, specialist?)` registered for tier B (and C/D where the tool registry allows), implemented in `tier_b_tools.py` against the supervisor; generic L2 uses the parent's model config unless a specialist is named. **Default: fire-and-forget with announce-back (OpenClaw-style; operator decision 2026-07-11)** — the tool returns the run id immediately; on completion the supervisor announces the result back into the spawning session (post-turn hook / outbound path, steer-injected when the parent L1 is still running, otherwise sent to the channel with the sub-agent's routing footer). Blocking wait available behind `wait: true` for skills that need the artifact inline (bounded by remaining cascade budget). |
| D10 | Persistence | New storage table `subagent_runs` mirroring registry fields (append/update), via `storage/migrate.py` migration; retention pruning with existing storage conventions. History powers Mission Control "recent" list and `sevn subagents list --all`. |
| D11 | Budgets & timeouts | L2 spawns draw down the parent turn's `CascadeBudget`; per-sub-agent wall-clock timeout `subagents.timeout_s` (default: tier default). L1 spawned by `multi` gets its own fresh cascade budget (it is a new task). |
| D12 | Tracing | Every sub-agent run = one OTel span (`sevn.subagent`, attrs: id/level/role/specialist/parent) child of the spawning span; mission telemetry kinds `subagent_spawned` / `subagent_finished` / `subagent_killed` added to `mission_state_models.py`; Prometheus gauge `sevn_subagents_running{level,role}` + counter `sevn_subagents_total{status}`. |
| D13 | Kill surfaces | Mission Control (button per row + kill-all per role), Telegram `/config → Sub-agents → Running` (inline kill buttons, owner-only), Telegram **`/stop`** slash (L1 picker + ALL when L1 runs; session cancel when empty), CLI `sevn subagents kill <id>|--all [--role R] [--force]`. All route through supervisor kill (D4). |
| D14 | Deterministic chart | Single source-of-truth topology descriptor `about-sevn.bot/_sources/subagents-topology.json` → `scripts/gen_subagents_chart.py` renders a **deterministic** static SVG (sorted keys, fixed layout, no timestamps/randomness) embedded in new `about-sevn.bot/sub-agents.html`. `make about-site` regenerates; a `subagents-chart-check` Make step fails CI-docs when the committed SVG differs from a fresh render (byte-identical). |
| D15 | Changelog skill | Changelog workflow: tracked `.claude/skills/changelog/SKILL.md` (local-only on clone) and in-tree [`src/sevn/data/standards/README.md`](src/sevn/data/standards/README.md) + `.cursor/skills/changelog-author/SKILL.md`. Maintains root `CHANGELOG.md` in **Keep a Changelog 1.1** format; invoked before releases and at plan Finals. |
| D16 | Naming | Public name "sub-agents" everywhere (config key `subagents`, CLI `sevn subagents`, spec 36). Specialist ids are snake_case (`media_generator`); the operator-visible label for the example instance is `sub_agent_2_media_generator`. |

Full authoring landed in wave W9 (2026-07-12). Locked decisions D1–D16 below
remain load-bearing; implementation waves W1–W8 closed the append-only §10 rows.

## Public Interface

| Symbol | Module | Role |
|--------|--------|------|
| `SubAgentsWorkspaceConfig` | `src/sevn/config/sections/subagents.py` | Typed `subagents` subtree (D2) |
| `resolve_limits` | `src/sevn/config/sections/subagents.py` | Effective `(max_level1, max_level2)` per role |
| `SubAgentRun` / `SubAgentStatus` | `src/sevn/agent/subagents/models.py` | Registry row shape (D3) |
| `SubAgentLimitExceeded` | `src/sevn/agent/subagents/models.py` | Typed spawn rejection (D5) |
| `SubAgentRegistry` | `src/sevn/agent/subagents/registry.py` | Async-safe in-memory ledger (D3) |
| `SubAgentSupervisor` | `src/sevn/agent/subagents/supervisor.py` | Spawn / kill / completion (D4) |
| `resolve_specialist` | `src/sevn/agent/subagents/specialists.py` | Specialist → executor settings (D8) |
| `spawn_subagent_tool` | `src/sevn/tools/subagent_spawn.py` | Tier B/C/D L2 spawn surface (D9) |
| `build_agent_run_turn` | `src/sevn/gateway/agent_turn.py` | L1 register → run → finalize |
| `classify_busy_relatedness` | `src/sevn/agent/triager/relatedness.py` | `multi` queue classifier (D6) |
| `sevn subagents` | `src/sevn/cli/commands/subagents_cmd.py` | `list` / `kill` / `limits` (D13) |

Operator surfaces: Mission Control `GET/POST /api/v1/mission/subagents*`,
Telegram `/config → Sub-agents`, deterministic chart at `about-sevn.bot/sub-agents.html`
(D14).

## Data Model

### §5 Configuration (`subagents` subtree)

Implemented in `src/sevn/config/sections/subagents.py` (D2):

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `enabled` | `bool` | `true` | Master switch |
| `max_level1_default` | `int ≥ 0` | `5` | Default L1 cap per role |
| `max_level2_default` | `int ≥ 0` | `3` | Default L2 cap per L1 parent |
| `max_override` | `int \| null` | `null` | When set, ceilings **every** resolved limit |
| `timeout_s` | `float \| null` | tier default | Per-run wall-clock cap (D11) |
| `agents.<role>.max_level1` | `int \| null` | → default | Per-role L1 override |
| `agents.<role>.max_level2` | `int \| null` | → default | Per-role L2 override |
| `specialists.<name>` | object | `{}` | Specialist entry (D8) |

`SpecialistConfig` fields: `model`, `provider`, `assigned_to[]`, `requestable_by[]`,
`max_concurrent` (default 2), optional `skill`, `system_prompt_ref`.

Limit precedence (`resolve_limits`): `max_override` ceiling → `agents.<role>.*` →
`*_default`.

`gateway.queue_mode` and `channels.busy_input_mode` gain `"multi"` (D6) — see
spec-17-gateway amendments.

### Storage (`subagent_runs`)

Migration in `src/sevn/storage/migrate.py` (D10). Table mirrors registry fields:
`id`, `level`, `role`, `specialist`, `parent_id`, `session_id`, `channel`,
`task_summary`, `status`, `started_at`, `finished_at`, `trace_id`. Write-through on
registry transitions; boot orphan sweep marks stale `running` → `orphaned`; retention
prune follows existing storage conventions. Powers Mission Control recent list and
`sevn subagents list --all`.

## Internal Architecture

```text
Inbound message → session_manager.enqueue_dispatch (multi?)
               → agent_turn: L1 register (triager | tier B/C/D)
               → executor body
               → tier B spawn_subagent → supervisor.spawn L2
               → registry + storage persist
               → subagents_announce on L2 completion (D9)
               → routing_footer tag on L1 outbound (D7)
```

### Registry lifecycle (state machine)

```text
pending → running → done | failed | killed
                 ↘ orphaned (boot-only reconcile)
```

- **pending**: row inserted, asyncio task not yet marked running.
- **running**: body executing; counts against concurrency caps (`ACTIVE_STATUSES`).
- **done / failed**: normal completion or unhandled exception in body.
- **killed**: cooperative `task.cancel()` via supervisor (D4); L1 kill cascades to L2 children.
- **orphaned**: previous process left `running`/`pending` rows; boot sweep only (D3/D10).

`SubAgentSupervisor.spawn`: limit check → registry insert → asyncio task → callbacks
update registry + storage + trace/mission sinks.

### `multi` queue flow (D6)

When session busy and `queue_mode`/`busy_input_mode` is `multi`:

1. `classify_busy_relatedness(in_flight_summary, queued, new_message)` →
   `related_steer` | `supersede_cancel` | `new_task` (5s timeout default).
2. `related_steer` → existing steer inject path.
3. `supersede_cancel` → existing cancel/supersede path (P9 bookkeeping preserved).
4. `new_task` → spawn new L1 `tier_b` via supervisor (fresh `CascadeBudget` — D11).
5. `SubAgentLimitExceeded` or classifier failure → steer + one-line operator notice (D5).

### Specialist contract (D8)

`resolve_specialist` maps config → provider/model transport. Gating:
`assigned_to` (static assignment per role), `requestable_by` (runtime request path).
Triager `specialist_grants[]` on `TriageResult` flows into tier-B `ToolContext` so
granted specialists bypass `assigned_to` when `triager` is in `requestable_by`.

First documented specialist: `media_generator` (MiniMax-3) bound to
`media_generation` skill via `wait: true` spawn path. Execute kinds include
`image`, `image_i2i`, `video` / `video_i2v` / `video_s2v` / `video_fl2v`,
`video_template`, `music`, and `voice` (TTS + clone); voice clone passes literal
`preview_text`/`speech_text` (not the template-augmented prompt). Bundled CLIs under
`src/sevn/data/bundled_skills/core/media_generation/scripts/` (including S2V/FL2V)
drive the same worker. Downloads are capped at 100 MiB; `_persist_bytes` size-verifies
with a direct `write_bytes` fallback. CI covers these with mocked MiniMax; live smoke
requires `SEVN_MEDIA_LIVE=1`.

Second documented specialist: `social_media_manager` — browser-first social
monitoring across six platforms with per-site medium config under
`skills.social_media_manager` (not on `SpecialistConfig`).

#### `social_media_manager` L2 boundary

Platform keys match [`SocialRecipe._SUPPORTED_SITES`](src/sevn/browser/recipes/social.py):
`x`, `facebook`, `instagram`, `linkedin`, `reddit`, `tiktok`.

| Resolved medium | L2 behaviour |
|-----------------|--------------|
| `twexapi` | Execute TwexAPI REST **inline** when site is `x` and TwexAPI is enabled |
| `browser` | Return a structured CDP plan (`tool=browser`, `action=social`, `site`, `op`, …) for the **parent** turn — L2 does not attach CDP |

Medium resolution order: task JSON `medium` → `skills.social_media_manager.platforms.<site>.medium` → `default_medium` → `"browser"`. TwexAPI is **X-only** — when site ≠ `x` and medium would be `twexapi`, coerce to `browser` at runtime (no TwexAPI HTTP).

Operator config under **`skills.social_media_manager`** (D1):

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `default_medium` | `"browser" \| "twexapi"` | `"browser"` | Fallback when per-site medium unset |
| `twexapi.enabled` | bool | `false` | Opt-in; key present does not auto-enable |
| `twexapi.api_key` | string | — | `${SECRET:SEVN_SECRET_TWEXAPI}` or env |
| `twexapi.base_url` | string | TwexAPI default | REST base |
| `platforms.<site>.medium` | `"browser" \| "twexapi"` | inherits `default_medium` | Per-site operator default |

Telegram **`/config → Skills → Social Media Manager`**: cycle per-site medium (TwexAPI offered on `x` only), TwexAPI enabled toggle, Set API key via secrets wizard (`SEVN_SECRET_TWEXAPI`), readiness hints (key yes/no, CDP/profile, login).

Specialists remain **opt-in empty by default** — `subagents.specialists` defaults to `{}`; operator must explicitly add `social_media_manager` (D11/D14). Onboarding capability `skill.social_media_manager` defaults **`false`** (D12).

`medium=capabilities` returns a per-platform matrix: `{site: {medium, allowed_media, effective_medium, skills[], tools[], readiness{…}}}` (D8).

Public entrypoints: `execute_social_media_manager_task`, `parse_social_media_task`, `resolve_social_medium`, `allowed_media_for_site`, bundled `social_media_manager` skill scripts (`capabilities.py`, `session_status.py`, TwexAPI helpers).

## Behavior

- **Degenerate case**: concurrency limits at 1 reproduce classic single-agent turns.
- **L1 registration**: every triager and tier B/C/D executor run is a tracked L1 row.
- **L2 spawn**: `spawn_subagent(task, specialist?, wait=false)` default fire-and-forget;
  completion announces via steer-inject (parent still running) or outbound send with
  sub-agent routing footer.
- **Reply attribution (D7)**: parallel L1 replies include short-id footer tags
  (`⋮a1f3` style) via `routing_footer.py`.
- **Kill (D13)**: all surfaces route to `SubAgentSupervisor.kill`; Mission Control and
  Telegram kill controls owner-only; Telegram **`/agents`** lists running L1/L2 inventory
  (visible to all; distinct from Config → Agents persona); CLI `sevn subagents kill <id>|--all [--role R]`.
- **Budgets (D11)**: L2 draws parent `CascadeBudget`; `multi` spawns fresh L1 budget.

## Failure Modes

| Condition | Behaviour |
|-----------|-----------|
| Limit exceeded (D5) | `SubAgentLimitExceeded` returned; `multi` → steer notice; spawn tool → tool error string |
| Classifier timeout (D6) | Fallback `related_steer` — never drop the message |
| Specialist misconfigured | Tool/skill error naming `subagents.specialists.<name>` |
| Run timeout (D11) | Supervisor marks `failed` |
| Crash mid-run (D10) | Boot orphan sweep → `orphaned`; not silently deleted |

## Test Strategy

Unit/harness tests only — no live LLM in CI:

| Area | Tests |
|------|-------|
| Config / limits | `tests/config/sections/test_subagents.py` |
| Registry / supervisor | `tests/agent/subagents/test_registry.py`, `test_supervisor.py`, `test_storage.py` |
| Spawn tool / specialists | `tests/agent/subagents/test_spawn_subagent_tool.py`, `test_specialists.py` |
| Turn wiring | `tests/gateway/test_agent_turn_subagents.py` |
| `multi` queue | `tests/gateway/test_queue_multi.py` |
| Tracing | `tests/agent/tracing/test_subagent_trace.py` |
| Mission API | `tests/gateway/test_mission_subagents.py` |
| Telegram menu | `tests/gateway/test_config_subagents_menu.py` |
| CLI | `tests/cli/test_subagents_cmd.py` |
| Media skill | `tests/skills/test_media_generation_skill.py`, `tests/skills/test_media_generation_skill_w1_red.py` — mocked execute paths for `image_i2i` / `video_s2v` / `video_fl2v` / `video_template` / voice-clone (literal `preview_text`) plus bundled script CLIs including S2V/FL2V; `tests/agent/subagents/test_media_minimax_w1_red.py` — download size cap + `_persist_bytes` fallback; live MiniMax only under `SEVN_MEDIA_LIVE=1` |
| Social media specialist | `tests/agent/subagents/test_social_media_platform_medium.py`, `tests/skills/test_social_media_manager_skill.py`, `tests/gateway/test_social_media_manager_menu.py`, `tests/integrations/test_social_media_config.py`, `tests/integrations/test_twexapi_client.py` |

Docs gate: `make subagents-chart-check` (deterministic SVG); `make ci-docs`.

## 10. Build Checklist

### 10.1 Wave W1 — Config model & schema — append-only

- [x] `SubAgentsWorkspaceConfig` + `resolve_limits` precedence (D2) (2026-07-12 ✅: `src/sevn/config/sections/subagents.py`, `tests/config/sections/test_subagents.py`)
- [x] `gateway.queue_mode` + `channels.busy_input_mode` `multi` literals (2026-07-12 ✅: `src/sevn/config/sections/gateway.py`, `channels.py`, `infra/sevn.schema.json`)
- [x] Long descriptions + schema export (2026-07-12 ✅: `infra/sevn_config_long_description.json`, `make config-schema`)

### 10.2 Wave W2 — Registry, supervisor, persistence — append-only

- [x] `SubAgentRun` / `SubAgentRegistry` / `SubAgentSupervisor` (D3/D4) (2026-07-12 ✅: `src/sevn/agent/subagents/`)
- [x] `subagent_runs` migration + orphan sweep (D10) (2026-07-12 ✅: `src/sevn/storage/migrate.py`, `tests/fixtures/storage/golden/migration_23.sql`)
- [x] Gateway boot supervisor (2026-07-12 ✅: `src/sevn/gateway/subagents/subagents_boot.py`)

### 10.3 Wave W3 — Runtime wiring — append-only

- [x] L1 registration in `agent_turn.py` (triager + tier B/C/D register → run → finalize) (2026-07-12 ✅: `src/sevn/gateway/agent_turn.py`, `tests/gateway/test_agent_turn_subagents.py`)
- [x] `specialists.py` resolver + `assigned_to`/`requestable_by` gating (D8) (2026-07-12 ✅: `src/sevn/agent/subagents/specialists.py`, `tests/agent/subagents/test_specialists.py`)
- [x] `spawn_subagent` tool (fire-and-forget + `wait:true` + announce-back) (2026-07-12 ✅: `src/sevn/tools/subagent_spawn.py`, `src/sevn/gateway/subagents/subagents_announce.py`)
- [x] Triager `specialist_grants` → tier-B tool context (W3.4) (2026-07-12 ✅: `src/sevn/agent/triager/models.py`, `tests/gateway/test_agent_turn_subagents.py`)
- [x] L2 spawns draw parent `CascadeBudget` (D11) (2026-07-12 ✅: `ToolContext.subagent_remaining_budget_s`, `spawn_subagent_tool` wait path)
- [x] Harness tests (no LLM round-trips) (2026-07-12 ✅: `tests/agent/subagents/test_spawn_subagent_tool.py`, `tests/gateway/test_agent_turn_subagents.py`)

### 10.4 Wave W4 — Queue mode `multi` — append-only

- [x] `enqueue_dispatch` `multi` branch (related_steer / supersede_cancel / new_task) (2026-07-12 ✅: `src/sevn/gateway/session_manager.py`, `src/sevn/gateway/queue/queue_multi.py`)
- [x] Relatedness classifier with timeout → steer fallback (D6) (2026-07-12 ✅: `src/sevn/agent/triager/relatedness.py`)
- [x] L1 tier-B spawn on `new_task` with fresh cascade budget (D11) (2026-07-12 ✅: `src/sevn/gateway/agent_turn.py::_spawn_multi_l1_tier_b`)
- [x] Routing-footer sub-agent tags (D7) (2026-07-12 ✅: `src/sevn/gateway/routing/routing_footer.py`)
- [x] Limit-exceeded / classifier-timeout steer fallback with operator notice (D5) (2026-07-12 ✅: `tests/gateway/test_queue_multi.py`)
- [x] Harness tests (no LLM round-trips) (2026-07-12 ✅: `tests/gateway/test_queue_multi.py`)

### 10.5 Wave W5 — Tracing, telemetry, Prometheus — append-only

- [x] OTel `sevn.subagent` span per run with parent linkage (D12) (2026-07-12 ✅: `src/sevn/agent/tracing/subagent_trace.py`, `tests/agent/tracing/test_subagent_trace.py::test_two_level_run_emits_parented_subagent_spans`)
- [x] Mission telemetry kinds `subagent_spawned` / `subagent_finished` / `subagent_killed` (2026-07-12 ✅: `src/sevn/gateway/mission/mission_state_models.py`, `src/sevn/gateway/mission/mission_state.py`)
- [x] Prometheus `sevn_subagents_running{level,role}` + `sevn_subagents_total{status}` (2026-07-12 ✅: `src/sevn/gateway/runtime/prometheus_metrics.py`, `tests/gateway/test_metrics.py`)
- [x] Tests — OTel parentage, mission-sink counts, metrics scrape (2026-07-12 ✅: `tests/agent/tracing/test_subagent_trace.py`, `tests/gateway/test_metrics.py`)

### 10.6 Wave W6 — Mission Control panel — append-only

- [x] Snapshot — running sub-agent counts by level/role, rows with id/role/specialist/task/status/age (2026-07-12 ✅: `src/sevn/gateway/mission/mission_subagents_snapshot.py`)
- [x] `mission_api.py` + `ops.py` — `GET /mission/subagents`, `POST /mission/subagents/{id}/kill`, `POST /mission/subagents/kill_all?role=` (owner+CSRF) (2026-07-12 ✅: `src/sevn/gateway/mission/mission_api.py`, `src/sevn/ui/dashboard/api/ops.py`)
- [x] Dashboard UI — Sub-agents panel: L1/L2 chips, running table + kill, recent history, read-only limits + config link (2026-07-12 ✅: `src/sevn/ui/spa/dashboard/app.js`, `tab_registry.py`)
- [x] Tests — `tests/gateway/test_mission_subagents.py` API shapes, kill round-trip, auth-required (2026-07-12 ✅: `tests/gateway/test_mission_subagents.py`)

### 10.7 Wave W7 — Telegram `/config` + CLI — append-only

- [x] Telegram Sub-agents section — enabled, limits, max_override, live L1/L2 counts, queue mode incl. `multi`, Running kill submenu (2026-07-12 ✅: `src/sevn/gateway/menu/menu.py`, `menu_registry.py`, `menu_form_handler.py`, `menu_action_router.py`, `menu_readiness.py`)
- [x] `sevn subagents list|kill|limits` + `sevn config subagents` + doctor `subagents_registry` probe (2026-07-12 ✅: `src/sevn/cli/commands/subagents_cmd.py`, `dashboard_api_client.py`, `cli/doctor/probes.py`, `src/sevn/data/doctor_solutions.json`, `src/sevn/cli/help/panels.py`)
- [x] Tests — `tests/gateway/test_config_subagents_menu.py`, `tests/cli/test_subagents_cmd.py`, doctor golden ids (2026-07-12 ✅)
- [x] Telegram menu docs — `about-sevn.bot/Telegram Menu.html` + `make about-site` (2026-07-12 ✅)

### 10.8 Wave W8 — `media_generation` skill + `media_generator` specialist — append-only

- [x] Bundled `media_generation` skill — `generate_image` / `generate_video` / `generate_music` scripts + SKILL.md (2026-07-12 ✅: `src/sevn/data/bundled_skills/core/media_generation/`)
- [x] MiniMax media adapter isolated in `media_minimax.py`; specialist worker in `media_worker.py`; spawn tool wires `media_generator` (2026-07-12 ✅: `src/sevn/agent/subagents/media_minimax.py`, `media_worker.py`, `src/sevn/tools/subagent_spawn.py`)
- [x] Skill→specialist grant merge + config docs example (D8/W8.3) (2026-07-12 ✅: `merge_specialist_grants`, `agent_turn.py`, `infra/sevn.json.template`)
- [x] Tests — `tests/skills/test_media_generation_skill.py` mocked MiniMax + spawn wait path + `max_concurrent` (2026-07-12 ✅)

### 10.9 Wave W9 — Docs, chart, changelog skill — append-only

- [x] Full spec 36 prose + cross-edits to specs 02/03/04/12/13/14/17/18/21/23/24 and prd-04 Experience (2026-07-12 ✅: `about-sevn.bot/specs/36-sub-agents.md`, `make about-docs-index`)
- [x] Deterministic topology chart + `sub-agents.html` + Makefile `subagents-chart` / `subagents-chart-check` wired into `about-site` and `ci-docs` (2026-07-12 ✅: `scripts/gen_subagents_chart.py`, `about-sevn.bot/_sources/subagents-topology.json`)
- [x] Changelog skill wrapping existing `CHANGELOG.md` / `changelog_validate.py` machinery (2026-07-12 ✅: `.claude/skills/changelog/SKILL.md` + `src/sevn/data/standards/README.md`; local `.claude/` may be absent on clone)
- [x] `docs/readmes/subagents.md` + `make readme-check` (2026-07-12 ✅: `docs/readmes/manifest.toml`)

### 10.10 Social media manager — platform medium + browser-first specialist — append-only

- [x] `social_media_manager` L2 worker + per-platform medium resolution under `skills.social_media_manager` (2026-07-15 ✅: `src/sevn/agent/subagents/social_media_worker.py`, `src/sevn/integrations/social_media/medium.py`)
- [x] TwexAPI X-only guard + browser CDP plan return path (2026-07-15 ✅: worker + `src/sevn/integrations/twexapi/`)
- [x] Telegram `/config → Skills → Social Media Manager` menu (2026-07-15 ✅: `src/sevn/gateway/menu/social_media_manager_menu.py`)
- [x] Bundled skill + onboarding opt-in (`default: false`) + normative docs (2026-07-15 ✅: W5 spec/PRD/SKILL/onboarding)
