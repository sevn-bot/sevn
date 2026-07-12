"""Tests for README pipeline settings resolution."""

from __future__ import annotations

from sevn.config.sections.docs import DocsWorkspaceSectionConfig, ReadmeWorkspaceConfig
from sevn.config.sections.root import WorkspaceConfig
from sevn.docs.readme.settings import resolve_readme_settings


def test_resolve_readme_settings_from_workspace() -> None:
    ws = WorkspaceConfig.minimal(
        docs=DocsWorkspaceSectionConfig(
            readme=ReadmeWorkspaceConfig(
                model="claude-opus-4-6",
                offline_default=False,
            )
        )
    )
    settings = resolve_readme_settings(ws)
    assert settings.model == "claude-opus-4-6"
    assert settings.offline_default is False
