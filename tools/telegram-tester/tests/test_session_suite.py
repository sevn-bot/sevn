"""Unit tests for session suite orchestration (mocked TelegramClient)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sevn_telegram_tester.assertions import TelegramAssertionError
from sevn_telegram_tester.config import TelegramTesterSettings
from sevn_telegram_tester.reporting.json_report import JsonReport
from sevn_telegram_tester.suites import session as session_mod


def test_run_session_suite_records_pass_and_fail() -> None:
    page = MagicMock()
    settings = TelegramTesterSettings(
        tg_target_bot="devbot",
        target="local",
        test_deployment_id=None,
    )

    def _pass(_client: object) -> str:
        return "dep-1"

    def _fail(_client: object) -> None:
        raise TelegramAssertionError("simulated")

    stub_tests = (
        ("test_deployment_id_visible", _pass),
        ("test_config_opens", lambda _c: None),
        ("test_session_section_buttons", _fail),
    )

    with (
        patch.object(session_mod, "SESSION_TESTS", stub_tests),
        patch.object(session_mod, "session_tests_for_settings", return_value=stub_tests),
        patch.object(session_mod, "TelegramClient") as client_cls,
    ):
        client_cls.return_value = MagicMock()
        report = session_mod.run_session_suite(page, settings)

    assert isinstance(report, JsonReport)
    assert report.deployment_id_observed == "dep-1"
    assert len(report.tests) == 3
    assert report.tests[0].status == "passed"
    assert report.tests[2].status == "failed"


def test_session_tests_for_settings_prod_omits_echo_probes() -> None:
    prod_names = {
        n for n, _ in session_mod.session_tests_for_settings(TelegramTesterSettings(target="prod"))
    }
    local_names = {
        n for n, _ in session_mod.session_tests_for_settings(TelegramTesterSettings(target="local"))
    }
    assert local_names >= session_mod._ECHO_PROBE_TESTS
    assert session_mod._ECHO_PROBE_TESTS.isdisjoint(prod_names)


def test_prod_run_appends_skipped_echo_probe_rows() -> None:
    page = MagicMock()
    settings = TelegramTesterSettings(tg_target_bot="devbot", target="prod")
    stub_tests: tuple[tuple[str, object], ...] = (("test_config_opens", lambda _c: None),)

    with (
        patch.object(session_mod, "session_tests_for_settings", return_value=stub_tests),
        patch.object(session_mod, "TelegramClient") as client_cls,
    ):
        client_cls.return_value = MagicMock()
        report = session_mod.run_session_suite(page, settings)

    skipped_names = {row.name for row in report.tests if row.status == "skipped"}
    assert skipped_names == session_mod._ECHO_PROBE_TESTS
    assert report.tests[0].status == "passed"
