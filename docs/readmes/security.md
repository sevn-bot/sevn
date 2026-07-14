<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint security` -->
# Security scanner — LLM Guard, .llmignore, block-and-notify, and channel security copy

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** LLM Guard, .llmignore, block-and-notify, and channel security copy.

## Level 1 — Overview (non-technical)

**Security scanner** filters hostile or sensitive content **before** any routing model sees it. Inbound Telegram/Web UI text, selected tool output, feedback bodies, and patch diffs can be scanned. When content is blocked, sevn **does not** silently drop it — the operator gets a clear channel message, an audit row under `.llmignore/`, and a non-LLM-visible transcript entry.

This is defense in depth alongside tool permission gates and sandbox isolation — not a replacement for operator judgment.

## Level 2 — How it works (technical)

Core scanner code lives in [`src/sevn/security/`](../../src/sevn/security/). The gateway wires it at the channel boundary ([`channel_router.py`](../../src/sevn/gateway/channel_router.py)).

### LLM Guard scan points

[`LLMGuardScanner`](../../src/sevn/security/llm_guard_scanner.py#L543) ([`llm_guard_scanner.py`](../../src/sevn/security/llm_guard_scanner.py)) exposes async instance methods plus one module helper:

| Entry point | When |
| --- | --- |
| [`scan_inbound`](../../src/sevn/security/llm_guard_scanner.py#L564) | Every gateway inbound message (before triage) |
| [`scan_tool_result`](../../src/sevn/security/llm_guard_scanner.py#L603) | Selected tool output before re-entering the model |
| [`scan_feedback_body`](../../src/sevn/security/llm_guard_scanner.py#L670) | Web App / structured feedback payloads |
| [`scan_patch_diff`](../../src/sevn/security/llm_guard_scanner.py#L1080) (module helper) | Self-improve patch promotion path |

Verdicts are [`ScanVerdict`](../../src/sevn/security/llm_guard_scanner.py#L123) **allow** or **block** with [`BlockReason`](../../src/sevn/security/llm_guard_scanner.py#L130) codes and provider metadata. Owner overrides can skip named guard kinds via config. There is **no** `security.scanner.enabled` field — scanner behaviour is always active when wired; tune providers, thresholds, and `heuristic_only` instead.

### Block-and-notify flow

When [`scan_inbound`](../../src/sevn/security/llm_guard_scanner.py#L564) returns block ([`channel_router.py`](../../src/sevn/gateway/channel_router.py)):

1. **[`write_blocked_inbound`](../../src/sevn/security/llmignore.py#L337)** — atomic JSON under `.llmignore/blocked/` ([`llmignore.py`](../../src/sevn/security/llmignore.py))
2. **Session row** — user message stored as `kind="blocked"`, `visible_to_llm=0`
3. **Trace events** — `gateway.llm_guard_block`, [`gateway.route_incoming`](../../src/sevn/gateway/channel_router.py#L1348) with `status="stopped_blocked"`
4. **Channel notify** — [`blocked_inbound_user_message`](../../src/sevn/gateway/util/strings.py#L47) ([`gateway/strings.py`](../../src/sevn/gateway/util/strings.py)) sent via the channel adapter

Feedback blocks mirror the pattern via [`write_blocked_feedback`](../../src/sevn/security/llmignore.py#L398).

### `.llmignore` layout

[`resolve_llmignore_root`](../../src/sevn/security/llmignore.py#L61) + [`ensure_llmignore_layout`](../../src/sevn/security/llmignore.py#L92) create:

- `.llmignore/blocked/` — inbound/feedback blocks
- `.llmignore/quarantine/` — held content with TTL
- `.llmignore/incidents/` — scanner incident records

[`sweep_expired`](../../src/sevn/security/llmignore.py#L164) enforces TTLs from `security.llmignore.retention_days` (`blocked`, `quarantine`, `incidents` day counts) in `sevn.json`. Indexers honor `DEFAULT_INDEX_DENY` so `.llmignore/` never enters LLM-facing corpora. Shadow workspaces must exclude the subtree ([`assert_shadow_workspace_excludes_llmignore`](../../src/sevn/security/llmignore.py#L208)).

### Configuration (`sevn.json` → `security`)

Key knobs (full schema: [`infra/sevn.schema.json`](../../infra/sevn.schema.json)):

- `security.scanner.providers`, `heuristic_only`, `bypass_owner`, `model`, `max_inbound_bytes` — LLM Guard backend and thresholds ([`SecurityScannerSubConfig`](../../src/sevn/config/sections/security.py#L79))
- `security.llmignore.retention_days.*` — per-subtree TTLs (`blocked`, `quarantine`, `incidents`)

**Schema reflection gaps:** some Pydantic-only subtrees (for example nested scanner fields) may not appear verbatim in [`infra/sevn.schema.json`](../../infra/sevn.schema.json); treat [`src/sevn/config/sections/security.py`](../../src/sevn/config/sections/security.py) as authoritative when the schema lags.

Validate after edits: `sevn config validate`.

### Key modules

- [`llm_guard_scanner.py`](../../src/sevn/security/llm_guard_scanner.py) — [`LLMGuardScanner`](../../src/sevn/security/llm_guard_scanner.py#L543), [`scan_patch_diff`](../../src/sevn/security/llm_guard_scanner.py#L1080)
- [`llmignore.py`](../../src/sevn/security/llmignore.py) — layout, persistence, [`sweep_expired`](../../src/sevn/security/llmignore.py#L164)
- [`channel_router.py`](../../src/sevn/gateway/channel_router.py) — inbound gate + notify path
- [`strings.py`](../../src/sevn/gateway/util/strings.py) — [`blocked_inbound_user_message`](../../src/sevn/gateway/util/strings.py#L47)

Normative spec: [`about-sevn.bot/specs/09-security-scanner.md`](../../about-sevn.bot/specs/09-security-scanner.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/security/` (32 Python files). Normative design: `about-sevn.bot/specs/09-security-scanner.md`.

