<!-- generated: do not edit by hand; run `sevn readme update proxy-egress` -->
# Egress proxy — Paired proxy daemon, /llm/* routes, Transport wire shapes, and session tokens

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Paired proxy daemon, /llm/* routes, Transport wire shapes, and session tokens.

## Level 1 — Overview (non-technical)

**Egress proxy** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Paired proxy daemon, /llm/* routes, Transport wire shapes, and session tokens.

In everyday use, egress proxy helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Normalize provider-shaped JSON over async HTTP to a single egress base URL (SEVN_PROXY_URL / ProcessSettings.proxy_url), so tier executors bind once per turn and never touch raw secrets. LiteLLM may r

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/proxy/`. The package contains 19 Python module(s); primary entry points include `src/sevn/proxy/__init__.py`, `src/sevn/proxy/anthropic_body.py`, `src/sevn/proxy/app.py`, `src/sevn/proxy/auth.py`, and 2 more.

### Data and control flow

Egress proxy sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/05-llm-transports.md`, `about-sevn.bot/specs/07-egress-proxy.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/proxy/anthropic_body.py` — `normalize_anthropic_request_body`
- `src/sevn/proxy/app.py` — `create_app`
- `src/sevn/proxy/auth.py` — `llm_post_auth_failure`
- `src/sevn/proxy/bedrock_converse.py` — `converse_via_bedrock`
- `src/sevn/proxy/codex_translation.py` — `translate_chat_to_responses_request`, `translate_responses_to_chat_completion`, `translate_responses_sse_to_chat_stream`, `aggregate_responses_sse`

### Spec context

From about-sevn.bot/specs/05-llm-transports.md:
Normalize provider-shaped JSON over async HTTP to a single egress base URL (SEVN_PROXY_URL / ProcessSettings.proxy_url), so tier executors bind once per turn and never touch raw secrets. LiteLLM may r

From about-sevn.bot/specs/07-egress-proxy.md:
Product pairing (v1). Deployment, paired daemon install, onboarding validation, and Mission Control management of the proxy are specified in prd-06-setup-and-operations and prd-07-mission-control §5.1

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/proxy/` (19 Python files). Normative design: `about-sevn.bot/specs/05-llm-transports.md`, `about-sevn.bot/specs/07-egress-proxy.md`.

### Module inventory

- `src/sevn/proxy/__init__.py` — """Egress LLM proxy (ASGI): vendor auth injection for ''/llm/*'' routes.
- `src/sevn/proxy/anthropic_body.py` — """Anthropic Messages request normalization for the egress proxy ('about-sevn.bot/specs/07-egress-proxy.md' §5).
- `src/sevn/proxy/app.py` — """Starlette ASGI app for the egress LLM proxy.
- `src/sevn/proxy/auth.py` — """Shared-secret guard for proxy ''POST /llm/*'' routes.
- `src/sevn/proxy/bedrock_converse.py` — """AWS Bedrock Converse forwarding for the egress proxy ('about-sevn.bot/specs/07-egress-proxy.md').
- `src/sevn/proxy/codex_translation.py` — """Chat-completions ↔ Codex Responses translation (W3.3 — D7).
- `src/sevn/proxy/codex_transport.py` — """Codex OAuth Responses transport helpers (W3.2 — D1/D7).
- `src/sevn/proxy/credentials.py` — """Build ''ProxySettings'' from workspace secrets and provider metadata.
- `src/sevn/proxy/forward.py` — """Httpx forward primitives for the egress proxy (test seam).
- `src/sevn/proxy/http_client.py` — """Shared ''httpx.AsyncClient'' factory for the egress proxy lifespan.
- `src/sevn/proxy/integration/__init__.py` — """Egress proxy third-party integration dispatch ('about-sevn.bot/specs/29-cursor-cloud-agent.md').
- `src/sevn/proxy/integration/cursor.py` — """Cursor Cloud Agents API v1 forwarder ('about-sevn.bot/specs/29-cursor-cloud-agent.md' §2.3).
- … and 7 more Python modules

### Anthropic Body (`src/sevn/proxy/anthropic_body.py`)

Public entry points:
- `normalize_anthropic_request_body` — see `src/sevn/proxy/anthropic_body.py`

### App (`src/sevn/proxy/app.py`)

Public entry points:
- `create_app` — see `src/sevn/proxy/app.py`

### Auth (`src/sevn/proxy/auth.py`)

Public entry points:
- `llm_post_auth_failure` — see `src/sevn/proxy/auth.py`

### Bedrock Converse (`src/sevn/proxy/bedrock_converse.py`)

Public entry points:
- `converse_via_bedrock` — see `src/sevn/proxy/bedrock_converse.py`

### Codex Translation (`src/sevn/proxy/codex_translation.py`)

Public entry points:
- `translate_chat_to_responses_request` — see `src/sevn/proxy/codex_translation.py`
- `translate_responses_to_chat_completion` — see `src/sevn/proxy/codex_translation.py`
- `translate_responses_sse_to_chat_stream` — see `src/sevn/proxy/codex_translation.py`
- `aggregate_responses_sse` — see `src/sevn/proxy/codex_translation.py`

### Codex Transport (`src/sevn/proxy/codex_transport.py`)

Public entry points:
- `codex_responses_url` — see `src/sevn/proxy/codex_transport.py`
- `build_codex_request_headers` — see `src/sevn/proxy/codex_transport.py`

### Credentials (`src/sevn/proxy/credentials.py`)

Public entry points:
- `credential_unresolved_detail` — see `src/sevn/proxy/credentials.py`
- `resolve_request_credential` — see `src/sevn/proxy/credentials.py`
- `resolve_oauth_request_credential` — see `src/sevn/proxy/credentials.py`
- `resolve_oauth_request_credential_async` — see `src/sevn/proxy/credentials.py`
- `build_proxy_settings` — see `src/sevn/proxy/credentials.py`
- `build_proxy_settings_sync` — see `src/sevn/proxy/credentials.py`

### Forward (`src/sevn/proxy/forward.py`)

Public entry points:
- `redact_headers` — see `src/sevn/proxy/forward.py`
- `summarize_request_body` — see `src/sevn/proxy/forward.py`
- `post_json` — see `src/sevn/proxy/forward.py`
- `post_sse_stream` — see `src/sevn/proxy/forward.py`

### Http Client (`src/sevn/proxy/http_client.py`)

Public entry points:
- `build_proxy_upstream_timeout` — see `src/sevn/proxy/http_client.py`
- `create_proxy_http_client` — see `src/sevn/proxy/http_client.py`

### Additional modules

7 more Python files under `src/sevn/proxy/` — including `src/sevn/proxy/integration/github.py`, `src/sevn/proxy/integration/mcp_expand.py`, `src/sevn/proxy/integration/router.py`, `src/sevn/proxy/oauth_lifecycle.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/05-llm-transports.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/proxy/`, run `sevn readme update proxy-egress` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/05-llm-transports.md](../../about-sevn.bot/specs/05-llm-transports.md)
- [../../about-sevn.bot/specs/07-egress-proxy.md](../../about-sevn.bot/specs/07-egress-proxy.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/05-llm-transports.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/proxy/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
