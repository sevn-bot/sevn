#!/usr/bin/env python3
"""Build the user-facing ``about-sevn.bot/`` static HTML help site.

Renders Jinja templates from ``about-sevn.bot/_templates/``, merges hand prose from
``about-sevn.bot/_sources/*.yaml``, and embeds catalog data from gateway registries.

Module: scripts.build_about_site
Depends: argparse, difflib, pathlib, re, shutil, subprocess, sys, tempfile, yaml, jinja2

Exports:
    build_site — render HTML and copy assets into ``about-sevn.bot/``.
    check_site — rebuild to tempdir and diff against committed output.
    check_purity — fail when forbidden markers appear in generated user pages.
    main — CLI entry (``build`` or ``--check``).

Examples:
    >>> isinstance(REPO, Path)
    True
    >>> "index.html" in USER_PAGES
    True
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.mission_control_catalog import (  # noqa: E402
    DEV_MISSION_HTML,
    match_dev_tab,
    parse_dev_group_nav,
    parse_dev_mission_control_catalog,
)
from scripts.mission_control_snapshot import collect_live_mission_control  # noqa: E402
from scripts.telegram_menu_catalog import (  # noqa: E402
    DEV_TELEGRAM_HTML,
    match_dev_button,
    parse_dev_telegram_menu_catalog,
    sanitize_user_text,
)
from scripts.telegram_menu_snapshot import (  # noqa: E402
    collect_live_config_menu,
    default_docs_workspace,
)

__all__ = [
    "REPO",
    "USER_PAGES",
    "build_site",
    "check_purity",
    "check_site",
    "main",
]

REPO = _REPO
ABOUT = REPO / "about-sevn.bot"
TEMPLATES = ABOUT / "_templates"
SOURCES = ABOUT / "_sources"
ASSETS_SRC = REPO / "styles" / "sevn" / "style"

USER_PAGES: tuple[str, ...] = (
    "index.html",
    "getting-started.html",
    "mission-control.html",
    "telegram-menu.html",
    "tools.html",
    "skills.html",
    "config.html",
    "troubleshooting.html",
    "agent-context.html",
)

_FORBIDDEN_MARKERS: tuple[str, ...] = ("src/sevn", "plan/", "prd/", "specs/")
# Agent/evolution markdown under about-sevn.bot/ (not compiled into USER_PAGES HTML).
_ABOUT_AGENT_MD_ROOTS = frozenset(
    {"agents", "spec-kit", "features", "_docsys", "prd", "specs", "decisions"}
)
_ABOUT_AGENT_MD_FILES = frozenset({"ARCHITECTURE.md", "README.md", "specs-index.md", "GLOSSARY.md"})
_FORBIDDEN_PAGE_RE = re.compile(
    r"(src/sevn|plan/|prd/|specs/)",
    re.IGNORECASE,
)
_SPEC_STRIP_RE = re.compile(r"\([^)]*specs/[^)]*\)|`specs/[^`]+`", re.I)
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


_FOOTER_RE = re.compile(
    r"^\s*Generated \d{4}-\d{2}-\d{2} from commit [0-9a-f]+\.\s*$",
    re.MULTILINE,
)


def _normalize_html_for_compare(text: str) -> str:
    """Strip volatile git footer metadata before comparing HTML.

    Args:
        text (str): Full HTML file body.

    Returns:
        str: Text with footer generation line removed.

    Examples:
        >>> _normalize_html_for_compare("Generated 2026-05-25 from commit abc1234.\\n")
        ''
    """
    return _FOOTER_RE.sub("", text)


def _git_commit_date() -> tuple[str, str]:
    """Return short SHA and commit date for footer metadata.

    Returns:
        tuple[str, str]: ``(short_sha, yyyy-mm-dd)`` or ``("unknown", "unknown")``.

    Examples:
        >>> sha, day = _git_commit_date()
        >>> isinstance(sha, str) and isinstance(day, str)
        True
    """
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%h %cs"],
            cwd=REPO,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        parts = out.strip().split()
        if len(parts) >= 2:
            return parts[0], parts[1]
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        pass
    return "unknown", "unknown"


def _git_head() -> str:
    """Return short git SHA or ``unknown`` when not in a repo.

    Returns:
        str: Seven-character commit id.

    Examples:
        >>> isinstance(_git_head(), str)
        True
    """
    sha, _day = _git_commit_date()
    return sha


def _load_source(slug: str) -> dict[str, Any]:
    """Load YAML prose for one page slug.

    Args:
        slug (str): Page stem without ``.html``.

    Returns:
        dict[str, Any]: Parsed YAML or empty dict.

    Examples:
        >>> isinstance(_load_source("missing-page"), dict)
        True
    """
    path = SOURCES / f"{slug}.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _nav_pages() -> tuple[tuple[str, str], ...]:
    """Return sidebar navigation entries.

    Returns:
        tuple[tuple[str, str], ...]: ``(href, label)`` pairs.

    Examples:
        >>> any(href == "index.html" for href, _ in _nav_pages())
        True
    """
    labels = {
        "index": "Home",
        "getting-started": "Getting started",
        "mission-control": "Mission Control",
        "telegram-menu": "Telegram settings",
        "tools": "Tools",
        "skills": "Skills",
        "config": "Settings",
        "troubleshooting": "Troubleshooting",
        "agent-context": "Agent context",
    }
    return tuple((f"{slug}.html", label) for slug, label in labels.items())


def _jinja_env() -> Environment:
    """Create Jinja environment for help templates.

    Returns:
        Environment: Configured loader.

    Examples:
        >>> env = _jinja_env()
        >>> env.get_template("base.html.j2") is not None
        True
    """
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _copy_assets(dest_root: Path) -> None:
    """Copy design-system CSS and logos into the help site assets tree.

    Args:
        dest_root (Path): Destination ``about-sevn.bot`` root.

    Returns:
        None: Always.

    Examples:
        >>> from pathlib import Path
        >>> _copy_assets(Path("/tmp"))  # doctest: +SKIP
    """
    assets = dest_root / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    for name in ("index.css", "base.css", "theme-dark.css", "theme-light.css"):
        src = ASSETS_SRC / name
        if src.is_file():
            shutil.copy2(src, assets / name)
    for sub in ("tokens", "components", "utils", "logos"):
        src_dir = ASSETS_SRC / sub
        if src_dir.is_dir():
            shutil.copytree(src_dir, assets / sub)


def _collect_telegram_menu() -> dict[str, Any]:
    """Build navigation-only Telegram ``/config`` mock data from live registries.

    Returns:
        dict[str, Any]: Template context for ``telegram-menu.html``.

    Examples:
        >>> data = _collect_telegram_menu()
        >>> "sections" in data and len(data["sections"]) >= 10
        True
    """
    from sevn.gateway.menu import _CONFIG_ROOT_TILES
    from sevn.gateway.menu_readiness import readiness_for_callback, readiness_user_label

    dev_catalog = parse_dev_telegram_menu_catalog(DEV_TELEGRAM_HTML)
    ws = default_docs_workspace()
    live = collect_live_config_menu(ws)
    sections: list[dict[str, Any]] = []

    for label, section_id, _cb in _CONFIG_ROOT_TILES:
        dev_sec = dev_catalog.get(section_id, {})
        title = str(dev_sec.get("title") or label.split(" ", 1)[-1])
        short = str(dev_sec.get("short") or f"Settings for {title}.")
        long_desc = str(dev_sec.get("long") or short)
        tier_label = str(dev_sec.get("status") or readiness_user_label("WIP"))
        dev_buttons = list(dev_sec.get("buttons") or [])
        live_sec = live.get(section_id)
        buttons: list[dict[str, str | bool]] = []
        if live_sec is not None:
            for btn in live_sec.buttons:
                matched = match_dev_button(
                    dev_buttons,
                    btn.label,
                    callback_data=btn.callback_data,
                )
                live_status = readiness_user_label(readiness_for_callback(btn.callback_data))
                if matched is not None:
                    buttons.append(
                        {
                            "label": btn.label,
                            "status": live_status,
                            "short": matched["short"],
                            "long": matched["long"],
                            "final": btn.is_final,
                        },
                    )
                else:
                    buttons.append(
                        {
                            "label": btn.label,
                            "status": live_status,
                            "short": f"Settings for {btn.label}.",
                            "long": f"Settings for {btn.label}.",
                            "final": btn.is_final,
                        },
                    )

        sections.append(
            {
                "id": section_id,
                "tile_label": label,
                "title": title,
                "short": short,
                "long": long_desc,
                "status": tier_label,
                "buttons": buttons,
            },
        )

    root_tiles = []
    for tile_label, section_id, _cb in _CONFIG_ROOT_TILES:
        dev_sec = dev_catalog.get(section_id, {})
        root_tiles.append(
            {
                "label": tile_label,
                "section": section_id,
                "short": str(dev_sec.get("short") or tile_label.split(" ", 1)[-1]),
            },
        )
    return {"root_tiles": root_tiles, "sections": sections}


def _live_tab_status(kind: str) -> str:
    """Map registry tab kind to user-facing readiness label.

    Args:
        kind (str): ``wired``, ``post_v1``, or ``stub``.

    Returns:
        str: Badge label for the help preview.

    Examples:
        >>> _live_tab_status("wired")
        'Available'
    """
    if kind == "wired":
        return "Available"
    if kind == "post_v1":
        return "Coming soon"
    return "Coming soon"


def _collect_mission_control() -> dict[str, Any]:
    """Build Mission Control sidebar mock data from tab registry + dev catalog.

    Returns:
        dict[str, Any]: Template context for ``mission-control.html``.

    Examples:
        >>> data = _collect_mission_control()
        >>> "groups" in data and len(data["groups"]) >= 8
        True
    """
    dev_catalog = parse_dev_mission_control_catalog(DEV_MISSION_HTML)
    live = collect_live_mission_control()
    groups: list[dict[str, Any]] = []

    for group_id, live_grp in live.items():
        dev_grp = dev_catalog.get(group_id, {})
        title = str(dev_grp.get("title") or live_grp.title)
        short = str(dev_grp.get("short") or f"Tabs for {title}.")
        long_desc = str(dev_grp.get("long") or short)
        tier_label = str(dev_grp.get("status") or "Coming soon")
        dev_tabs = list(dev_grp.get("tabs") or [])
        tabs: list[dict[str, str]] = []
        for tab in live_grp.tabs:
            matched = match_dev_tab(dev_tabs, tab.label)
            status = _live_tab_status(tab.kind)
            if matched is not None:
                tabs.append(
                    {
                        "label": tab.label,
                        "slug": tab.slug,
                        "status": status,
                        "short": matched["short"],
                        "long": matched["long"],
                    },
                )
            else:
                tabs.append(
                    {
                        "label": tab.label,
                        "slug": tab.slug,
                        "status": status,
                        "short": f"Dashboard panel for {tab.label}.",
                        "long": f"Dashboard panel for {tab.label}.",
                    },
                )
        groups.append(
            {
                "id": group_id,
                "title": title,
                "short": short,
                "long": long_desc,
                "status": tier_label,
                "tabs": tabs,
            },
        )

    group_nav: list[dict[str, str]] = []
    nav_order = parse_dev_group_nav(DEV_MISSION_HTML)
    if nav_order:
        for group_id, nav_label in nav_order:
            dev_grp = dev_catalog.get(group_id, {})
            live_grp = live.get(group_id)
            group_nav.append(
                {
                    "id": group_id,
                    "label": nav_label,
                    "short": str(
                        dev_grp.get("short") or (live_grp.title if live_grp else nav_label)
                    ),
                },
            )
    else:
        for group_id, live_grp in live.items():
            dev_grp = dev_catalog.get(group_id, {})
            group_nav.append(
                {
                    "id": group_id,
                    "label": live_grp.title,
                    "short": str(dev_grp.get("short") or live_grp.title),
                },
            )

    return {"group_nav": group_nav, "groups": groups}


def _collect_tools() -> list[dict[str, str]]:
    """Snapshot native tool names and sanitized descriptions.

    Returns:
        list[dict[str, str]]: Sorted tool rows.

    Examples:
        >>> rows = _collect_tools()
        >>> any(r["name"] == "load_skill" for r in rows)
        True
    """
    from sevn.tools.registry import build_session_registry

    overrides = _load_source("tools").get("overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}

    _exe, tool_set = build_session_registry()
    rows: list[dict[str, str]] = []
    for defn in tool_set.native:
        desc = overrides.get(defn.name)
        if not isinstance(desc, str) or not desc.strip():
            desc = sanitize_user_text(defn.description)
        if not desc:
            desc = f"Built-in capability: {defn.name.replace('_', ' ')}."
        rows.append({"name": defn.name, "description": desc, "category": defn.category})
    return sorted(rows, key=lambda r: r["name"])


def _parse_skill_front_matter(path: Path) -> dict[str, str]:
    """Parse YAML front matter from one ``SKILL.md``.

    Args:
        path (Path): Skill markdown path.

    Returns:
        dict[str, str]: ``name`` and ``description`` when present.

    Examples:
        >>> _parse_skill_front_matter(Path("/nonexistent"))
        {}
    """
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        return {}
    name = data.get("name")
    desc = data.get("description")
    return {
        "name": str(name) if name else path.parent.name,
        "description": sanitize_user_text(str(desc)) if desc else "",
    }


def _collect_skills() -> list[dict[str, str]]:
    """List bundled core skills with user-facing descriptions.

    Returns:
        list[dict[str, str]]: Sorted skill rows.

    Examples:
        >>> rows = _collect_skills()
        >>> len(rows) >= 5
        True
    """
    core = REPO / "src" / "sevn" / "data" / "bundled_skills" / "core"
    overrides = _load_source("skills").get("overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    rows: list[dict[str, str]] = []
    if not core.is_dir():
        return rows
    for skill_md in sorted(core.glob("*/SKILL.md")):
        meta = _parse_skill_front_matter(skill_md)
        name = meta.get("name") or skill_md.parent.name
        desc = overrides.get(name)
        if not isinstance(desc, str) or not desc.strip():
            desc = meta.get("description", "")
        if not desc:
            desc = f"Bundled skill: {name.replace('-', ' ')}."
        rows.append({"name": name, "description": desc})
    return rows


def _mermaid_safe_id(raw: str) -> str:
    """Return a Mermaid-safe node id derived from ``raw``.

    Args:
        raw (str): Arbitrary label or identifier.

    Returns:
        str: Identifier with non-alphanumeric characters replaced by ``_``.

    Examples:
        >>> _mermaid_safe_id("tier-b")
        'tier_b'
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw)


