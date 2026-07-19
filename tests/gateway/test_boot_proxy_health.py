"""RED suite for gateway boot proxy-health gate (D8; green after W6)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from sevn.config.settings import ProcessSettings


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W6: boot proxy health gate", strict=False)
async def test_boot_waits_for_proxy_health_with_capped_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8: gateway health-polls ``/healthz`` with bounded retry before channels up."""
    from sevn.gateway.http_server import wait_for_proxy_boot_health

    attempts: list[float] = []

    class _FlakyClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FlakyClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            attempts.append(time.monotonic())
            if len(attempts) < 2:
                raise httpx.ConnectError("proxy down", request=httpx.Request("GET", url))
            return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr("sevn.gateway.http_server.httpx.AsyncClient", _FlakyClient)
    process = ProcessSettings(proxy_url="http://127.0.0.1:8787")
    ok = await wait_for_proxy_boot_health(process, max_wait_s=5.0, poll_interval_s=0.05)
    assert ok is True
    assert len(attempts) >= 2
    assert attempts[-1] - attempts[0] <= 5.5


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W6: degraded boot when proxy stays down", strict=False)
async def test_boot_proceeds_degraded_when_proxy_never_comes_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8: when proxy never becomes healthy, boot proceeds degraded without hanging."""
    from sevn.gateway.http_server import wait_for_proxy_boot_health

    class _DownClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _DownClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            raise httpx.ConnectError("proxy down", request=httpx.Request("GET", url))

    monkeypatch.setattr("sevn.gateway.http_server.httpx.AsyncClient", _DownClient)
    process = ProcessSettings(proxy_url="http://127.0.0.1:8787")
    started = time.monotonic()
    ok = await wait_for_proxy_boot_health(process, max_wait_s=0.25, poll_interval_s=0.05)
    elapsed = time.monotonic() - started
    assert ok is False
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_log_only_boot_health_exists_today() -> None:
    """Baseline: today's boot path exposes the log-only probe helper."""
    from sevn.gateway.http_server import _log_proxy_boot_health

    process = ProcessSettings(proxy_url="http://127.0.0.1:1")
    await asyncio.wait_for(_log_proxy_boot_health(process), timeout=2.0)
