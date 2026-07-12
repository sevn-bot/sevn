#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Start virtual display, window manager, VNC, and noVNC for headed Brave in Docker.

set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"

Xvfb "${DISPLAY}" -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

sleep 1

openbox &
OPENBOX_PID=$!

x11vnc -display "${DISPLAY}" -forever -shared -rfbport 5900 -localhost -xkb &
VNC_PID=$!

websockify --web /usr/share/novnc 127.0.0.1:6080 localhost:5900 &
NOVNC_PID=$!

cleanup() {
    kill "${NOVNC_PID}" "${VNC_PID}" "${OPENBOX_PID}" "${XVFB_PID}" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:6080/vnc.html" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -fsS "http://127.0.0.1:6080/vnc.html" >/dev/null 2>&1; then
    echo "start-desktop.sh: noVNC did not become ready on port 6080" >&2
    exit 1
fi

# Exit when any critical desktop component dies so supervisord can restart the stack.
wait -n "${NOVNC_PID}" "${VNC_PID}" "${XVFB_PID}" "${OPENBOX_PID}"
exit 1
