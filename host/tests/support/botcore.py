"""Arrange helpers for the bot-core RED suite. Product imports stay inside calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def arm_configured(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    toml_text: str | None = None,
) -> None:
    """Point the host at ``home``. ``toml_text`` replaces the default config."""
    from support.chat import arm_home

    if toml_text is not None:
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.toml").write_text(toml_text, encoding="utf-8")
    arm_home(monkeypatch, home)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


async def upgrade_home(home: Path) -> None:
    from sevn.store.db import upgrade

    await upgrade(f"sqlite+aiosqlite:///{home / 'sevn.db'}")


def decision_rows(home: Path) -> list[dict[str, Any]]:
    from support.chat import fetch_all

    rows = fetch_all(
        home,
        """
        SELECT id, point, input_hash, state_redacted, answers, confidences,
               path, outcome, corrected_to
        FROM decision_log
        ORDER BY created_at, id
        """,
    )
    return [dict(row) for row in rows]


def decision_text(intent: str, target: str | None, confidence: float) -> str:
    """JSON object the LLM, Ollama, and CLI deciders parse from model text."""
    return json.dumps(
        {
            "intent": intent,
            "target_agent_id": target,
            "busy_policy": None,
            "confidence": confidence,
        }
    )


def set_provider_key(value: str = "test-provider-key") -> None:
    """Store a non-network provider key so the LLM decider is eligible."""
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    open_backend(Settings.load(), Paths.from_env()).set("provider/anthropic", value)


_SECRETS = '[secrets]\nbackend = "age-file"\n'


def secrets_toml(extra: str = "") -> str:
    return _SECRETS + extra
