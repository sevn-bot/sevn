"""Bundled ``telegram`` skill tests with mock adapter hooks."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sevn.channels.telegram_skill import (
    TelegramSkillHooks,
    add_custom_button,
    build_custom_inline_keyboard,
    clear_custom_buttons,
    create_forum_topic,
    find_group_by_name,
    list_custom_buttons,
    remove_custom_button,
)
from sevn.channels.telegram_skill.hooks import (
    bot_api_call_from_adapter,
    resolve_telegram_skill_hooks,
)

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "telegram"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


class _MockAdapter:
    """Minimal adapter recording Bot API calls."""

    def __init__(self, *, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses = responses or {}

    async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, body))
        return self._responses.get(method, {"ok": True, "result": {}})


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


@pytest.mark.asyncio
async def test_create_forum_topic_uses_adapter_api() -> None:
    """``create_forum_topic`` delegates to the injected Bot API hook."""
    adapter = _MockAdapter(
        responses={
            "createForumTopic": {
                "ok": True,
                "result": {"message_thread_id": 42, "name": "Roadmap"},
            },
        },
    )
    hooks = TelegramSkillHooks(bot_api=bot_api_call_from_adapter(adapter))
    out = await create_forum_topic(hooks, chat_id=-100123, name="Roadmap")
    assert out["topic_id"] == 42
    assert adapter.calls == [
        ("createForumTopic", {"chat_id": -100123, "name": "Roadmap"}),
    ]


@pytest.mark.asyncio
async def test_find_group_by_name_uses_mock_hook() -> None:
    """``find_group_by_name`` returns chat id from the find-group delegate."""

    async def _find(name: str) -> int | None:
        if "alpha" in name.casefold():
            return -100555
        return None

    hooks = TelegramSkillHooks(find_group=_find)
    out = await find_group_by_name(hooks, name="Alpha Team")
    assert out["chat_id"] == -100555


def test_buttons_crud_and_keyboard(tmp_path: Path) -> None:
    """Custom button store supports add, list, remove, clear, and keyboard build."""
    assert add_custom_button(tmp_path, name="Help", command="/help") is True
    assert add_custom_button(tmp_path, name="Help", command="/help") is False
    rows = list_custom_buttons(tmp_path)
    assert rows == [{"name": "Help", "command": "/help"}]
    kb = build_custom_inline_keyboard(tmp_path)
    assert kb["inline_keyboard"] == [[{"text": "Help", "callback_data": "btn:Help"}]]
    assert remove_custom_button(tmp_path, name="Help") is True
    assert clear_custom_buttons(tmp_path) == 0


def test_buttons_script_list_subprocess(tmp_path: Path) -> None:
    """``buttons.py --action list`` emits JSON envelope via subprocess."""
    _ = add_custom_button(tmp_path, name="Docs", command="/docs")
    code, payload = _run_script("buttons.py", tmp_path, ["--action", "list"])
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    buttons = data.get("buttons")
    assert isinstance(buttons, list)
    assert buttons[0]["name"] == "Docs"


def test_forum_create_script_with_env_token(tmp_path: Path) -> None:
    """``forum_create.py`` succeeds when a stub token env is paired with httpx mock."""

    async def _fake_api(_method: str, _body: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "result": {"message_thread_id": 7, "name": "Ops"}}

    hooks = TelegramSkillHooks(bot_api=_fake_api)
    resolved = resolve_telegram_skill_hooks(tmp_path, overrides=hooks)
    assert resolved.bot_api is not None
    out = asyncio.run(create_forum_topic(resolved, chat_id=-1001, name="Ops"))
    assert out["message_thread_id"] == 7


def test_resolve_hooks_scans_allowed_groups(tmp_path: Path) -> None:
    """``resolve_telegram_skill_hooks`` wires find_group when allowlist + token exist."""
    _ = (tmp_path / "sevn.json").write_text(
        json.dumps({"channels": {"telegram": {"allowed_groups": [-10077]}}}),
        encoding="utf-8",
    )

    async def _api(method: str, body: dict[str, Any]) -> dict[str, Any]:
        if method == "getChat":
            return {"ok": True, "result": {"id": body["chat_id"], "title": "Sevn Lab"}}
        return {"ok": False}

    hooks = TelegramSkillHooks(bot_api=_api)
    resolved = resolve_telegram_skill_hooks(tmp_path, overrides=hooks)
    assert resolved.find_group is not None
    chat_id = asyncio.run(resolved.find_group("lab"))
    assert chat_id == -10077
