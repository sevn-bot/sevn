#!/usr/bin/env bash
# Block `git clean -x`/`-X` in sevn.bot. Prefer inline alias from install_git_guards.sh
# (survives deletion of this file). Re-run: make install-git-guards
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

for arg in "$@"; do
  case "$arg" in
    -*) ;;
    *) continue ;;
  esac
  if [[ "$arg" == *x* ]] || [[ "$arg" == *X* ]]; then
    cat >&2 <<EOF
BLOCKED: git clean with -x or -X in $(basename "$repo_root")

Deletes gitignored local-only trees: plan/ specs/ prd/ examples/ prompts/ …

Safe: git clean -fd  |  git clean -fd -- path/

Reinstall guard: make install-git-guards
EOF
    exit 1
  fi
done

exec git -c "alias.clean=" clean "$@"
