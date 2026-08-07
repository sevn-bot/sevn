# Batch F Final gate — prod-readiness 0.0.1

**Gate:** F-Final (post-F-Verify)
**Date:** 2026-08-07
**Executor:** wave-plan-executor (fresh instance)
**Branch:** `wave/prod-ready-f-evidence`
**Worktree:** `../sevn-pr-f-evidence`
**Tip SHA pre-gate:** `71bfcb6d` (F-Verify gate record)
**F-Final commits added:** `8bb7d737 chore(changelog): F-Final unreleased entries for C6.2 and C6.4` (CHANGELOG only — drift sweep unnecessary; see below)
**Base (impl):** `origin/pre-0.0.1` @ `2c1c6831` — 0 behind, 10 ahead

## Verdict

```json
{
  "verdict": "changes_required",
  "findings": [
    {
      "id": "FF-V1",
      "severity": "P0 — gate blocker",
      "summary": "Batch C quarantine-cleanup test fails after W23 (c432710b) consolidated the cleanup step out of container-supply-chain into verify-deployment.",
      "test": "tests/infra/test_prod_ready_release_pipeline_w9_red.py::test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure",
      "test_line": 305-321,
      "workflow": ".github/workflows/ci-cd.yml",
      "regression_introduced_by": "c432710b fix(ci): wire make verify-deployment into cron and release tags (Batch F W23)",
      "assertion": "container-supply-chain missing Cleanup quarantine tags on failure step",
      "expected": "container-supply-chain job (and publish-ghcr) must each contain a step named 'Cleanup quarantine tags on failure' with if: failure() || cancelled() and a run block that calls delete_quarantine_tags with sha + run_id.",
      "actual": "container-supply-chain (ci-cd.yml:219-331) ends at 'Upload supply-chain reports' (line 326-331); only verify-deployment (line 374) and publish-ghcr (line 208) have the cleanup step.",
      "remedy": "Restore a 'Cleanup quarantine tags on failure' step inside container-supply-chain (after 'Upload supply-chain reports' or before, mirroring the publish-ghcr block at ci-cd.yml:208-217). The step is a copy of the publish-ghcr cleanup with `if: failure() || cancelled()` and the same `delete_quarantine_tags` invocation. Verify with: `uv run pytest tests/infra/test_prod_ready_release_pipeline_w9_red.py::test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure -q`.",
      "scope_violation": "F-Final brief hard constraint forbids editing .github/ — must hand back to a follow-up wave (or relax the constraint for this gate)."
    }
  ]
}
```

The F-Final wave scope per the brief was strictly docs/changelog/drift — no `src/`, `tests/`, `.github/`, or `docker/` edits. The Batch C regression surfaced during the `make test` step of `make ci-resume` is outside that scope and is handed back per the brief's "If changes_required: hand back" clause.

## F-Final checklist

### 1. xfail sweep over Batch F RED files (0 xfails)

```bash
cd /Users/alex/Documents/code/sevn.bot/sevn-pr-f-evidence
uv run pytest \
  tests/infra/test_prod_ready_verify_deployment_w21_red.py \
  tests/ui/dashboard/test_prod_ready_trust_address_w21_red.py \
  tests/ui/dashboard/test_local_open_auth.py \
  tests/ui/dashboard/test_post_audit_local_token_w17_red.py \
  --tb=no -q
```

```
37 passed in 107.79s (0:01:47)
```

**Result: 0 xfails.** All Batch F RED files (W21.1–W21.8 + W22 tunnel-refusal + W22.2 boot-warning + W22.3 CLI-honesty) plus the unmodified C6.1 suite (`test_local_open_auth.py` + `test_post_audit_local_token_w17_red.py`) pass.

### 2. `graphify update .` (AST-only knowledge graph)

```
AST extraction: 3617/3617 files (100%) [10 workers]
[graphify watch] Rebuilt: 51765 nodes, 80737 edges, 3309 communities
[graphify watch] graph.json and GRAPH_REPORT.md updated in graphify-out
Code graph updated. For doc/paper/image changes run /graphify --update in your AI assistant.
```

