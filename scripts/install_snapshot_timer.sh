#!/usr/bin/env bash
# Install the launchd timer that runs scripts/snapshot_local.sh every 3 hours,
# independent of git push. macOS only (LaunchAgent). Idempotent + re-runnable.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "install-snapshot-timer: launchd is macOS-only — skipping (use cron/systemd elsewhere)." >&2
  exit 0
fi

label="bot.sevn.snapshot-local"
src="$repo_root/scripts/launchd/${label}.plist"
agents_dir="$HOME/Library/LaunchAgents"
dst="$agents_dir/${label}.plist"
backup_root="${SEVN_LOCAL_BACKUP_DIR:-$HOME/.sevn-local-backups/sevn.bot}"

[[ -f "$src" ]] || { echo "install-snapshot-timer: missing $src" >&2; exit 1; }
chmod +x scripts/snapshot_local.sh 2>/dev/null || true
mkdir -p "$agents_dir" "$backup_root"

# Render the installed plist from the repo template, pinning ProgramArguments /
# WorkingDirectory to THIS checkout and the log path under the real backup root
# (launchd does not expand ~ or $HOME inside plist string values).
sed \
  -e "s#/Users/alex/Documents/code/sevn.bot/sevn#${repo_root}#g" \
  -e "s#/Users/alex/.sevn-local-backups/sevn.bot#${backup_root}#g" \
  "$src" > "$dst"

# Reload cleanly: bootout any prior instance, then bootstrap into the GUI user domain.
# Fall back to legacy load/unload on older macOS where bootstrap is unavailable.
domain="gui/$(id -u)"
launchctl bootout "$domain/$label" 2>/dev/null || true
if ! launchctl bootstrap "$domain" "$dst" 2>/dev/null; then
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst" 2>/dev/null || true
fi

echo "install-snapshot-timer: installed $label -> $dst"
echo "  interval: every 3h (StartInterval=10800), plus once at load (RunAtLoad)"
echo "  log:      $backup_root/snapshot-cron.log"
echo "  status:   launchctl print $domain/$label | grep -E 'state|runs'"
echo "  remove:   launchctl bootout $domain/$label && rm -f \"$dst\""
