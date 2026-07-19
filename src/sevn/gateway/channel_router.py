"""Unified inbound/outbound orchestration (`specs/17-gateway.md` §2.2-§2.4, §4.3-§4.4).
Module: sevn.gateway.channel_router
Depends: channel_types, LLMGuard + llmignore, SessionManager facade, dispatcher, rate limiting, tracing

Re-exported (defined in :mod:`sevn.gateway.channel_types` for stable imports):
``IncomingMessage``, ``OutgoingMessage``, ``ChannelAdapter``.

Exports:
    outbound_routing_metadata — inbound routing keys safe for outbound sends.
    ChannelRouter — register adapters, webhook entrypoints, pipelines.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from sevn.agent.provider_history_keys import PROVIDER_TURN_MESSAGES_KEY
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.channels.telegram import (
    TELEGRAM_RICH_DRAFT_KEY,
    TELEGRAM_STREAMING_ACTIVE_KEY,
    TELEGRAM_USE_RICH_KEY,
    TelegramAdapter,
    TelegramSendError,
    _is_poll_connectivity_error,
    _parse_dm_policy,
    chunk_text,
)
from sevn.channels.telegram_file_links import (
    build_file_link_keyboard,
    extract_file_link_paths,
    strip_file_link_markers,
)
from sevn.channels.telegram_rich import should_use_rich
from sevn.config.defaults import DEFAULT_GATEWAY_QUEUE_MODE, VOICE_INBOUND_TRANSCRIPT_PREFIX
from sevn.config.sections.channels import resolve_busy_input_mode
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.access.slash_access import (
    canonical_slash_command,
    policy_for_message,
    slash_allowed_for_actor,
)
from sevn.gateway.channel_types import (
    ChannelAdapter as ChannelAdapter,
)
from sevn.gateway.channel_types import (
    IncomingMessage as IncomingMessage,
)
from sevn.gateway.channel_types import (
    OutgoingMessage as OutgoingMessage,
)
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.lcm.lcm_ingest import ingest_gateway_message_row
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.onboarding.pairing import PairingStore
from sevn.gateway.queue.queue_multi import (
    MultiDispatchHooks,
    MultiSpawnOutcome,
    in_flight_task_summary_for_session,
)
from sevn.gateway.routing.response_filters import is_intentional_silence_response
from sevn.gateway.runtime.platform_runtime import PlatformRuntimeRegistry
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session.session_reset import resolve_session_reset_policy, session_should_reset
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.telegram.telegram_inline import try_route_telegram_inline
from sevn.gateway.telegram.telegram_quick_actions import (
    GATEWAY_OUTBOUND_PHASE_KEY,
    build_quick_action_inline_keyboard,
    is_telegram_fast_callback_ack,
    record_assistant_platform_message,
    telegram_fast_callback_ack_text,
)
from sevn.gateway.turn.turn_media import build_turn_media_summaries
from sevn.gateway.util.strings import (
    VOICE_DISABLED_USER_MESSAGE,
    VOICE_INBOUND_REJECTED_TOO_LARGE,
    VOICE_INBOUND_REJECTED_TOO_LONG,
    blocked_inbound_user_message,
)
from sevn.logging.context import set_message_id as _set_log_message_id
from sevn.plugins.hook import HookContext
from sevn.prompts.fallbacks import ASSISTANT_NO_OUTPUT_PLACEHOLDER, TURN_EMPTY_FALLBACK_TEXT
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.security.llmignore import write_blocked_inbound
from sevn.voice.factory import (
    VoiceRuntimeSettings,
    build_stt_pipeline,
    build_tts_pipeline,
    resolve_effective_tts_mode,
    voice_runtime_settings,
)
from sevn.voice.stt import PLACEHOLDER_LLM_LINE, SpeechToTextPipeline
from sevn.voice.trace_events import emit_voice_event
from sevn.voice.tts import TextToSpeechPipeline

if TYPE_CHECKING:
    from sevn.agent.subagents.supervisor import SubAgentSupervisor

_THINK_RE = re.compile(r"<\s*think\b[^>]*>.*?</\s*think\s*>", re.DOTALL | re.IGNORECASE)
_OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
# Unparsed tool-call XML that some providers (MiniMax, others) occasionally leak as text
# instead of executing. Model-agnostic regexes — the provider namespace is captured but not
# hardcoded. Fenced code blocks are carved out of the input first, so the agent can still
# intentionally render these fragments by wrapping them in ``` ... ``` (see
# ``transcript-review-2026-05-25.md`` item #4).
_TOOL_CALL_INVOKE_RE = re.compile(
    r"<\s*invoke\b[^>]*>.*?</\s*invoke\s*>", re.DOTALL | re.IGNORECASE
)
_TOOL_CALL_PARAMETER_RE = re.compile(
    r"<\s*parameter\b[^>]*>.*?</\s*parameter\s*>", re.DOTALL | re.IGNORECASE
)
# Unbalanced opens / closes — when the model truncates or emits half-tags.
_TOOL_CALL_OPEN_INVOKE_RE = re.compile(r"<\s*invoke\b[^>]*>", re.IGNORECASE)
_TOOL_CALL_CLOSE_INVOKE_RE = re.compile(r"</\s*invoke\s*>", re.IGNORECASE)
_TOOL_CALL_OPEN_PARAMETER_RE = re.compile(r"<\s*parameter\b[^>]*>", re.IGNORECASE)
_TOOL_CALL_CLOSE_PARAMETER_RE = re.compile(r"</\s*parameter\s*>", re.IGNORECASE)
_TOOL_CALL_NAMESPACE_RE = re.compile(r"</?\s*[A-Za-z0-9_-]+:tool_call\b[^>]*>", re.IGNORECASE)
# Box-drawing variants — a few model encodings substitute U+2502 / U+2503 for the literal
# ``<`` opener (transcript-review-2026-05-28). Normalise those before regex matching so the
# rest of the sanitizer pipeline applies uniformly.
_BRACKET_LIKE_PREFIX_RE = re.compile(
    r"[│┃╰-╿]+(?=\s*(?:invoke|parameter|[A-Za-z0-9_-]+:tool_call)\b)",
    re.IGNORECASE,
)
_FENCED_CODE_RE = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)


def _reply_keyboard_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``channels.telegram.reply_keyboard.enabled`` (defaults ``True``).

    Mirrors ``sevn.gateway.menu.menu._telegram_reply_keyboard_enabled``; inlined
    here so :meth:`ChannelRouter.apply_workspace` can refresh adapter flags
    without importing the menu module (forbidden by import-linter contracts).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``True`` when the persistent reply keyboard is enabled.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _reply_keyboard_enabled(WorkspaceConfig.minimal())
        True
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        rk = channels.telegram.reply_keyboard
        if rk is not None:
            return bool(rk.enabled)
    return True


def _dm_policy_label(workspace: WorkspaceConfig) -> str:
    """Return configured Telegram DM policy string (defaults to ``open``).

    Mirrors ``sevn.gateway.menu.menu._telegram_dm_policy``; inlined here so
    :meth:`ChannelRouter.apply_workspace` can refresh adapter flags without
    importing the menu module (forbidden by import-linter contracts).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        str: Lowercase policy label suitable for ``_parse_dm_policy``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _dm_policy_label(WorkspaceConfig.minimal())
        'open'
    """
    channels = workspace.channels
    if channels is not None and channels.telegram is not None:
        raw = channels.telegram.dm_policy
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return "open"


def _strip_unparsed_tool_call_xml(segment: str) -> str:
    """Remove unparsed tool-call XML fragments from a non-code-fence segment.

    Handles balanced pairs, lone opens / closes (truncated outputs), the wrapper
    ``<namespace:tool_call>`` envelope, and a few box-drawing characters that
    occasionally substitute for the literal ``<`` opener.

    Args:
        segment (str): Text outside fenced/inline code regions.

    Returns:
        str: Segment with ``<invoke>``, ``<parameter>``, and ``</…:tool_call>``
        fragments stripped. Provider namespace in ``…:tool_call`` is matched generically
        (model-agnostic).

    Examples:
        >>> _strip_unparsed_tool_call_xml("a<invoke name='x'>y</invoke>b")
        'ab'
        >>> _strip_unparsed_tool_call_xml("ok</minimax:tool_call>")
        'ok'
        >>> _strip_unparsed_tool_call_xml("│invoke name='x'>y</invoke>z")
        'z'
        >>> _strip_unparsed_tool_call_xml("<invoke name='x'>")
        ''
    """
    out = _BRACKET_LIKE_PREFIX_RE.sub("<", segment)
    out = _TOOL_CALL_INVOKE_RE.sub("", out)
    out = _TOOL_CALL_PARAMETER_RE.sub("", out)
    out = _TOOL_CALL_OPEN_INVOKE_RE.sub("", out)
    out = _TOOL_CALL_CLOSE_INVOKE_RE.sub("", out)
    out = _TOOL_CALL_OPEN_PARAMETER_RE.sub("", out)
    out = _TOOL_CALL_CLOSE_PARAMETER_RE.sub("", out)
    out = _TOOL_CALL_NAMESPACE_RE.sub("", out)
    return out  # noqa: RET504


def _outbound_stream_hygiene(text: str) -> tuple[str, int]:
    """Strip think tags, OSC/ANSI chunks, and unparsed tool-call XML; preserve fenced code.

    Args:
        text (str): Raw outbound text emitted by the agent loop.

    Returns:
        tuple[str, int]: Sanitised text and the count of characters removed.

    Examples:
        >>> _outbound_stream_hygiene("hello")
        ('hello', 0)
        >>> out, dropped = _outbound_stream_hygiene("<think>x</think>hi")
        >>> out
        'hi'
        >>> dropped > 0
        True
        >>> out, dropped = _outbound_stream_hygiene("a<invoke>x</invoke>b")
        >>> out
        'ab'
        >>> "<invoke>" in _outbound_stream_hygiene("```<invoke>x</invoke>```")[0]
        True
    """
    t = _THINK_RE.sub("", text)
    t = _OSC_RE.sub("", t)
    # Split out fenced/inline code regions and only sanitize the non-code segments so the
    # agent can intentionally render tool-call XML by wrapping it in a code block.
    parts = _FENCED_CODE_RE.split(t)
    sanitized: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            # Odd indices are the captured code regions; preserve as-is.
            sanitized.append(part)
        else:
            sanitized.append(_strip_unparsed_tool_call_xml(part))
    out = "".join(sanitized)
    dropped = max(0, len(text) - len(out))
    return out, dropped


def _outbound_has_deliverable(filtered_text: str, metadata: dict[str, Any]) -> bool:
    """Return whether an outbound envelope has text, attachment, TTS, or keyboard payload.

    Args:
        filtered_text (str): Hygiene-filtered assistant text.
        metadata (dict[str, Any]): Outbound routing metadata after TTS merge.

    Returns:
        bool: ``True`` when the router should call ``adapter.send``.

    Examples:
        >>> _outbound_has_deliverable("", {})
        False
        >>> _outbound_has_deliverable("  ", {"attachment_path": "/tmp/x.pdf"})
        True
        >>> _outbound_has_deliverable("", {"inline_keyboard": {"inline_keyboard": []}})
        False
    """
    if filtered_text.strip():
        return True
    for key in ("attachment_path", "tts_audio_path"):
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            return True
    inline = metadata.get("inline_keyboard")
    if isinstance(inline, dict):
        rows = inline.get("inline_keyboard")
        if isinstance(rows, list) and any(rows):
            return True
    return bool(isinstance(inline, str) and inline.strip())


RunTurnFn = Callable[[str, str], Coroutine[Any, Any, None]]
_CORRELATION_META_KEY = "__correlation_id"


_URL_RE = re.compile(r"https?://|t\.me/|tg://", re.IGNORECASE)


def _classify_message_kinds(msg: IncomingMessage) -> set[str]:
    """Tag an inbound message with the content kinds it carries.

    Args:
        msg (IncomingMessage): Adapter-normalised inbound envelope.

    Returns:
        set[str]: Subset of ``{"text", "links", "documents"}``. ``links`` is
        only set when the text body itself matches ``http(s)://``, ``t.me/``,
        or ``tg://``; ``documents`` is set when any attachment is a document,
        photo, audio, video, or voice descriptor. Empty messages return an
        empty set.

    Examples:
        >>> m = IncomingMessage(channel="t", user_id="1", text="hi https://x")
        >>> sorted(_classify_message_kinds(m))
        ['links', 'text']
        >>> sorted(_classify_message_kinds(IncomingMessage(channel="t", user_id="1", text="")))
        []
    """
    kinds: set[str] = set()
    text = (msg.text or "").strip()
    if text:
        kinds.add("text")
        if _URL_RE.search(msg.text or ""):
            kinds.add("links")
    for att in msg.attachments or []:
        if not isinstance(att, dict):
            continue
        att_type = att.get("type") or att.get("kind")
        if att_type in ("document", "photo", "audio", "video", "voice"):
            kinds.add("documents")
            break
    return kinds


def _build_unique_message_id(
    channel: str,
    user_id: str,
    *,
    topic_id: object | None,
    session_scope: str,
    rand_hex_len: int = 6,
) -> str:
    """Build a labelled per-inbound-message correlation id.

    Args:
        channel (str): Adapter key (``telegram``, ``webchat``, ...).
        user_id (str): Channel-specific user identifier.
        topic_id (object | None): Optional topic/thread id; omitted when absent.
        session_scope (str): Stable session-scope key (``channel:user_id``).
        rand_hex_len (int): Random hex tail length for the ``msg=`` segment.

    Returns:
        str: ``<channel>:user=<user_id>[:topic=<topic_id>]:session=<hash6>:msg=<rand>``.
        The ``session=`` segment is a 6-hex SHA-256 prefix of ``session_scope``
        so it ties together every inbound message from the same channel/user/scope
        without leaking long opaque identifiers into logs.

    Examples:
        >>> mid = _build_unique_message_id("telegram", "12345", topic_id=7, session_scope="telegram:12345")
        >>> mid.startswith("telegram:user=12345:topic=7:session=")
        True
    """
    parts = [channel, f"user={user_id}"]
    if topic_id not in (None, ""):
        parts.append(f"topic={topic_id}")
    sess_h = hashlib.sha256(session_scope.encode("utf-8")).hexdigest()[:6]
    parts.append(f"session={sess_h}")
    parts.append(f"msg={secrets.token_hex(max(1, rand_hex_len // 2))[:rand_hex_len]}")
    return ":".join(parts)


def _utc_ns() -> int:
    """Return the current UTC wall-clock time in nanoseconds.
    Returns:
        int: ``time.time_ns()`` snapshot (monotonic in practice on tests).
    Examples:
        >>> isinstance(_utc_ns(), int)
        True
    """
    return time.time_ns()


class ChannelRouter:
    """Inbound/outbound pipelines and adapter registry.
    Wires the LLM Guard scanner, per-scope rate limiter, command dispatcher,
    media store, and durable session manager together. Adapters are registered
    by name; ``handle_webhook`` and ``route_outgoing`` form the public surface
    consumed by :mod:`sevn.gateway.http_server`.
    Example:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ChannelRouter.route_incoming)
        True
    """

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        content_root: Path,
        sessions: SessionManager,
        dispatcher: CommandDispatcher,
        scanner: LLMGuardScanner,
        trace: TraceSink,
        rate: TokenBucketLimiter,
        media: MediaStore,
        owner_user_ids: frozenset[str] | None = None,
        actor_is_owner: Callable[[IncomingMessage], bool] | None = None,
        run_turn: RunTurnFn | None = None,
        queue_mode: str | None = None,
        stt_pipeline: SpeechToTextPipeline | None = None,
        tts_pipeline: TextToSpeechPipeline | None = None,
        plugin_hook_chain: Any | None = None,
        steer_store: Any | None = None,
    ) -> None:
        """Build the router with collaborators wired in (`specs/17-gateway.md` §2.2).
        Args:
            workspace (WorkspaceConfig): Parsed workspace configuration.
            content_root (Path): Workspace content root for sandboxed writes.
            sessions (SessionManager): Durable session facade.
            dispatcher (CommandDispatcher): Pre-LLM command short-circuit.
            scanner (LLMGuardScanner): Inbound guard.
            trace (TraceSink): Trace sink for gateway events.
            rate (TokenBucketLimiter): Per-scope rate limiter.
            media (MediaStore): Attachment + signed-URL store.
            owner_user_ids (frozenset[str] | None): Static owner allowlist.
            actor_is_owner (Callable[[IncomingMessage], bool] | None): Override
                callback that resolves owner status dynamically per message.
            run_turn (RunTurnFn | None): Override for the agent dispatch glue.
            queue_mode (str | None): Override workspace queue policy.
            stt_pipeline (SpeechToTextPipeline | None): Optional STT chain for tests.
            tts_pipeline (TextToSpeechPipeline | None): Optional TTS chain for tests.
            plugin_hook_chain (Any | None): Optional terminal transform chain
                (`specs/34-plugin-hooks.md` §4.4) for outbound assistant text.
            steer_store (Any | None): Optional :class:`~sevn.gateway.queue.steer_store.SessionSteerStore`.
        Examples:
            >>> import inspect
            >>> "workspace" in inspect.signature(ChannelRouter).parameters
            True
        """
        self._workspace = workspace
        self._content_root = content_root.expanduser().resolve()
        self._sessions = sessions
        self._dispatcher = dispatcher
        self._scanner = scanner
        self._trace = trace
        self._rate = rate
        self._media = media
        self._owner_ids = owner_user_ids or frozenset()
        self._actor_is_owner_cb = actor_is_owner
        self._run_turn = run_turn or self._default_run_turn
        self._queue_mode = (
            queue_mode
            or (
                workspace.gateway.queue_mode
                if workspace.gateway and workspace.gateway.queue_mode
                else None
            )
            or DEFAULT_GATEWAY_QUEUE_MODE
        )
        self._voice_rt: VoiceRuntimeSettings = voice_runtime_settings(workspace)
        self._stt = stt_pipeline or build_stt_pipeline(workspace, trace=trace)
        self._tts = tts_pipeline or build_tts_pipeline(
            workspace,
            content_root=self._content_root,
            trace=trace,
        )
        self._plugin_hook_chain = plugin_hook_chain
        self._steer_store = steer_store
        # W3.1/W3.3: process-wide sub-agent supervisor, wired lazily by
        # ``http_server.create_app`` right after ``run_boot_hooks`` (the boot hook that
        # constructs it runs *after* ``build_agent_run_turn``). ``None`` when sub-agents
        # are unwired (most unit tests) — ``agent_turn.py`` reads it via ``getattr`` and
        # treats ``None`` as "no sub-agent tracking", preserving classic single-turn behavior.
        self._subagent_supervisor: SubAgentSupervisor | None = None
        self._plan_gate_registry: Any | None = None
        self._plan_gate_callback_handler: Any | None = None
        self._evolution_approval_registry: Any | None = None
        self._evolution_approval_callback_handler: Any | None = None
        self._quick_action_callback_handler: Any | None = None
        self._menu_callback_handler: Any | None = None
        self._config_menu_handler: Any | None = None
        self._core_command_handler: Any | None = None
        self._evolution_command_handler: Any | None = None
        self._diagnostic_command_handler: Any | None = None
        self._menu_action_router: Any | None = None
        self._menu_form_handler: Any | None = None
        self._dashboard_pin_publisher: Any | None = None
        self._telegram_dashboard_pins: dict[str, int] = {}
        self._telegram_stream_anchor: dict[str, int] = {}
        self._inline_botfather_warned: bool = False
        self._config_menu_nav: dict[tuple[int, int], object] = {}
        self._adapters: dict[str, ChannelAdapter] = {}
        # Sessions that hit the tier-C-unavailable retry path last turn. When set, the next
        # tier-B execution for that session starts directly with the expanded budget,
        # skipping the wasted first attempt (`specs/14-executor-tier-b.md` §5; item #10 of
        # the 2026-05-25 transcript review).
        self._sessions_needing_expanded_budget: set[str] = set()
        # Per-session summary of the **last completed turn** — intent, tier, and the most
        # recent tool-call name when applicable. Populated by ``agent_turn`` at outcome
        # time, consulted by the regen quick-action handler so a regen never restarts cold
        # (`specs/16-harness-discipline.md`; transcript-review item #9).
        self._last_turn_summary: dict[str, dict[str, Any]] = {}
        # Populated by ``http_server.create_app`` via
        # :func:`sevn.gateway.runtime.deployment_id.load_or_create_deployment_id`
        # (`specs/17-gateway.md` §10.14 TE-1).
        self._deployment_id: str | None = None
        # Populated by ``http_server.create_app`` via
        # :func:`sevn.config.version_id.ensure_version_id` (issue #30 / plan D1-D2).
        self._version_id: str | None = None
        self._telegram_typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._replay_job_event_fanout: Any | None = None
        self._session_inbound_voice_flag: dict[str, bool] = {}
        self._platform_runtime = PlatformRuntimeRegistry()
        self._pairing_store = PairingStore(self._content_root)
        self._platform_command_handler: Any | None = None

    @property
    def platform_runtime(self) -> PlatformRuntimeRegistry:
        """In-process platform pause/resume and circuit-breaker registry.

        Returns:
            PlatformRuntimeRegistry: Mutable runtime registry.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.platform_runtime.fget)
            True
        """
        return self._platform_runtime

    @property
    def pairing_store(self) -> PairingStore:
        """Workspace-scoped DM pairing store.

        Returns:
            PairingStore: Pairing persistence helper.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.pairing_store.fget)
            True
        """
        return self._pairing_store

    def adapter_names(self) -> tuple[str, ...]:
        """Return registered adapter keys.

        Returns:
            tuple[str, ...]: Sorted adapter names.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.adapter_names)
            True
        """
        return tuple(sorted(self._adapters))

    def resolve_queue_mode_for_channel(self, channel: str) -> str:
        """Return effective busy-input queue mode for one adapter.

        Args:
            channel (str): Adapter name.

        Returns:
            str: ``cancel``, ``queue``, ``steer``, or ``multi``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.resolve_queue_mode_for_channel)
            True
        """
        gateway_mode = (
            str(self._workspace.gateway.queue_mode)
            if self._workspace.gateway is not None and self._workspace.gateway.queue_mode
            else None
        )
        return resolve_busy_input_mode(
            self._workspace.channels,
            channel,
            gateway_queue_mode=gateway_mode,
        )

    def build_multi_dispatch_hooks(
        self,
        *,
        classify_override: Callable[..., Awaitable[object]] | None = None,
    ) -> MultiDispatchHooks | None:
        """Build ``multi`` hooks when sub-agents and spawn glue are wired (D6).

        Args:
            classify_override (Callable | None): Test-only classifier stub.

        Returns:
            MultiDispatchHooks | None: Hooks when sub-agents are enabled; else ``None``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.build_multi_dispatch_hooks)
            True
        """
        supervisor = self._subagent_supervisor
        spawn_fn = getattr(self, "_spawn_multi_l1_tier_b", None)
        classify_fn = getattr(self, "_multi_classify_busy", None)
        if supervisor is None or spawn_fn is None or classify_fn is None:
            return None

        async def _classify_busy(
            in_flight_summary: str,
            queued_summaries: tuple[str, ...],
            new_message: str,
        ) -> tuple[str, bool]:
            if classify_override is not None:
                raw = await classify_override(in_flight_summary, queued_summaries, new_message)
                if isinstance(raw, tuple) and len(raw) == 2:
                    label, fallback = raw
                    return str(label), bool(fallback)
                return str(raw), False
            result = await classify_fn(in_flight_summary, queued_summaries, new_message)
            return str(result[0]), bool(result[1])

        async def _spawn(session_id: str, correlation_id: str) -> MultiSpawnOutcome:
            outcome = await spawn_fn(session_id, correlation_id)
            if isinstance(outcome, MultiSpawnOutcome):
                return outcome
            return MultiSpawnOutcome(str(outcome))

        async def _notify(session_id: str, line: str) -> None:
            from sevn.gateway.session_manager import load_session_row

            sess = load_session_row(self._sessions.connection, session_id)
            if sess is None or not line.strip():
                return
            try:
                await self.route_outgoing(
                    OutgoingMessage(
                        channel=sess.channel,
                        user_id=sess.user_id,
                        text=line.strip(),
                        session_id=session_id,
                        metadata={},
                    ),
                )
            except Exception:
                logger.exception(
                    "queue_multi_operator_notice_failed session_id={}",
                    session_id,
                )

        return MultiDispatchHooks(
            classify_busy=_classify_busy,
            spawn_new_task=_spawn,
            notify_operator=_notify,
        )

    async def _ensure_session_for_turn(self, msg: IncomingMessage) -> str:
        """Ensure session exists and apply per-channel reset policy when due.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            str: Active session id for the message scope.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter._ensure_session_for_turn)
            True
        """
        scoped = _scope_key(msg)
        session_id = await self._sessions.ensure_session(
            scope_key=scoped,
            channel=msg.channel,
            user_id=msg.user_id,
        )
        policy = resolve_session_reset_policy(
            channel=msg.channel,
            workspace_channels=self._workspace.channels,
        )
        if not policy.enabled:
            return session_id
        row = self._sessions.connection.execute(
            """
            SELECT created_at, updated_at
            FROM gateway_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return session_id
        created_at, updated_at = row[0], row[1]
        if session_should_reset(
            policy=policy,
            created_at=str(created_at) if created_at is not None else None,
            updated_at=str(updated_at) if updated_at is not None else None,
        ):
            session_id = await self._sessions.rotate_session(
                session_id,
                content_root=self._content_root,
            )
        return session_id

    def slash_command_allowed(self, msg: IncomingMessage, *, is_owner: bool) -> bool:
        """Return whether a slash command may run for ``msg`` under slash tiers.

        Args:
            msg (IncomingMessage): Inbound slash command.
            is_owner (bool): Owner flag for the sender.

        Returns:
            bool: ``True`` when allowed or not a slash command.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.slash_command_allowed)
            True
        """
        text = (msg.text or "").strip()
        if not text.startswith("/"):
            return True
        if is_owner:
            return True
        if not slash_allowed_for_actor(text, is_owner=False):
            return False
        chat_type = None
        if isinstance(msg.metadata, dict):
            raw = msg.metadata.get("chat_type")
            if isinstance(raw, str):
                chat_type = raw
        policy = policy_for_message(
            channel=msg.channel,
            workspace_channels=self._workspace.channels,
            user_id=msg.user_id,
            chat_type=chat_type,
        )
        cmd = canonical_slash_command(text)
        return policy.can_run(msg.user_id, cmd)

    @property
    def media_store(self) -> MediaStore:
        """Underlying :class:`~sevn.gateway.media.media_store.MediaStore` for HTTP handlers.
        Returns:
            MediaStore: The router's attachment store.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.media_store.fget)
            True
        """
        return self._media

    def load_turn_media(
        self,
        session_id: str,
        turn_id: str,
    ) -> tuple[Any, ...]:
        """Hydrate turn-bound media for one dispatch (W9 turn boundary).

        Args:
            session_id (str): Gateway session id.
            turn_id (str): Turn / correlation id.

        Returns:
            tuple: :class:`~sevn.gateway.turn.turn_media.TurnMediaItem` rows with bytes
            when materialised under ``channel_files/``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.load_turn_media)
            True
        """
        from sevn.gateway.turn.turn_media import hydrate_turn_media, load_turn_media_summaries

        summaries = load_turn_media_summaries(
            self._sessions.connection,
            session_id,
            turn_id,
        )
        return hydrate_turn_media(session_id, summaries, self._content_root)

    def apply_workspace(self, ws: WorkspaceConfig) -> None:
        """Refresh runtime state after a ``sevn.json`` reload (`specs/17-gateway.md` §2.9).

        Single hook invoked by :meth:`MenuActionRouter._reload_workspace` and
        :meth:`CoreCommandHandler._reload_workspace`. Recomputes ``_queue_mode``
        from ``ws.gateway.queue_mode`` (defaults to ``cancel`` — same logic as
        ``sevn.gateway.menu.menu._gateway_queue_mode``, inlined here to keep
        :mod:`sevn.gateway.channel_router` independent of the menu module per
        import-linter contracts), rebuilds the LLM Guard scanner + voice
        runtime, refreshes the Telegram adapter's reply keyboard / DM policy
        flags, and propagates ``ws`` to every command + menu handler so
        subsequent renders observe the new config. The deployment id is
        preserved across reloads.

        Args:
            ws (WorkspaceConfig): Reloaded workspace settings.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.apply_workspace)
            True
        """
        self._workspace = ws
        self._queue_mode = (
            str(ws.gateway.queue_mode)
            if ws.gateway is not None and ws.gateway.queue_mode is not None
            else DEFAULT_GATEWAY_QUEUE_MODE
        )
        self._scanner = LLMGuardScanner(self._content_root, ws)
        self._voice_rt = voice_runtime_settings(ws)
        from sevn.voice.host_deps import maybe_resolve_whisper_model_env

        maybe_resolve_whisper_model_env(allow_download=False)
        self._stt = build_stt_pipeline(ws, trace=self._trace)
        self._tts = build_tts_pipeline(
            ws,
            content_root=self._content_root,
            trace=self._trace,
        )
        tg_adapter = self._adapters.get("telegram")
        if isinstance(tg_adapter, TelegramAdapter):
            tg_adapter._cfg = tg_adapter._cfg.model_copy(
                update={
                    "reply_keyboard_enabled": _reply_keyboard_enabled(ws),
                    "dm_policy": _parse_dm_policy(_dm_policy_label(ws)),
                },
            )
        for attr in (
            "_config_menu_handler",
            "_menu_callback_handler",
            "_core_command_handler",
            "_menu_action_router",
            "_menu_form_handler",
        ):
            handler = getattr(self, attr, None)
            if handler is not None:
                handler._workspace = ws

    async def _default_run_turn(self, session_id: str, correlation_id: str) -> None:
        """Misconfiguration fallback when ``run_turn`` was not wired at boot (§2.6).
        Args:
            session_id (str): Target session.
            correlation_id (str): Trace correlation identifier.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter._default_run_turn)
            True
        """
        logger.error(
            "gateway run_turn not configured — wire build_agent_run_turn at boot "
            "(session_id={} correlation_id={})",
            session_id,
            correlation_id,
        )
        await self._emit(
            kind="gateway.agent_dispatch_stub",
            session_id=session_id,
            turn_id=correlation_id,
            status="misconfigured",
            attrs={"queue_mode": self._queue_mode},
        )

    def register_adapter(self, adapter: ChannelAdapter) -> None:
        """Record an inbound/outbound translator.
        Args:
            adapter (ChannelAdapter): Adapter keyed by ``adapter.name``.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.register_adapter)
            True
        """
        self._adapters[adapter.name] = adapter

    async def start_all(self) -> None:
        """Invoke ``adapter.start`` for every registered adapter.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter.start_all)
            True
        """
        for adapter in self._adapters.values():
            await adapter.start(self)

    def adapter_named(self, name: str) -> ChannelAdapter | None:
        """Return a registered adapter or ``None``.
        Args:
            name (str): Adapter key set by ``adapter.name``.
        Returns:
            ChannelAdapter | None: Matching adapter or ``None`` when unknown.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.adapter_named)
            True
        """
        return self._adapters.get(name)

    @property
    def session_manager(self) -> SessionManager:
        """SQLite session facade (tests and admin introspection).
        Returns:
            SessionManager: Durable session manager wired at construction.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.session_manager.fget)
            True
        """
        return self._sessions

    async def handle_webhook(self, channel: str, body: dict[str, Any]) -> None:
        """Parse webhook JSON and enqueue the inbound pipeline.
        Args:
            channel (str): Adapter key from the URL route.
            body (dict[str, Any]): Decoded JSON payload.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter.handle_webhook)
            True
        """
        adapter = self._adapters.get(channel)
        if adapter is None:
            logger.warning("unknown webhook channel={}", channel)
            return
        msg = adapter.parse_webhook(body)
        if msg is None:
            return
        if channel == "telegram":
            md = msg.metadata if isinstance(msg.metadata, dict) else {}
            is_inline = bool(md.get("is_inline_query") or md.get("is_chosen_inline_result"))
            if not is_inline:
                text = msg.text or ""
                logger.info(
                    "telegram_message_received user_id={} text_len={} preview={!r}",
                    msg.user_id,
                    len(text),
                    text[:80],
                )
        await self.route_incoming(msg)

    async def stop_all(self) -> None:
        """Shut down adapters in registration order.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter.stop_all)
            True
        """
        for adapter in self._adapters.values():
            await adapter.stop()

    def _resolve_owner_flag(self, msg: IncomingMessage) -> bool:
        """Return ``True`` when ``msg`` originates from the workspace owner.
        Args:
            msg (IncomingMessage): Normalised inbound message.
        Returns:
            bool: Owner flag from either the override callback or the static set.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter._resolve_owner_flag)
            True
        """
        if self._actor_is_owner_cb is not None:
            return self._actor_is_owner_cb(msg)
        return msg.user_id in self._owner_ids

    async def _emit(
        self,
        *,
        kind: str,
        session_id: str,
        turn_id: str,
        status: str,
        attrs: dict[str, object] | None = None,
    ) -> None:
        """Emit a synthetic single-span trace event from the gateway.
        Args:
            kind (str): Event kind string (``gateway.*``).
            session_id (str): Session identifier or empty string for pre-session events.
            turn_id (str): Correlation/turn id propagated across the pipeline.
            status (str): Status label (``started``, ``completed``, ``blocked``, ...).
            attrs (dict[str, object] | None): Optional attribute payload.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter._emit)
            True
        """
        now = _utc_ns()
        event = TraceEvent(
            kind=kind,
            span_id=uuid.uuid4().hex,
            parent_span_id=None,
            session_id=session_id,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs=dict(attrs or {}),
        )
        await self._trace.emit(event)

    def _schedule_telegram_typing(self, msg: IncomingMessage, *, session_id: str) -> None:
        """Emit ``sendChatAction(typing)`` every 4s until the turn ends (reactive-plum Wave 4).

        Telegram typing indicators expire after ~5s; resend every 4s while the tier-B
        turn is active. Call :meth:`cancel_telegram_typing` on first non-empty delta or
        when the turn completes.

        Args:
            msg (IncomingMessage): Allowed inbound envelope after scanner pass.
            session_id (str): Gateway session id used to cancel the typing loop later.

        Returns:
            None: Always.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter._schedule_telegram_typing)
            True
        """
        if msg.channel != "telegram":
            return
        adapter = self._adapters.get("telegram")
        if adapter is None:
            return
        send_action = getattr(adapter, "send_chat_action", None)
        if send_action is None:
            return
        meta = _telegram_reply_metadata(msg)
        chat_raw = meta.get("chat_id")
        if not isinstance(chat_raw, int):
            return
        topic_raw = meta.get("topic_id")
        thread_id = topic_raw if isinstance(topic_raw, int) else None
        self.cancel_telegram_typing(session_id)

        async def _typing_loop() -> None:
            try:
                while True:
                    try:
                        await send_action(
                            chat_id=chat_raw,
                            action="typing",
                            message_thread_id=thread_id,
                        )
                    except Exception as exc:
                        if _is_poll_connectivity_error(exc):
                            logger.debug(
                                "telegram_typing_offline chat_id={} err={}",
                                chat_raw,
                                exc,
                            )
                        else:
                            logger.warning(
                                "telegram_typing_failed chat_id={} err={}",
                                chat_raw,
                                exc,
                            )
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                return

        typing_task = asyncio.create_task(_typing_loop())
        self._telegram_typing_tasks[session_id] = typing_task

    def cancel_telegram_typing(self, session_id: str) -> None:
        """Stop the periodic typing loop for ``session_id`` when present.

        Args:
            session_id (str): Gateway session id (or synthetic telegram key).

        Returns:
            None: Always.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.cancel_telegram_typing)
            True
        """
        task = self._telegram_typing_tasks.pop(session_id, None)
        if task is None:
            return
        if not task.done():
            task.cancel()

    def resolve_effective_tts_mode(self, session_id: str) -> str:
        """Return session override ?? global ``voice.tts_mode`` (D4).

        Args:
            session_id (str): Gateway session id.

        Returns:
            str: Effective TTS mode for outbound gating.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelRouter.resolve_effective_tts_mode)
            True
        """
        override = self._sessions.get_tts_mode_override(session_id)
        return resolve_effective_tts_mode(
            global_mode=self._voice_rt.tts_mode,
            session_override=override,
        )

    async def _download_telegram_attachments(
        self,
        *,
        msg: IncomingMessage,
        session_id: str,
        correlation_id: str,
    ) -> None:
        """Materialise Telegram ``file_id`` attachments before STT (`specs/18` §10).

        Args:
            msg (IncomingMessage): Inbound envelope with attachment descriptors.
            session_id (str): Gateway session id.
            correlation_id (str): Trace correlation id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter._download_telegram_attachments)
            True
        """
        if msg.channel != "telegram" or not msg.attachments:
            return
        adapter = self._adapters.get("telegram")
        download = getattr(adapter, "download_attachment", None)
        if not callable(download):
            return
        dest = self._media.channel_files_dir(session_id)
        for _idx, att in enumerate(msg.attachments):
            if not isinstance(att, dict):
                continue
            file_id_raw = att.get("file_id")
            if not isinstance(file_id_raw, str) or not file_id_raw.strip():
                continue
            typ = str(att.get("type") or "attachment").strip() or "attachment"
            suggested = att.get("file_name")
            name_hint = str(suggested).strip() if isinstance(suggested, str) else None
            try:
                path = await cast("Any", download)(
                    file_id_raw.strip(),
                    dest_dir=dest,
                    attachment_type=typ,
                    suggested_name=name_hint,
                )
            except Exception:
                logger.exception(
                    "telegram_attachment_download_failed session_id={} file_id={}",
                    session_id,
                    file_id_raw,
                )
                continue
            att["filename"] = path.name
            mime = att.get("mime_type")
            await emit_voice_event(
                self._trace,
                kind="channel.telegram.attachment_download",
                session_id=session_id,
                turn_id=correlation_id,
                status="ok",
                attrs={
                    "bytes": path.stat().st_size if path.is_file() else 0,
                    "mime_type": str(mime) if isinstance(mime, str) else typ,
                    "duration_s": att.get("duration_s"),
                },
            )

    async def _prepare_inbound_voice_user_text(
        self,
        *,
        msg: IncomingMessage,
        session_id: str,
        correlation_id: str,
    ) -> tuple[str, str | None]:
        """Run STT on persisted ``voice`` / ``audio`` rows (`specs/20-voice.md` §2.3).
        Args:
            msg (IncomingMessage): Parsed inbound envelope (attachments updated in place).
            session_id (str): Gateway session id under :class:`~sevn.gateway.media.media_store.MediaStore`.
            correlation_id (str): Correlation id for traces.
        Returns:
            tuple[str, str | None]: ``(user_text_for_scanner, cap_reject)`` where
            ``cap_reject`` is ``"size"``, ``"duration"``, or ``None``.
        Examples:
            >>> ("hello", None)[1] is None
            True
        """
        vr = self._voice_rt
        if not vr.enabled:
            for att in msg.attachments:
                if isinstance(att, dict) and str(att.get("type") or "").casefold() in {
                    "voice",
                    "audio",
                }:
                    return VOICE_DISABLED_USER_MESSAGE, None
            return msg.text, None
        media_dir = self._media.channel_files_dir(session_id)
        pieces: list[str] = []
        voice_last: str | None = None
        had_voice_attachment = False
        for idx, att in enumerate(msg.attachments):
            if not isinstance(att, dict):
                continue
            typ = str(att.get("type") or "").strip().casefold()
            if typ not in {"voice", "audio"}:
                continue
            had_voice_attachment = True
            name = str(att.get("filename") or f"attachment-{idx}.bin")
            audio_path = (media_dir / name).resolve()
            try:
                audio_path.relative_to(self._content_root)
            except ValueError:
                continue
            if not audio_path.is_file():
                continue
            try:
                sz = audio_path.stat().st_size
            except OSError:
                continue
            size_mb = float(sz) / float(1024 * 1024)
            if size_mb > vr.max_voice_mb:
                await emit_voice_event(
                    self._trace,
                    kind="voice.inbound.rejected",
                    session_id=session_id,
                    turn_id=correlation_id,
                    status="rejected",
                    attrs={"reason": "size_mb", "bytes": sz},
                )
                return msg.text, "size"
            dur_raw = att.get("duration_s")
            duration_s = float(dur_raw) if isinstance(dur_raw, int | float) else None
            if duration_s is not None and duration_s > vr.max_voice_seconds:
                await emit_voice_event(
                    self._trace,
                    kind="voice.inbound.rejected",
                    session_id=session_id,
                    turn_id=correlation_id,
                    status="rejected",
                    attrs={"reason": "duration_s", "duration_s": duration_s},
                )
                return msg.text, "duration"
            mime_raw = att.get("mime_type")
            mime_type = str(mime_raw).strip() if isinstance(mime_raw, str) else None
            llm_line, meta = await self._stt.transcribe_or_placeholder(
                audio_path=audio_path,
                mime_type=mime_type,
                duration_s=duration_s,
                session_id=session_id,
                turn_id=correlation_id,
            )
            att.update(meta)
            transcript_raw = meta.get("transcript")
            if (
                isinstance(transcript_raw, str)
                and transcript_raw.strip()
                and llm_line != PLACEHOLDER_LLM_LINE
            ):
                voice_last = transcript_raw.strip()
            if llm_line == PLACEHOLDER_LLM_LINE:
                pieces.append(llm_line)
            else:
                esc = (llm_line or "").replace("\\", "\\\\").replace('"', '\\"')
                pieces.append(f'{VOICE_INBOUND_TRANSCRIPT_PREFIX}{esc}"')
        if had_voice_attachment:
            msg.metadata["inbound_voice_attachment"] = True
            self._session_inbound_voice_flag[session_id] = True
        if voice_last:
            msg.metadata["voice_user_text_last_turn"] = voice_last
        if not pieces:
            return msg.text, None
        joined = "\n".join(pieces)
        base = msg.text or ""
        if base.strip():
            return f"{base}\n{joined}", None
        return joined, None

    async def _maybe_dispatch_voice_shortcut(
        self,
        *,
        msg: IncomingMessage,
        session_id: str,
        user_text: str,
    ) -> str | None:
        """Post audit message when STT first token matches a shortcut name.

        Args:
            msg (IncomingMessage): Inbound voice message.
            session_id (str): Gateway session id.
            user_text (str): Prepared user text after STT packaging.

        Returns:
            str | None: Audit line to send before shortcut dispatch, or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter._maybe_dispatch_voice_shortcut)
            True
        """
        _ = session_id, user_text
        from sevn.gateway.commands.voice_match import (
            format_voice_matched_message,
            match_voice_shortcut,
            voice_shortcut_enabled,
        )

        if not voice_shortcut_enabled(self._workspace):
            return None
        transcript = msg.metadata.get("voice_user_text_last_turn")
        if not isinstance(transcript, str) or not transcript.strip():
            return None
        row = match_voice_shortcut(self._content_root, transcript)
        if row is None:
            return None
        name = str(row.get("name", "")).strip()
        if not name:
            return None
        return format_voice_matched_message(name)

    async def _telegram_answer_callback_query(self, msg: IncomingMessage, text: str) -> None:
        """Invoke Telegram ``answerCallbackQuery`` for inline callbacks.
        Args:
            msg (IncomingMessage): Inbound callback with ``callback_query_id``.
            text (str): Toast copy for the operator.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter._telegram_answer_callback_query)
            True
        """
        if msg.channel != "telegram":
            return
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cqid = md.get("callback_query_id")
        if not isinstance(cqid, str) or not cqid.strip():
            return
        adapter = self._adapters.get("telegram")
        if adapter is None:
            return
        answer = getattr(adapter, "answer_callback", None)
        if not callable(answer):
            return
        try:
            await cast("Any", answer)(cqid.strip(), text=text)
        except Exception:
            logger.exception(
                "telegram_answer_callback_failed channel={}",
                msg.channel,
            )

    async def route_incoming(self, msg: IncomingMessage) -> None:
        """Full inbound spine per `specs/17-gateway.md` §4.3 (truncated stubs noted inline).
        Args:
            msg (IncomingMessage): Adapter-parsed inbound envelope.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter.route_incoming)
            True
        """
        topic_meta = msg.metadata.get("topic_id") if isinstance(msg.metadata, dict) else None
        correlation_id = _build_unique_message_id(
            msg.channel,
            msg.user_id,
            topic_id=topic_meta,
            session_scope=_scope_key(msg),
        )
        msg.metadata[_CORRELATION_META_KEY] = correlation_id
        _set_log_message_id(correlation_id)
        if not self._platform_runtime.accepts_inbound(msg.channel):
            await self._emit(
                kind="gateway.route_incoming",
                session_id="",
                turn_id=correlation_id,
                status="platform_paused",
                attrs={"channel": msg.channel},
            )
            return
        md_pair = msg.metadata if isinstance(msg.metadata, dict) else {}
        if md_pair.get("pairing_pending"):
            code = self._pairing_store.generate_code(
                msg.channel,
                msg.user_id,
                user_name=str(md_pair.get("user_name") or ""),
            )
            adapter = self._adapters.get(msg.channel)
            if adapter is not None and code:
                await adapter.send(
                    OutgoingMessage(
                        channel=msg.channel,
                        user_id=msg.user_id,
                        text=(
                            f"Pairing required. Send this code to the operator:\n`{code}`\n"
                            f"Then they run: sevn pairing approve {msg.channel} {code}"
                        ),
                        session_id=await self._sessions.ensure_session(
                            scope_key=_scope_key(msg),
                            channel=msg.channel,
                            user_id=msg.user_id,
                        ),
                        metadata=dict(md_pair),
                    ),
                )
            await self._emit(
                kind="gateway.route_incoming",
                session_id="",
                turn_id=correlation_id,
                status="pairing_pending",
                attrs={"channel": msg.channel},
            )
            return
        await self._emit(
            kind="gateway.route_incoming",
            session_id="",
            turn_id=correlation_id,
            status="started",
            attrs={"channel": msg.channel, "user_id": msg.user_id},
        )
        if await try_route_telegram_inline(self, msg):
            await self._emit(
                kind="gateway.route_incoming",
                session_id="",
                turn_id=correlation_id,
                status="inline_dispatched",
                attrs={"channel": msg.channel, "user_id": msg.user_id},
            )
            return
        from sevn.gateway.routing.coding_agent_router import CodingAgentRouter

        coding_router = CodingAgentRouter(workspace=self._workspace, trace=self._trace)
        bound_agent_id = coding_router.match_binding(msg)
        if bound_agent_id is not None:
            scoped = _scope_key(msg)
            session_id_bound = await self._sessions.ensure_session(
                scope_key=scoped,
                channel=msg.channel,
                user_id=msg.user_id,
            )
            await self._sessions.add_message(
                session_id_bound,
                role="user",
                kind="message",
                content=msg.text,
                visible_to_llm=0,
                status="sent",
                turn_id=correlation_id,
            )
            adapter = self._adapters.get(msg.channel)
            await coding_router.handle_operator_message(
                msg,
                agent_id=bound_agent_id,
                session_id=session_id_bound,
                correlation_id=correlation_id,
                adapter=adapter,
            )
            await self._emit(
                kind="gateway.route_incoming",
                session_id=session_id_bound,
                turn_id=correlation_id,
                status="coding_agent_binding",
                attrs={"agent_id": bound_agent_id, "channel": msg.channel},
            )
            return
        if self._dispatcher.try_dispatch(msg):
            if is_telegram_fast_callback_ack(msg):
                await self._telegram_answer_callback_query(
                    msg,
                    telegram_fast_callback_ack_text(msg),
                )
            session_id_early = await self._ensure_session_for_turn(msg)
            actor_owner = self._resolve_owner_flag(msg)
            if (msg.text or "").strip().startswith("/") and not self.slash_command_allowed(
                msg,
                is_owner=actor_owner,
            ):
                adapter = self._adapters.get(msg.channel)
                if adapter is not None:
                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text="You are not allowed to run that command.",
                            session_id=session_id_early,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
                await self._emit(
                    kind="gateway.route_incoming",
                    session_id=session_id_early,
                    turn_id=correlation_id,
                    status="slash_denied",
                    attrs={"channel": msg.channel},
                )
                return
            plan_handler = self._plan_gate_callback_handler
            evo_handler = self._evolution_approval_callback_handler
            qa_handler = self._quick_action_callback_handler
            if qa_handler is not None and qa_handler.matches(msg):
                await self._sessions.add_message(
                    session_id_early,
                    role="user",
                    kind="command",
                    content=msg.text,
                    visible_to_llm=0,
                    status="sent",
                    turn_id=correlation_id,
                )
                reply = await qa_handler.handle(
                    msg,
                    session_id=session_id_early,
                    is_owner=self._resolve_owner_flag(msg),
                )
                if reply:
                    adapter = self._adapters.get(msg.channel)
                    if adapter is not None:
                        try:
                            tg_meta = _telegram_reply_metadata(msg)
                            await adapter.send(
                                OutgoingMessage(
                                    channel=msg.channel,
                                    user_id=msg.user_id,
                                    text=reply,
                                    session_id=session_id_early,
                                    metadata=dict(tg_meta),
                                )
                            )
                        except Exception:
                            logger.exception(
                                "qa_callback_notify_failed channel={}",
                                msg.channel,
                            )
                await self._emit(
                    kind="gateway.route_incoming",
                    session_id=session_id_early,
                    turn_id=correlation_id,
                    status="qa_callback",
                    attrs={"channel": msg.channel},
                )
                return
            if plan_handler is not None and plan_handler.matches(msg):
                await self._sessions.add_message(
                    session_id_early,
                    role="user",
                    kind="command",
                    content=msg.text,
                    visible_to_llm=0,
                    status="sent",
                    turn_id=correlation_id,
                )
                reply = await plan_handler.handle(msg, session_id=session_id_early)
                if reply:
                    adapter = self._adapters.get(msg.channel)
                    if adapter is not None:
                        try:
                            tg_meta = _telegram_reply_metadata(msg)
                            await adapter.send(
                                OutgoingMessage(
                                    channel=msg.channel,
                                    user_id=msg.user_id,
                                    text=reply,
                                    session_id=session_id_early,
                                    metadata=dict(tg_meta),
                                )
                            )
                        except Exception:
                            logger.exception(
                                "plan_gate_callback_notify_failed channel={}",
                                msg.channel,
                            )
                await self._emit(
                    kind="gateway.route_incoming",
                    session_id=session_id_early,
                    turn_id=correlation_id,
                    status="plan_gate_callback",
                    attrs={"channel": msg.channel},
                )
                return
            if evo_handler is not None and evo_handler.matches(msg):
                await self._sessions.add_message(
                    session_id_early,
                    role="user",
                    kind="command",
                    content=msg.text,
                    visible_to_llm=0,
                    status="sent",
                    turn_id=correlation_id,
                )
                reply = await evo_handler.handle(msg, session_id=session_id_early)
                if reply:
                    adapter = self._adapters.get(msg.channel)
                    if adapter is not None:
                        try:
                            tg_meta = _telegram_reply_metadata(msg)
                            await adapter.send(
                                OutgoingMessage(
                                    channel=msg.channel,
                                    user_id=msg.user_id,
                                    text=reply,
                                    session_id=session_id_early,
                                    metadata=dict(tg_meta),
                                )
                            )
                        except Exception:
                            logger.exception(
                                "evolution_approval_callback_notify_failed channel={}",
                                msg.channel,
                            )
                await self._emit(
                    kind="gateway.route_incoming",
                    session_id=session_id_early,
                    turn_id=correlation_id,
                    status="evolution_approval_callback",
                    attrs={"channel": msg.channel},
                )
                return
            await self._sessions.add_message(
                session_id_early,
                role="user",
                kind="command",
                content=msg.text,
                visible_to_llm=0,
                status="sent",
                turn_id=correlation_id,
            )
            hook_ctx = HookContext(
                workspace_id=self._workspace.workspace_root,
                session_id=session_id_early,
                turn_id=correlation_id,
                tier="B",
                correlation_id=correlation_id,
            )
            plugin_reply = await self._dispatcher.dispatch_plugin_slash_if_any(
                msg, hook_ctx, self._trace
            )
            reply = (
                plugin_reply
                if plugin_reply is not None
                else self._dispatcher.bypass_reply_text(
                    msg,
                    session_id=session_id_early,
                    is_owner=self._resolve_owner_flag(msg),
                )
            )
            if reply:
                adapter = self._adapters.get(msg.channel)
                if adapter is not None:
                    try:
                        tg_meta = _telegram_reply_metadata(msg)
                        out_meta = dict(tg_meta)
                        mid = (
                            msg.metadata.get("message_id")
                            if isinstance(msg.metadata, dict)
                            else None
                        )
                        if isinstance(mid, int):
                            out_meta["reply_to_message_id"] = mid
                        await adapter.send(
                            OutgoingMessage(
                                channel=msg.channel,
                                user_id=msg.user_id,
                                text=reply,
                                session_id=session_id_early,
                                metadata=out_meta,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "command_bypass_notify_failed channel={}",
                            msg.channel,
                        )
            await self._emit(
                kind="gateway.route_incoming",
                session_id=session_id_early,
                turn_id=correlation_id,
                status="dispatcher_hit",
                attrs={"channel": msg.channel},
            )
            return
        scoped = _scope_key(msg)
        allowed = await self._rate.allow(scoped)
        if not allowed:
            await self._emit(
                kind="gateway.route_incoming",
                session_id="",
                turn_id=correlation_id,
                status="rate_limited",
                attrs={"scope": scoped},
            )
            return
        session_id = await self._sessions.ensure_session(
            scope_key=scoped,
            channel=msg.channel,
            user_id=msg.user_id,
        )
        await self._download_telegram_attachments(
            msg=msg,
            session_id=session_id,
            correlation_id=correlation_id,
        )
        await self._media.persist_attachment_descriptors(session_id, msg.attachments)
        turn_media_summaries = build_turn_media_summaries(
            msg.attachments,
            media_dir=self._media.channel_files_dir(session_id),
        )
        user_text, cap_reject = await self._prepare_inbound_voice_user_text(
            msg=msg,
            session_id=session_id,
            correlation_id=correlation_id,
        )
        voice_shortcut_reply = await self._maybe_dispatch_voice_shortcut(
            msg=msg,
            session_id=session_id,
            user_text=user_text,
        )
        if voice_shortcut_reply is not None:
            adapter = self._adapters.get(msg.channel)
            if adapter is not None:
                try:
                    tg_meta = _telegram_reply_metadata(msg)
                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=voice_shortcut_reply,
                            session_id=session_id,
                            metadata=dict(tg_meta),
                        ),
                    )
                except Exception:
                    logger.exception("voice_shortcut_audit_failed channel={}", msg.channel)
            handler = getattr(self, "_core_command_handler", None)
            if handler is not None:
                from sevn.gateway.commands.voice_match import match_voice_shortcut

                transcript = msg.metadata.get("voice_user_text_last_turn")
                if isinstance(transcript, str):
                    row = match_voice_shortcut(self._content_root, transcript)
                    if row is not None:
                        name = str(row.get("name", ""))
                        fake = IncomingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=f"/{name}",
                            metadata=dict(msg.metadata),
                        )
                        reply = await handler.handle(fake, session_id=session_id)
                        if reply:
                            adapter = self._adapters.get(msg.channel)
                            if adapter is not None:
                                await adapter.send(
                                    OutgoingMessage(
                                        channel=msg.channel,
                                        user_id=msg.user_id,
                                        text=reply,
                                        session_id=session_id,
                                        metadata=dict(_telegram_reply_metadata(msg)),
                                    ),
                                )
            await self._emit(
                kind="gateway.route_incoming",
                session_id=session_id,
                turn_id=correlation_id,
                status="voice_shortcut",
                attrs={"channel": msg.channel},
            )
            return
        if cap_reject is not None:
            note = (
                VOICE_INBOUND_REJECTED_TOO_LARGE
                if cap_reject == "size"
                else VOICE_INBOUND_REJECTED_TOO_LONG
            )
            adapter = self._adapters.get(msg.channel)
            if adapter is not None:
                try:
                    tg_meta = _telegram_reply_metadata(msg)
                    out_meta = dict(tg_meta)
                    mid = msg.metadata.get("message_id") if isinstance(msg.metadata, dict) else None
                    if isinstance(mid, int):
                        out_meta["reply_to_message_id"] = mid
                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=note,
                            session_id=session_id,
                            metadata=out_meta,
                        )
                    )
                except Exception:
                    logger.exception("voice_cap_notify_failed channel={}", msg.channel)
            await self._emit(
                kind="gateway.route_incoming",
                session_id=session_id,
                turn_id=correlation_id,
                status="voice_cap_rejected",
                attrs={"reason": cap_reject},
            )
            return
        rq = msg.metadata.get("reply_to_quote") or msg.metadata.get("reply_quote")
        if isinstance(rq, str) and rq:
            user_text = f"{rq}{user_text}"
        actor_is_owner = self._resolve_owner_flag(msg)
        guard_skip_reason = None
        if actor_is_owner:
            tg_cfg = (
                self._workspace.channels.telegram if self._workspace.channels is not None else None
            )
            ovr = (
                tg_cfg.owner_scanner_overrides
                if tg_cfg is not None and tg_cfg.owner_scanner_overrides is not None
                else None
            )
            kinds = _classify_message_kinds(msg)
            if ovr is not None and kinds:

                def _kind_disabled(k: str) -> bool:
                    if k == "text":
                        return bool(ovr.disable_text)
                    if k == "links":
                        return bool(ovr.disable_links)
                    if k == "documents":
                        return bool(ovr.disable_documents)
                    return False

                if all(_kind_disabled(k) for k in kinds):
                    guard_skip_reason = f"owner_override:kinds={','.join(sorted(kinds))}"
        if guard_skip_reason is not None:
            logger.info(
                "llm_guard_skipped channel={} user_id={} reason={}",
                msg.channel,
                msg.user_id,
                guard_skip_reason,
            )
            verdict = ScanResult(
                verdict=ScanVerdict.allow,
                reasons=(),
                scores={},
                provider_used="owner_override",
                details={"skip_reason": guard_skip_reason},
            )
        else:
            verdict = await self._scanner.scan_inbound(
                text=user_text,
                channel=msg.channel,
                user_id=msg.user_id,
                actor_is_owner=actor_is_owner,
                source="gateway.route_inbound",
            )
        if verdict.verdict != ScanVerdict.allow:
            logger.info(
                "inbound_blocked_by_scanner channel={} user_id={} reasons={} provider_used={}",
                msg.channel,
                msg.user_id,
                [r.value for r in verdict.reasons],
                verdict.provider_used,
            )
            _ = await asyncio.to_thread(
                write_blocked_inbound,
                self._content_root,
                text=user_text,
                verdict=verdict,
                channel=msg.channel,
                user_id=msg.user_id,
            )
            blocked_row = await self._sessions.add_message(
                session_id,
                role="user",
                kind="blocked",
                content="[blocked]",
                visible_to_llm=0,
                status="sent",
                turn_id=correlation_id,
                metadata_blob=json.dumps({"warning": "content_blocked"}),
            )
            await self._emit(
                kind="gateway.llm_guard_block",
                session_id=session_id,
                turn_id=correlation_id,
                status="blocked",
                attrs={"message_id": blocked_row},
            )
            await self._emit(
                kind="gateway.route_incoming",
                session_id=session_id,
                turn_id=correlation_id,
                status="stopped_blocked",
            )
            adapter = self._adapters.get(msg.channel)
            if adapter is not None:
                try:
                    tg_meta = _telegram_reply_metadata(msg)
                    out_meta = dict(tg_meta)
                    mid = msg.metadata.get("message_id") if isinstance(msg.metadata, dict) else None
                    if isinstance(mid, int):
                        out_meta["reply_to_message_id"] = mid
                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=blocked_inbound_user_message(
                                reasons=verdict.reasons,
                                details=verdict.details,
                            ),
                            session_id=session_id,
                            metadata=out_meta,
                        )
                    )
                except Exception:
                    logger.exception(
                        "blocked_inbound_notify_failed channel={}",
                        msg.channel,
                    )
            return
        self._schedule_telegram_typing(msg, session_id=session_id)
        user_meta = _telegram_reply_metadata(msg)
        voice_last_turn = msg.metadata.get("voice_user_text_last_turn")
        if isinstance(voice_last_turn, str) and voice_last_turn.strip():
            user_meta = dict(user_meta)
            user_meta["voice_user_text_last_turn"] = voice_last_turn.strip()
        if msg.metadata.get("inbound_voice_attachment"):
            user_meta = dict(user_meta)
            user_meta["inbound_voice_attachment"] = True
        if turn_media_summaries:
            user_meta = dict(user_meta)
            user_meta["turn_media"] = turn_media_summaries
        user_extras = json.dumps(user_meta)
        user_row_id = await self._sessions.add_message(
            session_id,
            role="user",
            kind="message",
            content=user_text,
            visible_to_llm=1,
            status="sent",
            turn_id=correlation_id,
            metadata_blob=user_extras,
        )
        await ingest_gateway_message_row(
            conn=self._sessions.connection,
            workspace=self._workspace,
            content_root=self._content_root,
            trace=self._trace,
            session_id=session_id,
            channel=msg.channel,
            role="user",
            content=user_text,
            turn_id=correlation_id,
        )
        await self._sessions.set_unanswered_tail(session_id, user_row_id)
        self._telegram_stream_anchor.pop(session_id, None)
        queue_mode = self.resolve_queue_mode_for_channel(msg.channel)
        multi_hooks = None
        in_flight_summary = ""
        task_summary = user_text.strip().splitlines()[0][:200] if user_text.strip() else ""
        if queue_mode == "multi":
            multi_hooks = self.build_multi_dispatch_hooks()
            in_flight_summary = await in_flight_task_summary_for_session(
                self._subagent_supervisor,
                session_id,
            )
        await self._sessions.enqueue_dispatch(
            session_id,
            correlation_id=correlation_id,
            queue_mode=queue_mode,
            dispatch=self._run_turn,
            multi_hooks=multi_hooks,
            new_message_text=user_text,
            task_summary=task_summary,
            in_flight_task_summary=in_flight_summary,
        )
        await self._emit(
            kind="gateway.route_incoming",
            session_id=session_id,
            turn_id=correlation_id,
            status="completed",
        )

    async def route_outgoing(self, msg: OutgoingMessage) -> None:
        """Outbound spine per §4.4 (Telegram streaming + TTS).
        Args:
            msg (OutgoingMessage): Agent-emitted reply ready for delivery.
        Raises:
            ValueError: When ``msg.session_id`` is empty.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelRouter.route_outgoing)
            True
        """
        if not msg.session_id:
            raise ValueError("OutgoingMessage.session_id required")
        correlation_id = str(uuid.uuid4())
        await self._emit(
            kind="gateway.route_outgoing",
            session_id=msg.session_id,
            turn_id=correlation_id,
            status="started",
            attrs={"channel": msg.channel},
        )
        filtered, dropped = _outbound_stream_hygiene(msg.text)
        # File-link markers (`[📎 send: <path>]`) become inline buttons on Telegram.
        # Strip them from the visible body regardless of channel so they never leak.
        _file_link_paths = extract_file_link_paths(filtered)
        if _file_link_paths:
            filtered = strip_file_link_markers(filtered)
        if self._plugin_hook_chain is not None:
            hook_ctx = HookContext(
                workspace_id=self._workspace.workspace_root,
                session_id=msg.session_id,
                turn_id=correlation_id,
                tier="B",
                correlation_id=correlation_id,
            )
            filtered = await self._plugin_hook_chain.transform_terminal_chunk(
                filtered, hook_ctx, self._trace
            )
        if dropped > 0:
            await self._emit(
                kind="gateway.outgoing.filtered",
                session_id=msg.session_id,
                turn_id=correlation_id,
                status="applied",
                attrs={"dropped_bytes": dropped},
            )
        out_meta: dict[str, Any] = dict(msg.metadata)
        phase_raw = out_meta.pop(GATEWAY_OUTBOUND_PHASE_KEY, None)
        phase = (
            str(phase_raw).strip().lower()
            if isinstance(phase_raw, str) and phase_raw.strip()
            else None
        )
        vr = self._voice_rt
        u_last = str(out_meta.get("voice_user_text_last_turn") or "")
        inbound_voice = bool(
            out_meta.get("inbound_voice_attachment")
            or self._session_inbound_voice_flag.pop(msg.session_id, False)
        )
        effective_mode = self.resolve_effective_tts_mode(msg.session_id)
        if vr.enabled and self._tts.should_synthesize(
            session_tts_mode=effective_mode,
            user_text_last_turn=u_last,
            inbound_voice_attachment=inbound_voice,
        ):
            tts_out = await self._tts.synthesize_or_skip(
                cleaned_assistant_text=filtered,
                voice_id=vr.tts_voice_id,
                session_id=msg.session_id,
                turn_id=correlation_id,
            )
            if tts_out.result is not None:
                out_meta["tts_audio_path"] = str(tts_out.result.path)
        if not _outbound_has_deliverable(filtered, out_meta):
            raw_had_text = bool((msg.text or "").strip())
            cause = "sanitizer_emptied" if raw_had_text else "original_text_empty"
            logger.info(
                "route_outgoing.empty_fallback session_id={} turn_id={} cause={} dropped={}",
                msg.session_id,
                correlation_id,
                cause,
                dropped,
            )
            await self._emit(
                kind="gateway.route_outgoing",
                session_id=msg.session_id,
                turn_id=correlation_id,
                status="empty_fallback",
                attrs={"cause": cause, "dropped_bytes": dropped},
            )
            filtered = TURN_EMPTY_FALLBACK_TEXT
        # §7 (`PROBLEMS.md`): strip any ``_intent=… · tier=… · conf=…_`` footer
        # before persistence so the line never survives into LLM context on the
        # next turn. The footer (when enabled) is still rendered on the outbound
        # ``filtered`` value below — but ``persisted_content`` is what
        # ``add_message`` writes, and it's authoritative for LLM read-back.
        from sevn.gateway.routing.routing_footer import strip_model_emitted_footer

        persisted_content = strip_model_emitted_footer(filtered).rstrip()
        if persisted_content.strip() == ASSISTANT_NO_OUTPUT_PLACEHOLDER:
            logger.info(
                "route_outgoing.no_output_placeholder session_id={} turn_id={}",
                msg.session_id,
                correlation_id,
            )
            persisted_content = ""
        if is_intentional_silence_response(filtered):
            logger.info(
                "route_outgoing.intentional_silence session_id={} turn_id={}",
                msg.session_id,
                correlation_id,
            )
            await self._sessions.add_message(
                msg.session_id,
                role="assistant",
                kind="message",
                content="",
                visible_to_llm=1,
                status="sent",
                turn_id=correlation_id,
                metadata_blob=json.dumps({"intentional_silence": True}),
            )
            await self._emit(
                kind="gateway.route_outgoing",
                session_id=msg.session_id,
                turn_id=correlation_id,
                status="intentional_silence",
            )
            return
        assistant_extras: dict[str, Any] = {}
        provider_rows = out_meta.get(PROVIDER_TURN_MESSAGES_KEY)
        if isinstance(provider_rows, list) and provider_rows:
            assistant_extras[PROVIDER_TURN_MESSAGES_KEY] = provider_rows
        metadata_blob = (
            json.dumps(assistant_extras, ensure_ascii=False) if assistant_extras else None
        )
        assistant_id = await self._sessions.add_message(
            msg.session_id,
            role="assistant",
            kind="message",
            content=persisted_content,
            visible_to_llm=1,
            status="pending",
            turn_id=correlation_id,
            metadata_blob=metadata_blob,
        )
        adapter = self._adapters.get(msg.channel)
        if adapter is None:
            await self._sessions.set_message_status(assistant_id, "failed")
            await self._emit(
                kind="gateway.route_outgoing",
                session_id=msg.session_id,
                turn_id=correlation_id,
                status="unknown_adapter",
            )
            return
        post_send_keyboard = False
        if msg.channel == "telegram":
            will_split = len(chunk_text(filtered)) > 1
            anchor = self._telegram_stream_anchor.get(msg.session_id)
            streaming_active = phase in ("early", "continue") or (
                phase == "final" and anchor is not None
            )
            tg_adapter = adapter if isinstance(adapter, TelegramAdapter) else None
            rich_cfg = (
                self._workspace.channels.telegram.rich
                if self._workspace.channels is not None
                and self._workspace.channels.telegram is not None
                else None
            )
            use_rich = False
            if tg_adapter is not None and not will_split:
                use_rich = should_use_rich(
                    filtered,
                    tg_adapter.rich_capability,
                    rich_cfg,
                    streaming_active=streaming_active,
                )
            out_meta[TELEGRAM_USE_RICH_KEY] = use_rich
            if streaming_active:
                out_meta[TELEGRAM_STREAMING_ACTIVE_KEY] = True
            if phase == "early" and use_rich:
                out_meta[TELEGRAM_RICH_DRAFT_KEY] = True
            if phase in ("continue", "final") and anchor is not None:
                out_meta["edit_message_id"] = anchor
            # ``persist`` (Triager ``first_message``) is always a standalone bubble — never edited.
            if phase == "final" and anchor is not None:
                api_thread = _telegram_api_thread_id(out_meta)
                chat_raw_kb = out_meta.get("chat_id")
                platform_chat_kb = int(chat_raw_kb) if isinstance(chat_raw_kb, int) else None
                if will_split:
                    post_send_keyboard = True
                else:
                    out_meta["inline_keyboard"] = build_quick_action_inline_keyboard(
                        anchor,
                        workspace=self._workspace,
                        conn=self._sessions.connection,
                        user_id=msg.user_id,
                        gateway_message_id=assistant_id,
                        platform_chat_id=platform_chat_kb,
                        topic_id=api_thread,
                        share_text=filtered,
                        viewer_source_text=filtered,
                    )
                    if _file_link_paths:
                        file_link_kb = build_file_link_keyboard(_file_link_paths)
                        if file_link_kb is not None:
                            rows = out_meta["inline_keyboard"].get("inline_keyboard") or []
                            rows = list(rows) + list(file_link_kb["inline_keyboard"])
                            out_meta["inline_keyboard"] = {"inline_keyboard": rows}
            elif phase == "final" and anchor is None:
                post_send_keyboard = True
                if _file_link_paths:
                    file_link_kb = build_file_link_keyboard(_file_link_paths)
                    if file_link_kb is not None:
                        out_meta["inline_keyboard"] = file_link_kb
        if msg.channel == "webchat" and phase == "final":
            out_meta["gateway_assistant_message_id"] = assistant_id
        out = OutgoingMessage(
            channel=msg.channel,
            user_id=msg.user_id,
            text=filtered,
            session_id=msg.session_id,
            metadata=out_meta,
        )
        chunks = []
        try:
            chunks = await adapter.send(out)
        except Exception as send_exc:
            self._platform_runtime.record_outbound_failure(msg.channel, str(send_exc))
            if isinstance(send_exc, TelegramSendError):
                await self._sessions.set_message_status(assistant_id, "failed")
                await self._emit(
                    kind="gateway.route_outgoing",
                    session_id=msg.session_id,
                    turn_id=correlation_id,
                    status="send_error",
                )
                raise send_exc
            logger.exception("adapter.send_failed channel={}", msg.channel)
            await self._sessions.set_message_status(assistant_id, "failed")
            await self._emit(
                kind="gateway.route_outgoing",
                session_id=msg.session_id,
                turn_id=correlation_id,
                status="send_error",
            )
            return
        self._platform_runtime.record_outbound_success(msg.channel)
        if msg.channel == "telegram" and chunks:
            try:
                platform_mid = int(chunks[0])
            except ValueError:
                platform_mid = None
            if platform_mid is not None and platform_mid > 0:
                chat_raw = out_meta.get("chat_id")
                platform_chat = str(int(chat_raw)) if isinstance(chat_raw, int) else None
                await asyncio.to_thread(
                    record_assistant_platform_message,
                    self._sessions.connection,
                    gateway_message_id=assistant_id,
                    platform_message_id=str(platform_mid),
                    platform_chat_id=platform_chat,
                )
                if phase == "early":
                    self._telegram_stream_anchor[msg.session_id] = platform_mid
                if phase == "final":
                    if post_send_keyboard:
                        api_thread = _telegram_api_thread_id(out_meta)
                        try:
                            platform_mid = int(chunks[-1])
                        except (TypeError, ValueError, IndexError):
                            platform_mid = None
                        if platform_mid is not None and platform_mid > 0:
                            kb = build_quick_action_inline_keyboard(
                                platform_mid,
                                workspace=self._workspace,
                                conn=self._sessions.connection,
                                user_id=msg.user_id,
                                gateway_message_id=assistant_id,
                                platform_chat_id=int(chat_raw)
                                if isinstance(chat_raw, int)
                                else None,
                                topic_id=api_thread,
                                share_text=filtered,
                                viewer_source_text=filtered,
                            )
                            edit_markup = getattr(adapter, "edit_reply_markup", None)
                            if callable(edit_markup) and isinstance(chat_raw, int):
                                await cast("Any", edit_markup)(
                                    chat_id=int(chat_raw),
                                    message_id=platform_mid,
                                    reply_markup=kb,
                                    message_thread_id=api_thread,
                                )
                    self._telegram_stream_anchor.pop(msg.session_id, None)
        await self._sessions.set_message_status(assistant_id, "sent")
        await ingest_gateway_message_row(
            conn=self._sessions.connection,
            workspace=self._workspace,
            content_root=self._content_root,
            trace=self._trace,
            session_id=msg.session_id,
            channel=msg.channel,
            role="assistant",
            # Same §7 strip applied to the LCM-ingest path so memory summaries
            # don't inherit the footer line either.
            content=persisted_content,
            turn_id=correlation_id,
        )
        await self._sessions.clear_unanswered_tail_on_final(
            session_id=msg.session_id, assistant_row_id=assistant_id
        )
        await self._emit(
            kind="gateway.route_outgoing",
            session_id=msg.session_id,
            turn_id=correlation_id,
            status="sent",
            attrs={"chunks": len(chunks)},
        )


