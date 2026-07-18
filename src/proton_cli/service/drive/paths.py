"""Drive path helpers."""

from __future__ import annotations


def dir_of(path: str) -> str:
    p = path.rstrip("/")
    i = p.rfind("/")
    if i <= 0:
        return "/"
    return p[:i]


def base_of(path: str) -> str:
    p = path.rstrip("/")
    i = p.rfind("/")
    return p[i + 1 :]


def normalize_path(path: str) -> str:
    p = path.strip()
    if not p or p == ".":
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    return p
