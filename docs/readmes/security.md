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

### Browser renderer sandbox vs container hardening (C8.1 / C8.4)

Operator compose may set `cap_drop: ALL` and `security_opt: [no-new-privileges:true]` on gateway/proxy. Those are **container** hardening controls. They do **not** substitute for Chromium's **renderer sandbox**.

- **Never** pass `--no-sandbox` via compose overlays or `SEVN_BROWSER_EXTRA_ARGS` in shipped files — including the production overlay. `make check-compose-default` rejects the token in every `docker/docker-compose*.yml`.
- Login-grade spawn keeps `--disable-features=IsolateOrigins,site-per-process` as a **justified** tradeoff for operator-driven auth flows against operator-chosen destinations (`src/sevn/browser/chrome.py`). That flag relaxes site-per-process isolation; it is **not** a general untrusted-browsing posture. A future untrusted-browsing mode must **not** inherit it.
- The Chromium/Brave renderer sandbox remains the primary process-isolation control for browser content; container caps only constrain the host namespace.

#### What the renderer sandbox needs to actually start

Dropping `--no-sandbox` only buys isolation if Brave can build its namespace sandbox. Two preconditions must hold, and both fail at runtime with the same opaque abort — `Failed to move to new namespace: … errno = Operation not permitted`, then `FATAL … zygote_host_impl_linux.cc`:

1. **Container syscall policy.** Docker's *default* seccomp profile gates `clone(CLONE_NEW*)`, `clone3` and `unshare` behind `CAP_SYS_ADMIN`, and `chroot` behind `CAP_SYS_CHROOT`. Under the overlays' `cap_drop: ALL` those are all denied, so Brave cannot create the user namespace it sandboxes renderers in. The browser and GUI overlays therefore pin **`infra/docker/seccomp-browser.json`** — Docker's default profile with exactly those four syscalls ungated. `mount`, `pivot_root`, `setns`, `bpf` and `perf_event_open` stay gated, and the container keeps `cap_drop: ALL` + `no-new-privileges:true`. This is strictly stronger than `--no-sandbox`, and far narrower than `seccomp=unconfined` (which would discard the whole syscall filter).

2. **Host user-namespace policy.** The kernel and container runtime must let the container create a user namespace. `scripts/check-browser-host.sh` (`make check-browser-host`, and automatically on `make compose-browser-up` / `make compose-gui-up`) **proves** this rather than inferring it — it runs `unshare -U` in a throwaway container under the overlays' exact security context (`cap_drop: ALL` + `no-new-privileges` + the pinned profile) and fails closed if the namespace is denied. When the probe itself cannot run (no daemon, image unavailable) it warns and passes: an unreachable daemon is not evidence about the sandbox.

   This is a property of the machine, not the repo, which is why it runs on the deploy path and not in CI's static gates — `make check-compose-default` asserts only that the committed overlays pin the profile.

   **`apparmor_restrict_unprivileged_userns=1` is not a blocker.** Ubuntu 23.10+ defaults that sysctl to `1`, and it is a tempting thing to gate on, but the restriction does not apply to processes running under Docker's own AppArmor profile. GitHub's `ubuntu-24.04` runners ship it set to `1` and the hardened Brave smoke passes there unmodified — the CI `docker-images` job records the value and boots Brave on a stock runner precisely so that claim keeps being re-proved. Gating on the sysctl would refuse to start on hosts that work fine, which is why the preflight probes instead.

   Where a host genuinely does mediate userns *for containers*, be aware that loading an AppArmor policy is not sufficient by itself — the container must **select** it, or Docker applies `docker-default` regardless:

   ```yaml
   # operator-supplied compose override, alongside the shipped overlay
   services:
     sevn-gateway:
       security_opt:
         - apparmor=<your-profile>
   ```

   sevn deliberately ships no such profile: no supported host has been observed to need one, and shipping an unselected policy file would be cargo-cult. If you hit a host that does require it, please report it — the shipped overlays would then need a first-class option rather than an operator override.

   `SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1` bypasses the gate once another mitigation has been accepted.

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

#### Docker sandbox network enforcement

Docker spawn uses the dedicated **`--internal`** bridge **`sevn-sandbox`**
([`ensure_sandbox_docker_network`](../../src/sevn/security/sandbox_runtime.py))
— containers cannot reach the public internet directly; egress is only via
[`SEVN_PROXY_URL`](../../src/sevn/security/sandbox_runtime.py) when configured.
`sandbox.runtime` trace events emit **`network_enforcement: "docker_internal"`**
(not a written-but-unapplied rules file).

**Known tradeoff:** [`ensure_proxy_attached_to_sandbox_network`](../../src/sevn/security/sandbox_runtime.py)
attaches the **whole** egress-proxy container to `sevn-sandbox` so sandbox
containers can reach the reverse-proxy API. That proxy interface is therefore
on the same internal bridge as sandboxes — not re-architected in post-audit
0.0.1 (D15).

Subprocess/namespace spawn paths use
[`apply_namespace_egress_firewall`](../../src/sevn/security/egress_firewall.py)
(optional apply via `SEVN_SANDBOX_IPTABLES_APPLY=1` on Linux). The
[`_write_docker_network_policy`](../../src/sevn/security/sandbox_runtime.py)
helper remains for operator reference but is **not** invoked on Docker spawn.

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
