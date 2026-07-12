"""Draft file lifecycle for ``.sevn.json.draft`` (`specs/22-onboarding.md` §2.1, §4.3).

Module: sevn.onboarding.draft_store
Depends: fcntl (POSIX), json, pathlib, typing

Exports:
    draft_path — absolute path helper.
    lock_path — POSIX advisory lock file beside ``sevn.json``.
    read_draft — load JSON draft if present.
    write_draft — atomic-ish write under advisory lock.
    discard_draft — remove draft file.
    DraftLock — context manager for POSIX ``flock`` advisory lock.

Examples:
    >>> from pathlib import Path
    >>> from sevn.onboarding.draft_store import draft_path
    >>> draft_path(Path("/tmp/w/sevn.json")) == Path("/tmp/w/.sevn.json.draft")
    True
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from sevn.onboarding.errors import OnboardingDraftLockError

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

DRAFT_FILENAME = ".sevn.json.draft"
LOCK_FILENAME = ".sevn.json.draft.lock"


def draft_path(sevn_json_path: Path) -> Path:
    """Return the draft path beside ``sevn.json``.

    Args:
        sevn_json_path (Path): Path to ``sevn.json`` (file, not directory).

    Returns:
        Path: ``<parent>/.sevn.json.draft``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.onboarding.draft_store import draft_path
        >>> draft_path(Path("/x/sevn.json")).name
        '.sevn.json.draft'
    """
    return sevn_json_path.parent / DRAFT_FILENAME


def lock_path(sevn_json_path: Path) -> Path:
    """Return the POSIX lock file path beside ``sevn.json``.

    Args:
        sevn_json_path (Path): Path to ``sevn.json`` (file, not directory).

    Returns:
        Path: ``<parent>/.sevn.json.draft.lock``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.onboarding.draft_store import lock_path
        >>> lock_path(Path("/tmp/z/sevn.json")).name
        '.sevn.json.draft.lock'
    """
    return sevn_json_path.parent / LOCK_FILENAME


def read_draft(sevn_json_path: Path) -> dict[str, Any] | None:
    """Read draft JSON when the file exists.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.

    Returns:
        dict[str, Any] | None: Parsed object, or ``None`` when absent.

    Examples:
        >>> import json
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> dp = draft_path(sj)
        >>> _ = dp.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        >>> read_draft(sj)["schema_version"]
        1
    """
    path = draft_path(sevn_json_path)
    if not path.is_file():
        return None
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "draft must be a JSON object"
        raise ValueError(msg)
    return raw


def write_draft(sevn_json_path: Path, doc: dict[str, Any]) -> None:
    """Write ``doc`` to ``.sevn.json.draft`` while holding the advisory lock.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.
        doc (dict[str, Any]): Draft body.

    Raises:
        OnboardingDraftLockError: When the lock cannot be acquired (non-blocking).

    Examples:
        >>> import json
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.draft_store import read_draft, write_draft
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> sj.parent.mkdir(parents=True, exist_ok=True)
        >>> write_draft(sj, {"schema_version": 1})
        >>> read_draft(sj)["schema_version"]
        1
    """
    with DraftLock(sevn_json_path):
        path = draft_path(sevn_json_path)
        tmp = path.with_suffix(".tmp")
        payload = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


def discard_draft(sevn_json_path: Path) -> None:
    """Remove draft file if it exists.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.draft_store import discard_draft, draft_path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> _ = draft_path(sj).write_text("{}", encoding="utf-8")
        >>> discard_draft(sj)
        >>> draft_path(sj).is_file()
        False
    """
    path = draft_path(sevn_json_path)
    if path.is_file():
        path.unlink()


class DraftLock:
    """Advisory non-blocking lock aligned with CLI draft writers (`specs/23-cli.md`)."""

    def __init__(self, sevn_json_path: Path) -> None:
        """Capture the target ``sevn.json`` path for lock coordination.

        Args:
            sevn_json_path (Path): Workspace ``sevn.json`` path.

        Returns:
            None: Always.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.onboarding.draft_store import DraftLock
            >>> DraftLock(Path("/tmp/x/sevn.json"))._sevn_json_path.name
            'sevn.json'
        """
        self._sevn_json_path = sevn_json_path
        self._fh: Any = None

    def __enter__(self) -> DraftLock:
        """Acquire the advisory lock (no-op on Windows).

        Returns:
            DraftLock: Self for ``with`` binding.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.onboarding.draft_store import DraftLock
            >>> dl = DraftLock(Path("/tmp/y/sevn.json"))
            >>> dl.__enter__() is dl
            True
        """
        if sys.platform == "win32":
            return self
        import fcntl

        lp = lock_path(self._sevn_json_path)
        lp.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(lp, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._fh.close()
            self._fh = None
            msg = "another onboarding or writer holds .sevn.json.draft.lock"
            raise OnboardingDraftLockError(msg) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the lock and close the handle.

        Args:
            exc_type (type[BaseException] | None): Exception type if unwinding.
            exc (BaseException | None): Active exception instance.
            tb (TracebackType | None): Traceback object.

        Returns:
            None: Always.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.onboarding.draft_store import DraftLock
            >>> dl = DraftLock(Path("/tmp/z/sevn.json"))
            >>> dl.__exit__(None, None, None) is None
            True
        """
        if self._fh is None:
            return
        if sys.platform != "win32":
            import fcntl

            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
        self._fh = None