def _agent_mermaid_diagram(agent: dict[str, Any]) -> str:
    """Build a Mermaid flowchart for an agent's ordered slots.

    Args:
        agent (dict[str, Any]): Agent subtree from the context manifest.

    Returns:
        str: Mermaid ``flowchart TD`` source for the agent's slots.

    Examples:
        >>> txt = _agent_mermaid_diagram({
        ...     "id": "x",
        ...     "slots": [{"order": 1, "id": "s", "label": "S", "role": "system", "content_type": "x"}],
        ... })
        >>> "flowchart TD" in txt
        True
    """
    agent_id = _mermaid_safe_id(str(agent.get("id", "agent")))
    lines = ["flowchart TD"]
    prev: str | None = None
    for slot in sorted(agent.get("slots", []), key=lambda s: int(s.get("order", 0))):
        if not isinstance(slot, dict):
            continue
        sid = _mermaid_safe_id(str(slot.get("id", "slot")))
        node = f"{agent_id}_{sid}"
        label = str(slot.get("label", sid)).replace('"', "'")
        role = str(slot.get("role", ""))
        ctype = str(slot.get("content_type", ""))
        lines.append(f'  {node}["{label}<br/>role:{role}<br/>{ctype}"]')
        if prev:
            lines.append(f"  {prev} --> {node}")
        prev = node
    if prev is None:
        lines.append(f'  {agent_id}_empty["No LLM slots"]')
    return "\n".join(lines)


