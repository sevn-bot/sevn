"""Environment and path settings for the Telegram Web tester.

Module: sevn_telegram_tester.config
Depends: pydantic, pydantic-settings

Exports:
    TelegramTesterSettings — host-runner configuration.
    package_root — ``tools/telegram-tester`` directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

package_root = Path(__file__).resolve().parents[2]
default_profile_dir = package_root / ".browser-profile"
default_artifacts_dir = package_root / "artifacts"

TargetKind = Literal["local", "prod"]


class TelegramTesterSettings(BaseSettings):
    """Operator settings for Playwright runs on the developer machine."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    target: TargetKind = Field(default="local")
    tg_target_bot: str | None = Field(default=None, validation_alias="TG_TARGET_BOT")
    test_deployment_id: str | None = Field(default=None, validation_alias="TEST_DEPLOYMENT_ID")
    sevn_gateway_port: int = Field(default=3001, validation_alias="SEVN_GATEWAY_PORT")
    browser_profile_dir: Path = Field(default_factory=lambda: default_profile_dir)
    artifacts_dir: Path = Field(default_factory=lambda: default_artifacts_dir)
    headless: bool = Field(default=False, validation_alias="TELEGRAM_TEST_HEADLESS")
    telegram_web_url: str = Field(default="https://web.telegram.org/k/")
    browser_viewport_width: int = Field(
        default=1920, validation_alias="TELEGRAM_TEST_VIEWPORT_WIDTH"
    )
    browser_viewport_height: int = Field(
        default=1080, validation_alias="TELEGRAM_TEST_VIEWPORT_HEIGHT"
    )
    browser_device_scale_factor: float = Field(
        default=1.0,
        validation_alias="TELEGRAM_TEST_DEVICE_SCALE_FACTOR",
    )
    browser_channel: str | None = Field(
        default=None,
        validation_alias="TELEGRAM_TEST_BROWSER_CHANNEL",
        description="Playwright browser channel, e.g. chrome (system Chrome) or chromium (bundled).",
    )
    telegram_test_echo_mode: bool | None = Field(
        default=None,
        validation_alias="TELEGRAM_TEST_ECHO_MODE",
        description="When true, run echo-probe tests (e2e-steer-*). Default: on for target=local only.",
    )

    def echo_mode_enabled(self) -> bool:
        """Whether tests may send ``e2e-*`` probe messages that require gateway echo replies.

        Returns:
            True for ``target=local`` (compose E2E override) or explicit ``TELEGRAM_TEST_ECHO_MODE=1``.

        Examples:
            >>> TelegramTesterSettings(target="local").echo_mode_enabled()
            True
            >>> TelegramTesterSettings(target="prod").echo_mode_enabled()
            False
            >>> TelegramTesterSettings(target="prod", telegram_test_echo_mode=True).echo_mode_enabled()
            True
        """
        if self.telegram_test_echo_mode is not None:
            return self.telegram_test_echo_mode
        return self.target == "local"

    @property
    def gateway_base_url(self) -> str:
        """HTTP base URL for ``--target local`` readiness checks."""
        return f"http://127.0.0.1:{self.sevn_gateway_port}"

    @property
    def repo_root(self) -> Path:
        """sevn.bot repository root (contains ``docker/docker-compose.yml``)."""
        return package_root.parent.parent

    def require_bot_username(self) -> str:
        """Return ``tg_target_bot`` or raise when unset.

        Returns:
            Bot handle without leading ``@``.

        Raises:
            ValueError: When ``TG_TARGET_BOT`` is missing.

        Examples:
            >>> TelegramTesterSettings(tg_target_bot="mybot").require_bot_username()
            'mybot'
        """
        if not self.tg_target_bot or not str(self.tg_target_bot).strip():
            msg = "TG_TARGET_BOT is required (set in .env or pass --bot-username)"
            raise ValueError(msg)
        return str(self.tg_target_bot).lstrip("@")
