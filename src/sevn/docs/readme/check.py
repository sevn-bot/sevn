"""README validation and staleness checks (`sevn readme check`, `make readme-check`).

Module: sevn.docs.readme.check
Depends: pathlib, re, sevn.docs.readme.catalog, sevn.docs.readme.fingerprint,
    sevn.docs.readme.links, sevn.docs.readme.manifest, sevn.docs.readme.profile_schemas,
    sevn.docs.readme.render, sevn.docs.readme.symbol_refs, sevn.docs.readme.verify

Exports:
    CheckResult — aggregated errors and warnings from a check run.
    check_readme_tree — validate manifest READMEs (structure + staleness).

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.manifest import load_manifest
    >>> m = load_manifest(Path("docs/readmes/manifest.toml"))
    >>> result = check_readme_tree(Path("."), m)
    >>> isinstance(result.errors, list)
    True
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sevn.docs.readme.catalog import build_catalog_rows
from sevn.docs.readme.fingerprint import default_fingerprints_path
from sevn.docs.readme.links import validate_markdown_links
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest
from sevn.docs.readme.profile_schemas import ProfileSchema, get_profile_schema
from sevn.docs.readme.render import validate_rendered_markdown
from sevn.docs.readme.symbol_refs import (
    extract_curated_prose_section,
    extract_level3_section,
    validate_path_refs,
    validate_symbol_refs,
)
from sevn.docs.readme.templates import (
    resolve_template_path,
    validate_against_template,
)
from sevn.docs.readme.verify import lint_summaries

_SUMMARY_MARKERS = ("> **Summary.**", "## Summary")
_PLACEHOLDER_LABEL = re.compile(r"PLACEHOLDER", re.IGNORECASE)
_PLACEHOLDER_LINE_MARKERS = ("![", "<img", "srcset=", "docs/brand/assets/")
_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_TABLE_ROW = re.compile(r"^\|.+\|.+\|", re.MULTILINE)


@dataclass
class CheckResult:
    """Aggregated README check outcome."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when no errors were recorded.

        Returns:
            bool: True when ``errors`` is empty.

        Examples:
            >>> CheckResult().ok
            True
            >>> not CheckResult(errors=["x"]).ok
            True
        """
        return not self.errors


def check_readme_tree(
    repo_root: Path,
    manifest: ReadmeManifest,
    *,
    fingerprints_path: Path | None = None,
) -> CheckResult:
    """Validate README files for existence, profile schema, links, and staleness.

        Args:
    repo_root (Path): Repository root.
    manifest (ReadmeManifest): Loaded manifest.
    fingerprints_path (Path | None): Override ``_fingerprints.json`` path.

        Returns:
            CheckResult: Errors (fail gate) and warnings (placeholders).

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> isinstance(check_readme_tree(_P("."), m), CheckResult)
            True
    """
    repo_root = repo_root.resolve()
    fp_path = fingerprints_path or default_fingerprints_path(repo_root)
    result = CheckResult()

    catalog = build_catalog_rows(repo_root, manifest, fingerprints_path=fp_path)
    status_by_slug = {row.slug: row.status for row in catalog}

    for err in lint_summaries(manifest, repo_root):
        result.errors.append(err)

    for entry in manifest.entries:
        output = repo_root / entry.output
        if not output.is_file():
            result.errors.append(f"{entry.slug}: missing README at {entry.output}")
            continue
        text = output.read_text(encoding="utf-8")
        schema = get_profile_schema(entry.profile)
        _check_profile(entry, text, schema, result)
        for err in validate_rendered_markdown(text, repo_root=repo_root):
            result.errors.append(f"{entry.slug}: {err}")
        for err in validate_markdown_links(text, output, repo_root):
            result.errors.append(f"{entry.slug}: {err}")
        _check_path_and_symbol_refs(entry, text, schema, repo_root, result)
        _check_template(entry, text, repo_root, result)
        if _has_placeholder_warning(text):
            result.warnings.append(f"{entry.slug}: contains PLACEHOLDER asset label (TODO)")
        status = status_by_slug.get(entry.slug)
        if status == "stale":
            if entry.curated:
                hint = f"sevn readme fingerprint {entry.slug}"
            else:
                hint = f"sevn readme update {entry.slug}"
            result.errors.append(f"{entry.slug}: stale source fingerprint — run `{hint}`")

    return result


def _check_profile(
    entry: ReadmeEntry,
    text: str,
    schema: ProfileSchema,
    result: CheckResult,
) -> None:
    """Apply profile-specific structural checks.

        Args:
    entry (ReadmeEntry): Manifest row.
    text (str): README body.
    schema (ProfileSchema): §C0 schema for the profile.
    result (CheckResult): Mutable result accumulator.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> from sevn.docs.readme.profile_schemas import get_profile_schema
            >>> r = CheckResult()
            >>> e = ReadmeEntry("g", "G", "S", "freeform", "g", "o.md", ("a",), ())
            >>> _check_profile(e, "> **Summary.** ok", get_profile_schema("freeform"), r)
            >>> r.errors
            []
    """
    if schema.requires_summary:
        _check_summary(entry.slug, text, result)
    for heading in schema.required_headings:
        if not _has_heading(text, heading):
            result.errors.append(f"{entry.slug}: missing required heading `{heading}`")
    if schema.requires_table and not _TABLE_ROW.search(text):
        result.errors.append(f"{entry.slug}: missing generated entry table")
    if schema.requires_step_sections:
        _check_guide_steps(entry.slug, text, result)
    if entry.profile == "index" and not _strip_leading_html_comments(text).startswith("#"):
        result.errors.append(f"{entry.slug}: missing title heading (`#`)")


def _check_summary(slug: str, text: str, result: CheckResult) -> None:
    """Require a Summary block at the top of every README.

        Args:
    slug (str): Manifest slug for error messages.
    text (str): README body.
    result (CheckResult): Mutable result accumulator.

        Examples:
            >>> r = CheckResult()
            >>> _check_summary("x", "> **Summary.** ok", r)
            >>> r.errors
            []
    """
    if any(marker in text for marker in _SUMMARY_MARKERS):
        return
    result.errors.append(f"{slug}: missing Summary block (> **Summary.** or ## Summary)")


def _check_guide_steps(slug: str, text: str, result: CheckResult) -> None:
    """Require at least one task/step ``##`` section in guide profiles.

        Args:
    slug (str): Manifest slug.
    text (str): README body.
    result (CheckResult): Mutable result accumulator.

        Examples:
            >>> r = CheckResult()
            >>> body = "> **Summary.** s\\n\\n## Step one\\n\\n## References\\n"
            >>> _check_guide_steps("onboarding", body, r)
            >>> r.errors
            []
    """
    skip = {"summary", "references"}
    for match in _HEADING.finditer(text):
        title = match.group(1).strip()
        normalized = title.split("—", 1)[0].strip().lower()
        if normalized not in skip:
            return
    result.errors.append(f"{slug}: guide profile requires at least one task/step `##` section")


def _check_path_and_symbol_refs(
    entry: ReadmeEntry,
    text: str,
    schema: ProfileSchema,
    repo_root: Path,
    result: CheckResult,
) -> None:
    """Verify cited paths and symbols per profile schema.

        Args:
    entry (ReadmeEntry): Manifest row.
    text (str): README body.
    schema (ProfileSchema): §C0 schema.
    repo_root (Path): Repository root.
    result (CheckResult): Mutable result accumulator.

        Examples:
            >>> from sevn.docs.readme.profile_schemas import get_profile_schema
            >>> r = CheckResult()
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("f", "F", "S", "freeform", "f", "o.md", ("a",), ())
            >>> _check_path_and_symbol_refs(e, "> **Summary.**", get_profile_schema("freeform"), Path("."), r)
            >>> r.errors
            []
    """
    if schema.verify_path_refs:
        path_sections: list[str]
        if entry.profile == "subsystem" and entry.curated:
            path_sections = []
            curated = extract_curated_prose_section(text)
            if curated.strip():
                path_sections.append(curated)
            level3 = extract_level3_section(text)
            if level3.strip():
                path_sections.append(level3)
            if not path_sections:
                path_sections = [text]
        else:
            path_sections = [text]
        for section in path_sections:
            for err in validate_path_refs(section, repo_root):
                result.errors.append(f"{entry.slug}: {err}")
    if schema.verify_symbol_refs:
        symbol_sections: list[str] = []
        if entry.curated:
            curated = extract_curated_prose_section(text)
            if curated.strip():
                symbol_sections.append(curated)
        level3 = extract_level3_section(text)
        if level3.strip():
            symbol_sections.append(level3)
        for section in symbol_sections:
            for err in validate_path_refs(section, repo_root):
                result.errors.append(f"{entry.slug}: {err}")
            for err in validate_symbol_refs(section, repo_root):
                result.errors.append(f"{entry.slug}: {err}")


def _check_template(
    entry: ReadmeEntry,
    text: str,
    repo_root: Path,
    result: CheckResult,
) -> None:
    """Validate a curated README's outline against its slug template.

    Only curated entries are checked, and only when a template file exists. A
    missing template for a curated entry is a warning (opt-in adoption), not a
    hard failure; structural drift against an existing template is an error.

        Args:
    entry (ReadmeEntry): Manifest row.
    text (str): README body.
    repo_root (Path): Repository root.
    result (CheckResult): Mutable result accumulator.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> r = CheckResult()
            >>> e = ReadmeEntry("f", "F", "S", "freeform", "f", "o.md", ("a",), ())
            >>> _check_template(e, "x", Path("."), r)
            >>> r.errors
            []
    """
    if not entry.curated:
        return
    template_path = resolve_template_path(repo_root, entry)
    if not template_path.is_file():
        result.warnings.append(
            f"{entry.slug}: curated but no template at "
            f"{template_path.relative_to(repo_root).as_posix()}"
        )
        return
    template_text = template_path.read_text(encoding="utf-8")
    for err in validate_against_template(template_text, text):
        result.errors.append(f"{entry.slug}: template {err}")


def _has_placeholder_warning(text: str) -> bool:
    """Return True when PLACEHOLDER appears on an image or brand-asset line.

        Args:
    text (str): README body.

        Returns:
            bool: True when a placeholder asset label should warn.

        Examples:
            >>> _has_placeholder_warning("![hero PLACEHOLDER](docs/brand/assets/x.png)")
            True
            >>> _has_placeholder_warning("- `transcribe_placeholder`")
            False
    """
    for line in text.splitlines():
        if not _PLACEHOLDER_LABEL.search(line):
            continue
        if any(marker in line for marker in _PLACEHOLDER_LINE_MARKERS):
            return True
    return False


def _strip_leading_html_comments(text: str) -> str:
    """Remove leading ``<!-- ... -->`` blocks so generated stamps do not hide ``#`` titles.

        Args:
    text (str): README body.

        Returns:
            str: Body with leading HTML comments stripped and left-trimmed.

        Examples:
            >>> _strip_leading_html_comments("<!-- gen -->\\n# Title\\n")
            '# Title\\n'
    """
    stripped = text.lstrip()
    while stripped.startswith("<!--"):
        end = stripped.find("-->")
        if end < 0:
            break
        stripped = stripped[end + 3 :].lstrip()
    return stripped


def _has_heading(text: str, heading: str) -> bool:
    """Return True when a ``##`` heading matches ``heading`` prefix.

        Args:
    text (str): Markdown body.
    heading (str): Required heading text without ``##``.

        Returns:
            bool: True when a matching heading exists.

        Examples:
            >>> _has_heading("## Level 1 — Overview (non-technical)\\n", "Level 1 — Overview")
            True
    """
    pattern = re.compile(rf"^##\s+{re.escape(heading)}", re.MULTILINE)
    return bool(pattern.search(text))
