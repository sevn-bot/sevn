"""Documentation tooling models for ``sevn.json`` (`docs.readme` pipeline).

Module: sevn.config.sections.docs
Depends: pydantic, typing

Exports:
    ReadmeWorkspaceConfig — ``docs.readme`` subtree.
    DocsWorkspaceSectionConfig — ``docs`` section wrapper.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReadmeWorkspaceConfig(BaseModel):
    """``docs.readme`` README pipeline generator and gate settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    manifest_path: str = "docs/readmes/manifest.toml"
    offline_default: bool = True
    transport: Literal["anthropic", "openai_chat", "openai_responses", "bedrock_converse"] = (
        "anthropic"
    )
    model: str = "claude-sonnet-4-6"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class DocsWorkspaceSectionConfig(BaseModel):
    """``docs`` section for README pipeline tooling."""

    model_config = ConfigDict(extra="forbid")

    readme: ReadmeWorkspaceConfig | None = None
