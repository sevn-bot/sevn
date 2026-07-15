"""Vault path resolution and safety (`specs/27-second-brain.md` sections 3.2 and 4.1).

Module: sevn.second_brain.paths
Depends: pathlib, sevn.config.workspace_config, sevn.security.llmignore, sevn.tools.paths

Exports:
    VaultLayout — layout-aware role resolver (legacy | PARA).
    vault_root — ``workspace/second_brain`` (legacy base).
    resolve_vault_base — legacy or custom configured vault directory.
    resolve_scope_root — resolved ``users/<scope>/`` or custom vault root.
    display_scope_root_relative — operator-facing workspace-relative path.
    user_scope_root — ``users/<scope>/`` under legacy vault base.
    shared_wiki_root — ``shared/wiki/`` when present (legacy overlay).
    wiki_dir_for_scope — legacy shim → ``VaultLayout.role_dir("curated")``.
    raw_dir_for_scope — legacy shim → ``VaultLayout.role_dir("sources")``.
    outputs_dir_for_scope — legacy shim → ``VaultLayout.role_dir("outputs")``.
    content_roots_for — convenience wrapper for ``VaultLayout.content_roots()``.
    assert_wiki_relative_safe — reject ``..`` and absolute fragments.
    resolve_wiki_file — resolved path under wiki with llmignore guard.
    resolve_raw_file — resolved path under ``raw/`` with llmignore guard.
    resolve_vault_note_file — resolve note paths across layout content roots.
    effective_scope — active scope name from args and config.
    legacy_shared_vault_root — ``<content_root>/second_brain`` for shared overlay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from sevn.config.workspace_config import SecondBrainWorkspaceConfig
from sevn.second_brain.errors import SecondBrainPathError
from sevn.security.llmignore import is_llmignored

LayoutRole = Literal[
    "capture",
    "projects",
    "areas",
    "curated",
    "archive",
    "templates",
    "sources",
    "outputs",
    "index_note",
    "log_note",
]

_LEGACY_ALIASED_ROLES = frozenset({"capture", "projects", "areas", "archive", "templates"})


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


class VaultLayout:
    """Map semantic layout roles to concrete vault paths (legacy or PARA).

    Args:
        content_root (Path): Workspace content root (directory with ``sevn.json``).
        cfg (SecondBrainWorkspaceConfig): Second Brain workspace slice (layout + para profile).
        scope (str | None): Caller scope override; defaults via :func:`effective_scope`.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), "owner")
        >>> layout.role_dir("curated").name
        'wiki'
    """

    def __init__(
        self,
        content_root: Path,
        cfg: SecondBrainWorkspaceConfig,
        scope: str | None,
    ) -> None:
        """Bind layout resolution to a workspace scope.

        Args:
            content_root (Path): Workspace content root.
            cfg (SecondBrainWorkspaceConfig): Second Brain workspace slice.
            scope (str | None): Caller scope override.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
            >>> layout.role_dir("curated").name
            'wiki'
        """
        self._content_root = content_root.expanduser().resolve()
        self._cfg = cfg
        self._scope = effective_scope(scope, cfg)
        self._scope_root = resolve_scope_root(self._content_root, cfg, self._scope)

    @property
    def layout_kind(self) -> Literal["legacy", "para"]:
        """Configured vault layout mode (``legacy`` or ``para``).

        Returns:
            Literal["legacy", "para"]: Value of ``second_brain.layout`` on this instance.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> VaultLayout(ws, SecondBrainWorkspaceConfig(), None).layout_kind
            'legacy'
        """
        return self._cfg.layout

    @property
    def scope_root(self) -> Path:
        """Resolved scope directory for this layout instance.

        Returns:
            Path: Scope root (legacy ``users/<scope>/`` or custom ``paths.vault``).

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), "owner")
            >>> layout.scope_root.name
            'owner'
        """
        return self._scope_root

    def role_dir(self, role: LayoutRole) -> Path:
        """Return the resolved path for a semantic layout role.

        Args:
            role (LayoutRole): Semantic role name (``curated``, ``sources``, ``capture``, …).

        Returns:
            Path: Resolved directory or note file path for the role.

        Raises:
            SecondBrainPathError: When ``role`` is not recognised.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
            >>> layout.role_dir("sources").name
            'raw'
        """
        if self._cfg.layout == "para":
            return self._para_role_dir(role)
        return self._legacy_role_dir(role)

    def content_roots(self) -> tuple[Path, ...]:
        """Return content roots for search, index, and lint scanning.

        Legacy layout returns ``(curated,)``; PARA returns inbox, projects, areas,
        and resources — excluding templates, archive, and machinery subdirs.

        Returns:
            tuple[Path, ...]: Resolved content root directories.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
            >>> len(layout.content_roots())
            1
        """
        if self._cfg.layout == "para":
            return (
                self.role_dir("capture"),
                self.role_dir("projects"),
                self.role_dir("areas"),
                self.role_dir("curated"),
            )
        return (self.role_dir("curated"),)

    def index_note(self) -> Path:
        """Return the resolved vault home / index note path.

        Returns:
            Path: ``wiki/index.md`` (legacy) or vault-root ``index.md`` (PARA).

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
            >>> layout.index_note().name
            'index.md'
        """
        return self.role_dir("index_note")

    def log_note(self) -> Path:
        """Return the resolved vault log note path.

        Returns:
            Path: ``wiki/log.md`` (legacy) or vault-root ``log.md`` (PARA).

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
            >>> layout.log_note().name
            'log.md'
        """
        return self.role_dir("log_note")

    def _legacy_role_dir(self, role: LayoutRole) -> Path:
        """Resolve a role path under the legacy ``wiki/raw/outputs`` layout.

        Args:
            role (LayoutRole): Semantic role to resolve.

        Returns:
            Path: Resolved directory or note path under the scope root.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
            >>> layout._legacy_role_dir("sources").name
            'raw'
        """
        root = self._scope_root
        if role in _LEGACY_ALIASED_ROLES or role == "curated":
            return (root / "wiki").resolve()
        if role == "sources":
            return (root / "raw").resolve()
        if role == "outputs":
            return (root / "outputs").resolve()
        if role == "index_note":
            return (root / "wiki" / "index.md").resolve()
        if role == "log_note":
            return (root / "wiki" / "log.md").resolve()
        msg = f"unknown layout role {role!r}"
        raise SecondBrainPathError(msg)

    def _para_role_dir(self, role: LayoutRole) -> Path:
        """Resolve a role path under the PARA profile from ``cfg.para``.

        Args:
            role (LayoutRole): Semantic role to resolve.

        Returns:
            Path: Resolved directory or note path under the vault root.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
            >>> ws = Path(tempfile.mkdtemp())
            >>> cfg = SecondBrainWorkspaceConfig(layout="para")
            >>> layout = VaultLayout(ws, cfg, None)
            >>> layout._para_role_dir("capture").name
            '00_Inbox'
        """
        root = self._scope_root
        para = self._cfg.para
        if role == "capture":
            return (root / para.inbox).resolve()
        if role == "projects":
            return (root / para.projects).resolve()
        if role == "areas":
            return (root / para.areas).resolve()
        if role == "curated":
            return (root / para.resources).resolve()
        if role == "archive":
            return (root / para.archive).resolve()
        if role == "templates":
            return (root / para.templates).resolve()
        if role == "sources":
            return (root / para.resources / para.sources_subdir).resolve()
        if role == "outputs":
            return (root / para.resources / para.outputs_subdir).resolve()
        if role == "index_note":
            return (root / para.index_note).resolve()
        if role == "log_note":
            return (root / para.log_note).resolve()
        msg = f"unknown layout role {role!r}"
        raise SecondBrainPathError(msg)


def content_roots_for(
    content_root: Path,
    cfg: SecondBrainWorkspaceConfig | None,
    scope: str | None,
) -> tuple[Path, ...]:
    """Return :meth:`VaultLayout.content_roots` for the active layout.

    Args:
        content_root (Path): Workspace content root.
        cfg (SecondBrainWorkspaceConfig | None): Second Brain slice; defaults to legacy.
        scope (str | None): Optional scope override.

    Returns:
        tuple[Path, ...]: Resolved content root directories.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> roots = content_roots_for(Path(tempfile.mkdtemp()), None, "owner")
        >>> len(roots)
        1
    """
    sb = cfg or SecondBrainWorkspaceConfig()
    return VaultLayout(content_root, sb, scope).content_roots()


def wiki_dir_for_scope(scope_root: Path) -> Path:
    """Return ``<scope_root>/wiki`` (legacy shim for :meth:`VaultLayout.role_dir` curated).

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        Path: Resolved ``wiki`` subdirectory (legacy layout curated root).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> wiki_dir_for_scope(Path(tempfile.mkdtemp())).name
        'wiki'
    """

    return (scope_root / "wiki").resolve()


def raw_dir_for_scope(scope_root: Path) -> Path:
    """Return ``<scope_root>/raw`` (legacy shim for :meth:`VaultLayout.role_dir` sources).

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        Path: Resolved ``raw`` subdirectory (legacy layout sources root).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> raw_dir_for_scope(Path(tempfile.mkdtemp())).name
        'raw'
    """

    return (scope_root / "raw").resolve()


def outputs_dir_for_scope(scope_root: Path) -> Path:
    """Return ``<scope_root>/outputs`` (legacy shim for :meth:`VaultLayout.role_dir` outputs).

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

    text = rel.strip().replace("\\", "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":" and text[0].isalpha()):
        msg = "wiki path must be relative (no absolute path)"
        raise SecondBrainPathError(msg)
    text = text.lstrip("/")
    if not text:
        msg = "wiki path must be non-empty"
        raise SecondBrainPathError(msg)
    parts = text.split("/")
    if ".." in parts or parts[0] == "..":
        msg = "wiki path must not contain '..' components"
        raise SecondBrainPathError(msg)
    return text


def _path_is_under(path: Path, root: Path) -> bool:
    """Return whether ``path`` resolves under ``root``.

    Args:
        path (Path): Candidate file or directory.
        root (Path): Containing root directory.

    Returns:
        bool: ``True`` when ``path`` is equal to or nested under ``root``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> child = root / "a" / "b.md"
        >>> _path_is_under(child, root)
        True
    """
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_vault_note_file(
    *,
    layout: VaultLayout,
    workspace_root: Path,
    rel_path: str,
) -> Path:
    """Resolve a note path for read/write across layout content roots.

    Accepts vault-relative paths (``00_Inbox/note.md`` in PARA) or paths relative
    to a single content root (``note.md`` under curated/resources). When multiple
    content roots exist and a bare filename matches more than one file, raises
    :class:`SecondBrainPathError`. When no file exists, defaults new paths to the
    curated/resources root unless the path clearly targets another role directory.

    Args:
        layout (VaultLayout): Active vault layout resolver.
        workspace_root (Path): Workspace content root for ``.llmignore`` checks.
        rel_path (str): Vault-relative or content-root-relative note path.

    Returns:
        Path: Resolved absolute note path.

    Raises:
        SecondBrainPathError: When the path is unsafe or ambiguous.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> vault = ws / "v"
        >>> _ = (vault / "wiki").mkdir(parents=True)
        >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), None)
        >>> out = resolve_vault_note_file(
        ...     layout=layout, workspace_root=ws, rel_path="wiki/x.md",
        ... )
        >>> out.name
        'x.md'
    """
    safe = assert_wiki_relative_safe(rel_path)
    vault_root = layout.scope_root.resolve()

    for reserved in (layout.index_note(), layout.log_note()):
        reserved_resolved = reserved.resolve()
        if safe == reserved_resolved.relative_to(vault_root).as_posix() and not is_llmignored(
            reserved_resolved, workspace_root
        ):
            return reserved_resolved
        if (
            "/" not in safe
            and safe == reserved_resolved.name
            and reserved_resolved.parent == vault_root
            and not is_llmignored(reserved_resolved, workspace_root)
        ):
            return reserved_resolved

    vault_candidate = (vault_root / safe).resolve()
    if _path_is_under(vault_candidate, vault_root) and not is_llmignored(
        vault_candidate,
        workspace_root,
    ):
        if vault_candidate.is_file():
            return vault_candidate
        if "/" in safe:
            parent = vault_candidate.parent
            if parent == vault_root:
                return vault_candidate
            for role in (
                "capture",
                "projects",
                "areas",
                "curated",
                "archive",
                "templates",
                "sources",
                "outputs",
            ):
                role_dir = layout.role_dir(role).resolve()
                if parent == role_dir or _path_is_under(vault_candidate, role_dir):
                    return vault_candidate

    matches: list[Path] = []
    for root in layout.content_roots():
        try:
            candidate = resolve_wiki_file(
                wiki_root=root,
                workspace_root=workspace_root,
                rel_path=safe,
            )
        except SecondBrainPathError:
            continue
        if candidate.is_file():
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        msg = f"ambiguous vault note path {rel_path!r}"
        raise SecondBrainPathError(msg)

    return resolve_wiki_file(
        wiki_root=layout.role_dir("curated"),
        workspace_root=workspace_root,
        rel_path=safe,
    )


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
    "LayoutRole",
    "VaultLayout",
    "assert_wiki_relative_safe",
    "content_roots_for",
    "display_scope_root_relative",
    "effective_scope",
    "legacy_shared_vault_root",
    "outputs_dir_for_scope",
    "raw_dir_for_scope",
    "resolve_raw_file",
    "resolve_scope_root",
    "resolve_vault_base",
    "resolve_vault_note_file",
    "resolve_wiki_file",
    "shared_wiki_root",
    "user_scope_root",
    "vault_root",
    "wiki_dir_for_scope",
]
