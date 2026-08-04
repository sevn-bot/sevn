#!/usr/bin/env bash
# Restore gitignored operator trees from the last good local snapshot (2026-08-01 13:30).
# Add-only — never passes --delete to rsync.
set -euo pipefail

SNAP="${SEVN_RESTORE_SNAP:-$HOME/.sevn-local-backups/sevn.bot/snapshots/sevn-20260801-133009}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -d "$SNAP/.ignorelocal" ]]; then
  echo "restore-operator-snapshot: missing snapshot at $SNAP" >&2
  exit 1
fi

echo "restore-operator-snapshot: source=$SNAP"
echo "restore-operator-snapshot: dest=$REPO"

mkdir -p "$REPO/.ignorelocal" "$REPO/spec-kit-wave" "$REPO/.cursor"

rsync -a --ignore-existing "$SNAP/.ignorelocal/" "$REPO/.ignorelocal/"
rsync -a --ignore-existing "$SNAP/spec-kit-wave/" "$REPO/spec-kit-wave/"
rsync -a --ignore-existing "$SNAP/.cursor/" "$REPO/.cursor/"
[[ -d "$SNAP/.claude" ]] && rsync -a --ignore-existing "$SNAP/.claude/" "$REPO/.claude/" || true
[[ -f "$SNAP/CLAUDE.md" ]] && rsync -a --ignore-existing "$SNAP/CLAUDE.md" "$REPO/" || true

chmod +x "$REPO/.cursor/hooks/destructive-fs-gate.sh" 2>/dev/null || true
chmod +x "$REPO/.cursor/hooks/git-pr-gate.sh" 2>/dev/null || true
chmod +x "$REPO/scripts/destructive_fs_gate.sh" 2>/dev/null || true

cd "$REPO"
bash scripts/install_git_guards.sh

echo "restore-operator-snapshot: done"
echo "  .ignorelocal: $(find "$REPO/.ignorelocal" -type f | wc -l | tr -d ' ') files"
echo "  spec-kit-wave: $(find "$REPO/spec-kit-wave" -type f ! -path '*/.venv/*' | wc -l | tr -d ' ') source files"
echo "  .cursor: $(find "$REPO/.cursor" -type f | wc -l | tr -d ' ') files"
