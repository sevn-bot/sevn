"""Serve GET /health on 127.0.0.1:$SEVN_SPIKE_PORT."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _HealthServer(ThreadingHTTPServer):
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/health":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"ok":true}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def main() -> None:
    raw = os.environ.get("SEVN_SPIKE_PORT", "")
    if not raw.isdigit():
        raise SystemExit("SEVN_SPIKE_PORT is required")
    port = int(raw)
    if not 1 <= port <= 65535:
        raise SystemExit("SEVN_SPIKE_PORT out of range")
    _HealthServer(("127.0.0.1", port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