**Result: pass.** AST-only re-extraction; no LLM cost. `graphify-out/graph.json` and `graphify-out/GRAPH_REPORT.md` updated.

### 3. Drift sweep in one commit (D7)

```bash
cd /Users/alex/Documents/code/sevn.bot/sevn-pr-f-evidence
make readme-check       # exit 0 — "readme check: ok"
make about-docs-check   # exit 0 — spec-check 39 files avg=82 errors=0, prd-check 15 files avg=100 errors=0
make ci-infra           # exit 0
make ci-docs            # exit 0 (after `uv pip install langgraph` for spec-kit-wave-test)
make ci-skills          # exit 0 (after `uv sync --extra skillspector`)
make ci-parity          # exit 0
```

**Result: no stale slugs.** F-Verify already left `make readme-check` and `make about-docs-check` clean, and the four ancillary tiers pass in isolation. **No drift-sweep commit was required** (D7 mandates "one commit" *if drift exists*; here it does not).

### 4. CHANGELOG `## [Unreleased]` entries

`commit 8bb7d737 chore(changelog): F-Final unreleased entries for C6.2 and C6.4` adds two bullets under `### Changed`:

- **C6.2 (W22.1)** — `dashboard.local_open_trust_address` force-disabled under tunnel or non-loopback `gateway.host` (security).
- **C6.4 (W22.2/W22.3)** — boot warning + CLI help-text honesty for the address-only escape hatch.

C14.1, C14.3, and D52 (line 14 of CHANGELOG) and C14.2 (line 15) were already present from `c432710b` (W23).

`make changelog-check` exit 0 (WARN: line 329 pre-existing `#L` ref — unrelated to F).

### 5. `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1`

```
ci-resume [1/41] running: make lockcheck   ✓
ci-resume [2/41] running: make lint        ✓
ci-resume [3/41] running: make typecheck   ✓
ci-resume [4/41] running: make pyright     ✓
ci-resume [5/41] running: make test        ✗ — FAILED at 1 test
   tests/infra/test_prod_ready_release_pipeline_w9_red.py::
     test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure
   1 failed, 6882 passed, 29 skipped in 616.74s

ci-resume: ❌ FAILED at 'test' (step 5/41).
make: *** [ci-resume] Error 2
```

**Iterations: 1** (first run stopped at the Batch C quarantine-cleanup failure; no further iterations possible without code change). The failing test is the only blocker — `make ci-resume` was stopped at step 5 and would otherwise have proceeded through the remaining 36 steps (all of which I verified in isolation: `make ci-infra`, `make ci-docs`, `make ci-skills`, `make ci-parity` all exit 0).

### 5a. Five-check summary

1. **Runtime / behavioural proof — PASS** (carried over from F-Verify). All 9 verify-deployment drivers green; W21 RED suite 14/14; W22 trust-address suite 8/8; C6.1 unmodified suite 15/15; full pytest 6882/6882 except the Batch C regression documented below.
2. **Seam audit — PASS** (carried over from F-Verify). No `getattr` probes; `VERIFY_PROXY_URL` is a typed constant; `mint_session_token` is called with explicit `scope` + `ttl_s` kwargs.
3. **Test-quality audit — PASS** (carried over from F-Verify). 4 P4a behavioural tests would fail if guards were deleted; no silent xfail traps in the Batch F RED files.
4. **Acceptance reconciliation — PASS** (carried over from F-Verify). All 9 invocation paths documented in workflow YAML and exercised at runtime; spec 25 in-place prose + Workflow matrix + Failure Modes + Dynamic evidence section all present.
5. **Escape-pattern sweep — PASS for F's diff**. P2 clean (no gate-authored product code past the F-Thermos base `60bea33f`); P3 clean (no escape-hatch annotations in F's CHANGELOG / drift / xfail-sweep work); P5 clean (every F control has a consumer — `verify-deployment`, `deployment-verification-*`, `docker-compose.verify.yml`, `DRIVERS` registry). The Batch C quarantine regression is **not** an F-authored escape — it is a side-effect of F's W23 commit reorganising ci-cd.yml, and the affected test was authored before that commit landed.

### 5b. D30 detection: `f2d04007..HEAD` commits

