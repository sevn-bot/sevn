"""Channels and voice subtree models for ``sevn.json``.

Module: sevn.config.sections.channels
Depends: pydantic, sevn.config.defaults, sevn.voice.backends (VoiceConfig validator only)

Exports:
    TelegramReplyKeyboardConfig — ``channels.telegram.reply_keyboard`` (`specs/18-channel-telegram.md` §5).
    TelegramQuickActionsConfig — ``channels.telegram.quick_actions`` (PRD 01 §5.15).
    TelegramRichConfig — ``channels.telegram.rich`` (Bot API 10.1 rich messages; W0 scaffold).
    TelegramInlineSourcesConfig — ``channels.telegram.inline.sources`` (inline result toggles).
    TelegramInlineConfig — ``channels.telegram.inline`` (inline mode; W0 scaffold).
    TelegramWebappConfig — ``channels.telegram.webapp`` (Mini App viewer; W0 scaffold).
    OwnerScannerOverrides — ``channels.telegram.owner_scanner_overrides`` per-kind LLM-guard kill-switches.
    TelegramChannelConfig — ``channels.telegram`` (`specs/17-gateway.md` §5).
    WebChatChannelConfig — ``channels.webchat`` (`specs/19-channel-webui.md` §5).
    VoiceConfig — top-level ``voice`` (`specs/20-voice.md`).
    ChannelsWorkspaceSectionConfig — typed ``channels`` subtree.
    channel_extra_dict — merged per-channel config blob lookup.
    channel_is_enabled — ``channels.<name>.enabled`` gate.
    resolve_busy_input_mode — map busy input mode to router queue mode.
"""

from __future__ import annotations

import warnings
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sevn.config.defaults import (
    DEFAULT_TELEGRAM_INLINE_CACHE_TIME_AGENT,
    DEFAULT_TELEGRAM_INLINE_CACHE_TIME_STATIC,
    DEFAULT_TELEGRAM_INLINE_ENABLED,
    DEFAULT_TELEGRAM_INLINE_FEEDBACK,
    DEFAULT_TELEGRAM_RICH_MODE,
    DEFAULT_VOICE_STT_PROVIDERS,
    DEFAULT_VOICE_TTS_PROVIDERS,
    DEFAULT_WEBCHAT_JWT_TTL_SECONDS,
    DEFAULT_WEBCHAT_PUBLIC,
    DEFAULT_WEBCHAT_TTS_INLINE,
)

BusyInputMode = Literal["interrupt", "queue", "steer", "multi"]
SessionResetPolicyName = Literal["daily", "idle", "both"]

JsonDict = dict[str, Any]


class TelegramReplyKeyboardConfig(BaseModel):
    """``channels.telegram.reply_keyboard`` — persistent slash-command bar (recovery Wave B3)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True


class TelegramQuickActionsConfig(BaseModel):
    """``channels.telegram.quick_actions`` — per-button QA bar visibility (PRD 01 §5.15)."""

    model_config = ConfigDict(extra="allow")

    show_regen: bool = True
    show_thumbs_up: bool = True
    show_thumbs_down: bool = True
    show_share: bool = True
    show_feedback: bool = True


class TelegramRichConfig(BaseModel):
    """``channels.telegram.rich`` — Bot API 10.1 rich message mode (D3; R1)."""

    model_config = ConfigDict(extra="allow")

    mode: Literal["off", "auto", "all"] = DEFAULT_TELEGRAM_RICH_MODE


class TelegramInlineSourcesConfig(BaseModel):
    """``channels.telegram.inline.sources`` — per-source inline result toggles."""

    model_config = ConfigDict(extra="allow")

    agent: bool = True
    second_brain: bool = True
    printing_press: bool = True
    artifacts: bool = True


class TelegramInlineConfig(BaseModel):
    """``channels.telegram.inline`` — inline mode (`@bot query`; D7/D8)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_TELEGRAM_INLINE_ENABLED
    feedback: bool = DEFAULT_TELEGRAM_INLINE_FEEDBACK
    cache_time_agent: int = Field(default=DEFAULT_TELEGRAM_INLINE_CACHE_TIME_AGENT, ge=0)
    cache_time_static: int = Field(default=DEFAULT_TELEGRAM_INLINE_CACHE_TIME_STATIC, ge=0)
    sources: TelegramInlineSourcesConfig = Field(default_factory=TelegramInlineSourcesConfig)


