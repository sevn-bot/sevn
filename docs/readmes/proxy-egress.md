<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint proxy-egress` -->
# Egress proxy — Shared-secret-guarded `/llm/*` egress proxy, Transport wire shapes, and route handlers

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Shared-secret-guarded `/llm/*` egress proxy, Transport wire shapes, and route handlers.

## Level 1 — Overview (non-technical)

The **egress proxy** is a small ASGI service that holds **provider API keys** and forwards outbound HTTP on sevn's behalf. Tier B/C/D executors talk to one base URL (`SEVN_PROXY_URL`) with normalized JSON shapes — they never see raw Anthropic/OpenAI/Bedrock credentials.

When configured, a **shared secret** (`SEVN_PROXY_SHARED_SECRET`) gates every `POST` to `/llm/*`, `/web/*`, and `/integration` via the `X-Sevn-Proxy-Token` header. The gateway and proxy run as a paired install; provider keys resolve here, channel tokens resolve in the gateway.

## Level 2 — How it works (technical)

Implementation lives under [`src/sevn/proxy/`](../../src/sevn/proxy/). [`create_app`](../../src/sevn/proxy/app.py#L92) builds the Starlette ASGI app; tier executors reach it through [`_ProxyTransport`](../../src/sevn/agent/providers/transport.py#L442) in [`transport.py`](../../src/sevn/agent/providers/transport.py).

### Route table

Registered in [`app.py`](../../src/sevn/proxy/app.py) (see routes list ~L436):

| Prefix | Method | Handler | Purpose |
| --- | --- | --- | --- |
| `/llm/anthropic/messages` | POST | `anthropic_messages` | Anthropic Messages API |
| `/llm/openai/chat/completions` | POST | `openai_chat_completions` | OpenAI-compatible chat (incl. MiniMax routing) |
| `/llm/openai/responses` | POST | `openai_responses` | OpenAI Responses / Codex OAuth path |
| `/llm/bedrock/converse` | POST | `bedrock_converse` | AWS Bedrock Converse |
| `/web/fetch` | POST | `web_fetch` | Page fetch for tools |
| `/web/brave/search` | POST | `web_brave_search` | Brave web search |
| `/integration` | POST | [`integration_post`](../../src/sevn/proxy/integration/__init__.py) | Cursor Cloud / GitHub dispatch |
| `/healthz` | GET | `healthz` | Liveness |

### Shared-secret auth

[`llm_post_auth_failure`](../../src/sevn/proxy/auth.py#L26) checks `X-Sevn-Proxy-Token` against `proxy_shared_secret` from [`ProxySettings`](../../src/sevn/proxy/settings.py) (env alias `SEVN_PROXY_SHARED_SECRET`). Empty/unset secret skips the guard (dev-only). Guarded prefixes: `/llm/`, `/web/`, `/integration/`.

### Credential injection

[`resolve_request_credential`](../../src/sevn/proxy/credentials.py#L343) maps `(route, model_id)` to the workspace provider registry and injects vendor auth headers per request. OAuth Codex paths use [`resolve_oauth_request_credential_async`](../../src/sevn/proxy/credentials.py#L494).

### Client transport wire shapes

Gateway/agent code binds [`Transport`](../../src/sevn/agent/providers/transport.py#L327) implementations once per turn — [`AnthropicMessagesTransport`](../../src/sevn/agent/providers/transport.py#L678), [`ChatCompletionsTransport`](../../src/sevn/agent/providers/transport.py#L700), [`BedrockTransport`](../../src/sevn/agent/providers/transport.py#L750) all POST to the proxy base URL with provider-shaped JSON; the proxy normalizes and forwards upstream.

### Configuration

- Process: `SEVN_PROXY_URL`, `SEVN_PROXY_SHARED_SECRET` ([`ProcessSettings`](../../src/sevn/config/settings.py))
- Workspace pairing: `sevn.json` provider entries + secrets chain wired at proxy boot
- Validate: `sevn doctor`; proxy factory reads `{SEVN_HOME}/workspace/sevn.json` when started via uvicorn `--factory`

### Key modules

- [`app.py`](../../src/sevn/proxy/app.py) — [`create_app`](../../src/sevn/proxy/app.py#L92), route table, auth middleware
- [`auth.py`](../../src/sevn/proxy/auth.py) — [`llm_post_auth_failure`](../../src/sevn/proxy/auth.py#L26)
- [`credentials.py`](../../src/sevn/proxy/credentials.py) — per-route key resolution
- [`forward.py`](../../src/sevn/proxy/forward.py) — httpx POST/SSE primitives
- [`integration/router.py`](../../src/sevn/proxy/integration/router.py) — `/integration` dispatcher

Normative specs: [`05-llm-transports.md`](../../about-sevn.bot/specs/05-llm-transports.md), [`07-egress-proxy.md`](../../about-sevn.bot/specs/07-egress-proxy.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/proxy`](../../src/sevn/proxy/) (19 Python files). Normative design: `about-sevn.bot/specs/05-llm-transports.md`, `about-sevn.bot/specs/07-egress-proxy.md`.

### Module inventory

Egress LLM proxy (ASGI): vendor auth injection for /llm/* routes.

Working with [`__init__.py`](../../src/sevn/proxy/__init__.py): inspect the public entry points below.

Anthropic Messages request normalization for the egress proxy (about-sevn.bot/specs/07-egress-proxy.md §5).

Working with [`anthropic_body.py`](../../src/sevn/proxy/anthropic_body.py): inspect the public entry points below.
Start with [`normalize_anthropic_request_body`](../../src/sevn/proxy/anthropic_body.py#L60).

Starlette ASGI app for the egress LLM proxy.

Working with [`app.py`](../../src/sevn/proxy/app.py): inspect the public entry points below.
Start with [`create_app`](../../src/sevn/proxy/app.py#L92).

Shared-secret guard for proxy POST /llm/* routes.

Working with [`auth.py`](../../src/sevn/proxy/auth.py): inspect the public entry points below.
Start with [`llm_post_auth_failure`](../../src/sevn/proxy/auth.py#L26).

AWS Bedrock Converse forwarding for the egress proxy (about-sevn.bot/specs/07-egress-proxy.md).

Working with [`bedrock_converse.py`](../../src/sevn/proxy/bedrock_converse.py): inspect the public entry points below.
Start with [`converse_via_bedrock`](../../src/sevn/proxy/bedrock_converse.py#L14).

Chat-completions ↔ Codex Responses translation (W3.3 — D7).

Working with [`codex_translation.py`](../../src/sevn/proxy/codex_translation.py): inspect the public entry points below.
Start with [`translate_chat_to_responses_request`](../../src/sevn/proxy/codex_translation.py#L308), then [`translate_responses_to_chat_completion`](../../src/sevn/proxy/codex_translation.py#L462), [`translate_responses_sse_to_chat_stream`](../../src/sevn/proxy/codex_translation.py#L563), [`aggregate_responses_sse`](../../src/sevn/proxy/codex_translation.py#L836).

Codex OAuth Responses transport helpers (W3.2 — D1/D7).

Working with [`codex_transport.py`](../../src/sevn/proxy/codex_transport.py): inspect the public entry points below.
Start with [`codex_responses_url`](../../src/sevn/proxy/codex_transport.py#L49), then [`build_codex_request_headers`](../../src/sevn/proxy/codex_transport.py#L62).

Build ProxySettings from workspace secrets and provider metadata.

Working with [`credentials.py`](../../src/sevn/proxy/credentials.py): inspect the public entry points below.
Start with [`credential_unresolved_detail`](../../src/sevn/proxy/credentials.py#L107), then [`resolve_request_credential`](../../src/sevn/proxy/credentials.py#L343), [`resolve_oauth_request_credential`](../../src/sevn/proxy/credentials.py#L457), [`resolve_oauth_request_credential_async`](../../src/sevn/proxy/credentials.py#L494).

Httpx forward primitives for the egress proxy (test seam).

Working with [`forward.py`](../../src/sevn/proxy/forward.py): inspect the public entry points below.
Start with [`redact_headers`](../../src/sevn/proxy/forward.py#L70), then [`summarize_request_body`](../../src/sevn/proxy/forward.py#L139), [`post_json`](../../src/sevn/proxy/forward.py#L273), [`post_sse_stream`](../../src/sevn/proxy/forward.py#L334).

Shared httpx.AsyncClient factory for the egress proxy lifespan.

Working with [`http_client.py`](../../src/sevn/proxy/http_client.py): inspect the public entry points below.
Start with [`build_proxy_upstream_timeout`](../../src/sevn/proxy/http_client.py#L35), then [`create_proxy_http_client`](../../src/sevn/proxy/http_client.py#L63).

Egress proxy third-party integration dispatch (about-sevn.bot/specs/29-cursor-cloud-agent.md).

Working with [`__init__.py`](../../src/sevn/proxy/integration/__init__.py): inspect the public entry points below.

Cursor Cloud Agents API v1 forwarder (about-sevn.bot/specs/29-cursor-cloud-agent.md §2.3).

Working with [`cursor.py`](../../src/sevn/proxy/integration/cursor.py): inspect the public entry points below.
Start with [`dispatch_cursor`](../../src/sevn/proxy/integration/cursor.py#L130).

7 more Python files under [`src/sevn/proxy`](../../src/sevn/proxy/) — including `src/sevn/proxy/integration/github.py`, `src/sevn/proxy/integration/mcp_expand.py`, `src/sevn/proxy/integration/router.py`, `src/sevn/proxy/oauth_lifecycle.py`.

### Extension and invariants

Follow [`05-llm-transports.md`](../../about-sevn.bot/specs/05-llm-transports.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/proxy`](../../src/sevn/proxy/), run `sevn readme update proxy-egress` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/05-llm-transports.md](../../about-sevn.bot/specs/05-llm-transports.md)
- [../../about-sevn.bot/specs/07-egress-proxy.md](../../about-sevn.bot/specs/07-egress-proxy.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/05-llm-transports.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/proxy/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
