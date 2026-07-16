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
        key, text, _ctx = augment_prompt("image", "a red fox")
        assert key == "default"
        assert "a red fox" in text

    def test_lofi_music_template(self) -> None:
        key, text, _ctx = augment_prompt("music", "rainy café", template_key="lofi")
        assert key == "lofi"
        assert "Lo-fi" in text

    def test_scene_style_variables(self) -> None:
        from sevn.agent.subagents.media_prompts import MediaPromptVars

        _key, text, ctx = augment_prompt(
            "image",
            "fox",
            template_key="cinematic",
            vars=MediaPromptVars(scene="forest", style="noir", mood="tense"),
        )
        assert "forest" in text
        assert "noir" in text
        assert ctx["scene"] == "forest"

    def test_unknown_template_falls_back(self) -> None:
        key, _, _ = augment_prompt("image", "test", template_key="nonexistent")
        assert key == "default"

    def test_empty_request_raises(self) -> None:
        with pytest.raises(ValueError, match="user_request must be non-empty"):
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
        with pytest.raises(ValueError, match="unknown video agent template"):
            resolve_video_agent_template("not_a_template")

    def test_list_prompt_templates(self) -> None:
        from sevn.agent.subagents.media_prompts import list_prompt_templates

        templates = list_prompt_templates("image")
        assert len(templates) >= 8
        assert any(t["slug"] == "cinematic" for t in templates)

    def test_list_video_templates_nonempty(self) -> None:
        catalog = list_video_agent_templates()
        assert len(catalog) >= 10
        assert any(entry["slug"] == "pet_pilot" for entry in catalog)
