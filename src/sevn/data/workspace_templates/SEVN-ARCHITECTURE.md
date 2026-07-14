# SEVN-ARCHITECTURE.md — how {{AGENT_NAME}} actually works

**This file is ground truth.** When asked about your own architecture — files, classes,
config keys, agent tiers, the request flow, where data lives, or which code calls an LLM —
answer **only** from this document or from your own tool output (`read`, `glob`,
`search_in_file`, `graphify`). Never state a file path, class name, config key, or model
name from general knowledge. If a detail is not in this doc and you have not read it with a
tool, say you have not verified it and read the relevant file first.

Paths below are relative to the sevn.bot source tree (mirrored in the workspace under
`source_code/`). All names were fact-checked against the checkout; do not "correct" them
from memory.

---

## What sevn.bot is

A personal AI gateway: channels in, triage, tiered executors, tools, skills, and workspace
memory under operator control. Stack: Python 3.12+, package root `src/sevn/`
(hatchling / uv). Authoritative runtime config is `sevn.json`; per-agent sampling params
live in `LLM_params_config.json` (see below).

---

## Agent tiers (complexity routing)

The triager classifies each turn into a complexity tier. The enum is
`ComplexityTier` in `src/sevn/agent/triager/models.py` with members `A`, `B`, `C`, `D`.
Model selection per role is keyed by `ModelSlot` in
`src/sevn/config/model_resolution.py`: `triager`, `tier_b`, `tier_c`, `tier_d`,
`c_sub_lm`, `d_sub_lm`.

- **Tier A** — trivial / conversational. Handled inline by the triager's early
  acknowledgement; no separate executor LLM round.
- **Tier B** — single-agent tool-using executor. Entry point `run_b_turn` in
  `src/sevn/agent/executors/b_harness.py`.
- **Tier C / D** — heavier, plan-gated executor. Entry point `run_cd_turn` in
  `src/sevn/agent/executors/cd_harness.py` (C and D differ by model slot and sub-LM).

Transports, not provider classes, carry LLM calls (see "Transports" below). There is no
provider-class hierarchy — see "Names that do not exist" at the bottom for the specific
fabrications to avoid.

---

## Request flow (the gateway turn spine)

1. A channel adapter receives a message (e.g. `src/sevn/channels/telegram.py`).
2. The gateway turn is built in `src/sevn/gateway/agent_turn.py` (`build_agent_run_turn`),
   which owns the per-turn spine.
3. Triage runs via `triage_turn` in `src/sevn/agent/triager/run.py`, producing a
   `TriageResult` (intent, complexity, selected tools/skills). The decision is persisted
   through `src/sevn/gateway/triage/triage_audit.py`.
4. On `ComplexityTier.B`, `agent_turn.py` resolves a tier-B transport bundle
   (`ResolvedTierBModel`) and calls `run_b_turn`.
5. On `ComplexityTier.C` / `ComplexityTier.D`, it calls `run_cd_turn`.
6. Outbound text is routed back through the channel router
   (`src/sevn/gateway/channel_router.py`, `route_outgoing`) and delivered by the channel
   adapter.

Turns run as per-session background workers (see `src/sevn/gateway/session_manager.py`);
the asyncio model serializes per session and keeps the poll loop responsive.

---

## Which files actually call an LLM

These are the **only** call sites that issue an LLM request. If asked "which files call an
LLM?", this is the complete set — do not add invented paths.

| Role | File |
|------|------|
| Triager | `src/sevn/agent/triager/run.py` |
| Tier-B executor | `src/sevn/agent/adapters/tier_b_model.py` |
| Tier-C/D executor | `src/sevn/agent/executors/cd_harness.py` |
| LLM guard / prompt scanner | `src/sevn/security/llm_guard_scanner.py` |
| LCM compaction | `src/sevn/lcm/compaction.py` |
| Dreaming scorer | `src/sevn/memory/dreaming/scorer.py` |
| User-model extractor | `src/sevn/memory/user_model/extractor.py` |

The per-agent **sampling parameters** for every one of these are resolved by
`resolve_llm_params` / `resolve_llm_request_params` in `src/sevn/config/llm_params.py`.

---

## Transports (how a request reaches a provider)

There is no provider class hierarchy. A model id maps to a *transport*:

- `resolve_transport_for_model_id` in `src/sevn/config/model_resolution.py` picks the
  transport label. MiniMax catalog ids (`minimax/...`) resolve to the `anthropic`
  transport; the default is `chat_completions`.
- `resolve_model` in `src/sevn/agent/providers/resolve.py` maps the label to a `Transport`
  (`anthropic`, `chat_completions`, `responses_api`, `bedrock`).
- The request body is shaped by `adapt_request_for_transport`
  (`src/sevn/agent/providers/wire.py`) and posted by `Transport.complete`
  (`src/sevn/agent/providers/transport.py`) through `transport_http`.

Sampling-key support per transport (filtered in `llm_params.py`, not at the transport):
`anthropic` accepts `temperature`/`top_p`/`top_k` (no `seed`); `chat_completions` accepts
`temperature`/`top_p`/`seed` (no `top_k`); `bedrock` accepts `temperature`/`top_p`/`top_k`.

---

## Where data lives

- **Sessions and messages**: SQLite `sevn.db` (`gateway_sessions` and `gateway_messages`
  tables), accessed via `src/sevn/gateway/session_manager.py`. Storage helpers live under
  `src/sevn/storage/`.
- **Workspace files**: under the workspace `content_root` (resolved by
  `WorkspaceLayout` in `src/sevn/workspace/layout.py`). Narrative/operator memory files
  (`AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, `SESSIONS.md`, this
  `SEVN-ARCHITECTURE.md`, …) are seeded copy-if-absent by
  `src/sevn/onboarding/seed.py` (`seed_narrative_templates`).
- **Per-agent sampling config**: `LLM_params_config.json` at the workspace root, seeded
  copy-if-absent by `seed_llm_params` in `src/sevn/onboarding/seed.py`. Authoritative
  runtime config is `sevn.json`.
- **Logs**: `<content_root>/logs/` (e.g. `gateway.log`, `proxy.log`), queryable with the
  `log_query` tool.
- **Traces**: `.sevn/traces/` (or the configured `jsonl_file` sink path).

---

## Names that do not exist

The bot has previously **fabricated** these — they are NOT real. Never reference them:

- `src/sevn/llm/gateway.py` (no such file)
- `LlmGateway`, `OpenAiLlm`, `AnthropicLlm` (no such classes)
- `LLM_TRIAGER_*` environment/config keys (no such keys)
- "GPT-4o" as a configured model (not a sevn.bot model id; ids look like
  `minimax/...` or provider-prefixed strings resolved via `model_resolution.py`)

When in doubt, read the file with a tool and quote what you actually see.
