# sevn.bot — code & docs index (workspace copy)

This file lives in your **workspace** and indexes the **sevn.bot source mirror** at `source_code/`. The full repo is mirrored read-only into `source_code/` and refreshed on every gateway restart — read it with normal workspace-relative paths (no special prefix).

**Two path forms, no others:** workspace/user files (this `sevn.bot.md`, `IDENTITY.md`, `MEMORY.md`, `sessions/`, …) are **bare paths** at the workspace root — never prefix them with `workspace/` (no such directory). The sevn.bot source mirror is under **`source_code/`**. There is no `@repo/` prefix — it does not resolve.

## GitHub repository (never `git remote`)

The operator GitHub repo is already in `sevn.json` as **`my_sevn.repo_url`** (default `https://github.com/sevn-bot/sevn` → slug **`sevn-bot/sevn`**). Pass that slug to `gh-issues` / `gh` as `--repo`. **Never** run `git remote` (or any git) against `source_code/` — it is a read-only mirror, not a git checkout.

## Before you search

1. Confirm the mirror exists: `read` `source_code/src/sevn/gateway/agent_turn.py` (git clone) **or** `source_code/sevn/gateway/agent_turn.py` (installed package). If `source_code/` is empty, ask the operator to set `my_sevn.repo_path` in `sevn.json` to the absolute git root and restart the gateway.
2. Use **`glob`**, **`list_dir`**, **`search_in_file`**, and **`read`** with `source_code/...` paths.

## Mirror — top-level folders

When `my_sevn.repo_path` points at the git tree, `source_code/` typically contains:

| Folder | What it is |
|--------|------------|
| `source_code/src/sevn/` | **Python package** — gateway, agents, tools, channels, config |
| `source_code/about-sevn.bot/` | **Agent orientation docs** — start at `source_code/about-sevn.bot/ARCHITECTURE.md` |
| `source_code/evolution/` | Evolution pillar index — `source_code/evolution/ARCHITECTURE.md` |
| `source_code/.index/graphify/` | Generated architecture graph (`GRAPH_REPORT.md`, `graph.json`) |
| `source_code/skills/` | Repo-bundled skill sources (copied into workspace `skills/core/` at seed) |
| `source_code/tests/` | Pytest suite |
| `source_code/docs/` | Operator runbooks |

The git-ignored internal design-doc trees are **not** mirrored (ask the operator if you need them).

**List the mirror root:** `list_dir` with path `source_code` or `glob` pattern `source_code/*` / `source_code/**/*`.

## Installed gateway (site-packages)

When only the running package is available (no git tree), paths look like `source_code/sevn/gateway/`, `source_code/sevn/agent/`, `source_code/sevn/tools/`. Use `glob` `source_code/**/agent_turn.py` to discover the layout.

## Python package map (`source_code/src/sevn/...`)

| Area | Path (git clone) | Role |
|------|------------------|------|
| Gateway | `source_code/src/sevn/gateway/` | HTTP server, Telegram/webchat routing, menus, agent turns |
| Triager | `source_code/src/sevn/agent/triager/` | Intent/complexity routing JSON |
| Tier B executor | `source_code/src/sevn/agent/executors/b_harness.py` | Tool-loop executor |
| Tools | `source_code/src/sevn/tools/` | `read`, `glob`, `search_in_file`, `list_dir`, registry |
| Channels | `source_code/src/sevn/channels/` | Telegram, webchat adapters |
| Config | `source_code/src/sevn/config/` | `sevn.json` schema, workspace models |
| Code understanding | `source_code/src/sevn/code_understanding/` | Graphify, orientation, MYCODE bootstrap |

**Gateway entry files (read these first):**

- `source_code/src/sevn/gateway/agent_turn.py` — message → triage → tier B/C
- `source_code/src/sevn/gateway/channel_router.py` — inbound/outbound per channel
- `source_code/src/sevn/gateway/menu/menu.py` — `/config` Telegram UI

(Use `source_code/sevn/gateway/...` instead when `src/sevn` is absent.)

## Runtime roles (who calls the LLM)

Inbound order for a normal chat message:

1. **LLM Guard scanner** — classifies inbound text (and can scan tool output / feedback); may block before any reply.
2. **Triager** — picks intent + tier **A** (reply in Triager only) or **B** / **C** / **D** (spawn executor).
3. **Executor** — tier B/C/D does the substantive work (tools, plans, long answers).

These are **model passes inside the gateway process**, not separate OS processes — except **subagent sessions**, which are extra gateway sessions.

