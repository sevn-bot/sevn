#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Install Brave Browser from the official apt repository (amd64 + arm64).
# Idempotent: safe to re-run in Docker image builds.
#
# Optional build args (environment):
#   BRAVE_VERSION — pin apt package version (e.g. 1.73.97); default: latest stable
#
# Proxy and ci-mock-openai images intentionally omit this script — they never run
# browser skills. Gateway and sandbox images opt in via Dockerfile COPY + RUN.

set -euo pipefail

BRAVE_VERSION="${BRAVE_VERSION:-}"

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends curl ca-certificates gnupg

install -d -m 0755 /usr/share/keyrings
curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg \
    https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg

cat >/etc/apt/sources.list.d/brave-browser-release.list <<'EOF'
deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main
EOF

apt-get update
if [[ -n "${BRAVE_VERSION}" ]]; then
    apt-get install -y --no-install-recommends "brave-browser=${BRAVE_VERSION}"
else
    apt-get install -y --no-install-recommends brave-browser
fi

rm -rf /var/lib/apt/lists/*

if ! command -v brave-browser >/dev/null 2>&1; then
    echo "install-brave.sh: brave-browser not found on PATH after install" >&2
    exit 1
fi

brave-browser --version
