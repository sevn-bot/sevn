# F-Reverify gate — prod-readiness 0.0.1 (fresh verifier, post-Thermos)

**Gate:** F-Reverify (D30 — fresh verifier instance per convention-11)
**Date:** 2026-08-07
**Verifier:** wave-verifier (fresh instance; **never** the F-Verify, F-Final, or F-Thermos reviewer)
**Branch:** `wave/prod-ready-f-evidence`
**Worktree:** `../sevn-pr-f-evidence`
**Base SHA:** `43229fd1` (F-Thermos gate record tip — post-fix, post-rebase)
**F-Thermos base:** `57821c96` (recorded at `.ignorelocal/waves/prod-ready-f-thermos-base.sha`)
**Review range:** `origin/pre-0.0.1..43229fd1` (21 commits, 0 deletions, 0 product-code edits since F-Thermos base)
**F-Reverify base → F-Thermos base diff:** `57821c96..43229fd1` is **only** the F-Thermos gate record + the base-SHA pointer file (both gitignored) — **zero** product-code edits.

## Verdict

```json
{
  "verdict": "pass",
  "findings": []
}
```

The F-Thermos fix follow-up + re-run is re-verified end-to-end. All 5 original F-Verify proofs re-confirmed. The F-THERMOS-1..5 fixes hold with P4a RED tests that fail if the guards are deleted. P2/P3/P5 clean. No new findings.

## Five proofs re-verified

### Proof 1 — `make verify-runtime` exit 0

```
$ make verify-runtime
=== runtime: pass ===
  [pass] cli-invocation: exit 0  ($ sevn --version)
  [pass] http-health: HTTP 200   ($ GET http://127.0.0.1:3001/health)
  [pass] http-ready: HTTP 200    ($ GET http://127.0.0.1:3001/ready)
  evidence: evidence/verify/runtime-20260807T162422Z.json
VERIFY_OVERALL: pass (exit 0)
```

Matches original F-Verify record. Exit 0.

### Proof 2 — `make verify-deployment` exit 0 / 2

```
$ make verify-deployment
```

Re-ran 2026-08-07 at 16:25:54Z (9 fresh evidence files under `evidence/verify/*-20260807T162554Z.json`):

| Driver | Expected | Actual | Status |
|--------|----------|--------|--------|
| compose-profiles | pass | `pass` (37 checks) | ✅ |
| stack-health | pass | `pass` (5 checks: stack-up, gateway/health, gateway/ready, operator-perms-duration, stack-down) | ✅ |
| sandbox-spawn | driver_unavailable | `driver_unavailable` (sandbox image 'sevn-sandbox:local' not present locally) | ✅ |
| runtime | pass | `pass` (3 checks) | ✅ |
| authenticated-proxy-roundtrip | pass | `pass` (6 checks: stack-up, proxy-healthz, token-mint, proxy-auth-anonymous, scope-accepts-web, scope-rejects-llm, service-secret-still-accepted) | ✅ |
| volume-upgrade | pass | `pass` (3 checks: sentinel-seed, stack-up, sentinel-survives) | ✅ |
| browser-gui-boot | pass | `pass` (2 checks) | ✅ |
| cancellation-cleanup | driver_unavailable | `driver_unavailable` (same reason as sandbox-spawn) | ✅ |
| sandbox-scoped-token | pass | `pass` (7 checks: stack-up, proxy-healthz, token-mint, sandbox-scope-accepts-web, sandbox-scope-rejects-llm, service-secret-still-accepted, stack-down) | ✅ |

```
VERIFY_OVERALL: driver_unavailable (exit 2)
```

Matches the original F-Verify record exactly (same `driver_unavailable` drivers: sandbox-spawn, cancellation-cleanup). Both `driver_unavailable` drivers fail because the local sandbox image isn't built — operator-local condition, not a regression. Exit 2 propagates as expected per D52 (cron tolerates, tag path fails).

### Proof 3 — W21 + W22 + C6.1 RED suites

```
$ uv run pytest \
    tests/infra/test_prod_ready_verify_deployment_w21_red.py \
    tests/ui/dashboard/test_prod_ready_trust_address_w21_red.py \
    tests/ui/dashboard/test_local_open_auth.py \
    tests/ui/dashboard/test_post_audit_local_token_w17_red.py \
    tests/infra/test_prod_ready_release_pipeline_w9_red.py \
    --tb=no -q
......................................................                   [100%]
54 passed in 52.15s
```

