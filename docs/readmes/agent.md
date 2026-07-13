<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint agent` -->
# Agent runtime — Triager, tier-B/C executors, harness discipline, sandboxes, and turn orchestration

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Triager, tier-B/C executors, harness discipline, sandboxes, and turn orchestration.

## Level 1 — Overview (non-technical)

**Agent runtime** is where your message becomes action. A lightweight **triager** model reads each turn and decides intent (greeting, code question, tool task) and **complexity tier** (A–D). Simple replies stay on tier A; everyday tool use runs on tier B; multi-step planning and delegation use tiers C and D. Executors run inside **harness discipline** rules — bounded tool loops, sandboxed subprocesses, and traces you can inspect in Mission Control.

You do not pick the tier manually; the triager and routing policy choose it per turn.

## Level 2 — How it works (technical)

Implementation lives under `src/sevn/agent/`. The gateway calls into this package through `build_agent_run_turn` (`gateway/agent_turn.py`).

### Triage (`src/sevn/agent/triager/`)

`triage_turn` (`triager/run.py`) returns a structured `TriageResult`: `Intent`, `ComplexityTier` (A–D), optional first-message ack, tool/skill shortlists, and confidence. Routing policy modules enforce repo-code detection, orientation blocks, and footer injection.

### Executor tiers

| Tier | Role | Entry point | Typical use |
| --- | --- | --- | --- |
| **A** | Triager-only | Handled in `agent_turn` after `triage_turn` | Greetings, simple Q&A with no tools |
| **B** | Harnessed tool executor | `run_b_turn` (`executors/b_harness.py`) | Default workhorse: skills, CodeMode, web tools |
| **C** | Planner + outer loop | `run_cd_turn` (`executors/cd_harness.py`) | Multi-step plans, tool orchestration |
| **D** | Deep delegation | Same `run_cd_turn` path with higher budgets | Long-horizon tasks, λ-RLM-style macros |

Tier B uses pydantic-ai adapters (`adapters/tier_b_*.py`), optional CodeMode (`tier_b_codemode.py`), and routes LLM calls through the egress proxy (`adapters/egress_bridge.py`) — keys stay out of the gateway process.

### Harness discipline and sandbox

[`about-sevn.bot/specs/16-harness-discipline.md`](../../about-sevn.bot/specs/16-harness-discipline.md) governs boot sweeps, tool permissions, and workspace write gates. Risky tool runs may enter a sandbox namespace (`security/sandbox_runtime.py`) with optional egress firewall rules (`security/egress_firewall.py`).

### Configuration

Model slots resolve from `sevn.json` → `providers.tier_default.*` and per-agent overrides. `sevn config validate` checks schema and credential coverage; `load_or_create_llm_params_doc` manages per-agent sampling caps.

### Honest status (selected paths)

| Path | Status | Where |
| --- | --- | --- |
| Triager structured output + routing | **live** | `triager/run.py`, `routing_policy.py` |
| Tier B harness + CodeMode | **live** | `executors/b_harness.py`, `adapters/tier_b_codemode.py` |
| Tier C/D plan harness | **live** | `executors/cd_harness.py`, `plan_gate_store.py` |
| λ-RLM combinator execute | **stub** | `executors/lambda_rlm_runtime.py` — name intersection only, no full REPL |
| Native pydantic-ai models (per-slot flags) | **partial** | `adapters/native_model.py` — gated by config |
| DSPy adapter scaffolding | **partial** | `adapters/dspy_adapter.py` — not production path |

### Key modules

- `src/sevn/agent/triager/run.py` — `triage_turn`
- `src/sevn/agent/executors/b_harness.py` — `run_b_turn`
- `src/sevn/agent/executors/cd_harness.py` — `run_cd_turn`
- `src/sevn/agent/adapters/egress_bridge.py` — proxy transport for native models
- `src/sevn/agent/adapters/tier_b_codemode.py` — CodeMode capability for tier B

Normative specs: [`13-rlm-triager`](../../about-sevn.bot/specs/13-rlm-triager.md), [`14-executor-tier-b`](../../about-sevn.bot/specs/14-executor-tier-b.md), [`21-executor-tier-cd`](../../about-sevn.bot/specs/21-executor-tier-cd.md), [`16-harness-discipline`](../../about-sevn.bot/specs/16-harness-discipline.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/agent/` (90 Python files). Normative design: `about-sevn.bot/specs/13-rlm-triager.md`, `about-sevn.bot/specs/14-executor-tier-b.md`, `about-sevn.bot/specs/21-executor-tier-cd.md`, `about-sevn.bot/specs/16-harness-discipline.md`.

### Module inventory

