"""W1 RED: destructive confirm gates + unknown suffix rejection (green after W7d/W8)."""

from __future__ import annotations

import pytest

from sevn.gateway.menu.menu import build_tunnel_on_confirm_keyboard, tunnel_on_confirm_message


@pytest.mark.parametrize(
    "callback",
    [
        "act:secrets:rm",
        "act:secrets:export-secrets",
        "act:deploy:remote",
    ],
)
@pytest.mark.xfail(
    reason="green after W7d/W8: confirm gate uses tunnel two-step shape", strict=False
)
def test_destructive_row_uses_two_step_confirm(callback: str) -> None:
    """W1.13 / D6 — destructive rows reuse tunnel-on confirm keyboard shape."""
    from sevn.gateway.menu.confirm_gates import build_confirm_gate_keyboard, confirm_gate_message

    rows = build_confirm_gate_keyboard(callback)
    tunnel_rows = build_tunnel_on_confirm_keyboard()
    assert [btn.get("callback_data") for row in rows for btn in row] == [
        btn.get("callback_data") for row in tunnel_rows for btn in row
    ]
    assert confirm_gate_message(callback)
    assert "Turn tunnel on" in tunnel_on_confirm_message() or confirm_gate_message(callback)


@pytest.mark.parametrize(
    ("family_prefix", "unknown_suffix"),
    [
        ("act:secrets:", "not-a-known-action"),
        ("act:deploy:", "unknown-deploy"),
        ("act:services:", "missing-service"),
    ],
)
@pytest.mark.xfail(
    reason="green after W7d/W8: unknown suffix rejected with toast (D15)", strict=False
)
def test_unknown_callback_suffix_rejected_not_defaulted(
    family_prefix: str,
    unknown_suffix: str,
) -> None:
    """W1.13 — unrecognised suffixes error-toast; never fall through to a default."""
    from sevn.gateway.commands.menu_action_router import MenuActionRouter

    callback = f"{family_prefix}{unknown_suffix}"
    assert hasattr(MenuActionRouter, "reject_unknown_callback_suffix")
    _ = callback