### Module inventory

- `src/sevn/security/__init__.py` — Security policy and sandboxing (''about-sevn.bot/specs/08-sandbox.md'').
- `src/sevn/security/egress_firewall.py` — Egress posture helpers inside sandbox namespaces (''about-sevn.bot/specs/08-sandbox.md'' §4.2, §8.2).
- `src/sevn/security/llm_guard_scanner.py` — Async LLM Guard scanner entrypoints (''about-sevn.bot/specs/09-security-scanner.md'' §2.1).
- `src/sevn/security/llmignore.py` — ''.llmignore/'' layout helpers (''about-sevn.bot/specs/09-security-scanner.md'' §2.2, §4.4).
- `src/sevn/security/oauth/__init__.py` — Codex (ChatGPT subscription) OAuth for sevn LLM transports (W0 scaffold).
- `src/sevn/security/oauth/authorize.py` — Authorize-URL builder for Codex OAuth (W2).
- `src/sevn/security/oauth/callback.py` — Local OAuth callback server for Codex PKCE (W2, D5).
- `src/sevn/security/oauth/constants.py` — OpenAI Codex OAuth constants (locked at W0 — ''codex-oauth-subscription'' plan).
- `src/sevn/security/oauth/credential.py` — Codex OAuth credential model and secret-alias helpers (W0 scaffold).
- `src/sevn/security/oauth/design.py` — Locked Codex OAuth design decisions (W0 gate — ''codex-oauth-subscription'' plan).
- `src/sevn/security/oauth/login_flow.py` — Codex OAuth login completion helpers (W4 — CLI + onboarding).
- `src/sevn/security/oauth/pkce.py` — PKCE pair generation for Codex OAuth (W2).
- … and 20 more Python modules

### Package init (`src/sevn/security/__init__.py`)

See `src/sevn/security/__init__.py` for implementation details.

### Egress Firewall (`src/sevn/security/egress_firewall.py`)

Public entry points:
- `write_macos_pf_ruleset`
- `egress_firewall_noop`
- `write_linux_iptables_ruleset`
- `apply_namespace_egress_firewall`

### Llm Guard Scanner (`src/sevn/security/llm_guard_scanner.py`)

Public entry points:
- `LLMGuardScanner.scan_inbound`
- `LLMGuardScanner.scan_tool_result`
- `LLMGuardScanner.scan_feedback_body`
- `scan_patch_diff`

### Llmignore (`src/sevn/security/llmignore.py`)

Public entry points:
- `resolve_llmignore_root`
- `ensure_llmignore_layout`
- `is_llmignored`
- `sweep_expired`
- `assert_shadow_workspace_excludes_llmignore`
- `write_blocked_inbound`
- `write_blocked_feedback`

### Package init (`src/sevn/security/oauth/__init__.py`)

See `src/sevn/security/oauth/__init__.py` for implementation details.

### Authorize (`src/sevn/security/oauth/authorize.py`)

Public entry points:
- `build_authorization_flow`

### Callback (`src/sevn/security/oauth/callback.py`)

Public entry points:
- `OAuthCallbackServer.ready`
- `OAuthCallbackServer.wait_for_code`
- `OAuthCallbackServer.close`
- `parse_pasted_oauth_redirect`
- `start_local_callback_server`

### Constants (`src/sevn/security/oauth/constants.py`)

See `src/sevn/security/oauth/constants.py` for implementation details.

### Credential (`src/sevn/security/oauth/credential.py`)

Public entry points:
- `resolution_probe_credential`
- `oauth_openai_secret_alias`

### Design (`src/sevn/security/oauth/design.py`)

See `src/sevn/security/oauth/design.py` for implementation details.

### Login Flow (`src/sevn/security/oauth/login_flow.py`)

See `src/sevn/security/oauth/login_flow.py` for implementation details.

### Pkce (`src/sevn/security/oauth/pkce.py`)

See `src/sevn/security/oauth/pkce.py` for implementation details.

### Additional modules

20 more Python files under `src/sevn/security/` — including `src/sevn/security/oauth/storage.py`, `src/sevn/security/oauth/token_client.py`, `src/sevn/security/sandbox_errors.py`, `src/sevn/security/sandbox_runtime.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/09-security-scanner.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/security/`, run `sevn readme update security` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/09-security-scanner.md](../../about-sevn.bot/specs/09-security-scanner.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/09-security-scanner.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/security/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
