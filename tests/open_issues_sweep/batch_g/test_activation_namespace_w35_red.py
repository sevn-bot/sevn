"""W35.2 — namespace non-collision (#102 → W36, D23).

Activation config keys must not collide with ``voice.voice_trigger_keywords`` or
``gateway.voice_trigger_keywords``; enabling activation must not alter TTS keyword gating.
"""

from __future__ import annotations

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    ACTIVATION_CONFIG_PREFIX,
    FORBIDDEN_ACTIVATION_KEY_FRAGMENTS,
    activation_enabled_workspace_doc,
    import_voice_activation_module,
)

from sevn.config.defaults import DEFAULT_VOICE_TRIGGER_KEYWORDS
from sevn.config.workspace_config import VoiceConfig, WorkspaceConfig
from sevn.voice.keywords import user_text_matches_voice_trigger


@pytest.mark.xfail(reason="green after W36: activation config key namespace", strict=False)
def test_activation_config_keys_are_distinct_from_trigger_keywords() -> None:
    activation = import_voice_activation_module()
    keys = frozenset(activation.activation_config_key_paths())
    assert ACTIVATION_CONFIG_PREFIX in next(iter(keys))
    for key in keys:
        for forbidden in FORBIDDEN_ACTIVATION_KEY_FRAGMENTS:
            assert forbidden not in key, f"activation key {key!r} collides with {forbidden!r}"
    voice_keys = {
        f"voice.{k}" for k in ("voice_trigger_keywords", "stt_providers", "tts_providers")
    }
    assert keys.isdisjoint(voice_keys)


@pytest.mark.xfail(
    reason="green after W36: gateway trigger keyword fallback stays separate", strict=False
)
def test_activation_keys_do_not_use_gateway_voice_trigger_keywords() -> None:
    activation = import_voice_activation_module()
    keys = activation.activation_config_key_paths()
    assert not any("gateway.voice_trigger_keywords" in k for k in keys)


@pytest.mark.parametrize(
    ("user_text", "keywords"),
    [
        ("please speak this aloud", ("speak",)),
        ("read aloud the summary", DEFAULT_VOICE_TRIGGER_KEYWORDS),
        ("请 speak 一下", ("speak",)),
    ],
)
@pytest.mark.xfail(
    reason="green after W36: TTS keyword gating unchanged by activation", strict=False
)
def test_enabling_activation_leaves_tts_keyword_gating_unchanged(
    user_text: str,
    keywords: tuple[str, ...],
) -> None:
    activation = import_voice_activation_module()
    baseline = user_text_matches_voice_trigger(user_text=user_text, keywords=keywords)
    doc = activation_enabled_workspace_doc(enabled=True)
    ws = WorkspaceConfig.model_validate(doc)
    activation.resolve_voice_activation_settings(ws)
    after = user_text_matches_voice_trigger(user_text=user_text, keywords=keywords)
    assert after == baseline


@pytest.mark.xfail(
    reason="green after W36: VoiceConfig keeps separate activation subtree", strict=False
)
def test_voice_config_activation_subtree_not_voice_trigger_keywords() -> None:
    activation = import_voice_activation_module()
    cfg = VoiceConfig.model_validate(
        {
            "voice_trigger_keywords": ["speak"],
            "activation": {"enabled": True, "wake_word": "hey sevn"},
        },
    )
    ws = WorkspaceConfig.minimal(voice=cfg)
    settings = activation.resolve_voice_activation_settings(ws)
    assert settings.enabled is True
    assert tuple(cfg.voice_trigger_keywords or ()) == ("speak",)
