# mergeCraft review memory — sevn.bot

Durable, cross-PR context for the mergeCraft reviewer. Loaded from
`.mergecraft/learnings.md` in the checked-out workspace on every run
(`config/settings.load_learnings`).

**This file must stay committed.** In CI the reviewer's write-back path
(`utils/learnings.persist_learnings`) targets `$GITHUB_WORKSPACE/.mergecraft/learnings.md`
on the ephemeral runner, and the workflow sets `push: disabled` — so anything the
reviewer "learns" during an Action run is discarded when the job ends. Committing
this file by hand is the only way review memory survives between PRs. Add entries
here yourself when a review lesson is worth keeping.

## Repository conventions

- Recurring commands go through **Make**, never raw `uv run pytest` / `ruff` / `mypy`
  ([`about-sevn.bot/specs/00-foundation.md`](../about-sevn.bot/specs/00-foundation.md) §2.1).
  A PR that adds a raw invocation to a documented flow is a real finding; a PR that
  calls one inside a Makefile recipe is not.
- Commits follow Conventional Commits 1.0.0, enforced by the `commit-msg` hook.
- Actions must be pinned to a full-length commit SHA — sevn-bot enforces
  `sha_pinning_required`, so a branch or tag ref fails at action-resolution time.
- `git clean -x` / `-X` is forbidden in this checkout; `bin/git` on PATH blocks it.
  Flag any script or doc that reintroduces those flags.

## Review scope

- The reviewer runs with `shell: disabled`, so `staticChecks` never execute in CI.
  Do not report a lint/typecheck/test result as if it were observed — the workflow
  passes the real CI outcome into the prompt instead, and that is the only
  mechanical signal available.
- The Action image ships no `make` and no analyzer toolchain, and the checkout is
  shallow with no guaranteed base ref.

## Withdrawn review findings (known non-issues)

Findings the author refuted and mergeCraft accepted. Consult this section before
re-raising anything that looks similar; re-raising a withdrawn finding is noise.

_(none yet — add an entry when a pushback is accepted, with the PR number, the
finding as it was originally phrased, and the reason it was wrong.)_
