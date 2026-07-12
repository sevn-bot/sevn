"""Tools registry package (`specs/11-tools-registry.md`).

Exports:
    ToolResultCode — canonical JSON envelope labels.
    ToolDefinition, ToolCall, ToolExecutor, Tool, FunctionTool — registry core types.
    ToolContext — async runtime envelope for tool bodies.
    enveloped_failure / enveloped_success / maybe_spill_large_payload — JSON helpers.
    ToolSet, build_session_registry — session snapshots & factory helpers.
    sevn_tool, tool_from_decorated — decorator ergonomics.
    LoadedBodyCache — lazy-load LRU keyed by registry generation.
    attach_meta_loaders — register ``load_tool`` / ``load_skill``.
    PermissionPolicy stubs — permissive/deny placeholders.
    ensure_path_not_under_llmignore — filesystem guardrail.
    is_integration_mutator — integration abortability heuristic.
    validate_json_schema_subset — coarse argument validator.
    RuntimeToolBindings, IntegrationProxyClient, SandboxExecutorClient,
        McpStdioClient, McpStdioTool — Wave T runtime dispatch hooks
        (`specs/11-tools-registry.md` §10.1).

Examples:
    >>> from sevn.tools import ToolExecutor
    >>> ToolExecutor().__class__.__name__
    'ToolExecutor'
"""

from __future__ import annotations

from sevn.tools.base import (
    BoundToolCallable,
    FunctionTool,
    SandboxMode,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    enveloped_failure,
    enveloped_success,
    maybe_spill_large_payload,
)
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.tools.integration_classifier import is_integration_mutator
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.paths import ensure_path_not_under_llmignore
from sevn.tools.permissions import (
    AllowAllPermissionPolicy,
    DenyingPermissionPolicy,
    PermissionPolicy,
)
from sevn.tools.registry import (
    McpUnavailableTool,
    ToolSet,
    build_session_registry,
    load_plugin_tools,
    merge_skill_manifests,
    plugin_entrypoint_allowed,
    register_feature_stubs,
    snapshot_tool_set,
)
from sevn.tools.runtime_dispatch import (
    IntegrationProxyClient,
    McpStdioClient,
    McpStdioTool,
    RuntimeToolBindings,
    SandboxExecutorClient,
)
from sevn.tools.validation import ValidationIssue, validate_json_schema_subset

__all__ = [
    "AllowAllPermissionPolicy",
    "BoundToolCallable",
    "DenyingPermissionPolicy",
    "FunctionTool",
    "IntegrationProxyClient",
    "LoadedBodyCache",
    "McpStdioClient",
    "McpStdioTool",
    "McpUnavailableTool",
    "PermissionPolicy",
    "RuntimeToolBindings",
    "SandboxExecutorClient",
    "SandboxMode",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolDefinition",
    "ToolExecutor",
    "ToolResultCode",
    "ToolSet",
    "ValidationIssue",
    "attach_meta_loaders",
    "build_session_registry",
    "ensure_path_not_under_llmignore",
    "enveloped_failure",
    "enveloped_success",
    "is_integration_mutator",
    "load_plugin_tools",
    "maybe_spill_large_payload",
    "merge_skill_manifests",
    "plugin_entrypoint_allowed",
    "register_feature_stubs",
    "sevn_tool",
    "snapshot_tool_set",
    "tool_from_decorated",
    "validate_json_schema_subset",
]
