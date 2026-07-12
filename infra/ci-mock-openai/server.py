"""Minimal OpenAI Chat Completions upstream for compose-backed CI (Wave D).

Module: server (infra image only)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    """Return a fixed JSON body for ``POST …/v1/chat/completions``."""

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        """Handle chat completions POST."""
        path = self.path.split("?", 1)[0].rstrip("/")
        if path.endswith("/chat/completions"):
            payload = {
                "id": "ci-mock",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404, "not found")


def main() -> None:
    """Listen on ``0.0.0.0:9090`` until interrupted."""
    HTTPServer(("0.0.0.0", 9090), _Handler).serve_forever()


if __name__ == "__main__":
    main()
