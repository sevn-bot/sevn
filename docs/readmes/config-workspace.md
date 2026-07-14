<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint config-workspace` -->
# Config & workspace — sevn.json schema, workspace layout, defaults, and layout validation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** sevn.json schema, workspace layout, defaults, and layout validation.

## Level 1 — Overview (non-technical)

**Config & workspace** is how sevn.bot knows *your* install: where files live, which models and channels are enabled, and what the gateway may touch. Everything operator-facing rolls up to **`sevn.json`** at the workspace root (bound path: `~/.sevn/workspace/sevn.json` when using the default operator home). The workspace directory holds prompts, skills, memory files, and SQLite state under `.sevn/`.

Edit `sevn.json` through Mission Control, Telegram `/config`, the onboarding wizard, or by hand — then validate before restarting the gateway.

## Level 2 — How it works (technical)

Config spans [`src/sevn/config/`](../../src/sevn/config/), workspace layout in [`src/sevn/workspace/`](../../src/sevn/workspace/), and the JSON Schema at [`infra/sevn.schema.json`](../../infra/sevn.schema.json).

### Discover and load

| Step | Function | Behavior |
| --- | --- | --- |
| Bound path | [`bound_sevn_json_path`](../../src/sevn/config/loader.py#L89) | `{SEVN_HOME}/workspace/sevn.json` (default `~/.sevn`) |
| Walk-up fallback | [`find_sevn_json`](../../src/sevn/config/loader.py) | First `sevn.json` from cwd to filesystem root |
| Parse + layout | [`load_workspace`](../../src/sevn/config/loader.py#L161) ([`config/loader.py`](../../src/sevn/config/loader.py)) | JSON → `WorkspaceConfig` + [`WorkspaceLayout`](../../src/sevn/workspace/layout.py#L31) |

[`WorkspaceLayout.from_config`](../../src/sevn/workspace/layout.py#L38) resolves `content_root` from `workspace_root` relative to the config file path. Derived paths include `.sevn/` (SQLite, traces), `logs/`, `skills/`, `sessions/`, `memory/`.

### Subtree model

`sevn.json` is a single document validated against [`infra/sevn.schema.json`](../../infra/sevn.schema.json). Domain sections live as Pydantic models under [`src/sevn/config/sections/`](../../src/sevn/config/sections/) — e.g. [`gateway.py`](../../src/sevn/config/sections/gateway.py), [`channels.py`](../../src/sevn/config/sections/channels.py), [`agent.py`](../../src/sevn/config/sections/agent.py), [`security.py`](../../src/sevn/config/sections/security.py). CLI section helpers live in the [`cli/config_sections/`](../../src/sevn/cli/config_sections/) package ([`config_sections/__init__.py`](../../src/sevn/cli/config_sections/__init__.py)) and expose stable slugs for **`sevn config <slug>`** (for example `sevn config gateway`).

**Schema vs Pydantic gaps:** typed models may include subtrees not yet reflected in [`infra/sevn.schema.json`](../../infra/sevn.schema.json). Notably [`provisioning`](../../src/sevn/config/sections/provisioning.py) (host-dependency auto-install allowlist) and [`coding_agents`](../../src/sevn/config/sections/coding_agents.py) (Coding Agents hub) parse from raw JSON via Pydantic but have **no** top-level schema entries today — validate with `sevn config validate` for schema-covered keys and read the section modules for the full contract.

### Validation flow

**`sevn config validate`** ([`cli/commands/config_cmd.py`](../../src/sevn/cli/commands/config_cmd.py)):

1. [`load_bound_workspace`](../../src/sevn/cli/workspace.py) — requires operator home + bound `sevn.json`
2. [`validate_workspace_document`](../../src/sevn/onboarding/validate.py) — schema + cross-field rules
3. Advisory warnings — unused providers, OpenAI OAuth probe ([`onboarding/live_validate.py`](../../src/sevn/onboarding/live_validate.py))

Gateway boot also runs [`validate_workspace_layout`](../../src/sevn/workspace/layout_validate.py) against canonical dirs (`skills/`, `logs/`, `.sevn/`) and seed markdown files (`AGENTS.md`, `SOUL.md`, `USER.md`, …).

**`sevn config set <dotted.path> <value>`** writes a draft and promotes through the same validate → merge path as onboarding.

### Layout vs config

| Path under `content_root` | Purpose |
| --- | --- |
| `sevn.json` | Authoritative typed config |
| `.sevn/` | SQLite (`sevn.db`), traces, improve jobs, turn bundles |
| `skills/` | Bundled core (read-only) + operator `skills/user/` |
| `memory/`, `sessions/` | Lazy-created operator dirs |
| `AGENTS.md`, `USER.md`, … | Workspace persona + operator memory |

### Key modules

- [`loader.py`](../../src/sevn/config/loader.py) — [`load_workspace`](../../src/sevn/config/loader.py#L161), [`find_sevn_json`](../../src/sevn/config/loader.py)
- [`sections/`](../../src/sevn/config/sections/) — typed `sevn.json` subtrees
- [`layout.py`](../../src/sevn/workspace/layout.py) — [`WorkspaceLayout`](../../src/sevn/workspace/layout.py#L31) path resolver
- [`layout_validate.py`](../../src/sevn/workspace/layout_validate.py) — boot-time filesystem check
- [`promote.py`](../../src/sevn/onboarding/promote.py) — merge validated draft → live `sevn.json`

Normative spec: [`about-sevn.bot/specs/02-config-and-workspace.md`](../../about-sevn.bot/specs/02-config-and-workspace.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/` (44 Python files). Normative design: `about-sevn.bot/specs/02-config-and-workspace.md`.

