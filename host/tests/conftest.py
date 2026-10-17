"""Shared fixtures. Product imports stay inside fixtures so collection succeeds."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

# Append, do not prepend: host/tests/secrets must not shadow the stdlib secrets module.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.append(_TESTS_DIR)

import pytest  # noqa: E402
from support.http_app import running_app  # noqa: E402


@pytest.fixture
def host_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[object, str, object]]:
    """Lifespan stays open. Yields `(app, token, client)`."""
    with running_app(tmp_path, monkeypatch) as opened:
        yield opened
