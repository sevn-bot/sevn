#!/usr/bin/env bash
# Install PATH git wrapper + record real git path (alias.clean is ignored for built-ins in Git 2.53+).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

chmod +x bin/git scripts/git_clean_guard.sh 2>/dev/null || true

real_git="$(PATH="${PATH//${repo_root}/bin:/}" command -v git)"
git_dir="$(git rev-parse --git-dir)"
printf '%s\n' "$real_git" > "${git_dir}/sevn-real-git-path"

# Prepend repo bin/ so `git` resolves to bin/git (blocks clean -x/-X).
if [[ -f .envrc ]]; then
  if ! grep -q 'sevn.bot bin/git guard' .envrc 2>/dev/null; then
    cat >> .envrc <<'EOF'

# sevn.bot bin/git guard (make install-git-guards)
export PATH="$PWD/bin:$PATH"
EOF
  fi
else
  cat > .envrc <<'EOF'
# sevn.bot bin/git guard (make install-git-guards)
export PATH="$PWD/bin:$PATH"
EOF
fi

# Best-effort alias (ignored by Git 2.53+ for built-in clean; kept for older git).
git config --local alias.clean \
  '!f() { for a in "$@"; do case "$a" in -*) case "$a" in *x*|*X*) echo "BLOCKED: git clean -x/-X (see CLAUDE.md)" >&2; return 1;; esac;; esac; done; git -c alias.clean= clean "$@"; }; f' 2>/dev/null || true

echo "install-git-guards: PATH -> bin/git (real git: $real_git)"
echo "  direnv: allow once if prompted"
echo "  manual: export PATH=\"$repo_root/bin:\$PATH\""
echo "  test:   PATH=\"$repo_root/bin:\$PATH\" git clean -fdx  # must print BLOCKED"

# --- pre-push snapshot of local-only gitignored trees -----------------------------------
# Backs up plan/specs/prd/.cursor/.claude/... before every push of a feature branch
# (i.e. before opening a PR to test-pre). Restore point survives a future git clean -fdx.
chmod +x scripts/snapshot_local.sh 2>/dev/null || true
hooks_dir="$(git rev-parse --git-path hooks)"
hook="${hooks_dir}/pre-push"
if [[ -f "$hook" ]] && ! grep -q 'snapshot_local.sh' "$hook" 2>/dev/null; then
  printf '\n# sevn.bot snapshot-local (make install-git-guards)\n"%s/scripts/snapshot_local.sh" || true\n' \
    "$repo_root" >> "$hook"
  echo "install-git-guards: appended snapshot-local to existing pre-push hook"
else
  cat > "$hook" <<'HOOK'
#!/usr/bin/env bash
# sevn.bot pre-push: snapshot local-only gitignored trees before a push (e.g. before a
# PR to test-pre). Installed by scripts/install_git_guards.sh. Never blocks a push.
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo)"
case "$branch" in
  test-pre|main|master) exit 0 ;;  # don't snapshot when pushing base branches themselves
esac
[[ -x "$repo_root/scripts/snapshot_local.sh" ]] && "$repo_root/scripts/snapshot_local.sh" || true
exit 0
HOOK
  chmod +x "$hook"
  echo "install-git-guards: pre-push snapshot hook installed (.git/hooks/pre-push)"
fi
