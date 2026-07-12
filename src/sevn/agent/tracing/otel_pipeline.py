"""Backward-compatible re-export of ``sevn.tracing.otel_pipeline``.

Module: sevn.agent.tracing.otel_pipeline
Depends: sevn.tracing.otel_pipeline
Exports: same as ``sevn.tracing.otel_pipeline`` (gateway/agent import path preserved).
"""

from sevn.tracing.otel_pipeline import (
    OtlpExportTarget,
    OTLPSpanExporter,
    configure_gateway_otel,
    configure_gateway_otel_async,
    configure_proxy_otel,
    instrumentation_capability,
    is_otel_export_configured,
    reset_otel_pipeline_for_tests,
    resolve_otlp_targets,
)

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
