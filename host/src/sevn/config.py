"""Host settings from SEVN_* variables and $SEVN_HOME/config.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from sevn.errors import ConfigError
from sevn.paths import Paths

type BackendName = Literal["keychain", "age-file", "env", "secret-service"]
type DecisionProvider = Literal["jev", "llm", "rules"]
type ExporterName = Literal["none", "logfire", "otlp"]
type ExportPreset = Literal["", "datadog-agent", "datadog-agentless"]
type OtlpProtocol = Literal["http/protobuf", "grpc"]

SECRET_REF_PREFIX = "secret://"  # noqa: S105 — the reference scheme, not a value


class ProtocolSettings(BaseModel):
    session_queue_limit: int = 1000


class SecretsSettings(BaseModel):
    backend: BackendName | None = None


class HttpSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    # Plan 0055 D5: extra Host names (``host`` or ``host:port``), e.g. a tailnet name.
    allowed_hosts: list[str] = Field(default_factory=list)
    # ``https`` when a proxy such as ``tailscale serve`` terminates TLS in front of sevn.
    public_scheme: Literal["http", "https"] = "http"
    # Exact origins of web clients served by other hosts (``https://linux.tailnet.ts.net``).
    allowed_origins: list[str] = Field(default_factory=list)
    # Extra CSP ``connect-src`` sources: other hosts this SPA dials (plan 0055 D8).
    connect_src: list[str] = Field(default_factory=list)

    def merged_allowed_hosts(self) -> list[str]:
        """``allowed_hosts`` then ``SEVN_ALLOWED_HOSTS`` (comma-separated), lower-cased, deduped.

        The one list the Host guard, the WebSocket session and the pairing URL share.
        """
        raw = [*self.allowed_hosts, *os.environ.get("SEVN_ALLOWED_HOSTS", "").split(",")]
        merged: list[str] = []
        for item in raw:
            cleaned = item.strip().lower()
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
        return merged


class RuntimeSettings(BaseModel):
    """Host-wide runtime caps (D7). Absent config keeps the defaults."""

    max_running_turns: int = 3


class BotsSettings(BaseModel):
    """Per-bot limits from spec §5.1. Absent config keeps the defaults."""

    max_parallel_agents: int = 3


class BudgetsSettings(BaseModel):
    """Daily spend caps in USD for routines. Unset means no cap."""

    daily_usd_per_bot: float | None = None
    daily_usd_host: float | None = None


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


class RuntimeInstallSettings(BaseModel):
    """One CLI runtime's resolution policy (plan 0025 D6)."""

    use_system: bool = True


class RuntimesSettings(BaseModel):
    """Managed CLI runtime installs (plan 0025 D6).

    ``dir`` overrides ``$SEVN_HOME/runtimes`` (``SEVN_RUNTIMES_DIR`` overrides both). Each
    runtime's ``use_system`` lets resolution fall back to the copy on ``PATH``.
    """

    model_config = ConfigDict(populate_by_name=True)

    dir: Path | None = None
    claude: RuntimeInstallSettings = Field(default_factory=RuntimeInstallSettings)
    opencode: RuntimeInstallSettings = Field(default_factory=RuntimeInstallSettings)
    codex: RuntimeInstallSettings = Field(default_factory=RuntimeInstallSettings)
    cursor_agent: RuntimeInstallSettings = Field(
        default_factory=RuntimeInstallSettings, alias="cursor-agent"
    )

    def for_runtime(self, name: str) -> RuntimeInstallSettings:
        """The policy for ``name``; a runtime without a section keeps the defaults."""
        match name:
            case "claude":
                return self.claude
            case "opencode":
                return self.opencode
            case "codex":
                return self.codex
            case "cursor-agent":
                return self.cursor_agent
            case _:
                return RuntimeInstallSettings()


class ObservabilitySettings(BaseModel):
    """OTel export (spec §12, plan 0015 D1). Nothing is exported unless an exporter is on.

    ``exporter = None`` means auto: Logfire when the secret ``logfire/token`` exists,
    else off. ``headers`` values are ``secret://<name>`` references, resolved only
    when the exporters are built.
    """

    exporter: ExporterName | None = None
    preset: ExportPreset = ""
    endpoint: str = ""
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    protocol: OtlpProtocol = "http/protobuf"
    capture_content: bool = False
    sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    datadog_site: str = "datadoghq.com"
    service_name: str = "sevnd"

    @field_validator("headers")
    @classmethod
    def _headers_are_secret_refs(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            # Name the header only: the refused value may be a credential.
            if not item.startswith(SECRET_REF_PREFIX) or item == SECRET_REF_PREFIX:
                raise ValueError(
                    f"header {key!r} must be a {SECRET_REF_PREFIX}<name> reference; "
                    "store the value with the secret backend"
                )
        return value

    @model_validator(mode="after")
    def _agentless_is_http(self) -> ObservabilitySettings:
        if self.preset == "datadog-agentless" and self.protocol == "grpc":
            raise ValueError(
                "preset 'datadog-agentless' does not support protocol 'grpc'; "
                "Datadog's agentless intake accepts http/protobuf only"
            )
        return self


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
    budgets: BudgetsSettings = Field(default_factory=BudgetsSettings)
    runtimes: RuntimesSettings = Field(default_factory=RuntimesSettings)

    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

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
