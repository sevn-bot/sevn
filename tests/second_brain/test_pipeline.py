"""Pipeline isolation — Second Brain must not target LCM flush paths (`specs/27-second-brain.md` §4.1)."""

from __future__ import annotations

from pathlib import Path


def test_second_brain_sources_do_not_reference_flush_paths() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "sevn" / "second_brain"
    forbidden = ("MEMORY.md", "USER.md", "memory/")
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for frag in forbidden:
            assert frag not in text, f"{py.relative_to(root)} must not mention {frag!r}"
