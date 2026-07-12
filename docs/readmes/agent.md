<!-- generated: do not edit by hand; run `sevn readme update agent` -->
# Agent runtime — Triager, tier-B/C executors, harness discipline, sandboxes, and turn orchestration

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Triager, tier-B/C executors, harness discipline, sandboxes, and turn orchestration.

## Level 1 — Overview (non-technical)

**Agent runtime** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Triager, tier-B/C executors, harness discipline, sandboxes, and turn orchestration.

In everyday use, agent runtime helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

The Triager is the routing brain (prd-04-getting-things-done §5.1–§5.2): a single, tool-less outbound generation step that emits validated TriageResult consumed by tier dispatch (A / B / C / D), MCP e

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/agent/`. The package contains 90 Python module(s); primary entry points include `src/sevn/agent/__init__.py`, `src/sevn/agent/adapters/__init__.py`, `src/sevn/agent/adapters/_monty_limits.py`, `src/sevn/agent/adapters/dspy_adapter.py`, and 2 more.

### Data and control flow

Agent runtime sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/13-rlm-triager.md`, `specs/14-executor-tier-b.md`, `specs/21-executor-tier-cd.md`, `specs/16-harness-discipline.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/agent/adapters/_monty_limits.py` — `default_codemode_limits`, `install_monty_resource_limits`
- `src/sevn/agent/adapters/dspy_adapter.py` — `to_dspy_tools`, `lambda_rlm_filter`
- `src/sevn/agent/adapters/egress_bridge.py` — `resolve_proxy_shared_secret`, `redact_llm_request_snapshot`, `redact_proxy_transport_request`, `redact_httpx_request_snapshot`
- `src/sevn/agent/adapters/minimax_wrapper_model.py` — `MiniMaxWrapperModel.request`, `MiniMaxWrapperModel.request_stream`, `MiniMaxWrapperModel.prepare_request`, `wrap_minimax_native_model`
- `src/sevn/agent/adapters/native_model.py` — `build_native_model_settings`, `resolve_pydantic_model`, `resolve_pydantic_model_for_slot`, `default_native_model_context`

### Spec context

From specs/13-rlm-triager.md:
The Triager is the routing brain (prd-04-getting-things-done §5.1–§5.2): a single, tool-less outbound generation step that emits validated TriageResult consumed by tier dispatch (A / B / C / D), MCP e

From specs/14-executor-tier-b.md:
Tier B is the default “do work” executor for messages the Triager classifies as complexity == B (prd-04-getting-things-done §5.2): a single pydantic-ai Agent loop over the user’s incoming_text, with t

