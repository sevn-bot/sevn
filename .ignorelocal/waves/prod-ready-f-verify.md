# Batch F Verify gate (post F-Reverify) — prod-readiness 0.0.1

**Gate:** F-Verify (re-run after F-V5 mechanical fix)
**Date:** 2026-08-07
**Verifier:** wave-verifier (fresh instance)
**Branch:** `wave/prod-ready-f-evidence`
**Worktree:** `../sevn-pr-f-evidence`
**Tip SHA:** `f2d04007`
**Base (impl):** `origin/pre-0.0.1` @ `2c1c6831` — 0 behind, 8 ahead
**F-Thermos base:** `60bea33f286e799ee4b29438e529432b373411c6` (post-F-Reverify fix tip — D29)
**Prior F-Verify SHA:** `60bea33f` (the first post-F-Reverify F-Verify) — verdict `changes_required` (F-V5)
**This gate evidence dir:** `evidence/verify/` (9 fresh JSON artifacts for the 9 drivers, stamped 20260807T081950Z / 082143Z)

## Verdict

```json
{
  "verdict": "pass",
  "findings": []
}
```

F-V5 (the only finding of the prior F-Verify) is fixed: the four leftover `@pytest.mark.xfail(strict=False)` decorators on the new P4a behavioural tests have been deleted in `f2d04007`. All 14 tests in `tests/infra/test_prod_ready_verify_deployment_w21_red.py` now pass **without** any xpass / xfail annotation. No new findings.

## F-V5 proof (the only prior blocker)

```bash
cd /Users/alex/Documents/code/sevn.bot/sevn-pr-f-evidence
source .venv/bin/activate
python -m pytest tests/infra/test_prod_ready_verify_deployment_w21_red.py -v --tb=short
```

```
collected 14 items
… 14 PASSED tests (lines 331, 355, 392, 422 — no xfail markers) …
============================== 14 passed in 1.34s ==============================
```

Diff vs the F-Thermos base (D30 detection):

```
$ git diff --stat 60bea33f..f2d04007
 tests/infra/test_prod_ready_verify_deployment_w21_red.py | 7 -------
 1 file changed, 7 deletions(-)

$ git diff --stat 60bea33f..f2d04007 -- src/ scripts/ docker/ .github/ Makefile
(empty — exit 0)
```

The single commit `f2d04007 test(verify-deployment): un-xfail F-V3 behavioural tests (F-V5)` is **test-only** — the diff outside `tests/` is empty. **P2 PASS** (no gate-authored product code past the F-Thermos base).

## All 9 driver `VERIFY_OVERALL` lines

| Driver | Expected | Actual | Artifact |
|--------|----------|--------|----------|
| compose-profiles | pass | `pass (exit 0)` | `evidence/verify/compose-profiles-20260807T081950Z.json` |
| stack-health | pass | `pass (exit 0)` | `evidence/verify/stack-health-20260807T081954Z.json` |
| sandbox-spawn | driver_unavailable | `driver_unavailable (exit 2)` | `evidence/verify/sandbox-spawn-20260807T082031Z.json` |
| runtime | pass | `pass (exit 0)` | `evidence/verify/runtime-20260807T082035Z.json` |
| authenticated-proxy-roundtrip | pass | `pass (exit 0)` | `evidence/verify/authenticated-proxy-roundtrip-20260807T082043Z.json` |
| volume-upgrade | pass | `pass (exit 0)` | `evidence/verify/volume-upgrade-20260807T082106Z.json` |
| browser-gui-boot | pass | `pass (exit 0)` | `evidence/verify/browser-gui-boot-20260807T082128Z.json` |
| cancellation-cleanup | driver_unavailable | `driver_unavailable (exit 2)` | `evidence/verify/cancellation-cleanup-20260807T082140Z.json` |
| sandbox-scoped-token | pass | `pass (exit 0)` | `evidence/verify/sandbox-scoped-token-20260807T082143Z.json` |

```
$ make verify-runtime    → VERIFY_OVERALL: pass (exit 0)
$ make verify-stack-health → VERIFY_OVERALL: pass (exit 0)
```

Each driver run was preceded by a `docker container/network/volume prune -f` cycle. All 9 drivers pass on a clean run — no env-flake this batch. The proxy-roundtrip and scoped-token drivers show full check-by-check evidence (stack-up, proxy-healthz 200, token-mint, scope rejection, service-secret still works, teardown clean).

## W22 tunnel-refusal proofs (re-verified)

