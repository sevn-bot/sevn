#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Normalize workspace layout for sevnoperator before GUI stack boot.

set -euo pipefail

SEVN_ROOT="${SEVN_HOME:-/operator}"
WORKSPACE="${SEVN_ROOT}/workspace"

mkdir -p \
    "${WORKSPACE}/.sevn/browser-profiles" \
    "${WORKSPACE}/.sevn/browser-sessions" \
    "${WORKSPACE}/logs"

if [[ ! -f "${WORKSPACE}/sevn.json" ]]; then
    echo "gui entrypoint: ${WORKSPACE}/sevn.json missing — running compose bootstrap"
    python /opt/sevn/infra/docker/compose-bootstrap.py
fi

# Ownership normalization is handled by sevn-operator-perms (D25); no chown here.

exec supervisord -c /opt/sevn/infra/docker/gui/supervisord.conf
