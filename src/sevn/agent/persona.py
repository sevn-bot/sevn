"""Workspace persona block for Triager and tier-B ``system_prompt`` (recovery Wave A).

Module: sevn.agent.persona
Depends: sevn.onboarding.seed

Exports:
    load_persona_block — AGENTS + IDENTITY/SOUL/USER markdown with template fallback + skills index.
    load_persona_block_intro — IDENTITY/SOUL/USER only (no AGENTS/sevn.bot.md/TOOLS) for first-session intro.
    build_tier_b_intro_prompt_parts — ordered D3 KEEP list for first-session intro ``system_prompt``.
    tier_b_repo_access_prompt — ``source_code/`` mirror paths and commit format for tier-B.
    tier_b_workspace_roots_prompt — workspace layout (incl. ``source_code/``) for tier-B prompt.

Note:
    The rule-style tier-B prompt blocks (``tier_b_hallucination_guard_prompt``,
    ``tier_b_no_preamble_echo_prompt``, ``tier_b_memorize_prompt``,
    ``tier_b_file_link_prompt``) live in :mod:`sevn.prompts.tier_b`. They are
    re-exported here for backward compatibility with existing callers.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from sevn.config.sevn_repo import (
    resolve_sevn_checkout_for_workspace,
    sevn_gateway_read_paths,
    sevn_package_glob_prefix,
)
from sevn.onboarding.seed import load_template
from sevn.prompts.tier_b import (  # re-exported for backward compatibility
    tier_b_brevity_prompt,
    tier_b_file_link_prompt,
    tier_b_hallucination_guard_prompt,
    tier_b_identity_answer_prompt,
    tier_b_identity_boundary_prompt,
    tier_b_memorize_prompt,
    tier_b_no_preamble_echo_prompt,
    tier_b_no_silent_substitution_prompt,
    tier_b_persistence_prompt,
    tier_b_telegram_formatting_prompt,
    tier_b_tools_vs_skills_prompt,
)
from sevn.standards.conventional_commits import conventional_commits_prompt_block

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig

_PERSONA_FILES: Final[tuple[str, ...]] = (
    "AGENTS.md",
    "sevn.bot.md",
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "TOOLS.md",
)
_INTRO_PERSONA_FILES: Final[tuple[str, ...]] = (
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
)
_CACHE_TTL_S: Final[float] = 5.0
_cache: dict[tuple[object, ...], tuple[float, str]] = {}
_intro_cache: dict[tuple[object, ...], tuple[float, str]] = {}


def _file_mtime(path: Path) -> float:
    """Return ``path`` mtime or ``-1.0`` when absent or unreadable.

    Args:
        path (Path): Candidate workspace file.

    Returns:
        float: ``st_mtime`` when the file exists.

    Examples:
        >>> from pathlib import Path
        >>> _file_mtime(Path("/this/path/should/not/exist/persona.md"))
        -1.0
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def _read_persona_file(content_root: Path, name: str) -> str:
    """Read one narrative file from the workspace or packaged templates.

    Args:
        content_root (Path): Resolved workspace content root.
        name (str): Filename (``IDENTITY.md``, ``SOUL.md``, ``USER.md``).

    Returns:
        str: Stripped body or empty string when unavailable.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text("Name: Sevn", encoding="utf-8")
        ...     "Sevn" in _read_persona_file(root, "IDENTITY.md")
        True
    """
    path = content_root / name
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if text:
            return text
    try:
        return load_template(name).strip()
    except FileNotFoundError:
        return ""


def _skills_section(skill_descriptions: Mapping[str, str] | None) -> str:
    """Format the ``## What I can do`` appendix from registry skill descriptions.

    Args:
        skill_descriptions (Mapping[str, str] | None): Skill id → short description.

    Returns:
        str: Markdown section or empty string when no skills are listed.

    Examples:
        >>> "## What I can do" in _skills_section({"tick": "Deterministic harness tick."})
        True
        >>> _skills_section({})
        ''
    """
    if not skill_descriptions:
        return ""
    lines = ["## What I can do"]
    for name, desc in sorted(skill_descriptions.items()):
        body = str(desc).strip()
        if body:
            lines.append(f"- **{name}**: {body}")
    return "" if len(lines) <= 1 else "\n".join(lines)


