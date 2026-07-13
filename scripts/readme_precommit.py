#!/usr/bin/env python3
"""Pre-commit hook: keep manifest READMEs in sync with touched ``source_globs``.

Module: scripts.readme_precommit
Depends: os, subprocess, pathlib, sevn.cli.asyncio_util, sevn.docs.readme.*

Behaviour per affected slug:

* **Non-curated** entries are regenerated offline (``write_readme``) — the body is a
  machine artefact.
* **Curated** entries never get their body overwritten by the generator. Instead, when
  an agent runner is available and not disabled, the ``readme-curator`` agent edits the
  body to match the staged source diff (``sevn readme curate --staged``); the result is
  validated and staged. When the agent is disabled (``SEVN_README_AGENT=0``), unavailable
  (offline / CLI missing), or fails, the hook falls back to a fingerprint-only stamp so
  the commit still proceeds — the curated prose is never clobbered either way.

Set ``SEVN_README_AGENT=0`` to skip the agent (stamp-only). Set ``SEVN_README_AGENT=strict``
to fail the commit when the agent errors or produces template drift.

Exports:
    main — sync affected README slugs (curate curated, regen the rest).

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sevn.cli.asyncio_util import run_sync_coro  # noqa: E402
from sevn.cli.commands.readme_cmd import (  # noqa: E402
    _load_workspace_settings,
    _manifest_path,
    _resolve_repo_root,
)
from sevn.docs.readme.curate import curate_entry, resolve_runner  # noqa: E402
from sevn.docs.readme.fingerprint import (  # noqa: E402
    default_fingerprints_path,
    slugs_for_changed_paths,
    stamp_entry,
)
from sevn.docs.readme.manifest import ReadmeEntry, get_entry, load_manifest  # noqa: E402
from sevn.docs.readme.render import write_readme  # noqa: E402
from sevn.docs.readme.settings import (  # noqa: E402
    default_offline_mode,
    provider_config_from_settings,
)


def _agent_mode() -> str:
    """Return the curator agent mode from ``SEVN_README_AGENT``.

    Returns:
        str: ``"on"`` (default, auto-edit & stage), ``"off"`` (stamp-only), or
        ``"strict"`` (fail the commit on agent error/drift).

    Examples:
        >>> import os
        >>> os.environ.pop("SEVN_README_AGENT", None) and False or _agent_mode()
        'on'
    """
    raw = (os.environ.get("SEVN_README_AGENT") or "").strip().lower()
    if raw in {"0", "off", "false", "no"}:
        return "off"
    if raw == "strict":
        return "strict"
    return "on"


def _git_add(repo_root: Path, *rel_paths: str) -> None:
    """Stage ``rel_paths`` (best-effort) so hook edits land in the commit.

    Args:
        repo_root (Path): Repository root.
        rel_paths (str): Repo-relative paths to stage.

    Examples:
        >>> import tempfile
        >>> _git_add(Path(tempfile.mkdtemp()), "README.md") is None
        True
    """
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "--", *rel_paths],
        capture_output=True,
        check=False,
    )


def _stamp(repo_root: Path, entry: ReadmeEntry, fingerprints_path: Path) -> None:
    """Refresh one curated entry's source fingerprint and stage the store.

    Args:
        repo_root (Path): Repository root.
        entry (ReadmeEntry): Curated manifest row.
        fingerprints_path (Path): ``_fingerprints.json`` path.

    Examples:
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = (td / "a.py").write_text("x = 1\\n", encoding="utf-8")
        >>> e = ReadmeEntry("g", "G", "s", "subsystem", "g", "o.md", ("a.py",), (),
        ...     curated=True)
        >>> _stamp(td, e, td / "_fingerprints.json") is None
        True
    """
    stamp_entry(
        repo_root,
        slug=entry.slug,
        source_globs=entry.source_globs,
        fingerprints_path=fingerprints_path,
    )
    _git_add(repo_root, str(fingerprints_path.relative_to(repo_root)))


def _curate_or_stamp(
    repo_root: Path,
    entry: ReadmeEntry,
    fingerprints_path: Path,
    *,
    mode: str,
) -> int:
    """Curate a curated entry via the agent, falling back to stamp-only.

    Args:
        repo_root (Path): Repository root.
        entry (ReadmeEntry): Curated manifest row.
        fingerprints_path (Path): ``_fingerprints.json`` path.
        mode (str): ``on`` | ``strict`` (``off`` is handled by the caller).

    Returns:
        int: ``0`` on success; ``1`` only in ``strict`` mode on agent error/drift.

    Examples:
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = (td / "a.py").write_text("x = 1\\n", encoding="utf-8")
        >>> e = ReadmeEntry("g", "G", "s", "subsystem", "g", "docs/readmes/g.md",
        ...     ("a.py",), (), curated=True, template="docs/readmes/_templates/none.md")
        >>> _curate_or_stamp(td, e, td / "_fingerprints.json", mode="on")
        0
    """
    if resolve_runner() is None:
        print(f"readme-precommit: {entry.slug} curated — no agent runner; stamped only")
        _stamp(repo_root, entry, fingerprints_path)
        return 0

    result = curate_entry(repo_root, entry, staged=True, validate=True)
    if result.status in {"updated", "unchanged"}:
        if result.status == "updated":
            _git_add(repo_root, entry.output)
        _stamp(repo_root, entry, fingerprints_path)
        print(f"readme-precommit: curated {entry.slug} ({result.status})")
        return 0

    # error / invalid / skipped — never clobber curated prose.
    for err in result.template_errors:
        print(f"readme-precommit: {entry.slug} template {err}", file=sys.stderr)
    if mode == "strict":
        print(
            f"readme-precommit: {entry.slug} curate {result.status} ({result.detail}); "
            "strict mode — commit blocked",
            file=sys.stderr,
        )
        return 1
    print(
        f"readme-precommit: {entry.slug} curate {result.status} ({result.detail}); stamped only",
        file=sys.stderr,
    )
    _stamp(repo_root, entry, fingerprints_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Regenerate READMEs for manifest slugs touched by ``argv`` paths.

    Args:
        argv (list[str] | None): Repo-relative paths from pre-commit; skips when empty.

    Returns:
        int: ``0`` on success (``1`` only when strict-mode curation fails).

    Examples:
        >>> main([]) == 0
        True
    """
    paths = list(argv if argv is not None else sys.argv[1:])
    if not paths:
        return 0

    repo_root = _resolve_repo_root(None)
    _, settings = _load_workspace_settings(repo_root)
    if not settings.enabled:
        return 0

    manifest = load_manifest(_manifest_path(repo_root, settings))
    slugs = slugs_for_changed_paths(
        repo_root,
        entries=manifest.entries,
        changed_paths=paths,
    )
    if not slugs:
        return 0

    fingerprints_path = default_fingerprints_path(repo_root)
    provider_config = provider_config_from_settings(
        settings,
        offline=default_offline_mode(settings),
    )
    mode = _agent_mode()
    exit_code = 0

    for slug in slugs:
        entry = get_entry(manifest, slug)
        if entry.curated:
            if mode == "off":
                _stamp(repo_root, entry, fingerprints_path)
                print(f"readme-precommit: stamped {slug} (curated, agent off)")
                continue
            exit_code |= _curate_or_stamp(repo_root, entry, fingerprints_path, mode=mode)
            continue
        path = run_sync_coro(
            write_readme(
                repo_root=repo_root,
                entry=entry,
                config=provider_config,
                fingerprints_path=fingerprints_path,
                manifest=manifest,
            )
        )
        rel = path.relative_to(repo_root)
        _git_add(repo_root, rel.as_posix())
        print(f"readme-precommit: updated {rel.as_posix()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