class TelegramWebappConfig(BaseModel):
    """``channels.telegram.webapp`` — rich artifact Mini App viewer (M1/M2)."""

    model_config = ConfigDict(extra="allow")

    viewer_enabled: bool = False
    share_to_story: bool = True


class OwnerScannerOverrides(BaseModel):
    """Per-content-kind LLM-guard kill-switches scoped to the owner actor.

    Skipping is gated by the actor's owner status (see ``allowed_users``); applies
    to any chat where the owner is the sender. A toggle disables scanning only
    for messages that consist entirely of the named kind — mixed-kind messages
    are skipped only when every kind present has its corresponding toggle on.
    """

    model_config = ConfigDict(extra="allow")

    disable_text: bool = False
    disable_links: bool = False
    disable_documents: bool = False


class TelegramChannelConfig(BaseModel):
    """``channels.telegram`` subtree (`specs/17-gateway.md` §5, `specs/18-channel-telegram.md` §5)."""

    model_config = ConfigDict(extra="allow")

    reply_keyboard: TelegramReplyKeyboardConfig | None = None
    quick_actions: TelegramQuickActionsConfig | None = None
    rich: TelegramRichConfig | None = None
    inline: TelegramInlineConfig | None = None
    webapp: TelegramWebappConfig | None = None
    show_routing: bool = False
    enabled: bool | None = None
    mode: str | None = None
    webhook_url: str | None = None
    proxy_url: str | None = None
    dm_policy: str | None = None
    allowed_users: list[int] | None = None
    allowed_groups: list[int] | None = None
    topics: JsonDict | None = None
    webhook_secret: str | None = None
    secret_token: str | None = None
    webhook_secret_token: str | None = None
    bot_token_ref: str | None = None
    commands_locale: list[str] | None = None
    parse_mode: str | None = None
    owner_scanner_overrides: OwnerScannerOverrides = Field(default_factory=OwnerScannerOverrides)


