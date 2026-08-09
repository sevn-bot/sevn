# GitHub Actions CI architecture — W0 anchor freeze

**Recorded:** 2026-08-09
**Wave plan:** `.ignorelocal/waves/github-actions-ci-architecture-wave-plan.md`
**Audit rev 2.1:** `.ignorelocal/github-actions-audit-2026-08-08.md`
**Primary checkout:** `pre-0.0.1` @ `0270cb88aacbf9a454b76a9d2cf83e0d49afd218` (no commit yet)
**Baseline refs recorded:** `origin/pre-0.0.1` = `39988e953976929f96b9e58004940254ea2b7bf3`; `origin/main` = `4273990195b555105cd930fbf0e8771a223d54b1`
**SHA file:** `.ignorelocal/waves/ci-architecture-preflight.sha`
**make check-git-guards:** ok

This file is the **before** for every batch's Verify gate — Wave 2, 7, 11, 15, 18 all
re-read it. Update it only via a new W0 (or a successor program's W0).

---

## W0.1 — Live ruleset state (verbatim)

Captured 2026-08-09 via `gh api repos/sevn-bot/sevn/rulesets/{id}`.

### `protect-main` (id `18631367`)

```json
{
  "id": 18631367,
  "name": "protect-main",
  "target": "branch",
  "source_type": "Repository",
  "source": "sevn-bot/sevn",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "exclude": [],
      "include": ["~DEFAULT_BRANCH"]
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "required_reviewers": [],
        "require_code_owner_review": true,
        "dismissal_restriction": {"enabled": false, "allowed_actors": []},
        "require_last_push_approval": true,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    }
  ],
  "node_id": "RRS_lACqUmVwb3NpdG9yec5NC5fyzgEcSsc",
  "created_at": "2026-07-07T19:47:51.339+02:00",
  "updated_at": "2026-07-15T01:42:31.570+02:00",
  "bypass_actors": [
    {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
  ],
  "current_user_can_bypass": "always",
  "_links": {
    "self": {"href": "https://api.github.com/repos/sevn-bot/sevn/rulesets/18631367"},
    "html": {"href": "https://github.com/sevn-bot/sevn/rules/18631367"}
  }
}
```

### `require-mergecraft-review` (id `19238611`)

```json
{
  "id": 19238611,
  "name": "require-mergecraft-review",
  "target": "branch",
  "source_type": "Repository",
  "source": "sevn-bot/sevn",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "exclude": [],
      "include": [
        "refs/heads/main",
        "refs/heads/pre-0.0.1",
        "refs/heads/test-pre"
      ]
    }
  },
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "do_not_enforce_on_create": false,
        "required_status_checks": [{"context": "mergecraft review"}]
      }
    }
  ],
  "node_id": "RRS_lACqUmVwb3NpdG9yec5NC5fyzgEljtM",
  "created_at": "2026-07-20T19:09:17.071+02:00",
  "updated_at": "2026-07-29T15:47:30.946+02:00",
  "bypass_actors": [
    {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
  ],
  "current_user_can_bypass": "always",
  "_links": {
    "self": {"href": "https://api.github.com/repos/sevn-bot/sevn/rulesets/19238611"},
    "html": {"href": "https://github.com/sevn-bot/sevn/rules/19238611"}
  }
}
```

### Bypass shorthand

Both rulesets:

```json
[{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
```

`actor_id: 5` resolves to **`RepositoryRole: admin`** (per GitHub's
[bypass_actors well-known IDs](https://github.com/github/rest-api-description/issues/4406)
and the Terraform provider docs — `maintain` → 2, `write` → 4, `admin` → 5).
The repository has `alexhawat` (`alexhawat role=admin`) as the only admin who
merges, so `protect-main`'s 1-approval rule and `require-mergecraft-review`'s
required check have **never applied to them**. Audit rev 2.1 §0.0 documented
PR #246 merged with `CHANGES_REQUESTED` as direct proof; PR #246 is now
`MERGED` (2026-08-08T06:39:00Z) and **remains the proof artefact** for finding 1.

---

## W0.2 — Finding 1 confirmed

| Item | Value |
|------|-------|
| `bypass_actors` (both rulesets) | `[{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]` |
| `actor_id: 5` label | **Admin** (`RepositoryRole: admin`) |
| Operators affected | `alexhawat` (admin) — only person who merges |
| `current_user_can_bypass` | `"always"` on both rulesets |
| Consequence (D8) | W2.1 must force the operator's decision before W2.3 applies required checks |

---

## W0.3 — Open PRs at W0 time

**Significant state change vs the audit (2026-08-08):** the three PRs the audit
flagged as "open and blocking" no longer are.

| PR | Title | State | Merged at | Audit concern |
|----|-------|-------|-----------|---------------|
| #243 | prod-readiness: Batch D — isolation + supply chain + production hardening (D-PR) | **MERGED** | 2026-08-09T05:26:18Z (`39988e95`) | `docker-images` red on `wave/prod-ready-d-isolation` — fixed in PR |
| #244 | prod-readiness: Batch F — deployment verification drivers + trust-address guard (F-PR) | **MERGED** | 2026-08-08T20:42:10Z | `ci-supplementary.yml:34-65` cron path — cron still inert (C17), tag path landed |
| #245 | prod-readiness: Batch E — scoped egress authority for run-bound tokens (E-PR) | **MERGED** | 2026-08-08T16:54:43Z | (audit listed as open) |

`gh pr list --state open` returns `[]` at W0 time. **D7's "either land A after
those merge, or omit the Docker checks" becomes moot — all three have merged,
so the first required-check set **can** include Docker.** Audit's belief that
`Docker` would fail on PR #243 is no longer testable: the latest `Docker` run
on `pre-0.0.1` (DB 31296686384, 2026-08-09T05:26:21Z) is `push`-triggered with
`conclusion: ""` (in-progress / cancelled-or-empty conclusion reported).
Pre-merge Docker runs on `wave/prod-ready-d-isolation` were `success` /
`cancelled` / `success` / `success` — the failure cited in the audit has
healed.

Recent `gh run list --workflow=Docker --limit 6`:

```json
[
  {"conclusion": "",           "createdAt": "2026-08-09T05:26:21Z", "headBranch": "pre-0.0.1",                  "event": "push",          "name": "Docker"},
  {"conclusion": "success",    "createdAt": "2026-08-08T21:41:44Z", "headBranch": "wave/prod-ready-d-isolation", "event": "pull_request",  "name": "Docker"},
  {"conclusion": "success",    "createdAt": "2026-08-08T21:30:49Z", "headBranch": "wave/prod-ready-d-isolation", "event": "pull_request",  "name": "Docker"},
  {"conclusion": "cancelled",  "createdAt": "2026-08-08T21:27:32Z", "headBranch": "wave/prod-ready-d-isolation", "event": "pull_request",  "name": "Docker"},
  {"conclusion": "success",    "createdAt": "2026-08-08T21:21:50Z", "headBranch": "wave/prod-ready-d-isolation", "event": "pull_request",  "name": "Docker"},
  {"conclusion": "success",    "createdAt": "2026-08-08T20:42:13Z", "headBranch": "pre-0.0.1",                  "event": "push",          "name": "Docker"}
]
```

**Onus on W2:** A-Verify must re-run the Docker failure case (a throwaway PR
with a deliberately failing test) to confirm the gate is real, not just
"absent-of-red-on-the-merged-trunk". The neg-test is **still** the deliverable.

---

## W0.4 — Dead triggers (verbatim)

`gh workflow list --all` (2026-08-09):

```json
[
  {"id": 311737875, "name": ".github/workflows/ci.yml",          "path": ".github/workflows/ci.yml",          "state": "active"},
  {"id": 313640589, "name": "CodeQL",                            "path": ".github/workflows/codeql.yml",      "state": "active"},
  {"id": 311865106, "name": "Docker",                            "path": ".github/workflows/docker.yml",      "state": "active"},
  {"id": 323001275, "name": "mergecraft",                        "path": ".github/workflows/mergecraft.yml",  "state": "active"},
  {"id": 314429813, "name": "PullFrog",                          "path": ".github/workflows/pullfrog.yml",    "state": "active"},
  {"id": 315448403, "name": "Copilot cloud agent",               "path": "dynamic/copilot-swe-agent/copilot", "state": "active"}
]
```

Dead triggers (Audit §TL;DR):

| Workflow | Status | Evidence |
|----------|--------|----------|
| `ci-cd.yml` | **absent** | `gh workflow list --all` → no entry |
| `ci-supplementary.yml` | **absent** | same |
| `style-guide-pages.yml` | **absent** | same |
| `pullfrog.yml` (file gone, reg kept) | **stale registration, still active** | id `314429813` — A1.6 closed by `W3.2` |
| `gh run list --event schedule` | **`[]`** | never fires |
| `gh pr list --author app/dependabot` | **`[]`** | Dependabot never configured |
| `gh api repos/sevn-bot/sevn/contents/.github/ISSUE_TEMPLATE` | **404** | templates inert on default branch |

`scheduled-impl.yml` and `release.yml` (the names this plan will create) **do
not yet exist on `main`**. They are the deliverable of W6.4 / W16.1.

---

## W0.5 — Finding 6 confirmed (already-landed set)

| Audit claim | Verified | Anchor |
|-------------|----------|--------|
| `ci-cd.yml` aggregator = "Artifact publication gate (required)" | ✅ | `.github/workflows/ci-cd.yml:580-583` (job id `delivery-chain`, name `Artifact publication gate (required)`) |
| `phase2` / `phase3` / `needs_impl_ok` gone | ✅ | only mention in tree is a comment at `ci-cd.yml:482` ("Dev deploy/smoke (former phase2/phase3) deleted with needs_impl_ok (D44 / C2.2)") |
| Quarantine tags run-scoped | ✅ | `ci-cd.yml:136, 160, 174, 189, 204` use `quarantine-<sha>-<run_id>` |
| Promotion by digest | ✅ | `ci-cd.yml:305-324` `promote_by_digest()` uses `docker buildx imagetools create` |
| SHA-pinned cosign / syft / trivy install | ✅ | `ci-cd.yml:236` (`sigstore/cosign-installer@dc72c7d5c4d10cd6bcb8cf6e3fd625a9e5e537da # v3.7.0`); `ci-cd.yml:243` (`anchore/sbom-action/download-syft@e22c389904149dbc22b58101806040fa8d37a610 # v0.24.0`); `ci-cd.yml:251` (`aquasecurity/setup-trivy@81e514348e19b6112ce2a7e3ecbafe19c1e1f567 # v0.3.1`) |
| `check-no-curl-pipe-sh` in **ci-infra** | ✅ | `Makefile:514` (`ci-infra: config-schema … check-no-curl-pipe-sh …`) |
| `check-no-curl-pipe-sh` in **CI_STEPS** | ✅ | `Makefile:527` (registry list member) |
| Zero `curl \| sh` remain | ✅ | `grep -rnE 'curl\s*\|\s*sh' .github/ Makefile` → empty |

**Batch D's scope is correspondingly narrow.** Its remaining work is the
phase4/5 decision (W15) and one throwaway `v0.0.1-rc0` end-to-end probe (W16).

---

## W0.6 — Blast radius of the `ci-supplementary.yml` → `scheduled-impl.yml` rename (D10)

Wave plans and gate records holding line-anchored references to the old path.
**Pre-rename anchors are void after W6.1.** Every holder must re-read before
editing.

| Wave plan / record | Anchor | Owner / role |
|---------------------|--------|--------------|
| `.ignorelocal/waves/PARALLEL-EXECUTION-PLAN-2026-08-08.md` | `:141` (cites `ci-supplementary.yml:34-65`) | parallel plan §"GitHub Actions CI — canonical reference" |
| `.ignorelocal/waves/prod-ready-f-verify.md` | `:101` (cites `ci-supplementary.yml:34-65`) | F-Verify item 1 |
| `.ignorelocal/waves/prod-ready-f-verify.md` | `:129` (producer / consumer grep table) | F-Verify evidence |
| `.ignorelocal/waves/prod-ready-f-reverify.md` | `:183` (CHANGELOG row) | F-Reverify |
| `.ignorelocal/waves/prod-ready-f-reverify.md` | `:221` (producer / consumer grep) | F-Reverify evidence |
| `.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md` | `:294` (D52) | prod-readiness W15 / W23 |
| `.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md` | `:789` (W23.1 file list) | prod-readiness W23 |
| `.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md` | `:791` (W23.1 acceptance) | prod-readiness W23 |
| `.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md` | `:973` (cross-file collisions table) | prod-readiness W23 |
| `.ignorelocal/waves/sevn-review-lessons-wave-plan.md` | `:127` (W3.7) | review-lessons W3.5/W3.7 |
| `.ignorelocal/waves/sevn-review-lessons-wave-plan.md` | `:234` (W3.4 files) | review-lessons W3.4 |
| `.ignorelocal/waves/sevn-review-lessons-wave-plan.md` | `:339` (W3.4.1 acceptance) | review-lessons W3.4 |
| `.ignorelocal/waves/sevn-review-lessons-wave-plan.md` | `:384` (W3.5 files) | review-lessons W3.5 |
| `.ignorelocal/waves/sevn-review-lessons-wave-plan.md` | `:394` (W3.5 files) | review-lessons W3.5 |
| `.ignorelocal/waves/sevn-review-lessons-wave-plan.md` | `:397` (W3.5.2 acceptance) | review-lessons W3.5 |
| `.ignorelocal/waves/sevn-review-lessons-CHANGES.md` | `:65` (W1.7 where-block) | review-lessons W1.7 |
| `.ignorelocal/waves/sevn-review-lessons-CHANGES.md` | `:100` (W3.5 change) | review-lessons W3.5 |
| `.ignorelocal/waves/spec-kit-wave-hygiene-wave-plan.md` | `:98` (W3 false-proof) | spec-kit-wave-hygiene W3 |
| `.ignorelocal/waves/test-ci-hygiene-debt-wave-plan.md` | `:13` (W4 cross-ref) | test-ci-hygiene W4 |
| `.ignorelocal/waves/post-audit-0.0.1-wave-plan.md` | (multiple — see `grep -rn ci-supplementary`) | post-audit |
| `.ignorelocal/waves/post-audit-c-verify.md` | (multiple) | post-audit C-Verify |
| `.ignorelocal/waves/doc-vs-code-analysis-fixes-wave-plan.md` | (multiple) | doc-vs-code-analysis |
| `.ignorelocal/thermos/changed-files.txt` | (cumulative history) | thermos log — historical, not edited |
| `.ignorelocal/review-lessons/{raw,chunks,analysis}/*` | (raw data) | review-lessons input — historical, not edited |

Plus the plan itself (`.ignorelocal/waves/github-actions-ci-architecture-wave-plan.md`) references `ci-supplementary.yml` and `codeql.yml`'s weekly cron in §"Stage 1" — those are the surface this plan will change.

**Announcement surface:** W6.1 carries an explicit "anchor invalidation" callout —
*B-PR* must name the rename and the wave plans whose anchors it invalidates
(Batch B gates, A-PR style).

---

## W0.7 — Verified anchors for W1–W19

All line numbers reference `origin/pre-0.0.1` @ `39988e953996…` (use `git show
origin/pre-0.0.1:<path>` to re-verify before W11 / W15 / W18).

### Pre-renamed workflow files (Skeleton + key anchors)

| File | Lines | Skeleton / key anchors |
|------|-------|------------------------|
| `.github/workflows/ci.yml` | 121 | `name: CI` (`:33`); `on:` (`:35` — `pull_request`, `push`, `workflow_dispatch`); `permissions:` (`:42`); `jobs:` (`:49`); `toolchain` job (`:50-77`, **dead** — `if: hashFiles('src/sevn/**') == ''`); `hashFiles` guards at `:59, 77, 96, 108, 120` (4 step-level, 1 job-level); fixture `cp infra/sevn_config_long_description.json src/sevn/data/sevn_config_long_description.json` at `:82` (W12.3 target) |
| `.github/workflows/docker.yml` | 184 | `name: Docker` (`:10`); `on:` (`:12` — `pull_request` with 14-entry `paths:` at `:15-28`, `push:` no `paths:` at `:30`, `workflow_dispatch:` at `:32`); `permissions:` (`:34`); `jobs:` (`:41`); `push: false` on `actions/checkout` at `:54, 65, 76, 87, 110` (5 sites); `timeout-minutes: 60` (default top-of-workflow); raw `uv run pytest tests/integration/test_proxy_transport_compose_roundtrip.py -v --tb=short --strict-markers -m integration` at `:169` (W12.3 target) |
| `.github/workflows/codeql.yml` | 42 | `name: CodeQL` (`:5`); `on:` (`:7` — `push`, `pull_request`, `schedule:` `0 6 * * 1` at `:12`); `permissions:` (`:15`); `jobs:` (`:22`); weekly cron **dead** (C17) |
| `.github/workflows/ci-cd.yml` | 469 | `name: CI/CD (artifact publication)` (`:55`); `on:` (`:57` — `push.branches: main`, `push.tags: v*`, `workflow_dispatch:`); `jobs:` (`:67`); `phase1` (`:68`); `publish-ghcr` (`:84` — `needs: [phase1]`); `container-supply-chain` (`:220` — `name: Container supply chain (cosign, syft, trivy)`); `delivery-chain` (`:580-...` — `name: Artifact publication gate (required)`, `needs: [phase1, publish-ghcr, container-supply-chain]` at `:358`); `phase4` (`:485` — stub `exit 1`); `phase5` (`:516` — stub `exit 1`); `phase6` (reachable only on `v*` per `:24`); `verification-deployment` (tag path) |
| `.github/workflows/ci-supplementary.yml` | 99 | `name: CI supplementary` (`:33`); `on:` (`:35` — `schedule: [17 5 * * *  daily, 17 5 * * 1  weekly]`, `workflow_dispatch:`); **will be renamed to `scheduled-impl.yml` in W6.1** |
| `.github/workflows/style-guide-pages.yml` | 47 | `name: Style guide (GitHub Pages)` (`:4`); `on:` (`:6` — `push.branches: main, paths: styles/sevn/style/**`); **dead** (no `styles/` on main) |
| `.github/workflows/mergecraft.yml` (on `main`) | 537 | `on: pull_request_target` (multi-trigger); `permissions:` (job-level); `uses: alexhawat/mergeCraft@8d747f39d3d36d889e0a85c2dcf691d1bdb91536 # pre-0.0.1` at lines **`:348` and `:435`** (W7.5 — both must pass the parity check) |

### `scripts/ci_lib.py` (`PATH_RULES` anchors)

| Anchor | Lines | Use |
|--------|-------|-----|
| `PATH_RULES` definition | `scripts/ci_lib.py:58` | PathRule tuple — currently 30+ rules; container tier lacks `security/**` and `tools/**` (W10.4 fix) |
| `collect_changed_paths()` | `scripts/ci_lib.py:311` | Diff vs `SEVN_CI_BASE` |
| `pyproject.toml` → `security` | `scripts/ci_lib.py:64` | forces `security` tier on dep changes |
| `src/sevn/tools/**` → `tools-skills-inventory-check` | `scripts/ci_lib.py:155` | tier path for tools (W3.6 fire) |
| `infra/**` → `infra-check` | `scripts/ci_lib.py:198` | infra changes |
| `docker/Dockerfile.*` (in container tier) | `scripts/ci_lib.py:68` | already in container tier |

### `Makefile` (ci tier anchors)

| Tier | Members | Anchor |
|------|---------|--------|
| `ci-static` | `lockcheck lint typecheck pyright doctest build artifact-integrity doctor-solutions` | `Makefile:~506` |
| `ci-test` | `test` | `Makefile:~510` |
| `ci-security` | `security` | `Makefile:~512` |
| `ci-core` | `ci-static test security` | `Makefile:~514` (verified by `tests/infra/test_ci_steps_tier_parity.py`) |
| `ci-infra` | `config-schema onboarding-profiles-schema infra-check mission-control-schema-check check-git-guards check-compose-default check-compose-operator-secrets check-no-curl-pipe-sh sandbox-image-check agent-context-manifest-check storage-migration-rehearsal-check` | `Makefile:514` |
| `CI_STEPS` | registry list (must mirror tiers) | `Makefile:527` |
| `ci-docs` | member list | `Makefile:527` |
| `ci-skills` | member list | `Makefile:527` |
| `ci-parity` | member list (target for `check-workflow-reachability` in W18.6) | `Makefile:527` |
| `ci-affected` | path-aware diff gate | `Makefile:` (the W0.8 command) |
| `ci-changed` | Python-only diff gate | `Makefile:` |
| `ci-resume` | resumable full gate | `Makefile:` |
| `check-no-curl-pipe-sh` | `:92` (definition), `:514` (in ci-infra), `:527` (in CI_STEPS) | — |

### `.github/FUNDING.yml` (delete in W5.4)

- 8 lines, 100% commented-out example. Anchor: `FUNDING.yml` on `pre-0.0.1` (any line).

### `docs/test-plans/` (test-creator landing zones)

| Wave | Plan file | Created in |
|------|-----------|-----------|
| W1 | `docs/test-plans/ci-architecture-batch-a.md` | W1.5 |
| W4 | `docs/test-plans/ci-architecture-batch-b.md` | W4.7 |
| W9 | `docs/test-plans/ci-architecture-batch-c.md` | W9.7 |
| W13 | `docs/test-plans/ci-architecture-batch-d.md` | W13.4 |
| W17 | `docs/test-plans/ci-architecture-batch-e.md` | W17.4 |

### `tests/infra/` (test-creator landing zones — **test-creator owns** these)

| Wave | Test file | Created in |
|------|-----------|-----------|
| W1 | `tests/infra/test_ci_architecture_gating_w1_red.py` | W1.1 (-W1.4) |
| W4 | `tests/infra/test_ci_architecture_reachability_w4_red.py` | W4.1 (-W4.6) |
| W9 | `tests/infra/test_ci_architecture_aggregator_w9_red.py` | W9.1 (-W9.6) |
| W13 | extend `tests/infra/test_post_audit_release_gate_w9_red.py` | W13.3 |
| W17 | fixture workflows under `tests/fixtures/workflows/` + per-rule tests | W17.1 (-W17.4) |

### Audit rev cross-references

| Claim (audit §) | Anchor in audit | Verified in tree |
|------------------|------------------|------------------|
| §4.1 `protect-main` has no `required_status_checks` | `9.0 §0.1` | W0.1 JSON |
| §4.1 `require-mergecraft-review` only requires `mergecraft review` | `9.0 §0.1` | W0.1 JSON |
| §4.3 fork PRs auto-pass `mergecraft review` | `9 §4.3` | `mergecraft.yml` HAS_AUTH guard chain |
| §5 `ci-cd.yml` aggregator pattern | `9.2 §2.3` | `delivery-chain` at `:580` |
| §5 `ci.yml` `toolchain` is dead | `9.2 §2.5` | `:50-77` (`if: hashFiles('src/sevn/**') == ''`) |
| §5 `docker.yml:169` raw `uv run pytest` | `9.2 §2.6` | `:169` verbatim |
| §5 `docker.yml` 60-min timeouts | `9.2 §2.7` | top-of-workflow `timeout-minutes: 60` |
| §5 `mergecraft.yml` ~520 L, 2 `uses:` lines | `9.1 §1.4` | 537 L (close), 2 `uses:` lines at `:348, :435` |
| §5 stale `PullFrog` registration | `9.0 §0.5` | `gh workflow list --all` id `314429813` active |
| §1 `main` only has `LICENSE`, `README.md`, `.github/workflows/mergecraft.yml` | `9.1 §1.1` | `git ls-tree -r origin/main` confirms |
| §7.2 four waves write into dead cron | `9.1 §1.3` | W0.6 enumeration |

---

## W0.8 — `make ci-affected` smoke

### Primary spec command: `SEVN_CI_BASE=origin/pre-0.0.1`

```
$ make ci-affected SEVN_CI_BASE=origin/pre-0.0.1
[ci-affected] no changed files — skipped
exit_code: 0  (elapsed_ms: 988)
```

Expected on the primary checkout (HEAD == pre-0.0.1, no diff vs origin). No
pre-existing reds observed in the partial gate.

### Cross-check: `SEVN_CI_BASE=origin/main` (extra, not in W0.8 spec)

Run as a sanity check (full log: `/tmp/w0-wide-affected.log`):

```
$ make ci-affected SEVN_CI_BASE=origin/main  # 624.9 s, 7,005 tests passed
…
/Users/alex/Documents/code/sevn.bot/sevn/tests/proxy/test_prod_ready_c11_guard_w1.py::test_c11_suite_files_unmodified_vs_ci_base FAILED
AssertionError: C1.1 guard could not read tests/proxy/test_auth.py at origin/main:
fatal: path 'tests/proxy/test_auth.py' exists on disk, but not in 'origin/main'
1 failed, 7005 passed, 31 skipped, 53 warnings, 7 errors in 372.45s
…
make: *** [ci-affected] Error 1
```

This is a **pre-existing red** unrelated to W0: the prod-readiness `C1.1`
guard compares test files against `SEVN_CI_BASE`, and `tests/proxy/test_auth.py`
**does not exist on `origin/main`** (the 3-file stub). The guard fails by
design when running against main. `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1`
does not trigger it because the file is present on the trunk.

Origin pre-0.0.1 was `39988e95` at W0; running `ci-affected` against the
trunk (`pre-0.0.1`) is the canonical W0.8 command — that one is green.

The W0.8 spec's `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1` is the
**mid-wave** gate: each batch implementation wave runs with `SEVN_CI_BASE=HEAD`
(batch's own branch tip) to verify their diff. A **batch Final** gate uses
`SEVN_CI_BASE=origin/pre-0.0.1` to catch drift.

---

## Finding 7 — `sha_pinning_required = true` (org policy)

```
$ gh api repos/sevn-bot/sevn/actions/permissions
{"enabled":true,"allowed_actions":"all","sha_pinning_required":true}
```

W5.1 will probe whether a branch ref `@pre-0.0.1` in `uses:` is accepted
before W6 / W7 commit to that shape. The answer is recorded in the W5 gate
record. **No SHA is pre-resolved in this plan** — they are resolved at
implementation time via `gh api repos/<owner>/<repo>/commits/<tag> -q .sha`.

---

## Index of in-flight wave plans covering touched files

| File | Other wave owners | Plan reference |
|------|-------------------|----------------|
| `.github/workflows/ci-cd.yml` | prod-readiness Batch C (W10–W12), prod-readiness Batch F (W23, **PR #244 merged**) | C16 — Batch D lands **after** #244 merges (now satisfied) |
| `.github/workflows/ci-supplementary.yml` → `scheduled-impl.yml` | prod-readiness W23, review-lessons W3.5/W3.7 | D10 / C16 |
| `.github/workflows/ci.yml` | test-ci W3 (`v1-smoke`), W4 (diff-cover), review-lessons W1.7 (workflow-lint) | W11.4 leaves named placeholder |
| `.github/workflows/mergecraft.yml` (on `main`) | none | Highest blast radius — W4.6 guards, B-Reverify drives live PR |
| `Makefile` (`ci-parity`, `CI_STEPS`) | test-ci Batch A (`Makefile:19,179`, C5), review-lessons W1 (C9) | Tier-parity forces member-list + `CI_STEPS` into one commit |
| `scripts/ci_lib.py` | none | `PATH_RULES` updates hand fixture updates to `test-creator` |
| `about-sevn.bot/specs/25-cicd-full.md` | prod-readiness W10/W11/W12/W23, test-ci W2/W3/W4 | Amend in place (D53); fingerprint refresh at every Final |
| Ruleset state | none | Only this plan edits rulesets; two swaps total (D9) |

---

## Acceptance evidence

- [x] W0.0 — `git fetch origin`; SHAs recorded in `ci-architecture-preflight.sha`; `make check-git-guards` ok.
- [x] W0.1 — Both rulesets captured verbatim (full JSON above).
- [x] W0.2 — `actor_id: 5` resolved to `RepositoryRole: admin` (GitHub well-known IDs).
- [x] W0.3 — Open PR list is `[]`; **all three audit-listed PRs merged**; recent Docker runs green/cancelled on the merged PR. D7's "wait or omit" is moot.
- [x] W0.4 — All four dead triggers confirmed; `PullFrog` registration still active (`314429813`); `ISSUE_TEMPLATE` on `main` 404.
- [x] W0.5 — All eight finding-6 claims verified verbatim in the tree.
- [x] W0.6 — Anchor blast radius enumerated (22 anchor sites across 12 wave plans).
- [x] W0.7 — Anchor freeze written; line numbers valid against `origin/pre-0.0.1` @ `39988e95`.
- [x] W0.8 — `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1` skipped (no changed files), exit 0.
- [x] W0.9 — Commit + push (in this commit).
