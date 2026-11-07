"""Fake CLI runtime archives in the three vendor shapes (plan 0025 W0.2).

Every payload is a tiny POSIX shell script that prints a marker. Nothing here is
a real vendor binary.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile


def script(marker: str) -> bytes:
    return f'#!/bin/sh\necho "{marker}"\n'.encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tar_gz(files: dict[str, tuple[bytes, int]], *, top: str | None = None) -> bytes:
    """``files`` maps member path to ``(data, mode)``. ``top`` prefixes every member."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if top is not None:
            info = tarfile.TarInfo(top)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, (data, mode) in files.items():
            member = f"{top}/{name}" if top is not None else name
            info = tarfile.TarInfo(member)
            info.size = len(data)
            info.mode = mode
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def zip_bytes(files: dict[str, tuple[bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (data, mode) in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def cursor_tree(marker: str) -> dict[str, tuple[bytes, int]]:
    """cursor-agent's shape: a wrapper that runs a bundled ``node`` beside it."""
    wrapper = b'#!/bin/sh\nhere="$(dirname "$0")"\nexec "$here/node" "$here/index.js"\n'
    node = b'#!/bin/sh\necho "node $(cat "$1")"\n'
    return {
        "cursor-agent": (wrapper, 0o755),
        "node": (node, 0o755),
        "index.js": (marker.encode(), 0o644),
        "lib/native.node": (b"not a real module", 0o644),
    }
