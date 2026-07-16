#!/usr/bin/env bash
# Snapshot local-only, gitignored trees that `git clean -fdx` (or rm -rf) would destroy
# and git cannot restore: whole ROOT TREES — .ignorelocal/, spec-kit-wave/,
# build-plan-from-review/, .cursor/, .claude/ agent config+memory+skills+commands, docs/.
#
# Also installable as a standalone launchd timer (every 3h, independent of git push) —
# see scripts/launchd/bot.sevn.snapshot-local.plist + scripts/install_snapshot_timer.sh.
#
# Strategy (Time-Machine style):
#   - rsync each path into a fresh dated snapshot under $backup_root/snapshots/
#   - --link-dest=<previous snapshot> => only CHANGED files are copied; unchanged files
#     become hardlinks to the previous snapshot (near-zero extra disk).
#   - Each snapshot is therefore a COMPLETE, restorable copy — not a fragile delta chain.
#   - NEVER uses --delete: a backup must never propagate a local deletion (that is the
#     exact disaster we guard against — a clean wipes the tree, the backup must keep it).
#
# Safe to call from a git pre-push hook: it is fast (copies only changed files) and always
# exits 0 so it can never block a push. Installed by scripts/install_git_guards.sh.
#
# Env overrides:
#   SEVN_LOCAL_BACKUP_DIR   backup root (default ~/.sevn-local-backups/sevn.bot)
#   SEVN_LOCAL_BACKUP_KEEP  dated snapshots to retain (default 40)
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root" || exit 0

backup_root="${SEVN_LOCAL_BACKUP_DIR:-$HOME/.sevn-local-backups/sevn.bot}"
snaps="$backup_root/snapshots"
keep="${SEVN_LOCAL_BACKUP_KEEP:-40}"

mkdir -p "$snaps" 2>/dev/null || { echo "snapshot-local: cannot write $snaps" >&2; exit 0; }

# High-value local-only trees (gitignored; not recoverable from git history).
# Back up whole ROOT TREES, not hand-picked subpaths — a narrow allow-list is exactly
# how an `rm -rf` of an un-enumerated sibling folder slipped past this backup before.
paths=(
  .ignorelocal
  spec-kit-wave
  build-plan-from-review
  .cursor
  .claude/agents .claude/agent-memory .claude/skills .claude/commands
  docs
)

present=()
for p in "${paths[@]}"; do [[ -e "$p" ]] && present+=("$p"); done
if [[ ${#present[@]} -eq 0 ]]; then
  echo "snapshot-local: nothing to back up (no target paths present)"
  exit 0
fi

# Skip regenerable / huge / runtime noise — and, critically, secrets. Broadening the
# trees above means we now sweep over dirs that may hold dotenv secrets and rebuildable
# indexes, so the denylist below is what keeps those out of the backup.
#
# .env carve-out: rsync applies include/exclude rules in order, FIRST match wins. The
# two --include lines therefore MUST precede the two .env --exclude lines so that
# tracked templates (.env.example, .env.proxy.example, …) are kept while real secret
# files (.env, .env.proxy, .env.local, …) are dropped.
excludes=(
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.DS_Store'
  --exclude='.venv/' --exclude='node_modules/'
  --exclude='.mypy_cache/' --exclude='.ruff_cache/' --exclude='.pytest_cache/'
  --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal'
  # keep dotenv TEMPLATES (tracked docs) ...
  --include='.env.example' --include='.env.*.example'
  # ... but never back up real dotenv SECRETS
  --exclude='.env' --exclude='.env.*'
  # regenerable / huge index dirs pulled in by the broadened trees
  --exclude='graphify-out/'
  --exclude='MyCodeGraph/'
  --exclude='.understand-anything/'
)

latest="$(ls -1dt "$snaps"/sevn-* 2>/dev/null | head -1 || true)"
link=()
[[ -n "${latest:-}" && -d "$latest" ]] && link=(--link-dest="$latest")

snap="$snaps/sevn-$(date +%Y%m%d-%H%M%S)"
# Avoid clobbering a snapshot from the same second (e.g. two pushes back-to-back).
[[ -e "$snap" ]] && snap="$snap-$$"
mkdir -p "$snap"

# -R keeps each path's relative layout under the snapshot so it mirrors the repo.
rsync -aR "${excludes[@]}" "${link[@]}" "${present[@]}" "$snap"/ 2>/dev/null \
  || rsync -aR "${excludes[@]}" "${present[@]}" "$snap"/ 2>/dev/null \
  || true

# Prune: keep newest $keep dated snapshots.
ls -1dt "$snaps"/sevn-* 2>/dev/null | tail -n +"$((keep + 1))" | while read -r old; do
  rm -rf "$old"
done

n="$(find "$snap" -type f 2>/dev/null | wc -l | tr -d ' ')"
echo "snapshot-local: $n files -> $snap${latest:+ (changed-only vs $(basename "$latest"))}"
exit 0
