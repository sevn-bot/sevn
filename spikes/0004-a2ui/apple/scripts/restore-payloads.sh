#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/payloads"
for file in "$SRC"/*.json; do
  [ -L "$file" ] || continue
  target="$(readlink "$file")"
  rm -f "$file"
  cp -f "$target" "$file"
done
