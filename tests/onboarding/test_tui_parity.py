"""TUI parity with comprehensive web onboarding (W11)."""

from __future__ import annotations

from sevn.onboarding.tui import _STEP_LABELS, OnboardApp, _merged_from_app
from sevn.onboarding.web_app import _merge_wizard_payload


def test_tui_step_labels_match_comprehensive_flow() -> None:
    assert len(_STEP_LABELS) == 13
    assert _STEP_LABELS[2].endswith("My Sevn.bot")
    assert _STEP_LABELS[4].endswith("Capabilities")
    assert _STEP_LABELS[8].endswith("Personality")


def test_tui_merge_aligns_with_web_merge_wizard_payload() -> None:
    app = OnboardApp()
    app.applied_profile = "good_value_osx"
    app.fields.update(
        {
            "onboarding.applied_profile": "good_value_osx",
            "agent.display_name": "Nova",
            "my_sevn.repo_url": "https://github.com/sevn-bot/sevn",
            "providers.tier_default.triager": "anthropic/claude-sonnet-4-6",
            "gateway.queue_mode": "steer",
            "onboarding.personality.name": "Alex",
            "onboarding.personality.vibe": "calm co-pilot",
        }
    )
    tui_merged = _merged_from_app(app)
    web_merged = _merge_wizard_payload({"fields": app.fields}, profile_id=app.applied_profile)
    assert tui_merged["agent"]["display_name"] == web_merged["agent"]["display_name"] == "Nova"
    assert tui_merged["gateway"]["queue_mode"] == web_merged["gateway"]["queue_mode"] == "steer"
    assert (
        tui_merged["onboarding"]["personality"]["name"]
        == web_merged["onboarding"]["personality"]["name"]
        == "Alex"
    )
    assert (
        tui_merged["providers"]["tier_default"]["triager"]
        == web_merged["providers"]["tier_default"]["triager"]
    )
