"""Batch A W1.1 — classifier timeout must never surface user-visible Telegram text (#119, D5).

Runtime integration lives in ``test_queue_multi.py`` (``test_multi_classifier_timeout_notice_not_on_prior_turn``).
W2 adds a CI grep gate; these tests pin the contract via the shared lint script.
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_gateway_classifier_timeout_user_text import GATEWAY_SRC, find_violations
from scripts.check_gateway_classifier_timeout_user_text import (
    main as check_gateway_classifier_timeout_user_text,
)


def _gateway_python_sources() -> list[Path]:
    return sorted(GATEWAY_SRC.rglob("*.py"))


def test_gateway_classifier_timeout_lint_script_passes() -> None:
    """Lint gate and pytest share one forbidden-string contract."""
    assert check_gateway_classifier_timeout_user_text() == 0


def test_gateway_source_has_no_user_facing_classifier_timeout_strings() -> None:
    """#119 / #70: user-facing classifier-timeout copy must not exist under gateway."""
    violations: list[tuple[str, str]] = []
    for path in _gateway_python_sources():
        violations.extend(find_violations(path))
    assert violations == [], "\n".join(f"  {rel}: {detail}" for rel, detail in violations)


def test_session_manager_classifier_spawn_path_has_structured_log_not_notify() -> None:
    """Classifier fallback spawn logs ``gateway.queue_classifier_timeout_spawned`` only."""
    session_manager_path = GATEWAY_SRC / "session_manager.py"
    session_manager = session_manager_path.read_text(encoding="utf-8")
    marker = "gateway.queue_classifier_timeout_spawned"
    assert marker in session_manager
    spawn_idx = session_manager.index(marker)
    return_idx = session_manager.find("return", spawn_idx)
    assert return_idx != -1
    spawn_block = session_manager[spawn_idx:return_idx]
    assert "notify_operator" not in spawn_block
    assert "routing_action=new_task" in spawn_block
