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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "session_bus: keep DBUS_SESSION_BUS_ADDRESS so the test can reach the real session bus",
    )


@pytest.fixture(autouse=True)
def _no_session_bus(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests off the real Secret Service (plan 0025 D4).

    With ``secrets.backend`` unset, Linux selection probes the session bus, so a
    test on a Linux desktop could otherwise read or write the user's keyring.
    Tests that need a bus set the variable themselves (to a fake address) or opt
    in with ``@pytest.mark.session_bus``.
    """
    if request.node.get_closest_marker("session_bus") is None:
        monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)


@pytest.fixture
def host_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[object, str, object]]:
    """Lifespan stays open. Yields `(app, token, client)`."""
    with running_app(tmp_path, monkeypatch) as opened:
        yield opened