def _collect_agent_context() -> dict[str, Any]:
    """Collect agent-context manifest, per-agent Mermaid diagrams, and example turn.

    Returns:
        dict[str, Any]: Keys ``manifest``, ``agent_mermaid``, and optional ``example_turn``.

    Examples:
        >>> data = _collect_agent_context()
        >>> "manifest" in data and "agent_mermaid" in data
        True
    """
    from scripts.agent_context_manifest_lib import GOLDEN_PATH, load_golden_manifest

    if not GOLDEN_PATH.is_file():
        from scripts.agent_context_manifest_lib import build_schema_document

        manifest = build_schema_document()
    else:
        manifest = load_golden_manifest()

    example_path = REPO / "tests" / "fixtures" / "agent_context" / "example_turn.json"
    example_turn: dict[str, Any] | None = None
    if example_path.is_file():
        example_turn = json.loads(example_path.read_text(encoding="utf-8"))

    agent_mermaid = {
        str(agent.get("id", "")): _agent_mermaid_diagram(agent)
        for agent in manifest.get("agents", [])
        if isinstance(agent, dict)
    }
    return {
        "manifest": manifest,
        "agent_mermaid": agent_mermaid,
        "example_turn": example_turn,
    }


def _collect_config_fields() -> list[dict[str, str]]:
    """Return curated user-facing config field rows from ``_sources/config.yaml``.

    Returns:
        list[dict[str, str]]: Config reference rows.

    Examples:
        >>> isinstance(_collect_config_fields(), list)
        True
    """
    raw = _load_source("config").get("fields") or []
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        title = str(item.get("title", path)).strip()
        desc = str(item.get("description", "")).strip()
        if path and title and desc:
            rows.append({"path": path, "title": title, "description": desc})
    return rows