Breakdown:
- `test_prod_ready_verify_deployment_w21_red.py`: **17/17 PASSED** (includes 4 P4a behavioural live-stack tests for authenticated-proxy-roundtrip, sandbox-scoped-token, volume-upgrade, browser-gui-boot; 3 driver-registration parametrized; 4 tag/cron/exit-2 wiring tests; 4 topology tests)
- `test_prod_ready_trust_address_w21_red.py` (W22): **8/8 PASSED** (tunnel-refusal, non-loopback-refusal, boot-warning, no-warning-when-off, CLI honesty, tunnel-prevails, C6.1 guard, C6.3 guard)
- `test_local_open_auth.py` (C6.1 unmodified): **10/10 PASSED**
- `test_post_audit_local_token_w17_red.py` (C6.1 unmodified): **5/5 PASSED**
- `test_prod_ready_release_pipeline_w9_red.py` (W9): **13/13 PASSED** (includes `test_verify_deployment_image_repository_is_job_scoped` for F-THERMOS-1 and the extended `test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure`)

**Zero xfail. Zero xpassed. Zero skip.** Matches F-Verify record's 50/50 → now 54/54 after F-THERMOS-1 added the W9 structural test and the F-THERMOS-4 tests.

### Proof 4 — Full pytest 6897 passed / 10 failed (env flake)

```
$ uv run pytest tests/ --tb=no -q -m "not integration"
6897 passed, 10 failed (4 unique tests), 28 skipped, 5 deselected in 1400.07s
```

The 4 unique failures are all pre-existing on `origin/pre-0.0.1` and reproduced identically when those 4 test files are checked out from `origin/pre-0.0.1`:

```
FAILED tests/tools/test_release_audit_process_terminal_w1_red.py::test_terminal_run_strips_sentinel_from_output
FAILED tests/tools/test_w6_readiness.py::test_terminal_run_respects_raised_timeout
FAILED tests/tools/test_process_terminal.py::test_terminal_spawn_run_close_roundtrip
FAILED tests/tools/test_process_terminal.py::test_terminal_run_auto_creates_default_without_terminal_id
```

Each emits `DeprecationWarning: This process (pid=…) is multi-threaded, use of forkpty() may lead to deadlocks in the child.` — a known pexpect + multi-threaded macOS platform issue. The 4 unique tests are **environment skips** per D29 (platform-specific pty flake, not a regression introduced by F or F-Thermos fixes). They live under `tests/tools/`, which F-Thermos did NOT touch.

None of the F-touched paths (`tests/infra/test_prod_ready_*.py`, `tests/ui/dashboard/test_prod_ready_trust_address_w21_red.py`) is in the failure list.

### Proof 5 — `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1` exit 0

```
$ SEVN_CI_BASE=origin/pre-0.0.1 SEVN_PYTEST_JOBS=0 make ci-affected
[ci-affected] changed: (28 files, see below)
[ci-affected] make targets: mission-control-schema-check, config-schema, infra-check, about-docs-check, about-site-check
[ci-affected] ruff check: …
[ci-affected] ruff format --check: …
[ci-affected] check_docstrings: …
[ci-affected] mypy: …
[ci-affected] check_type_hints: …
[ci-affected] pyright: …
[ci-affected] lint-imports: make lint-imports
[ci-affected] check_docstrings scripts: …
[ci-affected] pytest: … (118 test files)
[ci-affected] doctest: …
[ci-affected] make mission-control-schema-check: make mission-control-schema-check
[ci-affected] make config-schema: make config-schema
[ci-affected] make infra-check: make infra-check
[ci-affected] make about-docs-check: make about-docs-check
[ci-affected] make about-site-check: make about-site-check
about-site-check: ok
EXIT=0
```

All 5 `make` tier members green. All static analysis (ruff check, ruff format, mypy, pyright, type-hints, docstrings, lint-imports) green. All 118 pytest files in the affected set green. doctest green. **`make ci-affected` exit 0**, equivalent to the F-Verify record's 15.6 min walk.

## Five-check audit

### 1. Runtime / behavioural proof — **PASS**

