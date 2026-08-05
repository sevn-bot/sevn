#!/usr/bin/env bash
# Install a pinned uv release from GitHub with checksum verification (C11.2 / D47).
#
# Usage: UV_VERSION=0.12.1 ./scripts/install_uv_verified.sh
# Downloads the platform archive + sha256.sum from the matching GitHub release,
# verifies the archive checksum, then extracts ``uv`` / ``uvx`` into ~/.local/bin.
set -euo pipefail

UV_VERSION="${UV_VERSION:?UV_VERSION must be set (e.g. 0.12.1)}"
DEST_DIR="${UV_INSTALL_DIR:-${HOME}/.local/bin}"
BASE_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"

os="$(uname -s)"
arch="$(uname -m)"
case "${os}" in
  Darwin) os_tag="apple-darwin" ;;
  Linux) os_tag="unknown-linux-gnu" ;;
  *)
    echo "install_uv_verified: unsupported OS ${os}" >&2
    exit 1
    ;;
esac
case "${arch}" in
  x86_64 | amd64) arch_tag="x86_64" ;;
  arm64 | aarch64) arch_tag="aarch64" ;;
  *)
    echo "install_uv_verified: unsupported arch ${arch}" >&2
    exit 1
    ;;
esac

archive="uv-${arch_tag}-${os_tag}.tar.gz"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

echo "Downloading uv ${UV_VERSION} (${archive}) ..."
curl -fsSL -o "${tmpdir}/${archive}" "${BASE_URL}/${archive}"
curl -fsSL -o "${tmpdir}/sha256.sum" "${BASE_URL}/sha256.sum"

expected="$(
  awk -v f="${archive}" '
    $2 == f || $2 == ("*" f) { print $1; found=1; exit }
    END { if (!found) exit 1 }
  ' "${tmpdir}/sha256.sum"
)" || {
  echo "install_uv_verified: no checksum entry for ${archive} in sha256.sum" >&2
  exit 1
}

if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "${tmpdir}/${archive}" | awk '{print $1}')"
else
  actual="$(shasum -a 256 "${tmpdir}/${archive}" | awk '{print $1}')"
fi

if [[ "${actual}" != "${expected}" ]]; then
  echo "install_uv_verified: checksum mismatch for ${archive}" >&2
  echo "  expected: ${expected}" >&2
  echo "  actual:   ${actual}" >&2
  exit 1
fi
echo "checksum ok: ${archive} (${actual})"

mkdir -p "${DEST_DIR}"
tar -xzf "${tmpdir}/${archive}" -C "${tmpdir}"
# Archive layout is either flat (uv, uvx) or a single top-level directory.
if [[ -x "${tmpdir}/uv" ]]; then
  install -m 0755 "${tmpdir}/uv" "${DEST_DIR}/uv"
  [[ -x "${tmpdir}/uvx" ]] && install -m 0755 "${tmpdir}/uvx" "${DEST_DIR}/uvx"
else
  inner="$(find "${tmpdir}" -maxdepth 2 -type f -name uv -perm -111 | head -n 1)"
  if [[ -z "${inner}" ]]; then
    echo "install_uv_verified: uv binary missing from ${archive}" >&2
    exit 1
  fi
  install -m 0755 "${inner}" "${DEST_DIR}/uv"
  uvx_inner="$(dirname "${inner}")/uvx"
  [[ -x "${uvx_inner}" ]] && install -m 0755 "${uvx_inner}" "${DEST_DIR}/uvx"
fi

test -x "${DEST_DIR}/uv" || {
  echo "install_uv_verified: ${DEST_DIR}/uv missing after install" >&2
  exit 1
}
echo "Installed uv ${UV_VERSION} → ${DEST_DIR}/uv"
"${DEST_DIR}/uv" --version
