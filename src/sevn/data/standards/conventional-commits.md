# Conventional Commits (sevn.bot)

This repository uses [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).
The `commit-msg` pre-commit hook enforces the **subject line** format below.

**Setup and agent usage:** see [`README.md`](README.md) in this directory.

## Subject format

```text
<type>[optional scope][optional !]: <description>
```

- **type** (required): one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
- **scope** (optional): lowercase noun in parentheses, e.g. `(gateway)`, `(telegram)`, `(menu)`
- **!** (optional): marks a breaking change when placed before `:`
- **description** (required): imperative, concise summary; **no trailing period**; keep the full subject ≤ 72 characters

## Types (when to use)

| Type | Use for |
|------|---------|
| `feat` | New user-facing or operator-facing capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, whitespace, no logic change |
| `refactor` | Code change that is neither feat nor fix |
| `perf` | Performance improvement |
| `test` | Tests only |
| `build` | Build system or dependencies |
| `ci` | CI configuration |
| `chore` | Maintenance (deps, tooling) with no production logic change |
| `revert` | Revert a prior commit |

## Body and footers (optional)

After a blank line, add paragraphs for context. Footers use git-trailer style:

```text
fix: prevent racing of requests

Introduce a request id and dismiss stale responses.

Reviewed-by: Z
Refs: #123
```

Breaking changes: use `!` in the subject **or** a `BREAKING CHANGE: <description>` footer (uppercase token).

## Reverts

```text
revert: let us never again speak of the noodle incident

Refs: 676104e, a215868
```

## Good examples (this repo)

```text
feat(telegram): add restart ack after gateway reload
fix(menu): mark owner LLM-guard kill-switches as Ready
docs: align Telegram Menu.html with live keyboards
test(gateway): cover commit-msg hook for conventional commits
chore: sync pre-commit hook revisions
```

## Bad examples

```text
Updated stuff
WIP
fixed bug
feat: added the thing.
feat:This is missing a space after the colon
```

## Skipped by the hook

Git merge commits (`Merge branch …`, `Merge pull request …`) are not validated.

## Agents and humans

- Before `git commit`, read this file or load the **`conventional_commit`** skill (`load_skill`).
- Cursor: `.cursor/skills/conventional-commit/SKILL.md`
- Claude Code: `.claude/skills/conventional-commit/SKILL.md`
- Validate locally: `make commit-msg-check MSG='feat: example'`
