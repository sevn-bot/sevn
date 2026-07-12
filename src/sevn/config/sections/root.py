"""Root ``WorkspaceConfig`` model and section coercers for ``sevn.json``.

Module: sevn.config.sections.root
Depends: pydantic, sevn.code_understanding.models, sevn.config.sections.*

Exports:
    WorkspaceConfig — root document; unknown top-level keys are preserved.
"""

# Pydantic root model: section types are required at runtime for field coercion.
# ruff: noqa: TC001

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from sevn.code_understanding.models import CodeUnderstandingSettings
from sevn.config.sections.agent import AgentWorkspaceConfig
from sevn.config.sections.channels import ChannelsWorkspaceSectionConfig, VoiceConfig
from sevn.config.sections.dashboard import DashboardWorkspaceConfig
from sevn.config.sections.docs import DocsWorkspaceSectionConfig
from sevn.config.sections.evolution import MySevnWorkspaceConfig, SpecKitWorkspaceConfig
from sevn.config.sections.executors import (
    ExecutorsWorkspaceConfig,
    PlanApprovalWorkspaceConfig,
    RlmWorkspaceConfig,
)
from sevn.config.sections.features import (
    OpenUIWorkspaceConfig,
    PluginHookEntryConfig,
    SecondBrainWorkspaceConfig,
)
from sevn.config.sections.gateway import (
    DispatcherStateWorkspaceConfig,
    GatewayConfig,
    HarnessWorkspaceConfig,
    ReplayWorkspaceConfig,
)
from sevn.config.sections.logging import LoggingWorkspaceConfig
from sevn.config.sections.memory import LcmWorkspaceConfig, MemoryWorkspaceSectionConfig
from sevn.config.sections.ops import (
    OnboardingWorkspaceSectionConfig,
    TelemetryWorkspaceSectionConfig,
    TriggersWorkspaceConfig,
    WorkspaceOutputSectionConfig,
)
from sevn.config.sections.providers import ProvidersWorkspaceSectionConfig
from sevn.config.sections.provisioning import ProvisioningWorkspaceConfig
from sevn.config.sections.secrets import (
    SecretsBackendSectionConfig,
    _coerce_secrets_backend_model,
)
from sevn.config.sections.security import (
    DeploymentConfig,
    SandboxConfig,
    SecurityWorkspaceConfig,
)
from sevn.config.sections.self_improve import SelfImproveWorkspaceConfig
from sevn.config.sections.subagents import SubAgentsWorkspaceConfig
from sevn.config.sections.tracing import TracingConfig
from sevn.config.sections.triager import TriagerWorkspaceConfig

JsonDict = dict[str, Any]


