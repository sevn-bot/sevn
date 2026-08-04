#!/usr/bin/env bash
# Assert operator compose default profile and guard browser/gui mutual exclusion (#136, #137, #164, #165).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
compose_base="${repo_root}/docker/docker-compose.yml"
compose_browser="${repo_root}/docker/docker-compose.browser.yml"
compose_gui="${repo_root}/docker/docker-compose.gui.yml"

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

_expected_services="sevn-gateway sevn-operator-perms sevn-proxy "

_check_compose_file_set() {
  local label="$1"
  shift
  local -a compose_args=()
  local file
  for file in "$@"; do
    compose_args+=(-f "$file")
  done
  local services
  services="$(docker compose "${compose_args[@]}" config --services | sort | tr '\n' ' ')"
  if [ "$services" != "$_expected_services" ]; then
    echo "${label} compose must be exactly {sevn-operator-perms, sevn-proxy, sevn-gateway}, got: $services" >&2
    exit 1
  fi
  local publishers
  publishers="$(
    docker compose "${compose_args[@]}" config --format json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
publishers = []
for name, cfg in (data.get('services') or {}).items():
    for port in cfg.get('ports') or []:
        if isinstance(port, dict) and port.get('target') == 3001:
            publishers.append(name)
            break
print(' '.join(sorted(publishers)))
"
  )"
  if [ "$publishers" != "sevn-gateway" ]; then
    echo "${label} compose must publish gateway port 3001 from exactly sevn-gateway, got: ${publishers:-<none>}" >&2
    exit 1
  fi
}

_check_compose_file_set "default" "$compose_base"
_check_compose_file_set "browser override" "$compose_base" "$compose_browser"
_check_compose_file_set "gui override" "$compose_base" "$compose_gui"

for compose_file in "$compose_base" "$compose_browser" "$compose_gui"; do
  if grep -q '"!' "$compose_file"; then
    echo "negated compose profiles are not a thing ($compose_file)" >&2
    exit 1
  fi
done

for compose_file in "$compose_base" "$compose_browser" "$compose_gui"; do
  block="$(awk -v svc="sevn-gateway" '
    $0 ~ "^  " svc ":$" { capture=1; next }
    capture && /^  [a-zA-Z0-9_-]+:$/ { exit }
    capture { print }
  ' "$compose_file")"
  if [ -n "$block" ] && echo "$block" | grep -q 'OPENAI_API_KEY'; then
    echo "sevn-gateway in ${compose_file##*/} must not receive OPENAI_API_KEY (proxy-only)" >&2
    exit 1
  fi
done

# Self-test: mutual-exclusion guard must reject browser+gui together.
if _check_profile_conflict "browser,gui" 2>/dev/null; then
  echo "mutual exclusion guard broken: browser+gui should be rejected" >&2
  exit 1
fi
