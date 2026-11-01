"""Scripted Ollama ``/api/chat`` endpoint. No real Ollama process."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeOllama:
    """Loopback server. ``GET /`` answers; ``POST /api/chat`` returns ``content``."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[dict[str, object]] = []
        self.url = ""
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> FakeOllama:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                parsed: object = {}
                if raw:
                    loaded = json.loads(raw.decode())
                    parsed = loaded if isinstance(loaded, dict) else {"raw": loaded}
                owner.requests.append({"path": self.path, "body": parsed})
                payload = json.dumps(
                    {
                        "model": "llama3.2:3b",
                        "done": True,
                        "message": {"role": "assistant", "content": owner.content},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: Any) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd = server
        port = int(server.server_address[1])
        self.url = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._thread = thread
        return self

    def __exit__(self, *_exc: object) -> None:
        server = self._httpd
        if server is not None:
            server.shutdown()
            server.server_close()
        self._httpd = None

    def text(self) -> str:
        return json.dumps(self.requests, default=str, ensure_ascii=False)
