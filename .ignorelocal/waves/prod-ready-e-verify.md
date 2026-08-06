# Batch E Verify gate record (E-Verify)

**Date:** 2026-08-06
**Worktree:** `../sevn-pr-e-egress-scope`
**Branch:** `wave/prod-ready-e-egress-scope`
**Tip SHA:** `4f82db6c`
**Base:** `origin/pre-0.0.1`
**Verifier:** wave-verifier (E-Verify)

## Verdict

```json
{
  "verdict": "changes_required",
  "findings": [
    {
      "id": "E-V1",
      "severity": "high",
      "file": "src/sevn/proxy/auth.py:277-283",
      "summary": "Run/container binding is optional at the request seam.",
      "evidence": "A real probe supplied a valid token with no X-Sevn-Run-Id or X-Sevn-Container-Id and llm_post_auth_failure returned None. validate_session_token only checks a binding when the corresponding argument is non-None, and accepts a token with no container_id claim when a container header is supplied. Require the expected request bindings and reject missing claims/headers on sandbox authority paths; add a RED behavioral test for missing binding headers and unbound tokens."
    },
    {
      "id": "E-V2",
      "severity": "high",
      "file": "src/sevn/proxy/auth.py:169-208",
      "summary": "The production mint API cannot issue C7.3 allowlist or budget claims.",
      "evidence": "The mint payload contains only scope, exp, run_id, and optional container_id. The W20 tests construct allowlist/max_requests/max_bytes claims with private test-only token builders, so the proxy enforcement code is exercised but the shipped producer cannot create a limited token. Add typed mint parameters and production spawn/gateway propagation for those claims, with behavioral producer-to-consumer coverage."
    },
    {
      "id": "E-V3",
      "severity": "high",
      "file": "tests/proxy/test_auth.py:85-94",
      "summary": "The landed C1.1 regression suite was modified in scope.",
      "evidence": "git diff origin/pre-0.0.1...HEAD -- tests/proxy/test_auth.py tests/proxy/test_post_audit_proxy_auth_w4_red.py is non-empty. tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_suite_files_unmodified_vs_ci_base fails on this exact diff. Restore the landed suite unmodified and place D51 coverage only in the Batch E RED suite or otherwise obtain the required test-creator reconciliation without changing the landed contract file."
    },
    {
      "id": "E-V4",
      "severity": "high",
      "file": "tests/proxy/test_integration_github.py:49,93,142,164,181; tests/proxy/test_integration_cursor.py:46,93,166",
      "summary": "Affected CI is red because existing integration callers still present only the service secret on /integration.",
      "evidence": "The full affected pytest phase reports 15 failures; these integration tests receive HTTP 401 where they expect provider validation or a forwarded response. C7.2 intentionally rejects the service secret on /integration, so reconcile these callers/tests to use a valid sandbox session token while preserving the new authority distinction."
    },
    {
      "id": "E-V5",
      "severity": "medium",
      "file": "docs/readmes/_fingerprints.json; about-sevn.bot/prd/05-cost-and-providers.md; about-sevn.bot/specs/05-llm-transports.md; about-sevn.bot/specs/07-egress-proxy.md",
      "summary": "Required drift checks fail on stale fingerprints.",
      "evidence": "make readme-check exits 2 for tools, skills, ui-mission-control, and config-workspace fingerprints. make about-docs-check exits 2 for prd-05-cost-and-providers, spec-05-llm-transports, and spec-07-egress-proxy. Refresh only the affected generated drift artifacts in the appropriate final/drift step."
    },
    {
      "id": "E-V6",
      "severity": "medium",
      "file": "Makefile:ci-affected / scripts/check_skillspector.py",
      "summary": "make ci-affected does not exit 0 in this worktree.",
      "evidence": "The affected gate exits 2 after 15 pytest failures and also reports skillspector-check: SkillSpector CLI not found. Install the declared skillspector extra or otherwise make the canonical environment available, then rerun SEVN_CI_BASE=origin/pre-0.0.1 make ci-affected."
    }
  ]
}
```

## D36 gate confirmation

**PASS.** `git rev-list --left-right --count origin/pre-0.0.1...HEAD` → `0 4`. The branch log contains the merged Batch A commit `c62301d6` and it is an ancestor of the E tip. The E rebase dependency is satisfied.

## Runtime proof

| Required surface | Result | Evidence |
|---|---|---|
| `make verify-runtime` | **PASS for its registered driver** | `VERIFY_OVERALL: pass (exit 0)`; `evidence/verify/runtime-20260806T215350Z.json`; `sevn --version` exit 0, gateway `/health` 200, `/ready` 200 with proxy ok |
| Run-bound token accepted for own run / rejected for another | **NOT proven against a real proxy** | Behavioral ASGI tests pass in `tests/proxy/test_prod_ready_run_bound_token_w18_red.py`; the registered runtime driver only probes gateway health/readiness |
| Token replay from another container rejected | **NOT proven against a real proxy** | Behavioral ASGI test passes; no deployment driver exercises this path |
| Service secret rejected on sandbox family | **NOT proven against a real proxy** | Behavioral auth and ASGI tests pass for `/web/fetch` and `/integration`; `/llm/*` and `/web/auth-check` service-secret keep-allow tests pass |
| Out-of-allowlist destination rejected | **NOT proven against a real proxy** | Behavioral ASGI test passes with 403/allowlist detail; no real-proxy driver |
| Budget exhaustion distinguished from 401 | **NOT proven against a real proxy** | Behavioral ASGI test passes with 429 and budget detail; request and byte unit tests pass |
| Expiry/scope rejects | **PASS in focused behavioral suites** | Expired, forged-signature, and wrong-route-family tests pass |

