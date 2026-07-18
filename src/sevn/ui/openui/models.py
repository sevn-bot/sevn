"""OpenUI config and result models (`specs/29-openui.md` §3.1, §2.1).

Module: sevn.ui.openui.models
Depends: pydantic

Exports:
    Drop — sanitiser removal record.
    SanitiseResult — post-sanitise HTML + drops + stats.
    OpenUIConfig — effective numeric/open knobs for the bridge.
    OpenUIRuntimeDeps — per-render infrastructure snapshot.
    RasteriseCaps — channel raster limits.
    OpenUIRenderError — structured failure for tool results.
    OpenUIRenderResult — bridge / tool output envelope.
    effective_openui_config — merge ``WorkspaceConfig.openui`` into :class:`OpenUIConfig`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from sevn.config.workspace_config import OpenUIWorkspaceConfig

CapStatus = Literal["ok", "soft_warn", "hard_reject"]
OpenUIScope = Literal["render", "submit"]
RasteriserName = Literal["weasyprint"]
OutputMode = Literal["live", "screenshot", "pdf"]


class Drop(BaseModel):
    """One sanitiser removal (`specs/29-openui.md` §3.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tag: str = ""
    attr: str = ""
    reason: str


class SanitiseResult(BaseModel):
    """Sanitised HTML bundle (`specs/29-openui.md` §3.1)."""

    model_config = ConfigDict(extra="forbid")

    html: str
    dropped: list[Drop] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class OpenUIConfig(BaseModel):
    """Effective OpenUI limits resolved for the bridge (`specs/29-openui.md` §5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_ttl_seconds: int
    callback_timeout_seconds: int
    soft_cap_bytes: int
    hard_cap_bytes: int
    allowed_asset_origins: tuple[str, ...]
    rasteriser: RasteriserName


class OpenUIRuntimeDeps(BaseModel):
    """Per-render gateway snapshot (public URL, tunnel health)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    public_base_url: str = ""
    tunnel_healthy: bool = True


class RasteriseCaps(BaseModel):
    """Adapter-reported raster limits (`specs/29-openui.md` §3.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    png_max_bytes: int = 10 * 1024 * 1024
    pdf_max_bytes: int = 50 * 1024 * 1024
    image_max_dimension_px: int = 10_000


class OpenUIRenderError(BaseModel):
    """Structured bridge failure (`specs/29-openui.md` §6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    detail: str = ""
    limits: dict[str, int] = Field(default_factory=dict)


class OpenUIRenderResult(BaseModel):
    """Tool / bridge return shape (`specs/29-openui.md` §2.1)."""

    model_config = ConfigDict(extra="forbid")

    token: str = ""
    submit_token: str = ""
    live_url: str | None = None
    image_path: str | None = None
    pdf_path: str | None = None
    cap_status: CapStatus = "ok"
    error: OpenUIRenderError | None = None
    fallback_text: str = ""
    health_alert: str | None = None


def effective_openui_config(ws: OpenUIWorkspaceConfig | None) -> OpenUIConfig:
    """Merge workspace overrides into a frozen :class:`OpenUIConfig`.

    Args:
        ws (OpenUIWorkspaceConfig | None): Parsed workspace ``openui`` subtree or ``None``.

    Returns:
        OpenUIConfig: Normalised limits for the bridge.

    Examples:
        >>> c = effective_openui_config(None)
        >>> c.rasteriser
        'weasyprint'
    """

    from sevn.config.workspace_config import OpenUIWorkspaceConfig

    base = ws if ws is not None else OpenUIWorkspaceConfig()
    return OpenUIConfig(
        token_ttl_seconds=int(base.token_ttl_seconds),
        callback_timeout_seconds=int(base.callback_timeout_seconds),
        soft_cap_bytes=int(base.soft_cap_bytes),
        hard_cap_bytes=int(base.hard_cap_bytes),
        allowed_asset_origins=tuple(
            str(x).strip().rstrip("/") for x in base.allowed_asset_origins if str(x).strip()
        ),
        rasteriser=base.rasteriser,
    )


__all__ = [
    "CapStatus",
    "Drop",
    "OpenUIConfig",
    "OpenUIRenderError",
    "OpenUIRenderResult",
    "OpenUIRuntimeDeps",
    "OpenUIScope",
    "OutputMode",
    "RasteriseCaps",
    "RasteriserName",
    "SanitiseResult",
    "effective_openui_config",
]
