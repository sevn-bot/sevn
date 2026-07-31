"""Tests for :mod:`sevn.voice.keywords` (`specs/20-voice.md` §11)."""

from __future__ import annotations

import pytest

from sevn.voice.keywords import user_text_matches_voice_trigger


def test_word_boundary_rejects_substring_inside_token() -> None:
    assert not user_text_matches_voice_trigger(user_text="speakers", keywords=("speak",))


def test_cjk_surrounding_latin_keyword() -> None:
    assert user_text_matches_voice_trigger(user_text="请 speak 一下", keywords=("speak",))


# --- Batch G W35.2: activation namespace must not alter TTS keyword gating (→ W36, D23) ---


@pytest.mark.parametrize(
    "user_text",
    [
        "please speak this aloud",
        "read aloud the summary",
        "请 speak 一下",
    ],
)
@pytest.mark.xfail(
    reason="green after W36: activation config does not change keyword matching", strict=False
)
def test_voice_trigger_keywords_unchanged_when_activation_config_present(user_text: str) -> None:
    """``voice.activation`` must remain orthogonal to ``voice.voice_trigger_keywords``."""
    from sevn.config.defaults import DEFAULT_VOICE_TRIGGER_KEYWORDS

    baseline = user_text_matches_voice_trigger(
        user_text=user_text,
        keywords=DEFAULT_VOICE_TRIGGER_KEYWORDS,
    )
    try:
        from sevn.voice import activation as activation_mod
    except ImportError:
        pytest.fail("sevn.voice.activation not implemented")
    from sevn.config.workspace_config import VoiceConfig, WorkspaceConfig

    ws = WorkspaceConfig.minimal(
        voice=VoiceConfig(
            voice_trigger_keywords=list(DEFAULT_VOICE_TRIGGER_KEYWORDS),
            model_extra={"activation": {"enabled": True, "wake_word": "hey sevn"}},
        ),
    )
    activation_mod.resolve_voice_activation_settings(ws)
    after = user_text_matches_voice_trigger(
        user_text=user_text,
        keywords=DEFAULT_VOICE_TRIGGER_KEYWORDS,
    )
    assert after == baseline
