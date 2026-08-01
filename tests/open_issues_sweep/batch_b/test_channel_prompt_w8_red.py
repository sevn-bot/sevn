"""W8.2 — per-channel and per-topic system prompt overrides (#86 → W9)."""

from __future__ import annotations

from pathlib import Path

from tests.open_issues_sweep.batch_b.conftest import baseline_minimal_workspace


def _assemble_tier_b_prompt(
    content_root: Path,
    cfg: object,
    *,
    channel: str,
    scope_key: str | None,
) -> str:
    from sevn.agent.context_manifest import tier_b_system_prompt_builders
    from sevn.agent.prompt_overlays import resolve_turn_prompt_overlays

    overlays = resolve_turn_prompt_overlays(cfg, channel=channel, scope_key=scope_key)
    parts = tier_b_system_prompt_builders(
        content_root,
        workspace=cfg,
        extra_instructions=overlays.system_prompt,
    )
    return "\n\n".join(parts)


def test_channel_system_prompt_reaches_tier_b_assembly(batch_b_content_root: Path) -> None:
    cfg_doc = baseline_minimal_workspace().model_dump()
    cfg_doc["channels"] = {
        "telegram": {"system_prompt": "CHANNEL SYSTEM: use terse bullet answers."},
    }
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig.model_validate(cfg_doc)
    prompt = _assemble_tier_b_prompt(
        batch_b_content_root,
        cfg,
        channel="telegram",
        scope_key=None,
    )
    assert "CHANNEL SYSTEM: use terse bullet answers." in prompt


def test_topic_config_system_prompt_reaches_tier_b_assembly(batch_b_content_root: Path) -> None:
    cfg_doc = baseline_minimal_workspace().model_dump()
    cfg_doc["channels"] = {
        "telegram": {
            "topics": {
                "42": {
                    "topic_id": 42,
                    "system_prompt": "TOPIC SYSTEM: stay on music catalog tasks only.",
                },
            },
        },
    }
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig.model_validate(cfg_doc)
    prompt = _assemble_tier_b_prompt(
        batch_b_content_root,
        cfg,
        channel="telegram",
        scope_key="forum:100:42",
    )
    assert "TOPIC SYSTEM: stay on music catalog tasks only." in prompt


def test_channel_prompt_isolated_per_channel(batch_b_content_root: Path) -> None:
    cfg_doc = baseline_minimal_workspace().model_dump()
    cfg_doc["channels"] = {
        "telegram": {"system_prompt": "TELEGRAM ONLY"},
        "webchat": {"system_prompt": "WEBCHAT ONLY"},
    }
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig.model_validate(cfg_doc)
    telegram_prompt = _assemble_tier_b_prompt(
        batch_b_content_root,
        cfg,
        channel="telegram",
        scope_key=None,
    )
    webchat_prompt = _assemble_tier_b_prompt(
        batch_b_content_root,
        cfg,
        channel="webchat",
        scope_key=None,
    )
    assert "TELEGRAM ONLY" in telegram_prompt
    assert "TELEGRAM ONLY" not in webchat_prompt
    assert "WEBCHAT ONLY" in webchat_prompt
