"""Idempotent stub ingest (`specs/27-second-brain.md` §2.2).

Exports:
    run_ingest_stub — create or refresh stub page under the active layout capture role.
"""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import SecondBrainWorkspaceConfig
from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys, split_frontmatter
from sevn.second_brain.ingest import (
    _append_log,
    _ensure_index_entry,
    _ingest_page_path,
    _resolve_ingest_cfg,
)
from sevn.second_brain.paths import VaultLayout, effective_scope, resolve_raw_file


def run_ingest_stub(
    *,
    workspace_root: Path,
    vault_users_scope: Path,
    raw_relpath: str,
    sevn_source: str,
    sb_cfg: SecondBrainWorkspaceConfig | None = None,
    scope: str | None = None,
) -> dict[str, object]:
    """Create or refresh stub under the capture role; update index + log.

    Args:
        workspace_root (Path): Workspace content root (``sevn.json`` directory).
        vault_users_scope (Path): Resolved ``users/<scope>/`` directory for this vault user.
        raw_relpath (str): Path relative to the sources role directory.
        sevn_source (str): Provenance label stored in frontmatter.
        sb_cfg (SecondBrainWorkspaceConfig | None): Second Brain slice for layout resolution.
        scope (str | None): Scope id when ``sb_cfg`` is set.

    Returns:
        dict[str, object]: ``path``, ``promoted``, and ``raw`` fields describing the outcome.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> scope = ws / "u"
        >>> raw = scope / "raw"
        >>> _ = raw.mkdir(parents=True)
        >>> _ = (raw / "n.md").write_text("x", encoding="utf-8")
        >>> out = run_ingest_stub(
        ...     workspace_root=ws,
        ...     vault_users_scope=scope,
        ...     raw_relpath="n.md",
        ...     sevn_source="doctest",
        ... )
        >>> isinstance(out["path"], str)
        True
    """

    cfg = _resolve_ingest_cfg(
        workspace_root=workspace_root,
        vault_users_scope=vault_users_scope,
        sb_cfg=sb_cfg,
        scope=scope,
    )
    sc = effective_scope(scope, cfg)
    _ = vault_users_scope  # caller-resolved scope root; layout re-resolves via cfg + scope
    layout = VaultLayout(workspace_root, cfg, sc)
    raw_root = layout.role_dir("sources")
    log_path = layout.log_note()
    raw_file = resolve_raw_file(
        raw_root=raw_root, workspace_root=workspace_root, rel_path=raw_relpath
    )
    if not raw_file.is_file():
        msg = f"raw file missing: {raw_relpath}"
        raise FileNotFoundError(msg)

    stem = raw_file.stem
    page, rel_page = _ingest_page_path(layout, stem)
    source_relpath = raw_file.relative_to(layout.scope_root).as_posix()
    title = f"Stub: {stem}"
    layout_mode = cfg.layout

    promoted = False
    if page.is_file():
        full = page.read_text(encoding="utf-8")
        fm, _body, _ = split_frontmatter(full)
        if fm.get("stub") is False:
            promoted = True

    if promoted:
        _append_log(
            log_path,
            f"ingest_stub skipped body overwrite (stub promoted) for `{raw_relpath}`",
        )
        return {
            "path": rel_page,
            "promoted": True,
            "raw": raw_relpath,
        }

    body = (
        f"# {title}\n\nStub page for raw source `{source_relpath}`.\n\n[Source: {source_relpath}]\n"
    )
    if layout_mode == "para":
        fm_input: dict[str, object] = {
            "type": "Stub",
            "title": title,
            "stub": True,
            "source": sevn_source,
        }
    else:
        fm_input = {
            "type": "Stub",
            "title": title,
            "stub": True,
            "sevn_source": sevn_source,
            "sevn_evidence": [source_relpath],
        }
    fm = normalise_agent_keys(fm_input, layout=layout_mode)
    page.write_text(compose_page(fm, body), encoding="utf-8")
    _ensure_index_entry(layout, title=title, stem=stem, page_rel=rel_page)
    _append_log(log_path, f"stub ingest | `{raw_relpath}` → `{rel_page}`")

    return {
        "path": rel_page,
        "promoted": False,
        "raw": raw_relpath,
    }


__all__ = ["run_ingest_stub"]
