"""Prompt and template assets.

Module: sevn.agent.templates
Depends: sevn.agent.templates.registry

Exports:
    TemplateEntry — one Markdown file id and content hash.
    load_template_registry — discover Markdown templates.
    registry_version — aggregate registry fingerprint.
"""

from __future__ import annotations

from sevn.agent.templates.registry import TemplateEntry, load_template_registry, registry_version

__all__ = ["TemplateEntry", "load_template_registry", "registry_version"]
