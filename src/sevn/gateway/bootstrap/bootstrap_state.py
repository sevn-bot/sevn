"""USER.md bootstrap completion helpers without onboarding seed imports.

Module: sevn.gateway.bootstrap.bootstrap_state
Depends: pathlib, re, typing

Exports:
    bootstrap_completion_state — classify bootstrap from ``USER.md``.
    operator_name_from_user_md — resolved operator display name from ``USER.md``.

Examples:
    >>> from pathlib import Path
    >>> bootstrap_completion_state(Path("/nonexistent"), agent_name="Sevn")
    'missing'
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

_BOOTSTRAP_USER_INCOMPLETE_MARKER = "<!-- sevn-bootstrap:user-incomplete -->"
_NAME_PLACEHOLDER_VALUE = re.compile(r"^_\(.*\)_$")
BootstrapCompletionState = Literal["complete", "incomplete", "missing"]


def _user_md_field_value(text: str, field_label: str) -> str | None:
    """Return one ``- **Field:**`` value from ``USER.md`` body text.

    Args:
        text (str): Full ``USER.md`` contents.
        field_label (str): Label between ``**`` markers (e.g. ``Role``).

    Returns:
        str | None: Trimmed value, or ``None`` when the field line is absent.

    Examples:
        >>> _user_md_field_value("- **Role:** _(what you do)_", "Role")
        '_(what you do)_'
    """
    needle = f"**{field_label}:**"
    for line in text.splitlines():
        if needle not in line:
            continue
        _, _, tail = line.partition(needle)
        return tail.strip()
    return None


def _user_md_name_value(text: str) -> str | None:
    """Return the ``Name:`` field value from ``USER.md`` body text.

    Args:
        text (str): Full ``USER.md`` contents.

    Returns:
        str | None: Trimmed name value, or ``None`` when no ``Name:`` line exists.

    Examples:
        >>> _user_md_name_value("- **Name:** _(you)_\\n")
        '_(you)_'
    """
    return _user_md_field_value(text, "Name")


def operator_name_from_user_md(content_root: Path) -> str | None:
    """Return the operator's preferred name from ``USER.md`` when set.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        str | None: Trimmed ``Name:`` value, or ``None`` when ``USER.md`` is
            missing, unreadable, or still holds the bootstrap placeholder.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "USER.md").write_text("- **Name:** Alex\\n", encoding="utf-8")
        ...     operator_name_from_user_md(root)
        'Alex'
    """
    path = content_root / "USER.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    name_val = _user_md_name_value(text)
    if name_val is None:
        return None
    stripped = name_val.strip()
    if not stripped or _NAME_PLACEHOLDER_VALUE.fullmatch(stripped):
        return None
    return stripped


def bootstrap_completion_state(
    content_root: Path,
    *,
    agent_name: str,
) -> BootstrapCompletionState:
    """Classify bootstrap completion from ``USER.md`` (authoritative over DB cache).

    Args:
        content_root (Path): Resolved workspace content root.
        agent_name (str): Bot display name (reserved for template parity checks).

    Returns:
        BootstrapCompletionState: ``missing`` when ``USER.md`` absent;
            ``incomplete`` when the structural marker or placeholder ``Name:`` remains;
            else ``complete``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     bootstrap_completion_state(root, agent_name="Sevn")
        'missing'
    """
    _ = agent_name
    path = content_root / "USER.md"
    if not path.is_file():
        return "missing"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "missing"
    if _BOOTSTRAP_USER_INCOMPLETE_MARKER in text:
        return "incomplete"
    name_val = _user_md_name_value(text)
    if name_val is not None and _NAME_PLACEHOLDER_VALUE.fullmatch(name_val):
        return "incomplete"
    return "complete"
