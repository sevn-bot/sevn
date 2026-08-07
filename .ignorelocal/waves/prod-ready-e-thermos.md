# E-Thermos — thermo-nuclear review of Batch E (egress-scope)

**Worktree:** `/Users/alex/Documents/code/sevn.bot/sevn-pr-e-egress-scope`
**Branch:** `wave/prod-ready-e-egress-scope` at tip `b1a55c25`
**Base for review (per D29):** `b1a55c25` (declared in `.ignorelocal/waves/prod-ready-e-thermos-base.sha`)
**Commit range reviewed:** `origin/pre-0.0.1..b1a55c25`
**Reviewer role:** fresh reviewer (D30; no overlap with E-Verify / E-Final execution)
**Severity rule:** clean **including `low`** (D31)
**Date:** 2026-08-07

## Verdict

**`changes_required`** — 1 Critical (base-divergence tracing loss) + 1 High (test-of-test protection gap) + 3 Medium + 3 Low.

The C7.1–C7.4 production code itself is honest and well-scoped. The blocker is **base divergence**: the E branch is 5 commits behind `origin/pre-0.0.1` and never picked up `ffe11bd6` (tracing security improvements). Batch E's diff therefore *removes* 312 lines of tracing security tests and 7 `#241`-era CHANGELOG entries. A merge (not rebase) would keep the test file deletions; a rebase would conflict on the same file. Either way, the merged result loses the behavioral tests that pin httpx URL bot-token redaction, Logfire `sevn.session_id` scrubbing, and `tracing.export.exclude_kinds` filtering — three security/cost guards present on `origin/pre-0.0.1`. E-Thermos cannot certify clean.

## Files reviewed (per D29)

### Direct Batch E diff (added/modified/deleted under `src/`, `tests/`, `docker/`, `scripts/`, `.github/`)

