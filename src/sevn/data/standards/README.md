# Conventional Commits in sevn.bot

This repository uses [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) for every git commit. Messages are **machine-readable** (changelog tooling, semver hints) and **human-readable** (clear intent in `git log`).

The **subject line** is enforced locally by a `commit-msg` pre-commit hook. Bodies and footers are optional but encouraged for context, breaking changes, and issue references.

## Subject format

```text
<type>[optional scope][optional !]: <description>
```

| Part | Rule |
|------|------|
| **type** | Required. One of: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert` |
| **scope** | Optional. Lowercase noun in parentheses, e.g. `(gateway)`, `(telegram)` |
| **!** | Optional. Marks a breaking change before `:` |
| **description** | Required. Imperative mood, **no trailing period**, whole subject ≤ 72 characters |

**Examples**

```text
feat(telegram): add restart ack after gateway reload
fix(menu): mark owner kill-switches as Ready
docs: document conventional commit setup
test(standards): cover commit-msg validator
```

**Rejected by the hook**

```text
WIP
fixed bug
feat: Added the thing.
feat:no space after colon
```

Merge commits (`Merge branch …`, `Merge pull request …`) are not validated.

Full type list, body/footer rules, and revert format: [`conventional-commits.md`](conventional-commits.md).

## Local setup

### 1. Bootstrap the repo

From a fresh clone:

```bash
make setup
```

This runs `uv sync --extra dev`, installs **both** pre-commit hook types (`pre-commit` and `commit-msg`), and installs the `sevn` CLI.

If you already ran `make setup` before Conventional Commits was added, install only the commit-msg hook:

```bash
uv run pre-commit install --hook-type commit-msg
```

### 2. Validate a message before committing

```bash
make commit-msg-check MSG='feat(gateway): short imperative summary'
```

Exit code `0` means the subject would pass the hook.

### 3. Commit

```bash
git add <paths>
git commit -m "$(cat <<'EOF'
feat(standards): add conventional commits hook

Optional body. Footers after a blank line:
Refs: #123
EOF
)"
```

The hook runs automatically on `git commit`. To bypass (discouraged on shared branches):

```bash
git commit --no-verify -m "..."
```

### 4. Pre-commit on staged Python

The usual `pre-commit` stage (Ruff, mypy, docstrings, etc.) still runs when you commit. Fix those failures first; then the `commit-msg` hook validates the message.

## Using with Cursor

Cursor loads **project skills** from `.cursor/skills/` (this path is gitignored in sevn.bot; copy or recreate the skill locally if missing).

| Item | Location |
|------|----------|
| Skill | `.cursor/skills/conventional-commit/SKILL.md` |
| When it applies | Ask the agent to **commit**, **write a commit message**, or **amend** |

**Prompt examples**

- “Commit these changes with a conventional commit message.”
- “Draft a commit message for the staged diff.”

The agent should run `git status` / `git diff`, read recent `git log --oneline`, then format the subject as `<type>[(scope)]: <description>`. It can validate with:

```bash
make commit-msg-check MSG='feat(scope): summary'
```

**Repo rules:** `CLAUDE.md` and `.cursor/rules/sevn-coding-standards.mdc` point here for Python work; commit format is documented in `CLAUDE.md` as well.

## Using with Claude Code

Claude Code reads project skills from **`.claude/skills/`** (tracked in this repo).

| Item | Location |
|------|----------|
| Skill | `.claude/skills/conventional-commit/SKILL.md` |

Same workflow as Cursor: invoke the skill when committing, validate with `make commit-msg-check`, use a HEREDOC for multi-line messages. Do not use `--no-verify` unless you explicitly allow it.

## Using with sevn.bot (gateway agent)

When the gateway has `my_sevn.repo_path` set to this git checkout, tier-B agents get a **Git commits** block in the system prompt (from `sevn.standards.conventional_commits`).

| Mechanism | How |
|-----------|-----|
| **Bundled skill** | `conventional_commit` — load with `load_skill` when the operator asks to commit |
| **Packaged standard** | `source_code/src/sevn/data/standards/conventional-commits.md` via `read` |
| **Workspace templates** | `AGENTS.md` and `sevn.bot.md` remind agents to use Conventional Commits |

**Operator prompts (Telegram / webchat)**

- “Commit the worktree changes with a proper message.”
- “What commit message should I use for this fix?”

The agent should prefer type `feat` / `fix` / `docs` / `test` matching the change, keep one logical change per commit when possible, and never bypass hooks unless you say so.

**Python API** (tools, tests, other modules):

```python
from sevn.standards.conventional_commits import (
    conventional_commits_markdown,
    conventional_commits_prompt_block,
)
```

## Reference map

| File | Purpose |
|------|---------|
| [`README.md`](README.md) | This setup guide |
| [`conventional-commits.md`](conventional-commits.md) | Normative format + examples (packaged in the wheel) |
| [`scripts/check_conventional_commit.py`](../../../../scripts/check_conventional_commit.py) | Hook validator |
| [`.pre-commit-config.yaml`](../../../../.pre-commit-config.yaml) | `sevn-conventional-commit` hook |
| [`Makefile`](../../../../Makefile) | `commit-msg-check`, `setup` |
| [`CLAUDE.md`](../../../../CLAUDE.md) | Agent notes (repo root) |

ADR detail (local `plan/`, gitignored): `plan/architecture/17-coding-standards.md` § Git & Commits.

## FAQ

**Why was my commit rejected?**
The first non-comment line must match `<type>[(scope)][!]: <description>`. Run `make commit-msg-check MSG='…'` to see errors.

**Can I use types outside the list?**
Not in this repo; extend `_TYPES` in `scripts/check_conventional_commit.py` only if the team agrees.

**Squash merge on GitHub?**
The squash commit title should still follow Conventional Commits.

**Revert?**
Use `revert: <summary>` and cite SHAs in the body (`Refs: abc1234`).
