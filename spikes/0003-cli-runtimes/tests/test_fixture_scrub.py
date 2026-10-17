"""Fixture transcripts must not contain home paths, emails, tokens, temp dirs, or account names."""

from __future__ import annotations

import os
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

# macOS per-user temp dirs stay after a /Users and /home rewrite (F4).
_TEMP_PATTERNS = (
    re.compile(r"/private"),
    re.compile(r"/var"),
)

# Contiguous pytest temp segment whose account component was not replaced.
_PYTEST_ACCOUNT = re.compile(r"pytest-of-(?!<USER>)[A-Za-z0-9._-]+")


def _account_names() -> tuple[str, ...]:
    """Names from the environment. Never hard-code an account name."""

    names: list[str] = []
    for candidate in (
        os.environ.get("USER", ""),
        os.environ.get("LOGNAME", ""),
        Path.home().name,
    ):
        cleaned = candidate.strip()
        if len(cleaned) < 3 or cleaned in names:
            continue
        names.append(cleaned)
    return tuple(names)


def _leak_labels(text: str, *, names: tuple[str, ...]) -> list[str]:
    labels: list[str] = []
    for pattern in (*_PATTERNS, *_TEMP_PATTERNS):
        if pattern.search(text):
            labels.append(pattern.pattern)
    if _PYTEST_ACCOUNT.search(text):
        labels.append("pytest-of-<account>")
    if any(name in text for name in names):
        labels.append("account name")
    return labels


def test_scrub_patterns_match_known_leaks() -> None:
    leaks = (
        "/Users/example",
        "/home/example",
        "person@example.com",
        "sk-" + ("a" * 8),
        "Bearer " + ("a" * 8),
        "ghp_" + ("a" * 20),
        "/private/var/folders/ab/T/pytest-of-example/pytest-0",
        "/var/folders/ab",
        "pytest-of-example/",
    )
    for sample in leaks:
        assert _leak_labels(sample, names=()), sample
    safe = (
        "<HOME>/.claude",
        "ping",
        "Bearer abc",
        "sk-short",
        "ghp_tooshort",
        "pytest-of-<USER>/pytest-0",
    )
    for sample in safe:
        assert _leak_labels(sample, names=()) == [], sample
    assert "/private" in _leak_labels("/private/var/folders/ab", names=())
    assert "/var" in _leak_labels("/var/folders/ab", names=())
    assert "pytest-of-<account>" in _leak_labels("pytest-of-example/", names=())
    assert "account name" in _leak_labels("T/pytest-of-example/", names=("example",))
    assert _leak_labels("dir/example/file", names=("example",)) == ["account name"]
    assert _leak_labels("pytest-of-<USER>/", names=("example",)) == []
    assert _account_names()


def test_fixtures_are_scrubbed() -> None:
    files = (
        sorted(path for path in FIXTURES.rglob("*") if path.is_file()) if FIXTURES.is_dir() else []
    )
    names = _account_names()
    leaks: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(SPIKE_ROOT).as_posix()
        leaks.extend(f"{relative} matched {label}" for label in _leak_labels(text, names=names))
    assert leaks == []
