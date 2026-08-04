#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Bootstrap /operator/workspace/sevn.json on first boot, then exec the gateway CMD (#177).

set -euo pipefail

export SEVN_HOME="${SEVN_HOME:-/operator}"
SEVN_JSON="${SEVN_HOME}/workspace/sevn.json"

if [[ ! -f "${SEVN_JSON}" ]]; then
  echo "gateway entrypoint: ${SEVN_JSON} missing — running compose bootstrap"
  python /opt/sevn/infra/docker/compose-bootstrap.py
fi

exec "$@"
