#!/usr/bin/env bash
# Assert operator compose default profile and guard browser/gui mutual exclusion (#136, #137).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
compose_file="${repo_root}/docker/docker-compose.yml"

_check_profile_conflict() {
  local profiles="${1:-}"
  if [[ "$profiles" == *browser* && "$profiles" == *gui* ]]; then
    echo "error: browser and gui compose profiles are mutually exclusive (both publish port 3001)" >&2
    return 1
  fi
  return 0
}

_check_profile_conflict "${COMPOSE_PROFILES:-}" || exit 1

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI not on PATH — skipping compose default check" >&2
  exit 0
fi

services="$(docker compose -f "$compose_file" config --services | sort | tr '\n' ' ')"
expected="sevn-gateway sevn-proxy "
if [ "$services" != "$expected" ]; then
  echo "default compose profile must be exactly {sevn-proxy, sevn-gateway}, got: $services" >&2
  exit 1
fi

if grep -q '"!' "$compose_file"; then
  echo "negated compose profiles are not a thing" >&2
  exit 1
fi

for svc in sevn-gateway sevn-gateway-browser sevn-gateway-gui; do
  block="$(awk -v svc="$svc" '
    $0 ~ "^  " svc ":$" { capture=1; next }
    capture && /^  [a-zA-Z0-9_-]+:$/ { exit }
    capture { print }
  ' "$compose_file")"
  if [ -n "$block" ] && echo "$block" | grep -q 'OPENAI_API_KEY'; then
    echo "${svc} must not receive OPENAI_API_KEY (proxy-only)" >&2
    exit 1
  fi
done

# Self-test: mutual-exclusion guard must reject browser+gui together.
if _check_profile_conflict "browser,gui" 2>/dev/null; then
  echo "mutual exclusion guard broken: browser+gui should be rejected" >&2
  exit 1
fi