_OUTBOUND_ROUTING_METADATA_KEYS = (
    "chat_id",
    "topic_id",
    "telegram_thread_id",
    "message_id",
    "reply_to_message_id",
    "inline_keyboard",
    "edit_message_id",
    "disable_link_preview",
    "tts_audio_path",
)


def outbound_routing_metadata(md: dict[str, Any] | None) -> dict[str, Any]:
    """Subset of inbound metadata safe to forward on :class:`OutgoingMessage`.
    Args:
        md (dict[str, Any] | None): Inbound adapter metadata (or parsed ``extras_json``).
    Returns:
        dict[str, Any]: Routing keys for ``TelegramAdapter.send`` and peers.
    Examples:
        >>> outbound_routing_metadata({"chat_id": 42, "noise": 1})
        {'chat_id': 42}
    """
    blob = md if isinstance(md, dict) else {}
    return {k: blob[k] for k in _OUTBOUND_ROUTING_METADATA_KEYS if k in blob}


def _telegram_api_thread_id(md: dict[str, Any]) -> int | None:
    """Resolve Bot API ``message_thread_id`` from routing metadata.

    Args:
        md (dict[str, Any]): Inbound or outbound Telegram routing metadata.

    Returns:
        int | None: Thread id for API calls, including forum General-topic ``1``.

    Examples:
        >>> _telegram_api_thread_id({"telegram_thread_id": 1})
        1
        >>> _telegram_api_thread_id({"topic_id": 5})
        5
    """
    raw = md.get("telegram_thread_id")
    if isinstance(raw, int):
        return raw
    topic = md.get("topic_id")
    if isinstance(topic, int):
        return topic
    return None


def _telegram_reply_metadata(msg: IncomingMessage) -> dict[str, Any]:
    """Copy inbound Telegram routing keys onto :class:`OutgoingMessage` metadata.
    Args:
        msg (IncomingMessage): Inbound message whose metadata seeds the reply.
    Returns:
        dict[str, Any]: Subset of routing keys safe to forward outbound.
    Examples:
        >>> m = IncomingMessage(channel="telegram", user_id="1", text="hi")
        >>> m.metadata["chat_id"] = 42
        >>> _telegram_reply_metadata(m)
        {'chat_id': 42}
    """
    return outbound_routing_metadata(
        msg.metadata if isinstance(msg.metadata, dict) else {},
    )


def _scope_key(msg: IncomingMessage) -> str:
    """Compute the per-session scope key for an inbound message.
    Args:
        msg (IncomingMessage): Inbound envelope.
    Returns:
        str: Override from ``metadata["session_scope_override"]`` when set,
            otherwise ``"{channel}:{user_id}"``.
    Examples:
        >>> _scope_key(IncomingMessage(channel="webchat", user_id="u1", text=""))
        'webchat:u1'
    """
    override = msg.metadata.get("session_scope_override")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return f"{msg.channel}:{msg.user_id}"
