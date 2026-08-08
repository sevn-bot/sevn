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

_compose_version_compare() {
  # Compare two dotted numeric versions. Print -1/0/1 like strcmp.
  # Portable: pure-bash field split on '.', no GNU sort -V or python.
  local IFS=.
  local -a a=($1) b=($2)
  local i n max
  max="${#a[@]}"
  if (("${#b[@]}" > max)); then max="${#b[@]}"; fi
  for ((i = 0; i < max; i++)); do
    n="${a[i]:-0}"
    if ((10#${n} < 10#${b[i]:-0})); then printf '%s' -1; return 0; fi
    if ((10#${n} > 10#${b[i]:-0})); then printf '%s' 1; return 0; fi
  done
  printf '%s' 0
}

_compose_version_ge() {
  # True when $1 >= $2 (dotted numeric; portable across GNU/BSD sort).
  local have min cmp
  have="$(_compose_version_digits "$1")"
  min="$(_compose_version_digits "$2")"
  [[ -n "$have" && -n "$min" ]] || return 1
  cmp="$(_compose_version_compare "$have" "$min")"
  [[ "$cmp" == "0" || "$cmp" == "1" ]]
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
# POSIX-portable: use [[:space:]] instead of GNU \s so the script behaves identically on
# macOS / BSD grep. \s would be interpreted literally as backslash-s under BSD grep and
# the comment-stripping pass would fail to drop lines like ``# --no-sandbox …``.
_check_no_sandbox_in_compose() {
  local compose_file="$1"
  local active
  active="$(grep -v '^[[:space:]]*#' "$compose_file" || true)"
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

# ---------------------------------------------------------------------------
# C8.1 — browser renderer-sandbox preflight.
#
# Removing --no-sandbox only buys isolation if Brave can actually build its
# namespace sandbox. Two preconditions have to hold, and both fail *at runtime*
# with an opaque "Failed to move to new namespace" abort, so check them here.
#
#   1. Container syscall policy: Docker's default seccomp profile gates
#      clone(CLONE_NEW*) / clone3 / unshare behind CAP_SYS_ADMIN and chroot
#      behind CAP_SYS_CHROOT. Under the overlays' `cap_drop: ALL` that means no
#      sandbox at all, so the browser/GUI overlays must pin
#      infra/docker/seccomp-browser.json.
#   2. Host policy: the kernel must permit unprivileged user namespaces. On
#      Ubuntu 23.10+ AppArmor restricts them via
#      /proc/sys/kernel/apparmor_restrict_unprivileged_userns.
#
# Fails closed: an operator whose host refuses user namespaces is told before
# `compose up` rather than discovering a browser that will not start.
# Set SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1 to bypass (documented escape hatch
# for hosts where the operator has accepted a different mitigation).
# ---------------------------------------------------------------------------
_seccomp_profile="${repo_root}/infra/docker/seccomp-browser.json"

_check_browser_seccomp_profile_pinned() {
  local label="$1" compose_file="$2"
  if ! grep -q 'seccomp=.*seccomp-browser\.json' "$compose_file"; then
    echo "error: ${label} (${compose_file##*/}) must pin the browser seccomp profile" >&2
    echo "       (security_opt: - seccomp=../infra/docker/seccomp-browser.json)." >&2
    echo "       Without it Docker's default profile blocks clone(CLONE_NEWUSER)/chroot" >&2
    echo "       under cap_drop:ALL and Brave aborts before CDP binds." >&2
    return 1
  fi
  if grep -q 'seccomp[=:]unconfined' "$compose_file"; then
    echo "error: ${label} (${compose_file##*/}) sets seccomp=unconfined; pin the" >&2
    echo "       narrow browser profile instead of disabling the syscall filter." >&2
    return 1
  fi
  return 0
}

if [ ! -f "$_seccomp_profile" ]; then
  echo "error: missing browser seccomp profile at ${_seccomp_profile}" >&2
  exit 1
fi

_check_browser_seccomp_profile_pinned "browser override" "$compose_browser" || exit 1
_check_browser_seccomp_profile_pinned "gui override" "$compose_gui" || exit 1

if [ "${SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT:-0}" != "1" ]; then
  _userns_sysctl=/proc/sys/kernel/apparmor_restrict_unprivileged_userns
  if [ -r "$_userns_sysctl" ] && [ "$(cat "$_userns_sysctl")" != "0" ]; then
    echo "error: this host restricts unprivileged user namespaces" >&2
    echo "       (${_userns_sysctl} = $(cat "$_userns_sysctl"))." >&2
    echo "       Brave's renderer sandbox cannot start, and the browser/gui" >&2
    echo "       overlays no longer fall back to --no-sandbox (C8.1)." >&2
    echo "" >&2
    echo "       Remediation — prefer the app-scoped AppArmor policy:" >&2
    echo "         sudo tee /etc/apparmor.d/sevn-browser >/dev/null <<'EOF'" >&2
    echo "         abi <abi/4.0>," >&2
    echo "         include <tunables/global>" >&2
    echo "         profile sevn-browser flags=(unconfined) {" >&2
    echo "           userns," >&2
    echo "         }" >&2
    echo "         EOF" >&2
    echo "         sudo apparmor_parser -r /etc/apparmor.d/sevn-browser" >&2
    echo "" >&2
    echo "       Host-wide alternative (weaker, affects every process):" >&2
    echo "         echo 0 | sudo tee ${_userns_sysctl}" >&2
    echo "         # persist: /etc/sysctl.d/60-apparmor-userns.conf" >&2
    echo "" >&2
    echo "       See docker/README.md § Browser sandbox and docs/readmes/security.md §C8.1." >&2
    echo "       Bypass (after accepting another mitigation):" >&2
    echo "         SEVN_SKIP_BROWSER_SANDBOX_PREFLIGHT=1" >&2
    exit 1
  fi
fi
