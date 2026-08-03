#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Normalize workspace ownership for sevnoperator before GUI stack boot.

set -euo pipefail

SEVN_ROOT="${SEVN_HOME:-/operator}"
WORKSPACE="${SEVN_ROOT}/workspace"

mkdir -p \
    "${WORKSPACE}/.sevn/browser-profiles" \
    "${WORKSPACE}/.sevn/browser-sessions" \
    "${WORKSPACE}/logs"

OWNERSHIP_SENTINEL="${WORKSPACE}/.sevn/.ownership-normalized"
if [[ ! -f "${OWNERSHIP_SENTINEL}" ]]; then
    # One-shot fix for prior root-run `--profile browser` sessions on a shared volume.
    chown -R sevnoperator:sevnoperator "${WORKSPACE}/.sevn" "${WORKSPACE}/logs" 2>/dev/null || true
    touch "${OWNERSHIP_SENTINEL}"
    chown sevnoperator:sevnoperator "${OWNERSHIP_SENTINEL}" 2>/dev/null || true
fi

exec supervisord -c /opt/sevn/infra/docker/gui/supervisord.conf