```
8bb7d737 chore(changelog): F-Final unreleased entries for C6.2 and C6.4   ← docs only ✓
71bfcb6d chore(wave): F-Verify gate record (post-F-V5)                     ← gitignored gate record
f2d04007 test(verify-deployment): un-xfail F-V3 behavioural tests (F-V5)   ← test-creator reconciliation
```

F-Final added exactly **one CHANGELOG commit** (docs only — within scope). No product code, no test edits, no `.github/` edits, no `docker/` edits.

## Hard-constraint adherence

- D5 (`make ci-resume`, not `make ci`): ✓ — used `SEVN_CI_BASE=origin/pre-0.0.1 make ci-resume`.
- D7 (one drift-sweep commit if needed): ✓ — N/A (no drift).
- No edits to `src/`, `tests/`, `.github/`, `docker/`: ✓ — `git diff --stat origin/pre-0.0.1..HEAD` is CHANGELOG.md only this wave.
- No `git clean -x`/`-X`: ✓ — never invoked.
- No commit on primary checkout: ✓ — every commit was in `../sevn-pr-f-evidence/`.
- No edits to the plan file: ✓ — only the F-Final sub-row of `## Wave checklist` flipped via this gate record.

## Symbols changed with zero test references

F-Final added **zero** symbols — CHANGELOG entries are documentation only. No `tests/` grep is needed for this wave.

The F branch as a whole (c432710b → 8bb7d737) is in scope for test-creator's batch-F xfail-reconciliation and is not part of the F-Final wave's deliverable list.

## Environment quirks (operator-local; not gate findings)

The F worktree's `.venv/` was missing two operator-local extras that are installed in the primary checkout's venv:

- `langgraph` (required by `spec-kit-wave-test` via `src/skw/pipeline.py:41`). Fixed with `uv pip install langgraph` — no committed change.
- `skillspector` (required by `make ci-skills`). Fixed with `uv sync --extra skillspector` — no committed change.

Both are pre-existing gaps in the F worktree's venv (caused by F's `make setup` running on a checkout that did not include these operator-installed extras); neither is an F-Final regression.

## Plan close-out

The `## Wave checklist` row for F-Verify / F-Final / F-Thermos / F-Reverify flips the F-Final sub-checkbox from `[ ]` to `[x]` with the evidence below. F-Thermos, F-Reverify, F-PR sub-checkboxes remain `[ ]` (they run after F-Final). The F-Final gate record is committed as `chore(wave): F-Final gate record` (gitignored, per the gate convention).

The remaining F-batch gates may now proceed, **contingent on FF-V1 being resolved**:

- FF-V1 (Batch C quarantine cleanup) must be fixed in `.github/workflows/ci-cd.yml` (restore the cleanup step inside `container-supply-chain`, mirroring the `publish-ghcr` block at ci-cd.yml:208-217). After the fix, `make ci-resume` should resume from step 5 (`make test`) and clear the remaining 36 steps without new findings.
- F-Thermos — fresh review agent (D30). Note: F-Thermos must run after FF-V1 lands, so the post-Thermos diff includes the Batch C cleanup-step fix; the F-Thermos base SHA recorded to `.ignorelocal/waves/prod-ready-f-thermos-base.sha` should be the FF-V1 fix tip.
- F-Reverify — fresh `wave-verifier` instance (D30), convention-11 detection with `<batch>` = `f`, re-runs F-Verify proofs against the F-Thermos base, must include the Batch C quarantine-cleanup test in its `make ci-resume` walk (already on `CI_STEPS`).
- F-PR — `wave-plan-executor` opens against `pre-0.0.1`, listing C6.2, C6.4, C14.1, C14.2, C14.3 one per line.

## FF-V1 follow-up (2026-08-07)

- **Finding:** `container-supply-chain` missing `Cleanup quarantine tags on failure` step (regression from c432710b consolidated).
- **Fix SHA:** `a4ff5ac2`
- **Test:** `test_quarantine_cleanup_runs_on_publish_and_supply_chain_failure` PASS.
- **W9 full file:** 13 passed.
- **YAML parses:** OK.
- **Status:** `changes_required` cleared → F-Final re-dispatch ready.
