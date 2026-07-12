---
name: conventional_commit
description: >-
  Draft git commit messages using Conventional Commits 1.0.0. Use when the
  operator asks to commit, record changes in git, or before running git commit
  after editing code (including the sevn.bot checkout).
version: "1.0.0"
---

# conventional_commit skill

Use [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) for every commit.

## Subject (enforced on sevn.bot checkout)

```text
<type>[optional scope][optional !]: <description>
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

Rules:

- Imperative description, no trailing period
- Subject line ≤ 72 characters
- One logical change per commit when possible

## Packaged standard

Read `source_code/src/sevn/data/standards/conventional-commits.md` from the workspace mirror, or use `read` on the workspace copy if the operator synced standards.

## Workflow

1. Inspect `git status` and `git diff`.
2. Draft subject (+ optional body/footers).
3. On sevn.bot repo: operator may run `make commit-msg-check MSG='...'` before commit.
4. Commit with HEREDOC; never `--no-verify` unless the operator explicitly allows it.

## Examples

```text
feat(gateway): add commit-msg hook for conventional commits
fix(triage): handle empty tool result without retry storm
docs: document conventional commit skill paths
revert: roll back experimental menu layout

Refs: abc1234
```
