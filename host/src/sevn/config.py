"""Host settings from SEVN_* variables and $SEVN_HOME/config.toml."""

from __future__ import annotations

import tomllib
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from sevn.errors import ConfigError
from sevn.paths import Paths

type BackendName = Literal["keychain", "age-file", "env"]


class ProtocolSettings(BaseModel):
    session_queue_limit: int = 1000


class SecretsSettings(BaseModel):
    backend: BackendName | None = None


class HttpSettings(BaseModel):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEVN_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    protocol: ProtocolSettings = Field(default_factory=ProtocolSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_file = Paths.from_env().home / "config.toml"
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=toml_file),
        )

    @classmethod
    def load(cls) -> Settings:
        try:
            return cls()
        except ValidationError as exc:
            raise ConfigError(_validation_message(exc)) from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"config.toml: {exc}") from exc


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(item) for item in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    return "invalid config: " + "; ".join(parts)
