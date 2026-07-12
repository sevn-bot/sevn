"""Telegram adapter configuration, text utilities, and workspace wiring.

Module: sevn.channels.telegram_config
Depends: pydantic, sevn.config.*, sevn.channels.markdown_safe

Exports:
    TelegramSendError — raised when Bot API send returns ``ok: false``.
    DMPolicy — DM access mode enum.
    TopicConfig — per-forum-topic settings.
    TelegramConfig — resolved adapter configuration.
    build_reply_keyboard_markup — persistent ``/new`` / ``/menu`` / ``/help`` bar.
    telegram_utf16_len — count UTF-16 code units as Telegram measures text length.
    chunk_text — split outbound text for UTF-16-safe Telegram limits.
    format_reply_quote — build reply-quote prefix (no truncation).
    telegram_config_from_workspace — build ``TelegramConfig`` from ``sevn.json``.

Examples:
    >>> chunk_text("hello")[0]
    'hello'
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from sevn.channels.markdown_safe import escape_markdown_v2
from sevn.config.defaults import TELEGRAM_MAX_TEXT_LENGTH
from sevn.config.sections.channels import TelegramInlineConfig, TelegramRichConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.telegram_quick_actions import GATEWAY_OUTBOUND_PHASE_KEY


class TelegramSendError(Exception):
    """Bot API send returned ``ok: false`` (or missing ``message_id`` on success)."""

    def __init__(
        self,
        *,
        method: str,
        description: str,
        error_code: int | None = None,
    ) -> None:
        """Capture the failing Bot API method and upstream description.

        Args:
            method (str): Telegram method name (e.g. ``sendDocument``).
            description (str): ``description`` field from the API JSON body.
            error_code (int | None): Optional Telegram ``error_code``.

        Examples:
            >>> err = TelegramSendError(method="sendDocument", description="Bad Request")
            >>> err.method
            'sendDocument'
        """
        self.method = method
        self.description = description
        self.error_code = error_code
        super().__init__(description)


# ``/start`` deep-link prefix registry — first match wins (`specs/18-channel-telegram.md` §4.5).
# 1. ``onb_<token>`` — onboarding (``specs/22-onboarding.md``) — stub: fail closed to welcome.
# 2. ``dash_<token>`` — dashboard (``specs/24-dashboard.md``) — stub: fail closed to welcome.
# 3. ``short_<name>`` — shortcut deep link (DM-only product rule) — stub: fail closed.
# 4. Else — friendly welcome; never echo raw payload (defensive cap 256 bytes).
class DMPolicy(StrEnum):
    """DM ingress policy (`specs/18-channel-telegram.md` §2.5)."""

    PAIRING = "pairing"
    ALLOWLIST = "allowlist"
    OPEN = "open"
    DISABLED = "disabled"


class TopicConfig(BaseModel):
    """Per-topic overrides in forum supergroups."""

    model_config = ConfigDict(extra="ignore")
    topic_id: int
    allow_from: list[int] = Field(default_factory=list)
    dm_policy: DMPolicy = DMPolicy.OPEN
    skills: list[str] = Field(default_factory=list)
    system_prompt: str | None = None
    require_topic: bool = False
    ignored: bool = False
    disable_link_preview: bool = False


def build_reply_keyboard_markup() -> dict[str, Any]:
    """Build persistent reply-keyboard markup for tier-A discoverability (recovery Wave B3).

    Telegram accepts one ``reply_markup`` per message; tier-A sends this on the text
    message and the gateway attaches inline quick-actions via ``editMessageReplyMarkup``.

    Returns:
        dict[str, Any]: Bot API ``ReplyKeyboardMarkup`` object.

    Examples:
        >>> kb = build_reply_keyboard_markup()
        >>> len(kb["keyboard"][0]) == 3
        True
        >>> kb["keyboard"][0][0]["text"]
        '/new'
    """
    return {
        "keyboard": [
            [
                {"text": "/new"},
                {"text": "/menu"},
                {"text": "/help"},
            ],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


class TelegramConfig(BaseModel):
    """Resolved Telegram adapter settings (token must already be decrypted)."""

    model_config = ConfigDict(extra="ignore")
    bot_token: str
    reply_keyboard_enabled: bool = True
    mode: Literal["poll", "webhook"] = "poll"
    webhook_url: str = ""
    webhook_secret_token: str = ""
    proxy_url: str | None = None
    dm_policy: DMPolicy = DMPolicy.OPEN
    allowed_users: list[int] = Field(default_factory=list)
    allowed_groups: list[int] = Field(default_factory=list)
    topics: dict[int, TopicConfig] = Field(default_factory=dict)
    commands_locale: list[str] = Field(default_factory=lambda: ["en"])
    bot_user_id: int | None = None
    parse_mode: Literal["HTML", "MarkdownV2"] = "HTML"
    rich: TelegramRichConfig | None = None
    inline: TelegramInlineConfig | None = None


def telegram_utf16_len(text: str) -> int:
    """Return UTF-16 code unit length as counted by Telegram.
    Telegram message length limits are measured in UTF-16 code units (so a
    single emoji or non-BMP code point counts as two units), not Python
    string length.
    Args:
        text (str): Input text to measure.
    Returns:
        int: Number of UTF-16 code units in ``text``.
    Examples:
        >>> telegram_utf16_len("hello")
        5
        >>> telegram_utf16_len("")
        0
        >>> telegram_utf16_len("ab") == 2
        True
    """
    return len(text.encode("utf-16-le")) // 2


def chunk_text(text: str, *, max_utf16: int = TELEGRAM_MAX_TEXT_LENGTH) -> list[str]:
    """Split *text* into Telegram-safe segments (prefer newline, then space, else hard cut).
    Uses a binary search to find the longest UTF-16-safe prefix, then prefers
    to cut at a newline (and falls back to a space) when the candidate break
    point sits beyond the first quarter of the slice. Empty input returns an
    empty list rather than ``[""]`` so callers can iterate without a guard.
    Args:
        text (str): Outbound text to split.
        max_utf16 (int, optional): Maximum UTF-16 code units per chunk.
            Defaults to ``TELEGRAM_MAX_TEXT_LENGTH``.
    Returns:
        list[str]: Ordered list of chunks; concatenation reproduces ``text``.
    Examples:
        >>> chunk_text("")
        []
        >>> chunk_text("short")
        ['short']
        >>> chunks = chunk_text("A" * 5000)
        >>> len(chunks) >= 2
        True
        >>> "".join(chunks) == "A" * 5000
        True
    """
    if not text:
        return []
    out: list[str] = []
    rest = text
    while rest:
        if telegram_utf16_len(rest) <= max_utf16:
            out.append(rest)
            break
        # Binary search longest prefix fitting max_utf16
        lo, hi = 1, len(rest)
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            chunk = rest[:mid]
            if telegram_utf16_len(chunk) <= max_utf16:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        cut = best
        window = rest[:cut]
        br = window.rfind("\n")
        if br > cut // 4:
            cut = br + 1
        else:
            sp = window.rfind(" ")
            if sp > cut // 4:
                cut = sp + 1
        piece = rest[:cut]
        out.append(piece)
        rest = rest[cut:]
    return out


def _display_sender(from_blob: dict[str, Any]) -> str:
    """Derive a friendly sender label from a Telegram ``from`` blob.
    Prefers ``first_name`` (raw), then ``@username``, and otherwise returns
    the literal ``"user"`` so reply quotes never expose raw identifiers.
    Args:
        from_blob (dict[str, Any]): Telegram ``from`` user object.
    Returns:
        str: Display label suitable for inclusion in reply-quote prefixes.
    Examples:
        >>> _display_sender({"first_name": "Alice"})
        'Alice'
        >>> _display_sender({"username": "bob"})
        '@bob'
        >>> _display_sender({})
        'user'
    """
    fn = from_blob.get("first_name")
    if isinstance(fn, str) and fn.strip():
        return fn.strip()
    un = from_blob.get("username")
    if isinstance(un, str) and un.strip():
        return f"@{un.strip()}"
    return "user"


def _is_forum_topic_stub(reply_to: dict[str, Any]) -> bool:
    """True when ``reply_to_message`` is only a forum service header (no quotable body).
    Forum supergroups insert a synthetic ``reply_to_message`` pointing at the
    topic-creation service message. Those entries should not surface as a
    quoted reply because there is no actual body to echo.
    Args:
        reply_to (dict[str, Any]): Telegram ``reply_to_message`` object.
    Returns:
        bool: True if the reply is a forum service header without text.
    Examples:
        >>> _is_forum_topic_stub({"forum_topic_created": {"name": "topic"}})
        True
        >>> _is_forum_topic_stub({"text": "hello"})
        False
        >>> _is_forum_topic_stub({})
        False
    """
    body = (reply_to.get("text") or reply_to.get("caption") or "").strip()
    if body:
        return False
    return bool(reply_to.get("forum_topic_created") or reply_to.get("forum_topic_edited"))


_MARKDOWN_V2_ESCAPED_CHARS = re.compile(r"\\([_*\[\]()~`>#+\-=|{}.!\\])")


def _normalize_quoted_body(body: str) -> str:
    r"""Reverse MarkdownV2 backslash-escapes that survive ``reply_to_message.text``.

    When the bot's outbound passes through ``_markdown_escape`` and the user replies to
    that message, Telegram echoes the escaped form back in ``reply_to_message.text``. We
    strip the leading backslashes from MarkdownV2-significant characters so the LLM sees
    the original content (`transcript-review-2026-05-25.md` item #13).

    Args:
        body (str): Raw quoted body text from ``reply_to.text`` or ``caption``.

    Returns:
        str: Body with single-character backslash-escapes removed.

    Examples:
        >>> _normalize_quoted_body(r"a\_b\=c")
        'a_b=c'
        >>> _normalize_quoted_body("plain text")
        'plain text'
    """
    return _MARKDOWN_V2_ESCAPED_CHARS.sub(r"\1", body)


def format_reply_quote(reply_to: dict[str, Any]) -> str | None:
    """Build reply-quote block for router prefixing (no truncation; PRD 01 §5.4).
    Returns a multi-line prefix the router stitches onto inbound messages so
    the LLM sees the quoted content. Returns ``None`` when the payload is not
    a real reply (forum service stub, non-dict, etc.) so the router skips the
    quote envelope entirely. MarkdownV2 backslash-escapes that survived the
    ``reply_to_message.text`` round-trip are normalised before the body is
    inserted.
    Args:
        reply_to (dict[str, Any]): Telegram ``reply_to_message`` object.
    Returns:
        str | None: Reply-quote prefix terminated with two newlines, or
        ``None`` when no quote should be rendered.
    Examples:
        >>> out = format_reply_quote(
        ...     {"from": {"first_name": "Alice"}, "message_id": 7, "text": "hi"}
        ... )
        >>> out.startswith("Quoted from Alice (message_id=7):")
        True
        >>> out.endswith("\\n\\n")
        True
        >>> format_reply_quote({"forum_topic_created": {"name": "t"}}) is None
        True
        >>> format_reply_quote({"from": {"is_bot": True}, "text": "ok"}).startswith(
        ...     "Quoted from assistant (bot)"
        ... )
        True
        >>> "name=" in format_reply_quote(
        ...     {"from": {"first_name": "A"}, "message_id": 1, "text": r"name\\=x"}
        ... )
        True
    """
    if not isinstance(reply_to, dict) or _is_forum_topic_stub(reply_to):
        return None
    from_blob = reply_to.get("from")
    if not isinstance(from_blob, dict):
        from_blob = {}
    label = "assistant (bot)" if from_blob.get("is_bot") else _display_sender(from_blob)
    mid = reply_to.get("message_id")
    body = (reply_to.get("text") or reply_to.get("caption") or "").strip()
    body = "[no text]" if not body else _normalize_quoted_body(body)
    return f"Quoted from {label} (message_id={mid}):\n{body}\n\n"


def _markdown_escape(text: str) -> str:
    r"""Escape MarkdownV2-sensitive characters in outbound text.

    Thin alias for :func:`sevn.channels.markdown_safe.escape_markdown_v2`,
    kept so external test fixtures and module exports referencing
    ``_markdown_escape`` continue to resolve. New call sites should import
    ``escape_markdown_v2`` directly.

    Args:
        text (str): Raw outbound text.

    Returns:
        str: Text with Markdown-significant characters backslash-escaped.

    Examples:
        >>> _markdown_escape("hello")
        'hello'
        >>> _markdown_escape("a_b")
        'a\\_b'
        >>> _markdown_escape("(x)")
        '\\(x\\)'
    """
    return escape_markdown_v2(text)


def _parse_topics(raw: object) -> dict[int, TopicConfig]:
    """Normalise raw ``topics`` map into ``TopicConfig`` instances.
    Silently skips entries whose keys are not coercible to ``int`` or whose
    bodies fail Pydantic validation, so a single malformed topic cannot break
    adapter startup. Validation failures are logged at WARNING.
    Args:
        raw (object): Workspace-config ``topics`` value (expected ``dict``).
    Returns:
        dict[int, TopicConfig]: Keyed by topic id; empty when ``raw`` is not
        a dict or all entries are invalid.
    Examples:
        >>> _parse_topics(None)
        {}
        >>> out = _parse_topics({"5": {"topic_id": 5, "ignored": True}})
        >>> out[5].ignored
        True
        >>> _parse_topics({"bad": {}})
        {}
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[int, TopicConfig] = {}
    for k, v in raw.items():
        try:
            tid = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            data = dict(v)
            data.setdefault("topic_id", tid)
            try:
                out[tid] = TopicConfig.model_validate(data)
            except Exception:
                logger.warning("skip_invalid_topic_config topic_id={}", tid)
    return out


def _parse_dm_policy(raw: str | None) -> DMPolicy:
    """Coerce raw config value to a ``DMPolicy`` enum member.
    Unknown or missing values fall back to ``DMPolicy.OPEN`` so a typo in
    ``sevn.json`` never accidentally locks the operator out.
    Args:
        raw (str | None): Workspace-config string (case-insensitive).
    Returns:
        DMPolicy: Matched enum member; ``DMPolicy.OPEN`` on miss.
    Examples:
        >>> _parse_dm_policy("PAIRING")
        <DMPolicy.PAIRING: 'pairing'>
        >>> _parse_dm_policy(None)
        <DMPolicy.OPEN: 'open'>
        >>> _parse_dm_policy("nonsense")
        <DMPolicy.OPEN: 'open'>
    """
    if not raw or not isinstance(raw, str):
        return DMPolicy.OPEN
    key = raw.strip().lower()
    for p in DMPolicy:
        if p.value == key:
            return p
    return DMPolicy.OPEN


def telegram_config_from_workspace(
    workspace: WorkspaceConfig,
    *,
    bot_token: str,
    webhook_secret_token: str = "",
) -> TelegramConfig:
    """Materialise :class:`TelegramConfig` from ``channels.telegram`` (`specs/18` §5).
    Resolves the post-secrets bot token and webhook secret, defaulting mode
    to ``poll`` when not explicitly ``webhook``. The webhook secret is read
    from any of the legacy aliases (``webhook_secret``, ``secret_token``,
    ``webhook_secret_token``) when the keyword argument is empty.
    Args:
        workspace (WorkspaceConfig): Loaded workspace configuration.
        bot_token (str): Already-decrypted bot token.
        webhook_secret_token (str, optional): Already-decrypted webhook
            secret. Defaults to "" (read from config aliases when empty).
    Returns:
        TelegramConfig: Resolved adapter configuration ready for the adapter
        constructor.
    Examples:
        >>> import inspect
        >>> sig = inspect.signature(telegram_config_from_workspace)
        >>> "bot_token" in sig.parameters
        True
        >>> sig.parameters["bot_token"].kind.name
        'KEYWORD_ONLY'
    """
    ch = workspace.channels
    tg = ch.telegram if ch is not None else None
    if tg is None:
        return TelegramConfig(bot_token=bot_token, webhook_secret_token=webhook_secret_token)
    mode_raw = (tg.mode or "poll").strip().lower()
    mode: Literal["poll", "webhook"] = "webhook" if mode_raw == "webhook" else "poll"
    wurl = (tg.webhook_url or "").strip() if tg.webhook_url else ""
    proxy = tg.proxy_url.strip() if isinstance(tg.proxy_url, str) and tg.proxy_url.strip() else None
    dm_policy = _parse_dm_policy(tg.dm_policy)
    allowed_users = list(tg.allowed_users or [])
    allowed_groups = list(tg.allowed_groups or [])
    topics = _parse_topics(tg.topics)
    secret = webhook_secret_token
    if not secret:
        for candidate in (tg.webhook_secret, tg.secret_token, tg.webhook_secret_token):
            if candidate and str(candidate).strip():
                secret = str(candidate).strip()
                break
    locales_raw = tg.commands_locale
    locales = (
        [str(x).strip() for x in locales_raw if str(x).strip()]
        if isinstance(locales_raw, list)
        else ["en"]
    )
    if not locales:
        locales = ["en"]
    rk_enabled = True
    rk = tg.reply_keyboard
    if rk is not None:
        rk_enabled = bool(rk.enabled)
    pm_raw = (tg.parse_mode or "").strip().lower()
    parse_mode: Literal["HTML", "MarkdownV2"] = "MarkdownV2" if pm_raw == "markdownv2" else "HTML"
    return TelegramConfig(
        bot_token=bot_token,
        reply_keyboard_enabled=rk_enabled,
        mode=mode,
        webhook_url=wurl,
        webhook_secret_token=secret,
        proxy_url=proxy,
        dm_policy=dm_policy,
        allowed_users=[int(x) for x in allowed_users],
        allowed_groups=[int(x) for x in allowed_groups],
        topics=topics,
        commands_locale=locales,
        parse_mode=parse_mode,
        rich=tg.rich,
        inline=tg.inline,
    )


def _normalize_topic_id(raw: Any) -> int | None:
    """Normalise raw thread id (drop ``None`` and general topic 1).
    Telegram returns ``message_thread_id=1`` for the "General" topic in
    forum supergroups; we treat that as no topic so the router uses the
    chat-level scope.
    Args:
        raw (Any): Raw ``message_thread_id`` from the update payload.
    Returns:
        int | None: Topic id, or ``None`` when missing / unparseable / 1.
    Examples:
        >>> _normalize_topic_id(None) is None
        True
        >>> _normalize_topic_id(1) is None
        True
        >>> _normalize_topic_id("42")
        42
        >>> _normalize_topic_id("nope") is None
        True
    """
    if raw is None:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v == 1:
        return None
    return v


def _coerce_telegram_thread_id(md: dict[str, Any]) -> int | None:
    """Return ``message_thread_id`` for Bot API calls (keeps General-topic ``1``).

    Routing uses :func:`_normalize_topic_id` (``1`` → ``None``). Telegram still
    requires the raw thread id when editing messages inside a forum topic.

    Args:
        md (dict[str, Any]): Inbound or outbound routing metadata.

    Returns:
        int | None: Thread id for ``message_thread_id``, or ``None`` for DMs.

    Examples:
        >>> _coerce_telegram_thread_id({"telegram_thread_id": 1})
        1
        >>> _coerce_telegram_thread_id({"topic_id": 42})
        42
        >>> _coerce_telegram_thread_id({}) is None
        True
    """
    raw = md.get("telegram_thread_id")
    if isinstance(raw, int):
        return raw
    topic = md.get("topic_id")
    if isinstance(topic, int):
        return topic
    return None


def _session_scope_override(chat_id: int, topic_id: int | None) -> str:
    """Build the session scope override string for the router.
    The gateway uses this string verbatim to key per-scope session state, so
    keep the format stable.
    Args:
        chat_id (int): Telegram chat id.
        topic_id (int | None): Normalised topic id (``None`` for the general
            chat).
    Returns:
        str: ``telegram:<chat>:general`` or ``telegram:<chat>:topic:<id>``.
    Examples:
        >>> _session_scope_override(123, None)
        'telegram:123:general'
        >>> _session_scope_override(123, 42)
        'telegram:123:topic:42'
    """
    if topic_id is None:
        return f"telegram:{chat_id}:general"
    return f"telegram:{chat_id}:topic:{topic_id}"


def _voice_upload_meta(path: Path) -> tuple[str, str]:
    """Return ``(filename, mime_type)`` for Telegram ``sendVoice`` multipart upload.
    Telegram accepts OGG/Opus (``audio/ogg``) and MP3 (``audio/mpeg``) for voice
    notes. Unknown extensions default to ``audio/ogg`` so local TTS backends
    that emit ``.ogg`` without a suffix still upload.
    Args:
        path (Path): On-disk TTS output file (typically under workspace
            ``channel_files/.tts/`` per [`specs/20-voice.md`](../specs/20-voice.md)).
    Returns:
        tuple[str, str]: Filename and MIME type for the multipart ``voice`` field.
    Examples:
        >>> _voice_upload_meta(Path("reply.ogg"))
        ('reply.ogg', 'audio/ogg')
        >>> _voice_upload_meta(Path("reply.mp3"))
        ('reply.mp3', 'audio/mpeg')
    """
    suffix = path.suffix.lower()
    name = path.name or "voice.ogg"
    if suffix == ".mp3":
        return name, "audio/mpeg"
    if suffix in (".ogg", ".opus"):
        return name, "audio/ogg"
    return name, "audio/ogg"


def _coerce_chat_id(v: Any) -> int | None:
    """Narrow raw chat identifiers (implementation detail).
    Outbound metadata may carry the chat id as ``int`` or as a numeric
    string (callers pickle metadata through JSON layers); accept both and
    reject everything else.
    Args:
        v (Any): Raw value from outbound metadata.
    Returns:
        int | None: Coerced chat id, or ``None`` when unparseable.
    Examples:
        >>> _coerce_chat_id(42)
        42
        >>> _coerce_chat_id("42")
        42
        >>> _coerce_chat_id("not-a-number") is None
        True
        >>> _coerce_chat_id(None) is None
        True
    """
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _should_attach_reply_keyboard(
    *,
    metadata: dict[str, Any],
    chat_id: int,
    reply_keyboard_enabled: bool,
    attached_chats: set[int],
) -> bool:
    """Return True when this tier-A final outbound should carry the reply-keyboard.

    Tier-A sends a single ``gateway_outbound_phase=final`` message without
    ``edit_message_id`` (no streaming anchor). Inline keyboards are added
    post-send by the router; this path only runs when ``inline_keyboard`` is absent.

    Args:
        metadata (dict[str, Any]): Outbound routing metadata from the gateway.
        chat_id (int): Destination Telegram chat id.
        reply_keyboard_enabled (bool): Workspace ``reply_keyboard.enabled``.
        attached_chats (set[int]): Chats that already received the keyboard.

    Returns:
        bool: True when the persistent reply-keyboard should be attached.

    Examples:
        >>> _should_attach_reply_keyboard(
        ...     metadata={"gateway_outbound_phase": "final"},
        ...     chat_id=1,
        ...     reply_keyboard_enabled=True,
        ...     attached_chats=set(),
        ... )
        True
        >>> _should_attach_reply_keyboard(
        ...     metadata={"gateway_outbound_phase": "final"},
        ...     chat_id=1,
        ...     reply_keyboard_enabled=True,
        ...     attached_chats={1},
        ... )
        False
    """
    if not reply_keyboard_enabled:
        return False
    if chat_id in attached_chats:
        return False
    phase = metadata.get(GATEWAY_OUTBOUND_PHASE_KEY)
    if not isinstance(phase, str) or phase.strip().lower() != "final":
        return False
    if metadata.get("edit_message_id") is not None:
        return False
    inline = metadata.get("inline_keyboard")
    return not inline
