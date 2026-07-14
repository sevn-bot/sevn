"""Manifest glob prefix helpers shared by scanner and curation.

Module: sevn.docs.readme.glob_paths
Depends: (none)

Exports:
    glob_dir_prefix — directory prefix from a manifest glob pattern.
    glob_to_pathspec — git pathspec prefix from a manifest glob.

Examples:
    >>> from sevn.docs.readme.glob_paths import glob_dir_prefix
    >>> glob_dir_prefix("src/sevn/gateway/**")
    'src/sevn/gateway/'
"""


def glob_dir_prefix(pattern: str) -> str:
    """Extract a directory prefix from a manifest glob pattern.

    Args:
        pattern (str): Manifest ``source_globs`` entry.

    Returns:
        str: Repo-relative directory prefix ending with ``/``.

    Examples:
        >>> glob_dir_prefix("src/sevn/gateway/**")
        'src/sevn/gateway/'
    """
    if pattern.endswith("/**"):
        return pattern[:-3] + "/"
    prefix = pattern.split("*", maxsplit=1)[0]
    if prefix.endswith("/"):
        return prefix
    if "/" in prefix:
        return prefix.rsplit("/", maxsplit=1)[0] + "/"
    return prefix + "/"


def glob_to_pathspec(glob: str) -> str:
    """Reduce a source glob to a git pathspec prefix (strip wildcard tail).

    Args:
        glob (str): A manifest source glob (e.g. ``src/sevn/gateway/**``).

    Returns:
        str: Pathspec usable with ``git diff -- <spec>``.

    Examples:
        >>> glob_to_pathspec("src/sevn/gateway/**")
        'src/sevn/gateway'
        >>> glob_to_pathspec("src/sevn/config/sections/subagents.py")
        'src/sevn/config/sections/subagents.py'
    """
    out: list[str] = []
    for part in glob.split("/"):
        if any(ch in part for ch in "*?[]"):
            break
        out.append(part)
    return "/".join(out) or glob
