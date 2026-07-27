"""W1 RED: destructive confirm gates + unknown suffix rejection (green after W7d/W8)."""

from __future__ import annotations

from pathlib import Path

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


def test_secrets_export_dispatcher_kind_registered() -> None:
    """Thermos — export confirm pending rows use a registered dispatcher kind."""
    import json
    import sqlite3

    from sevn.gateway.commands.dispatcher_kinds import ALL_DISPATCHER_KINDS
    from sevn.gateway.dispatcher.dispatcher_state import insert_dispatcher_state
    from sevn.storage.migrate import apply_migrations

    assert "secrets_export" in ALL_DISPATCHER_KINDS
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    insert_dispatcher_state(
        conn,
        token="ds:export-test",
        kind="secrets_export",
        user_id=1,
        chat_id=2,
        topic_id=None,
        payload_json=json.dumps({"v": 1}, separators=(",", ":")),
        ttl_seconds=600,
    )
    row = conn.execute(
        "SELECT kind FROM dispatcher_state WHERE token = ?",
        ("ds:export-test",),
    ).fetchone()
    assert row is not None
    assert row[0] == "secrets_export"


# The live callbacks for the three families, as rendered today: secret removal is
# a form row (`form:secrets:rm`), not an `act:` row.
DESTRUCTIVE_NON_OWNER_CALLBACKS: tuple[str, ...] = (
    "form:secrets:rm",
    "act:secrets:export-secrets",
    "act:secrets:export-secrets:confirm",
    "form:deploy:remote",
    "act:deploy:remote",
    "act:deploy:remote:confirm",
)


@pytest.mark.parametrize("callback", DESTRUCTIVE_NON_OWNER_CALLBACKS)
@pytest.mark.asyncio
async def test_destructive_action_rejects_non_owner(callback: str, tmp_path: Path) -> None:
    """PR #63 review: nothing drove these three families through ``route_incoming``.

    The rest of this file unit-tests pure helpers, and
    ``tests/gateway/test_config_menu_actions.py`` only ever routes as the sole
    owner — so the PR's "owner bypass closed" claim had no runtime evidence for
    ``secrets:rm``, ``secrets:export-secrets`` or ``deploy:remote``. Tapping the
    confirm leg directly must be rejected too, not just the first step.
    """
    from tests.gateway.test_config_menu_actions import _build_router, _config_callback

    router, cap, _ws = _build_router(tmp_path)
    router._owner_ids = frozenset()
    cq = f"cq-{callback.replace(':', '-')}"
    await router.route_incoming(_config_callback(callback, callback_query_id=cq))

    assert (cq, "Owner only.") in cap.answered, cap.answered
    assert not cap.sent, f"{callback} leaked output to a non-owner: {cap.sent}"


@pytest.mark.asyncio
async def test_dm_policy_cycle_rejects_non_owner(tmp_path: Path) -> None:
    """PR #63 review: the DM-policy cycle went live in this PR without an owner gate.

    Inline keyboards are tappable by any member of the chat the message was
    rendered in, so an ungated cycle let anyone change who may DM the bot.
    """
    from sevn.gateway.menu.menu import build_config_menu_keyboard
    from tests.gateway.test_config_menu_actions import _build_router, _config_callback

    router, cap, _ws = _build_router(tmp_path)
    kb = build_config_menu_keyboard(router._workspace, section="access_pairing")
    cycle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if str(btn.get("callback_data", "")).startswith("cfg:toggle:channels.telegram.dm_policy:")
    )
    router._owner_ids = frozenset()
    await router.route_incoming(
        _config_callback(cycle_btn["callback_data"], callback_query_id="cq-dm-nonowner"),
    )

    assert ("cq-dm-nonowner", "Owner only.") in cap.answered, cap.answered
    # The row still offers the same next value, i.e. nothing was cycled.
    after_kb = build_config_menu_keyboard(router._workspace, section="access_pairing")
    after_btn = next(
        btn
        for row in after_kb["inline_keyboard"]
        for btn in row
        if str(btn.get("callback_data", "")).startswith("cfg:toggle:channels.telegram.dm_policy:")
    )
    assert after_btn["callback_data"] == cycle_btn["callback_data"]


@pytest.mark.parametrize(
    "section",
    ["access_secrets", "access_pairing", "access_guard", "deployment_host", "deployment_services"],
)
@pytest.mark.asyncio
async def test_owner_only_child_section_rejects_non_owner(section: str, tmp_path: Path) -> None:
    """PR #63 review: the nav gate only covered the 8 root tiles.

    ``cfg:section:access_secrets`` and friends sit under an owner-gated root but
    were not themselves in ``_OWNER_ONLY_ROOT_SECTIONS``, so entering a child
    directly skipped the gate entirely.
    """
    from tests.gateway.test_config_menu_actions import _build_router, _config_callback

    router, cap, _ws = _build_router(tmp_path)
    router._owner_ids = frozenset()
    cq = f"cq-{section}"
    await router.route_incoming(_config_callback(f"cfg:section:{section}", callback_query_id=cq))

    assert (cq, "Owner only.") in cap.answered, cap.answered
