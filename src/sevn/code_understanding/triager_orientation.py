"""Graphify and evolution orientation blocks for Triager prompts (`specs/28-code-understanding.md` §2.5).

Exports:
    infer_orientation_intent — best-effort evolution intent from user text.
    orientation_block_for_workspace — prefix text when graphify or evolution intent applies.
"""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.effective_settings import effective_graphify_settings
from sevn.code_understanding.graphify import (
    graph_report_path,
    resolve_active_profiles_cached,
    search_tool_prefix,
)
from sevn.config.sevn_repo import (
    resolve_sevn_checkout_for_workspace,
    sevn_gateway_read_paths,
    sevn_package_glob_prefix,
)
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001

_ARCHITECTURE_CANDIDATES = (
    Path("about-sevn.bot/ARCHITECTURE.md"),
    Path("evolution/ARCHITECTURE.md"),
)
_MYCODE_REL = Path(".index/mycode/MYCODE.md")
_EVOLUTION_INTENTS = frozenset({"coding", "self_evolution"})
_ARCHITECTURE_MARKERS = (
    "how does",
    "how do",
    "where is",
    "where are",
    "which file",
    "which module",
    "gateway",
    "triager",
    "your code",
    "this repo",
    "architecture",
    "source code",
    "read the code",
    "explain the code",
    "code path",
    "implemented",
    "dispatch",
    "agent_turn",
)


def infer_orientation_intent(message: str) -> str | None:
    """Return an evolution orientation intent when user text suggests coding or self-improve.

    Args:
        message (str): Current user message (commands or free text).

    Returns:
        str | None: ``coding``, ``self_evolution``, or ``None``.

    Examples:
        >>> infer_orientation_intent("/improve run sampler")
        'self_evolution'
        >>> infer_orientation_intent("hello")
        >>> infer_orientation_intent("where is gateway dispatch")
        'coding'
    """
    text = message.strip().lower()
    if not text:
        return None
    if text.startswith("/improve") or "self-improve" in text or "self improve" in text:
        return "self_evolution"
    if text.startswith(("/issue", "/evo")) or "evolution" in text or "worktree" in text:
        return "coding"
    coding_markers = (
        "sevn.bot",
        "fix bug",
        "feature issue",
        "open a pr",
        "pull request",
        "patch the bot",
        "codebase",
    )
    if any(marker in text for marker in coding_markers):
        return "coding"
    if any(marker in text for marker in _ARCHITECTURE_MARKERS):
        return "coding"
    return None


def _architecture_doc_path(repo_root: Path) -> Path | None:
    """Return the first existing ARCHITECTURE doc under ``repo_root``.

    Args:
        repo_root (Path): sevn.bot checkout root.

    Returns:
        Path | None: Absolute path to the doc file, or ``None``.

    Examples:
        >>> from pathlib import Path
        >>> _architecture_doc_path(Path("/nonexistent")) is None
        True
    """
    for rel in _ARCHITECTURE_CANDIDATES:
        candidate = (repo_root / rel).resolve()
        if candidate.is_file():
            return candidate
    return None


def _about_architecture_block(repo_root: Path) -> str:
    """Return ARCHITECTURE orientation text when a doc exists under ``repo_root``.

    Args:
        repo_root (Path): sevn.bot checkout root.

    Returns:
        str: Non-empty block or ``""``.

    Examples:
        >>> from pathlib import Path
        >>> _about_architecture_block(Path("/nonexistent"))
        ''
    """
    path = _architecture_doc_path(repo_root)
    if path is None:
        return ""
    rel = f"source_code/{path.relative_to(repo_root.resolve()).as_posix()}"
    return (
        "[code_orientation]\n"
        f"Evolution / coding on sevn.bot: read {rel} first "
        "(doc tree index, worktree-only writes, spec-kit artefact paths).\n"
    )


