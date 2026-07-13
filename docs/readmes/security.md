<!-- generated: do not edit by hand; run `sevn readme update security` -->
# Security scanner — LLM Guard,

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** LLM Guard, .llmignore, block-and-notify, and channel security copy. Deliver a single scanner subsystem that runs in the gateway process so hostile content is filtered before the Triager or any routing model sees user-visible text, transcripts, or selected tool output.

## Level 1 — Overview (non-technical)

**Security scanner** is a core part of sevn.bot — the personal AI assistant you run on your own machine. LLM Guard, .llmignore, block-and-notify, and channel security copy.

In everyday use, security scanner helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver a single scanner subsystem that runs in the gateway process so hostile content is filtered before the Triager or any routing model sees user-visible text, transcripts, or selected tool output.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/security/`. The package contains 32 Python module(s); primary entry points include `src/sevn/security/__init__.py`, `src/sevn/security/egress_firewall.py`, `src/sevn/security/llm_guard_scanner.py`, `src/sevn/security/llmignore.py`, `src/sevn/security/oauth/__init__.py`, `src/sevn/security/oauth/authorize.py`, and 26 more.

### Data and control flow

Security scanner is a supporting subsystem; see Level 3 for the module-level flow.

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/09-security-scanner.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/security/egress_firewall.py` — `write_macos_pf_ruleset`, `egress_firewall_noop`, `write_linux_iptables_ruleset`, `apply_namespace_egress_firewall`
- `src/sevn/security/llm_guard_scanner.py` — `LLMGuardScanner.scan_inbound`, `LLMGuardScanner.scan_tool_result`, `LLMGuardScanner.scan_feedback_body`, `scan_patch_diff`
- `src/sevn/security/llmignore.py` — `resolve_llmignore_root`, `ensure_llmignore_layout`, `is_llmignored`, `sweep_expired`
- `src/sevn/security/oauth/authorize.py` — `build_authorization_flow`
- `src/sevn/security/oauth/callback.py` — `OAuthCallbackServer.ready`, `OAuthCallbackServer.wait_for_code`, `OAuthCallbackServer.close`, `parse_pasted_oauth_redirect`

### Spec context

From about-sevn.bot/specs/09-security-scanner.md:
Deliver a single scanner subsystem that runs in the gateway process so hostile content is filtered before the Triager or any routing model sees user-visible text, transcripts, or selected tool output.

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
