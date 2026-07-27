"""W1 RED: destructive confirm gates + unknown suffix rejection (green after W7d/W8)."""

from __future__ import annotations

import pytest

from sevn.gateway.menu.menu import build_tunnel_on_confirm_keyboard, tunnel_on_confirm_message


@pytest.mark.parametrize(
    "gate_id",
    [
        "secrets:rm",
        "secrets:export-secrets",
        "deploy:remote",
    ],
)
def test_destructive_row_uses_two_step_confirm(gate_id: str) -> None:
    """W1.13 / D6 — destructive rows reuse tunnel-on confirm keyboard shape."""
    from sevn.gateway.menu.confirm_gates import build_confirm_gate_keyboard, confirm_gate_message

    rows = build_confirm_gate_keyboard(gate_id)
    tunnel_rows = build_tunnel_on_confirm_keyboard()

    assert len(rows) == len(tunnel_rows) == 1
    assert len(rows[0]) == len(tunnel_rows[0]) == 2
    assert rows[0][0]["text"].startswith("✅ Confirm")
    assert rows[0][1]["text"] == "Cancel"
    assert rows[0][0]["callback_data"] == f"act:{gate_id}:confirm"
    assert rows[0][1]["callback_data"] == f"act:{gate_id}:cancel"
    assert tunnel_rows[0][0]["callback_data"] == "act:tunnel:on:confirm"
    assert tunnel_rows[0][1]["callback_data"] == "act:tunnel:on:cancel"

    caption = confirm_gate_message(title="Test action", detail="Irreversible effect.")
    assert "Test action" in caption
    assert "Tap Confirm to proceed." in caption
    assert "Turn tunnel on" in tunnel_on_confirm_message()


@pytest.mark.parametrize(
    ("family_prefix", "unknown_suffix"),
    [
        ("act:secrets:", "not-a-known-action"),
        ("act:deploy:", "unknown-deploy"),
        ("act:services:", "missing-service"),
    ],
)
def test_unknown_callback_suffix_rejected_not_defaulted(
    family_prefix: str,
    unknown_suffix: str,
) -> None:
    """W1.13 — unrecognised suffixes error-toast; never fall through to a default."""
    from sevn.gateway.commands.menu_action_router import MenuActionRouter

    toast = MenuActionRouter.reject_unknown_callback_suffix(family_prefix, unknown_suffix)
    assert family_prefix in toast
    assert unknown_suffix in toast
    assert toast.startswith("Unknown ")