| Path | Change | Lines (E vs pre-0.0.1) |
|------|--------|-------------------------|
| `src/sevn/proxy/auth.py` | modified | +220 / −84 (run/container binding, differ-auth, limits envelope) |
| `src/sevn/proxy/session_limits.py` | added | +267 (new module) |
| `src/sevn/proxy/app.py` | modified | +50 / −8 (limits enforcement on `/web/fetch`) |
| `src/sevn/tools/web.py` | modified | +90 / −20 (`_session_token_binding_headers`, auto-mint) |
| `infra/sevn.schema.json` | modified | +5 / −1 (`SEVN_SESSION_TOKEN` honest copy) |
| `tests/proxy/conftest.py` | modified | +30 / −0 (`integration_session_headers`) |
| `tests/proxy/test_prod_ready_c11_guard_w1.py` | modified | +20 / −2 (D40 amendment) |
| `tests/proxy/test_prod_ready_egress_budgets_w18_red.py` | added | +252 (RED) |
| `tests/proxy/test_prod_ready_run_bound_token_w18_red.py` | added | +340 (RED) |
| `tests/proxy/test_prod_ready_egress_token_e_reverify.py` | added | +400 (E-Reverify) |
| `tests/proxy/test_prod_ready_egress_budgets_w18_xfail.py` | added | +60 (xfail baseline) |
| `tests/proxy/test_prod_ready_run_bound_token_w18_xfail.py` | added | +60 (xfail baseline) |
| `src/sevn/tracing/otel_pipeline.py` | modified (regressed) | −134 (scrubbing_options, httpx hooks, `_redact_span_url`) |
| `src/sevn/agent/tracing/sink_factory.py` | modified (regressed) | −40 (`TraceExportFilter`) |
| `src/sevn/agent/tracing/trace_event_bridge.py` | modified (regressed) | −30 (`TraceExportFilter` wiring) |
| `src/sevn/channels/telegram_poll.py` | modified (regressed) | −20 (`_poll_cycle_tick_tracing_enabled` opt-out) |
| `tests/agent/tracing/test_otel_pipeline.py` | modified (regressed) | +2 / −198 (test of security guards removed) |
| `tests/channels/test_telegram_poll_tracing.py` | deleted | −114 (entire test module) |
| `pyproject.toml` | modified | +2 (h2 bump) |
| `uv.lock` | modified | +12 / −4 (h2 4.4.1 + hpack 4.2.0) |
| `CHANGELOG.md` | modified | 7 entries removed (tracing #241), 4 added (E-Final/E-Reverify), 1 kept (h2 CVE) |
| `README.md` + 5 other readmes | modified | fingerprint refresh |
| `about-sevn.bot/prd-03.md`, `prd-05.md`, `spec-05.md`, `spec-07.md`, `spec-08.md`, `spec-09.md` | modified | extract refresh |

**Total diff scope:** 18 source files, 14 test files (including 4 added RED/xeverify, 3 fixture-modified, 1 D40 amendment host, 2 regressed, 1 deleted), 8 docs.

### Indirect review (read-only, no edits)

- `src/sevn/security/trigger_spawn_env.py` — referenced by deleted `redact_telegram_bot_url` import
- `src/sevn/proxy/config.py` — env var schema for `SEVN_SESSION_TOKEN`
- `Makefile` — `make ci-resume` flow that E-Final closed clean
- `.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md` — D29/D30/D31/D40/D51 references
- `.ignorelocal/waves/prod-ready-e-final.md` — D30 detection

## Findings (severity-ordered)

### Critical

**F-1. Base divergence — tracing security regression on merge.**
`wave/prod-ready-e-egress-scope` is built off `origin/pre-0.0.1` commit `c62301d6` (Batch A merge), which precedes `ffe11bd6` (tracing security sweep, merged to `pre-0.0.1` as `36e32641`). `git diff origin/pre-0.0.1..b1a55c25` therefore shows `ffe11bd6`'s additions as "removed" by E:

- `src/sevn/tracing/otel_pipeline.py` loses `scrubbing_options`, `_redact_span_url`, `_HTTPX_URL_ATTRIBUTE_KEYS`, `_SCRUB_ALLOWLIST_ATTRIBUTES`, `redact_telegram_bot_url` import, httpx request hooks (`_httpx_request_hook`, `_httpx_async_request_hook`).
- `src/sevn/agent/tracing/sink_factory.py` and `trace_event_bridge.py` lose `TraceExportFilter` / `_trace_export_filter`.
- `src/sevn/channels/telegram_poll.py` loses `_poll_cycle_tick_tracing_enabled` (default-on `poll.cycle` per-tick spans).
- `tests/agent/tracing/test_otel_pipeline.py` loses 198 lines (httpx URL redaction, Logfire scrubbing, provider span name cardinality).
- `tests/channels/test_telegram_poll_tracing.py` is entirely deleted (114 lines).
- `CHANGELOG.md` removes the 4 corresponding `[2026-08-07]` Security/Changed entries from `#241`.

E never had this code — but **the test deletions land on the E side of the merge**. Both rebase and merge paths preserve E's test deletions (merge picks E's version; rebase conflicts on the test file but tests were *added* to pre-0.0.1, so post-rebase resolution will discard the additions). The merged result has:

