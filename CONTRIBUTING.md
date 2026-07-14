# Contributing to sevn

Thanks for your interest in the project. This guide covers the basics for building,
testing, and submitting changes.

> Security issues: **do not** open a public issue — see [`SECURITY.md`](SECURITY.md).

## Prerequisites

- **Python 3.12+**
- [**uv**](https://docs.astral.sh/uv/) for dependency and environment management
- **make** and **git**

## Setup

```bash
make setup
```

This syncs dependencies into a local virtualenv, installs native libraries and
pre-commit hooks, and puts the `sevn` CLI on your PATH. Run `make help` for the full
list of targets.

## Development workflow

- **Format / lint** touched Python: `make lint`
- **Type-check** touched Python: `make typecheck`
- **Full pre-merge gate** (local): `make ci`
- **PR CI** (GitHub Actions): the same step set as `make ci` **minus** `security`
  (bandit + pip-audit). Those run daily in
  [`.github/workflows/ci-supplementary.yml`](.github/workflows/ci-supplementary.yml)
  and post-merge in `ci-cd.yml`, not on every PR.

Run `make ci` on a clean tree before opening or updating a PR. Locally that includes
the `security` tier; the PR workflow runs lint, type-check, tests, and docs drift
gates only.

## Commits

This repo follows [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/),
enforced by a `commit-msg` hook. Validate a subject before committing:

```bash
make commit-msg-check MSG='feat: add proxy egress allowlist'
```

Commits may include a **Developer Certificate of Origin** sign-off (`git commit -s`);
there is no in-tree hook enforcing DCO today.

Do not bypass hooks with `--no-verify`.

## Pull requests

- Branch off `main` and open a PR against `main`.
- PRs are **squash-merged**; keep the PR title Conventional-Commit-shaped (it becomes
  the squash commit subject).
- Every PR requires review from a code owner and must have its conversations resolved
  before merge. `main` is protected (linear history, no force-push).
- CI must pass. For PRs opened from a fork, a maintainer must approve the workflow run
  before CI executes.

## Changelog policy

Code changes under `src/sevn/**` or `scripts/**` require a matching entry in the
`## [Unreleased]` section of [`CHANGELOG.md`](CHANGELOG.md) (Keep a Changelog format —
one of `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`).

- Enforced in two places. Locally, a `commit-msg` hook checks your **staged** changes
  (the code and the entry go in the same commit); in CI, `make changelog-check` (the
  `ci-docs` tier of `make ci`) checks the branch against its base. Tests, docs, and
  `*.md` changes are exempt.
- To bypass a change that genuinely needs no entry, add a `changelog: skip` trailer to
  the commit message (or set `SEVN_CHANGELOG_SKIP=1` for the local hook).
- Commit subject rules and changelog expectations live in
  [`src/sevn/data/standards/README.md`](src/sevn/data/standards/README.md).
  A local-only `changelog` agent skill may exist under `.claude/skills/` on your
  machine but is not shipped in the public clone. Use `make changelog-eval` for the
  (advisory, non-CI) LLM quality score.

## License

By contributing, you agree that your contributions are licensed under the repository's
[MIT License](LICENSE).
