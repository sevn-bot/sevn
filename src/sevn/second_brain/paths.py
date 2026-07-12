"""Vault path resolution and safety (`specs/27-second-brain.md` sections 3.2 and 4.1).

Module: sevn.second_brain.paths
Depends: pathlib, sevn.config.workspace_config, sevn.security.llmignore, sevn.tools.paths

Exports:
    vault_root — ``workspace/second_brain`` (legacy base).
    resolve_vault_base — legacy or custom configured vault directory.
    resolve_scope_root — resolved ``users/<scope>/`` or custom vault root.
    display_scope_root_relative — operator-facing workspace-relative path.
    user_scope_root — ``users/<scope>/`` under legacy vault base.
    shared_wiki_root — ``shared/wiki/`` when present (legacy overlay).
    wiki_dir_for_scope — ``<scope_root>/wiki``.
    raw_dir_for_scope — ``<scope_root>/raw``.
    outputs_dir_for_scope — ``<scope_root>/outputs``.
    assert_wiki_relative_safe — reject ``..`` and absolute fragments.
    resolve_wiki_file — resolved path under wiki with llmignore guard.
    resolve_raw_file — resolved path under ``raw/`` with llmignore guard.
    effective_scope — active scope name from args and config.
    legacy_shared_vault_root — ``<content_root>/second_brain`` for shared overlay.
"""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import SecondBrainWorkspaceConfig
from sevn.second_brain.errors import SecondBrainPathError
from sevn.security.llmignore import is_llmignored


def vault_root(workspace_content_root: Path) -> Path:
    """Return resolved ``<content_root>/second_brain``.

    Args:
        workspace_content_root (Path): Workspace content root (directory with ``sevn.json``).

    Returns:
        Path: Legacy Second Brain vault base directory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> isinstance(vault_root(Path(tempfile.mkdtemp())), Path)
        True
    """

    return (workspace_content_root.expanduser().resolve() / "second_brain").resolve()


def legacy_shared_vault_root(workspace_content_root: Path) -> Path:
    """Return the legacy ``second_brain`` directory used for ``shared/wiki`` overlay.

    Args:
        workspace_content_root (Path): Workspace content root.

    Returns:
        Path: Resolved ``<content_root>/second_brain``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> legacy_shared_vault_root(Path(tempfile.mkdtemp())).name
        'second_brain'
    """

    return vault_root(workspace_content_root)


def _resolve_vault_relative(content_root: Path, rel_path: str) -> Path:
    """Resolve a workspace-relative vault path with containment checks.

    Args:
        content_root (Path): Workspace content root.
        rel_path (str): Normalised workspace-relative path.

    Returns:
        Path: Resolved absolute path under ``content_root``.

    Raises:
        SecondBrainPathError: When the path escapes the workspace or hits ``.llmignore/``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / "obsidian").mkdir()
        >>> _resolve_vault_relative(ws, "obsidian").name
        'obsidian'
    """
    text = rel_path.strip().replace("\\", "/").lstrip("/")
    if not text or ".." in text.split("/"):
        msg = f"path {rel_path!r} must be a safe workspace-relative path"
        raise SecondBrainPathError(msg)
    root = content_root.expanduser().resolve()
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        msg = f"path {rel_path!r} escapes workspace root"
        raise SecondBrainPathError(msg) from exc
    if is_llmignored(candidate, root):
        msg = f"path {rel_path!r} is under quarantined .llmignore/"
        raise SecondBrainPathError(msg)
    return candidate


def resolve_vault_base(
    content_root: Path,
    cfg: SecondBrainWorkspaceConfig | None,
) -> Path:
    """Return the configured vault base or legacy ``second_brain`` directory.

    When ``paths.vault`` is set, returns the resolved custom vault root. Otherwise
    returns the legacy ``<content_root>/second_brain`` path.

    Args:
        content_root (Path): Workspace content root.
        cfg (SecondBrainWorkspaceConfig | None): Second Brain workspace slice.

    Returns:
        Path: Resolved vault base directory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / "obsidian").mkdir()
        >>> cfg = SecondBrainWorkspaceConfig(paths={"vault": "obsidian"})
        >>> resolve_vault_base(ws, cfg).name
        'obsidian'
    """
    if cfg is not None and cfg.paths.vault:
        return _resolve_vault_relative(content_root, cfg.paths.vault)
    return vault_root(content_root)


