<!-- generated: do not edit by hand; run `sevn readme update config-workspace` -->
# Config & workspace — sevn

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** sevn.json schema, workspace layout, defaults, and layout validation.

## Level 1 — Overview (non-technical)

**Config & workspace** is a core part of sevn.bot — the personal AI assistant you run on your own machine. sevn.json schema, workspace layout, defaults, and layout validation.

In everyday use, config & workspace helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Provide a single, testable configuration surface before storage, tracing, proxy, and gateway work: locate sevn.json, validate schema_version and structured subtrees needed by early boot, resolve the c

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/config/`. The package contains 44 Python module(s); primary entry points include `src/sevn/config/__init__.py`, `src/sevn/config/defaults.py`, `src/sevn/config/errors.py`, `src/sevn/config/field_help.py`, and 2 more.

### Data and control flow

Config & workspace sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/02-config-and-workspace.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/config/field_help.py` — `load_config_field_help`, `field_help_for`, `urls_in_help_text`
- `src/sevn/config/llm_params.py` — `SamplingParams.as_request_kwargs`, `ReasoningParams.as_thinking_request`, `builtin_llm_params_doc`, `validate_llm_params_doc`
- `src/sevn/config/loader.py` — `find_sevn_json`, `operator_home_dir`, `bound_sevn_json_path`, `resolve_sevn_json_path`
- `src/sevn/config/model_resolution.py` — `use_main_model_for_all`, `resolve_main_model_id`, `resolve_model_slot`, `is_minimax_catalog_model`
- `src/sevn/config/my_sevn.py` — `persist_my_sevn_repo_path`, `resolve_my_sevn_repo_path`, `effective_my_sevn_sync`, `effective_my_sevn_executors`

### Spec context

