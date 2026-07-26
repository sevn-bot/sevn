"""W1 RED: host-only command cards + checkout guard (green after W8, D17)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.menu.menu import build_config_menu_keyboard
from tests.gateway.telegram_menu_redesign_helpers import DEFAULT_DOCS_WORKSPACE


@pytest.mark.parametrize(
    "command",
    [
        "sevn onboard",
        "sevn completion install",
        "sevn shell-history install",
        "sevn gateway set-token",
        "sevn dashboard set-password",
        "sevn secrets store-passphrase",
        "sevn unboard",
    ],
)
@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W8: host-only card renders exact command", strict=False)
async def test_host_only_row_renders_copy_paste_card(command: str) -> None:
    """W1.12 / D17 — host-only rows post ``<pre>`` command cards, never subprocess."""
    from sevn.gateway.menu.host_command_cards import render_host_command_card

    card = await render_host_command_card(command, why="Gateway cannot run this here.")
    assert command in card
    assert "<pre>" in card or "```" in card


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W8: host-only rows never invoke subprocess", strict=False)
async def test_host_only_card_never_spawns_subprocess() -> None:
    """W1.12 — render_host_command_card must not call subprocess."""
    from sevn.gateway.menu.host_command_cards import render_host_command_card

    with patch("subprocess.run", new=AsyncMock()) as run_mock:
        await render_host_command_card("sevn onboard", why="host only")
    run_mock.assert_not_called()


@pytest.mark.xfail(reason="green after W8: unboard has no execution path", strict=False)
def test_unboard_has_no_act_execution_callback() -> None:
    """W1.12 — uninstall row is print-only at every layer."""
    from sevn.gateway.menu.menu_registry import MENU_BUTTON_SPECS

    unboard = [
        spec
        for spec in MENU_BUTTON_SPECS
        if "unboard" in spec.callback_pattern and spec.implemented
    ]
    assert not unboard


@pytest.mark.xfail(reason="green after W8: developer rows hidden without checkout", strict=False)
def test_developer_section_hidden_without_checkout() -> None:
    """W1.12 — Help > Developer follows conditional-row precedent (hide, not grey)."""
    ws = WorkspaceConfig.minimal()
    kb = build_config_menu_keyboard(
        DEFAULT_DOCS_WORKSPACE,
        section="help",
        is_owner=True,
        content_root=ws.workspace_path if hasattr(ws, "workspace_path") else None,
    )
    labels = [btn.get("text", "") for row in kb["inline_keyboard"] for btn in row]
    assert not any("Developer" in str(label) for label in labels)
