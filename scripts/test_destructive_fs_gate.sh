#!/usr/bin/env bash
# Regression suite for scripts/destructive_fs_gate.sh — the logic behind the Cursor
# `beforeShellExecution` hook that blocks agent commands capable of wiping gitignored
# operator trees.
#
# Why this exists: on 2026-07-20 an `rsync -a --delete` of a sparse tree onto
# spec-kit-wave/ reaped 165 source files, and on 2026-06-17 a CI `git clean -fdx` wiped
# .ignorelocal/. Neither was catchable by git. The gate is the only thing standing in
# front of a third incident, so its allow/deny behaviour is pinned here.
#
# A note on why the suite earns its keep: while hardening the gate, a stray `--` passed to
# an internal grep wrapper silently turned the rsync and find rules into no-ops — the two
# rules the gate exists for. It looked fine; only these cases caught it.
#
# Run: bash scripts/test_destructive_fs_gate.sh
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
gate="$repo_root/scripts/destructive_fs_gate.sh"

[[ -r "$gate" ]] || { echo "test-destructive-fs-gate: FAIL (missing $gate)"; exit 1; }
command -v jq >/dev/null || { echo "test-destructive-fs-gate: SKIP (jq not installed)"; exit 0; }

pass=0; fail=0

# check <command> <expected-permission> <label>
check() {
  local got
  got=$(printf '%s' "$1" \
    | python3 -c 'import json,sys; print(json.dumps({"command": sys.stdin.read()}))' \
    | bash "$gate" 2>/dev/null | jq -r '.permission // "ERROR"')
  if [[ "$got" == "$2" ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf '  FAIL  got=%-6s want=%-6s  %s\n' "$got" "$2" "$3"
  fi
}

# --- must DENY: the fingerprints we actually lost data to ---------------------------------
check 'rsync -a --delete src/ spec-kit-wave/'          deny  'rsync --delete (2026-07-20 fingerprint)'
check 'rsync -av --delete-excluded a/ b/'              deny  'rsync --delete-excluded'
check 'rsync -a --del src/ spec-kit-wave/'             deny  'rsync --del (documented alias)'
check 'cd /tmp && rsync -a --delete x/ y/'             deny  'rsync --delete after cd'
check 'git clean -fdx'                                 deny  'git clean -fdx (2026-06-17 fingerprint)'
check 'git clean -X'                                   deny  'git clean -X'
check '/usr/bin/git clean -fdx'                        deny  'absolute git bypasses alias.clean'
check 'git stash push --all'                           deny  'git stash --all removes ignored files'

# --- must DENY: recursive rm naming a protected root, any flag arrangement -----------------
check 'rm -rf .ignorelocal'                            deny  'rm -rf .ignorelocal'
check 'rm -rf spec-kit-wave/agents'                    deny  'rm -rf protected subdir'
check 'rm -r -f .ignorelocal'                          deny  'rm -r -f (split flags)'
check 'rm --recursive --force spec-kit-wave'           deny  'rm --recursive --force'
check 'rm -rf wave-orchestrator'                       deny  'rm -rf wave-orchestrator'
check 'rm -rf build-plan-from-review'                  deny  'rm -rf build-plan-from-review'
check 'rm -rf docs'                                    deny  'rm -rf docs'
check 'rm -rf CLAUDE.md'                               deny  'rm -rf CLAUDE.md'

# --- must DENY: other ways to lose a tree --------------------------------------------------
check 'find spec-kit-wave -type f -delete'             deny  'find -delete'
check 'find .ignorelocal -name "*.md" -exec rm {} ;'   deny  'find -exec rm'
check 'mv spec-kit-wave /tmp/gone'                     deny  'mv a protected root away'

# --- must ALLOW: ordinary work (false positives are how a guard gets disabled) --------------
check 'rsync -a --ignore-existing src/ dst/'           allow 'rsync --ignore-existing (restore idiom)'
check 'rsync -a docs/ /tmp/backup/'                    allow 'rsync without --delete'
check 'git clean -fd'                                  allow 'git clean -fd'
check 'git stash -u'                                   allow 'git stash -u'
check 'rm -rf /tmp/scratch'                            allow 'rm -rf unrelated path'
check 'rm -rf node_modules'                            allow 'rm -rf node_modules'
check 'find . -name "*.pyc" -delete'                   allow 'find -delete outside protected roots'
check 'mv build dist'                                  allow 'mv unrelated'
check 'ls -la docs'                                    allow 'reading a protected path'
check 'cat .cursor/hooks.json'                         allow 'reading a protected path'
check 'git status'                                     allow 'git status'
check 'make ci'                                        allow 'make ci'

# --- the .cursor wrapper must actually delegate here (it is gitignored, so may be absent) --
hook="$repo_root/.cursor/hooks/destructive-fs-gate.sh"
if [[ -x "$hook" ]]; then
  got=$(printf '{"command":"rsync -a --delete src/ spec-kit-wave/"}' \
    | "$hook" 2>/dev/null | jq -r '.permission // "ERROR"')
  if [[ "$got" == "deny" ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf '  FAIL  got=%-6s want=deny    .cursor hook delegates to tracked gate\n' "$got"
  fi
else
  echo "test-destructive-fs-gate: note — .cursor/hooks/destructive-fs-gate.sh absent (gitignored); wrapper delegation not checked"
fi

echo "test-destructive-fs-gate: PASS=$pass FAIL=$fail"
[[ $fail -eq 0 ]] || exit 1
exit 0
