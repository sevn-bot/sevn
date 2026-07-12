"""Logfire trace export helpers for operator toggles (`specs/04-tracing.md`).

Module: sevn.agent.tracing.logfire_config
Depends: typing, sevn.config.workspace_config

Exports:
    LogfireExportStatus — resolved export posture for CLI / menu / Mission Control.
    logfire_export_status_from_doc — status from raw ``sevn.json``.
    logfire_export_status — status from :class:`WorkspaceConfig`.
    apply_logfire_export_to_sevn_doc — add/remove the Logfire sink entry.
    logfire_sink_entry_for_tests — validated sink descriptor for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sevn.config.workspace_config import TraceSinkEntry, WorkspaceConfig

LOGFIRE_SECRET_LOGICAL_KEY = "logfire.token"  # nosec B105 — logical secret id, not a credential
DEFAULT_LOGFIRE_TOKEN_REF = f"${{SECRET:encrypted_file:{LOGFIRE_SECRET_LOGICAL_KEY}}}"
DEFAULT_LOGFIRE_PROJECT = "sevn-gateway"


@dataclass(frozen=True)
class LogfireExportStatus:
    """Resolved Logfire export configuration for operator surfaces."""

    enabled: bool
    token_ref: str | None
    project: str | None
    local_sinks: tuple[str, ...]


def _sink_types_from_doc(doc: dict[str, Any]) -> list[str]:
    """Collect normalized sink ``type`` values from a raw document.

    Args:
        doc (dict[str, Any]): Parsed ``sevn.json`` root object.

    Returns:
        list[str]: Lowercase sink type names in list order.

    Examples:
        >>> _sink_types_from_doc({"tracing": {"sinks": [{"type": "sqlite"}]}})
        ['sqlite']
    """
    tracing = doc.get("tracing")
    if not isinstance(tracing, dict):
        return []
    sinks = tracing.get("sinks")
    if not isinstance(sinks, list):
        return []
    types: list[str] = []
    for item in sinks:
        if not isinstance(item, dict):
            continue
        raw_type = item.get("type")
        if isinstance(raw_type, str) and raw_type.strip():
            types.append(raw_type.strip().lower())
    return types


def logfire_export_status_from_doc(doc: dict[str, Any]) -> LogfireExportStatus:
    """Return Logfire export posture from a raw ``sevn.json`` document.

    Args:
        doc (dict[str, Any]): Parsed ``sevn.json`` root object.

    Returns:
        LogfireExportStatus: Whether a ``logfire`` sink is configured and local sinks.

    Examples:
        >>> logfire_export_status_from_doc({}).enabled
        False
    """
    tracing = doc.get("tracing")
    token_ref: str | None = None
    project: str | None = None
    enabled = False
    local: list[str] = []
    if isinstance(tracing, dict):
        sinks = tracing.get("sinks")
        if isinstance(sinks, list):
            for item in sinks:
                if not isinstance(item, dict):
                    continue
                raw_type = item.get("type")
                kind = raw_type.strip().lower() if isinstance(raw_type, str) else ""
                if kind == "logfire":
                    enabled = True
                    ref = item.get("token_ref")
                    token_ref = ref.strip() if isinstance(ref, str) and ref.strip() else token_ref
                    proj = item.get("project")
                    project = proj.strip() if isinstance(proj, str) and proj.strip() else project
                elif kind in ("sqlite", "jsonl_file", "otel"):
                    local.append(kind)
    return LogfireExportStatus(
        enabled=enabled,
        token_ref=token_ref,
        project=project,
        local_sinks=tuple(local),
    )


def logfire_export_status(workspace: WorkspaceConfig) -> LogfireExportStatus:
    """Return Logfire export posture from a parsed workspace model.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.

    Returns:
        LogfireExportStatus: Resolved export configuration.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> logfire_export_status(WorkspaceConfig.minimal()).enabled
        False
    """
    tracing = workspace.tracing
    token_ref: str | None = None
    project: str | None = None
    enabled = False
    local: list[str] = []
    if tracing is not None and tracing.sinks:
        for entry in tracing.sinks:
            kind = entry.sink_type.strip().lower()
            if kind == "logfire":
                enabled = True
                token_ref = (entry.token_ref or "").strip() or token_ref
                project = (entry.project or "").strip() or project
            elif kind in ("sqlite", "jsonl_file", "otel"):
                local.append(kind)
    return LogfireExportStatus(
        enabled=enabled,
        token_ref=token_ref,
        project=project,
        local_sinks=tuple(local),
    )


def _ensure_tracing(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the ``tracing`` subtree, creating ``tracing.sinks`` when absent.

    Args:
        doc (dict[str, Any]): ``sevn.json`` root (mutated in place).

    Returns:
        dict[str, Any]: The ``tracing`` mapping.

    Examples:
        >>> doc: dict[str, object] = {}
        >>> tracing = _ensure_tracing(doc)
        >>> isinstance(tracing.get("sinks"), list)
        True
    """
    tracing = doc.get("tracing")
    if not isinstance(tracing, dict):
        tracing = {}
        doc["tracing"] = tracing
    sinks = tracing.get("sinks")
    if not isinstance(sinks, list):
        sinks = []
        tracing["sinks"] = sinks
    return tracing


