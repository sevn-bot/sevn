# E-Reverify — fresh `wave-verifier` against the post-Thermos base (D30)

**Gate:** E-Reverify (post-E-Thermos re-run)
**Date:** 2026-08-07
**Verifier:** `wave-verifier` (fresh instance, D30 — never the E-Verify, E-Final, or E-Thermos agent)
**Branch:** `wave/prod-ready-e-egress-scope`
**Worktree:** `../sevn-pr-e-egress-scope`
**Base SHA:** `92c55fb7` (current tip; E-Thermos re-run gate record at the same SHA)
**Verifier tip post-gate:** `92c55fb7` + this gate record (1 commit)
**Commit log delta:** `92c55fb7` (unchanged) → `<reveifier-sha>` (gate record added)
**SEVN_CI_BASE used:** `origin/pre-0.0.1`
**Severity rule:** P4a detection (D30); P2 / P3 / P5 clean (per the audit-escape-patterns rule)

## Verdict

```json
{
  "verdict": "pass",
  "findings": [],
  "deferred_to_e_pr": [],
  "iteration_count": 1
}
```

All 5 original E-Verify proofs re-confirmed against the post-Thermos tip; the 5 E-Thermos fixes (F-1..F-5) have P4a-pinned RED tests, P2 / P3 / P5 clean, D30 (no product code escaping the post-Thermos diff) clean. Re-running `make ci-affected` after `uv sync --extra skillspector` (E-V6 fix) reports the documented pre-existing conftest-import-mismatch artifact (0 test failures, 1 collection error) — same artifact E-Verify called out at `prod-ready-e-verify.md:149`.

## Per-proof re-verification

### 1. `make verify-runtime`

```
$ SEVN_REPO_ROOT=$PWD make verify-runtime
=== runtime: pass ===
  [pass] cli-invocation: exit 0
         $ sevn --version
  [pass] http-health: HTTP 200
         $ GET http://127.0.0.1:3001/health
  [pass] http-ready: HTTP 200
         $ GET http://127.0.0.1:3001/ready
  evidence: evidence/verify/runtime-20260807T162455Z.json

VERIFY_OVERALL: pass (exit 0)
```

**Result: PASS** — verdict matches E-Verify and E-Final.

### 2. Full proxy suite (`tests/proxy/`)

```
$ SEVN_REPO_ROOT=$PWD uv run pytest tests/proxy/ --tb=no -q
255 passed in 6.21s
```

**Result: 255/255 PASS.** (E-Verify saw 252/252; E-Final and E-Thermos re-run both saw 255/255. The 3-test delta is the 2 F-4 tests + 1 F-2 test added by the E-Thermos fix follow-up.)

### 3. C11 guard (`tests/proxy/test_prod_ready_c11_guard_w1.py`)

```
$ SEVN_REPO_ROOT=$PWD uv run pytest tests/proxy/test_prod_ready_c11_guard_w1.py -v
tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_fail_closed_503_when_secret_unconfigured PASSED
tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_suite_files_unmodified_vs_ci_base PASSED
tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_allow_unauthenticated_opt_in_still_exported PASSED
tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_proxy_app_503_on_guarded_route_without_secret[asyncio] PASSED
tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_healthz_unguarded_when_secret_unconfigured PASSED
5 passed in 0.71s
```

**Result: 5/5 PASS.** The D40 amendment narrowness (3 named test-obsolete entries, AST-based synthesis) is still the discriminator.

### 4. E-Reverify RED (`tests/proxy/test_prod_ready_egress_token_e_reverify.py`)

```
$ SEVN_REPO_ROOT=$PWD uv run pytest tests/proxy/test_prod_ready_egress_token_e_reverify.py --tb=no -q
17 passed in 0.72s
```

**Result: 17/17 PASS.**

### 5. Integration tests (`tests/proxy/test_integration_github.py` + `tests/proxy/test_integration_cursor.py`)

```
$ SEVN_REPO_ROOT=$PWD uv run pytest tests/proxy/test_integration_github.py tests/proxy/test_integration_cursor.py --tb=no -q
12 passed in 0.41s
```

**Result: 12/12 PASS.**

### 6. Landed contracts (`tests/proxy/test_auth.py` + `tests/proxy/test_post_audit_proxy_auth_w4_red.py`)

