# 0003. Craft release management evaluation and runbook

**Status:** Accepted (evaluation + scaffold); Craft CI adoption **deferred** (plan D10 operator gate)
**Date:** 2026-08-01
**Source:** [#110 — Use Craft for release management](https://github.com/sevn-bot/sevn/issues/110) · [getsentry/craft](https://github.com/getsentry/craft)

---

# Release management — maintainer runbook

Maintainer guide for cutting **sevn.bot** releases. Covers the **current** six-phase
delivery pipeline, an evaluation of [Sentry Craft](https://github.com/getsentry/craft)
([#110](https://github.com/sevn-bot/sevn/issues/110)), and dry-run instructions for
the optional `.craft.yml` scaffold added in open-issues-sweep **Wave W15** (plan **D10**:
evaluate-then-adopt — scaffold only until operator sign-off).

Normative CI/CD spec: [`about-sevn.bot/specs/25-cicd-full.md`](../specs/25-cicd-full.md).

---

## Current release flow (today)

### Pre-merge (every PR)

1. Contributors add datestamped bullets under `CHANGELOG.md` → `## [Unreleased]`.
2. `make changelog-check` (in `make ci-docs` / `make ci`) validates Keep a Changelog
   shape and Unreleased diff rules via `scripts/changelog_validate.py`.
3. Conventional Commits subjects are enforced by the commit-msg hook
   (`.claude/skills/conventional-commit`).
4. PR verify runs `.github/workflows/ci.yml` → `make ci` on gated branches
   (`main`, `develop`, `test-pre`, `pre-0.0.1`).
5. mergeCraft PR review (`.github/workflows/mergecraft.yml` on `origin/main`) is
   advisory; pin parity is enforced locally by `make mergecraft-ref-check`.

### Staging branch

Release candidates accumulate on **`pre-*`** branches (currently `pre-0.0.1`).
Wave programs merge feature branches there before a semver tag lands on `main`.

### Tag-triggered delivery (`.github/workflows/ci-cd.yml`)

Pushing a **`v*`** tag starts the six-phase pipeline:

| Phase | Job | What happens today |
|-------|-----|-------------------|
| 1 | `phase1` | `make ci` full gate on the tagged SHA |
| — | `publish-ghcr` | Builds and pushes five GHCR images (`sandbox`, `proxy`, `gateway`, `gateway.browser`, `gateway.gui`) tagged with the git tag |
| 2–3 | `phase2`, `phase3` | **Stub** — Dev deploy/smoke (main push only) |
| 4–5 | `phase4`, `phase5` | **Stub** — Production deploy/smoke |
| 6 | `phase6` | `softprops/action-gh-release` creates a GitHub Release with auto-generated notes |

**Manual steps maintainers still perform:**

- Decide semver and cut `CHANGELOG.md` `[Unreleased]` into a dated version section.
- Bump `pyproject.toml` `[project].version` (still `0.0.1` on trunk; #123 tracks richer CLI version strings separately).
- Merge staging → `main`, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
- No `make release` target exists; no PyPI publish automation is wired.

### Version surfaces

| Surface | Source |
|---------|--------|
| Package metadata | `pyproject.toml` → `importlib.metadata` / `sevn --version` (baseline) |
| Operator build id | Git branch + short SHA in Telegram `/config` Version id (see CHANGELOG 2026-07-24) |
| Container tags | `ghcr.io/sevn-bot/sevn/{sandbox,proxy,gateway,...}:vX.Y.Z` |

---

## Craft evaluation (#110)

Craft is Sentry’s CLI for **prepare → CI wait → publish** across GitHub, PyPI, Docker,
and other registries. Source: https://github.com/getsentry/craft · docs: https://craft.sentry.dev/

### What Craft would improve

| Capability | Benefit for sevn |
|------------|------------------|
| `craft prepare <version>` | Creates `release/<version>` branch, bumps `pyproject.toml` via Hatch detection, validates changelog |
| `craft publish <version>` | Orchestrates GitHub release + PyPI after CI green + artifact fetch |
| `--dry-run` / `CRAFT_DRY_RUN` | Safe rehearsal without tags, commits, or registry writes |
| `getsentry/craft@v2` Action | `workflow_dispatch` release with `version: auto` from conventional commits |
| Status / artifact providers | Wait for `make ci` workflow on the release branch before publish |

### Gaps and conflicts (why adoption is gated — D10)

| Topic | Current sevn behavior | Craft default | Mitigation if adopted |
|-------|----------------------|---------------|------------------------|
| Changelog | Keep a Changelog + datestamped `## [Unreleased]` bullets; `make changelog-check` | `auto` policy reads conventional commits / `.github/release.yml` | Keep `policy: simple` in `.craft.yml` until Unreleased workflow is redesigned |
| GitHub Release | `ci-cd.yml` phase6 on every `v*` tag | `github` target also creates release on publish | Remove phase6 **or** drop `github` target; pick one owner |
| Docker | Five bespoke Dockerfiles → GHCR in `publish-ghcr` | Single-image `docker` target | Keep GHCR job; Craft publishes wheel + GitHub tag only |
| Staging branches | `pre-0.0.1` integration branch | `release/<version>` per Craft | Document merge order: `pre-*` → `main` → Craft prepare from `main` |
| Deploy phases | Phases 2–5 stubs | Craft assumes external deploy | Unchanged — Craft does not replace future prod deploy work |
| PyPI | Not published yet | `pypi` target | Enable only when trusted publishing is configured |

### Recommendation (W15 verdict)

**Adopt Craft incrementally after operator review:**

1. ✅ **Done (W15):** `.craft.yml` scaffold + this runbook + dry-run commands below.
2. ⏸ **Operator gate:** Trial `craft prepare … --dry-run` on a maintainer machine; confirm changelog + version bump diff matches expectations.
3. ⏸ **Operator gate:** Add `getsentry/craft@v2` workflow (manual dispatch only) — do **not** remove tag-triggered `ci-cd.yml` until GHCR + phase6 ownership is decided.
4. ⏸ **Operator gate:** Add `make release-prepare` / `make release-publish` wrappers if the team wants Make-only ergonomics (explicitly out of W15 scope).

---

## `.craft.yml` scaffold

The repo root contains an evaluation-only [`.craft.yml`](../../.craft.yml) with:

- `github` target (`tagPrefix: v`)
- `pypi` target (Hatch / `pyproject.toml` bump — publish credentials not configured)
- `changelog.policy: simple` (compatible with existing Keep a Changelog gate)
- `versioning.policy: manual` (explicit version argument to `craft prepare`)

It is **not** referenced by any workflow or Makefile target.

---

## Dry-run instructions (safe testing)

Install Craft (pick one):

```bash
# npm (Volta-managed Node recommended upstream)
npm install -g @sentry/craft

# or Docker — mount repo at /work
docker run --rm -v "$PWD:/work" -w /work getsentry/craft craft -h
```

From a **full** checkout worktree (not the sparse primary tree):

```bash
git fetch origin
git checkout main   # or pre-0.0.1 after staging merges

# Inspect parsed config (no side effects)
craft config

# List configured targets
craft targets

# Rehearse prepare — no branches, commits, or file writes
craft prepare 0.0.2 --dry-run
# or: CRAFT_DRY_RUN=1 craft prepare 0.0.2

# Rehearse publish — no tags, registry uploads, or GitHub API mutations
craft publish 0.0.2 --dry-run --no-status-check

# Target-scoped dry run
craft publish 0.0.2 --dry-run -t github
```

**Expected dry-run output:** Craft logs the release branch name (`release/0.0.2`), files it
would edit (`pyproject.toml`, `CHANGELOG.md`), and targets it would invoke. Verify the
diff mentally (or redirect to a scratch worktree) before running without `--dry-run`.

**Do not** run live `craft publish` against `sevn-bot/sevn` until:

- Operator approves D10 adoption,
- `GITHUB_TOKEN` / PyPI credentials are scoped to maintainer machines or CI secrets,
- Duplicate GitHub Release creation with `ci-cd.yml` phase6 is resolved.

---

## Maintainer checklist — cutting a release (current manual flow)

Until Craft is adopted:

1. Ensure `## [Unreleased]` in `CHANGELOG.md` is complete; run `make changelog-check`.
2. Run `make ci` (or `make ci-resume`) green on the release SHA.
3. Move `[Unreleased]` entries into `## [X.Y.Z] — YYYY-MM-DD`.
4. Bump `pyproject.toml` `[project].version` to `X.Y.Z`.
5. Merge to `main` (via `pre-*` if using staging branch policy).
6. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
7. Watch `.github/workflows/ci-cd.yml` — phase1 + `publish-ghcr` + phase6 must succeed.
8. Verify GHCR images and the GitHub Release page.
9. Post release notes / operator comms as needed.

Future Craft-assisted flow (after operator gate): replace steps 3–6 with
`craft prepare X.Y.Z` → PR/CI → `craft publish X.Y.Z`, keeping steps 7–8 as verification.

---

## Related files

| File | Role |
|------|------|
| `.craft.yml` | Craft config scaffold (evaluation only) |
| `.github/workflows/ci-cd.yml` | Tag-triggered CI + GHCR + GitHub Release |
| `.github/workflows/ci.yml` | PR/full `make ci` verify |
| `CHANGELOG.md` | Keep a Changelog source of truth |
| `pyproject.toml` | Hatchling package version |
| `Makefile` | `changelog-check`, `make ci`, `mergecraft-ref-check` |
| `about-sevn.bot/specs/25-cicd-full.md` | CI/CD spec + W15 amendment row |