def _logfire_sink_entry(
    *,
    token_ref: str | None = None,
    project: str | None = None,
) -> dict[str, str]:
    """Build one raw ``logfire`` sink dict for ``tracing.sinks[]``.

    Args:
        token_ref (str | None): Bearer ``token_ref`` override.
        project (str | None): ``project`` / service name override.

    Returns:
        dict[str, str]: Sink descriptor ready for JSON serialization.

    Examples:
        >>> _logfire_sink_entry()["type"]
        'logfire'
    """
    entry: dict[str, str] = {"type": "logfire"}
    ref = (token_ref or DEFAULT_LOGFIRE_TOKEN_REF).strip()
    if ref:
        entry["token_ref"] = ref
    proj = (project or DEFAULT_LOGFIRE_PROJECT).strip()
    if proj:
        entry["project"] = proj
    return entry


def apply_logfire_export_to_sevn_doc(
    doc: dict[str, Any],
    *,
    enabled: bool,
    token_ref: str | None = None,
    project: str | None = None,
    keep_local_sinks: bool = True,
) -> None:
    """Add or remove the Logfire sink in ``tracing.sinks[]``.

    When enabling, prepends a ``logfire`` sink and optionally strips local
    ``sqlite`` / ``jsonl_file`` sinks so future spans export only to Logfire.

    Args:
        doc (dict[str, Any]): ``sevn.json`` root (mutated in place).
        enabled (bool): When ``True``, ensure a Logfire sink exists.
        token_ref (str | None): Optional ``token_ref`` override for the sink.
        project (str | None): Optional ``service.name`` override (``project`` key).
        keep_local_sinks (bool): When ``False`` while enabling, drop sqlite/jsonl sinks.

    Examples:
        >>> doc: dict[str, object] = {"tracing": {"sinks": [{"type": "sqlite"}]}}
        >>> apply_logfire_export_to_sevn_doc(doc, enabled=True)
        >>> types = [s["type"] for s in doc["tracing"]["sinks"] if isinstance(s, dict)]
        >>> types[0]
        'logfire'
    """
    tracing = _ensure_tracing(doc)
    sinks_raw = tracing.get("sinks")
    if not isinstance(sinks_raw, list):
        sinks_raw = []
    retained: list[Any] = []
    for item in sinks_raw:
        if not isinstance(item, dict):
            retained.append(item)
            continue
        raw_type = item.get("type")
        kind = raw_type.strip().lower() if isinstance(raw_type, str) else ""
        if kind == "logfire":
            continue
        if not keep_local_sinks and enabled and kind in ("sqlite", "jsonl_file"):
            continue
        retained.append(dict(item))
    if enabled:
        retained.insert(0, _logfire_sink_entry(token_ref=token_ref, project=project))
    tracing["sinks"] = retained


def logfire_sink_entry_for_tests(
    *,
    token_ref: str | None = None,
    project: str | None = None,
) -> TraceSinkEntry:
    """Build a validated :class:`TraceSinkEntry` for tests and CLI previews.

    Args:
        token_ref (str | None): Optional bearer ``token_ref``.
        project (str | None): Optional ``project`` / service name.

    Returns:
        TraceSinkEntry: Validated sink descriptor.

    Examples:
        >>> logfire_sink_entry_for_tests().sink_type
        'logfire'
    """
    return TraceSinkEntry.model_validate(_logfire_sink_entry(token_ref=token_ref, project=project))


__all__ = [
    "DEFAULT_LOGFIRE_PROJECT",
    "DEFAULT_LOGFIRE_TOKEN_REF",
    "LOGFIRE_SECRET_LOGICAL_KEY",
    "LogfireExportStatus",
    "apply_logfire_export_to_sevn_doc",
    "logfire_export_status",
    "logfire_export_status_from_doc",
    "logfire_sink_entry_for_tests",
]
