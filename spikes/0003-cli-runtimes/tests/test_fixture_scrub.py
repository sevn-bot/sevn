"""Fixture transcripts must not contain home paths, emails, or token shapes."""

from __future__ import annotations

import re
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = SPIKE_ROOT / "fixtures"

_PATTERNS = (
    re.compile(r"/Users/[^/\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer [A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
)


def test_scrub_patterns_match_known_leaks() -> None:
    leaks = (
        "/Users/example",
        "/home/example",
        "person@example.com",
        "sk-" + ("a" * 8),
        "Bearer " + ("a" * 8),
        "ghp_" + ("a" * 20),
    )
    for sample in leaks:
        assert any(pattern.search(sample) for pattern in _PATTERNS), sample
    safe = (
        "<HOME>/.claude",
        "ping",
        "Bearer abc",
        "sk-short",
        "ghp_tooshort",
    )
    for sample in safe:
        assert not any(pattern.search(sample) for pattern in _PATTERNS), sample


def test_fixtures_are_scrubbed() -> None:
    files = (
        sorted(path for path in FIXTURES.rglob("*") if path.is_file()) if FIXTURES.is_dir() else []
    )
    leaks: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(SPIKE_ROOT).as_posix()
        for pattern in _PATTERNS:
            if pattern.search(text):
                leaks.append(f"{relative} matched {pattern.pattern}")
    assert leaks == []
