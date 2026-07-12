#!/usr/bin/env python3
"""Render a deterministic SVG chart of the sub-agents topology (D14).

Reads ``about-sevn.bot/_sources/subagents-topology.json`` and writes
``about-sevn.bot/assets/subagents-chart.svg``. Sorted iteration and fixed
geometry keep output byte-stable across runs (no timestamps or randomness).

Module: scripts.gen_subagents_chart
Depends: argparse, json, pathlib, sys

Exports:
    load_topology — parse and validate the topology JSON.
    render_svg — deterministic SVG string from topology dict.
    write_chart — write SVG to the output path.
    check_chart — regenerate and diff against committed SVG.
    main — CLI (default write, ``--check`` for CI).

Examples:
    >>> svg = render_svg(load_topology())
    >>> "<svg" in svg
    True
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

TOPOLOGY_PATH = _REPO / "about-sevn.bot" / "_sources" / "subagents-topology.json"
OUTPUT_PATH = _REPO / "about-sevn.bot" / "assets" / "subagents-chart.svg"

__all__ = [
    "check_chart",
    "load_topology",
    "main",
    "render_svg",
    "write_chart",
]

_ROLE_X: dict[str, int] = {
    "triager": 120,
    "tier_b": 280,
    "tier_c": 440,
    "tier_d": 600,
}
_ROLE_Y = 160
_BOX_W = 120
_BOX_H = 44
_SVG_W = 800
_SVG_H = 480


def load_topology(path: Path | None = None) -> dict[str, Any]:
    """Parse and return the topology descriptor.

    Args:
        path (Path | None): Override path; defaults to :data:`TOPOLOGY_PATH`.

    Returns:
        dict[str, Any]: Parsed topology document.

    Examples:
        >>> doc = load_topology()
        >>> doc["schema_version"]
        1
    """
    src = path or TOPOLOGY_PATH
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"topology must be a JSON object: {src}"
        raise TypeError(msg)
    return data


def _esc(text: str) -> str:
    """Escape text for safe SVG ``<text>`` nodes.

    Args:
        text (str): Raw label text.

    Returns:
        str: XML-escaped text.

    Examples:
        >>> _esc("a<b")
        'a&lt;b'
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _rect(x: int, y: int, w: int, h: int, *, fill: str, stroke: str, rx: int = 6) -> str:
    """Return one rounded ``<rect>`` SVG element string.

    Args:
        x (int): Top-left x.
        y (int): Top-left y.
        w (int): Width.
        h (int): Height.
        fill (str): Fill colour.
        stroke (str): Stroke colour.
        rx (int): Corner radius.

    Returns:
        str: SVG fragment.

    Examples:
        >>> '<rect' in _rect(0, 0, 10, 10, fill="#000", stroke="#fff")
        True
    """
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
    )


def _text(x: int, y: int, label: str, *, size: int = 12, anchor: str = "middle") -> str:
    """Return one ``<text>`` SVG element string.

    Args:
        x (int): Anchor x.
        y (int): Baseline y.
        label (str): Visible label.
        size (int): Font size in px.
        anchor (str): SVG ``text-anchor`` value.

    Returns:
        str: SVG fragment.

    Examples:
        >>> 'Hello' in _text(1, 2, 'Hello')
        True
    """
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-family="ui-sans-serif,system-ui,sans-serif" font-size="{size}" '
        f'fill="#e8eaed">{_esc(label)}</text>'
    )


def _arrow(x1: int, y1: int, x2: int, y2: int) -> str:
    """Return one directed ``<line>`` with arrow marker.

    Args:
        x1 (int): Start x.
        y1 (int): Start y.
        x2 (int): End x.
        y2 (int): End y.

    Returns:
        str: SVG fragment.

    Examples:
        >>> 'marker-end' in _arrow(0, 0, 10, 10)
        True
    """
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="#8ab4f8" stroke-width="1.5" marker-end="url(#arrow)"/>'
    )


