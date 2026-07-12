"""AWS Bedrock Converse forwarding for the egress proxy (`specs/07-egress-proxy.md`).

Exports:
    converse_via_bedrock — call Bedrock Runtime ``converse`` with SigV4 credentials.
"""

from __future__ import annotations

from typing import Any, cast

from sevn.proxy.settings import ProxySettings


def converse_via_bedrock(settings: ProxySettings, body: dict[str, Any]) -> dict[str, Any]:
    """Invoke Bedrock Runtime ``converse`` and return the parsed response dict.

    Args:
        settings (ProxySettings): Proxy env including AWS region and keys.
        body (dict[str, Any]): Converse API request object from the client.

    Returns:
        dict[str, Any]: Bedrock response payload.

    Raises:
        RuntimeError: When boto3 is missing or AWS credentials are unset.

    Examples:
        >>> converse_via_bedrock.__name__
        'converse_via_bedrock'
    """
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        msg = "AWS credentials required for Bedrock (set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)"
        raise RuntimeError(msg)
    try:
        import boto3
    except ImportError as exc:
        msg = "install optional dependency: uv sync --extra bedrock"
        raise RuntimeError(msg) from exc

    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    model_id = str(body.get("modelId") or body.get("model_id") or "")
    if not model_id:
        msg = "Bedrock converse body requires modelId"
        raise ValueError(msg)
    kwargs = {k: v for k, v in body.items() if k not in ("modelId", "model_id")}
    response = client.converse(modelId=model_id, **kwargs)
    return cast("dict[str, Any]", response)


__all__ = ["converse_via_bedrock"]