def _render_page(env: Environment, slug: str, *, extra: dict[str, Any] | None = None) -> str:
    """Render one help page HTML.

    Args:
        env (Environment): Jinja environment.
        slug (str): Page stem.
        extra (dict[str, Any] | None): Additional template variables.

    Returns:
        str: Rendered HTML document.

    Examples:
        >>> env = _jinja_env()
        >>> html = _render_page(env, "index")
        >>> "<html" in html.lower()
        True
    """
    src = _load_source(slug)
    title = str(src.get("title") or slug.replace("-", " ").title())
    summary = str(src.get("summary") or "")
    body_html = str(src.get("body") or "")

    sha, commit_day = _git_commit_date()
    ctx: dict[str, Any] = {
        "slug": slug,
        "title": title,
        "summary": summary,
        "body_html": body_html,
        "nav_pages": _nav_pages(),
        "generated_at": commit_day,
        "git_commit": sha,
        "is_generated_catalog": slug
        in {
            "mission-control",
            "telegram-menu",
            "tools",
            "skills",
            "config",
            "agent-context",
        },
    }
    if extra:
        ctx.update(extra)

    template_name = f"{slug}.html.j2"
    if not (TEMPLATES / template_name).is_file():
        template_name = "generic.html.j2"
    return env.get_template(template_name).render(**ctx)


