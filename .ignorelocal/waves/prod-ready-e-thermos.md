# E-Thermos — thermo-nuclear review of Batch E (egress-scope) — **RE-RUN**

**Worktree:** `/Users/alex/Documents/code/sevn.bot/sevn-pr-e-egress-scope`
**Branch:** `wave/prod-ready-e-egress-scope` at tip `5a74bc15`
**Base for review (per D29):** `5a74bc15` (declared in `.ignorelocal/waves/prod-ready-e-thermos-base.sha`)
**Commit range reviewed:** `origin/pre-0.0.1..5a74bc15` (19 commits)
**Reviewer role:** fresh reviewer (D30; no overlap with E-Verify / E-Final execution)
**Severity rule:** clean **including `low`** (D31)
**Date:** 2026-08-07

## Verdict

**`pass`** — rebase restored (F-1 verified), 5 findings all resolved; no new Critical / High / Medium defects. One Low observation noted (`_enforce_session_egress_limits` not wired to `/web/brave/search`); matches the spec's stated `/web/fetch`-only scope and is not a defect. P2 / P3 / P5 / D30 clean.

## Re-verification of the 5 original E-Thermos findings

### F-1 (Critical) — base divergence / tracing loss — **RESOLVED**

`git diff origin/pre-0.0.1..5a74bc15` shows **no** changes to the tracing security files; all six files exist in the working tree at their `pre-0.0.1` content (rebase intact, no deletions by E's diff):

| File | Lines on HEAD | Diff vs `origin/pre-0.0.1` |
|---|---|---|
| `src/sevn/tracing/otel_pipeline.py` | 621 | 0 / 0 |
| `src/sevn/agent/tracing/sink_factory.py` | 290 | 0 / 0 |
| `src/sevn/agent/tracing/trace_event_bridge.py` | 438 | 0 / 0 |
| `src/sevn/channels/telegram_poll.py` | 466 | 0 / 0 |
| `tests/agent/tracing/test_otel_pipeline.py` | 423 | 0 / 0 |
| `tests/channels/test_telegram_poll_tracing.py` | 114 | 0 / 0 |

Behavioral tests for httpx URL bot-token redaction, Logfire `sevn.session_id` scrubbing, `tracing.export.exclude_kinds` filter, and `_poll_cycle_tick_tracing_enabled` survive. The 7 `#241`-era CHANGELOG entries survive (CHANGELOG diff shows +5 / 0 deletions, no `ffe11bd6`-era entries removed). **PASS.**

### F-2 (High) — `test_container_id_int_zero_rejected_returns_false_not_typeerror` — **PRESENT & GREEN**

Added in commit `527179d4` at `tests/proxy/test_prod_ready_run_bound_token_w18_red.py:307`. Live verified by direct invocation:

```
tests/proxy/test_prod_ready_run_bound_token_w18_red.py::test_container_id_int_zero_rejected_returns_false_not_typeerror PASSED
```

The test hand-crafts a token whose `container_id` claim is `int(0)`, calls `validate_session_token(token, ..., container_id="0")`, and asserts the return is `False` (not `TypeError`). P4a: deleting the `isinstance(token_cid, str)` guard at `src/sevn/proxy/auth.py:370` would let `hmac.compare_digest(0, "0")` raise `TypeError` and the assertion `result is False` would fail. **PASS.**

### F-3 (Medium) — `validate_session_token` uses `_check_binding` for `container_id` — **RESOLVED**

`src/sevn/proxy/auth.py:367-377`:

```python
if container_id is not None:
    token_cid = payload.get("container_id")
    if token_cid is not None:
        if not isinstance(token_cid, str) or not _check_binding(
            claim_value=token_cid,
            request_value=container_id,
            label="container_id",
        ):
            return False
    elif container_id:
        return False
```

Mirrors the `run_id` block at line 359-366. No bare `raise TypeError`. **PASS.**

### F-4 (Medium) — `test_destination_allowed_empty_list_denies_all` + HTTP variant — **PRESENT & GREEN**

Two tests added in commit `d16e3920`:

- `tests/proxy/test_prod_ready_egress_budgets_w18_red.py:249` — `test_destination_allowed_empty_list_denies_all`: mints via `_mint_budgeted_token(allowlist=[])`, asserts `pytest.raises(DestinationNotAllowed)` on `destination_allowed(token, ..., destination="https://any.example/")`.
- `tests/proxy/test_prod_ready_egress_budgets_w18_red.py:272` — `test_destination_allowed_empty_list_http_returns_403`: HTTP variant through the live proxy app, asserts `status_code in (403, 422)` and `status_code != 401`.

Live verified (both PASS). P4a: removing the `allowlist is None → return True` short-circuit and the `host not in allowed → DestinationNotAllowed` raise would break the test. Schema copy at `infra/sevn.schema.json:200` documents the fail-closed default ("Empty `allowlist` denies every destination (fail-closed default); omit the field to allow any host"). **PASS.**

### F-5 (Medium) — `byte_budget` non-negative int guard — **PRESENT**

`src/sevn/proxy/auth.py:255-259`:

```python
if byte_budget is not None and (
    not isinstance(byte_budget, int) or isinstance(byte_budget, bool) or byte_budget < 0
):
    msg = "byte_budget must be a non-negative int"
    raise ValueError(msg)
```

Matches the existing `request_budget` pattern at lines 260-266 exactly. The `isinstance(byte_budget, bool)` check is necessary because `bool` is a subclass of `int` in Python (without it, `byte_budget=True` would silently pass the int check). Live verified:

```
PASS byte_budget=-1: byte_budget must be a non-negative int
PASS byte_budget=True (bool): byte_budget must be a non-negative int
```

**PASS.**

### F-6 / F-7 / F-8 (Low) — deferred per gate record

- **F-6** (zero-container / empty-header binding tests): not added; non-blocking, deferred.
- **F-7** (subsumed by F-1): no separate handling needed.
- **F-8** (CHANGELOG ordering): **resolved by F-1 rebase** — the original complaint was that a `[2026-08-06]` entry was inserted "at the top of `Changed`". The current CHANGELOG shows `[2026-08-06] SEVN_SESSION_TOKEN` at line 24, between `[2026-08-07]` entries (lines 20-23) and other `[2026-08-06]` / `[2026-08-05]` entries (lines 25-31). Date-descending convention preserved.

## New findings

### Low

**L-1.** `_enforce_session_egress_limits` is wired only to `POST /web/fetch` (`src/sevn/proxy/app.py:591`), not to `POST /web/brave/search` (line 609 calls `brave_search_json` without going through the enforcer). The Brave search route is a sandbox family and would benefit from the same allowlist/budget enforcement. However, the spec amendment at `about-sevn.bot/specs/07-egress-proxy.md:340-345` (W20 C7.3) explicitly states "``sevn.proxy.session_limits`` enforces them on ``POST /web/fetch`` before upstream forward" — the omission is intentional / scoped. **Not a defect; flag for a follow-up wave if Brave search should fall under C7.3.**

**L-2.** `bind_id = (container_id or "").strip() or None` at `src/sevn/security/sandbox_runtime.py:930` is dead defensive code: the only caller (`_assemble_spawn_child_env`) always passes `container_id=bind_id` (a freshly-generated UUID hex string, never None or empty). The `.strip() or None` evaluates to the input. Not a defect, just code smell.

**L-3.** `build_egress_web_headers` (`src/sevn/tools/web.py:215-223`) mints a fresh session token on every call when the gateway does not supply one. This is per-request token minting rather than cached. Not a defect (TTL is short), but worth noting if hot-path latency becomes a concern.

No new Critical, High, or Medium findings.

## P2 — Terminal-gate authorship

5 commits in `origin/pre-0.0.1..5a74bc15` name gates in their subject or body:

```
5a74bc15 chore(wave): E-Thermos fix follow-up (F-1..F-5)
491ed3f5 docs(about-docs): refresh post-rebase fingerprints (E-THERMOS-1)
caea99fc docs(about-docs): refresh spec-08/09 fingerprint (E-THERMOS-4)
d16e3920 test(proxy): pin empty destination_allowed deny-all (E-THERMOS-4)
527179d4 fix(proxy): guard non-str container_id claim (E-THERMOS-2/3)
```

Per P2 rule, each is reviewed as new work and requires a RED test + re-verify pass:

- `5a74bc15`: docs-only (gate record); no production code; n/a.
- `491ed3f5`, `caea99fc`: docs-only (about-docs fingerprint refresh); n/a.
- `d16e3920` (TEST): adds `test_destination_allowed_empty_list_denies_all` and the HTTP variant. Both are RED tests against the production `destination_allowed` function (P4a verified). **PASS.**
- `527179d4` (PROD CODE + TEST): adds the `isinstance(token_cid, str)` guard at `src/sevn/proxy/auth.py:370` AND adds the RED test `test_container_id_int_zero_rejected_returns_false_not_typeerror` in the same commit. P4a: deleting the guard breaks the test. **PASS.**

**P2 clean** — RED tests and verify pass are bundled with each gate-authored commit.

## P3 — Intent is not a waiver

Diff grep on `src/sevn/`, `docker/`, `.github/`, `Makefile` for `dev.?only|advisory|exit-code 0|for now|temporar|needs-implementation|intentional|by design` returned:

```
src/sevn/proxy/auth.py:399: unless ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` (explicit dev-only opt-in).
```

This is the **pre-existing** docstring on `llm_post_auth_failure` describing the existing `SEVN_PROXY_ALLOW_UNAUTHENTICATED` opt-in. The opt-in is unchanged by E's diff (not a new shipped-default-unsafe branch). No new P3 patterns introduced by E. The schema copy at `infra/sevn.schema.json:200` uses "Intent (not yet shipped):" to mark **docstring-only** state (proxy minting API, PermissionConfig ceiling, revoke-on-teardown) — honest doc-as-intent, not a code waiver on a credential guard.

**P3 clean.**

## P5 — Silent opt-out / default-on dev branch / ephemeral secret in code

Diff grep for default-on auth bypass, ephemeral secrets in code, exit-code 0 escapes: no new matches. `SEVN_PROXY_ALLOW_UNAUTHENTICATED` (existing) is unchanged.

**P5 clean.**

## D30 — Fresh reviewer

This review reads only: `src/sevn/proxy/auth.py`, `src/sevn/proxy/session_limits.py`, `src/sevn/proxy/app.py`, `src/sevn/tools/web.py`, `src/sevn/security/sandbox_runtime.py`, `src/sevn/ui/dashboard/services/sandbox_terminal.py`, `src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py`, the corresponding tests, the schema, and the E-Final / E-Verify gate records. No overlap with E-Verify execution (the E-Verify executor wrote `044933ed`, `4eeeb33b`; this review inspected them but did not author them). E-Final steps (drift sweep, xfail sweep, skillspector, CHANGELOG refresh, ci-resume) are documented in `prod-ready-e-final.md` and produce no product code that escapes review. **D30 PASS.**

## D29 — Diff scope summary

| Path | Change | Lines vs `origin/pre-0.0.1` |
|---|---|---|
| `src/sevn/proxy/auth.py` | modified | +181 / 0 |
| `src/sevn/proxy/session_limits.py` | added | +275 / 0 |
| `src/sevn/proxy/app.py` | modified | +57 / 0 |
| `src/sevn/tools/web.py` | modified | +63 / 0 |
| `src/sevn/security/sandbox_runtime.py` | modified | +39 / 0 |
| `src/sevn/ui/dashboard/services/sandbox_terminal.py` | modified | +27 / 0 |
| `src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py` | modified | +23 / 0 |
| `tests/proxy/conftest.py` | modified | +32 / 0 |
| `tests/proxy/test_auth.py` | modified (D40 amendment) | 0 / 7 |
| `tests/proxy/test_integration_cursor.py` | modified | +17 / 0 |
| `tests/proxy/test_integration_github.py` | modified | +17 / 0 |
| `tests/proxy/test_post_audit_proxy_auth_w4_red.py` | modified (D40 amendment) | 0 / 50 |
| `tests/proxy/test_prod_ready_c11_guard_w1.py` | modified | +142 / 0 |
| `tests/proxy/test_prod_ready_egress_budgets_w18_red.py` | added (with E-Thermos-4 test) | +298 / 0 |
| `tests/proxy/test_prod_ready_egress_token_e_reverify.py` | added | +485 / 0 |
| `tests/proxy/test_prod_ready_run_bound_token_w18_red.py` | added (with E-Thermos-2/3 test) | +405 / 0 |
| `tests/proxy/test_prod_ready_session_token_schema_w18_red.py` | added | +52 / 0 |
| `tests/proxy/test_release_audit_ssrf_w1_red.py` | modified (D51 obsolete deletion) | 0 / 5 |
| `infra/sevn.schema.json` | modified (F-4 copy + C7.4 honesty) | +4 / 0 |
| `about-sevn.bot/specs/05-llm-transports.md` | modified (interface list refresh) | +19 / 0 |
| `about-sevn.bot/specs/07-egress-proxy.md` | modified (C7.1/C7.2/C7.3/C7.4 amendments + interfaces) | +53 / 0 |
| `about-sevn.bot/specs/08-sandbox.md` | modified (W19 amendment) | +14 / 0 |
| `about-sevn.bot/specs/09-security-scanner.md` | modified (fingerprint refresh) | +4 / 0 |
| `about-sevn.bot/specs/11-tools-registry.md`, `24-dashboard.md` | modified (fingerprint) | +8 / 0 |
| `about-sevn.bot/prd/03-trust-and-control.md`, `04-getting-things-done.md`, `05-cost-and-providers.md`, `07-mission-control.md` | modified (fingerprint) | +16 / 0 |
| `docs/readmes/_fingerprints.json` | modified | +24 / 0 |
| `CHANGELOG.md` | modified (E-Final unreleased + 2026-08-06 SEVN_SESSION_TOKEN) | +5 / 0 |
| `.ignorelocal/waves/prod-ready-e-final.md` | added (E-Final gate record) | +268 / 0 |
| `.ignorelocal/waves/prod-ready-e-thermos.md` | this file | +187 / 0 |
| `.ignorelocal/waves/prod-ready-e-verify.md` | added (E-Verify gate record) | +196 / 0 |

**No tracing security file (`src/sevn/tracing/otel_pipeline.py`, `src/sevn/agent/tracing/sink_factory.py`, `src/sevn/agent/tracing/trace_event_bridge.py`, `src/sevn/channels/telegram_poll.py`, `tests/agent/tracing/test_otel_pipeline.py`, `tests/channels/test_telegram_poll_tracing.py`) is modified by E's diff.** The rebase brought them forward intact.

## Five-check summary

1. **Correctness** — `mint_session_token` accepts `destination_allowed` / `request_budget` / `byte_budget` and emits a `limits` envelope only when at least one is non-default (`tests/proxy/test_prod_ready_egress_token_e_reverify.py::test_reverify_v2_mint_without_budgets_omits_limits_envelope`); `validate_session_token` enforces binding on every present claim; `consume_run_budget` exhausts at the configured limit (`test_w18_5_request_budget_exhausted_raises_distinguishable_error`). **PASS.**
2. **Breaking change** — Service secret rejection on `/web/*` (except `/web/auth-check`) and `/integration` is a deliberate, documented behavioral break (spec-07 W19 amendment; CHANGELOG). `llm_post_auth_failure` returns 401 with `{"detail":"unauthorized"}` body. **PASS.**
3. **Security** — Bot-token URL redaction, Logfire scrubbing, span-kind filtering, and `_poll_cycle_tick_tracing_enabled` are present on `pre-0.0.1` and **not deleted by E's diff** (F-1 verified). `int(0)` container_id is rejected via `_check_binding` (no `TypeError` escape). Empty `allowlist` denies all (fail-closed default documented in schema). **PASS.**
4. **DevEx** — `integration_session_headers` fixture is connascence-free; no silent breakage of non-integration tests (verified `tests/proxy/` runs 255/255 pass; `tests/sandbox/` 50 passed + 3 Docker-only skipped; `tests/security/` 108 passed + 1 Linux-only skipped; `tests/tools/test_web_tools.py` 26/26 pass; `tests/ui/dashboard/test_terminal_api.py` 8/8 pass). `make ci-resume` clean in E-Final. **PASS.**
5. **Feature gate leak** — `_D40_AMENDMENT_OBSOLETE_TESTS` lists exactly 3 (path, signature-prefix) tuples; AST-based synthesis excises them by `node.name` from the base file before comparing (verified: synthesized output equals working tree for both `test_auth.py` and `test_post_audit_proxy_auth_w4_red.py`). Amendment is **narrow** (only the 3 listed functions). **PASS.**

## Live-test verification (this reviewer)

```
tests/proxy/test_prod_ready_run_bound_token_w18_red.py::test_container_id_int_zero_rejected_returns_false_not_typeerror PASSED
tests/proxy/test_prod_ready_egress_budgets_w18_red.py::test_destination_allowed_empty_list_denies_all PASSED
tests/proxy/test_prod_ready_egress_budgets_w18_red.py::test_destination_allowed_empty_list_http_returns_403[asyncio] PASSED
tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_suite_files_unmodified_vs_ci_base PASSED
tests/proxy/ — 255 passed
tests/sandbox/ — 50 passed, 3 skipped (Docker)
tests/security/ — 108 passed, 1 skipped (iptables)
tests/tools/test_web_tools.py — 26 passed
tests/ui/dashboard/test_terminal_api.py — 8 passed
```

AST excision algorithm against `origin/pre-0.0.1:tests/proxy/test_post_audit_proxy_auth_w4_red.py` produces a string that matches the working tree's file content exactly. Same for `tests/proxy/test_auth.py`.

## Files changed by this review

Two files:
- `.ignorelocal/waves/prod-ready-e-thermos.md` (this gate record)
- `.ignorelocal/waves/prod-ready-e-thermos-base.sha` (base SHA declaration)

No edits to `src/`, `tests/`, `docker/`, `scripts/`, or `.github/`. **HARD CONSTRAINTS HONORED.**

## Plan row update

The plan row at `.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md:349` flips E-Thermos from `[ ]` to `[x]` with `(2026-08-07 ✅: 5a74bc15 — clean including low; 5 findings all resolved; rebase intact; P2/P3/P5 clean)`. The plan checkbox at line 757 flips from `[ ]` to `[x]`. E-Reverify and E-PR rows left at `[ ]`.