- `src/sevn/agent/__init__.py` — Agent runtime and orchestration (scaffold).
- `src/sevn/agent/adapters/__init__.py` — Framework adapter entrypoints bridging ''ToolSet'' + ''ToolExecutor''.
- `src/sevn/agent/adapters/_monty_limits.py` — Inject Monty ''ResourceLimits'' into CodeMode's sandbox REPL.
- `src/sevn/agent/adapters/dspy_adapter.py` — DSPy + λ-RLM adapter scaffolding ('about-sevn.bot/specs/11-tools-registry.md' §2.6).
- `src/sevn/agent/adapters/egress_bridge.py` — httpx egress bridge for native pydantic-ai models via the sevn proxy (W2).
- `src/sevn/agent/adapters/minimax_wrapper_model.py` — MiniMax native-model wrappers: Anthropic XML recovery + OpenAI settings hygiene.
- `src/sevn/agent/adapters/native_model.py` — Native pydantic-ai model factory behind per-slot flags (W3).
- `src/sevn/agent/adapters/pydantic_adapter.py` — Pydantic AI adapter surfaces (tier B scaffolding) ('about-sevn.bot/specs/11-tools-registry.md' §2.6).
- `src/sevn/agent/adapters/tier_b_capabilities.py` — Provider-adaptive WebSearch/WebFetch + Thinking for tier B (W7).
- `src/sevn/agent/adapters/tier_b_codemode.py` — Tier-B CodeMode helpers ('about-sevn.bot/specs/14-executor-tier-b.md' W8; D8/D9).
- `src/sevn/agent/adapters/tier_b_hooks.py` — Tier-B pydantic-ai lifecycle hooks ('about-sevn.bot/specs/14-executor-tier-b.md'; W5).
- `src/sevn/agent/adapters/tier_b_model.py` — OpenAI Chat Completions bridge for tier-B ''FunctionModel'' ('about-sevn.bot/specs/14-executor-tier-b.md' §2.3).
- … and 78 more Python modules

### Package init (`src/sevn/agent/__init__.py`)

See `src/sevn/agent/__init__.py` for implementation details.

### Package init (`src/sevn/agent/adapters/__init__.py`)

See `src/sevn/agent/adapters/__init__.py` for implementation details.

###  Monty Limits (`src/sevn/agent/adapters/_monty_limits.py`)

Public entry points:
- `default_codemode_limits`
- `install_monty_resource_limits`

### Dspy Adapter (`src/sevn/agent/adapters/dspy_adapter.py`)

Public entry points:
- `to_dspy_tools`
- `lambda_rlm_filter`

### Egress Bridge (`src/sevn/agent/adapters/egress_bridge.py`)

Public entry points:
- `resolve_proxy_shared_secret`
- `redact_llm_request_snapshot`
- `redact_proxy_transport_request`
- `redact_httpx_request_snapshot`
- `build_sevn_httpx_event_hooks`
- `build_sevn_anthropic_client`
- `build_sevn_openai_client`

### Minimax Wrapper Model (`src/sevn/agent/adapters/minimax_wrapper_model.py`)

Public entry points:
- `MiniMaxWrapperModel.request`
- `MiniMaxWrapperModel.request_stream`
- `MiniMaxWrapperModel.prepare_request`
- `wrap_minimax_native_model`
- `MiniMaxOpenAIWrapperModel.request`
- `MiniMaxOpenAIWrapperModel.request_stream`
- `MiniMaxOpenAIWrapperModel.prepare_request`
- `wrap_minimax_openai_native_model`

### Native Model (`src/sevn/agent/adapters/native_model.py`)

Public entry points:
- `build_native_model_settings`
- `resolve_pydantic_model`
- `resolve_pydantic_model_for_slot`
- `default_native_model_context`

### Pydantic Adapter (`src/sevn/agent/adapters/pydantic_adapter.py`)

Public entry points:
- `register_pydantic_tools`

### Tier B Capabilities (`src/sevn/agent/adapters/tier_b_capabilities.py`)

Public entry points:
- `resolve_web_egress_domain_policy`
- `provider_supports_native_web_search`
- `provider_supports_native_web_fetch`
- `url_passes_domain_policy`
- `build_serp_local_tool`
- `make_codemode_web_registry_tool`
- `build_get_page_content_local_tool`
- `resolve_thinking_effort`

### Tier B Codemode (`src/sevn/agent/adapters/tier_b_codemode.py`)

Public entry points:
- `is_codemode_eligible_tool`
- `compute_codemode_eligible_names`
- `build_codemode_capability`

### Tier B Hooks (`src/sevn/agent/adapters/tier_b_hooks.py`)

See `src/sevn/agent/adapters/tier_b_hooks.py` for implementation details.

### Tier B Model (`src/sevn/agent/adapters/tier_b_model.py`)

See `src/sevn/agent/adapters/tier_b_model.py` for implementation details.

### Additional modules

78 more Python files under `src/sevn/agent/` — including `src/sevn/agent/adapters/tier_b_multimodal.py`, `src/sevn/agent/adapters/tier_b_overflow.py`, `src/sevn/agent/adapters/tier_b_skill_capabilities.py`, `src/sevn/agent/adapters/tier_b_tools.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/13-rlm-triager.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/agent/`, run `sevn readme update agent` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/13-rlm-triager.md](../../about-sevn.bot/specs/13-rlm-triager.md)
- [../../about-sevn.bot/specs/14-executor-tier-b.md](../../about-sevn.bot/specs/14-executor-tier-b.md)
- [../../about-sevn.bot/specs/21-executor-tier-cd.md](../../about-sevn.bot/specs/21-executor-tier-cd.md)
- [../../about-sevn.bot/specs/16-harness-discipline.md](../../about-sevn.bot/specs/16-harness-discipline.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/13-rlm-triager.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/agent/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
