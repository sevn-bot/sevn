#!/usr/bin/env bash
# Sync vendored last30days engine from mvanhorn/last30days-skill into bundled_skills.
#
# Usage:
#   scripts/sync_last30days_upstream.sh [REF]
#
# REF defaults to main (SKILL.md may be ahead of the latest git tag). After sync,
# re-apply sevn-owned files: SKILL.md (adapted), scripts/research.py, UPSTREAM_VERSION.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_ROOT/src/sevn/data/bundled_skills/core/last30days"
REF="${1:-main}"
TMP="$(mktemp -d)"
ARCHIVE="$TMP/last30days-skill.tar.gz"

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "Fetching mvanhorn/last30days-skill @ ${REF}..."
curl -fsSL "https://codeload.github.com/mvanhorn/last30days-skill/tar.gz/${REF}" -o "$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'last30days-skill-*' | head -1)/skills/last30days"
if [[ ! -d "$SRC" ]]; then
  echo "ERROR: skills/last30days not found in archive" >&2
  exit 1
fi

mkdir -p "$DEST"

# Preserve sevn-owned artifacts across sync (SKILL.md is a split overlay, not upstream monolith).
BACKUP="$(mktemp -d)"
for f in SKILL.md references/contract.md scripts/research.py UPSTREAM_VERSION; do
  if [[ -e "$DEST/$f" ]]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp -a "$DEST/$f" "$BACKUP/$f"
  fi
done

rsync -a --delete \
  --exclude 'assets/' \
  --exclude 'agents/' \
  --exclude 'scripts/build-skill.sh' \
  --exclude 'scripts/test-v1-vs-v2.sh' \
  --exclude 'scripts/test_device_auth.py' \
  --exclude 'scripts/verify_v3.py' \
  "$SRC/" "$DEST/"

# Upstream SKILL.md is reference-only; restore sevn adaptation + split contract when present.
if [[ -f "$BACKUP/SKILL.md" ]]; then
  cp -a "$BACKUP/SKILL.md" "$DEST/SKILL.md"
fi
if [[ -f "$BACKUP/references/contract.md" ]]; then
  mkdir -p "$DEST/references"
  cp -a "$BACKUP/references/contract.md" "$DEST/references/contract.md"
fi
if [[ -f "$BACKUP/scripts/research.py" ]]; then
  cp -a "$BACKUP/scripts/research.py" "$DEST/scripts/research.py"
fi

# Upstream sources often ship blank lines with trailing spaces (pre-commit fails).
while IFS= read -r -d '' py; do
  sed -i '' 's/[[:space:]]*$//' "$py"
done < <(find "$DEST" -name '*.py' -print0)

# Record sync ref + upstream version from archived SKILL.md when available.
UPSTREAM_VER="$(awk '/^version:/{gsub(/"/,"",$2); print $2; exit}' "$SRC/SKILL.md" 2>/dev/null || true)"
{
  echo "ref=${REF}"
  echo "synced=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ -n "$UPSTREAM_VER" ]]; then
    echo "version=${UPSTREAM_VER}"
  fi
} > "$DEST/UPSTREAM_VERSION"

# MIT license from repo root.
if [[ -f "$(dirname "$SRC")/../LICENSE" ]]; then
  cp "$(dirname "$SRC")/../LICENSE" "$DEST/LICENSE"
elif [[ -f "$TMP/$(basename "$(dirname "$SRC")")/../LICENSE" ]]; then
  :
fi
LICENSE_SRC="$(find "$TMP" -maxdepth 2 -name LICENSE -path '*/last30days-skill-*/LICENSE' | head -1)"
if [[ -n "$LICENSE_SRC" && -f "$LICENSE_SRC" ]]; then
  cp "$LICENSE_SRC" "$DEST/LICENSE"
fi

echo "Synced to $DEST (ref=${REF}, version=${UPSTREAM_VER:-unknown})"
echo "Review sevn SKILL.md + scripts/research.py if this was a fresh import."
