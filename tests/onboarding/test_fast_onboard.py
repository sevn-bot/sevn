"""Fast ``sevn onboard --config`` pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.onboarding.fast_onboard import (
    FastOnboardValidationError,
    merge_config_layers,
    run_fast_onboard,
)
from sevn.onboarding.live_validate import (
    ValidationCheck,
    ValidationReport,
    handoff_credential_keys_for_doc,
    llm_provider_configured,
    telegram_channel_enabled,
)
from sevn.onboarding.validate import validate_workspace_document

_FIXTURE_MIN = Path(__file__).resolve().parents[1] / "fixtures" / "config" / "schema_v1_min.json"
_FIXTURE_RICH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "config"
    / "fast_onboard_telegram_minimax.json"
)


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_handoff_credential_keys_channel_aware() -> None:
    """Telegram and LLM keys are required only when those features are enabled."""
    assert handoff_credential_keys_for_doc(
        {"channels": {"telegram": {"enabled": True}}}
    ) == frozenset({"SEVN_TELEGRAM_BOT_TOKEN"})
    assert handoff_credential_keys_for_doc(
        {
            "schema_version": 1,
            "gateway": {"token": "t"},
            "providers": {"tier_default": {"triager": "minimax/M2"}},
        }
    ) == frozenset({"SEVN_SECRET_MINIMAX"})
    assert (
        handoff_credential_keys_for_doc(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        )
        == frozenset()
    )


def test_telegram_and_llm_helpers() -> None:
    """Channel and provider helpers match fixture shape."""
    rich = json.loads(_FIXTURE_RICH.read_text(encoding="utf-8"))
    assert telegram_channel_enabled(rich)
    assert llm_provider_configured(rich)
    minimal = json.loads(_FIXTURE_MIN.read_text(encoding="utf-8"))
    assert not telegram_channel_enabled(minimal)
    assert not llm_provider_configured(minimal)


@pytest.mark.asyncio
async def test_run_fast_onboard_fails_schema_before_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid schema exits before ``sevn.json`` is written."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    sevn_json = home / "workspace" / "sevn.json"

    with pytest.raises(FastOnboardValidationError):
        await run_fast_onboard(
            config_doc={
                "schema_version": 999,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
            profile_id=None,
            bot_name="Bot",
            prompt_for_bot_name=False,
            install_daemon=False,
            start_services=False,
        )
    assert not sevn_json.is_file()


@pytest.mark.asyncio
async def test_run_fast_onboard_fails_live_before_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live validation errors block promote."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    sevn_json = home / "workspace" / "sevn.json"
    doc = json.loads(_FIXTURE_RICH.read_text(encoding="utf-8"))

    fail_report = ValidationReport(
        checks=[
            ValidationCheck(
                check_id="telegram_get_me",
                ok=False,
                severity="error",
                detail="token bad",
                hint="fix token",
            )
        ]
    )

    with (
        patch(
            "sevn.onboarding.fast_onboard.run_live_validation",
            new_callable=AsyncMock,
            return_value=fail_report,
        ),
        patch(
            "sevn.onboarding.fast_onboard.credentials_status",
            new_callable=AsyncMock,
            return_value={
                "present": {
                    "SEVN_TELEGRAM_BOT_TOKEN": True,
                    "SEVN_SECRET_MINIMAX": True,
                },
                "ready_for_handoff": True,
                "needs_passphrase": False,
            },
        ),
        pytest.raises(FastOnboardValidationError, match="telegram_get_me"),
    ):
        await run_fast_onboard(
            config_doc=doc,
            profile_id=None,
            prompt_for_bot_name=False,
            install_daemon=False,
            start_services=False,
        )
    assert not sevn_json.is_file()


@pytest.mark.asyncio
async def test_run_fast_onboard_bot_name_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--bot-name`` wins over file ``agent.display_name``."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    doc = json.loads(_FIXTURE_MIN.read_text(encoding="utf-8"))

    ok_report = ValidationReport()

    with (
        patch(
            "sevn.onboarding.fast_onboard.run_live_validation",
            new_callable=AsyncMock,
            return_value=ok_report,
        ),
        patch(
            "sevn.onboarding.fast_onboard.credentials_status",
            new_callable=AsyncMock,
            return_value={
                "present": {},
                "ready_for_handoff": True,
                "needs_passphrase": False,
            },
        ),
        patch("sevn.cli.install_gate.maybe_install_daemon_after_promote", return_value=None),
        patch(
            "sevn.onboarding.fast_onboard.maybe_install_pdf_native_libs_after_promote",
            return_value=None,
        ),
    ):
        result = await run_fast_onboard(
            config_doc=doc,
            profile_id=None,
            bot_name="OverrideName",
            prompt_for_bot_name=False,
            install_daemon=False,
            start_services=False,
        )

    promoted = json.loads(result.sevn_json_path.read_text(encoding="utf-8"))
    assert promoted["agent"]["display_name"] == "OverrideName"


@pytest.mark.asyncio
async def test_run_fast_onboard_calls_pdf_native_install_on_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-promote hook installs WeasyPrint natives on macOS when degraded."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    doc = json.loads(_FIXTURE_MIN.read_text(encoding="utf-8"))
    ok_report = ValidationReport()

    with (
        patch(
            "sevn.onboarding.fast_onboard.run_live_validation",
            new_callable=AsyncMock,
            return_value=ok_report,
        ),
        patch(
            "sevn.onboarding.fast_onboard.credentials_status",
            new_callable=AsyncMock,
            return_value={
                "present": {},
                "ready_for_handoff": True,
                "needs_passphrase": False,
            },
        ),
        patch("sevn.cli.install_gate.maybe_install_daemon_after_promote", return_value=None),
        patch(
            "sevn.onboarding.fast_onboard.maybe_install_pdf_native_libs_after_promote",
            return_value="installed WeasyPrint native libs via brew install pango",
        ) as mock_pdf,
    ):
        result = await run_fast_onboard(
            config_doc=doc,
            profile_id=None,
            bot_name="PdfBot",
            prompt_for_bot_name=False,
            install_daemon=False,
            start_services=False,
        )

    mock_pdf.assert_called_once()
    assert (
        result.pdf_native_install_line == "installed WeasyPrint native libs via brew install pango"
    )


def test_merge_applies_model_slot_policy() -> None:
    """Unified model flag strips per-slot overrides like web promote."""
    doc = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "providers": {
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/M2", "B": "extra"},
        },
    }
    merged = merge_config_layers(doc, profile_id=None)
    from sevn.config.provider_secrets import apply_provider_credential_bindings
    from sevn.onboarding.web_app import apply_model_slot_policy

    apply_model_slot_policy(merged)
    apply_provider_credential_bindings(merged)
    tier = merged["providers"]["tier_default"]
    assert tier == {"triager": "minimax/M2"}
    validate_workspace_document(merged)


def test_onboard_config_cli_happy_path_mocked(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI ``--config`` delegates to fast onboard and exits 0 when handoff is mocked."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))

    from sevn.onboarding.fast_onboard import FastOnboardResult

    fake_result = FastOnboardResult(
        sevn_json_path=home / "workspace" / "sevn.json",
        seeded_paths=(),
        daemon_install_line="units installed",
        pdf_native_install_line=None,
        services_restart={"message": "gateway started"},
    )

    with patch(
        "sevn.cli.commands.onboard.run_fast_onboard",
        new=AsyncMock(return_value=fake_result),
    ):
        result = runner.invoke(
            get_command(app),
            [
                "onboard",
                "--config",
                str(_FIXTURE_MIN),
                "--no-prompt-bot-name",
                "--bot-name",
                "CliBot",
            ],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "promoted config to" in result.stdout
    assert "units installed" in result.stdout
    assert "gateway started" in result.stdout


def test_onboard_config_cli_validation_exit_2(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI maps ``FastOnboardValidationError`` to exit code 2."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))

    mock_run = AsyncMock(side_effect=FastOnboardValidationError("schema bad"))
    with patch("sevn.cli.commands.onboard.run_fast_onboard", new=mock_run):
        result = runner.invoke(
            get_command(app),
            ["onboard", "--config", str(_FIXTURE_MIN), "--no-prompt-bot-name", "--bot-name", "x"],
        )
    assert result.exit_code == 2
    assert "schema bad" in result.stderr