def load_persona_block(
    content_root: Path,
    *,
    skill_descriptions: Mapping[str, str] | None = None,
) -> str:
    """Assemble persona markdown for unconditional ``Agent.system_prompt``.

    Reads ``AGENTS.md``, ``sevn.bot.md``, ``IDENTITY.md``, ``SOUL.md``, ``USER.md``, and
    ``TOOLS.md`` from
    ``content_root`` in that
    order, falling back to packaged ``src/sevn/data/workspace_templates/`` entries when
    a workspace file is missing. Results are cached for five seconds keyed by
    ``(content_root, mtime tuple, skill descriptions)``.

    Args:
        content_root (Path): Resolved workspace content root.
        skill_descriptions (Mapping[str, str] | None): Optional skill index for
            ``## What I can do``.

    Returns:
        str: Combined persona block (may be empty when no sources exist).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text("CustomBot", encoding="utf-8")
        ...     block = load_persona_block(root)
        ...     "CustomBot" in block and "IDENTITY.md" in block
        True
    """
    root = content_root.resolve()
    mtimes = tuple(_file_mtime(root / name) for name in _PERSONA_FILES)
    skills_key = tuple(sorted((str(k), str(v)) for k, v in (skill_descriptions or {}).items()))
    key = (str(root), mtimes, skills_key)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    parts: list[str] = []
    for name in _PERSONA_FILES:
        text = _read_persona_file(root, name)
        if text:
            parts.append(f"## {name}\n{text}")
    block = "\n\n".join(parts)
    skills = _skills_section(skill_descriptions)
    if skills:
        block = f"{block}\n\n{skills}" if block else skills
    _cache[key] = (now, block)
    return block


def load_persona_block_intro(content_root: Path) -> str:
    """Assemble a slim persona block for first-session intro tier-B turns.

    Reads only ``IDENTITY.md``, ``SOUL.md``, and ``USER.md`` from ``content_root``
    (per locked decision D2 — omits ``AGENTS.md``, ``sevn.bot.md``, ``TOOLS.md``).
    No skills appendix is included. Results are cached for five seconds keyed by
    ``(content_root, mtime tuple)`` using a separate ``_intro_cache`` dict so the
    two caches never collide.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        str: Combined persona block (may be empty when no sources exist).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text("CustomBot", encoding="utf-8")
        ...     block = load_persona_block_intro(root)
        ...     "CustomBot" in block and "## IDENTITY.md" in block
        True
    """
    root = content_root.resolve()
    mtimes = tuple(_file_mtime(root / name) for name in _INTRO_PERSONA_FILES)
    key = (str(root), mtimes)
    now = time.monotonic()
    cached = _intro_cache.get(key)
    if cached is not None and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    parts: list[str] = []
    for name in _INTRO_PERSONA_FILES:
        text = _read_persona_file(root, name)
        if text:
            parts.append(f"## {name}\n{text}")
    block = "\n\n".join(parts)
    _intro_cache[key] = (now, block)
    return block


def build_tier_b_intro_prompt_parts(content_root: Path) -> list[str]:
    """Return the ordered D3 KEEP list for a first-session intro ``system_prompt``.

    Assembles the 9 static builder blocks that are always present on intro turns
    (locked decision D3) followed by the slim intro persona block (D2). The 11
    D4 blocks (architecture context, sessions context, index architecture, log
    query playbook, repo access, workspace roots, retrieval honesty,
    no-silent-substitution, spill recovery, tool economy, file link) are omitted
    to reduce ``system_chars`` from ~90k to ~24k.

    The ``workspace`` param from the full-turn builder is absent because no D3
    KEEP block requires it; ``tier_b_repo_access_prompt`` (workspace-dependent)
    is a D4 DROP.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        list[str]: Raw prompt part strings (some may be empty; callers should
            filter with ``p.strip()`` when joining, consistent with
            ``run_b_turn``'s ``"\\n\\n".join(p for p in prompt_parts if p.strip())``).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text("Bot", encoding="utf-8")
        ...     parts = build_tier_b_intro_prompt_parts(root)
        ...     len(parts) == 10
        True
    """
    from sevn.agent.context_manifest import tier_b_intro_system_prompt_builders

    return tier_b_intro_system_prompt_builders(content_root)


