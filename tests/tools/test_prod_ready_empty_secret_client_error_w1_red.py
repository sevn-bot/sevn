"""Prod-ready Batch A W1.4 RED — empty resolved secret fails loudly (C3.3).

Guarded-route clients must raise a named, actionable error when the resolved
shared secret is empty, rather than sending an empty ``X-Sevn-Proxy-Token`` and
surfacing an opaque 401. Covers ``tools/web.py``, ``tools/integration_proxy_client.py``,
``integrations/proxy_client.py``, and ``integrations/github_skill/hooks.py``.
Green after W3.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_SECRET_NAME = "SEVN_PROXY_SHARED_SECRET"
_REMEDY_MARKERS = ("set", "configure", "generate", "secrets put", "onboard")


def _import_unconfigured_error() -> type[BaseException]:
    """Resolve the named C3.3 exception (W3 deliverable)."""
    from sevn.tools.web import ProxySharedSecretUnconfiguredError

    return ProxySharedSecretUnconfiguredError


def _assert_actionable(exc: BaseException) -> None:
    message = str(exc)
    assert _SECRET_NAME in message, f"error must name {_SECRET_NAME!r}: {message!r}"
    lowered = message.lower()
    assert any(marker in lowered for marker in _REMEDY_MARKERS), (
        f"error must name a remedy: {message!r}"
    )


def test_proxy_shared_secret_unconfigured_error_is_exported() -> None:
    """W1.4: named exception is a public ``sevn.tools.web`` export."""
    exc_type = _import_unconfigured_error()
    assert issubclass(exc_type, Exception)
    assert exc_type.__name__ == "ProxySharedSecretUnconfiguredError"


def test_build_egress_web_headers_raises_on_empty_secret() -> None:
    """W1.4: header builder refuses to omit the token for a guarded call."""
    from sevn.tools.web import build_egress_web_headers

    exc_type = _import_unconfigured_error()
    with pytest.raises(exc_type) as caught:
        build_egress_web_headers(
            proxy_url="http://127.0.0.1:8787",
            session_token="sess",
            proxy_shared_secret=None,
        )
    _assert_actionable(caught.value)

    with pytest.raises(exc_type) as caught_empty:
        build_egress_web_headers(
            proxy_url="http://127.0.0.1:8787",
            session_token="sess",
            proxy_shared_secret="   ",
        )
    _assert_actionable(caught_empty.value)


@pytest.mark.anyio
async def test_web_process_egress_raises_when_secret_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.4 / tools/web.py: call-time failure before any proxy POST."""
    monkeypatch.setenv("SEVN_PROXY_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.delenv("SEVN_SESSION_TOKEN", raising=False)

    from sevn.tools import web as web_mod

    exc_type = _import_unconfigured_error()
    with (
        patch.object(web_mod, "proxy_post_json", new_callable=AsyncMock) as post,
        pytest.raises(exc_type) as caught,
    ):
        await web_mod._proxy_web_fetch_single(url="https://example.com/page")
    post.assert_not_awaited()
    _assert_actionable(caught.value)


def test_resolve_process_egress_reads_generate_once_file_when_env_blank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thermos T3: ProcessSettings env blank still resolves the SEVN_HOME generate-once file."""
    from sevn.proxy.bootstrap_secret import ensure_proxy_shared_secret_file
    from sevn.tools.web import _resolve_process_egress

    file_secret = "file-backed-egress-secret-value-32b"
    monkeypatch.setenv("SEVN_PROXY_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.delenv("SEVN_SESSION_TOKEN", raising=False)
    ensure_proxy_shared_secret_file(tmp_path, secret=file_secret)

    proxy_url, session_token, shared_secret = _resolve_process_egress()
    assert proxy_url == "http://127.0.0.1:8787"
    assert session_token is None
    assert shared_secret == file_secret


@pytest.mark.anyio
async def test_integration_proxy_client_raises_on_empty_secret() -> None:
    """W1.4 / tools/integration_proxy_client.py: live client refuses empty secret."""
    from sevn.tools.context import ToolContext
    from sevn.tools.integration_proxy_client import EgressIntegrationProxyClient

    exc_type = _import_unconfigured_error()
    client = EgressIntegrationProxyClient(
        proxy_url="http://127.0.0.1:8787",
        session_token="sess",
        proxy_shared_secret=None,
    )
    ctx = ToolContext(
        session_id="s1",
        workspace_path=Path("/tmp"),
        workspace_id="ws",
        registry_version=1,
    )
    with (
        patch(
            "sevn.tools.integration_proxy_client.proxy_post_json",
            new_callable=AsyncMock,
        ) as post,
        pytest.raises(exc_type) as caught,
    ):
        await client.integration_call(
            service="github",
            method="pulls.list",
            args={},
            ctx=ctx,
        )
    post.assert_not_awaited()
    _assert_actionable(caught.value)


@pytest.mark.anyio
async def test_integrations_proxy_client_raises_on_empty_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.4 / integrations/proxy_client.py: skill helper refuses empty secret."""
    monkeypatch.setenv("SEVN_PROXY_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)

    from sevn.integrations import proxy_client as pc

    exc_type = _import_unconfigured_error()
    with (
        patch.object(pc, "proxy_post_json", new_callable=AsyncMock) as post,
        pytest.raises(exc_type) as caught,
    ):
        await pc.integration_post_async(service="github", method="pulls.list", args={})
    post.assert_not_awaited()
    _assert_actionable(caught.value)


@pytest.mark.anyio
async def test_github_hooks_raise_on_empty_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.4 / integrations/github_skill/hooks.py: GitHub proxy caller refuses empty secret."""
    monkeypatch.setenv("SEVN_PROXY_URL", "http://127.0.0.1:8787")
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)

    from sevn.integrations.github_skill import hooks

    exc_type = _import_unconfigured_error()
    call = hooks.proxy_github_integration_call()
    with (
        patch.object(hooks, "proxy_post_json", new_callable=AsyncMock) as post,
        pytest.raises(exc_type) as caught,
    ):
        await call("pulls.list", {})
    post.assert_not_awaited()
    _assert_actionable(caught.value)


def test_build_integration_proxy_client_does_not_silently_fill_from_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.4 edge: factory must not paper over a missing injected secret via os.environ."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", "should-not-be-read")
    from sevn.tools.integration_proxy_client import build_integration_proxy_client

    client = build_integration_proxy_client(
        proxy_url="http://127.0.0.1:8787",
        proxy_shared_secret=None,
    )
    assert client is not None
    # After W3 the factory keeps the injected None; call-time raises instead of env fill.
    assert client.proxy_shared_secret is None
    # And it must not have copied from environ as a fallback.
    assert getattr(client, "proxy_shared_secret", None) != "should-not-be-read"
