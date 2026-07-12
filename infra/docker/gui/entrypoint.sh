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

# Prior root-run `--profile browser` sessions may leave root-owned profiles on the shared volume.
chown -R sevnoperator:sevnoperator "${WORKSPACE}/.sevn" "${WORKSPACE}/logs" 2>/dev/null || true

exec supervisord -c /opt/sevn/infra/docker/gui/supervisord.conf