From specs/02-config-and-workspace.md:
Provide a single, testable configuration surface before storage, tracing, proxy, and gateway work: locate sevn.json, validate schema_version and structured subtrees needed by early boot, resolve the c

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/config/` (44 Python files). Normative design: `specs/02-config-and-workspace.md`.

### Module inventory

- `src/sevn/config/__init__.py` — """Configuration subpackage: workspace file, defaults, process env.
- `src/sevn/config/defaults.py` — """Non-workspace tunables ('Final' constants).
- `src/sevn/config/errors.py` — """Configuration loading errors.
- `src/sevn/config/field_help.py` — """Packaged sevn.json field help (long descriptions and collection hints).
- `src/sevn/config/llm_params.py` — """Per-agent LLM call config ('LLM_params_config.json').
- `src/sevn/config/loader.py` — """Discover and load ''sevn.json'' into typed config + layout.
- `src/sevn/config/model_resolution.py` — """Resolve model ids per logical slot from workspace config.
- `src/sevn/config/my_sevn.py` — """''my_sevn'' config helpers ('specs/35-bot-evolution.md').
- `src/sevn/config/provider_credential_validate.py` — """Validate provider credential coverage for assigned model slots (D7).
- `src/sevn/config/provider_registry.py` — """Resolve provider bindings and credentials from workspace config.
- `src/sevn/config/provider_secrets.py` — """Canonical provider secret aliases and config binding helpers (D2/D6).
- `src/sevn/config/sections/__init__.py` — """Domain modules for ''sevn.json'' Pydantic section models.
- … and 32 more Python modules

### Field Help (`src/sevn/config/field_help.py`)

Public entry points:
- `load_config_field_help` — see `src/sevn/config/field_help.py`
- `field_help_for` — see `src/sevn/config/field_help.py`
- `urls_in_help_text` — see `src/sevn/config/field_help.py`

### Llm Params (`src/sevn/config/llm_params.py`)

Public entry points:
- `SamplingParams.as_request_kwargs` — see `src/sevn/config/llm_params.py`
- `ReasoningParams.as_thinking_request` — see `src/sevn/config/llm_params.py`
- `builtin_llm_params_doc` — see `src/sevn/config/llm_params.py`
- `validate_llm_params_doc` — see `src/sevn/config/llm_params.py`
- `load_or_create_llm_params_doc` — see `src/sevn/config/llm_params.py`
- `write_llm_params_doc` — see `src/sevn/config/llm_params.py`
- `set_agent_model_max_output_tokens` — see `src/sevn/config/llm_params.py`
- `resolve_llm_params` — see `src/sevn/config/llm_params.py`

### Loader (`src/sevn/config/loader.py`)

Public entry points:
- `find_sevn_json` — see `src/sevn/config/loader.py`
- `operator_home_dir` — see `src/sevn/config/loader.py`
- `bound_sevn_json_path` — see `src/sevn/config/loader.py`
- `resolve_sevn_json_path` — see `src/sevn/config/loader.py`
- `ensure_schema_supported` — see `src/sevn/config/loader.py`
- `load_workspace` — see `src/sevn/config/loader.py`

### Model Resolution (`src/sevn/config/model_resolution.py`)

Public entry points:
- `use_main_model_for_all` — see `src/sevn/config/model_resolution.py`
- `resolve_main_model_id` — see `src/sevn/config/model_resolution.py`
- `resolve_model_slot` — see `src/sevn/config/model_resolution.py`
- `is_minimax_catalog_model` — see `src/sevn/config/model_resolution.py`
- `is_minimax_model` — see `src/sevn/config/model_resolution.py`
- `resolve_wire_model_id` — see `src/sevn/config/model_resolution.py`
- `resolve_minimax_anthropic_base_url` — see `src/sevn/config/model_resolution.py`
- `resolve_minimax_openai_base_url` — see `src/sevn/config/model_resolution.py`

### My Sevn (`src/sevn/config/my_sevn.py`)

Public entry points:
- `persist_my_sevn_repo_path` — see `src/sevn/config/my_sevn.py`
- `resolve_my_sevn_repo_path` — see `src/sevn/config/my_sevn.py`
- `effective_my_sevn_sync` — see `src/sevn/config/my_sevn.py`
- `effective_my_sevn_executors` — see `src/sevn/config/my_sevn.py`
- `effective_my_sevn_issues` — see `src/sevn/config/my_sevn.py`
- `effective_my_sevn_pipelines` — see `src/sevn/config/my_sevn.py`
- `effective_my_sevn` — see `src/sevn/config/my_sevn.py`

### Provider Credential Validate (`src/sevn/config/provider_credential_validate.py`)

Public entry points:
- `provider_credential_resolvable` — see `src/sevn/config/provider_credential_validate.py`
- `declared_provider_names` — see `src/sevn/config/provider_credential_validate.py`
- `collect_missing_provider_credentials` — see `src/sevn/config/provider_credential_validate.py`
- `collect_unused_declared_providers` — see `src/sevn/config/provider_credential_validate.py`
- `validate_provider_credentials` — see `src/sevn/config/provider_credential_validate.py`
- `format_unused_provider_warning` — see `src/sevn/config/provider_credential_validate.py`

### Provider Registry (`src/sevn/config/provider_registry.py`)

Public entry points:
- `resolve_provider_for_model_id` — see `src/sevn/config/provider_registry.py`
- `resolve_provider_binding` — see `src/sevn/config/provider_registry.py`
- `provider_credential_ref` — see `src/sevn/config/provider_registry.py`

### Additional modules

32 more Python files under `src/sevn/config/` — including `src/sevn/config/sections/accessors.py`, `src/sevn/config/sections/agent.py`, `src/sevn/config/sections/channels.py`, `src/sevn/config/sections/coding_agents.py`.

### Extension and invariants

Follow `specs/02-config-and-workspace.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/config/`, run `sevn readme update config-workspace` and `make readme-check`.

## References

- [specs/02-config-and-workspace.md](specs/02-config-and-workspace.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/02-config-and-workspace.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/config/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
