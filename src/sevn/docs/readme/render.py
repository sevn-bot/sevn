"""Jinja2 rendering and README generation pipeline (Wave 1 preview + Wave 2 gen).

Module: sevn.docs.readme.render
Depends: jinja2, pathlib, sevn.docs.readme.fixtures, sevn.docs.readme.profiles,
    sevn.docs.readme.fingerprint, sevn.docs.readme.manifest, sevn.docs.readme.model,
    sevn.docs.readme.providers, sevn.docs.readme.scanner

Exports:
    jinja_env — configured Jinja2 environment for README templates.
    render_profile — render markdown for one profile + context dict.
    render_all_fixtures — render every profile; return slug → markdown mapping.
    validate_rendered_markdown — GitHub-safe structural checks for rendered output.
    render_readme_markdown — scan → sections → assemble → markdown string.
    write_readme — render and write output + update fingerprint store.
    render_manifest_slug — render one README by manifest slug.

Examples:
    >>> from sevn.docs.readme.render import render_profile
    >>> md = render_profile("subsystem", {"slug": "gateway", "profile": "subsystem",
    ...     "title": "Gateway", "role": "x", "summary": "s", "spec_path": "specs/17-gateway.md",
    ...     "source_dir": "src/sevn/gateway/", "level1": "a", "level2": "b", "level3": "c",
    ...     "references": []})
    >>> "## Level 1" in md
    True
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sevn.docs.readme import paths
from sevn.docs.readme.catalog import build_index_rows, build_subsystem_map_rows
from sevn.docs.readme.fingerprint import (
    compute_digest,
    default_fingerprints_path,
    load_fingerprints,
    save_fingerprints,
    upsert_entry,
)
from sevn.docs.readme.fixtures import FIXTURE_CONTEXTS
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest, get_entry, load_manifest
from sevn.docs.readme.model import (
    ReadmeAssembly,
    assemble_template_context,
    format_module_symbols_for_prompt,
    format_path_list,
    merge_section,
    offline_sections,
)
from sevn.docs.readme.profiles import PROFILE_TEMPLATES
from sevn.docs.readme.providers import (
    OfflineProvider,
    ReadmeProviderConfig,
    SectionProvider,
    build_provider,
)
from sevn.docs.readme.scanner import scan_repo_context

templates_dir = paths.templates_dir
prompts_dir = paths.prompts_dir

_TAG_ATTR_FORBIDDEN = re.compile(r"\b(style|class|on\w+)\s*=", re.IGNORECASE)
_FORBIDDEN_TAG = re.compile(
    r"<\s*(script|iframe|style|form|input)\b|"
    r"href\s*=\s*[\"']javascript:",
    re.IGNORECASE,
)


def _has_forbidden_html(markdown: str) -> bool:
    """Return True when markdown contains GitHub-forbidden HTML (§E).

        Args:
    markdown (str): Rendered README body.

        Returns:
            bool: True when forbidden constructs are present.

        Examples:
            >>> _has_forbidden_html('<div class="x">ok</div>')
            True
            >>> _has_forbidden_html('[b]: https://img.shields.io/badge/x?style=for-the-badge')
            False
    """
    if _FORBIDDEN_TAG.search(markdown):
        return True
    return any(_TAG_ATTR_FORBIDDEN.search(tag) for tag in re.findall(r"<[^>]+>", markdown))


_IMAGE_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|srcset=\"([^\"]+)\"|src=\"([^\"]+)\"")


def jinja_env() -> Environment:
    """Return a Jinja2 environment for README templates.

    Returns:
        Environment: Loader rooted at ``templates_dir``; autoescape enabled.

    Examples:
        >>> env = jinja_env()
        >>> env.get_template("root.md.j2") is not None
        True
    """
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_profile(profile: str, context: dict[str, Any]) -> str:
    """Render one README markdown string from profile name and context.

        Args:
    profile (str): §C0 profile key (``root``, ``subsystem``, …).
    context (dict[str, Any]): Template variables (slug, title, summary, …).

        Returns:
            str: Rendered GitHub-safe markdown.

        Raises:
            KeyError: When ``profile`` is unknown.
            jinja2.TemplateNotFound: When the mapped template file is missing.

        Examples:
            >>> text = render_profile("freeform", FIXTURE_CONTEXTS["freeform"])
            >>> "Summary" in text
            True
    """
    template_name = PROFILE_TEMPLATES[profile]
    env = jinja_env()
    template = env.get_template(template_name)
    return template.render(**context)


def _collect_image_refs(markdown: str) -> list[str]:
    """Extract repo-relative image paths from rendered markdown.

        Args:
    markdown (str): Rendered README body.

        Returns:
            list[str]: Deduplicated paths (http(s) URLs excluded).

        Examples:
            >>> _collect_image_refs('![x](docs/brand/assets/hero.png)')
            ['docs/brand/assets/hero.png']
    """
    refs: list[str] = []
    for match in _IMAGE_REF.finditer(markdown):
        for group in match.groups():
            if group and not group.startswith(("http://", "https://", "#")):
                refs.append(group.strip())
    return list(dict.fromkeys(refs))


def validate_rendered_markdown(markdown: str, *, repo_root: Path) -> list[str]:
    """Return structural validation errors for rendered markdown.

        Args:
    markdown (str): Rendered README body.
    repo_root (Path): Repository root for image path resolution.

        Returns:
            list[str]: Human-readable errors; empty when valid.

        Examples:
            >>> errs = validate_rendered_markdown("# ok\\n", repo_root=Path("."))
            >>> errs
            []
    """
    errors: list[str] = []
    if _has_forbidden_html(markdown):
        errors.append("forbidden HTML detected (script/iframe/style/class/javascript:)")
    for ref in _collect_image_refs(markdown):
        candidate = repo_root / ref
        if not candidate.is_file():
            errors.append(f"missing image: {ref}")
    return errors


def render_all_fixtures(*, repo_root: Path | None = None) -> dict[str, str]:
    """Render every §C0 profile with deterministic fixture data.

        Args:
    repo_root (Path | None): When set, validate image refs against this root.

        Returns:
            dict[str, str]: Profile name → rendered markdown.

        Raises:
            ValueError: When validation fails for any rendered profile.

        Examples:
            >>> outputs = render_all_fixtures()
            >>> set(outputs) == set(PROFILE_TEMPLATES)
            True
    """
    outputs: dict[str, str] = {}
    for profile in PROFILE_TEMPLATES:
        context = FIXTURE_CONTEXTS[profile]
        markdown = render_profile(profile, context)
        if repo_root is not None:
            errors = validate_rendered_markdown(markdown, repo_root=repo_root)
            if errors:
                msg = f"{profile}: " + "; ".join(errors)
                raise ValueError(msg)
        outputs[profile] = markdown
    return outputs


_SUBSYSTEM_SECTION_PROMPTS: tuple[tuple[str, str], ...] = (
    ("summary", "summary"),
    ("level1", "overview"),
    ("level2", "how-it-works"),
    ("level3", "deep-dive"),
)

_ROOT_SECTION_PROMPTS: tuple[tuple[str, str], ...] = (
    ("value_prop", "root-valueprop"),
    ("highlights", "highlights"),
)

_GUIDE_SECTION_PROMPTS: tuple[tuple[str, str], ...] = (("steps", "guide-steps"),)

_CATALOG_SECTION_PROMPTS: tuple[tuple[str, str], ...] = (("table_intro", "catalog-table"),)

_PROFILE_LLM_PROMPTS: dict[str, tuple[tuple[str, str], ...]] = {
    "subsystem": _SUBSYSTEM_SECTION_PROMPTS,
    "root": _ROOT_SECTION_PROMPTS,
    "guide": _GUIDE_SECTION_PROMPTS,
    "catalog": _CATALOG_SECTION_PROMPTS,
}


async def render_readme_markdown(
    *,
    repo_root: Path,
    entry: ReadmeEntry,
    provider: SectionProvider | None = None,
    config: ReadmeProviderConfig | None = None,
    manifest: ReadmeManifest | None = None,
    fingerprints_path: Path | None = None,
) -> str:
    """Generate one README markdown string (offline or LLM section polish).

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row to render.
    provider (SectionProvider | None): Optional provider; defaults from ``config``.
    config (ReadmeProviderConfig | None): Provider settings when ``provider`` omitted.
    manifest (ReadmeManifest | None): Full manifest for root/index catalog enrichment.
    fingerprints_path (Path | None): Fingerprint store for catalog staleness rows.

        Returns:
            str: Rendered GitHub-safe markdown.

        Examples:
            >>> import asyncio
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import get_entry, load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> e = get_entry(m, "gateway")
            >>> md = asyncio.run(render_readme_markdown(repo_root=_P("."), entry=e))
            >>> "## Level 1" in md
            True
    """
    scan = scan_repo_context(repo_root, entry)
    if manifest is not None:
        scan = _enrich_scan_for_catalog(
            repo_root,
            entry,
            scan,
            manifest=manifest,
            fingerprints_path=fingerprints_path,
        )
    assembly = await _build_assembly(entry, scan, provider=provider, config=config)
    context = assemble_template_context(assembly, scan, repo_root=repo_root)
    return render_profile(entry.profile, context)


async def write_readme(
    *,
    repo_root: Path,
    entry: ReadmeEntry,
    provider: SectionProvider | None = None,
    config: ReadmeProviderConfig | None = None,
    fingerprints_path: Path | None = None,
    manifest: ReadmeManifest | None = None,
) -> Path:
    """Render a README, write ``entry.output``, and stamp fingerprints.

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row.
    provider (SectionProvider | None): Optional section provider.
    config (ReadmeProviderConfig | None): Provider settings when ``provider`` omitted.
    fingerprints_path (Path | None): Override ``docs/readmes/_fingerprints.json``.
    manifest (ReadmeManifest | None): Full manifest for root/index catalog enrichment.

        Returns:
            Path: Written README path (absolute).

        Examples:
            >>> import asyncio
            >>> import tempfile
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> td = _P(tempfile.mkdtemp())
            >>> (td / "src/sevn/x").mkdir(parents=True)
            >>> _ = (td / "src/sevn/x/a.py").write_text("x=1\\n", encoding="utf-8")
            >>> e = ReadmeEntry("x", "X", "S", "freeform", "d", "out.md", ("src/sevn/x/**",), ())
            >>> out = asyncio.run(write_readme(repo_root=td, entry=e))
            >>> out.is_file()
            True
    """
    markdown = await render_readme_markdown(
        repo_root=repo_root,
        entry=entry,
        provider=provider,
        config=config,
        manifest=manifest,
        fingerprints_path=fingerprints_path,
    )
    output_path = repo_root / entry.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    fp_path = fingerprints_path or default_fingerprints_path(repo_root)
    store = load_fingerprints(fp_path)
    digest = compute_digest(repo_root, entry.source_globs)
    upsert_entry(store, slug=entry.slug, digest=digest, source_globs=entry.source_globs)
    save_fingerprints(fp_path, store)
    return output_path


async def render_manifest_slug(
    *,
    repo_root: Path,
    manifest_path: Path,
    slug: str,
    config: ReadmeProviderConfig | None = None,
) -> str:
    """Render one README by manifest slug.

        Args:
    repo_root (Path): Repository root.
    manifest_path (Path): Path to ``manifest.toml``.
    slug (str): Entry slug.
    config (ReadmeProviderConfig | None): Provider settings.

        Returns:
            str: Rendered markdown.

        Examples:
            >>> import asyncio
            >>> from pathlib import Path as _P
            >>> md = asyncio.run(render_manifest_slug(
            ...     repo_root=_P("."), manifest_path=_P("docs/readmes/manifest.toml"), slug="gateway"))
            >>> "> **Summary.**" in md
            True
    """
    manifest = load_manifest(manifest_path)
    entry = get_entry(manifest, slug)
    return await render_readme_markdown(
        repo_root=repo_root,
        entry=entry,
        config=config,
        manifest=manifest,
    )


def _enrich_scan_for_catalog(
    repo_root: Path,
    entry: ReadmeEntry,
    scan: dict[str, Any],
    *,
    manifest: ReadmeManifest | None,
    fingerprints_path: Path | None,
) -> dict[str, Any]:
    """Inject catalog rows into scan context for root/index profiles.

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row being rendered.
    scan (dict[str, Any]): Base scanner context.
    manifest (ReadmeManifest | None): Full manifest for catalog rows.
    fingerprints_path (Path | None): Fingerprint store override.

        Returns:
            dict[str, Any]: Scan dict, possibly enriched.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import get_entry, load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> e = get_entry(m, "root")
            >>> out = _enrich_scan_for_catalog(_P("."), e, {"title": "R"}, manifest=m, fingerprints_path=None)
            >>> "subsystem_entries" in out
            True
    """
    if manifest is None:
        return scan
    enriched = dict(scan)
    if entry.profile == "root":
        enriched["subsystem_entries"] = build_subsystem_map_rows(
            repo_root,
            manifest,
            fingerprints_path=fingerprints_path,
        )
    elif entry.profile == "index":
        enriched["index_entries"] = build_index_rows(
            repo_root,
            manifest,
            fingerprints_path=fingerprints_path,
            embed_output=entry.output,
        )
    return enriched


def _provider_from_config(
    provider: SectionProvider | None,
    config: ReadmeProviderConfig | None,
) -> SectionProvider:
    """Resolve a section provider from explicit instance or config.

        Args:
    provider (SectionProvider | None): Explicit provider instance.
    config (ReadmeProviderConfig | None): Config when ``provider`` is omitted.

        Returns:
            SectionProvider: Offline or LLM provider.

        Examples:
            >>> isinstance(_provider_from_config(None, None), OfflineProvider)
            True
    """
    if provider is not None:
        return provider
    cfg = config or ReadmeProviderConfig(offline=True)
    return build_provider(cfg)


async def _build_assembly(
    entry: ReadmeEntry,
    scan: dict[str, Any],
    *,
    provider: SectionProvider | None,
    config: ReadmeProviderConfig | None,
) -> ReadmeAssembly:
    """Build section bodies offline, optionally polishing via LLM provider.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.
    provider (SectionProvider | None): Optional explicit provider.
    config (ReadmeProviderConfig | None): Provider config fallback.

        Returns:
            ReadmeAssembly: Section map for template assembly.

        Examples:
            >>> import asyncio
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import get_entry, load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> e = get_entry(m, "gateway")
            >>> s = scan_repo_context(_P("."), e)
            >>> asm = asyncio.run(_build_assembly(e, s, provider=None, config=None))
            >>> "level1" in asm.sections
            True
    """
    assembly = offline_sections(entry, scan)
    resolved = _provider_from_config(provider, config)
    if isinstance(resolved, OfflineProvider):
        return assembly
    prompt_map = _PROFILE_LLM_PROMPTS.get(entry.profile)
    if prompt_map is None:
        return assembly
    return await _llm_profile_assembly(assembly, scan, resolved, prompt_map)


async def _llm_profile_assembly(
    base: ReadmeAssembly,
    scan: dict[str, Any],
    provider: SectionProvider,
    prompt_map: tuple[tuple[str, str], ...],
) -> ReadmeAssembly:
    """Polish profile sections via LLM section prompts.

        Args:
    base (ReadmeAssembly): Offline baseline sections.
    scan (dict[str, Any]): Scanner context.
    provider (SectionProvider): LLM provider.
    prompt_map (tuple[tuple[str, str], ...]): Section key → prompt stem pairs.

        Returns:
            ReadmeAssembly: Assembly with LLM-polished section bodies.

        Examples:
            >>> import asyncio
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("src/**",), ())
            >>> base = ReadmeAssembly(e, {"summary": "S", "level1": "a"})
            >>> polished = asyncio.run(
            ...     _llm_profile_assembly(base, {"title": "G"}, OfflineProvider(), (("summary", "summary"),))
            ... )
            >>> polished.sections["summary"] == "S"
            True
    """
    assembly = base
    variables = _llm_prompt_variables(base, scan)
    for section_key, prompt_name in prompt_map:
        content = await provider.render_section(prompt_name, variables)
        if not content.strip():
            continue
        polished = content.strip()
        if section_key == "highlights":
            bullets = _parse_markdown_bullets(polished)
            if bullets:
                merged = dict(assembly.sections)
                merged["highlights"] = bullets
                assembly = ReadmeAssembly(entry=assembly.entry, sections=merged)
            continue
        if section_key == "steps":
            steps = _parse_guide_steps(polished)
            if steps:
                merged = dict(assembly.sections)
                merged["steps"] = steps
                assembly = ReadmeAssembly(entry=assembly.entry, sections=merged)
            continue
        assembly = merge_section(assembly, name=section_key, content=polished)
    return assembly


def _llm_prompt_variables(base: ReadmeAssembly, scan: dict[str, Any]) -> dict[str, Any]:
    """Build shared LLM prompt variables from scan context and offline sections.

        Args:
    base (ReadmeAssembly): Offline baseline assembly.
    scan (dict[str, Any]): Scanner context.

        Returns:
            dict[str, Any]: Variables for section prompt templates.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("src/**",), ())
            >>> vars = _llm_prompt_variables(ReadmeAssembly(e, {"summary": "S"}), {"title": "G"})
            >>> vars["title"]
            'G'
    """
    context_json = json.dumps(
        {
            "source_files": scan.get("source_files", [])[:20],
            "specs": scan.get("specs", []),
            "graphify": scan.get("graphify"),
        },
        sort_keys=True,
    )
    items = base.sections.get("items", [])
    if not isinstance(items, list):
        items = []
    subsystem_entries = scan.get("subsystem_entries", base.sections.get("subsystem_entries", []))
    subsystem_slugs = [
        str(row.get("slug", row.get("title", "")))
        for row in subsystem_entries
        if isinstance(row, dict)
    ]
    intro_lines = scan.get("intro_lines", base.sections.get("intro_lines", []))
    intro_hint = intro_lines[0] if isinstance(intro_lines, list) and intro_lines else ""
    architecture_bullets = base.sections.get("architecture_bullets", [])
    architecture_hint = (
        architecture_bullets[0]
        if isinstance(architecture_bullets, list) and architecture_bullets
        else ""
    )
    steps = base.sections.get("steps", [])
    return {
        "title": scan.get("title", base.entry.title),
        "summary": base.sections.get("summary", base.entry.summary),
        "profile": base.entry.profile,
        "specs": list(scan.get("specs", base.entry.specs)),
        "source_globs": scan.get("source_globs", []),
        "source_excerpt": scan.get("source_excerpt", ""),
        "spec_excerpt": scan.get("spec_excerpt", ""),
        "module_symbols": format_module_symbols_for_prompt(scan.get("module_symbols", {})),
        "modules_hint": format_path_list(list(scan.get("source_py_files", []))[:6]),
        "context_json": context_json,
        "value_prop": base.sections.get("value_prop", base.entry.summary),
        "highlights": base.sections.get("highlights", []),
        "intro_hint": intro_hint,
        "architecture_hint": architecture_hint,
        "subsystem_slugs": ", ".join(subsystem_slugs),
        "items_json": json.dumps(items[:20], sort_keys=True),
        "steps_json": json.dumps(steps, sort_keys=True),
    }


def _parse_markdown_bullets(text: str) -> list[str]:
    """Parse markdown list items into plain bullet strings.

        Args:
    text (str): Markdown list body.

        Returns:
            list[str]: Bullet text without list markers.

        Examples:
            >>> _parse_markdown_bullets("- One\\n- Two")
            ['One', 'Two']
    """
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            bullets.append(stripped[2:].strip())
    return bullets


def _parse_guide_steps(text: str) -> list[dict[str, str]]:
    """Parse ``##`` headings from guide LLM output into step dicts.

        Args:
    text (str): Markdown with one or more ``##`` sections.

        Returns:
            list[dict[str, str]]: Step dicts with ``heading`` and ``body`` keys.

        Examples:
            >>> _parse_guide_steps("## Setup\\nRun make setup.\\n\\n## Verify\\nRun doctor.")
            [{'heading': 'Setup', 'body': 'Run make setup.'}, {'heading': 'Verify', 'body': 'Run doctor.'}]
    """
    steps: list[dict[str, str]] = []
    current_heading: str | None = None
    body_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                steps.append({"heading": current_heading, "body": "\n".join(body_lines).strip()})
            current_heading = line.removeprefix("## ").strip()
            body_lines = []
            continue
        if current_heading is not None:
            body_lines.append(line)
    if current_heading is not None:
        steps.append({"heading": current_heading, "body": "\n".join(body_lines).strip()})
    return steps


async def _llm_subsystem_assembly(
    base: ReadmeAssembly,
    scan: dict[str, Any],
    provider: SectionProvider,
) -> ReadmeAssembly:
    """Polish subsystem tiers via LLM section prompts.

        Args:
    base (ReadmeAssembly): Offline baseline sections.
    scan (dict[str, Any]): Scanner context.
    provider (SectionProvider): LLM provider.

        Returns:
            ReadmeAssembly: Assembly with LLM-polished tier bodies.

        Examples:
            >>> import asyncio
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("src/**",), ())
            >>> base = ReadmeAssembly(e, {"summary": "S", "level1": "a"})
            >>> polished = asyncio.run(_llm_subsystem_assembly(base, {"title": "G"}, OfflineProvider()))
            >>> polished.sections["summary"] == "S"
            True
    """
    return await _llm_profile_assembly(base, scan, provider, _SUBSYSTEM_SECTION_PROMPTS)
