#!/usr/bin/env python3
"""Pre-commit hook: offline README regen for touched manifest ``source_globs``.

Module: scripts.readme_precommit
Depends: pathlib, sevn.cli.asyncio_util, sevn.docs.readme.*

Exports:
    main — regen affected README slugs and refresh fingerprints.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

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
from sevn.docs.readme.fingerprint import (  # noqa: E402
    default_fingerprints_path,
    slugs_for_changed_paths,
    stamp_entry,
)
from sevn.docs.readme.manifest import get_entry, load_manifest  # noqa: E402
from sevn.docs.readme.render import write_readme  # noqa: E402
from sevn.docs.readme.settings import (  # noqa: E402
    default_offline_mode,
    provider_config_from_settings,
)


def main(argv: list[str] | None = None) -> int:
    """Regenerate READMEs for manifest slugs touched by ``argv`` paths.

    Args:
        argv (list[str] | None): Repo-relative paths from pre-commit; skips when empty.

    Returns:
        int: ``0`` on success.

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

    for slug in slugs:
        entry = get_entry(manifest, slug)
        if entry.curated:
            stamp_entry(
                repo_root,
                slug=slug,
                source_globs=entry.source_globs,
                fingerprints_path=fingerprints_path,
            )
            print(f"readme-precommit: stamped {slug} (curated)")
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
        print(f"readme-precommit: updated {rel.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
