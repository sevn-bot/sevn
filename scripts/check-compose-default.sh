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

_check_override_file_conflict() {
  local has_browser=0 has_gui=0 file
  for file in "$@"; do
    case "$file" in
      *docker-compose.browser.yml*) has_browser=1 ;;
      *docker-compose.gui.yml*) has_gui=1 ;;
    esac
  done
  if [[ $has_browser -eq 1 && $has_gui -eq 1 ]]; then
    echo "error: browser and gui compose override files are mutually exclusive (both replace sevn-gateway on port 3001)" >&2
    return 1
  fi
  return 0
}

_check_legacy_profile_without_override() {
  local profiles="${1:-}"
  shift
  local has_browser_override=0 has_gui_override=0 file
  for file in "$@"; do
    case "$file" in
      *docker-compose.browser.yml*) has_browser_override=1 ;;
      *docker-compose.gui.yml*) has_gui_override=1 ;;
    esac
  done
  if [[ "$profiles" == *browser* && $has_browser_override -eq 0 ]]; then
    echo "error: browser profile requires -f docker/docker-compose.browser.yml (legacy --profile/COMPOSE_PROFILES invocations removed)" >&2
    return 1
  fi
  if [[ "$profiles" == *gui* && $has_gui_override -eq 0 ]]; then
    echo "error: gui profile requires -f docker/docker-compose.gui.yml (legacy --profile/COMPOSE_PROFILES invocations removed)" >&2
    return 1
  fi
  return 0
}

_cli_profiles=""
_compose_files=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      _cli_profiles="${_cli_profiles},${2:-}"
      shift 2
      ;;
    -f)
      _compose_files+=("${2:-}")
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

_combined_profiles="${COMPOSE_PROFILES:-}${_cli_profiles}"
_combined_profiles="${_combined_profiles#,}"

_check_profile_conflict "$_combined_profiles" || exit 1
if ((${#_compose_files[@]} > 0)); then
  _check_override_file_conflict "${_compose_files[@]}" || exit 1
fi
if [[ -n "$_combined_profiles" ]]; then
  _guard_files=("${_compose_files[@]}")
  if ((${#_guard_files[@]} == 0)); then
    _guard_files=("$compose_base")
  fi
  _check_legacy_profile_without_override "$_combined_profiles" "${_guard_files[@]}" || exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI not on PATH — skipping compose default check" >&2
  exit 0
fi

# C10.1 — minimum Docker Compose version (deploy.resources.limits applied on non-swarm).
# Override with SEVN_COMPOSE_MIN_VERSION for local experiments only.
SEVN_COMPOSE_MIN_VERSION="${SEVN_COMPOSE_MIN_VERSION:-2.20.0}"

_compose_version_digits() {
  # Strip leading v and any -/+ suffix (e.g. v2.38.2-desktop.1 → 2.38.2).
  local raw="${1:-}"
  raw="${raw#v}"
  printf '%s' "${raw%%[-+]*}"
}

_compose_version_ge() {
  # True when $1 >= $2 (dotted numeric). Uses sort -V.
  local have min
  have="$(_compose_version_digits "$1")"
  min="$(_compose_version_digits "$2")"
  [[ -n "$have" && -n "$min" ]] || return 1
  [[ "$(printf '%s\n%s\n' "$min" "$have" | sort -V | head -n1)" == "$min" ]]
}

_require_min_compose_version() {
  local raw short ver
  raw="$(docker compose version 2>/dev/null || true)"
  short="$(docker compose version --short 2>/dev/null || true)"
  ver="$(_compose_version_digits "$short")"
  if [[ -z "$ver" ]]; then
    # Fallback: "Docker Compose version v2.38.2-desktop.1"
    ver="$(printf '%s' "$raw" | sed -n 's/.*[Vv]\([0-9][0-9.]*\).*/\1/p' | head -n1)"
  fi
  if [[ -z "$ver" ]]; then
    echo "error: could not parse Docker Compose version from: ${raw:-<empty>}" >&2
    exit 1
  fi
  if ! _compose_version_ge "$ver" "$SEVN_COMPOSE_MIN_VERSION"; then
    echo "error: Docker Compose version ${ver} is below minimum ${SEVN_COMPOSE_MIN_VERSION} (C10.1; deploy.resources.limits require Compose v2.20+)" >&2
    exit 1
  fi
}

_require_min_compose_version

# Static compose validation only — not a runtime secret. Operator stacks must set
# SEVN_GATEWAY_TOKEN in .env (see .env.example); bootstrap rejects known sentinels.
export SEVN_GATEWAY_TOKEN="${SEVN_GATEWAY_TOKEN:-check-compose-default-placeholder-token-32chars}"

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

# C8.1 — no compose file or overlay may pass --no-sandbox (renderer sandbox stays on).
# Strip YAML comment lines, then reject the token in active config (prod overlay included).
_check_no_sandbox_in_compose() {
  local compose_file="$1"
  local active
  active="$(grep -v '^\s*#' "$compose_file" || true)"
  if printf '%s\n' "$active" | grep -q -- '--no-sandbox'; then
    echo "error: ${compose_file##*/} must not pass --no-sandbox (Chromium renderer sandbox required)" >&2
    return 1
  fi
  return 0
}

shopt -s nullglob
for compose_file in "${repo_root}/docker"/docker-compose*.yml; do
  _check_no_sandbox_in_compose "$compose_file" || exit 1
done
shopt -u nullglob

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

if _check_override_file_conflict "$compose_base" "$compose_browser" "$compose_gui" 2>/dev/null; then
  echo "mutual exclusion guard broken: browser+gui override files should be rejected" >&2
  exit 1
fi

if _check_legacy_profile_without_override "browser" "$compose_base" 2>/dev/null; then
  echo "legacy profile guard broken: browser profile without override should be rejected" >&2
  exit 1
fi

if _check_legacy_profile_without_override "gui" "$compose_base" 2>/dev/null; then
  echo "legacy profile guard broken: gui profile without override should be rejected" >&2
  exit 1
fi

# C10.3 — every resolved service in operator + CI file sets must declare limits.
_check_resolved_service_limits() {
  local label="$1"
  shift
  local -a compose_args=()
  local file
  for file in "$@"; do
    compose_args+=(-f "$file")
  done
  local lacking
  lacking="$(
    docker compose "${compose_args[@]}" config --format json 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin)
lacking = []
for name, svc in sorted((data.get("services") or {}).items()):
    limits = ((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}
    cpus, memory = limits.get("cpus"), limits.get("memory")
    pids = limits.get("pids")
    pids_limit = svc.get("pids_limit")
    if not (cpus and memory and (pids is not None or pids_limit is not None)):
        lacking.append(name)
print(" ".join(lacking))
'
  )"
  if [[ -n "${lacking// /}" ]]; then
    echo "${label}: services missing deploy.resources.limits and/or pids_limit: ${lacking}" >&2
    exit 1
  fi
}

_check_resolved_service_limits "default" "$compose_base"
_check_resolved_service_limits "browser override" "$compose_base" "$compose_browser"
_check_resolved_service_limits "gui override" "$compose_base" "$compose_gui"
_check_resolved_service_limits "ci" "${repo_root}/docker/docker-compose.ci.yml"