def _always_on_checkout_block(checkout: Path, *, graphify_report: Path | None) -> str:
    """Build the minimal orientation block when a checkout resolves.

    Args:
        checkout (Path): Absolute sevn.bot checkout root.
        graphify_report (Path | None): ``GRAPH_REPORT.md`` when Graphify is active.

    Returns:
        str: Non-empty orientation text.

    Examples:
        >>> from pathlib import Path
        >>> block = _always_on_checkout_block(Path("/tmp"), graphify_report=None)
        >>> "[code_orientation]" in block
        True
    """
    arch = _architecture_doc_path(checkout)
    if arch is not None:
        arch_hint = f"source_code/{arch.relative_to(checkout.resolve()).as_posix()}"
    else:
        arch_hint = "source_code/about-sevn.bot/ARCHITECTURE.md"
    agent_turn, channel_router, _menu = sevn_gateway_read_paths(checkout)
    glob_hint = f"source_code/{sevn_package_glob_prefix(checkout)}/**/*.py".replace("//", "/")
    mycode = (checkout / _MYCODE_REL).resolve()
    lines = [
        "[code_orientation]",
        "sevn.bot source: mirrored read-only at source_code/ (workspace-relative paths)",
        f"Read first: {arch_hint}",
        f"Gateway entry: {agent_turn}; routing: {channel_router}",
        f"Search package: glob {glob_hint}",
    ]
    if mycode.is_file():
        rel_mycode = f"source_code/{mycode.relative_to(checkout.resolve()).as_posix()}"
        lines.append(f"Repo map: {rel_mycode} (MYCODE).")
    else:
        lines.append("Repo map: run mycode-scan skill to generate .index/mycode/MYCODE.md.")
    if graphify_report is not None and graphify_report.is_file():
        lines.append(f"Architecture graph: {graphify_report.as_posix()} (Graphify).")
    lines.append(
        "Source paths in tools: source_code/<relative> (read-only). "
        "Writes: workspace/.sevn/code-worktrees/<issue-id>/ only."
    )
    return "\n".join(lines) + "\n"


def orientation_block_for_workspace(
    workspace: WorkspaceConfig,
    *,
    content_root: Path | None = None,
    primary_repo_root: Path | None = None,
    intent: str | None = None,
) -> str:
    """Build Triager orientation text from checkout resolution and Graphify profiles.

    When a sevn.bot checkout resolves, prepends an always-on block (source_code/
    mirror, ARCHITECTURE, MYCODE). Adds evolution ARCHITECTURE detail
    for ``coding`` / ``self_evolution`` intents. Appends Graphify profile lines when
    enabled and reports exist on disk.

    Args:
        workspace (WorkspaceConfig): Parsed workspace (``code_understanding.graphify``).
        content_root (Path | None, optional): Operator workspace ``content_root`` hint.
        primary_repo_root (Path | None, optional): Deprecated alias for ``content_root``.
        intent (str | None, optional): Evolution orientation intent.

    Returns:
        str: Combined orientation block, or ``""`` when nothing applies.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> block = orientation_block_for_workspace(
        ...     WorkspaceConfig.minimal(),
        ...     content_root=Path("/nonexistent-operator-ws"),
        ... )
        >>> isinstance(block, str)
        True
    """
    hint = content_root if content_root is not None else primary_repo_root
    checkout = resolve_sevn_checkout_for_workspace(workspace, content_root=hint)
    parts: list[str] = []

    graphify_settings = effective_graphify_settings(workspace, checkout)
    profile_root = checkout if checkout is not None else (hint or Path.cwd())
    profiles = (
        resolve_active_profiles_cached(graphify_settings, profile_root)
        if graphify_settings.enabled
        else []
    )
    graph_report = graph_report_path(profiles[0]) if len(profiles) == 1 else None

    if checkout is not None:
        parts.append(_always_on_checkout_block(checkout, graphify_report=graph_report).rstrip("\n"))

    if intent in _EVOLUTION_INTENTS and checkout is not None:
        about = _about_architecture_block(checkout)
        if about and (not parts or about.strip() not in parts[0]):
            parts.append(about.rstrip("\n"))

    if profiles:
        graph_lines = [
            "[code_orientation]",
            "Read Graphify reports before broad repo search.",
        ]
        for profile in profiles:
            graph_lines.append(search_tool_prefix(profile))
        block = "\n".join(graph_lines)
        if not parts or block not in parts[-1]:
            parts.append(block)

    if not parts:
        return ""
    return "\n".join(parts) + "\n"
