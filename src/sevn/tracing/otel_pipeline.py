"""Shared OpenTelemetry ``TracerProvider`` for gateway + proxy + pydantic-ai.

Module: sevn.tracing.otel_pipeline
Depends: logfire, opentelemetry-sdk, sevn.config.workspace_config
Exports:
    OtlpExportTarget — resolved OTLP endpoint + auth headers.
    configure_gateway_otel — install one global ``TracerProvider`` at gateway boot.
    configure_gateway_otel_async — async secret resolution then configure.
    configure_proxy_otel — proxy process OTLP + ``instrument_httpx`` (W1.5).
    instrumentation_capability — pydantic-ai ``Instrumentation`` on the shared provider.
    is_otel_export_configured — whether OTLP processors are attached.
    reset_otel_pipeline_for_tests — test isolation hook.
    resolve_otlp_targets — parse otel/logfire sink entries into export targets.
Examples:
    >>> from sevn.tracing.otel_pipeline import is_otel_export_configured
    >>> isinstance(is_otel_export_configured(), bool)
    True
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from sevn.security.secrets.value_expand import expand_env_refs

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.capabilities.instrumentation import Instrumentation

    from sevn.config.workspace_config import TraceSinkEntry, WorkspaceConfig


class _OtlpExporterFactory(Protocol):
    """Callable factory matching :class:`OTLPSpanExporter` construction."""

    def __call__(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
    ) -> SpanExporter:
        """Build one OTLP HTTP exporter instance.

        Args:
            endpoint (str): OTLP traces URL.
            headers (dict[str, str]): Optional auth headers.

        Returns:
            SpanExporter: Configured exporter.

        Examples:
            >>> isinstance(OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces", headers={}), object)
            True
        """
        ...


_export_configured = False


@dataclass(frozen=True)
class OtlpExportTarget:
    """One OTLP HTTP export destination for the shared ``TracerProvider``."""

    endpoint: str
    headers: dict[str, str]
    service_name: str


def is_otel_export_configured() -> bool:
    """Return whether OTLP span processors were attached at last configure call.

    Returns:
        bool: ``True`` when at least one OTLP exporter is active.

    Examples:
        >>> isinstance(is_otel_export_configured(), bool)
        True
    """
    return _export_configured


def _resolve_logfire_service_name(
    workspace: WorkspaceConfig,
    *,
    default_service_name: str,
) -> str:
    """Return ``service.name`` for Logfire from the first ``logfire`` sink ``project``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        default_service_name (str): Fallback when ``project`` is omitted.

    Returns:
        str: Service name passed to :func:`logfire.configure`.

    Examples:
        >>> from sevn.config.workspace_config import TraceSinkEntry, TracingConfig, WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     tracing=TracingConfig(
        ...         sinks=[TraceSinkEntry.model_validate({"type": "logfire", "project": "home"})],
        ...     ),
        ... )
        >>> _resolve_logfire_service_name(ws, default_service_name="sevn-gateway")
        'home'
    """
    tracing = workspace.tracing
    if tracing is None or not tracing.sinks:
        return default_service_name
    for entry in tracing.sinks:
        if entry.sink_type.strip().lower() != "logfire":
            continue
        project = (entry.project or "").strip()
        if project:
            return project
    return default_service_name


def _resolve_logfire_token(
    workspace: WorkspaceConfig,
    *,
    resolved_tokens: dict[int, str] | None,
) -> str:
    """Resolve a Logfire bearer token from env and ``tracing.sinks[]`` ``token_ref``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        resolved_tokens (dict[int, str] | None): Async-resolved bearer tokens by sink index.

    Returns:
        str: Non-empty token text or ``""`` when unset.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _resolve_logfire_token(WorkspaceConfig.minimal(), resolved_tokens=None)
        ''
    """
    token = os.environ.get("LOGFIRE_TOKEN", "").strip()
    if token:
        return token
    tracing = workspace.tracing
    if tracing is None or not tracing.sinks:
        return ""
    token_by_index = resolved_tokens or {}
    for idx, entry in enumerate(tracing.sinks):
        if entry.sink_type.strip().lower() not in ("logfire", "otel"):
            continue
        resolved = _resolve_token(entry, resolved_token=token_by_index.get(idx)) or ""
        if resolved.strip():
            return resolved.strip()
    return ""


def _resolve_token(
    entry: TraceSinkEntry,
    *,
    resolved_token: str | None,
) -> str | None:
    """Resolve bearer token for one otel/logfire sink entry.

    Args:
        entry (TraceSinkEntry): Sink descriptor from ``tracing.sinks[]``.
        resolved_token (str | None): Async-resolved secret when present.

    Returns:
        str | None: Bearer token or ``None``.

    Examples:
        >>> from sevn.config.workspace_config import TraceSinkEntry
        >>> entry = TraceSinkEntry.model_validate({"type": "otel", "token_ref": "plain"})
        >>> _resolve_token(entry, resolved_token="tok")
        'tok'
    """
    if resolved_token is not None:
        stripped = resolved_token.strip()
        return stripped or None
    token_ref = (entry.token_ref or "").strip()
    if not token_ref:
        return None
    expanded = expand_env_refs(token_ref, strict=False).strip()
    if expanded and "${ENV:" not in expanded and "${SECRET:" not in expanded:
        return expanded
    return None


def resolve_otlp_targets(
    workspace: WorkspaceConfig,
    *,
    resolved_tokens: dict[int, str] | None = None,
    default_service_name: str = "sevn-gateway",
) -> list[OtlpExportTarget]:
    """Collect OTLP export targets from ``tracing.sinks[]`` otel/logfire entries.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.
        resolved_tokens (dict[int, str] | None): Pre-resolved bearer tokens by sink index.
        default_service_name (str): Fallback ``service.name`` when ``project`` is omitted.

    Returns:
        list[OtlpExportTarget]: Zero or more export destinations.

    Examples:
        >>> from sevn.config.workspace_config import TraceSinkEntry, TracingConfig, WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate(
        ...         {"type": "otel", "endpoint": "http://127.0.0.1:4318/v1/traces"},
        ...     )]),
        ... )
        >>> len(resolve_otlp_targets(ws))
        1
    """
    tracing = workspace.tracing
    entries = tracing.sinks if tracing and tracing.sinks else None
    if not entries:
        return []
    token_by_index = resolved_tokens or {}
    targets: list[OtlpExportTarget] = []
    for idx, entry in enumerate(entries):
        kind = entry.sink_type.strip().lower()
        if kind not in ("logfire", "otel"):
            continue
        endpoint = (entry.endpoint or "").strip() or os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "",
        ).strip()
        if not endpoint:
            continue
        headers = dict(entry.headers or {})
        token = _resolve_token(entry, resolved_token=token_by_index.get(idx))
        if token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        service_name = (entry.project or "").strip() or default_service_name
        targets.append(
            OtlpExportTarget(endpoint=endpoint, headers=headers, service_name=service_name),
        )
    return targets


def _build_processors(
    targets: list[OtlpExportTarget],
    *,
    exporter_factory: _OtlpExporterFactory = OTLPSpanExporter,
) -> list[BatchSpanProcessor]:
    """Build batch processors for each OTLP target.

    Args:
        targets (list[OtlpExportTarget]): Resolved export destinations.
        exporter_factory (type[SpanExporter]): Exporter class (test seam).

    Returns:
        list[BatchSpanProcessor]: Processors to attach to the shared provider.

    Examples:
        >>> len(_build_processors([]))
        0
    """
    processors: list[BatchSpanProcessor] = []
    for target in targets:
        exporter = exporter_factory(
            endpoint=target.endpoint,
            headers=dict(target.headers),
        )
        processors.append(BatchSpanProcessor(exporter))
    return processors


def configure_gateway_otel(
    workspace: WorkspaceConfig,
    *,
    resolved_tokens: dict[int, str] | None = None,
    exporter_factory: _OtlpExporterFactory = OTLPSpanExporter,
) -> TracerProvider:
    """Install one global ``TracerProvider`` for gateway + pydantic-ai spans.

    Uses ``logfire.configure(send_to_logfire='if-token-present')`` when a Logfire
    token is available; always attaches explicit OTLP targets from ``tracing.sinks[]``.
    With no token and no endpoint the provider is installed without exporters (CI no-op).

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        resolved_tokens (dict[int, str] | None): Async-resolved OTLP bearer tokens.
        exporter_factory (type[SpanExporter]): Exporter class (test seam).

    Returns:
        TracerProvider: The configured global provider.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> isinstance(configure_gateway_otel(WorkspaceConfig.minimal()), TracerProvider)
        True
    """
    global _export_configured
    targets = resolve_otlp_targets(workspace, resolved_tokens=resolved_tokens)
    processors = _build_processors(targets, exporter_factory=exporter_factory)

    logfire_token = _resolve_logfire_token(workspace, resolved_tokens=resolved_tokens)
    service_name = _resolve_logfire_service_name(
        workspace,
        default_service_name="sevn-gateway",
    )

    _export_configured = bool(processors) or bool(logfire_token)

    if logfire_token or targets:
        import logfire

        logfire.configure(
            service_name=service_name,
            token=logfire_token or None,
            send_to_logfire=True if logfire_token else "if-token-present",
            additional_span_processors=processors or None,
        )
        logfire.instrument_pydantic_ai()
        logfire.instrument_httpx(capture_all=True)
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            return provider
        resource = Resource.create({"service.name": service_name})
        fallback = TracerProvider(resource=resource)
        for processor in processors:
            fallback.add_span_processor(processor)
        trace.set_tracer_provider(fallback)
        return fallback

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    _export_configured = False
    return provider


def configure_proxy_otel(
    workspace: WorkspaceConfig | None = None,
    *,
    resolved_tokens: dict[int, str] | None = None,
    exporter_factory: _OtlpExporterFactory = OTLPSpanExporter,
) -> None:
    """Configure proxy OTLP export and ``instrument_httpx`` (same backend, own service).

    Args:
        workspace (WorkspaceConfig | None): Operator workspace when booted from ``SEVN_HOME``.
        resolved_tokens (dict[int, str] | None): Optional pre-resolved OTLP tokens.
        exporter_factory (type[SpanExporter]): Exporter class (test seam).

    Examples:
        >>> configure_proxy_otel(None) is None
        True
    """
    targets: list[OtlpExportTarget] = []
    if workspace is not None:
        targets = resolve_otlp_targets(
            workspace,
            resolved_tokens=resolved_tokens,
            default_service_name="sevn-proxy",
        )
    elif endpoint := os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        targets = [OtlpExportTarget(endpoint=endpoint, headers={}, service_name="sevn-proxy")]

    processors = _build_processors(targets, exporter_factory=exporter_factory)
    logfire_token = ""
    service_name = "sevn-proxy"
    if workspace is not None:
        logfire_token = _resolve_logfire_token(workspace, resolved_tokens=resolved_tokens)
        service_name = _resolve_logfire_service_name(
            workspace,
            default_service_name="sevn-proxy",
        )
    else:
        logfire_token = os.environ.get("LOGFIRE_TOKEN", "").strip()

    if logfire_token or targets:
        import logfire

        logfire.configure(
            service_name=service_name,
            token=logfire_token or None,
            send_to_logfire=True if logfire_token else "if-token-present",
            additional_span_processors=processors or None,
        )
        logfire.instrument_httpx()
        return

    resource = Resource.create({"service.name": "sevn-proxy"})
    provider = TracerProvider(resource=resource)
    for processor in processors:
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)


async def configure_gateway_otel_async(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
) -> TracerProvider:
    """Async gateway boot wrapper resolving ``token_ref`` secrets before configure.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        content_root (Path): Workspace content root for secrets backends.

    Returns:
        TracerProvider: Configured global provider.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(configure_gateway_otel_async)
        True
    """
    from sevn.tracing.trace_secrets_resolve import resolve_trace_sink_token

    tracing = workspace.tracing
    entries = tracing.sinks if tracing and tracing.sinks else None
    resolved_tokens: dict[int, str] = {}
    if entries:
        for idx, entry in enumerate(entries):
            kind = entry.sink_type.strip().lower()
            if kind not in ("logfire", "otel"):
                continue
            token_ref = (entry.token_ref or "").strip()
            if not token_ref:
                continue
            token = await resolve_trace_sink_token(
                token_ref,
                content_root=content_root,
                workspace=workspace,
            )
            if token:
                resolved_tokens[idx] = token
    return configure_gateway_otel(workspace, resolved_tokens=resolved_tokens or None)


def instrumentation_capability() -> Instrumentation:
    """Return pydantic-ai ``Instrumentation`` wired to the shared ``TracerProvider``.

    Returns:
        Instrumentation: Capability for Triager + Tier B agents.

    Examples:
        >>> from sevn.tracing.otel_pipeline import instrumentation_capability
        >>> cap = instrumentation_capability()
        >>> cap.__class__.__name__
        'Instrumentation'
    """
    from pydantic_ai.capabilities.instrumentation import Instrumentation
    from pydantic_ai.models.instrumented import InstrumentationSettings

    provider = trace.get_tracer_provider()
    tracer_provider = provider if isinstance(provider, TracerProvider) else None
    return Instrumentation(
        settings=InstrumentationSettings(tracer_provider=tracer_provider),
    )


def reset_otel_pipeline_for_tests() -> None:
    """Reset export flag and global provider (test isolation only).

    Examples:
        >>> reset_otel_pipeline_for_tests() is None
        True
    """
    global _export_configured
    _export_configured = False
    trace.set_tracer_provider(TracerProvider())


__all__ = [
    "OTLPSpanExporter",
    "OtlpExportTarget",
    "configure_gateway_otel",
    "configure_gateway_otel_async",
    "configure_proxy_otel",
    "instrumentation_capability",
    "is_otel_export_configured",
    "reset_otel_pipeline_for_tests",
    "resolve_otlp_targets",
]
