"""Resolve README pipeline settings from workspace config and environment.

Module: sevn.docs.readme.settings
Depends: os, sys, sevn.config.sections.docs, sevn.docs.readme.providers

Exports:
    ReadmePipelineSettings — effective operator settings for generation.
    resolve_readme_settings — merge defaults, ``sevn.json``, and env overrides.
    provider_config_from_settings — map to :class:`ReadmeProviderConfig`.
    default_offline_mode — whether non-interactive runs should stay offline.

Examples:
    >>> from sevn.docs.readme.settings import resolve_readme_settings
    >>> s = resolve_readme_settings(None)
    >>> s.manifest_path.endswith("manifest.toml")
    True
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sevn.config.sections.docs import ReadmeWorkspaceConfig
from sevn.docs.readme.providers import ReadmeProviderConfig

if TYPE_CHECKING:
    from sevn.config.sections.root import WorkspaceConfig


@dataclass(frozen=True)
class ReadmePipelineSettings:
    """Effective README pipeline settings for CLI and make targets."""

    enabled: bool = True
    manifest_path: str = "docs/readmes/manifest.toml"
    offline_default: bool = True
    transport: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.2
    proxy_base_url: str | None = None


def resolve_readme_settings(
    workspace: WorkspaceConfig | None,
    *,
    proxy_base_url: str | None = None,
) -> ReadmePipelineSettings:
    """Merge defaults with ``docs.readme`` from workspace config.

        Args:
    workspace (WorkspaceConfig | None): Parsed ``sevn.json``; ``None`` uses defaults.
    proxy_base_url (str | None): Egress proxy origin for LLM mode.

        Returns:
            ReadmePipelineSettings: Effective settings.

        Examples:
            >>> resolve_readme_settings(None).offline_default
            True
    """
    readme_cfg = _readme_section(workspace)
    if readme_cfg is None:
        return ReadmePipelineSettings(proxy_base_url=proxy_base_url)
    return ReadmePipelineSettings(
        enabled=readme_cfg.enabled,
        manifest_path=readme_cfg.manifest_path,
        offline_default=readme_cfg.offline_default,
        transport=readme_cfg.transport,
        model=readme_cfg.model,
        temperature=readme_cfg.temperature,
        proxy_base_url=proxy_base_url,
    )


def provider_config_from_settings(
    settings: ReadmePipelineSettings,
    *,
    offline: bool,
    model: str | None = None,
) -> ReadmeProviderConfig:
    """Map pipeline settings to a section provider config.

        Args:
    settings (ReadmePipelineSettings): Effective pipeline settings.
    offline (bool): When True, use template-only mode.
    model (str | None): Optional model override from CLI ``--model``.

        Returns:
            ReadmeProviderConfig: Provider factory input.

        Examples:
            >>> s = resolve_readme_settings(None)
            >>> provider_config_from_settings(s, offline=True).offline
            True
    """
    return ReadmeProviderConfig(
        offline=offline,
        model=(model or settings.model).strip(),
        transport=settings.transport,
        temperature=settings.temperature,
        proxy_base_url=settings.proxy_base_url,
    )


def default_offline_mode(settings: ReadmePipelineSettings) -> bool:
    """Return whether generation should default to offline (CI / non-interactive).

        Args:
    settings (ReadmePipelineSettings): Effective pipeline settings.

        Returns:
            bool: True when offline is the default for this invocation.

        Examples:
            >>> default_offline_mode(resolve_readme_settings(None))
            True
    """
    if os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if not sys.stdin.isatty():
        return True
    return settings.offline_default


def _readme_section(workspace: WorkspaceConfig | None) -> ReadmeWorkspaceConfig | None:
    """Extract ``docs.readme`` from a workspace config document.

        Args:
    workspace (WorkspaceConfig | None): Parsed workspace.

        Returns:
            ReadmeWorkspaceConfig | None: Readme subtree when present.

        Examples:
            >>> _readme_section(None) is None
            True
    """
    if workspace is None:
        return None
    docs = workspace.docs
    if docs is None or docs.readme is None:
        return None
    return docs.readme
