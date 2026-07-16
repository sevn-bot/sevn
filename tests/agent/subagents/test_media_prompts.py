"""Tests for media prompt augmentation and Video Agent catalog."""

from __future__ import annotations

import pytest

from sevn.agent.subagents.media_prompts import (
    augment_prompt,
    list_video_agent_templates,
    resolve_video_agent_template,
)


class TestAugmentPrompt:
    """Prompt template augmentation."""

    def test_default_image(self) -> None:
        key, text = augment_prompt("image", "a red fox")
        assert key == "default"
        assert "a red fox" in text
        assert "high-quality image" in text

    def test_lofi_music_template(self) -> None:
        key, text = augment_prompt("music", "rainy café", template_key="lofi")
        assert key == "lofi"
        assert "Lo-fi study beat" in text

    def test_unknown_template_falls_back(self) -> None:
        key, _ = augment_prompt("image", "test", template_key="nonexistent")
        assert key == "default"

    def test_empty_request_raises(self) -> None:
        with pytest.raises(ValueError):
            augment_prompt("image", "  ")


class TestVideoAgentTemplates:
    """Video Agent template catalog."""

    def test_resolve_by_slug(self) -> None:
        t = resolve_video_agent_template("diving")
        assert t.template_id == "392747428568649728"

    def test_resolve_by_id(self) -> None:
        t = resolve_video_agent_template("393769180141805569")
        assert t.slug == "run_for_life"

    def test_unknown_template_raises(self) -> None:
        with pytest.raises(ValueError):
            resolve_video_agent_template("not_a_template")

    def test_list_templates_nonempty(self) -> None:
        catalog = list_video_agent_templates()
        assert len(catalog) >= 10
        assert any(entry["slug"] == "pet_pilot" for entry in catalog)
