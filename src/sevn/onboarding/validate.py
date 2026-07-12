"""Schema gate for onboarding drafts (`specs/22-onboarding.md` §2.2).

Module: sevn.onboarding.validate
Depends: sevn.config.defaults, sevn.config.errors, sevn.config.workspace_config

Exports:
    validate_workspace_document — Pydantic parse + supported ``schema_version`` check.
    emit_unused_provider_warnings — print declared-but-unused provider warnings (D7).

Examples:
    >>> validate_workspace_document(_MINIMAL_VALIDATE_DOC)
    >>> from sevn.config.errors import UnsupportedSchemaVersionError
    >>> try:
    ...     validate_workspace_document({"schema_version": 999})
    ... except UnsupportedSchemaVersionError:
    ...     pass
"""

from __future__ import annotations

from typing import Any

from sevn.config.defaults import SUPPORTED_SCHEMA_VERSIONS
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.config.model_resolution import is_minimax_catalog_model
from sevn.config.provider_credential_validate import (
    collect_unused_declared_providers,
    format_unused_provider_warning,
    validate_provider_credentials,
)
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config

_MINIMAL_VALIDATE_DOC: dict[str, Any] = {
    "schema_version": 1,
    "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},  # nosec B105
}


def _check_gateway_token(doc: dict[str, Any]) -> None:
    """Require a non-empty ``gateway.token`` before Pydantic parse.

    Args:
        doc (dict[str, Any]): Workspace document under validation.

    Raises:
        ValueError: When ``gateway.token`` is missing or blank.

    Examples:
        >>> _check_gateway_token(_MINIMAL_VALIDATE_DOC) is None
        True
        >>> import pytest
        >>> with pytest.raises(ValueError, match="gateway.token"):
        ...     _check_gateway_token({"schema_version": 1})
    """
    gateway = doc.get("gateway")
    if not isinstance(gateway, dict):
        msg = (
            "gateway.token is required — run `sevn gateway set-gateway-token` "
            "or set gateway.token in sevn.json"
        )
        raise ValueError(msg)
    raw = gateway.get("token")
    if not isinstance(raw, str) or not raw.strip():
        msg = (
            "gateway.token is required — run `sevn gateway set-gateway-token` "
            "or set gateway.token in sevn.json"
        )
        raise ValueError(msg)


def _check_minimax_transport_override(doc: dict[str, Any]) -> None:
    """Reject ``providers.models[minimax/...].transport == "chat_completions"``.

    MiniMax catalog ids must route via the Anthropic-compatible upstream
    (`specs/05-llm-transports.md` §2.2, `specs/07-egress-proxy.md` §5). Allowing a
    `chat_completions` override on a `minimax/` id would forward the prefixed model
    id to the OpenAI upstream and return ``400``.

    Args:
        doc (dict[str, Any]): Workspace document under validation.

    Raises:
        ValueError: When a MiniMax catalog id has a `chat_completions` transport override.

    Examples:
        >>> _check_minimax_transport_override({"providers": {}})
    """
    providers = doc.get("providers")
    if not isinstance(providers, dict):
        return
    models = providers.get("models")
    if not isinstance(models, dict):
        return
    for raw_id, entry in models.items():
        mid = str(raw_id)
        if not is_minimax_catalog_model(mid) or not isinstance(entry, dict):
            continue
        transport = entry.get("transport")
        if isinstance(transport, str) and transport.strip().lower() == "chat_completions":
            msg = (
                f"providers.models[{mid!r}].transport must be 'anthropic' for "
                "minimax/ catalog ids — MiniMax requires the Anthropic-compatible "
                "API (`specs/05-llm-transports.md` §2.2)."
            )
            raise ValueError(msg)


def validate_workspace_document(
    doc: dict[str, Any],
    *,
    check_provider_credentials: bool = True,
) -> None:
    """Validate ``doc`` as a workspace JSON document.

    Args:
        doc (dict[str, Any]): Candidate ``sevn.json`` or draft body.
        check_provider_credentials (bool): When True (default), flag assigned slots
            whose provider has no resolvable credential (D7). Packaged profile fragments
            pass ``False`` because they ship without operator secrets.

    Raises:
        UnsupportedSchemaVersionError: When ``schema_version`` is missing or unknown.
        ValueError: When a ``minimax/`` catalog id forces ``chat_completions`` transport or
            when an assigned model slot's provider has no resolvable credential (D7).
        pydantic.ValidationError: When the document fails ``WorkspaceConfig`` validation.

    Examples:
        >>> validate_workspace_document(_MINIMAL_VALIDATE_DOC)
        >>> from sevn.config.errors import UnsupportedSchemaVersionError
        >>> try:
        ...     validate_workspace_document({"schema_version": 999})
        ... except UnsupportedSchemaVersionError:
        ...     pass
    """
    raw = doc.get("schema_version")
    if raw is None:
        msg = "/schema_version: required (pointer /schema_version)"
        raise UnsupportedSchemaVersionError(msg)
    if raw not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))
        msg = (
            f"/schema_version: value {raw!r} is not supported by this binary "
            f"(supported: {supported}); run `sevn migrate` when available "
            f"(`specs/22-onboarding.md` §2.3)"
        )
        raise UnsupportedSchemaVersionError(msg)
    _check_gateway_token(doc)
    cfg = parse_workspace_config(doc)
    _check_minimax_transport_override(doc)
    if check_provider_credentials:
        validate_provider_credentials(cfg)


def emit_unused_provider_warnings(cfg: WorkspaceConfig, *, echo: Any | None = None) -> None:
    """Print warnings for declared ``providers.<name>`` entries with no assigned slot (D7).

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        echo (Any | None): Callable accepting one message string; defaults to ``print``.

    Returns:
        None

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> emit_unused_provider_warnings(
        ...     WorkspaceConfig.minimal(providers={"openai": {"api_key": "x"}}),
        ...     echo=lambda _msg: None,
        ... ) is None
        True
    """
    writer = echo if echo is not None else print
    for name in collect_unused_declared_providers(cfg):
        writer(format_unused_provider_warning(name))
