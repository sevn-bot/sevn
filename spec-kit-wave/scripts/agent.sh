#!/usr/bin/env bash
# spec-kit-wave — render a prompt template and drive one headless agent turn.
#
# Usage:
#   agent.sh --rendered <rendered-prompt.md>
#   agent.sh <template.md> [KEY=VAL ...]
#
# Legacy mode: {{KEY}} placeholders in <template.md> are substituted with VAL before
# the rendered prompt is handed to the agent. --rendered mode reads a pre-rendered
# file (e.g. from scripts/render.py) with no substitution.
#
# The driver is Cursor's `cursor-agent` today; thermo is a Cursor plugin invoked from
# inside the prompt. (Portable to `claude` headless later — override SKW_AGENT_BIN.)
#
# Env (all optional; set by the Makefile):
#   SKW_AGENT_BIN    agent binary               (default: cursor-agent)
#   SKW_MODEL        --model                    (default: auto  → Cursor "auto")
#   SKW_PERMS        permission flags           (default: --force)
#   SKW_PLUGIN_DIR   --plugin-dir <dir>         (default: empty → use installed plugins)
#   SKW_WORKSPACE    --workspace <dir>          (default: $PWD)
#   SKW_OUTPUT_FMT   --output-format            (default: text)
#   SKW_DRYRUN       1 = print argv, do not run (default: 0)
#   SKW_RESOLVE_STAGE  resolve model params from skw.toml (e.g. wave-generator)
#   SKW_WAVE_FILE    wave-file path when SKW_RESOLVE_STAGE needs wave TOML
#   SKW_WAVE_ID      wave id for run-stage resolution
set -euo pipefail

RENDERED_MODE=0
if [ "${1:-}" = "--rendered" ]; then
  RENDERED_MODE=1
  shift
fi

if [ "$RENDERED_MODE" = "1" ]; then
  RENDERED="${1:?usage: agent.sh --rendered <rendered-prompt.md>}"
  shift || true
  [ -f "$RENDERED" ] || { echo "agent.sh: rendered prompt not found: $RENDERED" >&2; exit 1; }
  prompt="$(cat "$RENDERED")"
  label="$(basename "$RENDERED")"
else
  TEMPLATE="${1:?usage: agent.sh <template.md> [KEY=VAL ...]  OR  agent.sh --rendered <file>}"
  shift || true
  [ -f "$TEMPLATE" ] || { echo "agent.sh: template not found: $TEMPLATE" >&2; exit 1; }
  label="$(basename "$TEMPLATE")"

  # Render: replace {{KEY}} with VAL for each KEY=VAL argument.
  prompt="$(cat "$TEMPLATE")"
  for kv in "$@"; do
    key="${kv%%=*}"
    val="${kv#*=}"
    prompt="${prompt//\{\{$key\}\}/$val}"
  done
fi

# Surface any unfilled placeholders rather than shipping a broken prompt.
if printf '%s' "$prompt" | grep -q '{{[A-Z_]*}}'; then
  if [ "$RENDERED_MODE" = "1" ]; then
    echo "agent.sh: unfilled placeholder(s) in rendered file $RENDERED:" >&2
  else
    echo "agent.sh: unfilled placeholder(s) in $TEMPLATE:" >&2
  fi
  printf '%s' "$prompt" | grep -o '{{[A-Z_]*}}' | sort -u >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

_skw_resolve_exports() {
  # Usage: _skw_resolve_exports [wave_file]
  local _wave_file="${1:-}"
  SKW_KIT_ROOT="$KIT_ROOT" \
    SKW_WORKSPACE="${SKW_WORKSPACE:-$PWD}" \
    SKW_RESOLVE_STAGE="${SKW_RESOLVE_STAGE}" \
    SKW_WAVE_FILE="${_wave_file}" \
    SKW_WAVE_ID="${SKW_WAVE_ID:-}" \
    SKW_AGENT_BIN="${_saved_agent_bin}" \
    SKW_MODEL="${_saved_model}" \
    SKW_PERMS="${_saved_perms}" \
    SKW_PLUGIN_DIR="${_saved_plugin_dir}" \
    uv run --directory "$KIT_ROOT" python -c '
import os
from pathlib import Path
from skw.agent_config import resolve_agent_params, shell_export_params
from skw.resolve_wave import load_wave_data
kit = Path(os.environ["SKW_KIT_ROOT"])
stage = os.environ["SKW_RESOLVE_STAGE"]
wave = os.environ.get("SKW_WAVE_FILE", "").strip()
wave_id = os.environ.get("SKW_WAVE_ID", "").strip() or None
data = load_wave_data(Path(wave)) if wave else None
params = resolve_agent_params(
    kit_root=kit, stage=stage, wave_data=data, wave_id=wave_id,
)
print(shell_export_params(params))
'
}

