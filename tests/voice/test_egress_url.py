"""Tests for ``sevn.voice.egress`` (`specs/20-voice.md` §10.3)."""

from __future__ import annotations

from sevn.voice.egress import voice_http_base_url


def test_voice_http_base_url_prefers_process_over_workspace() -> None:
    assert (
        voice_http_base_url(
            process_proxy_url="http://proc/",
            workspace_proxy_url="http://ws",
        )
        == "http://proc"
    )


def test_voice_http_base_url_falls_back_to_workspace() -> None:
    assert (
        voice_http_base_url(
            process_proxy_url=None,
            workspace_proxy_url="https://ws.example/proxy",
        )
        == "https://ws.example/proxy"
    )


def test_voice_http_base_url_returns_none_when_unset() -> None:
    assert voice_http_base_url(process_proxy_url=None, workspace_proxy_url=None) is None