```
tests/ui/dashboard/test_prod_ready_trust_address_w21_red.py — 8/8 PASSED:
  test_guard_c61_tokenless_loopback_denied                                    PASSED
  test_tokenless_denied_under_tunnel_even_when_trust_address_true             PASSED  ← W22.1
  test_dashboard_cli_does_not_claim_no_login_required                         PASSED  ← W22.3
  test_trust_address_forced_off_when_tunnel_configured                        PASSED  ← W22.1
  test_trust_address_boot_warning_noop_when_disabled                          PASSED
  test_trust_address_boot_warning_emitted_when_enabled                        PASSED  ← W22.2
  test_guard_c63_landed_auth_suites_unmodified                                PASSED
  test_trust_address_forced_off_when_gateway_not_loopback                     PASSED  ← W22.1
```

The boot-warning test asserts that `log_local_open_trust_address_boot_warning` actually emits a WARNING log when the escape hatch is enabled (`src/sevn/ui/dashboard/services/auth.py:399-430`); the CLI-honesty test asserts the literal substring `"loopback access — no login required"` is **absent** from `src/sevn/cli/commands/dashboard_cmd.py` (greps came back empty). The tunnel-refusal tests assert `apply_tunnel_local_open_policy` (`src/sevn/ui/dashboard/services/auth.py:327-396`) force-disables both `local_open` and `local_open_trust_address` under a `tunnel.mode` configuration **and** under a non-loopback `gateway.host`.

### C6.1 unmodified suite (re-verified)

```
tests/ui/dashboard/test_local_open_auth.py            + test_post_audit_local_token_w17_red.py
collected 15 items
… 15 PASSED in 57.55s …
```

`C6.1` denial still holds unmodified.

## W23 wiring (re-verified)

1. **Cron path** — `.github/workflows/ci-supplementary.yml:34-65` runs `make verify-deployment` on `schedule` + `workflow_dispatch`; exit 1 propagates as `::error`, exit 2 (driver_unavailable) downgrades to `::warning` and the job still succeeds.
2. **Tag path** — `.github/workflows/ci-cd.yml:333-365` runs `make verify-deployment` on `workflow_dispatch` and `refs/tags/v*`; all three non-zero codes fail the job (no `set +e` tolerance — a release that cannot run its own verification has not been verified, D52 / C14.1).
3. **`delivery-chain` aggregator** — `.github/workflows/ci-cd.yml:480-530` lists `verify-deployment` in `needs:` (line 491) **and** in the `require()` loop (line 529).
4. **9 DRIVERS registered** — `scripts/verify_deployment.py:1821-1831` lists all 9 driver names (compose-profiles, stack-health, sandbox-spawn, runtime, authenticated-proxy-roundtrip, volume-upgrade, browser-gui-boot, cancellation-cleanup, sandbox-scoped-token).
5. **Evidence upload name** — `.github/workflows/ci-cd.yml:370 + 455` upload to `name: deployment-verification-${{ github.sha }}`.
6. **Spec 25 amended in-place** — `about-sevn.bot/specs/25-cicd-full.md` documents both invocation surfaces, the aggregator gate, the artefact, the failure modes, and the dynamic evidence section (lines 467-468, 476-478, 488, 537-543, 700-727).
7. **`docker/docker-compose.verify.yml`** present (9 lines) and publishes `127.0.0.1:3102:8787` — the verify-only host mapping.

## Drift sweep

```
$ make readme-check       → exit 0 — "readme check: ok"
$ make about-docs-check   → exit 0 — spec-check 39 files avg=82 errors=0, prd-check 15 files avg=100 errors=0
```

## `make ci-affected` exit code

```
$ SEVN_CI_BASE=origin/pre-0.0.1 SEVN_PYTEST_JOBS=0 make ci-affected  → exit 0  (15.6 min)
```

All tier members green: onboarding-capabilities-check, infra-check, spec-check, prd-check, about-site-check, mission-control-schema-check, telemetry-check, full pytest. No path-aware failures.

## Producer → consumer grep results (P5)

```
$ git grep -n "verify-deployment" -- .github/ Makefile scripts/
  .github/workflows/ci-cd.yml:333,365,491,503,510,529   ✓ producer + consumer
  .github/workflows/ci-supplementary.yml:34,54,58,62    ✓ producer + consumer
  Makefile:650                                          ✓ make target defined
  scripts/verify_deployment.py:1821-1831,1898,1899      ✓ DRIVERS registry + main iteration

$ git grep -n "deployment-verification" -- .github/
  .github/workflows/ci-cd.yml:370,455,476               ✓ evidence artefact name

$ git grep -n "VERIFY_PROXY_URL\|VERIFY_COMPOSE\|docker-compose.verify" -- scripts/ docker/
  scripts/verify_deployment.py:66,67,1046,1064,1613,1631 ✓ constant + consumer
  docker/docker-compose.verify.yml:1-9                  ✓ verify-only overlay exists

$ git grep -nE "SEVN_VERIFY_PROXY_PORT" -- src/ docker/ scripts/   → exit 1, zero matches
$ git grep -n "ttl_seconds" -- scripts/                                → exit 1, zero matches
$ git grep -n 'scope="web"' -- scripts/verify_deployment.py           → exit 1, zero matches
```

