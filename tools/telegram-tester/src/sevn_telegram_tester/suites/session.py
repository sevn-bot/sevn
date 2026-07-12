"""Session /config Playwright suite (plan/telegram-e2e-wave-plan.md TE-8).

Module: sevn_telegram_tester.suites.session
Depends: sevn_telegram_tester.telegram_client, sevn_telegram_tester.assertions,
    sevn_telegram_tester.reporting.json_report

Exports:
    run_session_suite — run session /config tests and return a JsonReport.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from sevn_telegram_tester.assertions import (
    TelegramAssertionError,
    assert_message_contains,
)
from sevn_telegram_tester.reporting.json_report import JsonReport, JsonTestResult
from sevn_telegram_tester.telegram_client import TelegramClient

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from sevn_telegram_tester.config import TelegramTesterSettings

_DEPLOYMENT_ID_RE = re.compile(
    r"Deployment id:\s*[\w.-]+-\d{14}-[0-9a-f]{6}",
    re.IGNORECASE,
)
_ROUTING_FOOTER_RE = re.compile(r"intent=[A-Z_]+ · tier=[A-D]", re.IGNORECASE)
_STEER_LOG_TOKEN = "gateway.queue_steer_queued"

# Free-text probes — only run when ``settings.echo_mode_enabled()`` (local E2E stack).
_ECHO_PROBE_TESTS: frozenset[str] = frozenset(
    {
        "test_regen_toggle_affects_next_reply",
        "test_queue_mode_runtime_reflects",
    }
)
_SKIP_ECHO_ON_PROD_MSG = (
    "skipped on --target prod (sends e2e-* probe messages; requires SEVN_E2E_ECHO_TURN=1). "
    "Use --target local or set TELEGRAM_TEST_ECHO_MODE=1 on a deployment with echo enabled."
)

_CONFIG_ROOT_MIN_BUTTONS = 21


def _open_config(client: TelegramClient) -> list[str]:
    """Open the /config root menu and wait for the inline tile keyboard."""
    client.send_message("/config")
    # Do not match the outgoing "/config" echo — wait for the tile keyboard.
    return client.wait_for_inline_keyboard(
        min_buttons=_CONFIG_ROOT_MIN_BUTTONS,
        label_contains="Help",
        timeout_ms=45_000,
    )


def _open_channels(client: TelegramClient) -> None:
    """Navigate to the Channels section from the /config root."""
    _open_config(client)
    client.click_inline_button("Channels")
    client.wait_for_message_matching(r"Show routing footer:\s*(on|off)", timeout_ms=30_000)


def _ensure_show_routing(client: TelegramClient, *, enabled: bool) -> None:
    """Set ``channels.telegram.show_routing`` via the Channels inline toggle."""
    _open_channels(client)
    text = client.wait_for_message_matching(r"Show routing footer:\s*(on|off)", timeout_ms=30_000)
    is_on = bool(re.search(r"Show routing footer:\s*on", text, re.IGNORECASE))
    if is_on == enabled:
        return
    client.click_inline_button("Show routing")
    expected = r"Show routing footer:\s*on" if enabled else r"Show routing footer:\s*off"
    client.wait_for_message_matching(expected, timeout_ms=30_000)


def test_deployment_id_visible(client: TelegramClient) -> str | None:
    """``/status`` includes a stable deployment id line."""
    client.send_message("/status")
    text = client.wait_for_message_matching(_DEPLOYMENT_ID_RE, timeout_ms=45_000)
    match = _DEPLOYMENT_ID_RE.search(text)
    if match is None:
        msg = f"deployment id line missing in status: {text!r}"
        raise TelegramAssertionError(msg)
    return match.group(0).split(":", 1)[-1].strip()


def test_config_opens(client: TelegramClient) -> None:
    """Root ``/config`` shows 19 section tiles plus Help and Close."""
    labels = _open_config(client)
    if len(labels) < 21:
        msg = f"expected at least 21 inline buttons (19 tiles + Help + Close), got {len(labels)}: {labels}"
        raise TelegramAssertionError(msg)
    joined = "\n".join(labels)
    if "Help" not in joined:
        raise TelegramAssertionError("Help button missing on /config root")
    if "Close" not in joined:
        raise TelegramAssertionError("Close button missing on /config root")
    if not any("Logs" in label for label in labels):
        raise TelegramAssertionError("📜 Logs tile missing on /config root")


def test_session_section_buttons(client: TelegramClient) -> None:
    """Session section exposes QA toggles and queue row without 🚧 locks."""
    _open_config(client)
    client.click_inline_button("Session")
    labels = client.wait_for_inline_keyboard(
        min_buttons=3,
        label_contains="Regen",
        timeout_ms=30_000,
    )
    if any("🚧" in label for label in labels):
        msg = f"unexpected 🚧 on Session section buttons: {labels}"
        raise TelegramAssertionError(msg)
    joined = "\n".join(labels)
    if "Regen" not in joined:
        raise TelegramAssertionError("Regen toggle missing in Session section")
    if "Queue:" not in joined:
        raise TelegramAssertionError("Queue mode row missing in Session section")


def test_regen_toggle_persists_in_caption(client: TelegramClient) -> None:
    """Toggling Regen updates the Session section caption (on ↔ off)."""
    _open_config(client)
    client.click_inline_button("Session")
    text = client.wait_for_message_matching(r"Regen:\s*(on|off)", timeout_ms=30_000)
    if re.search(r"Regen:\s*on", text, re.IGNORECASE):
        expected_after = r"Regen:\s*off"
    else:
        expected_after = r"Regen:\s*on"
    client.click_inline_button("Regen")
    client.wait_for_message_matching(expected_after, timeout_ms=30_000)


def test_regen_toggle_affects_next_reply(client: TelegramClient) -> None:
    """With Regen off, the next echo reply omits the Regen QA button."""
    _open_config(client)
    client.click_inline_button("Session")
    client.wait_for_message_matching(r"Regen:", timeout_ms=30_000)
    if "Regen: on" in client.last_message_text(timeout_ms=5_000):
        client.click_inline_button("Regen")
        client.wait_for_message_matching(r"Regen:\s*off", timeout_ms=30_000)
    client.send_and_wait("e2e-regen-check", r"echo:", wait_timeout_ms=90_000)
    labels = client.inline_button_labels(timeout_ms=10_000)
    if any("Regen" in label for label in labels):
        msg = f"Regen QA button still visible after toggle off: {labels}"
        raise TelegramAssertionError(msg)


def test_queue_mode_cycle_persists(client: TelegramClient) -> None:
    """Queue mode toggle updates the Session caption (cancel ↔ steer)."""
    _open_config(client)
    client.click_inline_button("Session")
    text = client.wait_for_message_matching(r"Queue mode:", timeout_ms=30_000)
    if "steer" in text:
        client.click_inline_button("Queue:")
        client.wait_for_message_matching(r"Queue mode:\s*cancel", timeout_ms=30_000)
    else:
        client.click_inline_button("Queue:")
        client.wait_for_message_matching(r"Queue mode:\s*steer", timeout_ms=30_000)


def test_queue_mode_runtime_reflects(client: TelegramClient) -> None:
    """Steer mode queues overlapping echo dispatches; token appears in ``/logs``."""
    _open_config(client)
    client.click_inline_button("Session")
    caption = client.wait_for_message_matching(r"Queue mode:", timeout_ms=30_000)
    if "steer" not in caption:
        client.click_inline_button("Queue:")
        client.wait_for_message_matching(r"Queue mode:\s*steer", timeout_ms=30_000)
    client.send_message("e2e-steer-a")
    time.sleep(0.4)
    client.send_message("e2e-steer-b")
    client.wait_for_message_matching(r"echo:\s*e2e-steer-b", timeout_ms=90_000)
    client.send_message("/logs tail gateway 80")
    assert_message_contains(client, _STEER_LOG_TOKEN, timeout_ms=45_000)


def test_logs_section_smoke(client: TelegramClient) -> None:
    """Navigate to Logs and press Tail gateway (owner smoke; actions may be 🚧 until TE-9)."""
    _open_config(client)
    client.click_inline_button("Logs")
    client.wait_for_message_matching(r"^Logs", timeout_ms=30_000)
    client.click_inline_button("Tail gateway")
    text = client.wait_for_message_matching(r".+", timeout_ms=30_000)
    if not text.strip():
        raise TelegramAssertionError("empty response after Tail gateway")


def test_channels_section_buttons(client: TelegramClient) -> None:
    """Channels section exposes Show routing toggle without 🚧 on the routing row."""
    _open_channels(client)
    labels = client.wait_for_inline_keyboard(
        min_buttons=3,
        label_contains="Show routing",
        timeout_ms=30_000,
    )
    routing_labels = [label for label in labels if "Show routing" in label]
    if not routing_labels:
        msg = f"Show routing toggle missing in Channels section: {labels}"
        raise TelegramAssertionError(msg)
    if any("🚧" in label for label in routing_labels):
        msg = f"Show routing toggle locked with 🚧: {routing_labels}"
        raise TelegramAssertionError(msg)


def test_show_routing_toggle_persists_in_caption(client: TelegramClient) -> None:
    """Toggling Show routing updates the Channels caption (on ↔ off)."""
    _open_channels(client)
    text = client.wait_for_message_matching(r"Show routing footer:\s*(on|off)", timeout_ms=30_000)
    if re.search(r"Show routing footer:\s*on", text, re.IGNORECASE):
        expected_after = r"Show routing footer:\s*off"
    else:
        expected_after = r"Show routing footer:\s*on"
    client.click_inline_button("Show routing")
    client.wait_for_message_matching(expected_after, timeout_ms=30_000)


def test_show_routing_toggle_affects_next_reply(client: TelegramClient) -> None:
    """Show routing on adds intent/tier footer to the next bot reply; off omits it."""
    probe_on = "smoke-routing-on"
    probe_off = "smoke-routing-off"
    _ensure_show_routing(client, enabled=True)
    client.send_message(probe_on)
    client.wait_for_message_matching(_ROUTING_FOOTER_RE, timeout_ms=120_000)

    _ensure_show_routing(client, enabled=False)
    client.send_message(probe_off)
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        for text in reversed(client.recent_message_texts(limit=20)):
            if probe_off in text or "Show routing footer:" in text or text.startswith("Channels"):
                continue
            if probe_on in text or text.strip().startswith("/config"):
                continue
            if len(text.strip()) < 8:
                continue
            if _ROUTING_FOOTER_RE.search(text):
                msg = f"routing footer present when show_routing is off: {text!r}"
                raise TelegramAssertionError(msg)
            return
        time.sleep(0.5)
    msg = "timed out waiting for bot reply without routing footer after show_routing off"
    raise TimeoutError(msg)


SESSION_TESTS: tuple[tuple[str, Callable[[TelegramClient], None | str]], ...] = (
    ("test_deployment_id_visible", test_deployment_id_visible),
    ("test_config_opens", test_config_opens),
    ("test_session_section_buttons", test_session_section_buttons),
    ("test_regen_toggle_persists_in_caption", test_regen_toggle_persists_in_caption),
    ("test_regen_toggle_affects_next_reply", test_regen_toggle_affects_next_reply),
    ("test_queue_mode_cycle_persists", test_queue_mode_cycle_persists),
    ("test_queue_mode_runtime_reflects", test_queue_mode_runtime_reflects),
    ("test_logs_section_smoke", test_logs_section_smoke),
    ("test_channels_section_buttons", test_channels_section_buttons),
    ("test_show_routing_toggle_persists_in_caption", test_show_routing_toggle_persists_in_caption),
    ("test_show_routing_toggle_affects_next_reply", test_show_routing_toggle_affects_next_reply),
)


def session_tests_for_settings(
    settings: TelegramTesterSettings,
) -> tuple[tuple[str, Callable[[TelegramClient], None | str]], ...]:
    """Return session tests to run for ``settings`` (prod omits echo probes by default).

    Args:
        settings: Host-runner settings.

    Returns:
        Filtered test list.

    Examples:
        >>> from sevn_telegram_tester.config import TelegramTesterSettings
        >>> names = [n for n, _ in session_tests_for_settings(TelegramTesterSettings(target='prod'))]
        >>> 'test_queue_mode_runtime_reflects' in names
        False
    """
    if settings.echo_mode_enabled():
        return SESSION_TESTS
    return tuple(row for row in SESSION_TESTS if row[0] not in _ECHO_PROBE_TESTS)


def run_session_suite(
    page: Page,
    settings: TelegramTesterSettings,
) -> JsonReport:
    """Execute the session /config pack against an open Telegram Web page.

    Args:
        page: Logged-in Playwright page on Telegram Web K.
        settings: Host-runner settings (bot username, optional deployment id check).

    Returns:
        JsonReport with per-test rows and optional ``deployment_id_observed``.

    Examples:
        >>> run_session_suite  # doctest: +SKIP
    """
    bot = settings.require_bot_username()
    client = TelegramClient(page, bot_username=bot)
    client.open_bot_chat()

    report = JsonReport(
        suite="session",
        target=settings.target,
        artifacts_dir=str(settings.artifacts_dir),
    )
    deployment_observed: str | None = None
    tests = session_tests_for_settings(settings)
    if not settings.echo_mode_enabled():
        skipped = [n for n, _ in SESSION_TESTS if n in _ECHO_PROBE_TESTS]
        if skipped:
            logger.info(
                "skipping echo-probe tests on target={} (no e2e-* chat spam): {}",
                settings.target,
                ", ".join(skipped),
            )

    for name, fn in tests:
        logger.info("running {}", name)
        try:
            result = fn(client)
            if name == "test_deployment_id_visible" and isinstance(result, str):
                deployment_observed = result
                if settings.test_deployment_id and settings.test_deployment_id not in result:
                    msg = (
                        f"TEST_DEPLOYMENT_ID mismatch: expected {settings.test_deployment_id!r}, "
                        f"observed {result!r}"
                    )
                    raise TelegramAssertionError(msg)
            report.tests.append(JsonTestResult(name=name, status="passed"))
        except (TelegramAssertionError, TimeoutError, AssertionError) as exc:
            logger.error("{} failed: {}", name, exc)
            report.tests.append(
                JsonTestResult(name=name, status="failed", message=str(exc)),
            )
        except Exception as exc:
            logger.exception("{} error", name)
            report.tests.append(
                JsonTestResult(name=name, status="failed", message=f"{type(exc).__name__}: {exc}"),
            )

    if not settings.echo_mode_enabled():
        for name in _ECHO_PROBE_TESTS:
            report.tests.append(
                JsonTestResult(name=name, status="skipped", message=_SKIP_ECHO_ON_PROD_MSG),
            )

    report.deployment_id_observed = deployment_observed
    return report
