# Cursor IDE — operator-local setup

The repository gitignores **`/.cursor`** (see root `.gitignore`). Cursor **agents**, **skills**, and most **rules** are operator-local and must not be committed.

## Bootstrap hooks and the D1 worktree rule

After clone, or when Cursor shell hooks are missing, copy the tracked templates into your gitignored tree:

```bash
mkdir -p .cursor/hooks .cursor/rules
cp docs/templates/cursor/hooks.json .cursor/
cp docs/templates/cursor/hooks/*.sh .cursor/hooks/
chmod +x .cursor/hooks/*.sh
cp docs/templates/cursor/rules/no-primary-checkout-work.mdc .cursor/rules/
```

Keep your existing `.cursor/agents/`, `.cursor/skills/`, and other rules alongside these files. Re-run the copy step when `docs/templates/cursor/` changes on pull.

## Guards that stay in git (not under `.cursor/`)

| Concern | Location |
|--------|----------|
| Primary-checkout commit block (D1) | `scripts/check_primary_checkout_commit.py` (pre-commit `sevn-primary-checkout-commit`) |
| Destructive `git clean -x`/`-X` and related FS gates | `scripts/destructive_fs_gate.sh` (Cursor hook wrapper delegates here) |
| PATH `git` wrapper | `bin/git`, `make install-git-guards` |

The thin hook scripts in `docs/templates/cursor/hooks/` exist so `.cursor/hooks.json` can use stable relative paths; implementation lives under `scripts/`.