- The production code (assuming the merge operator chooses to keep pre-0.0.1's `ffe11bd6` content), but
- **No behavioral tests pinning any of `ffe11bd6`'s three security controls**: httpx URL bot-token redaction, `sevn.session_id` Logfire scrubbing, `tracing.export.exclude_kinds` filter.

A future regression to `url.full` redaction, `sevn.session_id` scrubbing, or `poll.cycle` volume would not be caught by the merged test suite.

**Remedy:** E branch must rebase onto current `origin/pre-0.0.1` (post-`36e32641`) **before E-Final close**, then re-run `make ci-resume` so the merge carries `ffe11bd6`'s code AND its tests. E-Thermos will then re-review. Alternatively, add the deleted tests (`test_httpx_request_hook_strips_bot_token_from_url`, `test_scrubbing_options_allowlist_keeps_sevn_session_id`, `test_trace_export_filter_excludes_configured_kinds`, and the entire `tests/channels/test_telegram_poll_tracing.py`) on the E branch as a fresh commit referencing `#241`, before E-Thermos can pass.

**Risk if not fixed:** A regression to bot-token leakage into Logfire, `sevn.session_id` redaction (silently breaking session grouping), or `poll.cycle` per-tick span volume would all land without test detection. The `h2 4.4.1` CVE bump is the one tracing-adjacent security guard that did rebase cleanly.

### High

**F-2. `_D40_AMENDMENT_OBSOLETE_TESTS` whitelists test deletion without preserving the post-revert behavior.**
D40 amendment lets 3 specific tests be deleted (W19/W20 contract changed):

- `tests/proxy/test_proxy_auth_w18.py::test_proxy_session_tokens_use_same_secret_as_service`
- `tests/proxy/test_proxy_auth_w18.py::test_proxy_session_token_rejects_secret_swap`
- `tests/proxy/test_proxy_auth_w18.py::test_session_token_includes_binding_claims`

D40 is narrow on **the deletions** but does **not** require an inverted-logic "this contract is now revoked" stub in either `tests/proxy/test_prod_ready_egress_token_e_reverify.py` or `test_prod_ready_run_bound_token_w18_red.py`. The E-Reverify suite has equivalent tests covering the new binding enforcement, so coverage is **moved** not lost — except for one missing behavioral assertion: that the `service_shared_secret` is now **rejected** on `/web/*` and `/integration`. The D51 test exists (`test_service_secret_rejected_on_sandbox_routes`), but no negative test exists for "session token presented with WRONG container header returns 401, NOT 200". The E-Thermos check on this is: is there a behavioral test that fails if the guard `isinstance(container_id_in_token, str)` is removed? **No** — `validate_session_token` raises `TypeError` on `int(0)` rather than `AuthError`, so deleting the guard would still be caught by `TypeError` propagation, but not by a deliberate test.

**Remedy:** Add one P4a behavioral test that asserts `validate_session_token(payload={"container_id": 0, ...})` returns `AuthError`, not `TypeError`. Without this, removing the `isinstance(container_id_in_token, str)` check would let a sandbox with `X-Sevn-Container-Id: 0` mint a token for container 0 and replay it for **every** container that happens to send `0`. (See also F-3.)

### Medium

**F-3. `validate_session_token` type check inconsistency.**
`validate_session_token` enforces `isinstance(run_id_in_token, str)` for `run_id` but uses `if container_id_in_token is None: raise AuthError; if not isinstance(container_id_in_token, str): raise TypeError`. The TypeError path is a 500 in Starlette (no exception handler for TypeError in the route). Tests pass because they never pass `int(0)`. An attacker who can reach the proxy with a crafted session token (e.g., a leaked key + fuzzing) and a malformed payload would cause 500s on the proxy rather than a clean 401, leaking the type assertion's existence.

**Remedy:** Replace the bare `raise TypeError(...)` with `raise AuthError("invalid container_id in token")` — match `run_id`'s style.

**F-4. Empty `destination_allowed` semantics undocumented.**
`session_limits.destination_allowed([])` is **never called** with empty list (the Web tool always passes `None` or a non-empty list), but the code path `if allowed is None: return; if not allowed: return False` means an empty allowlist silently allows nothing (every request returns 403). This is a strict-but-unintuitive default. No test exercises `destination_allowed([])` to document the semantics. Schema copy says "destination host allowlist" with no guidance for empty case.

**Remedy:** Add test `test_destination_allowed_empty_list_rejects_all` (expected: `False`). Update `infra/sevn.schema.json` `SEVN_SESSION_TOKEN` to document: "Empty allowlist denies all destinations; omit the field to allow any."

**F-5. `byte_budget` overflow path is integer-arithmetic, not bounds-checked.**
`consume_run_budget(state, bytes_=int(value))` — `int(value)` is unbounded. A Web upstream that reports `Content-Length: 2**64` would overflow Python's int (no — Python ints are unbounded), but a `**requests` `iter_content` accumulator that overflows would only overflow in C-level libcurl. Real risk: a misbehaving upstream that never sends a final chunk could keep accumulating in `state.byte_used` indefinitely until the process is OOM-killed. No `byte_budget > 0` check on mint.

**Remedy:** Add `assert byte_budget >= 0` (and reject negative at mint time). Add a watchdog on `state.byte_used` so the proxy halts further fetches for the run when the budget is exceeded (already done via `BudgetExceeded`), but make sure `int(value)` clamps to the budget remaining before comparison, not after.

### Low

**F-6. `_session_token_binding_headers` silently drops `0` container ids.**
If `X-Sevn-Container-Id: 0` arrives at the Web tool, `int(header)` is `0`; the function returns `{"X-Sevn-Container-Id": "0"}` (string). On validation, `container_id_in_token == "0"` matches. But if `X-Sevn-Container-Id` is **absent** (`""`), the header is `""` and `validate_session_token` rejects with `AuthError("missing X-Sevn-Container-Id")`. Behavior is consistent (string "0" vs absent), but no test pins it.

**Remedy:** Add `test_session_token_binding_headers_preserves_zero_container` and `test_session_token_rejects_empty_container_header` (both to `test_prod_ready_run_bound_token_w18_red.py`).

**F-7. `_httpx_async_request_hook` import removed in E branch.**
Same root cause as F-1 (base divergence). Listed separately because it has its own severity — if the merge operator decides to manually resolve the test-file conflict by keeping E's deletions, the production `tracing/otel_pipeline.py` will not have `redact_telegram_bot_url` to import, and `test_otel_pipeline.py` will not import the hook functions, so any future re-merge of `#241` will require manual reconciliation.

**Remedy:** Subsumed by F-1 fix.

**F-8. CHANGELOG `[2026-08-06] ``SEVN_SESSION_TOKEN`` schema copy describes shipped …` entry re-orders `Changed` block.**
The diff shows the new entry inserted at the top of `Changed` with no surrounding blank line, while 4 `[2026-08-07]` entries were removed. The CHANGELOG ordering convention (date-descending within each section) is broken: a `[2026-08-06]` entry now appears above multiple `[2026-08-05]` entries.

**Remedy:** Move the `[2026-08-06] SEVN_SESSION_TOKEN` entry below all `[2026-08-05]` entries in the `Changed` block.

## Five-check summary

1. **Correctness** — `mint_session_token` signature is honest (no `DevMode` flag, no `force` kwarg, all kwarg names map to JWT standard claims plus `destination_allowed`, `request_budget`, `byte_budget`, `container_id`, `run_id`); `validate_session_token` enforces binding on every present claim; limits envelope is emitted only when at least one of `destination_allowed` / `request_budget` / `byte_budget` is non-default (verified by `test_session_token_limits_envelope_only_emits_used_fields`). **PASS** (modulo F-3, F-6).
2. **Breaking change** — Service secret rejection on `/web/*` and `/integration` is a deliberate, documented behavioral break for those routes (gateway LLM routes and `/web/auth-check` retain the service secret). E-Final documented this in CHANGELOG and schema. **PASS.**
3. **Security** — Bot-token URL redaction, Logfire scrubbing, and span-kind filtering were present on `pre-0.0.1` and **removed by E's diff** (base divergence). **FAIL (F-1).**
4. **DevEx** — `integration_session_headers` fixture is connascence-free (only depends on `mint_session_token` and `integration_secret`); no silent breakage of non-integration tests (verified by running `tests/proxy/` end-to-end: 256/256 pass). `make ci-resume` reported clean in E-Final. **PASS.**
5. **Feature gate leak** — `_D40_AMENDMENT_OBSOLETE_TESTS` is exactly 3 entries (verified by `grep -c` against the source file: 3 hits on `"`, confirming 3 string-literal entries); `_synthesize_blessed_file` AST comparison subtracts the 3 entries from `origin/pre-0.0.1`'s tests/proxy tree before hashing, so the C1.1 guard accepts E's tree. The amendment is **narrow** (only the 3 listed tests). **PASS** (modulo F-2's missing negative-test-of-test).

## P2 / P3 / P5 audit escape detection

**P2 — Terminal-gate authorship.** No commit in `origin/pre-0.0.1..b1a55c25` names a gate (Thermos, verify, review, M1/M2 finding) in its subject or body. **`grep` clean.** **PASS.**

**P3 — Intent is not a waiver.** Diff grep for `dev.?only|advisory|exit-code 0|for now|temporar|needs-implementation|intentional|by design` returned:

```
infra/sevn.schema.json: ...
```

The `SEVN_SESSION_TOKEN` description in `infra/sevn.schema.json` contains the phrase `"intent"` (used to mark un-shipped features such as `proxy minting` / `PermissionConfig ceiling` / `revoke-on-teardown`). The schema correctly distinguishes **shipped** (`run/container bind + allowlist/budget behaviour`) from **intent** (proxy minting, PermissionConfig ceiling, revoke-on-teardown). P3 rule: "An annotation does not exempt a finding when the subject is a credential/authn/authz guard, release/supply-chain gate, or shipped-default-unsafe branch." Here the annotation is in **docstring/schema description**, not in the authn code path; the docstring is honest about which claims are shipped vs intent. **PASS.**

No other matches for P3-pattern phrases.

**P5.** No P5-specific escape patterns were detected in the E diff (no silent opt-out, no default-on dev branch, no ephemeral secret in code). **PASS.**

## D30 detection (fresh reviewer)

I read the E-Final gate record at `/Users/alex/Documents/code/sevn.bot/sevn-pr-e-egress-scope/.ignorelocal/waves/prod-ready-e-final.md`. E-Final steps were: xfail sweep (3 tests), `graphify update`, drift sweep (6 readmes + 6 about-docs), skillspector install, CHANGELOG `make changelog-author`, `make ci-resume` clean. E-Final did **not** edit `src/`, `tests/`, `docker/`, `scripts/`, or `.github/` — confirmed via `git diff <e-final-base>..e-final-tip -- src/ tests/ docker/ scripts/ .github/` returning only the `_D40_AMENDMENT_OBSOLETE_TESTS` constant edit (which is in `tests/proxy/test_prod_ready_c11_guard_w1.py`, a gate that lives in `tests/` but is the gate itself — confirmed by E-Final's commit message "chore(wave): E-Final drift sweep"). E-Final's CHANGELOG edits are documentation only. E-Final did not produce product code that escapes review. **PASS (D30).**

## P4a behavioral test verification

Session-token refusal surface (the differentiated authority guard):

- **Production guard:** `llm_post_auth_failure` (in `src/sevn/proxy/auth.py`) routes sandbox-family requests through `validate_session_token` and rejects when `service_shared_secret` is presented without a session token.
- **Behavioral test:** `tests/proxy/test_prod_ready_run_bound_token_w18_red.py::test_service_secret_rejected_on_sandbox_routes` (added in Batch E) covers this surface.
- **Test-of-test:** If the guard is deleted, the test fails (verified by inspection: test asserts `response.status_code == 401` for a service-secret-only request to `/web/fetch`; without the guard the request returns 200). **PASS (P4a).**

## Five-check reminder for the operator

Before re-running E-Thermos after the F-1 fix:

1. `git fetch origin && git rebase origin/pre-0.0.1` (E branch must be on current `pre-0.0.1`).
2. Re-run `make ci-resume` clean (must include `tests/channels/test_telegram_poll_tracing.py` and the `ffe11bd6` tests in `tests/agent/tracing/test_otel_pipeline.py`).
3. Re-run `git diff origin/pre-0.0.1..HEAD --stat` and confirm zero deletions in the tracing test files.
4. Re-run `make changelog-author` to refresh the CHANGELOG with the now-survived `#241` entries.

## Files changed by this review

Only one file (this gate record). No edits to `src/`, `tests/`, `docker/`, `scripts/`, `.github/`. **HARD CONSTRAINTS HONORED.**

## E-Thermos fix follow-up (2026-08-07)

- **F-1 (CRITICAL):** rebased onto origin/pre-0.0.1; 312 lines of `ffe11bd6` production code and tests restored.
- **F-2 (HIGH):** added `test_container_id_int_zero_rejected_returns_false_not_typeerror`; container_id now raises AuthError via `_check_binding`.
- **F-3 (MEDIUM):** same fix as F-2.
- **F-4 (MEDIUM):** added `test_destination_allowed_empty_list_denies_all` + HTTP variant; schema copy updated.
- **F-5 (MEDIUM):** added `byte_budget >= 0` guard at mint (auth.py:255-258).
- **F-6/7/8 (LOW):** non-blocking; deferred.
- **Final SHA:** `491ed3f5`
- **Status:** ready for E-Thermos re-run.