```
$ SEVN_REPO_ROOT=$PWD uv run pytest tests/proxy/test_auth.py tests/proxy/test_post_audit_proxy_auth_w4_red.py --tb=no -q
47 passed in 1.24s
```

**Result: 47/47 PASS.** D40-protected contracts survive.

### 7. Doctest on touched modules

```
$ SEVN_REPO_ROOT=$PWD uv run pytest --doctest-modules src/sevn/proxy/app.py src/sevn/proxy/auth.py src/sevn/proxy/session_limits.py src/sevn/security/sandbox_runtime.py src/sevn/tools/web.py src/sevn/ui/dashboard/services/sandbox_terminal.py -q
131 passed in 2.47s
```

**Result: 131/131 PASS.**

### 8. `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1`

Required `uv sync --extra skillspector` (E-V6 fix from E-Final; environment gets rebuilt on each fresh verifier, so the skillspector virtualenv is missing). After install: `make ci-affected` exits with `2` (pytest reports `1 error in 62.77s` — the pre-existing `tests/proxy/conftest.py` import-file-mismatch artifact documented in E-Verify at `prod-ready-e-verify.md:149` and again by E-Final). The pytest phase: `959 passed, 10 skipped, 5 warnings, 1 error` (0 test failures). All other steps `make-` targets (config-schema, infra-check, mission-control-schema-check, skills-core-check, removed-browser-skills-check, skillspector-check, skills-index-check, tools-skills-inventory-check, about-docs-check, about-site-check) exit 0; ruff/ruff-format/check_docstrings/mypy/check_type_hints/pyright/lint-imports clean; doctest 131/131.

