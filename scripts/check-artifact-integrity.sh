#!/usr/bin/env bash
# Install wheel + sdist into clean venvs; assert sevn and proton-cli entry points work (#148).
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

UV="${UV:-uv}"

if ! compgen -G "dist/*.whl" >/dev/null || ! compgen -G "dist/*.tar.gz" >/dev/null; then
  echo "error: dist/*.whl and dist/*.tar.gz required — run 'make build' first" >&2
  exit 1
fi

for artifact in dist/*.whl dist/*.tar.gz; do
  [ -e "$artifact" ] || continue
  label="$(basename "$artifact" | tr '/.' '__')"
  venv="/tmp/sevn-artifact-integrity-${label}"
  rm -rf "$venv"
  "$UV" venv "$venv"
  "$UV" pip install --python "$venv/bin/python" --quiet "$artifact"
  "$venv/bin/sevn" --version >/dev/null
  "$venv/bin/proton-cli" --version >/dev/null
  rm -rf "$venv"
  echo "ok: $artifact"
done
