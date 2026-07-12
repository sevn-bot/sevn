"""Host-dependency provisioning config subtree for ``sevn.json``.

Module: sevn.config.sections.provisioning
Depends: pydantic, sevn.provisioning.host_deps, sevn.voice.host_deps (validator only, lazy)

Exports:
    ProvisioningWorkspaceConfig — ``provisioning`` subtree (host-dep auto-install allowlist).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProvisioningWorkspaceConfig(BaseModel):
    """``provisioning`` subtree — opt-in host-dependency auto-install.

    ``auto_install`` lists the host dependencies that ``sevn sync`` and gateway (re)start may
    install when missing: the core :data:`sevn.provisioning.host_deps.HOST_DEPS` ids
    (``ripgrep``, ``deno``, ``pango``, ``docker``) plus the voice-only
    :data:`sevn.voice.host_deps.VOICE_HOST_DEPS` ids (``whisper_cpp``, ``ffmpeg`` — local STT
    binary + audio conversion, `build-plan-from-review/waves/
    voice-duplex-tts-menu-log-fixes-wave-plan.md` W2). Empty (the default) means provisioning is
    a no-op — the gateway keeps logging degraded-fallback warnings instead. ``on_gateway_start``
    / ``on_sync`` gate which entry points act on the allowlist.

    On Linux, ``apt-get install`` requires root or passwordless sudo; otherwise provisioning
    records a ``manual`` outcome with install commands instead of running the installer.

    Examples:
        >>> ProvisioningWorkspaceConfig().auto_install
        []
        >>> ProvisioningWorkspaceConfig(auto_install=["ripgrep"]).on_sync
        True
        >>> ProvisioningWorkspaceConfig(auto_install=["whisper_cpp", "ffmpeg"]).auto_install
        ['whisper_cpp', 'ffmpeg']
    """

    model_config = ConfigDict(extra="allow")

    auto_install: list[str] = Field(
        default_factory=list,
        description="Host-dependency ids to auto-install when missing (ripgrep/deno/pango/docker).",
    )
    on_gateway_start: bool = Field(
        default=True,
        description="Run the auto_install allowlist during gateway (re)start.",
    )
    on_sync: bool = Field(
        default=True,
        description="Run the auto_install allowlist during `sevn sync`.",
    )

    @field_validator("auto_install")
    @classmethod
    def _validate_ids(cls, value: list[str]) -> list[str]:
        """Reject unknown host-dependency ids with an actionable error.

        Args:
            cls (type): Model class.
            value (list[str]): Configured ids.

        Returns:
            list[str]: De-duplicated, order-preserving id list.

        Raises:
            ValueError: When any id is not a known host dependency.

        Examples:
            >>> ProvisioningWorkspaceConfig._validate_ids(["deno", "deno"])
            ['deno']
            >>> ProvisioningWorkspaceConfig._validate_ids(["whisper_cpp"])
            ['whisper_cpp']
            >>> import pytest
            >>> with pytest.raises(ValueError):
            ...     ProvisioningWorkspaceConfig._validate_ids(["bogus"])
        """
        from sevn.provisioning.host_deps import host_dep_ids
        from sevn.voice.host_deps import voice_host_dep_ids

        known = set(host_dep_ids()) | set(voice_host_dep_ids())
        bad = [v for v in value if v not in known]
        if bad:
            msg = f"unknown provisioning.auto_install ids {bad!r}; known ids: {sorted(known)!r}"
            raise ValueError(msg)
        return list(dict.fromkeys(value))