def build_site(dest_root: Path | None = None) -> None:
    """Render all user pages and copy assets.

    Args:
        dest_root (Path | None): Output root; defaults to ``about-sevn.bot/``.

    Returns:
        None: Always.

    Examples:
        >>> build_site()  # doctest: +SKIP
    """
    root = dest_root or ABOUT
    root.mkdir(parents=True, exist_ok=True)
    _copy_assets(root)
    env = _jinja_env()

    extras: dict[str, dict[str, Any]] = {
        "mission-control": _collect_mission_control(),
        "telegram-menu": _collect_telegram_menu(),
        "tools": {"tools": _collect_tools()},
        "skills": {"skills": _collect_skills()},
        "config": {"config_fields": _collect_config_fields()},
        "agent-context": _collect_agent_context(),
    }

    for slug in (
        "index",
        "getting-started",
        "mission-control",
        "telegram-menu",
        "tools",
        "skills",
        "config",
        "troubleshooting",
        "agent-context",
    ):
        html = _render_page(env, slug, extra=extras.get(slug))
        if not html.endswith("\n"):
            html += "\n"
        (root / f"{slug}.html").write_text(html, encoding="utf-8")


def _read_text_files(root: Path) -> dict[str, str]:
    """Read tracked user HTML and asset files under a site root.

    Args:
        root (Path): Site root directory.

    Returns:
        dict[str, str]: Relative path to file text.

    Examples:
        >>> isinstance(_read_text_files(ABOUT), dict)
        True
    """
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for rel in USER_PAGES:
        path = root / rel
        if path.is_file():
            out[rel] = path.read_text(encoding="utf-8")
    assets = root / "assets"
    if assets.is_dir():
        for path in sorted(assets.rglob("*")):
            if not path.is_file():
                continue
            # Skip OS-generated metadata that doesn't ship with the site
            # (macOS Finder writes ``.DS_Store`` into directories users browse).
            if path.name == ".DS_Store":
                continue
            out[path.relative_to(root).as_posix()] = path.read_bytes().decode(
                "utf-8",
                errors="replace",
            )
    return out


