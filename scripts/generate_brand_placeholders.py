#!/usr/bin/env python3
"""Generate committed brand placeholder assets for the README pipeline (Wave 1).

Module: scripts.generate_brand_placeholders
Depends: pathlib, struct, zlib; optional PIL for labeled PNGs

Exports:
    main — write placeholder PNG/GIF/SVG files under docs/brand/assets/

Examples:
    >>> from pathlib import Path
    >>> Path(__file__).name.endswith('.py')
    True
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ASSETS = _REPO / "docs" / "brand" / "assets"

# Brand tokens from styles/sevn/style/tokens/colors.css
_BASE = (12, 10, 9)
_PRIMARY = (95, 177, 247)
_ACCENT = (255, 59, 59)
_MUTED = (38, 33, 29)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    """Pack one PNG chunk with length and CRC.

        Args:
    tag (bytes): Four-byte chunk type.
    data (bytes): Chunk payload.

        Returns:
            bytes: Length + type + data + CRC.

        Examples:
            >>> len(_png_chunk(b'IHDR', b'')) > 4
            True
    """
    crc = zlib.crc32(tag)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _write_solid_png(path: Path, *, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    """Write a minimal valid solid-color PNG (stdlib only).

        Args:
    path (Path): Output file path.
    width (int): Image width in pixels.
    height (int): Image height in pixels.
    rgb (tuple[int, int, int]): Background color.

        Examples:
            >>> from pathlib import Path
            >>> p = Path('/tmp/sevn-test-placeholder.png')
            >>> _write_solid_png(p, width=2, height=2, rgb=(1, 2, 3))
            >>> p.exists()
            True
            >>> p.unlink()
    """
    raw_rows = []
    row = bytes([0] + list(rgb) * width)
    for _ in range(height):
        raw_rows.append(row)
    compressed = zlib.compress(b"".join(raw_rows), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", compressed)
    png += _png_chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def _write_labeled_png(path: Path, *, width: int, height: int, label: str) -> None:
    """Write a PNG with centered PLACEHOLDER label when Pillow is available.

        Args:
    path (Path): Output file path.
    width (int): Image width.
    height (int): Image height.
    label (str): Visible label text.

        Examples:
            >>> from pathlib import Path
            >>> p = Path('/tmp/sevn-labeled-placeholder.png')
            >>> _write_labeled_png(p, width=64, height=32, label='PLACEHOLDER')
            >>> p.stat().st_size > 0
            True
            >>> p.unlink()
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        _write_solid_png(path, width=width, height=height, rgb=_BASE)
        return

    img = Image.new("RGB", (width, height), _BASE)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=_PRIMARY, width=4)
    text = label
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, (height - th) // 2), text, fill=_PRIMARY, font=font)
    sub = f"{width}x{height}"
    draw.text((16, height - 40), sub, fill=_ACCENT, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def _write_gif_placeholder(path: Path, *, width: int, height: int) -> None:
    """Write a minimal single-frame GIF placeholder.

        Args:
    path (Path): Output path.
    width (int): Frame width.
    height (int): Frame height.

        Examples:
            >>> from pathlib import Path
            >>> p = Path('/tmp/sevn-demo.gif')
            >>> _write_gif_placeholder(p, width=16, height=8)
            >>> p.read_bytes()[:6] == b'GIF89a'
            True
            >>> p.unlink()
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("P", (width, height), 0)
        palette = [_BASE, _PRIMARY, _ACCENT, _MUTED]
        flat = []
        for color in palette:
            flat.extend(color)
        flat.extend([0] * (768 - len(flat)))
        img.putpalette(flat)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(2, 2), (width - 3, height - 3)], outline=1)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
        except OSError:
            font = ImageFont.load_default()
        draw.text((width // 2 - 80, height // 2 - 14), "PLACEHOLDER", fill=1, font=font)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, format="GIF", save_all=True, duration=1000, loop=0)
    except ImportError:
        # Minimal GIF89a 1x1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x0c\x0a\x09\xff\xff\xff"
            b"\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00"
            b"\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )


def _write_architecture_svg(path: Path) -> None:
    """Write theme-aware architecture diagram placeholder SVG.

        Args:
    path (Path): Output SVG path.

        Examples:
            >>> from pathlib import Path
            >>> p = Path('/tmp/sevn-arch.svg')
            >>> _write_architecture_svg(p)
            >>> 'PLACEHOLDER' in p.read_text()
            True
            >>> p.unlink()
    """
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0c0a09"/>
      <stop offset="100%" stop-color="#26211d"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#bg)"/>
  <rect x="24" y="24" width="912" height="492" rx="12" fill="none" stroke="#5fb1f7" stroke-width="3"/>
  <text x="480" y="250" text-anchor="middle" fill="#5fb1f7" font-family="system-ui,sans-serif" font-size="36" font-weight="700">PLACEHOLDER</text>
  <text x="480" y="300" text-anchor="middle" fill="#ff3b3b" font-family="system-ui,sans-serif" font-size="20">Architecture diagram — see ARCHITECTURE.md</text>
  <text x="480" y="340" text-anchor="middle" fill="#9dd0fb" font-family="system-ui,sans-serif" font-size="16">Turn spine: channel → gateway → triage → executor</text>
</svg>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    """Generate all Wave 1 brand placeholder assets.

    Returns:
        int: Exit code (0 on success).

    Examples:
        >>> isinstance(main(), int)
        True
    """
    _write_labeled_png(_ASSETS / "hero.png", width=1280, height=720, label="PLACEHOLDER")
    _write_labeled_png(_ASSETS / "demo-poster.png", width=1280, height=720, label="PLACEHOLDER")
    _write_gif_placeholder(_ASSETS / "demo.gif", width=640, height=360)
    _write_architecture_svg(_ASSETS / "architecture.svg")
    _write_labeled_png(_ASSETS / "social-preview.png", width=1280, height=640, label="PLACEHOLDER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
