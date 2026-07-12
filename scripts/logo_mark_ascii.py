#!/usr/bin/env python3
"""Generate sevn logo ASCII art and optional row-reveal terminal animation.

Static exports write under ``about-sevn.bot/assets/logos/``. Pass ``--animate`` to
play the stop-motion row-by-row reveal on stdout (Warp ASCII Studio style),
``--marquee`` to slide the logo mark across the terminal, or ``--trot`` to play
the trotting-unicorn splash.

Usage:
    uv run python scripts/logo_mark_ascii.py
    uv run python scripts/logo_mark_ascii.py --animate
    uv run python scripts/logo_mark_ascii.py --animate --transition dissolve --fps 12
    uv run python scripts/logo_mark_ascii.py --trot --fps 18 --step 2

Exports:
    main — CLI entry.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from sevn.branding.logo_mark import (
    _marquee_track_cols,
    build_marquee_frames,
    build_palette,
    build_reveal_frames,
    convert_colored,
    hex_to_rgb,
    play_frames,
    render_ansi,
    render_html,
    render_plain,
    rgb_to_hex,
    trim_grid,
)
from sevn.branding.unicorn_trot import play_unicorn_trot

_DEFAULT_SRC = Path("styles/sevn/style/logos/logo-mark.png")
_DEFAULT_OUT = Path("about-sevn.bot/assets/logos")
_DEFAULT_PALETTE_SVG = Path("styles/sevn/style/logos/logo-mark.svg")
_DEFAULT_PALETTE_CSS = Path("styles/sevn/style/tokens/colors.css")


def main() -> None:
    """Generate ASCII logo files and/or play row-reveal animation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=_DEFAULT_SRC)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--width", type=int, default=72, help="Character columns")
    parser.add_argument("--palette-svg", type=Path, default=_DEFAULT_PALETTE_SVG)
    parser.add_argument("--palette-css", type=Path, default=_DEFAULT_PALETTE_CSS)
    parser.add_argument(
        "--animate",
        action="store_true",
        help="Play row-by-row colored animation on stdout instead of writing files.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=6.0,
        help="Animation frames per second when --animate is set.",
    )
    parser.add_argument(
        "--transition",
        choices=("none", "dissolve"),
        default="none",
        help="Frame transition: none (row cut) or dissolve (char stagger per row).",
    )
    parser.add_argument(
        "--marquee",
        action="store_true",
        help="Slide the logo mark left-to-right across the terminal.",
    )
    parser.add_argument(
        "--trot",
        action="store_true",
        help="Play the trotting-unicorn splash across the terminal.",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=3,
        help="Marquee/trot columns advanced per frame (higher is faster).",
    )
    parser.add_argument(
        "--track-cols",
        type=int,
        default=0,
        help="Marquee/trot travel width; 0 uses the terminal width.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Also write static .txt/.ansi/.html when using --animate.",
    )
    args = parser.parse_args()

    if args.trot:
        track = _marquee_track_cols(args.track_cols or None)
        play_unicorn_trot(fps=args.fps, step=args.step, track_cols=track)
        return

    svg_path = args.palette_svg if args.palette_svg.is_file() else None
    css_path = args.palette_css if args.palette_css.is_file() else None
    ink_palette, bg_hex = build_palette(svg_path, css_path)
    background = hex_to_rgb(bg_hex)
    palette_note = str(args.palette_svg if svg_path else args.palette_css)

    with Image.open(args.src) as img:
        cols, rows, cells = convert_colored(
            img,
            cols=args.width,
            ink_palette=ink_palette,
            background=background,
        )
    cols, rows, cells = trim_grid(cols, rows, cells)

    if args.marquee:
        track = _marquee_track_cols(args.track_cols or None)
        marquee = build_marquee_frames(
            cols,
            rows,
            cells,
            background=background,
            track_cols=track,
            step=args.step,
        )
        play_frames(track, rows, marquee, fps=args.fps, hold_final_s=0.0, restore_newline=True)
        return

    if args.animate:
        frames = build_reveal_frames(
            cols,
            rows,
            cells,
            background=background,
            transition=args.transition,
        )
        play_frames(cols, rows, frames, fps=args.fps)
        if not args.write:
            return

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / "logo-mark-ascii.txt"
    ansi_path = out_dir / "logo-mark-ascii.ansi.txt"
    html_path = out_dir / "logo-mark-ascii.html"

    txt_path.write_text(render_plain(cols, rows, cells), encoding="utf-8")
    ansi_path.write_text(render_ansi(cols, rows, cells), encoding="utf-8")
    html_path.write_text(
        render_html(cols, rows, cells, bg=bg_hex, palette_note=palette_note),
        encoding="utf-8",
    )

    used = sorted({rgb_to_hex(c.r, c.g, c.b) for c in cells if c.ch != " "})
    print(f"Palette source: {palette_note}")
    print(f"Ink colors used: {', '.join(used)}")
    print(f"Wrote {txt_path} ({cols}x{rows})")
    print(f"Wrote {ansi_path} (true-color ANSI)")
    print(f"Wrote {html_path} (bg {bg_hex})")
    if not args.animate:
        print()
        print(ansi_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