def check_purity(root: Path | None = None) -> list[str]:
    """Return purity violations in generated user pages.

    Args:
        root (Path | None): Site root; defaults to ``about-sevn.bot/``.

    Returns:
        list[str]: Human-readable violation messages.

    Examples:
        >>> isinstance(check_purity(), list)
        True
    """
    site = root or ABOUT
    violations: list[str] = []
    for rel in USER_PAGES:
        path = site / rel
        if not path.is_file():
            violations.append(f"missing generated page: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if _FORBIDDEN_PAGE_RE.search(text):
            violations.append(f"{rel}: forbidden internal reference marker")
    for md in site.rglob("*.md"):
        if "_standards" in md.parts:
            continue
        rel = md.relative_to(site)
        if rel.parts and rel.parts[0] in _ABOUT_AGENT_MD_ROOTS:
            continue
        if len(rel.parts) == 1 and rel.name in _ABOUT_AGENT_MD_FILES:
            continue
        violations.append(f"unexpected markdown outside _standards/: {rel}")
    return violations


def check_site() -> int:
    """Rebuild into a temp directory and diff against committed files.

    Returns:
        int: Exit code (0 ok, 1 drift or purity failure).

    Examples:
        >>> isinstance(check_site(), int)
        True
    """
    purity = check_purity(ABOUT)
    if purity:
        for msg in purity:
            print(f"about-site-check: {msg}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="sevn-about-site-") as tmp:
        tmp_root = Path(tmp)
        build_site(tmp_root)
        committed = _read_text_files(ABOUT)
        built = _read_text_files(tmp_root)
        drift = False
        for rel in sorted(set(committed) | set(built)):
            a = committed.get(rel, "")
            b = built.get(rel, "")
            if rel.endswith(".html"):
                a = _normalize_html_for_compare(a)
                b = _normalize_html_for_compare(b)
            if a != b:
                drift = True
                print(f"about-site-check: drift in {rel}", file=sys.stderr)
                for line in difflib.unified_diff(
                    a.splitlines(),
                    b.splitlines(),
                    fromfile=f"committed/{rel}",
                    tofile=f"built/{rel}",
                    lineterm="",
                ):
                    print(line, file=sys.stderr)
        if drift:
            print("about-site-check: run `make about-site` and commit the result", file=sys.stderr)
            return 1
    print("about-site-check: ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry for build or check modes.

    Args:
        argv (list[str] | None): Arguments (defaults to ``sys.argv[1:]``).

    Returns:
        int: Exit code.

    Examples:
        >>> isinstance(main(["--check"]), int)
        True
    """
    parser = argparse.ArgumentParser(description="Build about-sevn.bot user help site")
    parser.add_argument(
        "command",
        nargs="?",
        default="build",
        choices=("build", "check"),
        help="build writes HTML; check verifies committed output",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Alias for check command",
    )
    args = parser.parse_args(argv)
    cmd = "check" if args.check else args.command
    if cmd == "check":
        return check_site()
    build_site()
    purity = check_purity()
    if purity:
        for msg in purity:
            print(f"about-site-build: {msg}", file=sys.stderr)
        return 1
    print(f"about-site-build: wrote {len(USER_PAGES)} pages under {ABOUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
