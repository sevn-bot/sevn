#!/bin/bash
# Build SevnSpike, then copy Python, site, server, helper, and the launch agent into the app.
# The bundle is ad-hoc signed. Developer ID signing belongs to sign.sh (W3).

set -euo pipefail

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode-16.4.0.app/Contents/Developer}"
export PATH="${HOME}/.cargo/bin:${PATH}"

SPIKE="$(cd "$(dirname "$0")/.." && pwd)"
APP="${SPIKE}/app/build/Build/Products/Release/SevnSpike.app"
PREFIX="${SPIKE}/build/python"
SITE="${SPIKE}/build/site"
HELPER="${SPIKE}/build/helper/release/sevn-helper"
HOST="${SPIKE}/build/sevn-host"

echo "building SevnSpike" >&2
xcodebuild \
    -project "${SPIKE}/app/SevnSpike.xcodeproj" \
    -scheme SevnSpike \
    -configuration Release \
    -destination "platform=macOS" \
    -derivedDataPath "${SPIKE}/app/build" \
    CODE_SIGN_IDENTITY="-" \
    CODE_SIGN_STYLE=Manual \
    build

echo "building helper" >&2
cargo build --release --manifest-path "${SPIKE}/helper/Cargo.toml" --target-dir "${SPIKE}/build/helper"

echo "compiling sevn-host" >&2
xcrun --sdk macosx clang \
    -mmacosx-version-min=15.0 \
    -O2 -Wall -Wextra -Werror \
    -o "${HOST}" \
    "${SPIKE}/scripts/sevn-host.c"

echo "fetching python" >&2
"${SPIKE}/scripts/fetch_python.sh" >/dev/null

echo "installing server into site" >&2
rm -rf "${SITE}"
uv pip install --python "${PREFIX}/bin/python3.13" --target "${SITE}" "${SPIKE}/server"

echo "copying into ${APP}" >&2
rm -rf \
    "${APP}/Contents/Resources/python" \
    "${APP}/Contents/Resources/site" \
    "${APP}/Contents/Resources/server"
mkdir -p \
    "${APP}/Contents/Resources" \
    "${APP}/Contents/MacOS" \
    "${APP}/Contents/Library/LaunchAgents" \
    "${APP}/Contents/Resources/server"
cp -R "${PREFIX}/." "${APP}/Contents/Resources/python/"
cp -R "${SITE}/." "${APP}/Contents/Resources/site/"
cp -R "${SPIKE}/server/src/sevn_spike_server" "${APP}/Contents/Resources/server/sevn_spike_server"
cp "${HELPER}" "${APP}/Contents/MacOS/sevn-helper"
cp "${HOST}" "${APP}/Contents/MacOS/sevn-host"
cp "${SPIKE}/app/LaunchAgents/com.sevn.spike.host.plist" \
    "${APP}/Contents/Library/LaunchAgents/com.sevn.spike.host.plist"
chmod +x \
    "${APP}/Contents/MacOS/sevn-host" \
    "${APP}/Contents/MacOS/sevn-helper" \
    "${APP}/Contents/Resources/python/bin/python3.13"

xattr -dr com.apple.quarantine "${APP}" 2>/dev/null || true
xattr -cr "${APP}" 2>/dev/null || true

echo "ad-hoc signing" >&2
codesign --force --sign - "${APP}/Contents/MacOS/sevn-helper"
codesign --force --sign - "${APP}/Contents/MacOS/sevn-host"
codesign --force --sign - "${APP}"

printf '%s\n' "${APP}"