if [ -n "${SKW_RESOLVE_STAGE:-}" ]; then
  _saved_agent_bin="${SKW_AGENT_BIN:-}"
  _saved_model="${SKW_MODEL:-}"
  _saved_perms="${SKW_PERMS:-}"
  _saved_plugin_dir="${SKW_PLUGIN_DIR:-}"
  unset SKW_AGENT_BIN SKW_MODEL SKW_PERMS SKW_PLUGIN_DIR SKW_EXTRA_ARGS SKW_EFFORT
  if ! command -v uv >/dev/null 2>&1; then
    echo "agent.sh: warning: uv not on PATH; cannot resolve SKW_RESOLVE_STAGE=${SKW_RESOLVE_STAGE} (using shell defaults)" >&2
  else
    _resolve_rc=0
    _exports="$(_skw_resolve_exports "${SKW_WAVE_FILE:-}")" || _resolve_rc=$?
    if [ "$_resolve_rc" -ne 0 ] || [ -z "$_exports" ]; then
      echo "agent.sh: warning: parameter resolution failed for SKW_RESOLVE_STAGE=${SKW_RESOLVE_STAGE} (exit ${_resolve_rc:-1}); falling back to skw.toml defaults" >&2
      _resolve_rc=0
      _exports="$(_skw_resolve_exports "")" || _resolve_rc=$?
      if [ "$_resolve_rc" -ne 0 ] || [ -z "$_exports" ]; then
        echo "agent.sh: warning: skw.toml fallback resolution also failed; using shell defaults" >&2
        _exports=""
      fi
    fi
    if [ -n "$_exports" ]; then
      # shellcheck disable=SC1090
      eval "$_exports"
    fi
  fi
fi

AGENT_BIN="${SKW_AGENT_BIN:-cursor-agent}"
MODEL="${SKW_MODEL:-auto}"
PERMS="${SKW_PERMS:---force}"
PLUGIN_DIR="${SKW_PLUGIN_DIR:-}"
WORKSPACE="${SKW_WORKSPACE:-$PWD}"
OUTPUT_FMT="${SKW_OUTPUT_FMT:-text}"
DRYRUN="${SKW_DRYRUN:-0}"

argv=("$AGENT_BIN" -p --output-format "$OUTPUT_FMT" --workspace "$WORKSPACE" --model "$MODEL")
# shellcheck disable=SC2086
[ -n "${SKW_EXTRA_ARGS:-}" ] && eval "argv+=($SKW_EXTRA_ARGS)"
# shellcheck disable=SC2206  # intentional word-split: PERMS may carry several flags
[ -n "$PERMS" ] && argv+=($PERMS)
[ -n "$PLUGIN_DIR" ] && argv+=(--plugin-dir "$PLUGIN_DIR")
if [ "$AGENT_BIN" = "claude" ] && [ -n "${SKW_EFFORT:-}" ]; then
  _has_effort=0
  for _arg in "${argv[@]}"; do
    if [ "$_arg" = "--effort" ]; then
      _has_effort=1
      break
    fi
  done
  if [ "$_has_effort" -eq 0 ]; then
    argv+=(--effort "$SKW_EFFORT")
  fi
fi
argv+=("$prompt")

if [ "$DRYRUN" = "1" ]; then
  echo "[dry-run] would exec ($(basename "$label"), prompt ${#prompt} chars):"
  printf '  %q' "${argv[@]:0:${#argv[@]}-1}"
  printf ' '\''<%s prompt, %d chars>'\''\n' "$label" "${#prompt}"
  exit 0
fi

exec "${argv[@]}"