class WebChatChannelConfig(BaseModel):
    """``channels.webchat`` subtree (`specs/19-channel-webui.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool | None = None
    public: bool = Field(default=DEFAULT_WEBCHAT_PUBLIC)
    allowed_origins: list[str] = Field(default_factory=list)
    tts_inline: bool = Field(default=DEFAULT_WEBCHAT_TTS_INLINE)
    jwt_ttl_seconds: int = Field(default=DEFAULT_WEBCHAT_JWT_TTL_SECONDS, ge=1)
    jwt_secret: str | None = None
    jwt_secret_ref: str | None = None
    telegram_bot_token_ref: str | None = None


class VoiceConfig(BaseModel):
    """Top-level ``voice`` workspace keys (`specs/20-voice.md`)."""

    model_config = ConfigDict(extra="allow")

    stt_providers: list[str] | None = None
    tts_providers: list[str] | None = None
    voice_trigger_keywords: list[str] | None = None
    max_voice_mb: float | None = Field(default=None, gt=0)
    max_voice_seconds: float | None = Field(default=None, gt=0)
    stt_confidence_reprompt_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    tts_temp_ttl_days: int | None = Field(default=None, ge=1)
    preload_local_tts_on_boot: bool | None = None
    enabled: bool | None = None
    tts_mode: Literal["off", "all", "when_asked"] | None = None
    tts_voice_id: str | None = None

    @model_validator(mode="after")
    def _validate_voice_tags_and_keywords(self) -> VoiceConfig:
        """Ensure provider tags are known; warn on ``when_asked`` without keywords.

        Returns:
            VoiceConfig: ``self`` after validation side effects.

        Examples:
            >>> VoiceConfig(stt_providers=["whisper_cpp"], tts_providers=["kokoro"])
            VoiceConfig(...)
        """

        from sevn.voice.backends import validate_voice_backend_tags

        stt = (
            list(self.stt_providers)
            if self.stt_providers is not None
            else list(DEFAULT_VOICE_STT_PROVIDERS)
        )
        tts = (
            list(self.tts_providers)
            if self.tts_providers is not None
            else list(DEFAULT_VOICE_TTS_PROVIDERS)
        )
        validate_voice_backend_tags(stt, tts)
        if self.tts_mode == "when_asked" and not (
            self.voice_trigger_keywords and any(str(x).strip() for x in self.voice_trigger_keywords)
        ):
            warnings.warn(
                "voice.tts_mode is when_asked but voice.voice_trigger_keywords is empty — "
                "TTS will never run until keywords are set under voice.voice_trigger_keywords "
                "in sevn.json (specs/20-voice.md §5).",
                stacklevel=2,
            )
        return self


class ChannelsWorkspaceSectionConfig(BaseModel):
    """Typed ``channels`` subtree — unknown channel keys stay in ``model_extra``."""

    model_config = ConfigDict(extra="allow")

    telegram: TelegramChannelConfig | None = None
    webchat: WebChatChannelConfig | None = None


def channel_extra_dict(
    channels: ChannelsWorkspaceSectionConfig | None, name: str
) -> dict[str, Any]:
    """Return merged config dict for one channel adapter name.

    Args:
        channels (ChannelsWorkspaceSectionConfig | None): Parsed channels section.
        name (str): Adapter name (``telegram``, plugin entry name, …).

    Returns:
        dict[str, Any]: Typed model dump plus ``model_extra`` keys when present.

    Examples:
        >>> channel_extra_dict(None, "telegram")
        {}
    """
    if channels is None:
        return {}
    dumped = channels.model_dump(mode="python")
    blob = dumped.get(name)
    if isinstance(blob, dict):
        return dict(blob)
    extra = getattr(channels, "model_extra", None) or {}
    plugin_blob = extra.get(name)
    if isinstance(plugin_blob, dict):
        return dict(plugin_blob)
    return {}


def channel_is_enabled(channels: ChannelsWorkspaceSectionConfig | None, name: str) -> bool:
    """Return whether ``channels.<name>.enabled`` is truthy (default enabled).

    Args:
        channels (ChannelsWorkspaceSectionConfig | None): Parsed channels section.
        name (str): Adapter name.

    Returns:
        bool: Effective enabled flag.

    Examples:
        >>> channel_is_enabled(None, "telegram")
        True
    """
    extra = channel_extra_dict(channels, name)
    if not extra:
        return name in ("telegram", "webchat")
    enabled = extra.get("enabled")
    if enabled is None:
        return True
    return bool(enabled)


def resolve_busy_input_mode(
    channels: ChannelsWorkspaceSectionConfig | None,
    channel: str,
    *,
    gateway_queue_mode: str | None,
) -> str:
    """Map ``channels.<name>.busy_input_mode`` to router queue mode.

    Busy input modes map to sevn queue semantics:
    ``interrupt`` → ``cancel``, ``queue`` → ``queue``, ``steer`` → ``steer``,
    ``multi`` → ``multi`` (triager relatedness classification; `specs/36-sub-agents.md` D6).

    Args:
        channels (ChannelsWorkspaceSectionConfig | None): Parsed channels section.
        channel (str): Adapter name.
        gateway_queue_mode (str | None): Workspace ``gateway.queue_mode`` fallback.

    Returns:
        str: Effective queue mode for :meth:`SessionManager.enqueue_dispatch`.

    Examples:
        >>> resolve_busy_input_mode(None, "telegram", gateway_queue_mode="steer")
        'steer'
        >>> resolve_busy_input_mode(None, "telegram", gateway_queue_mode="cancel")
        'cancel'
        >>> resolve_busy_input_mode(None, "telegram", gateway_queue_mode="multi")
        'multi'
    """
    extra = channel_extra_dict(channels, channel)
    raw = extra.get("busy_input_mode")
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "interrupt":
            return "cancel"
        if normalized in ("queue", "steer", "multi"):
            return normalized
    fallback = (gateway_queue_mode or "cancel").strip().lower()
    if fallback == "steer":
        return "steer"
    if fallback == "queue":
        return "queue"
    if fallback == "multi":
        return "multi"
    return "cancel"
