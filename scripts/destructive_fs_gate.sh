#!/usr/bin/env bash
# Block agent shell commands that wipe gitignored operator trees.
#
# Reads a Cursor `beforeShellExecution` payload on stdin ({"command": "..."}) and emits
# {"permission":"allow"} or {"permission":"deny", ...}. Wired up by .cursor/hooks.json via
# the thin wrapper .cursor/hooks/destructive-fs-gate.sh — the LOGIC lives here, tracked in
# git, because .cursor/ is gitignored and a guard that only exists in an unversioned tree
# is exactly as losable as the files it protects (see 2026-07-20, when the deletion took
# .cursor/rules/no-destructive-git-clean.mdc with it).
#
# Behaviour is pinned by scripts/test_destructive_fs_gate.sh — run it after any edit.
#
# Fingerprint we already lost to (2026-07-20): `rsync -a --delete` of a sparse tree onto
# spec-kit-wave/ — 165 source files reaped, caches/.venv spared by the rsync excludes.
# Prior loss 2026-06-17: CI wave-runner ran `git clean -fdx` on the main checkout.
#
# Design notes:
#   - rsync --delete is blocked UNCONDITIONALLY (target-independent): it is almost never
#     what an agent wants, and the destination is often built from a variable.
#   - rm / mv / find are blocked only when they NAME a protected root, to keep false
#     positives off ordinary work (`rm -rf /tmp/x`, `mv build dist`).
#   - Flag matching is arrangement-independent: `-rf`, `-fr`, `-r -f`, `--recursive --force`.
#   - Protected roots track scripts/snapshot_local.sh `paths=()`. Keep the two in sync.
set -uo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.command // empty' 2>/dev/null) || command=""
if [[ -z "$command" ]]; then
  # Unparseable input: hooks.json sets failClosed, so refuse rather than wave it through.
  jq -n '{permission:"deny", user_message:"destructive-fs-gate: could not parse command", agent_message:"destructive-fs-gate: could not parse command"}'
  exit 0
fi

deny() {
  jq -n --arg m "$1" '{permission:"deny", user_message:$m, agent_message:$m}'
  exit 0
}

# Roots that are gitignored and therefore unrecoverable from git history.
PROTECTED='(\.ignorelocal|spec-kit-wave|build-plan-from-review|wave-orchestrator|\.cursor|\.claude|docs|CLAUDE\.md)'
LEAD='(^|[[:space:]/"=])'
TRAIL='([/[:space:]";|&]|$)'

has()  { printf '%s' "$command" | grep -Eq -- "$1"; }
names_protected() { printf '%s' "$command" | grep -Eq "${LEAD}${PROTECTED}${TRAIL}"; }

# --- rsync --delete / --del / --delete-excluded (the 2026-07-20 fingerprint) -------------
# `--del` is a documented rsync alias for `--delete`; `--delete-*` variants all reap too.
if has '(^|[[:space:];|&])rsync([[:space:]]|$)' && has '--del(ete)?([-=]|[[:space:]]|$)'; then
  deny "BLOCKED: rsync --delete/--del. It reaps destination files absent from the source — this destroyed spec-kit-wave on 2026-07-20 (165 files). Use 'rsync -a --ignore-existing' to restore, or plain 'rsync -a' to update. Never mirror a sparse tree onto .ignorelocal/, spec-kit-wave/, .cursor/, .claude/, build-plan-from-review/ or wave-orchestrator/."
fi

# --- git clean -x / -X (deletes ignored trees) -------------------------------------------
# The repo-local alias.clean guard only binds interactive shells; agents call git directly.
if has 'git[[:space:]]+clean([[:space:]]|$)' && has '(^|[[:space:]])--?[a-zA-Z-]*[xX]([[:space:]]|$)'; then
  deny "BLOCKED: git clean -x/-X. Deletes gitignored operator trees. Safe: 'git clean -fd -- <path>'."
fi

# --- git stash --all (stashes AND removes ignored files) ---------------------------------
if has 'git[[:space:]]+stash([[:space:]]|$)' && has '(^|[[:space:]])(-a|--all)([[:space:]]|$)'; then
  deny "BLOCKED: git stash --all. It removes gitignored trees from the working tree. Recoverable via 'git stash pop', but use 'git stash -u' or an explicit pathspec instead."
fi

# --- rm -r -f of a protected root (any flag arrangement) ---------------------------------
if has '(^|[[:space:];|&])rm([[:space:]]|$)' \
   && has '(^|[[:space:]])(-[a-zA-Z]*[rR]|--recursive)([[:space:]]|$|[a-zA-Z])' \
   && names_protected; then
  deny "BLOCKED: recursive rm naming a protected operator tree (.ignorelocal / spec-kit-wave / build-plan-from-review / wave-orchestrator / .cursor / .claude / docs / CLAUDE.md). These are gitignored — git cannot restore them. Delete specific files explicitly, after confirming with the operator."
fi

# --- find -delete / -exec rm inside a protected root -------------------------------------
if has '(^|[[:space:];|&])find([[:space:]]|$)' \
   && has '(-delete([[:space:]]|$)|-exec[[:space:]]+rm([[:space:]]|$))' \
   && names_protected; then
  deny "BLOCKED: find -delete / -exec rm inside a protected operator tree. Enumerate matches first ('find ... -print'), then remove specific files after confirming."
fi

# --- mv of a protected root (a move is a loss) -------------------------------------------
if has '(^|[[:space:];|&])mv([[:space:]]|$)' && names_protected; then
  deny "BLOCKED: mv naming a protected operator tree. Moving it away is indistinguishable from deleting it for anything that reads the path. Copy instead, or confirm with the operator first."
fi

echo '{"permission":"allow"}'
exit 0
