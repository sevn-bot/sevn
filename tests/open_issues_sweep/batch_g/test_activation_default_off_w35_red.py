"""W35.1 — default-off proof (#102 → W36, D24).

With a default ``WorkspaceConfig``, wake-word activation must resolve disabled and
must not construct a capture/listener object.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    baseline_voice_workspace,
    import_voice_activation_module,
)

from sevn.config.workspace_config import WorkspaceConfig


@pytest.mark.xfail(
    reason="green after W36: voice.activation config + default-off gate", strict=False
)
def test_default_workspace_resolves_activation_disabled() -> None:
    activation = import_voice_activation_module()
    settings = activation.resolve_voice_activation_settings(WorkspaceConfig.minimal())
    assert settings.enabled is False
    assert settings.listening is False


@pytest.mark.xfail(
    reason="green after W36: no capture object when activation disabled", strict=False
)
def test_build_wake_word_listener_returns_none_when_disabled() -> None:
    activation = import_voice_activation_module()
    ws = baseline_voice_workspace()
    listener = activation.build_wake_word_listener(
        ws,
        stt_pipeline=None,
        trace=None,
        content_root=None,
    )
    assert listener is None


@pytest.mark.xfail(
    reason="green after W36: listener factory must not open audio when disabled", strict=False
)
def test_disabled_activation_never_opens_injected_frame_source() -> None:
    activation = import_voice_activation_module()
    from tests.open_issues_sweep.batch_g.conftest import _StaticFrameSource

    source = _StaticFrameSource((b"\x00" * 64,))
    ws = baseline_voice_workspace()
    listener = activation.build_wake_word_listener(
        ws,
        stt_pipeline=None,
        trace=None,
        content_root=None,
        frame_source=source,
    )
    assert listener is None
    assert source.opened is False


@pytest.mark.xfail(
    reason="green after W36: lifespan hook must no-op when activation disabled", strict=False
)
def test_maybe_start_wake_word_listener_is_noop_when_disabled() -> None:
    activation = import_voice_activation_module()
    ws = baseline_voice_workspace()
    with patch.object(activation, "WakeWordListener", create=True) as mock_cls:
        activation.maybe_start_wake_word_listener(app_state={}, workspace=ws)
        mock_cls.assert_not_called()
