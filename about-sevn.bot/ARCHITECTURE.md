# about-sevn.bot — architecture index

Canonical evolution orientation for agents. Deep folder contract and read order also live at [`evolution/ARCHITECTURE.md`](../evolution/ARCHITECTURE.md).

## Agent read order

1. This file (or `evolution/ARCHITECTURE.md` when only that path exists).
2. [`specs-index.md`](specs-index.md) — compact map of the design specs.
3. [`graphify-out/GRAPH_REPORT.md`](../graphify-out/GRAPH_REPORT.md) when Graphify is enabled.
4. `<checkout>/.sevn/MYCODE.md` when present.
5. Package source via tier-B tools: `source_code/<relative>` (read-only).
6. Code writes only under `workspace/.sevn/code-worktrees/<issue-id>/`.

Normative requirements remain in the local-only design docs (PRDs and specs).

## Concept index

Curated map of the load-bearing concepts and their primary source files.
The whole checkout is mirrored read-only into the workspace at `source_code/`
on every gateway boot, so the agent reads each path with ordinary
workspace-relative file tools (e.g. `read` with path
`source_code/src/sevn/agent/triager/run.py`). There is no `@repo/` prefix.

### Agent tiers

- **Context graphs (HTML)** — ordered LLM input slots per agent: [`agent-context.html`](agent-context.html). Regenerate with `make agent-context-manifest-generate` then `make about-site`.
- **Triager** — routing brain that picks tier/intent/tools per turn.
  - Prompt assembly: `source_code/src/sevn/agent/triager/prompt.py`
  - Runtime: `source_code/src/sevn/agent/triager/run.py`
  - Routing policy + fast greeting path: `source_code/src/sevn/agent/triager/routing_policy.py`
  - Per-turn context builder: `source_code/src/sevn/agent/triager/context.py`
- **Tier A** — triager-only short replies (greetings, thanks, bye). No executor.
  - Canned reply pool: `source_code/src/sevn/agent/triager/routing_policy.py` (`_TIER_A_REPLIES`).
- **Tier B** — Pydantic-AI executor with lazy tool loading.
  - Harness: `source_code/src/sevn/agent/executors/b_harness.py`
  - Model adapter: `source_code/src/sevn/agent/adapters/tier_b_model.py`
  - Persona / system-prompt blocks: `source_code/src/sevn/agent/persona.py`
- **Tier C/D** — Lambda-RLM / planner backend.
  - Harness: `source_code/src/sevn/agent/executors/cd_harness.py`
  - Runtime backends: `source_code/src/sevn/agent/executors/lambda_rlm_runtime.py`
  - Plan gate (approval): `source_code/src/sevn/agent/executors/plan_gate_store.py`

### Gateway

- Turn dispatcher: `source_code/src/sevn/gateway/agent_turn.py`
- HTTP server + lifespan: `source_code/src/sevn/gateway/http_server.py`
- Channel router (outbound spine): `source_code/src/sevn/gateway/channel_router.py`
- Session manager + JSONL mirror: `source_code/src/sevn/gateway/session_manager.py`, `source_code/src/sevn/gateway/session_mirror.py`
- Turn finalizer (placeholder/edit dance): `source_code/src/sevn/gateway/turn_finalizer.py`
- Menus + callbacks: `source_code/src/sevn/gateway/commands/menu_action_router.py`,
  `source_code/src/sevn/gateway/commands/menu_form_handler.py`,
  `source_code/src/sevn/gateway/commands/file_link_callback_handler.py`

### Channels

- Telegram adapter: `source_code/src/sevn/channels/telegram.py`
- Webchat adapter: `source_code/src/sevn/channels/webchat.py`
- Telegram callback overflow store: `source_code/src/sevn/channels/callback_overflow.py`
- File-link inline buttons (`[📎 send: <path>]` marker): `source_code/src/sevn/channels/telegram_file_links.py`

### Tools and skills

- Tool registry / decorator: `source_code/src/sevn/tools/registry.py`, `source_code/src/sevn/tools/decorator.py`
- File operations: `source_code/src/sevn/tools/file_ops/` (read, list_dir, glob, search, edit, write, …)
- Transcript reader (always available): `source_code/src/sevn/tools/transcript.py`
- Outbound (send_file, message, tts): `source_code/src/sevn/tools/outbound.py`
- Path resolution + `source_code/` prefix: `source_code/src/sevn/tools/paths.py`
- Skills bundled with the package: `source_code/src/sevn/data/bundled_skills/core/`

### Configuration

- Pydantic schema: `source_code/src/sevn/config/workspace_config.py`
- Defaults / constants: `source_code/src/sevn/config/defaults.py`
- Workspace loader: `source_code/src/sevn/config/loader.py`
- `my_sevn` (repo path): `source_code/src/sevn/config/my_sevn.py`, `source_code/src/sevn/config/sevn_repo.py`

### Memory and context

- SQLite memory store: `source_code/src/sevn/tools/memory_tools.py`
- Daily memory logs + dreaming: `source_code/src/sevn/memory/`
- LCM (long-term context manager): `source_code/src/sevn/lcm/`
- Workspace personality (SOUL/IDENTITY/USER/MEMORY load): `source_code/src/sevn/gateway/triage_context.py`

### Code understanding

- Mycode scan + generate: `source_code/src/sevn/code_understanding/mycode_scan.py`,
  `source_code/src/sevn/code_understanding/mycode_generate.py`
- Code index (this folder's `CODE_INDEX.md`): `source_code/src/sevn/code_understanding/code_index.py`
- Source mirror at boot: `source_code/src/sevn/workspace/source_copy.py`
- Graphify CLI integration: `source_code/src/sevn/code_understanding/graphify.py`

### Observability

- Structured DEBUG event helper: `source_code/src/sevn/logging/structured.py`
- Service log setup: `source_code/src/sevn/logging/setup.py`
- Tracing sinks: `source_code/src/sevn/agent/tracing/`

### Sub-agents (L1/L2)

- Operator docs: [`sub-agents.html`](sub-agents.html) (architecture chart and limits reference)
- Registry + supervisor: `source_code/src/sevn/agent/subagents/registry.py`, `source_code/src/sevn/agent/subagents/supervisor.py`
- Gateway wiring: `source_code/src/sevn/gateway/agent_turn.py`, `source_code/src/sevn/gateway/queue_multi.py`
- Spawn tool: `source_code/src/sevn/tools/subagent_spawn.py`
- Config subtree: `source_code/src/sevn/config/sections/subagents.py`
- Deterministic topology chart: `about-sevn.bot/_sources/subagents-topology.json` → `make subagents-chart`
