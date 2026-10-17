#!/bin/sh
# The iOS Simulator hangs in open() on a regular file under ~/Documents.
# A symlink to a copy outside Documents reads normally. Restore after the test.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/payloads"
DEST="/tmp/sevn-a2ui-payloads"
mkdir -p "$DEST"
for file in "$SRC"/*.json; do
  [ -e "$file" ] || continue
  base="$(basename "$file")"
  if [ -L "$file" ]; then
    continue
  fi
  cp -f "$file" "$DEST/$base"
  ln -sfn "$DEST/$base" "$file"
done
echo "exposed $(date)" >>"$DEST/preflight.log"