From specs/21-executor-tier-cd.md:
Tier C/D is the planned-work executor for messages the Triager classifies as complexity == C or complexity == D (prd-04-getting-things-done §5.3–§5.4): structured planning, optional owner approval (Pl

From specs/16-harness-discipline.md:
45# Harness discipline — Spec

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/agent/` (90 Python files). Normative design: `specs/13-rlm-triager.md`, `specs/14-executor-tier-b.md`, `specs/21-executor-tier-cd.md`, `specs/16-harness-discipline.md`.

### Module inventory

- `src/sevn/agent/__init__.py` — """Agent runtime and orchestration (scaffold).
- `src/sevn/agent/adapters/__init__.py` — """Framework adapter entrypoints bridging ''ToolSet'' + ''ToolExecutor''.
- `src/sevn/agent/adapters/_monty_limits.py` — """Inject Monty ''ResourceLimits'' into CodeMode's sandbox REPL.
- `src/sevn/agent/adapters/dspy_adapter.py` — """DSPy + λ-RLM adapter scaffolding ('specs/11-tools-registry.md' §2.6).
- `src/sevn/agent/adapters/egress_bridge.py` — """httpx egress bridge for native pydantic-ai models via the sevn proxy (W2).
- `src/sevn/agent/adapters/minimax_wrapper_model.py` — """MiniMax native-model wrappers: Anthropic XML recovery + OpenAI settings hygiene.
- `src/sevn/agent/adapters/native_model.py` — """Native pydantic-ai model factory behind per-slot flags (W3).
- `src/sevn/agent/adapters/pydantic_adapter.py` — """Pydantic AI adapter surfaces (tier B scaffolding) ('specs/11-tools-registry.md' §2.6).
- `src/sevn/agent/adapters/tier_b_capabilities.py` — """Provider-adaptive WebSearch/WebFetch + Thinking for tier B (W7).
- `src/sevn/agent/adapters/tier_b_codemode.py` — """Tier-B CodeMode helpers ('specs/14-executor-tier-b.md' W8; D8/D9).
- `src/sevn/agent/adapters/tier_b_hooks.py` — """Tier-B pydantic-ai lifecycle hooks ('specs/14-executor-tier-b.md'; W5).
- `src/sevn/agent/adapters/tier_b_model.py` — """OpenAI Chat Completions bridge for tier-B ''FunctionModel'' ('specs/14-executor-tier-b.md' §2.3).
- … and 78 more Python modules

###  Monty Limits (`src/sevn/agent/adapters/_monty_limits.py`)

Public entry points:
- `default_codemode_limits` — see `src/sevn/agent/adapters/_monty_limits.py`
- `install_monty_resource_limits` — see `src/sevn/agent/adapters/_monty_limits.py`

### Dspy Adapter (`src/sevn/agent/adapters/dspy_adapter.py`)

Public entry points:
- `to_dspy_tools` — see `src/sevn/agent/adapters/dspy_adapter.py`
- `lambda_rlm_filter` — see `src/sevn/agent/adapters/dspy_adapter.py`

### Egress Bridge (`src/sevn/agent/adapters/egress_bridge.py`)

Public entry points:
- `resolve_proxy_shared_secret` — see `src/sevn/agent/adapters/egress_bridge.py`
- `redact_llm_request_snapshot` — see `src/sevn/agent/adapters/egress_bridge.py`
- `redact_proxy_transport_request` — see `src/sevn/agent/adapters/egress_bridge.py`
- `redact_httpx_request_snapshot` — see `src/sevn/agent/adapters/egress_bridge.py`
- `build_sevn_httpx_event_hooks` — see `src/sevn/agent/adapters/egress_bridge.py`
- `build_sevn_anthropic_client` — see `src/sevn/agent/adapters/egress_bridge.py`
- `build_sevn_openai_client` — see `src/sevn/agent/adapters/egress_bridge.py`

### Minimax Wrapper Model (`src/sevn/agent/adapters/minimax_wrapper_model.py`)

Public entry points:
- `MiniMaxWrapperModel.request` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `MiniMaxWrapperModel.request_stream` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `MiniMaxWrapperModel.prepare_request` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `wrap_minimax_native_model` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `MiniMaxOpenAIWrapperModel.request` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `MiniMaxOpenAIWrapperModel.request_stream` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `MiniMaxOpenAIWrapperModel.prepare_request` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`
- `wrap_minimax_openai_native_model` — see `src/sevn/agent/adapters/minimax_wrapper_model.py`

### Native Model (`src/sevn/agent/adapters/native_model.py`)

Public entry points:
- `build_native_model_settings` — see `src/sevn/agent/adapters/native_model.py`
- `resolve_pydantic_model` — see `src/sevn/agent/adapters/native_model.py`
- `resolve_pydantic_model_for_slot` — see `src/sevn/agent/adapters/native_model.py`
- `default_native_model_context` — see `src/sevn/agent/adapters/native_model.py`

### Pydantic Adapter (`src/sevn/agent/adapters/pydantic_adapter.py`)

Public entry points:
- `register_pydantic_tools` — see `src/sevn/agent/adapters/pydantic_adapter.py`

### Tier B Capabilities (`src/sevn/agent/adapters/tier_b_capabilities.py`)

Public entry points:
- `resolve_web_egress_domain_policy` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `provider_supports_native_web_search` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `provider_supports_native_web_fetch` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `url_passes_domain_policy` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `build_serp_local_tool` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `make_codemode_web_registry_tool` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `build_get_page_content_local_tool` — see `src/sevn/agent/adapters/tier_b_capabilities.py`
- `resolve_thinking_effort` — see `src/sevn/agent/adapters/tier_b_capabilities.py`

### Tier B Codemode (`src/sevn/agent/adapters/tier_b_codemode.py`)

Public entry points:
- `is_codemode_eligible_tool` — see `src/sevn/agent/adapters/tier_b_codemode.py`
- `compute_codemode_eligible_names` — see `src/sevn/agent/adapters/tier_b_codemode.py`
- `build_codemode_capability` — see `src/sevn/agent/adapters/tier_b_codemode.py`

### Additional modules

78 more Python files under `src/sevn/agent/` — including `src/sevn/agent/adapters/tier_b_multimodal.py`, `src/sevn/agent/adapters/tier_b_overflow.py`, `src/sevn/agent/adapters/tier_b_skill_capabilities.py`, `src/sevn/agent/adapters/tier_b_tools.py`.

### Extension and invariants

Follow `specs/13-rlm-triager.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/agent/`, run `sevn readme update agent` and `make readme-check`.

## References

- [specs/13-rlm-triager.md](specs/13-rlm-triager.md)
- [specs/14-executor-tier-b.md](specs/14-executor-tier-b.md)
- [specs/21-executor-tier-cd.md](specs/21-executor-tier-cd.md)
- [specs/16-harness-discipline.md](specs/16-harness-discipline.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/13-rlm-triager.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/agent/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
