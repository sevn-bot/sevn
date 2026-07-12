"""Egress base URL for voice HTTP clients (`specs/20-voice.md` §4.2, §10.3).

Module: sevn.voice.egress
Depends: typing

Exports:
    voice_http_base_url — pick proxy origin for ``httpx.AsyncClient`` parity with LLM calls.
"""


def voice_http_base_url(
    *,
    process_proxy_url: str | None,
    workspace_proxy_url: str | None,
) -> str | None:
    """Return the canonical HTTP(S) origin for cloud voice providers.

    Precedence matches merged runtime config in ``specs/02-config-and-workspace.md``
    §2.7: allowlisted process env overrides workspace file values. Callers pass the
    effective pair resolved by the gateway (``ProcessSettings.proxy_url`` vs
    workspace proxy base), mirroring ``specs/05-llm-transports.md`` and
    ``specs/07-egress-proxy.md`` single-egress posture.

    Args:
        process_proxy_url (str | None): Typically ``SEVN_PROXY_URL`` when set.
        workspace_proxy_url (str | None): Workspace proxy base when modeled.

    Returns:
        str | None: Origin with no trailing slash, or ``None`` when neither side sets a URL.

    Examples:
        >>> voice_http_base_url(process_proxy_url="http://p/", workspace_proxy_url=None)
        'http://p'
        >>> voice_http_base_url(process_proxy_url=None, workspace_proxy_url="http://w")
        'http://w'
        >>> voice_http_base_url(process_proxy_url="http://a", workspace_proxy_url="http://b")
        'http://a'
    """

    if process_proxy_url and str(process_proxy_url).strip():
        return str(process_proxy_url).rstrip("/")
    if workspace_proxy_url and str(workspace_proxy_url).strip():
        return str(workspace_proxy_url).rstrip("/")
    return None
