"""Unit tests for ``sevn.model_eval.compare._proxy_headers`` (Thermos T3 / A-R5)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.model_eval.compare import _proxy_headers
from sevn.proxy.bootstrap_secret import ensure_proxy_shared_secret_file

if TYPE_CHECKING:
    import pytest

_FILE_SECRET = "model-eval-compare-file-secret-32chars!"


def test_proxy_headers_reads_generate_once_file_when_env_blank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank env + generate-once file under SEVN_HOME still yields X-Sevn-Proxy-Token."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.delenv("SEVN_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    ensure_proxy_shared_secret_file(tmp_path, secret=_FILE_SECRET)

    headers = _proxy_headers()

    assert headers.get("X-Sevn-Proxy-Token") == _FILE_SECRET
    assert "X-Sevn-Session-Token" not in headers


def test_proxy_headers_env_wins_over_generate_once_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit env secret takes precedence over the generate-once file."""
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_SESSION_TOKEN", raising=False)
    ensure_proxy_shared_secret_file(tmp_path, secret=_FILE_SECRET)
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", "env-wins-model-eval-secret-32chars!")

    headers = _proxy_headers()

    assert headers.get("X-Sevn-Proxy-Token") == "env-wins-model-eval-secret-32chars!"
