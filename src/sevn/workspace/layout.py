"""Resolved filesystem layout for a workspace (content root + ``.sevn`` paths).

Module: sevn.workspace.layout
Depends: sevn.config.workspace_config

Exports:
    WorkspaceLayout — absolute paths derived from ``sevn.json`` location + config.

Examples:
    >>> from pathlib import Path
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> p = Path("/tmp/w/sevn.json")
    >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
    >>> Layout = WorkspaceLayout  # alias for doctest length
    >>> lay = Layout.from_config(p, cfg)
    >>> lay.content_root == p.parent.resolve()
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


@dataclass(frozen=True)
class WorkspaceLayout:
    """Canonical directories under the resolved content root."""

    sevn_json_path: Path
    content_root: Path

    @classmethod
    def from_config(cls, sevn_json_path: Path, config: WorkspaceConfig) -> WorkspaceLayout:
        """Resolve ``content_root`` from the config file path and ``workspace_root`` string.

                Args:
        sevn_json_path (Path): Absolute or relative path to ``sevn.json``.
        config (WorkspaceConfig): Parsed workspace config.

                Returns:
                    WorkspaceLayout: Frozen layout with resolved ``content_root``.

                Examples:
                    >>> from pathlib import Path
                    >>> from sevn.config.workspace_config import WorkspaceConfig
                    >>> cfg = WorkspaceConfig.minimal(workspace_root="deep")
                    >>> base = Path("/tmp/repo")
                    >>> lay = WorkspaceLayout.from_config(base / "sevn.json", cfg)
                    >>> lay.content_root == (base / "deep").resolve()
                    True
        """
        cfg_path = sevn_json_path.expanduser().resolve()
        base = cfg_path.parent
        wr = Path(config.workspace_root).expanduser()
        root = wr.resolve() if wr.is_absolute() else (base / wr).resolve()
        return cls(sevn_json_path=cfg_path, content_root=root)

    @property
    def dot_sevn(self) -> Path:
        """Operator-local artefacts (SQLite, traces, exports).

        Returns:
            Path: ``<content_root>/.sevn``.

        Examples:
            >>> isinstance(WorkspaceLayout(Path("/x/s.json"), Path("/r")).dot_sevn, Path)
            True
        """
        return self.content_root / ".sevn"

    @property
    def logs_dir(self) -> Path:
        """Default log directory under the content root.

            Returns:
                Path: ``<content_root>/logs``.

        Examples:
            >>> WorkspaceLayout(Path("/a/sevn.json"), Path("/w")).logs_dir == Path("/w/logs")
            True
        """
        return self.content_root / "logs"

    def traces_dir(self, config: WorkspaceConfig) -> Path:
        """Prefer the first ``jsonl_file`` sink path; otherwise ``.sevn/traces``.

                Args:
        config (WorkspaceConfig): Parsed config (`tracing.sinks`).

                Returns:
                    Path: Directory to store JSONL traces under ``content_root``.

                Examples:
                    >>> from sevn.config.workspace_config import (
                    ...     TraceSinkEntry,
                    ...     TracingConfig,
                    ...     WorkspaceConfig,
                    ... )
                    >>> cfg = WorkspaceConfig.minimal(
                    ...     tracing=TracingConfig(
                    ...         sinks=[TraceSinkEntry(sink_type="jsonl_file", path=".sevn/t/")],
                    ...     ),
                    ... )
                    >>> lay = WorkspaceLayout(Path("/r/sevn.json"), Path("/r"))
                    >>> lay.traces_dir(cfg) == Path("/r/.sevn/t")
                    True
        """
        if config.tracing and config.tracing.sinks:
            for sink in config.tracing.sinks:
                if sink.sink_type == "jsonl_file" and sink.path:
                    rel = sink.path.strip().strip('"').strip("'")
                    target = (self.content_root / rel).resolve()
                    if rel.endswith(("/", "\\")):
                        return target
                    if target.suffix in (".jsonl", ".json"):
                        return target.parent
                    return target
        return self.dot_sevn / "traces"

    @property
    def turn_bundles_dir(self) -> Path:
        """Per-turn diagnostic JSONL bundles (``<content_root>/.sevn/turns``).

        Sits alongside the default ``.sevn/traces`` JSONL sink directory.

        Returns:
            Path: Turn-bundle root containing per-day ``<DDMMYY>/`` subfolders.

        Examples:
            >>> WorkspaceLayout(Path("/a/sevn.json"), Path("/w")).turn_bundles_dir == Path(
            ...     "/w/.sevn/turns"
            ... )
            True
        """
        return self.dot_sevn / "turns"
