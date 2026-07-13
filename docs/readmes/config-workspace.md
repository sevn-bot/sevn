<!-- generated: do not edit by hand; run `sevn readme update config-workspace` -->
# Config & workspace — sevn

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** sevn.json schema, workspace layout, defaults, and layout validation.

## Level 1 — Overview (non-technical)

**Config & workspace** is a core part of sevn.bot — the personal AI assistant you run on your own machine. sevn.json schema, workspace layout, defaults, and layout validation.

In everyday use, config & workspace helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation spans `infra/`, `src/sevn/config/`, `src/sevn/workspace/`. The package contains 44 Python module(s); primary entry points include `src/sevn/config/__init__.py`, `src/sevn/config/defaults.py`, `src/sevn/config/errors.py`, `src/sevn/config/field_help.py`, `src/sevn/config/llm_params.py`, `src/sevn/config/loader.py`, and 38 more.

### Data and control flow

Config & workspace is a supporting subsystem; see Level 3 for the module-level flow.

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/02-config-and-workspace.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/config/field_help.py` — `load_config_field_help`, `field_help_for`, `urls_in_help_text`
- `src/sevn/config/llm_params.py` — `SamplingParams.as_request_kwargs`, `ReasoningParams.as_thinking_request`, `builtin_llm_params_doc`, `validate_llm_params_doc`
- `src/sevn/config/loader.py` — `find_sevn_json`, `operator_home_dir`, `bound_sevn_json_path`, `resolve_sevn_json_path`
- `src/sevn/config/model_resolution.py` — `use_main_model_for_all`, `resolve_main_model_id`, `resolve_model_slot`, `is_minimax_catalog_model`
- `src/sevn/config/my_sevn.py` — `persist_my_sevn_repo_path`, `resolve_my_sevn_repo_path`, `effective_my_sevn_sync`, `effective_my_sevn_executors`

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