The mandated `make verify-runtime` command is green, but its current driver is limited to CLI plus `/health` and `/ready`; it does not satisfy the requested real-proxy egress scenarios by itself.

## P4a test-quality confirmations

| Guard | Result | Evidence |
|---|---|---|
| Run-id mismatch rejects | **PASS behaviorally** | `test_w18_1_validate_rejects_token_when_request_run_id_mismatches` and HTTP foreign-run test pass; deletion of the comparison would fail these assertions |
| Container replay mismatch rejects | **PASS for supplied headers** | `test_w18_2_validate_rejects_token_from_different_container` and HTTP replay test pass; deletion of the mismatch comparison would fail |
| Service secret rejected on sandbox families | **PASS** | W18.3 unit/HTTP tests and updated web-prefix test pass; deletion of the sandbox-family rejection would fail |
| Destination allowlist | **PASS for test-constructed claims** | W18.4 direct and HTTP tests pass; deletion of `destination_allowed` enforcement would fail |
| Budget exhaustion → 429/distinguishable | **PASS for test-constructed claims** | W18.5 request, byte, HTTP, and concurrent tests pass; deletion of budget enforcement would fail |

P4a is incomplete for the production producer because the tests mint W20 claims with private builders rather than `mint_session_token`; see E-V2.

## Landed contracts

- `tests/proxy/test_auth.py`: **27 passed**, but **modified in scope** (8 additions / 4 deletions); therefore the unmodified-contract requirement fails.
- `tests/proxy/test_post_audit_proxy_auth_w4_red.py`: **23 passed**, unmodified.
- Combined focused landed-contract count: **50 passed**.
- The affected CI immutability guard also fails at `tests/proxy/test_prod_ready_c11_guard_w1.py:103`.

## CI and drift gates

- `SEVN_CI_BASE=origin/pre-0.0.1 make ci-affected`: **exit 2**. Pytest phase: **15 failed, 928 passed, 10 skipped**; later checks also report missing SkillSpector CLI and stale about-docs fingerprints.
- `make readme-check`: **exit 2** — stale fingerprints for `tools`, `skills`, `ui-mission-control`, and `config-workspace`.
- `make about-docs-check`: **exit 2** — stale fingerprints for `prd-05-cost-and-providers`, `spec-05-llm-transports`, and `spec-07-egress-proxy`.
- Focused E suites: **73 passed** across the two W18 RED suites and schema suite.
- `make verify-runtime`: **`VERIFY_OVERALL: pass (exit 0)`**.

## Producer → consumer grep

```text
git grep -n "validate_session_token|consume_run_budget|session_limits|destination_allowed|X-Sevn-Run-Id" -- src/ tests/
src/sevn/proxy/app.py:68-72 imports session limit consumers
src/sevn/proxy/app.py:83-121 enforces allowlist and budgets for /web/fetch
src/sevn/proxy/auth.py:211-283 validates signature, expiry, scope, and optional bindings
src/sevn/proxy/auth.py:341-347 passes X-Sevn-Run-Id and X-Sevn-Container-Id into validation
src/sevn/security/sandbox_runtime.py:900-907 validates an existing sandbox token
src/sevn/tools/web.py:130-171 derives binding headers from token payload
src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py:120 propagates X-Sevn-Run-Id

git grep -n "SEVN_SESSION_TOKEN" -- infra/ src/
infra/sevn.schema.json:197-200 documents the shipped session-token contract
src/sevn/security/sandbox_runtime.py:803-834 emits the session token and excludes the service secret
src/sevn/security/sandbox_runtime.py:964-982 assembles the child environment
src/sevn/tools/web.py:214-226 sends session and binding headers
```

Producer/consumer wiring exists for the enforcement functions and child environment, but the production mint producer does not expose W20 claim inputs (E-V2), and request bindings are optional at the auth seam (E-V1).

## Five-check summary

1. **Runtime / behavioral proof: changes required.** `make verify-runtime` passes only health/readiness; requested real-proxy egress scenarios were not exercised by the registered deployment driver.
2. **Seam audit: changes required.** Auth bindings are optional/missing-header permissive; production minting has no allowlist/budget parameters. No new `getattr(..., None)` integration seam was found in the E auth/limits path.
3. **Test-quality audit: changes required.** The five guard assertions are behavioral and pass, but W20 tests use private test token constructors rather than the production mint API; the landed `test_auth.py` contract was edited, and affected CI has unrelated integration callers that now fail under D51.
4. **Acceptance reconciliation: changes required.** Health/readiness runtime evidence exists, but no registered real-proxy driver covers the five requested egress scenarios; affected CI and both drift checks fail.
5. **Escape-pattern sweep: changes required.** P5 consumers exist for allowlist/budget enforcement and session-token headers. P6 has no relevant process teardown sibling in this scope. P2 is clean: the four in-scope commits are implementation/RED/reconciliation commits and none is authored by Thermos, Verify, Review, or a gate-finding fixer.

## Test reconciliation status

`tests/proxy/test_auth.py::test_llm_post_auth_failure_guarded_web_prefix` was reconciled to expect service-secret rejection on `/web/fetch`, and it passes. However, that reconciliation violates the landed-contract-unmodified requirement and the broader `/integration` test callers remain stale, so test-creator follow-up is still required.

## Required remedy before E-Verify can pass

Resolve E-V1 through E-V6, then rerun the full E-Verify checklist. In particular, restore the landed auth suite unchanged, make all affected `/integration` behavioral tests use the correct sandbox credential, expose/propagate production allowlist and budget claims, require binding headers/claims at the sandbox auth boundary, refresh drift artifacts, install the CI-required SkillSpector dependency, and provide real-proxy evidence for each requested runtime scenario.
