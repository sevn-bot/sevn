"""Descriptor-relative access to already-authorized absolute paths.

No component is followed through a symlink, including components replaced
between authorization and opening. Directory descriptors pin the traversal.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sevn.domain.errors import DomainError


@contextmanager
def directory(path: Path, *, create: bool = False) -> Generator[int]:
    """Open an absolute directory without following any symlink."""
    if not path.is_absolute() or ".." in path.parts:
        raise DomainError("path_outside_workspace", "path is outside the workspace")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except (NotADirectoryError, OSError) as exc:
        raise DomainError("path_outside_workspace", "path is outside the workspace") from exc
    finally:
        os.close(descriptor)


@contextmanager
def regular_file(
    path: Path, *, write: bool = False, create_parents: bool = False
) -> Generator[int]:
    """Open a regular file; validate it before any truncation or chmod."""
    with directory(path.parent, create=create_parents) as parent:
        flags = os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_CREAT if write else os.O_RDONLY)
        try:
            descriptor = os.open(path.name, flags, 0o600, dir_fd=parent)
        except FileNotFoundError as exc:
            raise DomainError("not_found", "file not found") from exc
        except OSError as exc:
            raise DomainError("path_outside_workspace", "path is outside the workspace") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (write and info.st_nlink != 1):
                raise DomainError("path_outside_workspace", "path is outside the workspace")
            yield descriptor
        finally:
            os.close(descriptor)


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    """Write through a pinned descriptor, refusing symlinks and hardlinks."""
    with regular_file(path, write=True, create_parents=True) as descriptor:
        with os.fdopen(os.dup(descriptor), "r+", encoding="utf-8") as stream:
            # Avoid truncating a shim another command is currently executing.
            if not executable or stream.read() != content:
                stream.seek(0)
                stream.truncate(0)
                stream.write(content)
        if executable:
            os.fchmod(descriptor, 0o755)