class WorkspaceConfig(BaseModel):
    """Workspace config document (``sevn.json``).

    Typed nested sections cover values read early in bootstrap; additional
    top-level keys (``providers``, ``channels``, …) are kept in ``model_extra``.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = Field(ge=1)
    workspace_root: str = "."
    workspace: WorkspaceOutputSectionConfig | None = None
    timezone: str | None = None
    gateway: GatewayConfig | None = None
    dispatcher_state: DispatcherStateWorkspaceConfig | None = None
    dashboard: DashboardWorkspaceConfig | None = None
    proxy: JsonDict | None = None
    secrets_backend: SecretsBackendSectionConfig | None = None
    tracing: TracingConfig | None = None
    deployment: DeploymentConfig | None = None
    sandbox: SandboxConfig | None = None
    security: SecurityWorkspaceConfig | None = None
    channels: ChannelsWorkspaceSectionConfig | None = None
    voice: VoiceConfig | None = None
    providers: ProvidersWorkspaceSectionConfig | None = None
    provisioning: ProvisioningWorkspaceConfig | None = None
    triager: TriagerWorkspaceConfig | None = None
    subagents: SubAgentsWorkspaceConfig | None = None
    memory: MemoryWorkspaceSectionConfig | None = None
    lcm: LcmWorkspaceConfig | None = None
    rlm: RlmWorkspaceConfig | None = None
    executors: ExecutorsWorkspaceConfig | None = None
    plan_approval: PlanApprovalWorkspaceConfig | None = None
    replay: ReplayWorkspaceConfig | None = None
    harness: HarnessWorkspaceConfig | None = None
    permissions: JsonDict | None = None
    skills: JsonDict | None = None
    tools: JsonDict | None = None
    onboarding: OnboardingWorkspaceSectionConfig | None = None
    telemetry: TelemetryWorkspaceSectionConfig | None = None
    second_brain: SecondBrainWorkspaceConfig | None = None
    openui: OpenUIWorkspaceConfig | None = None
    triggers: TriggersWorkspaceConfig | None = None
    logging: LoggingWorkspaceConfig | None = None
    self_improve: SelfImproveWorkspaceConfig | None = None
    spec_kit: SpecKitWorkspaceConfig | None = None
    my_sevn: MySevnWorkspaceConfig | None = None
    plugin_hooks: dict[str, PluginHookEntryConfig] | None = None
    code_understanding: CodeUnderstandingSettings | None = None
    docs: DocsWorkspaceSectionConfig | None = None
    agent: AgentWorkspaceConfig | None = None

    @field_validator("agent", mode="before")
    @classmethod
    def _coerce_agent_section(cls, v: object) -> object:
        """Parse optional ``agent`` subtree (CodeMode + diagnostics slot).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_agent_section(None) is None
            True
        """
        if v is None or isinstance(v, AgentWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return AgentWorkspaceConfig.model_validate(v)
        msg = f"invalid agent section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("docs", mode="before")
    @classmethod
    def _coerce_docs_section(cls, v: object) -> object:
        """Parse optional ``docs`` subtree (README pipeline settings).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_docs_section(None) is None
            True
        """
        if v is None or isinstance(v, DocsWorkspaceSectionConfig):
            return v
        if isinstance(v, dict):
            return DocsWorkspaceSectionConfig.model_validate(v)
        msg = f"invalid docs section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("code_understanding", mode="before")
    @classmethod
    def _coerce_code_understanding_section(cls, v: object) -> object:
        """Parse optional ``code_understanding`` subtree (`specs/28-code-understanding.md` §2.1).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_code_understanding_section(None) is None
            True
        """
        if v is None or isinstance(v, CodeUnderstandingSettings):
            return v
        if isinstance(v, dict):
            return CodeUnderstandingSettings.model_validate(v)
        msg = f"invalid code_understanding section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("providers", mode="before")
    @classmethod
    def _coerce_providers_section(cls, v: object) -> object:
        """Parse ``providers`` dict into a typed section while keeping extras.

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_providers_section(None) is None
            True
        """
        if v is None or isinstance(v, ProvidersWorkspaceSectionConfig):
            return v
        if isinstance(v, dict):
            return ProvidersWorkspaceSectionConfig.model_validate(v)
        msg = f"invalid providers section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("channels", mode="before")
    @classmethod
    def _coerce_channels_section(cls, v: object) -> object:
        """Parse ``channels`` dict into a typed section while keeping extras.

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_channels_section(None) is None
            True
        """

        if v is None or isinstance(v, ChannelsWorkspaceSectionConfig):
            return v
        if isinstance(v, dict):
            return ChannelsWorkspaceSectionConfig.model_validate(v)
        msg = f"invalid channels section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("dashboard", mode="before")
    @classmethod
    def _coerce_dashboard_section(cls, v: object) -> object:
        """Parse optional ``dashboard`` subtree (`specs/24-dashboard.md` §5).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_dashboard_section(None) is None
            True
        """

        if v is None or isinstance(v, DashboardWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return DashboardWorkspaceConfig.model_validate(v)
        msg = f"invalid dashboard section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("second_brain", mode="before")
    @classmethod
    def _coerce_second_brain_section(cls, v: object) -> object:
        """Parse optional ``second_brain`` subtree (`specs/27-second-brain.md` section 5).

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, an existing model, or a coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_second_brain_section(None) is None
            True
        """
        if v is None or isinstance(v, SecondBrainWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return SecondBrainWorkspaceConfig.model_validate(v)
        msg = f"invalid second_brain section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("openui", mode="before")
    @classmethod
    def _coerce_openui_section(cls, v: object) -> object:
        """Parse optional ``openui`` subtree (`specs/29-openui.md` §5).

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, an existing model, or a coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_openui_section(None) is None
            True
        """

        if v is None or isinstance(v, OpenUIWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return OpenUIWorkspaceConfig.model_validate(v)
        msg = f"invalid openui section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("triggers", mode="before")
    @classmethod
    def _coerce_triggers_section(cls, v: object) -> object:
        """Parse optional ``triggers`` subtree (`specs/30-non-interactive-triggers.md` §5).

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, an existing model, or a coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_triggers_section(None) is None
            True
        """

        if v is None or isinstance(v, TriggersWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return TriggersWorkspaceConfig.model_validate(v)
        msg = f"invalid triggers section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("self_improve", mode="before")
    @classmethod
    def _coerce_self_improve_section(cls, v: object) -> object:
        """Parse optional ``self_improve`` subtree (`specs/33-self-improvement.md` §5).

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, an existing model, or a coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_self_improve_section(None) is None
            True
        """
        if v is None or isinstance(v, SelfImproveWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return SelfImproveWorkspaceConfig.model_validate(v)
        msg = f"invalid self_improve section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("voice", mode="before")
    @classmethod
    def _coerce_voice_section(cls, v: object) -> object:
        """Parse optional ``voice`` subtree (`specs/20-voice.md` §5).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_voice_section(None) is None
            True
        """

        if v is None or isinstance(v, VoiceConfig):
            return v
        if isinstance(v, dict):
            return VoiceConfig.model_validate(v)
        msg = f"invalid voice section type: {type(v).__name__}"
        raise ValueError(msg)

    @model_validator(mode="after")
    def _lambda_rlm_enabled_requires_backend(self) -> WorkspaceConfig:
        """Require ``rlm.c_d_backend=lambda_rlm`` when the tier-C/D λ gate is enabled.

        Confirmed by ``cd_harness._cd_backend`` (`specs/21-executor-tier-cd.md` §5): the
        opt-in flag alone does not select the λ backend when ``c_d_backend`` stays ``dspy``.

        Args:
            self (WorkspaceConfig): Validated workspace config.

        Returns:
            WorkspaceConfig: Unchanged ``self`` when validation passes.

        Raises:
            ValueError: When λ-RLM is enabled without the matching backend.

        Examples:
            >>> WorkspaceConfig.minimal().schema_version
            1
        """
        executors = self.executors
        if executors is None or executors.tier_cd is None or executors.tier_cd.lambda_rlm is None:
            return self
        if not executors.tier_cd.lambda_rlm.enabled:
            return self
        allowlist: list[str] = []
        if self.rlm is not None:
            allowlist = [str(x) for x in self.rlm.lambda_tool_allowlist if str(x).strip()]
        if not allowlist:
            return self
        backend = self.rlm.c_d_backend if self.rlm is not None else "dspy"
        if backend != "lambda_rlm":
            msg = (
                "rlm.c_d_backend must be lambda_rlm when "
                "executors.tier_cd.lambda_rlm.enabled is true "
                "(specs/21-executor-tier-cd.md §5)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _require_gateway_token(self) -> WorkspaceConfig:
        """Require a non-empty ``gateway.token`` (``specs/17-gateway.md`` §2.1).

        Args:
            self (WorkspaceConfig): Validated workspace config.

        Returns:
            WorkspaceConfig: Unchanged ``self``.

        Raises:
            ValueError: When ``gateway`` or ``gateway.token`` is missing.

        Examples:
            >>> import pytest
            >>> from pydantic import ValidationError
            >>> from sevn.config.workspace_config import parse_workspace_config
            >>> with pytest.raises(ValidationError):
            ...     parse_workspace_config({"schema_version": 1})
        """
        if self.gateway is None or not (self.gateway.token or "").strip():
            msg = (
                "gateway.token is required — run `sevn gateway set-gateway-token` "
                "or set gateway.token in sevn.json"
            )
            raise ValueError(msg)
        return self

    @classmethod
    def minimal(cls, **kwargs: object) -> WorkspaceConfig:
        """Minimal config for tests and doctests (includes a placeholder gateway token).

        Args:
            kwargs (object): Overrides merged onto defaults.

        Returns:
            WorkspaceConfig: Parsed minimal document.

        Examples:
            >>> WorkspaceConfig.minimal().gateway is not None
            True
        """
        defaults: dict[str, object] = {
            "schema_version": 1,
            "gateway": GatewayConfig(token="${SECRET:keychain:sevn.gateway.token}"),  # nosec B106
        }
        defaults.update(kwargs)
        return cls.model_validate(defaults)

    @model_validator(mode="after")
    def _reject_prod_subprocess_fallback(self) -> WorkspaceConfig:
        """Reject subprocess fallback under production deployment (§08 §4.3).

        Args:
            self (WorkspaceConfig): Validated workspace config.

        Returns:
            WorkspaceConfig: Unchanged ``self``.

        Raises:
            ValueError: When production profile allows subprocess fallback.

        Examples:
            >>> import pytest
            >>> from pydantic import ValidationError
            >>> from sevn.config.workspace_config import parse_workspace_config
            >>> bad = {"schema_version": 1,
            ...        "deployment": {"profile": "production"},
            ...        "security": {"sandbox": {"allow_subprocess_fallback": True}}}
            >>> with pytest.raises(ValidationError):
            ...     parse_workspace_config(bad)
            ...
        """
        prof = ""
        if self.deployment and self.deployment.profile:
            prof = self.deployment.profile.strip().lower()
        allow = False
        if self.security and self.security.sandbox:
            allow = bool(self.security.sandbox.allow_subprocess_fallback)
        if prof == "production" and allow:
            msg = (
                "security.sandbox.allow_subprocess_fallback cannot be true when "
                "deployment.profile is production (specs/08-sandbox.md §4.3)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _reject_prod_llmignore_disabled(self) -> WorkspaceConfig:
        """Reject disabling ``.llmignore`` in production (§09 §5).

        Args:
            self (WorkspaceConfig): Validated workspace config.

        Returns:
            WorkspaceConfig: Unchanged ``self``.

        Raises:
            ValueError: When production profile disables llmignore.

        Examples:
            >>> import pytest
            >>> from pydantic import ValidationError
            >>> from sevn.config.workspace_config import parse_workspace_config
            >>> bad = {"schema_version": 1,
            ...        "deployment": {"profile": "production"},
            ...        "security": {"llmignore": {"enabled": False}}}
            >>> with pytest.raises(ValidationError):
            ...     parse_workspace_config(bad)
            ...
        """
        prof = ""
        if self.deployment and self.deployment.profile:
            prof = self.deployment.profile.strip().lower()
        enabled = True
        if self.security and self.security.llmignore is not None:
            enabled = bool(self.security.llmignore.enabled)
        if prof == "production" and not enabled:
            msg = (
                "security.llmignore.enabled cannot be false when "
                "deployment.profile is production (specs/09-security-scanner.md §5)"
            )
            raise ValueError(msg)
        return self

    @field_validator("memory", mode="before")
    @classmethod
    def _coerce_memory_section(cls, v: object) -> object:
        """Parse ``memory`` dict into a typed section while keeping extras.

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_memory_section(None) is None
            True
        """
        if v is None or isinstance(v, MemoryWorkspaceSectionConfig):
            return v
        if isinstance(v, dict):
            return MemoryWorkspaceSectionConfig.model_validate(v)
        msg = f"invalid memory section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("rlm", mode="before")
    @classmethod
    def _coerce_rlm_section(cls, v: object) -> object:
        """Parse optional ``rlm`` subtree (`specs/21-executor-tier-cd.md` §5).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_rlm_section(None) is None
            True
        """

        if v is None or isinstance(v, RlmWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return RlmWorkspaceConfig.model_validate(v)
        msg = f"invalid rlm section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("plan_approval", mode="before")
    @classmethod
    def _coerce_plan_approval_section(cls, v: object) -> object:
        """Parse optional ``plan_approval`` subtree (`specs/21-executor-tier-cd.md` §5).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_plan_approval_section(None) is None
            True
        """

        if v is None or isinstance(v, PlanApprovalWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return PlanApprovalWorkspaceConfig.model_validate(v)
        msg = f"invalid plan_approval section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("lcm", mode="before")
    @classmethod
    def _coerce_lcm_section(cls, v: object) -> object:
        """Parse optional ``lcm`` subtree (`specs/15-memory-lcm.md` §5).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_lcm_section(None) is None
            True
        """
        if v is None or isinstance(v, LcmWorkspaceConfig):
            return v
        if isinstance(v, dict):
            return LcmWorkspaceConfig.model_validate(v)
        msg = f"invalid lcm section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("secrets_backend", mode="before")
    @classmethod
    def _wrap_secrets_backend(cls, v: object) -> object:
        """Coerce string legacy ``secrets_backend`` values before validation.

        Args:
            cls (type): Model class.
            v (object): Raw field value.

        Returns:
            object: Coerced structure for ``SecretsBackendSectionConfig``.

        Examples:
            >>> WorkspaceConfig._wrap_secrets_backend(None) is None
            True
        """
        return _coerce_secrets_backend_model(v)

    @field_validator("workspace", mode="before")
    @classmethod
    def _coerce_workspace_section(cls, v: object) -> object:
        """Parse optional ``workspace`` subtree for artifact output settings.

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_workspace_section(None) is None
            True
        """
        if v is None or isinstance(v, WorkspaceOutputSectionConfig):
            return v
        if isinstance(v, dict):
            return WorkspaceOutputSectionConfig.model_validate(v)
        msg = f"invalid workspace section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("onboarding", mode="before")
    @classmethod
    def _coerce_onboarding_section(cls, v: object) -> object:
        """Parse optional ``onboarding`` subtree (`specs/22-onboarding.md` §3.2).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_onboarding_section(None) is None
            True
        """

        if v is None or isinstance(v, OnboardingWorkspaceSectionConfig):
            return v
        if isinstance(v, dict):
            return OnboardingWorkspaceSectionConfig.model_validate(v)
        msg = f"invalid onboarding section type: {type(v).__name__}"
        raise ValueError(msg)

    @field_validator("telemetry", mode="before")
    @classmethod
    def _coerce_telemetry_section(cls, v: object) -> object:
        """Parse optional ``telemetry`` subtree (`specs/22-onboarding.md` §3.2).

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: ``None``, existing model, or coerced mapping.

        Examples:
            >>> WorkspaceConfig._coerce_telemetry_section(None) is None
            True
        """

        if v is None or isinstance(v, TelemetryWorkspaceSectionConfig):
            return v
        if isinstance(v, dict):
            return TelemetryWorkspaceSectionConfig.model_validate(v)
        msg = f"invalid telemetry section type: {type(v).__name__}"
        raise ValueError(msg)