def tier_b_repo_access_prompt(
    workspace: WorkspaceConfig | None,
    content_root: Path,
) -> str:
    """Build tier-B instructions for reading sevn.bot source via the ``source_code/`` mirror.

    The entire sevn.bot repo is mirrored read-only into ``workspace/source_code/``
    and refreshed on every gateway restart, so source is read with ordinary
    workspace-relative paths (no ``@repo/`` prefix).

    Args:
        workspace (WorkspaceConfig | None): Parsed workspace for ``my_sevn.repo_path``.
        content_root (Path): Operator workspace content root.

    Returns:
        str: Markdown describing the ``source_code/`` mirror and commit format.

    Examples:
        >>> from pathlib import Path
        >>> block = tier_b_repo_access_prompt(None, Path("/tmp/ws"))
        >>> "source_code/" in block
        True
    """
    checkout = resolve_sevn_checkout_for_workspace(workspace, content_root=content_root)
    if checkout is not None:
        agent_turn, channel_router, menu = sevn_gateway_read_paths(checkout)
        glob_hint = f"source_code/{sevn_package_glob_prefix(checkout)}/**/*.py".replace("//", "/")
    else:
        agent_turn = "source_code/src/sevn/gateway/agent_turn.py"
        channel_router = "source_code/src/sevn/gateway/channel_router.py"
        menu = "source_code/src/sevn/gateway/menu.py"
        glob_hint = "source_code/src/sevn/**/*.py"
    return (
        "## sevn.bot source access (use for any code or gateway question)\n"
        "The **entire sevn.bot repo is mirrored read-only at `source_code/`** in this\n"
        "workspace and refreshed on every gateway restart. Read it with normal\n"
        "workspace-relative paths under `source_code/` — there is no `@repo/` prefix.\n"
        "Workspace/user files (e.g. `IDENTITY.md`, `sevn.bot.md`) are **bare paths** at\n"
        "the workspace root — never prefix them with `workspace/`.\n"
        "Read workspace `sevn.bot.md` first (code/docs index), then use file tools under\n"
        "`source_code/`.\n"
        f"- Gateway turn loop: `{agent_turn}`\n"
        f"- Channel routing: `{channel_router}`\n"
        f"- Telegram/config menus: `{menu}`\n"
        f"- Discover modules: `glob` with `{glob_hint}`\n"
        "- About-site docs: `source_code/about-sevn.bot/...`\n"
        "Examples:\n"
        "  `read` with path=`source_code/src/sevn/gateway/agent_turn.py`\n"
        "  `glob` with pattern=`source_code/src/sevn/**/*.py`\n"
        "`source_code/` is read-only (it is overwritten on each restart); make code\n"
        "changes in a worktree under `.sevn/code-worktrees/`, never in `source_code/`.\n"
        "Do not claim you lack source access until you tried the paths above.\n"
        f"\n{conventional_commits_prompt_block()}\n"
    )


def tier_b_workspace_roots_prompt(content_root: Path) -> str:
    """Describe the workspace layout (incl. ``source_code/``) for tier-B ``system_prompt``.

    Args:
        content_root (Path): Operator workspace content root.

    Returns:
        str: Markdown block appended to tier-B system prompt assembly.

    Examples:
        >>> from pathlib import Path
        >>> block = tier_b_workspace_roots_prompt(Path("/tmp/ws"))
        >>> "workspace" in block.lower() and "source_code/" in block
        True
    """
    workspace_posix = content_root.resolve().as_posix()
    return (
        "## Workspace layout\n"
        f"Everything lives under the **workspace**: `{workspace_posix}`.\n"
        "Two path forms, no others:\n"
        "- **Workspace/user data** (IDENTITY.md, sevn.bot.md, MEMORY.md, sessions/,\n"
        "  memory/, skills/) → **bare paths** at the workspace root, e.g.\n"
        "  `read` path=`IDENTITY.md`. Do **not** prefix with `workspace/` — there is no\n"
        "  `workspace/` directory and that prefix will not resolve.\n"
        "- **sevn.bot source** (the full repo mirror, read-only, refreshed each restart)\n"
        "  → under **`source_code/`**, e.g. `source_code/src/sevn/gateway/agent_turn.py`.\n"
        "There is no `@repo/` prefix — it does not resolve.\n"
        "Default to bare workspace paths when the user asks about their files, notes, or\n"
        "skills. Use `source_code/...` for sevn.bot source, gateway, or package questions.\n"
    )


__all__ = [
    "build_tier_b_intro_prompt_parts",
    "load_persona_block",
    "load_persona_block_intro",
    "tier_b_brevity_prompt",
    "tier_b_file_link_prompt",
    "tier_b_hallucination_guard_prompt",
    "tier_b_identity_answer_prompt",
    "tier_b_identity_boundary_prompt",
    "tier_b_memorize_prompt",
    "tier_b_no_preamble_echo_prompt",
    "tier_b_no_silent_substitution_prompt",
    "tier_b_persistence_prompt",
    "tier_b_repo_access_prompt",
    "tier_b_telegram_formatting_prompt",
    "tier_b_tools_vs_skills_prompt",
    "tier_b_workspace_roots_prompt",
]