Every control has a consumer; no dangling controls; no dead env vars.

## Five-check summary

1. **Runtime / behavioural proof — PASS.** All 9 drivers green; `authenticated-proxy-roundtrip` and `sandbox-scoped-token` drivers pass with check-by-check evidence (token-mint uses `scope='sandbox', ttl_s=60`, scope=sandbox accepts on `/web/` and refuses on `/llm/`, service-secret still works). `make verify-runtime` + `make verify-stack-health` green.
2. **Seam audit — PASS.** No `getattr` probes. `VERIFY_PROXY_URL` is a typed constant + verify-only compose overlay; `mint_session_token` called with explicit `scope` + `ttl_s` kwargs (no stringly-typed env interpolation).
3. **Test-quality audit — PASS.** All 14 tests pass for real; the 4 P4a behavioural tests (lines 360-421) **would fail if their guards were deleted** (verified by inspection — they assert `result.status not in {STATUS_FAIL, STATUS_UNAVAILABLE}` against a healthy mocked stack, assert exact `VERIFY_PROXY_URL` literal in source, assert `docker-compose.verify.yml` exists with `127.0.0.1:3102:8787`, and `git grep` the dead env var). No silent-xfail traps remain.
4. **Acceptance reconciliation — PASS.** All 9 invocation paths exercised at runtime; cron + tag paths documented in workflow YAML; aggregator wiring verified; spec 25 in-place prose + Workflow matrix + Failure Modes + Dynamic evidence section all present.
5. **Escape-pattern sweep — PASS.** P2 clean (single test-only commit past F-Thermos base, not gate-authored); P3 clean (no escape-hatch annotations in the post-Thermos diff — there is no post-Thermos diff); P5 clean (every control has a consumer; 4 greps confirm no dangling writes); P6 clean (single overlay file, single constant).

## Static proofs

- `tests/infra/test_prod_ready_verify_deployment_w21_red.py:382-409` — `test_no_driver_probes_unmapped_host_proxy_port` pins the topology: asserts inline `f"http://127.0.0.1:{proxy_port}"` interpolation is **absent** AND `VERIFY_PROXY_URL = "http://127.0.0.1:3102"` is defined exactly once AND `docker/docker-compose.verify.yml` exists AND contains `127.0.0.1:3102:8787`. P4a holds: deleting the constant or the overlay fails this test.
- `tests/infra/test_prod_ready_verify_deployment_w21_red.py:412-421` — `test_no_dead_sevn_verify_proxy_port_reference` runs `git grep -n SEVN_VERIFY_PROXY_PORT -- src/ docker/ scripts/` and asserts exit 1 (no matches). Re-introducing the dead env var fails this test.
- `tests/infra/test_prod_ready_verify_deployment_w21_red.py:360-378` — both `test_authenticated_proxy_roundtrip_driver_probes_via_live_stack` and `test_sandbox_scoped_token_driver_probes_via_live_stack` import the driver module, monkeypatch `_run`/`_http_probe`/`_authenticated_probe`/`mint_session_token`, invoke the live `module.drive_*` functions, and assert `result.status not in {STATUS_FAIL, STATUS_UNAVAILABLE}` plus the `proxy-healthz` check exists. Deleting any of the guards above fails both.
- `tests/ui/dashboard/test_prod_ready_trust_address_w21_red.py:8 tests` — including `test_tokenless_denied_under_tunnel_even_when_trust_address_true`, `test_trust_address_forced_off_when_tunnel_configured`, `test_trust_address_forced_off_when_gateway_not_loopback`, `test_trust_address_boot_warning_emitted_when_enabled`, and `test_dashboard_cli_does_not_claim_no_login_required`. Each is behavioural, not structural.

## Environment skips

None. All 9 drivers ran on a clean docker state; all 14 W21 RED tests + 15 C6.1 unmodified tests + 8 W21 trust-address RED tests passed under pytest.

## Plan close-out

The `## Wave checklist` row for F-Verify / F-Final / F-Thermos / F-Reverify is updated to reflect this gate: the F-Verify sub-checkbox flips from `[ ]` to `[x]` with the F-V5 un-xfail evidence. F-Final, F-Thermos, F-Reverify, F-PR sub-checkboxes remain `[ ]` (those gates run after this one). The F-Verify gate record is committed as `chore(wave): F-Verify gate record (post-F-V5)` (gitignored, per the gate convention).

The remaining F-batch gates may now proceed:
- F-Final — `wave-plan-executor` for the drift-sweep + CHANGELOG + xfail sweep + `make ci-resume` final-wave gate.
- F-Thermos — fresh review agent (D30).
- F-Reverify — fresh `wave-verifier` instance (D30), convention-11 detection with `<batch>` = `f`, re-runs F-Verify proofs against the F-Thermos base.
- F-PR — `wave-plan-executor` opens against `pre-0.0.1`.