def user_scope_root(vault: Path, scope: str) -> Path:
    """Return ``vault/users/<scope>`` (resolved).

    Args:
        vault (Path): Resolved vault root under ``second_brain``.
        scope (str): User scope directory name.

    Returns:
        Path: Resolved ``vault/users/<scope>``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> v = vault_root(Path(tempfile.mkdtemp()))
        >>> user_scope_root(v, "owner").name
        'owner'
    """

    s = scope.strip()
    if not s or s in (".", "..") or "/" in s or "\\" in s:
        msg = f"invalid scope {scope!r}"
        raise SecondBrainPathError(msg)
    return (vault / "users" / s).resolve()


def resolve_scope_root(
    content_root: Path,
    cfg: SecondBrainWorkspaceConfig | None,
    scope: str | None,
) -> Path:
    """Return the resolved scope directory for wiki/raw/outputs resolution.

    Custom ``paths.vault`` applies only to ``default_scope``; other scopes keep the
    legacy ``second_brain/users/<scope>/`` layout.

    Args:
        content_root (Path): Workspace content root.
        cfg (SecondBrainWorkspaceConfig | None): Second Brain workspace slice.
        scope (str | None): Caller scope override.

    Returns:
        Path: Resolved scope root directory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / "obsidian" / "alex_AI").mkdir(parents=True)
        >>> cfg = SecondBrainWorkspaceConfig(default_scope="owner", paths={"vault": "obsidian/alex_AI"})
        >>> resolve_scope_root(ws, cfg, None).name
        'alex_AI'
    """
    sc = effective_scope(scope, cfg)
    if cfg is not None and cfg.paths.vault and sc == cfg.default_scope.strip():
        return resolve_vault_base(content_root, cfg)
    return user_scope_root(vault_root(content_root), sc)


def display_scope_root_relative(content_root: Path, scope_root: Path) -> str:
    """Return *scope_root* as a POSIX path relative to *content_root*.

    Args:
        content_root (Path): Workspace content root.
        scope_root (Path): Resolved scope directory.

    Returns:
        str: Workspace-relative POSIX path for operator display.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> scope = ws / "second_brain" / "users" / "owner"
        >>> _ = scope.mkdir(parents=True)
        >>> display_scope_root_relative(ws, scope)
        'second_brain/users/owner'
    """
    root = content_root.expanduser().resolve()
    return scope_root.expanduser().resolve().relative_to(root).as_posix()


def shared_wiki_root(vault: Path) -> Path:
    """Return ``vault/shared/wiki`` (may not exist yet).

    Args:
        vault (Path): Resolved legacy ``second_brain`` vault root.

    Returns:
        Path: Resolved shared wiki directory path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> v = vault_root(Path(tempfile.mkdtemp()))
        >>> shared_wiki_root(v).name
        'wiki'
    """

    return (vault / "shared" / "wiki").resolve()


def wiki_dir_for_scope(scope_root: Path) -> Path:
    """Return ``<scope_root>/wiki``.

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        Path: Resolved ``wiki`` subdirectory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> wiki_dir_for_scope(Path(tempfile.mkdtemp())).name
        'wiki'
    """

    return (scope_root / "wiki").resolve()


def raw_dir_for_scope(scope_root: Path) -> Path:
    """Return ``<scope_root>/raw``.

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        Path: Resolved ``raw`` subdirectory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> raw_dir_for_scope(Path(tempfile.mkdtemp())).name
        'raw'
    """

    return (scope_root / "raw").resolve()


def outputs_dir_for_scope(scope_root: Path) -> Path:
    """Return ``<scope_root>/outputs``.

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        Path: Resolved ``outputs`` subdirectory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> outputs_dir_for_scope(Path(tempfile.mkdtemp())).name
        'outputs'
    """

    return (scope_root / "outputs").resolve()


