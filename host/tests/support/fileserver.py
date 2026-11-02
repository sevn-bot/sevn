"""Local HTTP file server on 127.0.0.1 for download tests (no network)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FileServer:
    """Serves ``root``. Records request paths; ``slow`` paths sleep before answering."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.requests: list[str] = []
        self.slow: dict[str, float] = {}
        self.port = 0

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url(self, relative: str) -> str:
        return f"{self.base}/{relative.lstrip('/')}"

    def put(self, relative: str, data: bytes) -> str:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return self.url(relative)


def _handler(server: FileServer) -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            server.requests.append(self.path)
            delay = server.slow.get(self.path.split("?", 1)[0], 0.0)
            if delay:
                time.sleep(delay)
            super().do_GET()

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


@contextmanager
def serve_files(root: Path) -> Iterator[FileServer]:
    root.mkdir(parents=True, exist_ok=True)
    state = FileServer(root)
    handler = partial(_handler(state), directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    state.port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
