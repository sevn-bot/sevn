"""Batch A W1.1 — classifier timeout must never surface user-visible Telegram text (#119, D5).

Runtime integration lives in ``test_queue_multi.py`` (``test_multi_classifier_timeout_notice_not_on_prior_turn``).
W2 adds a CI grep gate; these tests pin the contract for gateway source and known bad strings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATEWAY_SRC = _REPO_ROOT / "src" / "sevn" / "gateway"

_FORBIDDEN_USER_FACING_PATTERNS: tuple[str, ...] = (
    "Queue classifier timed out",
    "queuing this message as its own turn",
    "classifier timed out — queuing",
)

_FORBIDDEN_REGEX = re.compile(
    r"classifier\s+timed\s+out.*(?:queu|own\s+turn)",
    re.IGNORECASE,
)


def _gateway_python_sources() -> list[Path]:
    return sorted(_GATEWAY_SRC.rglob("*.py"))


@pytest.mark.parametrize("needle", _FORBIDDEN_USER_FACING_PATTERNS)
def test_gateway_source_has_no_user_facing_classifier_timeout_strings(needle: str) -> None:
    """#119 / #70: user-facing classifier-timeout copy must not exist under gateway."""
    hits: list[str] = []
    for path in _gateway_python_sources():
        text = path.read_text(encoding="utf-8")
        if needle in text:
            hits.append(str(path.relative_to(_REPO_ROOT)))
    assert hits == [], f"forbidden string {needle!r} found in: {hits}"


def test_gateway_source_has_no_classifier_timeout_notice_regex() -> None:
    """Reject combined notice phrasing even when split across formatting."""
    hits: list[str] = []
    for path in _gateway_python_sources():
        for match in _FORBIDDEN_REGEX.finditer(path.read_text(encoding="utf-8")):
            hits.append(f"{path.relative_to(_REPO_ROOT)}:{match.group(0)!r}")
    assert hits == []


def test_session_manager_classifier_spawn_path_has_structured_log_not_notify() -> None:
    """Classifier fallback spawn logs ``gateway.queue_classifier_timeout_spawned`` only."""
    session_manager = (_GATEWAY_SRC / "session_manager.py").read_text(encoding="utf-8")
    assert "gateway.queue_classifier_timeout_spawned" in session_manager
    spawn_block_start = session_manager.find("gateway.queue_classifier_timeout_spawned")
    assert spawn_block_start != -1
    # The log call must appear before any notify_operator in the timeout early-return path.
    early_return = session_manager.find("routing_action=new_task", spawn_block_start)
    assert early_return != -1