| Role | Tier / slot | What it does | Code |
|------|-------------|--------------|------|
| **LLM Guard scanner** | `security.scanner` | Inbound prompt-injection / policy scan; optional owner kill-switches on Telegram | `source_code/src/sevn/security/llm_guard_scanner.py`, wired from `source_code/src/sevn/gateway/channel_router.py` |
| **Triager (tier A)** | `providers.tier_default.triager` | Short greetings and tier-A-only replies; routes harder work to B/C/D | `source_code/src/sevn/agent/triager/` |
| **Tier B executor** | `providers.tier_default.B` | Tool-loop agent (`load_tool`, skills); most operator tasks | `source_code/src/sevn/agent/executors/b_harness.py` |
| **Tier C executor** | `providers.tier_default.C` | Plan / decompose harness (DSPy or λ-RLM when enabled) | `source_code/src/sevn/agent/executors/cd_harness.py` |
| **Tier D executor** | `providers.tier_default.D` | Heavier C/D path (same harness, higher tier config) | same `cd_harness.py` |
| **C/D sub-LM** | `C.sub_lm` / `D.sub_lm` | Smaller model calls inside C/D planning loops | `cd_harness.py` + `source_code/src/sevn/config/model_resolution.py` (`ModelSlot`) |
| **C/D λ-leaf** | `C.lambda_leaf` / `D.lambda_leaf` | Optional λ-RLM leaf model when `executors.tier_cd.lambda_rlm.enabled` | `cd_harness.py`, `source_code/src/sevn/agent/runtimes/` |
| **LCM summary** | `lcm.summary_model` | Compaction summaries for cross-session context | `source_code/src/sevn/lcm/` |
| **Pre-compaction flush** | `memory.pre_compaction_flush` | Flush before LCM compaction | `source_code/src/sevn/gateway/` + memory config |
| **Dreaming ranker** | `memory.dreaming.scoring` | Background consolidation into `MEMORY.md` | `source_code/src/sevn/memory/` (dreaming jobs) |
| **Honcho extractor** | `memory.user_model.extractor_model` | Inferred operator profile → `USER.md` | `source_code/src/sevn/memory/user_model/` |
| **Manual guard tool** | tier B tool `llm_guard_scan` | Agent-initiated rescan of suspect text | `source_code/src/sevn/tools/llm_guard_tool.py` |
| **Subagent sessions** | tier B in child session | `sessions_management` spawn/send | `source_code/src/sevn/skills/` + gateway sessions |

**Evolution playbooks** (markdown under `source_code/evolution/agents/` or `source_code/about-sevn.bot/agents/`) are **documentation for pipelines**, not live gateway agents: `explore_codebase.md`, `bug_fix.md`, `feature_spec.md`.

**Config:** model per slot lives in `sevn.json` under `providers.tier_default`, `lcm`, `memory.*`, and `security.scanner` — see `source_code/src/sevn/config/model_resolution.py` (`ModelSlot` enum).

## about-sevn.bot (under the mirror)

- `source_code/about-sevn.bot/ARCHITECTURE.md` — doc tree index
- `source_code/about-sevn.bot/_standards/` — help-site authoring rules
- `source_code/about-sevn.bot/agents/` — evolution playbooks (when present)

**Discover:** `list_dir` `source_code/about-sevn.bot` or `glob` `source_code/about-sevn.bot/**/*`.

## Search cheatsheet

| Goal | Tool | Example |
|------|------|---------|
| List the mirror root | `list_dir` | path `source_code` |
| List gateway package | `list_dir` | `source_code/src/sevn/gateway` |
| Find files by name | `find_file` | name `agent_turn`, path `source_code` |
| Find by glob | `glob` | pattern `**/triager/*.py`, path `source_code` |
| Search text in tree | `search_in_file` | pattern `class Triager`, path `source_code/src/sevn` |
| Read one file | `read` | `source_code/about-sevn.bot/ARCHITECTURE.md` |

## Workspace vs mirror

| Location | Contents |
|----------|----------|
| Workspace root (`sevn.json` here) | `AGENTS.md`, `USER.md`, `memory/`, `skills/`, operator data |
| `source_code/` | sevn.bot Python source + `about-sevn.bot/` (read-only, refreshed each restart) |

See **`AGENTS.md`** for operating rules and **`TOOLS.md`** for environment notes.

## Git commits

When committing in this repo, use [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/). Read `source_code/src/sevn/data/standards/conventional-commits.md` or load skill **`conventional_commit`**. Validate with `make commit-msg-check MSG='feat(scope): summary'` from the repo root.