def render_svg(topology: dict[str, Any]) -> str:
    """Render deterministic SVG from a topology document.

    Args:
        topology (dict[str, Any]): Parsed topology (see ``subagents-topology.json``).

    Returns:
        str: SVG document string (UTF-8, trailing newline).

    Examples:
        >>> svg = render_svg(load_topology())
        >>> "<svg" in svg and "SubAgentRegistry" in svg
        True
    """
    roles = sorted(topology.get("roles", []), key=lambda r: str(r.get("id", "")))
    specialists = sorted(topology.get("specialists", []), key=lambda s: str(s.get("id", "")))
    nodes = sorted(topology.get("nodes", []), key=lambda n: str(n.get("id", "")))
    edges = sorted(
        topology.get("edges", []),
        key=lambda e: (str(e.get("from", "")), str(e.get("to", "")), str(e.get("label", ""))),
    )
    surfaces = sorted(topology.get("surfaces", []), key=lambda s: str(s.get("id", "")))
    defaults = topology.get("defaults", {})
    multi = topology.get("multi_queue", {})

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_SVG_W} {_SVG_H}" '
        f'width="{_SVG_W}" height="{_SVG_H}" role="img" '
        f'aria-label="sevn.bot sub-agents topology">',
        "<defs>",
        '<marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">',
        '<path d="M0,0 L6,3 L0,6 Z" fill="#8ab4f8"/>',
        "</marker>",
        "</defs>",
        f'<rect width="{_SVG_W}" height="{_SVG_H}" fill="#1a1d21"/>',
        _text(
            _SVG_W // 2,
            22,
            str(topology.get("title", "Sub-agents topology")),
            size=16,
        ),
        _text(
            _SVG_W // 2,
            38,
            (
                f"defaults L1={defaults.get('max_level1_default', 5)} "
                f"L2={defaults.get('max_level2_default', 3)}"
            ),
            size=11,
        ),
    ]

    node_centers: dict[str, tuple[int, int]] = {}

    for node in nodes:
        nid = str(node.get("id", ""))
        x = int(node.get("x", 0))
        y = int(node.get("y", 0))
        label = str(node.get("label", nid))
        kind = str(node.get("kind", "service"))
        fill = {
            "hub": "#2d3a4f",
            "service": "#243328",
            "worker": "#3a2d40",
            "decision": "#3a3520",
        }.get(kind, "#2a2f36")
        stroke = "#5f7a9a" if kind == "hub" else "#6a8f6e"
        parts.append(
            _rect(x - _BOX_W // 2, y - _BOX_H // 2, _BOX_W, _BOX_H, fill=fill, stroke=stroke)
        )
        parts.append(_text(x, y + 4, label, size=11))
        node_centers[nid] = (x, y)

    for role in roles:
        rid = str(role.get("id", ""))
        label = str(role.get("label", rid))
        x = _ROLE_X.get(rid, 400)
        y = _ROLE_Y
        parts.append(
            _rect(
                x - _BOX_W // 2, y - _BOX_H // 2, _BOX_W, _BOX_H, fill="#1e3a5f", stroke="#4a90d9"
            )
        )
        parts.append(_text(x, y - 6, "L1", size=9))
        parts.append(_text(x, y + 8, label, size=12))
        node_centers[rid] = (x, y)

    spec_y = 300
    for idx, spec in enumerate(specialists):
        sid = str(spec.get("id", ""))
        label = str(spec.get("label", sid))
        x = 440 + idx * 140
        parts.append(
            _rect(
                x - _BOX_W // 2,
                spec_y - _BOX_H // 2,
                _BOX_W,
                _BOX_H,
                fill="#3a2448",
                stroke="#b48ad9",
            )
        )
        parts.append(_text(x, spec_y - 6, "L2 specialist", size=9))
        parts.append(_text(x, spec_y + 8, label, size=11))
        node_centers[sid] = (x, spec_y)

    if "l2_generic" in node_centers:
        gx, gy = node_centers["l2_generic"]
        parts.append(
            _rect(
                gx - _BOX_W // 2, gy - _BOX_H // 2, _BOX_W, _BOX_H, fill="#2a3540", stroke="#7a8a9a"
            )
        )
        parts.append(_text(gx, gy - 6, "L2", size=9))
        parts.append(_text(gx, gy + 8, "generic worker", size=11))

    if "gateway" in node_centers and roles:
        gx, gy = node_centers["gateway"]
        for role in roles:
            rid = str(role.get("id", ""))
            if rid not in node_centers:
                continue
            rx, ry = node_centers[rid]
            parts.append(_arrow(gx, gy + _BOX_H // 2, rx, ry - _BOX_H // 2))

    for edge in edges:
        src = str(edge.get("from", ""))
        dst = str(edge.get("to", ""))
        if src not in node_centers or dst not in node_centers:
            continue
        if src == "gateway" and dst in _ROLE_X:
            continue
        x1, y1 = node_centers[src]
        x2, y2 = node_centers[dst]
        parts.append(_arrow(x1, y1 + _BOX_H // 2, x2, y2 - _BOX_H // 2))
        label = str(edge.get("label", ""))
        if label:
            parts.append(_text((x1 + x2) // 2, (y1 + y2) // 2 - 4, label, size=9))

    labels = sorted(str(lb) for lb in multi.get("labels", []))
    fallback = str(multi.get("fallback", "steer"))
    parts.append(
        _text(
            640,
            200,
            "multi: " + " / ".join(labels),
            size=10,
        )
    )
    parts.append(_text(640, 216, f"fallback → {fallback}", size=10))

    surface_labels = ", ".join(str(s.get("label", "")) for s in surfaces)
    parts.append(_text(_SVG_W // 2, _SVG_H - 16, f"Kill surfaces: {surface_labels}", size=10))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_chart(path: Path | None = None, *, topology_path: Path | None = None) -> Path:
    """Write the SVG chart to the output path.

    Args:
        path (Path | None): Output SVG path; defaults to :data:`OUTPUT_PATH`.
        topology_path (Path | None): Topology JSON path override.

    Returns:
        Path: Path written.

    Examples:
        >>> write_chart()  # doctest: +SKIP
    """
    out = path or OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    svg = render_svg(load_topology(topology_path))
    out.write_text(svg, encoding="utf-8")
    return out


def check_chart(path: Path | None = None, *, topology_path: Path | None = None) -> list[str]:
    """Regenerate SVG and return diff messages when stale.

    Args:
        path (Path | None): Committed SVG path; defaults to :data:`OUTPUT_PATH`.
        topology_path (Path | None): Topology JSON path override.

    Returns:
        list[str]: Empty when fresh; otherwise human-readable error lines.

    Examples:
        >>> isinstance(check_chart(), list)
        True
    """
    out = path or OUTPUT_PATH
    expected = render_svg(load_topology(topology_path))
    if not out.is_file():
        return [f"missing committed SVG: {out} — run make subagents-chart"]
    actual = out.read_text(encoding="utf-8")
    if actual == expected:
        return []
    return [
        f"stale sub-agents chart: {out}",
        "run: make subagents-chart",
        f"committed bytes={len(actual.encode())} expected bytes={len(expected.encode())}",
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry — write chart or ``--check`` for CI.

    Args:
        argv (list[str] | None): Arguments (``--check`` optional).

    Returns:
        int: Exit code (0 success, 1 on check failure).

    Examples:
        >>> isinstance(main([]), int)
        0
    """
    parser = argparse.ArgumentParser(description="Generate deterministic sub-agents topology SVG")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed SVG differs from a fresh render",
    )
    parser.add_argument(
        "--topology",
        type=Path,
        default=None,
        help="Override topology JSON path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output SVG path",
    )
    args = parser.parse_args(argv)
    if args.check:
        errors = check_chart(args.output, topology_path=args.topology)
        if errors:
            for line in errors:
                print(line, file=sys.stderr)
            return 1
        print(f"subagents chart OK: {args.output or OUTPUT_PATH}")
        return 0
    written = write_chart(args.output, topology_path=args.topology)
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