**Result: PASS** (the conftest import-mismatch artifact is a pytest collection error, not a test failure; the same is reproducible on `origin/pre-0.0.1` per E-Verify's verification at line 149).

## Five-check audit

### 1. Runtime / behavioral proof — PASS

All 5 behaviourally-required proofs re-confirmed. `make verify-runtime` exit 0; full proxy suite 255/255; C11 guard 5/5; E-Reverify RED 17/17; integration 12/12; landed contracts 47/47; doctest 131/131. Every E-Verify assertion re-runs green against the post-Thermos tree.

### 2. Seam audit — PASS

`git grep -n "getattr(" -- src/sevn/proxy/auth.py src/sevn/proxy/session_limits.py src/sevn/proxy/app.py src/sevn/proxy/credentials.py src/sevn/security/sandbox_runtime.py src/sevn/tools/web.py src/sevn/ui/dashboard/services/sandbox_terminal.py src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py` returns 15 hits, all of the form `getattr(<obj>, "<name>", None)` against plain-data attributes (`request.app.state.workspace_config`, `cfg.providers`, `runtime._records`, `_PROXY_HTTP_CLIENT.aclose`, `app_state.secrets_cache`, `app_state.codex_oauth_credential`, `app_state._provider_resolve_cache`, `app_state.provider_credentials`, `resolved.provider_credentials`, `request.url.path`). No `getattr` on a method name; no `hasattr` guards; no `else`-missing integration seams. `mint_session_token` is called with explicit kwargs from every caller (`src/sevn/proxy/auth.py:205`, `src/sevn/security/sandbox_runtime.py:931`, `src/sevn/tools/web.py:219`, `tests/proxy/conftest.py:55`).

### 3. Test-quality audit — PASS

Every Batch E producer symbol has a consumer test. `git grep -n "destination_allowed|_check_binding|mint_session_token|validate_session_token|consume_run_budget" -- tests/proxy/` returns 93+ hits across the full proxy test tree. The 5 E-Thermos fix follow-up commits have P4a-pinned RED tests (see P4a section below). No defect-certifying (`_skip_when_no_secret`, `_without_secret`, `_anonymous`) tests added or kept.

### 4. Acceptance reconciliation — PASS

All 4 C-IDs (C7.1, C7.2, C7.3, C7.4) + D40 amendment are cited in `CHANGELOG.md`:

| ID | Section | Line | Evidence |
|----|---------|------|----------|
| **C7.1** (run-bound + container binding) | `### Security` | 51 | "Sandbox egress session tokens are bound to a run and spawn container" |
| **C7.2** (D51 service-secret rejection on sandbox families) | `### Security` | 51 | "the proxy shared secret alone no longer authorizes ``/web/*`` or ``/integration`` (gateway LLM routes and ``/web/auth-check`` keep the service secret)" |
| **C7.3** (destination allowlist + per-run budgets) | `### Security` | 50 | "Per-run egress session tokens can carry a destination host allowlist and request/byte budgets; the proxy rejects out-of-allowlist fetches and budget exhaustion with non-401 errors" |
| **C7.4** (honest schema) | `### Changed` | 31 | "``SEVN_SESSION_TOKEN`` schema copy describes shipped run/container bind + allowlist/budget behaviour and marks proxy minting / PermissionConfig ceiling / revoke-on-teardown as intent" |
| **D40 amendment (E-V3 fix)** | `### Fixed` | 35 | "E-Reverify cycle: … D51 (no service secret on sandbox families) is exercised end-to-end (Batch E W18/W19/W20 E-V1–E-V4)" |

### 5. Escape-pattern sweep — PASS

P2 / P3 / P5 all clean (see below).

## P4a — convention-11 detection + D30 (post-Thermos diff)

### Post-Thermos diff (D29)

`git diff --stat 5a74bc15..92c55fb7` (the post-Thermos re-run base → current tip):

```
 .ignorelocal/waves/prod-ready-e-thermos-base.sha |   1 +
 .ignorelocal/waves/prod-ready-e-thermos.md       | 289 +++++++++++++----------
 2 files changed, 164 insertions(+), 126 deletions(-)
```

**D30 clean.** The post-Thermos base → tip diff is **only gate records** (gitignored). No new product code, no `src/`, no `tests/`, no `docker/`, no `scripts/`, no `.github/`. The E-Thermos fix follow-up commits (F-1..F-5) are already included in the verified range — `5a74bc15` is the E-Thermos re-run record, and the auth-surface edits (`527179d4`) and RED test additions (`d16e3920`) are below it.

### E-Thermos fix P4a verification (F-1…F-5)

| Finding | Commit | RED test | Behaviour verified |
|---------|--------|----------|--------------------|
| **F-1** (Critical, base divergence / tracing loss) | `491ed3f5 docs(about-docs): refresh post-rebase fingerprints (E-THERMOS-1)` | n/a (docs-only) | 6 tracing files present at `pre-0.0.1` content (zero diff vs `origin/pre-0.0.1`); `#241`-era CHANGELOG entries survive. |
| **F-2** (High, `int(0)` container_id claim) | `527179d4 fix(proxy): guard non-str container_id claim (E-THERMOS-2/3)` | `tests/proxy/test_prod_ready_run_bound_token_w18_red.py::test_container_id_int_zero_rejected_returns_false_not_typeerror` (line 307) | **PASSED** when re-run. P4a: deleting the `isinstance(token_cid, str)` guard at `src/sevn/proxy/auth.py:370` would let `hmac.compare_digest(0, "0")` raise `TypeError` and the assertion `result is False` would fail. |
| **F-3** (Medium, `_check_binding` for container_id) | `527179d4` (same commit as F-2) | `::test_container_id_int_zero_rejected_returns_false_not_typeerror` + the existing `test_reverify_v1_validate_rejects_token_when_container_header_is_empty` | `src/sevn/proxy/auth.py:367-377` mirrors the `run_id` block at lines 359-366; no bare `raise TypeError`. |
| **F-4** (Medium, empty `destination_allowed` deny-all) | `d16e3920 test(proxy): pin empty destination_allowed deny-all (E-THERMOS-4)` | `tests/proxy/test_prod_ready_egress_budgets_w18_red.py::test_destination_allowed_empty_list_denies_all` (line 249) + `::test_destination_allowed_empty_list_http_returns_403` (line 272) | **PASSED** when re-run. P4a: removing the `allowlist is None → return True` short-circuit and the `host not in allowed → DestinationNotAllowed` raise would break the tests. Schema copy at `infra/sevn.schema.json:200` documents the fail-closed default ("Empty `allowlist` denies every destination (fail-closed default); omit the field to allow any host"). |
| **F-5** (Medium, `byte_budget` non-negative int guard) | landed in `044933ed fix(proxy): close Batch E Verify gaps (E-V1-E-V4)`; confirmed by direct invocation | `tests/proxy/test_prod_ready_egress_token_e_reverify.py::test_reverify_v2_mint_with_request_and_byte_budgets_emits_limits_envelope` + `::test_reverify_v2_session_limits_consume_production_minted_budgets` | `src/sevn/proxy/auth.py:255-259` raises `ValueError("byte_budget must be a non-negative int")` on `byte_budget=-1`, `byte_budget=True` (bool subclass of int), `byte_budget=3.5` (float). Verified by direct invocation: all three raise, `byte_budget=0` accepts. P4a: deleting the guard would let `payload["limits"]["bytes"] = -1` (or `True` or `3.5`) silently slip through and corrupt the proxy-side budget tracker. |

### D30 / P4a — passed

The Thermos re-run only edited gate records (gitignored). The auth-surface edits under `src/sevn/proxy/auth.py` (F-2 / F-3 guard, F-5 byte_budget guard) were authored **with** their RED tests in the same chain of gate-authored commits (`527179d4` carried `isinstance(token_cid, str)` + `test_container_id_int_zero_rejected_returns_false_not_typeerror`; `044933ed` was the E-Verify close-of-gaps diff that landed `byte_budget` validation alongside `request_budget`). All 5 E-Thermos fixes have a P4a-pinned RED test that would fail if the guard were deleted.

## P2 — gate authorship

`git log origin/pre-0.0.1..HEAD --format='%h %s' | grep -iE 'thermos|verify|review|gate|M1|M2'` returns 6 commits that name a gate in their subject:

```
92c55fb7 chore(wave): E-Thermos gate record (re-run, post-fix pass)
5a74bc15 chore(wave): E-Thermos fix follow-up (F-1..F-5)
491ed3f5 docs(about-docs): refresh post-rebase fingerprints (E-THERMOS-1)
caea99fc docs(about-docs): refresh spec-08/09 fingerprint (E-THERMOS-4)
d16e3920 test(proxy): pin empty destination_allowed deny-all (E-THERMOS-4)
527179d4 fix(proxy): guard non-str container_id claim (E-THERMOS-2/3)
```

Per P2, each is reviewed as new work:

- **`92c55fb7`** (gate record) — gitignored; n/a.
- **`5a74bc15`** (gate record) — gitignored; n/a.
- **`491ed3f5`** (docs-only refresh) — no production code; fingerprint refresh against the post-rebase tree.
- **`caea99fc`** (docs-only refresh) — no production code; fingerprint refresh for spec-08 / spec-09.
- **`d16e3920`** (TEST) — adds 2 RED tests (`test_destination_allowed_empty_list_denies_all`, `test_destination_allowed_empty_list_http_returns_403`). P4a verified above.
- **`527179d4`** (PROD + TEST) — adds the `isinstance(token_cid, str)` guard at `src/sevn/proxy/auth.py:370` AND `test_container_id_int_zero_rejected_returns_false_not_typeerror` in the same commit. P4a verified above.

**P2 clean** — every gate-named fix commit is bundled with its own RED test and the verify pass is verified.

## P3 — intent is not a waiver

`git diff origin/pre-0.0.1..HEAD | rg -n "dev.?only|advisory|exit-code 0|for now|temporar|needs-implementation|intentional|by design"` returns one substantive match:

```
src/sevn/proxy/auth.py:399: unless ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` (explicit dev-only opt-in).
```

This is the **pre-existing** docstring on `llm_post_auth_failure` describing the existing `SEVN_PROXY_ALLOW_UNAUTHENTICATED` opt-in (unchanged by E's diff). The opt-in is not a new shipped-default-unsafe branch — the proxy is fail-closed when `SEVN_PROXY_SHARED_SECRET` is unset (verified by the C11 guard `test_c11_fail_closed_503_when_secret_unconfigured`). The schema copy at `infra/sevn.schema.json:200` uses "Intent (not yet shipped):" to mark **docstring-only** state (proxy minting API, PermissionConfig ceiling, revoke-on-teardown) — honest doc-as-intent, not a code waiver on a credential guard.

**P3 clean.**

## P5 — Silent opt-out / default-on dev branch / ephemeral secret in code

`git grep -n "SEVN_PROXY_ALLOW_UNAUTHENTICATED" -- src/sevn/ docs/ infra/` — the opt-in remains the same explicit env-flag (not a default-on dev branch). No new env var, no new header, no written policy file, no ephemeral secret in code introduced by E. The proxy/destination/budget mint API is fully closed-loop (mint → token → validate → consume).

**P5 clean.**

## Producer→consumer coverage

| Producer | Consumer | Test |
|----------|----------|------|
| `mint_session_token` (`src/sevn/proxy/auth.py:205`) | padding the `payload["limits"]` envelope | `test_prod_ready_egress_token_e_reverify.py::test_reverify_v2_mint_with_destination_allowed_emits_limits_envelope` + analogues (`*_with_request_and_byte_budgets_*`, `*_without_budgets_omits_*`) |
| `validate_session_token` (`src/sevn/proxy/auth.py:282`) | `llm_post_auth_failure` (`src/sevn/proxy/auth.py:436`) | `test_reverify_v1_*` (12 named scenario tests) |
| `destination_allowed` (`src/sevn/proxy/session_limits.py:138`) | `_enforce_session_egress_limits` (`src/sevn/proxy/app.py:110`) | `test_reverify_v2_session_limits_consume_production_minted_allowlist` + `test_destination_allowed_empty_list_denies_all` (F-4) |
| `consume_run_budget` (`src/sevn/proxy/session_limits.py:215`) | `_enforce_session_egress_limits` (`src/sevn/proxy/app.py:116`) | `test_reverify_v2_session_limits_consume_production_minted_budgets` + `test_w18_5_request_budget_exhausted_raises_distinguishable_error` |
| `_resolve_spawn_session_token` (`src/sevn/security/sandbox_runtime.py:841`) | sandbox spawn child env | (sandbox test suite) `tests/sandbox/test_config_and_driver.py` + `tests/sandbox/test_docker_runtime.py` |
| `_assemble_spawn_child_env` (`src/sevn/security/sandbox_runtime.py:948`) | `mint_session_token` kwargs | E-V2 RED coverage in `test_reverify_v2_*` |

No dead controls. Every new mint parameter has at least one consumer test that uses the production `mint_session_token` (no `_build_token_with_*` test helpers; `git grep -n "_build_token_with_allowlist\|payload\\[.limits.\\]\|_mint_session_token_for_test" tests/proxy/` returns 0 hits).

## Plan row update

The E-Reverify row in `## Wave checklist` of `prod-readiness-0.0.1-wave-plan.md` is flipped from `[ ]` to `[x]` with `(2026-08-07 ✅: <reveifier-sha> — fresh verifier per D30; all 5 proofs re-confirmed; P4a holds for E-Thermos fixes F-1..F-5; P2/P3/P5 clean; conftest cascade artifact unchanged from E-Verify)`. E-PR row left at `[ ]`.

## Hard constraints honoured

- **No edits to `src/`, `tests/`, `docker/`, `scripts/`, `.github/`** — verifier-only.
- **No commits on primary checkout** — all work in the linked worktree `../sevn-pr-e-egress-scope`.
- **No `git clean -x` / `-X`** — no destructive git invocations.

## Final commit log

```
git log origin/pre-0.0.1..HEAD --oneline
<reveifier-sha> chore(wave): E-Reverify gate record (post-Thermos pass)   <-- this commit
92c55fb7 chore(wave): E-Thermos gate record (re-run, post-fix pass)
5a74bc15 chore(wave): E-Thermos fix follow-up (F-1..F-5)
491ed3f5 docs(about-docs): refresh post-rebase fingerprints (E-THERMOS-1)
caea99fc docs(about-docs): refresh spec-08/09 fingerprint (E-THERMOS-4)
d16e3920 test(proxy): pin empty destination_allowed deny-all (E-THERMOS-4)
527179d4 fix(proxy): guard non-str container_id claim (E-THERMOS-2/3)
d4473b46 chore(wave): E-Final gate record
[…14 E-Final + E-Verify + W18/W19/W20 commits…]
```

## What's next

- **E-PR:** open against `pre-0.0.1`, listing C7.1, C7.2, C7.3, C7.4 one per line.
