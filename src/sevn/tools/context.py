"""Framework-agnostic runtime passed into every `@sevn_tool` body (`specs/11-tools-registry.md` §2.3).

Hosts session identifiers, filesystem roots, tracing, and coarse permission gates. Optional
handles stay ``None`` until gateway/sandbox/channel wiring lands.

Module: sevn.tools.context
Depends: sevn.tools.permissions

Exports:
    ToolContext — per-invocation/async-task context envelope.

Examples:
    >>> from pathlib import Path
    >>> from sevn.tools.permissions import AllowAllPermissionPolicy
    >>> ctx = ToolContext(
    ...     session_id="s",
    ...     workspace_path=Path("/tmp/w"),
    ...     workspace_id="wid",
    ...     registry_version=1,
    ...     trace=None,
    ...     permissions=AllowAllPermissionPolicy(),
    ... )
    >>> ctx.registry_version
    1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.agent.tracing.sink import TraceSink
    from sevn.code_understanding.models import GraphifyProfile
    from sevn.plugins.runner import PluginHookChain
    from sevn.tools.permissions import PermissionPolicy


@dataclass
class ToolContext:
    """Values shared across dispatcher, adapters, and tool bodies."""

    session_id: str
    workspace_path: Path
    workspace_id: str
    registry_version: int
    checkout_path: Path | None = None
    """Resolved sevn.bot checkout root seeding the ``source_code/`` mirror, when known.

    Lets file tools rebase an absolute checkout path (e.g. the model echoing
    ``/Users/.../sevn.bot/src/x.py`` from the transcript) onto the workspace-relative
    ``source_code/`` mirror before containment, instead of rejecting it as
    ``escapes workspace root`` (`specs/11-tools-registry.md` §4.3). ``None`` disables the
    rewrite (no checkout resolved), preserving prior behaviour.
    """
    trace: TraceSink | None = None
    permissions: PermissionPolicy | None = None
    sandbox_client: Any | None = None
    channel_adapter: Any | None = None
    channel_router: Any | None = None
    """Gateway :class:`~sevn.gateway.channel_router.ChannelRouter` for proactive outbound tools."""
    outbound_user_id: str = ""
    """Destination user id for ``message`` / ``send_file`` / ``tts`` when omitted in tool args."""
    outbound_metadata: dict[str, Any] = field(default_factory=dict)
    """Routing hints (``chat_id``, ``topic_id``, …) forwarded on outbound envelopes."""
    tts_pipeline: Any | None = None
    """Gateway :class:`~sevn.voice.tts.TextToSpeechPipeline` for ``tts`` tool synthesis."""
    voice_tts_voice_id: str | None = None
    """Default provider voice id from workspace ``voice.tts_voice_id``."""
    turn_id: str = "unset"
    turn_span_id: str | None = None
    """Active turn root span id (``gateway.turn.start``) for parent linkage."""
    executor_tier: str | None = None
    human_acknowledged_tools: frozenset[str] = field(default_factory=frozenset)
    """Tool names cleared for ``requires_human`` this turn (executor fills)."""
    openui_bridge: Any | None = None
    """Gateway-injected :class:`sevn.ui.openui.bridge.OpenUIBridge` when available."""
    gateway_public_base_url: str = ""
    """Public gateway base URL for ``live_url`` construction (no trailing slash)."""
    tunnel_healthy: bool = True
    """When ``False``, Telegram live OpenUI falls back to raster (`specs/29-openui.md` §4.5)."""
    delivery_channel: str = "webchat"
    """Active channel key for the current dispatch (``webchat``, ``telegram``, …)."""
    graphify_profiles: list[GraphifyProfile] | None = None
    """Active Graphify profiles for §2.5 search-tool prefix injection."""
    plugin_hooks: PluginHookChain | None = None
    """Ordered plugin interceptors (:class:`sevn.plugins.runner.PluginHookChain`)."""
    loaded_tools: dict[str, str] = field(default_factory=dict)
    """Per-turn memo of successful ``load_tool`` envelopes keyed by tool ``name`` argument.

    Populated by :class:`sevn.tools.registry.TracingToolExecutor` on the first
    successful ``load_tool(name)``; repeat calls within the same turn return the
    cached envelope and emit ``tool_call.cached``.
    """
    negative_cache: dict[tuple[str, str], str] = field(default_factory=dict)
    """Per-turn cache of failed tool envelopes keyed by ``(tool_name, args_signature)``.

    Populated by :class:`sevn.tools.registry.TracingToolExecutor` on the first
    ``ok=false`` return; subsequent dispatches with the same arguments short-
    circuit with the cached envelope so the model can't burn calls retrying a
    known-bad path or name (``PROBLEMS.md`` §Priority 1.f).
    """
    known_tool_names: frozenset[str] = field(default_factory=frozenset)
    """Snapshot of registered tool names for this session.

    Populated at session-registry build time so the dispatcher can produce
    ``did_you_mean`` suggestions for ``load_tool``-style errors without a
    back-reference to the executor (``PROBLEMS.md`` §Priority 1.h). Empty
    frozenset disables the matcher gracefully.
    """
    tool_debug_result_max_chars: int | None = None
    """Max chars for ``tool_call.finish`` / ``tool_call.cached`` result in DEBUG logs.

    ``None`` logs the full JSON envelope (``logging.tool_debug_result_max_chars``).
    """
    artifact_output_prefix: str = ""
    """Workspace-relative artifact output prefix (e.g. ``out/<session_id>``)."""
    seen_reads: dict[tuple[str, int | None, int | None], str] = field(default_factory=dict)
    """Per-turn memo of successful ``read`` envelopes keyed by ``(path, offset, limit)``.

    Populated by :class:`sevn.tools.registry.TracingToolExecutor` on the first
    successful ``read`` of a given path+range; identical repeat reads within the
    same turn short-circuit to a compact "already read above" notice instead of
    re-emitting the full body, so the model can't burn tokens re-fetching the same
    file (`specs/11-tools-registry.md` §10.13).
    """
    seen_messages: dict[tuple[str, str, str], int] = field(default_factory=dict)
    """Per-turn memo of delivered outbound ``message`` sends keyed by ``(channel, user_id, text)``.

    Populated by :class:`sevn.tools.registry.TracingToolExecutor` on the first
    successful ``message`` send of a given destination+body; identical repeat sends
    within the same turn short-circuit to a notice instead of re-delivering, so a
    looping model cannot spam the user with the same line or burn rounds re-sending
    the same content until the executor timeout (`specs/11-tools-registry.md` §10.13).
    """


__all__ = ["ToolContext"]
