#!/usr/bin/env bash
# Thin Cursor hook wrapper — logic lives in scripts/destructive_fs_gate.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GATE="${ROOT}/scripts/destructive_fs_gate.sh"
if [[ -x "${GATE}" ]]; then
  exec "${GATE}" "$@"
fi
if [[ -f "${GATE}" ]]; then
  exec bash "${GATE}" "$@"
fi
# Fail-open when the tracked gate script is absent (sparse checkout / main stub).
# failClosed hooks still need a successful exit with an allow decision on stdin JSON.
jq -n '{permission:"allow"}' 2>/dev/null || echo '{"permission":"allow"}'
