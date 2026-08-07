# Batch D Reverify gate — prod-readiness 0.0.1

**Gate:** D-Reverify (fresh verifier, D30)
**Date:** 2026-08-07
**Branch:** `wave/prod-ready-d-isolation`
**Worktree:** `../sevn-pr-d-isolation`
**D-Thermos base SHA:** `9ccb75c6`
**Verified tip:** `636aa69c`
**Compare range:** `origin/pre-0.0.1..HEAD`

## Verdict

```json
{
  "verdict": "pass",
  "findings": []
}
```

D31 satisfied: clean including `low`.

## Re-verification of original D-Verify proofs

1. **Runtime / behavioural proof — PASS.** `make verify-runtime` exited 0 with `VERIFY_OVERALL: pass (exit 0)`; CLI invocation, `/health`, and `/ready` all passed. Evidence: `evidence/verify/runtime-20260807T162343Z.json`.
2. **W13 RED + post-audit W1 suites — PASS.** The combined command completed with `34 passed, 1 skipped, 1 xfailed`. The skip is the expected absent `:ci` image; the sole xfail is the explicit D50/#240 C8.3 deferral. This includes the W13 tests and all 22 post-audit W1 tests.
3. **Compose preflight / hardening proof — PASS.** The affected gate exercised the compose checks without failure. The current compose files retain the overlay-wide `--no-sandbox` ban, scoped permissions migration, `/operator/.sevn/perms-v1` marker, CI parity, Compose 2.20 floor, and resolved-service resource-limit checks.
4. **Acceptance / supply-chain and production-hardening proof — PASS.** C9.1, C9.2, C9.4 and C10.1, C10.2, C10.3 remain covered by their behavioral consumers. C8.1, C8.2, and C8.4 remain green; C8.3 remains explicitly deferred under D50/#240.
5. **Post-Thermos partial gate — PASS.** `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1` exited 0: `506 passed, 2 skipped, 1 xfailed, 3 warnings`; doctests `24 passed`; `about-docs-check` and `about-site-check` passed.

## Five-check summary

1. **Seams — PASS.** No `getattr(` probing was introduced in Batch D touched files. The D-specific implementation uses direct/typed seams for compose configuration and runtime `HostConfig` JSON.
2. **Test quality — PASS.** No silent xfail traps. The only xfail is `xfail(strict=False)` with explicit `deferred D50/#240` rationale. Every Batch D producer has a behavioral consumer: overlay sandbox flag scan; stale-comment scan; site-isolation justification; scoped permissions and marker guards; CI-init parity; minimum Compose version; runtime `HostConfig`; and resolved limits for every service.
3. **Acceptance reconciliation — PASS.** `CHANGELOG.md` explicitly cites all ten IDs: C8.1, C8.2, C8.3, C8.4, C9.1, C9.2, C9.4, C10.1, C10.2, and C10.3.
4. **Escape patterns — PASS.** P2/P3/P5 are clean; details below.
5. **Producer → consumer — PASS.** Commit history pairs W13/W14/W15/W16 implementations with consumer tests. W17/C8.3 is retained as a visible RED xfail and tracked by #240 rather than silently waived.

## D30 / P2 / P3 / P5 detection

- **D30 — PASS.** `git diff 9ccb75c6..HEAD -- src/sevn/security docker scripts .github tests` is empty. The only post-base commit is `636aa69c chore(wave): D-Thermos gate record`; it adds only `.ignorelocal/waves/prod-ready-d-thermos-base.sha`. Thermos authored no product code and no auth/release surface.
- **P2 — PASS.** The gate-named commits in the range are gate records only. No gate-authored product hunk exists. The implementation/fix commits remain paired with RED consumer commits.
- **P3 — PASS.** The diff contains no credential, release, supply-chain, or shipped-default waiver. The `dev-only` hit in `docker/README.md` is pre-existing context, not a Batch D addition; no `--exit-code 0`, temporary, advisory, intentional, or by-design waiver was added to a protected surface.
- **P5 — PASS.** No dangling control was found. Every Batch D hardening producer has an invoked consumer test or CI/preflight path. The pre-existing `exit 0` in `scripts/check-compose-default.sh` is not introduced by Batch D and is not an escape added by this gate.

## P4a auth-surface deletion proof

No Thermos edit exists inside `src/sevn/security/`, `docker/`, `scripts/`, or `.github/`; therefore no post-Thermos auth surface was authored without a RED test. The relevant guards remain deletion-sensitive:

- deleting/reintroducing the compose `--no-sandbox` protection fails `test_no_compose_file_passes_no_sandbox` and the compose preflight;
- deleting the scoped `/operator` behavior fails `test_operator_perms_scopes_chown_to_application_owned_dirs`;
- deleting marker gating fails `test_operator_perms_writes_versioned_init_marker` and `test_operator_perms_skips_broad_migration_when_marker_present`;
- deleting CI parity fails `test_ci_init_has_no_unconditional_chown`;
- deleting the Compose floor fails `test_compose_preflight_enforces_minimum_version`;
- deleting runtime/declared resource guards fails `test_created_containers_hostconfig_matches_declared_limits` or `test_resolved_compose_config_declares_limits_for_every_service`.

## Final commit state before this gate record

```text
636aa69c chore(wave): D-Thermos gate record
9ccb75c6 chore(wave): D-Final gate record (post-blocker-fix pass)
fe4b7c14 chore(spec-kit-wave): ignore W1 RED tests (D-Final)
035037c3 chore(changelog): D-Final unreleased entries
b03aa47a docs: refresh fingerprints for D-Final drift sweep (D7)
74d8e3da test(compose): un-xfail W13.1/W13.5–W13.8 after W15/W16
1f40a9ab fix(compose): prove resource limits are enforced at runtime
0d4133af fix(compose): scope the permissions init and gate it on a marker
f03d18ae test(compose): un-xfail W13.2–W13.4 after browser sandbox flags
a9208ed9 fix(compose): stop disabling the browser sandbox in production
85648766 test(compose): add Batch D W13 RED isolation suite
```

`D-PR` remains unmodified.