### Module inventory

- `src/sevn/config/__init__.py` — Configuration subpackage: workspace file, defaults, process env.
- `src/sevn/config/defaults.py` — Non-workspace tunables ('Final' constants).
- `src/sevn/config/errors.py` — Configuration loading errors.
- `src/sevn/config/field_help.py` — Packaged sevn.json field help (long descriptions and collection hints).
- `src/sevn/config/llm_params.py` — Per-agent LLM call config ('LLM_params_config.json').
- `src/sevn/config/loader.py` — Discover and load ''sevn.json'' into typed config + layout.
- `src/sevn/config/model_resolution.py` — Resolve model ids per logical slot from workspace config.
- `src/sevn/config/my_sevn.py` — ''my_sevn'' config helpers ('about-sevn.bot/specs/35-bot-evolution.md').
- `src/sevn/config/provider_credential_validate.py` — Validate provider credential coverage for assigned model slots (D7).
- `src/sevn/config/provider_registry.py` — Resolve provider bindings and credentials from workspace config.
- `src/sevn/config/provider_secrets.py` — Canonical provider secret aliases and config binding helpers (D2/D6).
- `src/sevn/config/sections/__init__.py` — Domain modules for ''sevn.json'' Pydantic section models.
- … and 32 more Python modules

### Package init (`src/sevn/config/__init__.py`)

See `src/sevn/config/__init__.py` for implementation details.

### Defaults (`src/sevn/config/defaults.py`)

See `src/sevn/config/defaults.py` for implementation details.

### Errors (`src/sevn/config/errors.py`)

See `src/sevn/config/errors.py` for implementation details.

### Field Help (`src/sevn/config/field_help.py`)

Public entry points:
- `load_config_field_help`
- `field_help_for`
- `urls_in_help_text`

### Llm Params (`src/sevn/config/llm_params.py`)

Public entry points:
- `SamplingParams.as_request_kwargs`
- `ReasoningParams.as_thinking_request`
- `builtin_llm_params_doc`
- `validate_llm_params_doc`
- `load_or_create_llm_params_doc`
- `write_llm_params_doc`
- `set_agent_model_max_output_tokens`
- `resolve_llm_params`

### Loader (`src/sevn/config/loader.py`)

Public entry points:
- `find_sevn_json`
- `operator_home_dir`
- `bound_sevn_json_path`
- `resolve_sevn_json_path`
- `ensure_schema_supported`
- `load_workspace`

### Model Resolution (`src/sevn/config/model_resolution.py`)

Public entry points:
- `use_main_model_for_all`
- `resolve_main_model_id`
- `resolve_model_slot`
- `is_minimax_catalog_model`
- `is_minimax_model`
- `resolve_wire_model_id`
- `resolve_minimax_anthropic_base_url`
- `resolve_minimax_openai_base_url`

### My Sevn (`src/sevn/config/my_sevn.py`)

Public entry points:
- `persist_my_sevn_repo_path`
- `resolve_my_sevn_repo_path`
- `effective_my_sevn_sync`
- `effective_my_sevn_executors`
- `effective_my_sevn_issues`
- `effective_my_sevn_pipelines`
- `effective_my_sevn`

### Provider Credential Validate (`src/sevn/config/provider_credential_validate.py`)

Public entry points:
- `provider_credential_resolvable`
- `declared_provider_names`
- `collect_missing_provider_credentials`
- `collect_unused_declared_providers`
- `validate_provider_credentials`
- `format_unused_provider_warning`

### Provider Registry (`src/sevn/config/provider_registry.py`)

Public entry points:
- `resolve_provider_for_model_id`
- `resolve_provider_binding`
- `provider_credential_ref`

### Provider Secrets (`src/sevn/config/provider_secrets.py`)

See `src/sevn/config/provider_secrets.py` for implementation details.

### Package init (`src/sevn/config/sections/__init__.py`)

See `src/sevn/config/sections/__init__.py` for implementation details.

### Additional modules

32 more Python files under `src/sevn/` — including `src/sevn/config/sections/accessors.py`, `src/sevn/config/sections/agent.py`, `src/sevn/config/sections/channels.py`, `src/sevn/config/sections/coding_agents.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/02-config-and-workspace.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/`, run `sevn readme update config-workspace` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/02-config-and-workspace.md](../../about-sevn.bot/specs/02-config-and-workspace.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/02-config-and-workspace.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