def assert_wiki_relative_safe(rel: str) -> str:
    """Normalise a wiki-relative path fragment; reject traversal.

    Args:
        rel (str): Path relative to ``wiki/`` (POSIX separators).

    Returns:
        str: Normalised relative path.

    Raises:
        SecondBrainPathError: When unsafe.

    Examples:
        >>> assert_wiki_relative_safe("a/b")
        'a/b'
    """

    text = rel.strip().replace("\\", "/").lstrip("/")
    if not text:
        msg = "wiki path must be non-empty"
        raise SecondBrainPathError(msg)
    parts = text.split("/")
    if ".." in parts or parts[0] == "..":
        msg = "wiki path must not contain '..' components"
        raise SecondBrainPathError(msg)
    return text


def resolve_wiki_file(
    *,
    wiki_root: Path,
    workspace_root: Path,
    rel_path: str,
) -> Path:
    """Resolve ``rel_path`` under ``wiki_root``; enforce containment + ``.llmignore`` guard.

    Args:
        wiki_root (Path): Resolved ``wiki/`` root directory.
        workspace_root (Path): Workspace content root for ``.llmignore`` checks.
        rel_path (str): Wiki-relative path fragment.

    Returns:
        Path: Resolved absolute file path under ``wiki_root``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> wiki = ws / "wiki"
        >>> _ = wiki.mkdir()
        >>> out = resolve_wiki_file(wiki_root=wiki, workspace_root=ws, rel_path="x.md")
        >>> out.parent.resolve() == wiki.resolve()
        True
    """

    safe = assert_wiki_relative_safe(rel_path)
    candidate = (wiki_root / safe).resolve()
    wiki_r = wiki_root.resolve()
    try:
        candidate.relative_to(wiki_r)
    except ValueError as exc:
        msg = f"path {rel_path!r} escapes wiki root"
        raise SecondBrainPathError(msg) from exc
    if is_llmignored(candidate, workspace_root):
        msg = f"path {rel_path!r} is under quarantined .llmignore/"
        raise SecondBrainPathError(msg)
    return candidate


def resolve_raw_file(
    *,
    raw_root: Path,
    workspace_root: Path,
    rel_path: str,
) -> Path:
    """Resolve a path under ``raw_root`` (relative to ``raw/``).

    Args:
        raw_root (Path): Resolved ``raw/`` directory for the scope.
        workspace_root (Path): Workspace content root for ``.llmignore`` checks.
        rel_path (str): Path relative to ``raw_root``.

    Returns:
        Path: Resolved absolute file path under ``raw_root``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> raw = ws / "raw"
        >>> _ = raw.mkdir()
        >>> out = resolve_raw_file(raw_root=raw, workspace_root=ws, rel_path="f.md")
        >>> out.parent.resolve() == raw.resolve()
        True
    """

    text = rel_path.strip().replace("\\", "/").lstrip("/")
    if not text or ".." in text.split("/"):
        msg = f"invalid raw path {rel_path!r}"
        raise SecondBrainPathError(msg)
    candidate = (raw_root / text).resolve()
    raw_r = raw_root.resolve()
    try:
        candidate.relative_to(raw_r)
    except ValueError as exc:
        msg = f"path {rel_path!r} escapes raw root"
        raise SecondBrainPathError(msg) from exc
    if is_llmignored(candidate, workspace_root):
        msg = f"path {rel_path!r} is under quarantined .llmignore/"
        raise SecondBrainPathError(msg)
    return candidate


def effective_scope(scope: str | None, cfg: SecondBrainWorkspaceConfig | None) -> str:
    """Return active scope name.

    Args:
        scope (str | None): Caller-provided scope when non-empty after strip.
        cfg (SecondBrainWorkspaceConfig | None): Workspace slice with ``default_scope``.

    Returns:
        str: Resolved scope id, defaulting to ``owner``.

    Examples:
        >>> effective_scope(None, None)
        'owner'
    """

    if scope and scope.strip():
        return scope.strip()
    if cfg and cfg.default_scope.strip():
        return cfg.default_scope.strip()
    return "owner"


__all__ = [
    "assert_wiki_relative_safe",
    "display_scope_root_relative",
    "effective_scope",
    "legacy_shared_vault_root",
    "outputs_dir_for_scope",
    "raw_dir_for_scope",
    "resolve_raw_file",
    "resolve_scope_root",
    "resolve_vault_base",
    "resolve_wiki_file",
    "shared_wiki_root",
    "user_scope_root",
    "vault_root",
    "wiki_dir_for_scope",
]
