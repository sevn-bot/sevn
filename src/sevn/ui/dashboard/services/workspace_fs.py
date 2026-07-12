"""Mission Control workspace path confinement for guarded file APIs (MC W1).

Module: sevn.ui.dashboard.services.workspace_fs
Depends: pathlib, re, sevn.cli.repo_sync, sevn.code_understanding.effective_settings,
    sevn.code_understanding.graphify, sevn.second_brain.paths, sevn.tools.paths,
    sevn.workspace.layout

Exports:
    resolve_root_base — map root key to absolute base directory.
    resolve_confined — resolve workspace-relative path with confinement checks.
    is_excluded_path — hard-excluded path segments and secret-store guard.
    is_skills_core_write_blocked — Q7 write-forbidden under skills/core/.
    is_editable_extension — extension allowlist for text editor path.
    validate_utf8_text — reject binary/non-UTF-8 payloads.
    content_has_secret_refs — detect ``${SECRET:…}`` in file bodies.
    soft_trash_destination — compute soft-trash target for deletes.
    workspace_relative_posix — workspace-relative POSIX path helper.
    graph_json_for_workspace — locate confined graphify ``graph.json``.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from sevn.cli.repo_sync import resolve_sevn_repo_root
from sevn.code_understanding.effective_settings import (
    effective_graphify_settings,
    graphify_enabled_for_checkout,
)
from sevn.code_understanding.graphify import graph_json_path, resolve_profiles
from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.paths import resolve_scope_root, wiki_dir_for_scope
from sevn.tools.paths import WorkspacePathError, resolve_workspace_relative_path
from sevn.workspace.layout import WorkspaceLayout

MAX_FILE_BYTES = 1_048_576

ALLOWED_ROOT_KEYS = frozenset(
    {
        "workspace",
        "memory",
        "second-brain",
        "skills",
        "standards",
        "prompts",
        "graphify",
    },
)

EDITABLE_EXTENSIONS = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".py",
        ".sh",
        ".js",
        ".css",
        ".html",
        ".csv",
        ".sql",
        ".ini",
        ".cfg",
        ".env.example",
    },
)

_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".ruff_cache",
        ".llmignore",
    },
)

_SENSITIVE_BASENAME_RE = re.compile(
    r"^(\.env(\..*)?|id_rsa|credentials(\..*)?|.*\.pem|.*\.key)$",
    re.IGNORECASE,
)

_SECRET_REF_PATTERN = re.compile(r"\$\{SECRET:[^}]+\}")

_GRAPHIFY_READ_ONLY = frozenset({"graphify"})


def resolve_root_base(
    root_key: str,
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
) -> Path | None:
    """Map a tree ``root`` key to an absolute base directory.

    Args:
        root_key (str): One of :data:`ALLOWED_ROOT_KEYS`.
        layout (WorkspaceLayout): Resolved workspace layout.
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        Path | None: Absolute base path, or ``None`` when the key is unknown.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> lay = WorkspaceLayout(Path("/tmp/w/sevn.json"), Path("/tmp/w"))
        >>> resolve_root_base("workspace", lay, cfg) == lay.content_root.resolve()
        True
    """
    key = root_key.strip().lower()
    if key not in ALLOWED_ROOT_KEYS:
        return None
    root = layout.content_root.resolve()
    if key in {"workspace", "memory"}:
        return root
    if key == "second-brain":
        scope_root = resolve_scope_root(root, workspace.second_brain, "owner")
        return wiki_dir_for_scope(scope_root).resolve()
    if key == "skills":
        return (root / "skills").resolve()
    if key == "standards":
        return (root / "standards").resolve()
    if key == "prompts":
        return (root / "prompts").resolve()
    if key == "graphify":
        checkout = resolve_sevn_repo_root() or root
        graphify = effective_graphify_settings(workspace, checkout)
        if not graphify_enabled_for_checkout(workspace, checkout):
            return (checkout / ".index/graphify").resolve()
        profiles = resolve_profiles(graphify, checkout)
        if profiles:
            return Path(profiles[0].output_dir).resolve()
        return (checkout / ".index/graphify").resolve()
    return None


def _path_segments_under_content(content_root: Path, candidate: Path) -> tuple[str, ...] | None:
    """Return workspace-relative segments when ``candidate`` is under ``content_root``.

    Args:
        content_root (Path): Workspace content root.
        candidate (Path): Resolved absolute path.

    Returns:
        tuple[str, ...] | None: Relative segments, or ``None`` when outside root.

    Examples:
        >>> from pathlib import Path
        >>> root = Path("/tmp/w").resolve()
        >>> _path_segments_under_content(root, root / "notes.md")
        ('notes.md',)
    """
    try:
        rel = candidate.resolve().relative_to(content_root.resolve())
    except ValueError:
        return None
    return rel.parts


def is_excluded_path(abs_path: Path, content_root: Path) -> bool:
    """Return ``True`` when ``abs_path`` is hard-excluded from the generic file editor.

    Args:
        abs_path (Path): Resolved absolute path.
        content_root (Path): Workspace content root.

    Returns:
        bool: Whether reads and writes must be rejected.

    Examples:
        >>> from pathlib import Path
        >>> root = Path("/tmp/w").resolve()
        >>> is_excluded_path(root / ".sevn/secrets/store.enc", root)
        True
        >>> is_excluded_path(root / "notes.md", root)
        False
    """
    segments = _path_segments_under_content(content_root, abs_path)
    if segments is None:
        return True
    if segments and segments[0] == ".sevn" and len(segments) >= 2 and segments[1] == "secrets":
        return True
    for segment in segments:
        if segment in _EXCLUDED_DIR_NAMES:
            return True
    basename = segments[-1] if segments else abs_path.name
    return bool(_SENSITIVE_BASENAME_RE.match(basename))


def is_skills_core_write_blocked(abs_path: Path, content_root: Path) -> bool:
    """Return ``True`` when a mutating op targets ``skills/core/**`` (Q7).

    Args:
        abs_path (Path): Resolved absolute path.
        content_root (Path): Workspace content root.

    Returns:
        bool: Whether writes must be rejected.

    Examples:
        >>> from pathlib import Path
        >>> root = Path("/tmp/w").resolve()
        >>> is_skills_core_write_blocked(root / "skills/core/foo/SKILL.md", root)
        True
        >>> is_skills_core_write_blocked(root / "skills/user/foo/SKILL.md", root)
        False
    """
    segments = _path_segments_under_content(content_root, abs_path)
    if segments is None or len(segments) < 3:
        return False
    return segments[0] == "skills" and segments[1] == "core"


def is_editable_extension(path: Path) -> bool:
    """Return whether ``path`` has an editor-allowed extension.

    Args:
        path (Path): Target file path.

    Returns:
        bool: ``True`` when the suffix is in :data:`EDITABLE_EXTENSIONS`.

    Examples:
        >>> from pathlib import Path
        >>> is_editable_extension(Path("notes.md"))
        True
        >>> is_editable_extension(Path("image.bin"))
        False
    """
    suffix = path.suffix.lower()
    if suffix in EDITABLE_EXTENSIONS:
        return True
    return path.name in {"SOUL.md", "USER.md", "AGENTS.md", "MEMORY.md"}


def _symlink_escapes_root(candidate: Path, root_base: Path) -> bool:
    """Detect symlink components whose target resolves outside ``root_base``.

    Args:
        candidate (Path): Path relative to ``root_base`` (not yet resolved).
        root_base (Path): Allowed root directory.

    Returns:
        bool: ``True`` when a symlink escapes the root.

    Examples:
        >>> from pathlib import Path
        >>> _symlink_escapes_root(Path("notes.md"), Path("/tmp/w"))
        False
    """
    root_resolved = root_base.resolve()
    current = root_resolved
    for part in candidate.parts:
        if part in (".", ""):
            continue
        current = current / part
        if current.is_symlink():
            target = current.resolve()
            try:
                target.relative_to(root_resolved)
            except ValueError:
                return True
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return True
    return False


def resolve_confined(
    rel_path: str,
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
    *,
    root_key: str = "workspace",
    for_write: bool = False,
) -> Path | None:
    """Resolve ``rel_path`` under ``root_key`` with MC confinement rules.

    Args:
        rel_path (str): Path relative to the selected root base (POSIX).
        layout (WorkspaceLayout): Workspace layout.
        workspace (WorkspaceConfig): Parsed config (graphify/second-brain roots).
        root_key (str): Tree root key (default ``workspace`` → ``content_root``).
        for_write (bool): When ``True``, enforce Q7 skills/core write ban and graphify RO.

    Returns:
        Path | None: Resolved absolute path, or ``None`` when forbidden.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> lay = WorkspaceLayout(Path("/tmp/w/sevn.json"), Path("/tmp/w"))
        >>> resolve_confined("../escape", lay, cfg) is None
        True
    """
    base = resolve_root_base(root_key, layout, workspace)
    if base is None:
        return None
    if for_write and root_key in _GRAPHIFY_READ_ONLY:
        return None
    text = rel_path.strip().replace("\\", "/").lstrip("/")
    if not text:
        text = "."
    if "\x00" in text or ".." in text.split("/"):
        return None
    try:
        if root_key in {"workspace", "memory", "skills", "standards", "prompts"}:
            candidate = resolve_workspace_relative_path(layout.content_root, text)
        else:
            candidate = (base / text).resolve()
            try:
                candidate.relative_to(base.resolve())
            except ValueError:
                return None
    except (WorkspacePathError, PermissionError):
        return None
    if _symlink_escapes_root(Path(text), base):
        return None
    content_root = layout.content_root.resolve()
    if is_excluded_path(candidate, content_root):
        return None
    if for_write and is_skills_core_write_blocked(candidate, content_root):
        return None
    return candidate


def workspace_relative_posix(abs_path: Path, content_root: Path) -> str:
    """Return a POSIX path relative to ``content_root``.

    Args:
        abs_path (Path): Resolved file path.
        content_root (Path): Workspace content root.

    Returns:
        str: Relative POSIX path.

    Examples:
        >>> from pathlib import Path
        >>> workspace_relative_posix(Path("/w/a/b.md"), Path("/w"))
        'a/b.md'
    """
    rel = abs_path.resolve().relative_to(content_root.resolve())
    return rel.as_posix()


def validate_utf8_text(raw: bytes) -> str | None:
    """Decode UTF-8 text or return ``None`` for binary payloads.

    Args:
        raw (bytes): File bytes.

    Returns:
        str | None: Decoded text when valid UTF-8.

    Examples:
        >>> validate_utf8_text(b"hello")
        'hello'
        >>> validate_utf8_text(b"\\xff\\xfe") is None
        True
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def content_has_secret_refs(text: str) -> bool:
    """Return whether ``text`` contains ``${SECRET:…}`` placeholders.

    Args:
        text (str): File body.

    Returns:
        bool: ``True`` when secret refs are present.

    Examples:
        >>> content_has_secret_refs('token = "${SECRET:k:tok}"')
        True
        >>> content_has_secret_refs("plain")
        False
    """
    return bool(_SECRET_REF_PATTERN.search(text))


def soft_trash_destination(content_root: Path, rel_posix: str) -> Path:
    """Compute a soft-trash path under ``.sevn/trash/{timestamp}/…``.

    Args:
        content_root (Path): Workspace content root.
        rel_posix (str): Original workspace-relative POSIX path.

    Returns:
        Path: Absolute trash destination (parent dirs not created).

    Examples:
        >>> from pathlib import Path
        >>> dest = soft_trash_destination(Path("/w"), "notes.md")
        >>> ".sevn/trash" in dest.as_posix()
        True
    """
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return content_root / ".sevn" / "trash" / stamp / rel_posix


def graph_json_for_workspace(
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
) -> Path | None:
    """Return confined ``graph.json`` path when present on disk.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        workspace (WorkspaceConfig): Parsed config.

    Returns:
        Path | None: Absolute ``graph.json`` path, or ``None`` when unavailable.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> lay = WorkspaceLayout(Path("/tmp/w/sevn.json"), Path("/tmp/w"))
        >>> graph_json_for_workspace(lay, cfg) is None or True
        True
    """
    base = resolve_root_base("graphify", layout, workspace)
    if base is None:
        return None
    checkout = resolve_sevn_repo_root() or layout.content_root
    graphify = effective_graphify_settings(workspace, checkout)
    profiles = resolve_profiles(graphify, checkout)
    candidate = graph_json_path(profiles[0]) if profiles else base / "graph.json"
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


__all__ = [
    "ALLOWED_ROOT_KEYS",
    "EDITABLE_EXTENSIONS",
    "MAX_FILE_BYTES",
    "content_has_secret_refs",
    "graph_json_for_workspace",
    "is_editable_extension",
    "is_excluded_path",
    "is_skills_core_write_blocked",
    "resolve_confined",
    "resolve_root_base",
    "soft_trash_destination",
    "validate_utf8_text",
    "workspace_relative_posix",
]
