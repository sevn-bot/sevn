"""Shared sevn.bot UI style assets (copied from ``styles/sevn/style`` via ``make styles-build``).

Module: sevn.ui.style
Depends: pathlib, fastapi, importlib.resources

Exports:
    serve_style_asset — path-traversal-safe static file handler.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, Response

STYLE_STATIC_ROOT: Path = Path(__file__).resolve().parent

_STYLE_MIME: dict[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


def _dev_source_style_root() -> Path | None:
    """Return ``styles/sevn/style`` when present in a repo checkout.

    Returns:
        Path | None: Source tree path, or ``None`` when not found.

    Examples:
        >>> root = _dev_source_style_root()
        >>> root is None or (root / "index.css").is_file()
        True
    """
    for parent in STYLE_STATIC_ROOT.parents:
        candidate = parent / "styles" / "sevn" / "style"
        if (candidate / "index.css").is_file():
            return candidate.resolve()
    return None


def _style_search_roots() -> list[Path]:
    """Ordered directories to probe for a style asset.

    Returns:
        list[Path]: Packaged copy, then optional repo ``styles/sevn/style``.

    Examples:
        >>> roots = _style_search_roots()
        >>> len(roots) >= 1
        True
    """
    roots: list[Path] = [STYLE_STATIC_ROOT]
    dev = _dev_source_style_root()
    if dev is not None and dev not in roots:
        roots.append(dev)
    return roots


def _read_from_package(rel: str) -> tuple[bytes, str] | None:
    """Load asset bytes from the installed ``sevn.ui.style`` package data.

    Args:
        rel (str): Relative path under the style root.

    Returns:
        tuple[bytes, str] | None: Body and media type, or ``None`` if missing.

    Examples:
        >>> out = _read_from_package("index.css")
        >>> out is None or out[0].startswith(b"/*")
        True
    """
    try:
        ref = resources.files("sevn.ui.style") / rel
        if ref.is_file():
            media = _STYLE_MIME.get(Path(rel).suffix.lower(), "application/octet-stream")
            return ref.read_bytes(), media
    except (OSError, TypeError, ValueError, FileNotFoundError):
        return None
    return None


def serve_style_asset(asset_path: str) -> Response:
    """Serve a file from the packaged style tree with path traversal protection.

    Args:
        asset_path (str): Relative path under the style root.

    Returns:
        Response: ``FileResponse`` or 404 JSON.

    Examples:
        >>> isinstance(serve_style_asset("index.css"), Response)
        True
    """
    rel = asset_path.lstrip("/")
    if not rel:
        rel = "index.css"

    for root in _style_search_roots():
        root_resolved = root.resolve()
        candidate = (root_resolved / rel).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            continue
        if candidate.is_file():
            media = _STYLE_MIME.get(candidate.suffix.lower(), "application/octet-stream")
            return FileResponse(candidate, media_type=media)

    packaged = _read_from_package(rel)
    if packaged is not None:
        body, media = packaged
        return Response(content=body, media_type=media)

    return JSONResponse(status_code=404, content={"error": "not_found"})


__all__ = ["STYLE_STATIC_ROOT", "serve_style_asset"]
