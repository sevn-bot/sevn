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
type DecisionProvider = Literal["jev", "llm", "rules"]


class ProtocolSettings(BaseModel):
    session_queue_limit: int = 1000


class SecretsSettings(BaseModel):
    backend: BackendName | None = None


class HttpSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787


class RuntimeSettings(BaseModel):
    """Host-wide runtime caps (D7). Absent config keeps the defaults."""

    max_running_turns: int = 3


class BotsSettings(BaseModel):
    """Per-bot limits from spec §5.1. Absent config keeps the defaults."""

    max_parallel_agents: int = 3


class DecisionThresholds(BaseModel):
    """Confidence gates for the jev router questions (D4)."""

    intent: float = 0.70
    target: float = 0.65
    busy: float = 0.60


class MemorySettings(BaseModel):
    """Pinned memories share one byte budget (D9). Absent config keeps 4 KB."""

    pinned_budget: int = 4096


class DecisionsSettings(BaseModel):
    """How the host answers decision points (spec §7, D4)."""

    provider: DecisionProvider = "jev"
    jev_model: str = "jev-1.13.0"
    llm_model: str = ""
    ollama_model: str = "llama3.2:3b"
    allow_cli_fallback: bool = True
    evals_on: bool = False
    thresholds: DecisionThresholds = Field(default_factory=DecisionThresholds)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEVN_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    protocol: ProtocolSettings = Field(default_factory=ProtocolSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    bots: BotsSettings = Field(default_factory=BotsSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    decisions: DecisionsSettings = Field(default_factory=DecisionsSettings)

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
