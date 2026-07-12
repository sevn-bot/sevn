"""Web wizard step order and capabilities tab (onboarding comprehensive setup W3)."""

from __future__ import annotations

from importlib import resources

from sevn.onboarding.web_app import _config_from_fields, _merge_wizard_payload


def test_base_steps_capabilities_before_channels() -> None:
    """``BASE_STEPS`` lists capabilities after model and before channels."""
    app_js = (resources.files("sevn.onboarding") / "web_wizard" / "app.js").read_text(
        encoding="utf-8"
    )
    assert '"capabilities"' in app_js
    assert '"features"' not in app_js
    model_idx = app_js.index('"model"')
    cap_idx = app_js.index('"capabilities"')
    ch_idx = app_js.index('"channels"')
    assert model_idx < cap_idx < ch_idx


def test_base_steps_personality_before_validate() -> None:
    """``BASE_STEPS`` lists personality after tunnel and before validate."""
    app_js = (resources.files("sevn.onboarding") / "web_wizard" / "app.js").read_text(
        encoding="utf-8"
    )
    tunnel_idx = app_js.index('"tunnel"')
    personality_idx = app_js.index('"personality"')
    validate_idx = app_js.index('"validate"')
    assert tunnel_idx < personality_idx < validate_idx
    assert "personality:[]," in app_js.replace(" ", "")


def test_wizard_html_personality_step() -> None:
    """Packaged HTML exposes optional personality step before validate."""
    html = (resources.files("sevn.onboarding") / "web_wizard" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'data-step="personality"' in html
    assert 'data-field-id="onboarding.personality.name"' in html
    assert 'data-field-id="onboarding.personality.style"' in html
    assert 'id="personality_preferences_options"' in html
    assert 'id="personality_timezone"' in html
    personality_pos = html.index('data-step="personality"')
    validate_pos = html.index('data-step="validate"')
    assert personality_pos < validate_pos


def test_wizard_html_capabilities_step_replaces_features() -> None:
    """Packaged HTML exposes capabilities step; workspace has no queue_mode select."""
    html = (resources.files("sevn.onboarding") / "web_wizard" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'data-step="capabilities"' in html
    assert 'data-step="features"' not in html
    assert 'data-field-id="gateway.queue_mode"' not in html
    assert 'id="capabilities-groups"' in html


def test_merge_wizard_payload_capability_fields() -> None:
    """Capability manifest config paths merge into sevn.json via wizard fields."""
    merged = _merge_wizard_payload(
        {
            "fields": {
                "gateway.queue_mode": "steer",
                "witchcraft_enabled": True,
                "skills.computer_use.enabled": False,
            }
        },
        profile_id=None,
    )
    assert merged["gateway"]["queue_mode"] == "steer"
    assert merged["witchcraft_enabled"] is True
    assert merged["skills"]["computer_use"]["enabled"] is False


def test_config_from_fields_checkbox_false_persists() -> None:
    """Unchecked capability checkboxes write explicit false values."""
    doc = _config_from_fields({"memory.lcm.enabled": False})
    assert doc["memory"]["lcm"]["enabled"] is False


def test_config_from_fields_personality_nested() -> None:
    """Personality wizard fields merge into ``onboarding.personality``."""
    doc = _config_from_fields(
        {
            "onboarding.personality.name": "Alex",
            "onboarding.personality.style": "Brief and direct",
            "onboarding.personality.vibe": "calm",
        }
    )
    assert doc["onboarding"]["personality"]["name"] == "Alex"
    assert doc["onboarding"]["personality"]["style"] == "Brief and direct"
    assert doc["onboarding"]["personality"]["vibe"] == "calm"


def test_config_from_fields_capability_selections_flat_keys() -> None:
    """Capability wizard paths store flat keys under ``capability_selections``."""
    doc = _config_from_fields(
        {
            "onboarding.capability_selections.extra.web_fetch": True,
            "onboarding.capability_selections.extra.web_extract": False,
        }
    )
    selections = doc["onboarding"]["capability_selections"]
    assert selections == {"extra.web_fetch": True, "extra.web_extract": False}
