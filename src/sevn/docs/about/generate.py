"""LLM prose generation for about-docs bodies.

Module: sevn.docs.about.generate
Depends: asyncio, json, tomllib, jinja2, sevn.docs.about.model, sevn.docs.about.paths,
    sevn.docs.readme.providers

Exports:
    generate_body — render markdown body via readme providers (offline stub by default).

Examples:
    >>> from datetime import date
    >>> from sevn.docs.about.generate import generate_body
    >>> from sevn.docs.about.model import AboutDoc
    >>> from sevn.docs.readme.providers import OfflineProvider
    >>> doc = AboutDoc(
    ...     id="spec-17-gateway",
    ...     kind="spec",
    ...     title="Gateway",
    ...     status="done",
    ...     owner="Alex",
    ...     summary="Turn spine.",
    ...     last_updated=date(2026, 6, 19),
    ...     parent_prd="prd-01-conversational-experience",
    ...     sources=["src/sevn/gateway/**"],
    ... )
    >>> body = generate_body(doc, OfflineProvider())
    >>> "## Purpose" in body
    True
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, select_autoescape

from sevn.docs.about.paths import prompts_dir
from sevn.docs.readme.providers import (
    LlmProvider,
    OfflineProvider,
    _build_llm_request,
    _extract_completion_text,
)

if TYPE_CHECKING:
    from sevn.docs.about.model import AboutDoc


def generate_body(doc: AboutDoc, provider: OfflineProvider | LlmProvider) -> str:
    """Generate the markdown body for one about-doc.

    Offline providers return a deterministic stub containing the kind's required
    H2 outline. LLM providers render the full body via the per-kind prompt TOML.

    Args:
        doc (AboutDoc): Validated frontmatter.
        provider (OfflineProvider | LlmProvider): Section renderer from
            :func:`sevn.docs.readme.providers.build_provider`.

    Returns:
        str: Markdown body (no frontmatter).

    Examples:
        >>> from datetime import date
        >>> from sevn.docs.about.model import AboutDoc
        >>> from sevn.docs.readme.providers import OfflineProvider
        >>> d = AboutDoc(
        ...     id="prd-00-main",
        ...     kind="prd",
        ...     title="Main",
        ...     status="ready",
        ...     owner="Alex",
        ...     summary="Umbrella.",
        ...     last_updated=date(2026, 6, 19),
        ... )
        >>> "## Problem & Motivation" in generate_body(d, OfflineProvider())
        True
    """
    prompt = _load_kind_prompt(doc.kind)
    outline = _outline_headings(prompt)
    if isinstance(provider, OfflineProvider):
        return _offline_body(doc, outline)
    return asyncio.run(_llm_body(doc, provider, prompt, outline))


def _prompt_name(kind: str) -> str:
    """Return the prompt stem for ``kind``.

    Args:
        kind (str): ``prd`` or ``spec``.

    Returns:
        str: Prompt filename stem.

    Examples:
        >>> _prompt_name("spec")
        'spec.body'
    """
    return f"{kind}.body"


def _load_kind_prompt(kind: str) -> dict[str, Any]:
    """Load the prose prompt TOML for ``kind``.

    Args:
        kind (str): ``prd`` or ``spec``.

    Returns:
        dict[str, Any]: Parsed prompt table.

    Examples:
        >>> "outline" in _load_kind_prompt("spec")
        True
    """
    path = prompts_dir / f"{_prompt_name(kind)}.toml"
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"{path}: prompt must be a TOML table"
        raise ValueError(msg)
    return data


def _outline_headings(prompt: dict[str, Any]) -> list[str]:
    """Return ordered H2 headings from a prompt table.

    Args:
        prompt (dict[str, Any]): Parsed prompt TOML.

    Returns:
        list[str]: Section headings.

    Examples:
        >>> _outline_headings({"outline": ["Purpose", "Behavior"]})
        ['Purpose', 'Behavior']
    """
    raw = prompt.get("outline")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _offline_body(doc: AboutDoc, outline: list[str]) -> str:
    """Return deterministic offline prose containing each required H2.

    Args:
        doc (AboutDoc): Document frontmatter.
        outline (list[str]): Required section headings.

    Returns:
        str: Markdown body.

    Examples:
        >>> from datetime import date
        >>> from sevn.docs.about.model import AboutDoc
        >>> d = AboutDoc(
        ...     id="spec-17-gateway",
        ...     kind="spec",
        ...     title="Gateway",
        ...     status="done",
        ...     owner="Alex",
        ...     summary="Turn spine.",
        ...     last_updated=date(2026, 6, 19),
        ...     parent_prd="prd-01-main",
        ...     sources=["src/sevn/gateway/**"],
        ... )
        >>> "## Purpose" in _offline_body(d, ["Purpose"])
        True
    """
    lines: list[str] = []
    for heading in outline:
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(f"Offline scaffold for {doc.title} ({doc.id}) — {heading}.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _prompt_variables(doc: AboutDoc, outline: list[str]) -> dict[str, Any]:
    """Build template variables for LLM body generation.

    Args:
        doc (AboutDoc): Document frontmatter.
        outline (list[str]): Required H2 headings.

    Returns:
        dict[str, Any]: Variables for the prompt ``user_template``.

    Examples:
        >>> from datetime import date
        >>> from sevn.docs.about.model import AboutDoc
        >>> d = AboutDoc(
        ...     id="spec-17-gateway",
        ...     kind="spec",
        ...     title="Gateway",
        ...     status="done",
        ...     owner="Alex",
        ...     summary="Turn spine.",
        ...     last_updated=date(2026, 6, 19),
        ...     parent_prd="prd-01-main",
        ...     sources=["src/sevn/gateway/**"],
        ... )
        >>> _prompt_variables(d, ["Purpose"])["id"] == "spec-17-gateway"
        True
    """
    return {
        "id": doc.id,
        "kind": doc.kind,
        "title": doc.title,
        "summary": doc.summary,
        "status": doc.status,
        "parent_prd": doc.parent_prd or "",
        "sources_json": json.dumps(list(doc.sources), sort_keys=True),
        "outline_json": json.dumps(outline),
    }


async def _llm_body(
    doc: AboutDoc,
    provider: LlmProvider,
    prompt: dict[str, Any],
    outline: list[str],
) -> str:
    """Render one body via the configured LLM transport and about prompt TOML.

    Args:
        doc (AboutDoc): Document frontmatter.
        provider (LlmProvider): LLM provider from :func:`build_provider`.
        prompt (dict[str, Any]): Parsed per-kind prompt table.
        outline (list[str]): Required H2 headings.

    Returns:
        str: Model-generated markdown body.

    Examples:
        >>> _llm_body.__name__
        '_llm_body'
    """
    system = str(prompt.get("system", "")).strip()
    user_template = str(prompt.get("user_template", "{{ title }}"))
    max_tokens = int(prompt.get("max_tokens", 4096))
    user_content = _render_prompt_user(doc, outline, user_template)
    request = _build_llm_request(
        transport=provider._transport,
        model=provider.config.model,
        system=system,
        user_content=user_content,
        max_tokens=max_tokens,
        temperature=provider.config.temperature,
    )
    response = await provider._transport.complete(request)
    text = _extract_completion_text(provider._transport.name, response)
    return text.strip() + "\n"


def _render_prompt_user(doc: AboutDoc, outline: list[str], template: str) -> str:
    """Render a prompt ``user_template`` with Jinja2 (LLM path).

    Args:
        doc (AboutDoc): Document frontmatter.
        outline (list[str]): Required H2 headings.
        template (str): Jinja2 template string.

    Returns:
        str: Rendered user prompt.

    Examples:
        >>> from datetime import date
        >>> from sevn.docs.about.model import AboutDoc
        >>> d = AboutDoc(
        ...     id="spec-17-gateway",
        ...     kind="spec",
        ...     title="Gateway",
        ...     status="done",
        ...     owner="Alex",
        ...     summary="Turn spine.",
        ...     last_updated=date(2026, 6, 19),
        ...     parent_prd="prd-01-main",
        ...     sources=["src/sevn/gateway/**"],
        ... )
        >>> "Gateway" in _render_prompt_user(d, ["Purpose"], "Title: {{ title }}")
        True
    """
    env = Environment(autoescape=select_autoescape(enabled_extensions=()))
    return env.from_string(template).render(**_prompt_variables(doc, outline))
