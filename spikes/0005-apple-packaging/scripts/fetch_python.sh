#!/bin/bash
# Download a pinned python-build-standalone CPython 3.13 install_only prefix.
# Checksums come from the release SHA256SUMS file (tag 20261013).

set -euo pipefail

SPIKE="$(cd "$(dirname "$0")/.." && pwd)"
TAG="20261013"
PYVER="3.13.16"

case "$(uname -m)" in
arm64)
    TRIPLE="aarch64-apple-darwin"
    SHA="ca0e6a70fb75a0984751bd75493e3de77680aef7fbd0fea9b903c299537b3423"
    ;;
x86_64)
    TRIPLE="x86_64-apple-darwin"
    SHA="d1f2e7b5f0cfa25fc856fea819890bbe722f47a692e5ce2552636b5240930b38"
    ;;
*)
    echo "unsupported architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

NAME="cpython-${PYVER}+${TAG}-${TRIPLE}-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${TAG}/${NAME}"
CACHE="${SPIKE}/build/cache"
PREFIX="${SPIKE}/build/python"
STAMP="${PREFIX}/.fetch-stamp"
TARBALL="${CACHE}/${NAME}"

if [[ -x "${PREFIX}/bin/python3.13" && -f "${STAMP}" && "$(cat "${STAMP}")" == "${SHA}" ]]; then
    printf '%s\n' "${PREFIX}"
    exit 0
fi

mkdir -p "${CACHE}"
if [[ ! -f "${TARBALL}" ]] || ! printf '%s  %s\n' "${SHA}" "${TARBALL}" | shasum -a 256 -c - >/dev/null 2>&1; then
    echo "fetching ${URL}" >&2
    curl -fL --retry 3 --retry-delay 2 -o "${TARBALL}.partial" "${URL}"
    mv "${TARBALL}.partial" "${TARBALL}"
fi

printf '%s  %s\n' "${SHA}" "${TARBALL}" | shasum -a 256 -c -
xattr -d com.apple.quarantine "${TARBALL}" 2>/dev/null || true

rm -rf "${PREFIX}"
mkdir -p "${PREFIX}"
tar -xzf "${TARBALL}" -C "${PREFIX}" --strip-components=1
xattr -dr com.apple.quarantine "${PREFIX}" 2>/dev/null || true
printf '%s\n' "${SHA}" >"${STAMP}"
printf '%s\n' "${PREFIX}"