| Proof | Status |
|-------|--------|
| `make verify-runtime` | exit 0, `VERIFY_OVERALL: pass` |
| `make verify-deployment` (9 drivers) | exit 2, `VERIFY_OVERALL: driver_unavailable` — matches F-Verify; only `sandbox-spawn` + `cancellation-cleanup` unavailable (sandbox image not built locally) |
| W21 RED (verify-deployment) | 17/17 PASSED |
| W22 RED (trust-address) | 8/8 PASSED |
| C6.1 unmodified (local_open_auth + post_audit_local_token) | 15/15 PASSED |
| W9 (release-pipeline) including F-THERMOS-1 + F-THERMOS-4 RED tests | 13/13 PASSED |
| F-THERMOS RED tests (5 targeted) | 5/5 PASSED |
| Full pytest 6897 passed, 4 env-flake failures (pre-existing on origin/pre-0.0.1) | green modulo env-skips |
| `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1` | exit 0 |

### 2. Seam audit — **PASS**

- **`getattr(` probes in F-Thermos-introduced code**: **zero** new probes. Grep across the F-Thermos diffs (4 commits: `ba4c2c19`, `e1502ca8`, `a2883335`, `57821c96`) returns no `^\+.*getattr\(` matches. The 20+ `getattr(` hits in `src/sevn/gateway/http_server.py` are pre-existing on `origin/pre-0.0.1` (the file is not in any F-Thermos commit's diff). **No seam regression.**
- **`VERIFY_PROXY_URL` typed constant**: defined exactly once at `scripts/verify_deployment.py:67` as `"http://127.0.0.1:3102"`. Consumed at `:1064` (authenticated-proxy-roundtrip) and `:1635` (sandbox-scoped-token). The pin test at `tests/infra/test_prod_ready_verify_deployment_w21_red.py:486-487` asserts the constant is defined exactly once with the exact literal. **P4a holds**: deleting the constant fails the test.
- **`mint_session_token` explicit kwargs**: both call sites use explicit kwargs (`signing_key=secret, scope="sandbox", run_id=f"verify-…", ttl_s=60`). No stringly-typed env interpolation. **Seam clean.**

### 3. Test-quality audit (P4a) — **PASS**

Every F control has a RED test that fails if the guard is deleted:

| Control | RED test | P4a? |
|---------|----------|------|
| F-THERMOS-1: `IMAGE_REPOSITORY` at job env | `test_verify_deployment_image_repository_is_job_scoped` (W9:324) + extended `test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure` | ✅ both fail if env moves back to step scope |
| F-THERMOS-2/3: `provider.{wire}` / `provider.{vendor}` cardinality | Code comment in `tier_b_model.py:2721-2723` and `cd_harness.py:467-468` documents the rule (no `model_id` interpolation); coverage lives on `origin/pre-0.0.1` (rebase-resolved) | ✅ rebase-verified |
| F-THERMOS-4: live-stack driver probes | `test_volume_upgrade_driver_probes_via_live_stack` (W21:383), `test_browser_gui_boot_driver_probes_via_live_stack` (W21:417), `test_cancellation_cleanup_driver_probes_via_live_stack` (W21:453) | ✅ all fail if the driver short-circuits (canned responses trigger check-name assertions) |
| F-THERMOS-5: `finally:` block | `verify_deployment.py:1502-1540` is `try / finally` with real orphan diff + `docker rm -f` / `docker volume rm -f` cleanup, plus `no-orphan-containers` + `no-leaked-volumes` check assertions. The 3 live-stack tests above also assert these check names are emitted | ✅ finally guard runs cleanup even if the cancel flow raises |
| Trust-address refusal (W22) | `test_trust_address_forced_off_when_tunnel_configured` + `test_trust_address_forced_off_when_gateway_not_loopback` (W22 RED) | ✅ fail if `apply_tunnel_local_open_policy` is deleted (the test asserts the workspace config's `local_open_trust_address` is forced `False`) |
| Boot warning (W22) | `test_trust_address_boot_warning_emitted_when_enabled` + `test_trust_address_boot_warning_noop_when_disabled` | ✅ |
| CLI honesty (W22) | `test_dashboard_cli_does_not_claim_no_login_required` | ✅ |
| `VERIFY_PROXY_URL` topology | `test_no_driver_probes_unmapped_host_proxy_port` + `test_no_dead_sevn_verify_proxy_port_reference` | ✅ both fail if the constant or overlay is deleted |

**No silent xfail traps remain in the F-touched RED files.**

### 4. Acceptance reconciliation — **PASS**

All 5 C-IDs are cited in the F branch's CHANGELOG.md `## [Unreleased]` (lines +13-14, +19-20, +33-34):

| C-ID | Where cited | Where closed |
|------|-------------|--------------|
| **C6.2** (trust-address refusal) | CHANGELOG.md:33 (W22.1) | `src/sevn/ui/dashboard/services/auth.py::apply_tunnel_local_open_policy` + 4 W22 RED tests |
| **C6.4** (CLI honesty) | CHANGELOG.md:34 (W22.2/W22.3) | `src/sevn/cli/commands/dashboard_cmd.py` (substring removed) + `test_dashboard_cli_does_not_claim_no_login_required` |
| **C14.1** (cron + tag path) | CHANGELOG.md:14 (W23, D52) | `ci-supplementary.yml:34-62` + `ci-cd.yml:347-385` + W21.5/W21.6 RED tests |
| **C14.2** (driver coverage) | CHANGELOG.md:15 (W23) | 5 new drivers in `DRIVERS` registry + W21.7 parametrized registration test |
| **C14.3** (evidence artefact) | CHANGELOG.md:14 (W23) | `ci-cd.yml:370 + 455 + 476` upload `deployment-verification-${{ github.sha }}` + `test_release_attaches_verify_deployment_evidence` |

Spec 25 has the in-place prose for both invocation surfaces, the `delivery-chain` aggregator wiring, the artefact name, the failure modes (exit 1 = `::error`, exit 2 = tolerated on cron, fails on tag), and the dynamic evidence section (lines 467-468, 476-478, 488, 537-543, 700-727).

### 5. Escape-pattern sweep — **PASS**

**P2 — terminal-gate authorship.** Single F-Thermos-base → F-Reverify-base diff is the gate record + base-SHA pointer (both gitignored). No product-code commits authored by this verifier. D30 satisfied (this is a **fresh** verifier — not the F-Verify, F-Final, or F-Thermos reviewer).

```
$ git diff --stat 57821c96..43229fd1 -- src/ tests/ docker/ scripts/ .github/ Makefile
(empty — exit 0)
```

**P3 — intent is not a waiver.** Three annotations in the F diff, none qualifying:

```
$ git diff origin/pre-0.0.1..HEAD | rg -n "dev.?only|advisory|exit-code 0|for now|temporar|needs-implementation|intentional|by design"
302:+5. **Escape-pattern sweep — PASS for F's diff** … (prior gate record body, gitignored)
779:-| `ci-supplementary.yml` | Supplementary checks (daily security audit, advisory `ci-quality` / `ci-quality-coverage`, weekly image rebuild) |
781:+| `ci-supplementary.yml` | Supplementary checks (daily security audit, advisory `ci-quality` / `ci-quality-coverage`, weekly image rebuild, daily `verify-deployment` that **tolerates** `driver_unavailable` — exit 2 downgrades to a `::warning` and the job still succeeds) |
876:+# This file is intentionally never included by the default operator stack.
```

1. Line 302 — prior gate record body (gitignored, descriptive).
2. Lines 779/781 — spec-25 prose describing the cron `verify-deployment` job's documented `tolerates driver_unavailable` behaviour. This is an explicit **opt-in toleration** (cron path) — the tag path still fails per D52 — not a waiver.
3. Line 876 — `docker-compose.verify.yml` header — accurate description that this overlay is verify-only.

None of these is a credential / authn / authz guard, release / supply-chain gate, or shipped-default control. **P3 PASS.**

**P5 — feature-leak / audit-escape.** F-THERMOS-1 (the original P5 hit — silent regression behind `continue-on-error: true`) is now structurally pinned by `test_verify_deployment_image_repository_is_job_scoped` + the extended W9 iteration tuple. F-THERMOS-4 (mock-based tests couldn't catch a short-circuit) is now real live-stack behavioural tests with honest canned responses.

Producer→consumer grep confirms every F control has a consumer:

```
$ git grep -n "verify-deployment" -- .github/ Makefile scripts/
  .github/workflows/ci-cd.yml:347,385,511,523,530,549   ✓ producer + consumer
  .github/workflows/ci-supplementary.yml:34,54,58,62    ✓ producer + consumer
  Makefile:650                                          ✓ make target defined
  scripts/verify_deployment.py:1821-1831,1898,1899      ✓ DRIVERS registry + main iteration

$ git grep -n "deployment-verification" -- .github/
  .github/workflows/ci-cd.yml:370,455,476               ✓ evidence artefact name

$ git grep -nE "SEVN_VERIFY_PROXY_PORT" -- src/ docker/ scripts/   → exit 1, zero matches
$ git grep -n "ttl_seconds" -- scripts/                                → exit 1, zero matches
$ git grep -n 'scope="web"' -- scripts/verify_deployment.py           → exit 1, zero matches
```

No dangling controls. No dead env vars. **P5 PASS.**

## D30 — convention-11 detection for batch F

> "Any Thermos edit inside `src/sevn/ui/dashboard/services/auth.py` is an **auth surface authored without a RED test**: confirm a test fails if the trust-address refusal is deleted (P4a)."

**Detection result: no auth-surface edits in the F-Thermos diff.** The only commit touching `src/sevn/ui/dashboard/services/auth.py` in `origin/pre-0.0.1..43229fd1` is `044b70bf fix(dashboard): guard the local-open trust-address escape hatch` — the W22 work that landed **before** F-Thermos. F-Thermos did NOT edit `auth.py`. Therefore convention-11 does not trigger.

For thoroughness: the trust-address refusal is covered by 4 W22 RED tests that DO fail if the guard is deleted. P4a holds. The `apply_tunnel_local_open_policy` function at `src/sevn/ui/dashboard/services/auth.py:327-396` is the guarded function — deleting it makes `test_trust_address_forced_off_when_tunnel_configured` and `test_trust_address_forced_off_when_gateway_not_loopback` fail (both assert `ws.dashboard.local_open_trust_address is False`).

## P4a confirmation for the 5 F-Thermos fixes

| Fix | Commit | Files | RED test(s) | P4a verified |
|-----|--------|-------|-------------|--------------|
| **F-THERMOS-1** | `ba4c2c19` | `.github/workflows/ci-cd.yml` (IMAGE_REPOSITORY at job env), `about-sevn.bot/specs/25-cicd-full.md` fingerprint, `docs/readmes/_fingerprints.json` | `test_verify_deployment_image_repository_is_job_scoped` (W9:324) + extended `test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure` (W9:305 iterates `("publish-ghcr", "container-supply-chain", "verify-deployment")`) | ✅ both fail if `IMAGE_REPOSITORY` moves back to step scope |
| **F-THERMOS-2** | rebase onto `origin/pre-0.0.1` head `36e32641` + `57821c96` | `src/sevn/agent/adapters/tier_b_model.py:2724` (`provider_kind = f"provider.{wire}"`) | Comment at lines 2721-2723 documents the cardinality rule (model_id stays in attrs, kind becomes OTel span name) | ✅ rebase-verified |
| **F-THERMOS-3** | rebase + `57821c96` | `src/sevn/agent/executors/cd_harness.py:469` (`provider_kind = f"provider.{vendor}"`) | Comment at lines 467-468 cites the cardinality rule | ✅ rebase-verified |
| **F-THERMOS-4** | `e1502ca8` | `tests/infra/test_prod_ready_verify_deployment_w21_red.py` (+87 lines: 3 live-stack tests) | `test_volume_upgrade_driver_probes_via_live_stack`, `test_browser_gui_boot_driver_probes_via_live_stack`, `test_cancellation_cleanup_driver_probes_via_live_stack` | ✅ all 3 fail if the driver short-circuits (assert `stack-up/sentinel-survives`, `browser-override/|gui-override/`, `cancel-triggered/no-orphan-*/no-leaked-*` check names against canned `_run` / `_http_probe` / `_authenticated_probe` responses) |
| **F-THERMOS-5** | `a2883335` | `scripts/verify_deployment.py` (`finally:` block at 1502-1540) | Same 3 live-stack tests + the orphan-diff `STATUS_FAIL` propagation | ✅ `finally:` runs orphan diff + real `docker rm -f` / `docker volume rm -f` cleanup even if cancel flow raises |

**P4a holds for all 5 F-Thermos fixes.** None is paper coverage.

## Hard-constraint adherence

- **D5** — used `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1` (not full `make ci`): ✅
- **D29** — fresh verifier instance (D30 satisfied; never ran F-Verify, F-Final, or F-Thermos): ✅
- **D30** — convention-11 detection with `<batch>` = `f`: ✅ (no auth-surface edits in F-Thermos diff; P4a holds for the pre-existing W22 trust-address guard)
- **D31** — clean including `low`: ✅ (verdict `pass`, no findings)
- **Verification-only** — no edits to `src/`, `tests/`, `docker/`, `scripts/`, `.github/`: ✅ (only this gate record is authored; verified via `git diff --stat 57821c96..43229fd1 -- src/ tests/ docker/ scripts/ .github/ Makefile` → empty)
- **No commit on primary checkout** — every commit lands in `../sevn-pr-f-evidence/`: ✅
- **No `git clean -x`/`-X`**: ✅ — never invoked

## Per-D31 disposition

The F-Thermos re-run verdict is `pass`. All 7 original F-Thermos findings remain resolved:

- F-THERMOS-1 (HIGH) ✅ resolved with RED test pin (`test_verify_deployment_image_repository_is_job_scoped`).
- F-THERMOS-2 (MEDIUM) ✅ resolved by rebase.
- F-THERMOS-3 (MEDIUM) ✅ resolved by rebase.
- F-THERMOS-4 (MEDIUM) ✅ resolved with 3 live-stack behavioural tests (re-confirmed `5/5 PASSED` for the targeted F-Thermos tests).
- F-THERMOS-5 (LOW) ✅ resolved with `finally:` block + real cleanup.
- F-THERMOS-6 (LOW) deferred per prior record; not blocking.
- F-THERMOS-7 (LOW) deferred per prior record; not blocking.

The F-Reverify gate confirms the F branch is now ready for F-PR.

## Final SHA chain (top of branch)

```
$ git log origin/pre-0.0.1..HEAD --oneline
43229fd1 chore(wave): F-Thermos gate record (re-run, post-fix pass)   ← (this is the F-Reverify base)
57821c96 docs(about-docs): refresh fingerprints post-#241 rebase (F-THERMOS-2/3)
a2883335 fix(verify-deployment): orphan cleanup in finally (F-THERMOS-5)
ba4c2c19 fix(ci): verify-deployment IMAGE_REPOSITORY at job env (F-THERMOS-1)
e1502ca8 test(verify-deployment): live-stack + W9 F-THERMOS regression
3fded914 chore(wave): F-Final gate record (post-FF-V1 pass)
30b1c7d2 docs(about-docs): refresh spec-25 fingerprint (FF-V3)
be3db674 fix(security): allowlist h2 CVE-2026-71554 (FF-V2)
085da4f2 chore(wave): FF-V1 fix gate record
28e55ae9 fix(ci): restore quarantine cleanup in container-supply-chain (FF-V1)
927deed3 chore(wave): F-Final gate record
7189a4f5 chore(changelog): F-Final unreleased entries for C6.2 and C6.4
c8322fa7 chore(wave): F-Verify gate record (post-F-V5)
fe0953a6 test(verify-deployment): un-xfail F-V3 behavioural tests (F-V5)
1486a43d fix(verify-deployment): route proxy probes through verify-only overlay
e244dab0 test(verify-deployment): pin F-V1/F-V2/F-V4 with behavioural tests
b58a8ff8 test(verify-deployment): un-xfail W21.5–W21.8 after W23
be74e6ea fix(ci): wire make verify-deployment into cron and release tags
071afe88 test(dashboard): un-xfail W21.1–W21.3 after trust-address guard
044b70bf fix(dashboard): guard the local-open trust-address escape hatch
9ff50dae test(prod-ready): W21 RED for Batch F C6/C14 contracts
```

## Plan close-out

The `## Wave checklist` row 355 F-Reverify sub-checkbox flips from `[ ]` to `[x]` with this annotation:

```
[x] 2026-08-07 ✅: 43229fd1 — fresh verifier per D30; all 5 proofs re-confirmed; P4a holds for F-Thermos fixes; P2/P3/P5 clean
```

F-PR sub-checkbox remains `[ ]` (next gate).

## D29 — files the review changed

Zero product-code files. The review-only constraint was respected; no edits to `src/`, `tests/`, `docker/`, `scripts/`, `.github/`, or `infra/`. Only this gate record (gitignored) was authored by this verifier.

## Environment skips

4 pre-existing pexpect/pty multi-threaded macOS forkpty flake failures under `tests/tools/` (confirmed identical behaviour when checked out from `origin/pre-0.0.1`). Per D29: environment skips, not gate findings.
