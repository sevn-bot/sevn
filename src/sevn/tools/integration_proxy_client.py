"""Egress-paired ``/integration`` client for gateway ``integration_call`` (Wave W2).

Module: sevn.tools.integration_proxy_client
Depends: os, sevn.config.settings, sevn.tools.context, sevn.tools.web

Exports:
    IntegrationCredentialRequired — typed error when proxy secrets lack a provider token.
    EgressIntegrationProxyClient — live :class:`~sevn.tools.runtime_dispatch.IntegrationProxyClient`.
    build_integration_proxy_client — factory for gateway boot (W3 factory seam).

Examples:
    >>> build_integration_proxy_client(proxy_url=None) is None
    True
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Final

from sevn.tools.context import ToolContext
from sevn.tools.web import build_egress_web_headers, proxy_post_json

_PROXY_INTEGRATION_PATH: Final[str] = "/integration"
_CREDENTIAL_MARKERS: Final[tuple[str, ...]] = (
    "not configured",
    "api key",
    "token",
    "credential",
)


class IntegrationCredentialRequired(Exception):
    """Raised when the egress proxy reports a missing integration provider token."""

    def __init__(
        self,
        detail: str,
        *,
        service: str,
        method: str,
    ) -> None:
        """Capture provider context for §3.1 envelope mapping.

        Args:
            detail (str): Proxy ``detail`` string.
            service (str): Integration namespace (``github``, ``cursor``, ...).
            method (str): Dotted method identifier.

        Returns:
            None

        Examples:
            >>> err = IntegrationCredentialRequired(
            ...     "GitHub token not configured",
            ...     service="github",
            ...     method="pulls.list",
            ... )
            >>> err.service
            'github'
        """
        super().__init__(detail)
        self.service = service
        self.method = method
        self.detail = detail


@dataclass(frozen=True)
class EgressIntegrationProxyClient:
    """POST ``{service, method, args}`` to the paired egress proxy ``/integration`` route."""

    proxy_url: str
    session_token: str | None = None
    proxy_shared_secret: str | None = None

    async def integration_call(
        self,
        *,
        service: str,
        method: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> dict[str, Any]:
        """Forward one integration dispatch to the egress proxy.

        Args:
            service (str): Integration namespace (``github``, ``cursor``, ...).
            method (str): Dotted method within ``service``.
            args (dict[str, Any]): JSON-safe payload forwarded verbatim.
            ctx (ToolContext): Active tool frame (reserved for future trace headers).

        Returns:
            dict[str, Any]: Decoded proxy JSON body on success.

        Raises:
            IntegrationCredentialRequired: When the proxy returns 503 for a missing token.
            RuntimeError: For other proxy/transport failures.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EgressIntegrationProxyClient.integration_call)
            True
        """
        _ = ctx
        body = {
            "service": service.strip(),
            "method": method.strip(),
            "args": dict(args),
        }
        headers = build_egress_web_headers(
            proxy_url=self.proxy_url,
            session_token=self.session_token,
            proxy_shared_secret=self.proxy_shared_secret,
        )
        status, data = await proxy_post_json(
            proxy_url=self.proxy_url,
            path=_PROXY_INTEGRATION_PATH,
            body=body,
            headers=headers,
        )
        detail = str(data.get("detail") or data.get("error") or f"proxy status {status}")
        if status == 503 and _detail_needs_credential(detail):
            raise IntegrationCredentialRequired(
                detail,
                service=service,
                method=method,
            )
        if status >= 400:
            raise RuntimeError(detail)
        return data


def _detail_needs_credential(detail: str) -> bool:
    """Return whether a proxy ``detail`` string indicates a missing provider token.

    Args:
        detail (str): Proxy error detail.

    Returns:
        bool: ``True`` when the message looks like a credential/configuration gap.

    Examples:
        >>> _detail_needs_credential("GitHub token not configured")
        True
        >>> _detail_needs_credential("unknown integration service: foo")
        False
    """
    lowered = detail.lower()
    return any(marker in lowered for marker in _CREDENTIAL_MARKERS)


def build_integration_proxy_client(
    *,
    proxy_url: str | None,
    session_token: str | None = None,
    proxy_shared_secret: str | None = None,
) -> EgressIntegrationProxyClient | None:
    """Build a live integration client when ``proxy_url`` is configured.

    W3 folds this into the single ``RuntimeToolBindings`` factory; pass the result as
    ``RuntimeToolBindings(integration=build_integration_proxy_client(...), ...)``.

    Args:
        proxy_url (str | None): Resolved egress proxy origin (``SEVN_PROXY_URL``).
        session_token (str | None, optional): Per-run session token header value.
        proxy_shared_secret (str | None, optional): Optional ``SEVN_PROXY_SHARED_SECRET``.

    Returns:
        EgressIntegrationProxyClient | None: Live client, or ``None`` when proxy URL unset.

    Examples:
        >>> build_integration_proxy_client(proxy_url=None) is None
        True
        >>> c = build_integration_proxy_client(proxy_url="http://127.0.0.1:8787")
        >>> isinstance(c, EgressIntegrationProxyClient)
        True
    """
    url = (proxy_url or "").strip()
    if not url:
        return None
    secret = (proxy_shared_secret or "").strip() or None
    if secret is None:
        secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip() or None
    token = (session_token or "").strip() or None
    return EgressIntegrationProxyClient(
        proxy_url=url,
        session_token=token,
        proxy_shared_secret=secret,
    )


__all__ = [
    "EgressIntegrationProxyClient",
    "IntegrationCredentialRequired",
    "build_integration_proxy_client",
]
