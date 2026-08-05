#!/usr/bin/env bash
# Install a pinned uv release from GitHub with in-repo checksum verification (C11.2 / D47).
#
# Usage: UV_VERSION=0.12.1 ./scripts/install_uv_verified.sh
# Downloads the platform archive from the matching GitHub release, verifies it
# against the **in-repo** SHA-256 pin below (not the release's sha256.sum — that
# would be TOFU if the release were compromised), then extracts ``uv`` / ``uvx``
# into ~/.local/bin.
#
# When bumping UV_VERSION, update PINNED_UV_VERSION and UV_SHA256_* together.
set -euo pipefail

UV_VERSION="${UV_VERSION:?UV_VERSION must be set (e.g. 0.12.1)}"
DEST_DIR="${UV_INSTALL_DIR:-${HOME}/.local/bin}"
BASE_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"

# In-repo pins for astral-sh/uv 0.12.1 (GitHub release sha256.sum, 2026-08-05).
PINNED_UV_VERSION="0.12.1"
UV_SHA256_x86_64_apple_darwin="69d9f9a00337f25a50dcb13882052da08b8469bac11091c98c5694c3c6721467"
UV_SHA256_aarch64_apple_darwin="77d2906988e8074fd43f2f329ec452ebbf9b0c257ba1c66451c71de70a6baf42"
UV_SHA256_x86_64_unknown_linux_gnu="90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb"
UV_SHA256_aarch64_unknown_linux_gnu="769d373e146692c639b5fbaae33b331c297a32e03d30448772051902df52bbf4"

if [[ "${UV_VERSION}" != "${PINNED_UV_VERSION}" ]]; then
  echo "install_uv_verified: UV_VERSION=${UV_VERSION} does not match in-repo pin ${PINNED_UV_VERSION}" >&2
  echo "  bump PINNED_UV_VERSION and UV_SHA256_* in this script together with Makefile UV_VERSION" >&2
  exit 1
fi

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
pin_var="UV_SHA256_${arch_tag}_${os_tag//-/_}"
expected="${!pin_var-}"
if [[ -z "${expected}" ]]; then
  echo "install_uv_verified: no in-repo SHA-256 pin for ${archive} (${pin_var})" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

echo "Downloading uv ${UV_VERSION} (${archive}) ..."
curl -fsSL -o "${tmpdir}/${archive}" "${BASE_URL}/${archive}"

if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "${tmpdir}/${archive}" | awk '{print $1}')"
else
  actual="$(shasum -a 256 "${tmpdir}/${archive}" | awk '{print $1}')"
fi

if [[ "${actual}" != "${expected}" ]]; then
  echo "install_uv_verified: checksum mismatch for ${archive}" >&2
  echo "  expected (in-repo): ${expected}" >&2
  echo "  actual:             ${actual}" >&2
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
