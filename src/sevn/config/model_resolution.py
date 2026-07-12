"""Resolve model ids per logical slot from workspace config.

Module: sevn.config.model_resolution
Depends: sevn.agent.triager.errors, sevn.config.defaults, sevn.config.workspace_config

Exports:
    ModelSlot — canonical slot identifiers.
    use_main_model_for_all — read unified-model flag (default true).
    resolve_main_model_id — ``providers.tier_default.triager``.
    resolve_model_slot — slot-specific id with unified / override rules.
    resolve_transport_for_model_id — transport label from ``providers.models`` / ``minimax/`` default.
    is_minimax_catalog_model — True when catalog id uses ``minimax/`` prefix.
    is_minimax_model — True for MiniMax by catalog id or bare vendor wire name.
    resolve_wire_model_id — upstream vendor model name (strips ``minimax/``).
    resolve_minimax_anthropic_base_url — MiniMax Anthropic-compatible proxy base URL.
    resolve_minimax_openai_base_url — MiniMax OpenAI-compatible base URL for chat-completions.
    workspace_has_minimax_catalog_model — True when any slot uses ``minimax/``.
    fill_missing_model_slots_from_triager — seed unset slots when unified is off.
    model_slot_for_config_dot_path — map ``sevn config set`` dot path to :class:`ModelSlot`.
    maybe_split_unified_model_on_config_set — flip unified off and seed other slots on per-slot edit.
    list_catalog_model_ids — sorted unique ids from ``providers.models`` and tiers.
    model_picker_slot_keys — callback slot keys for Telegram model pickers.
    model_picker_slots_for_key — map picker key to :class:`ModelSlot` tuple.
    apply_model_to_picker_slot — write one catalog id into ``sevn.json`` slot(s).
    native_model_enabled — read ``providers.native_model.<slot>`` (default false).
    user_model_extraction_enabled — read ``memory.user_model.enabled`` (default false).
    codemode_enabled — read ``agent.codemode.enabled`` (default false, W8 sole owner).
    codemode_resource_limits — resolve Monty sandbox ``ResourceLimits`` from ``agent.codemode``.
    codemode_max_retries — read ``agent.codemode.max_retries`` (default 3).
    diagnostics_agent_enabled — read ``agent.diagnostics.enabled`` (default true, W4).
    resolve_diagnostics_model — ``agent.diagnostics.model`` or tier-B default; ``--model`` wins.
    resolve_slot_fallback_model_ids — fallback catalog ids for ``FallbackModel`` (W3.2).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sevn.config.defaults import (
    DEFAULT_CODEMODE_ENABLED,
    DEFAULT_CODEMODE_MAX_ALLOCATIONS,
    DEFAULT_CODEMODE_MAX_DURATION_S,
    DEFAULT_CODEMODE_MAX_MEMORY_BYTES,
    DEFAULT_CODEMODE_MAX_RETRIES,
    DEFAULT_DIAGNOSTICS_AGENT_ENABLED,
    DEFAULT_MINIMAX_ANTHROPIC_BASE_URL,
    DEFAULT_MINIMAX_OPENAI_BASE_URL,
    DEFAULT_MINIMAX_TRANSPORT,
    DEFAULT_NATIVE_MODEL_ENABLED,
    DEFAULT_USE_MAIN_MODEL_FOR_ALL,
)
from sevn.config.errors import TriagerUnavailable

MINIMAX_CATALOG_PREFIX: str = "minimax/"


class ModelSlot(StrEnum):
    """Canonical LLM model slots referenced across gateway subsystems."""

    triager = "triager"
    tier_b = "tier_b"
    tier_c = "tier_c"
    tier_d = "tier_d"
    c_sub_lm = "c_sub_lm"
    d_sub_lm = "d_sub_lm"
    c_lambda_leaf = "c_lambda_leaf"
    d_lambda_leaf = "d_lambda_leaf"
    lcm_summary = "lcm_summary"
    pre_compaction_flush = "pre_compaction_flush"
    dreaming_ranker = "dreaming_ranker"
    user_model_extractor = "user_model_extractor"
    scanner = "scanner"


_NATIVE_MODEL_FLAG_KEYS: dict[ModelSlot, str] = {
    ModelSlot.triager: "triager",
    ModelSlot.tier_b: "tier_b",
}

_FALLBACK_CHAIN_KEYS: dict[ModelSlot, str] = {
    ModelSlot.triager: "triager",
    ModelSlot.tier_b: "B",
}

_TIER_DEFAULT_KEYS: dict[ModelSlot, str] = {
    ModelSlot.triager: "triager",
    ModelSlot.tier_b: "B",
    ModelSlot.tier_c: "C",
    ModelSlot.tier_d: "D",
    ModelSlot.c_sub_lm: "C.sub_lm",
    ModelSlot.d_sub_lm: "D.sub_lm",
    ModelSlot.c_lambda_leaf: "C.lambda_leaf",
    ModelSlot.d_lambda_leaf: "D.lambda_leaf",
}


def _agent_dict(cfg: object) -> dict[str, Any]:
    """Return the workspace ``agent`` mapping when present.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        dict[str, Any]: Agent mapping, or empty dict.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _agent_dict(WorkspaceConfig.minimal(agent={"codemode": {"enabled": True}}))
        {'codemode': {'enabled': True, 'max_retries': 3}}
    """
    raw = getattr(cfg, "agent", None)
    if isinstance(raw, dict):
        return raw
    if raw is not None and hasattr(raw, "model_dump"):
        dumped = raw.model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    extra = getattr(cfg, "model_extra", None)
    if isinstance(extra, dict):
        agent = extra.get("agent")
        if isinstance(agent, dict):
            return agent
    return {}


def _providers_dict(cfg: object) -> dict[str, Any]:
    """Return the workspace ``providers`` mapping when present.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        dict[str, Any]: Providers mapping, or empty dict.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _providers_dict(WorkspaceConfig.minimal(providers={"a": 1}))
        {'a': 1}
    """
    from sevn.config.sections.providers import providers_section_dict

    raw = getattr(cfg, "providers", None)
    return providers_section_dict(raw)


def use_main_model_for_all(cfg: object) -> bool:
    """Return whether all slots inherit the main triager model (default true).

    Args:
        cfg (object): Parsed workspace settings (``WorkspaceConfig`` recommended).

    Returns:
        bool: False only when ``providers.use_main_model_for_all`` is explicitly false.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> use_main_model_for_all(WorkspaceConfig.minimal())
        True
    """
    providers = _providers_dict(cfg)
    flag = providers.get("use_main_model_for_all")
    if flag is False:
        return False
    return DEFAULT_USE_MAIN_MODEL_FOR_ALL


def _tier_default_string(providers: dict[str, Any], key: str) -> str | None:
    """Read a string tier entry from ``providers.tier_default``.

    Args:
        providers (dict[str, Any]): Workspace ``providers`` block.
        key (str): Tier key (e.g. ``triager``, ``B``).

    Returns:
        str | None: Model id string, or ``None`` when missing.

    Examples:
        >>> _tier_default_string({"tier_default": {"triager": "m"}}, "triager")
        'm'
    """
    tier_default = providers.get("tier_default")
    if not isinstance(tier_default, dict):
        return None
    raw = tier_default.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        primary = raw.get("primary")
        if isinstance(primary, str) and primary.strip():
            return primary.strip()
    return None


def resolve_main_model_id(cfg: object) -> str:
    """Return ``providers.tier_default.triager`` (main model).

    Args:
        cfg (object): Parsed workspace settings (``WorkspaceConfig`` recommended).

    Returns:
        str: Non-empty triager model id.

    Raises:
        TriagerUnavailable: When triager tier is missing or not a plain string.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_main_model_id(
        ...     WorkspaceConfig.minimal(
        ...     providers={"tier_default": {"triager": "minimax/MiniMax-M2.7"}},
        ...     )
        ... )
        'minimax/MiniMax-M2.7'
    """
    providers = _providers_dict(cfg)
    from sevn.config.errors import TriagerUnavailable

    mid = _tier_default_string(providers, "triager")
    if mid is None:
        tier_default = providers.get("tier_default")
        if isinstance(tier_default, dict) and isinstance(tier_default.get("triager"), dict):
            msg = "triager tier_default must be a string model id, not an object (`specs/13` §2.6)"
            raise TriagerUnavailable(msg)
        msg = 'workspace.providers.tier_default["triager"] is missing or empty'
        raise TriagerUnavailable(msg)
    return mid


def _slot_override(cfg: object, slot: ModelSlot) -> str | None:
    """Read per-slot override when unified mode is off.

    Args:
        cfg (object): Parsed workspace settings.
        slot (ModelSlot): Target slot.

    Returns:
        str | None: Override model id, or ``None`` when unset.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     SecurityScannerSubConfig,
        ...     SecurityWorkspaceConfig,
        ...     WorkspaceConfig,
        ... )
        >>> cfg = WorkspaceConfig.minimal(
        ...     security=SecurityWorkspaceConfig(
        ...         scanner=SecurityScannerSubConfig(model="openai/gpt-4o-mini"),
        ...     ),
        ... )
        >>> _slot_override(cfg, ModelSlot.scanner)
        'openai/gpt-4o-mini'
    """
    if slot in _TIER_DEFAULT_KEYS:
        return _tier_default_string(_providers_dict(cfg), _TIER_DEFAULT_KEYS[slot])
    if slot == ModelSlot.lcm_summary:
        lcm = getattr(cfg, "lcm", None)
        if lcm is not None:
            raw = getattr(lcm, "summary_model", None)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None
    if slot == ModelSlot.pre_compaction_flush:
        memory = getattr(cfg, "memory", None)
        if memory is not None and memory.pre_compaction_flush is not None:
            model = memory.pre_compaction_flush.model
            if isinstance(model, str) and model.strip():
                return model.strip()
        return None
    if slot == ModelSlot.dreaming_ranker:
        memory = getattr(cfg, "memory", None)
        if memory is not None and memory.dreaming is not None:
            scoring = memory.dreaming.scoring
            if scoring is not None and scoring.llm_ranker is not None:
                model = scoring.llm_ranker.model
                if isinstance(model, str) and model.strip():
                    return model.strip()
        return None
    if slot == ModelSlot.user_model_extractor:
        memory = getattr(cfg, "memory", None)
        if memory is not None and memory.user_model is not None:
            model = memory.user_model.extractor_model
            if isinstance(model, str) and model.strip():
                return model.strip()
        return None
    if slot == ModelSlot.scanner:
        security = getattr(cfg, "security", None)
        if security is not None and security.scanner is not None:
            model = security.scanner.model
            if isinstance(model, str) and model.strip():
                return model.strip()
        return None
    return None


def resolve_model_slot(cfg: object, slot: ModelSlot) -> str:
    """Resolve the model id for a logical slot.

    When ``use_main_model_for_all`` is true (default), every slot returns the
    main triager model. When false, use each slot's saved value only; missing
    keys fall back to triager (after promote, ``fill_missing_model_slots_from_triager``
    seeds unset slots from triager without overwriting explicit values).

    Args:
        cfg (object): Parsed workspace settings (``WorkspaceConfig`` recommended).
        slot (ModelSlot): Target slot.

    Returns:
        str: Resolved model id.

    Raises:
        TriagerUnavailable: When the main triager model cannot be resolved.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={
        ...         "use_main_model_for_all": True,
        ...         "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        ...     },
        ... )
        >>> resolve_model_slot(cfg, ModelSlot.scanner)
        'minimax/MiniMax-M2.7'
    """
    if use_main_model_for_all(cfg):
        return resolve_main_model_id(cfg)
    override = _slot_override(cfg, slot)
    if override is not None:
        return override
    return resolve_main_model_id(cfg)


def is_minimax_catalog_model(model_id: str) -> bool:
    """Return True when ``model_id`` uses the ``minimax/`` catalog prefix.

    Args:
        model_id (str): Workspace catalog model id.

    Returns:
        bool: Whether the id is routed via MiniMax Anthropic-compatible API.

    Examples:
        >>> is_minimax_catalog_model("minimax/MiniMax-M2.7")
        True
        >>> is_minimax_catalog_model("MiniMax-M2.7")
        False
    """
    mid = model_id.strip()
    return bool(mid) and mid.lower().startswith(MINIMAX_CATALOG_PREFIX)


def is_minimax_model(model_id: str) -> bool:
    """Return True for MiniMax models by catalog id **or** bare vendor wire name.

    The catalog id is ``minimax/MiniMax-M3``; once :func:`resolve_wire_model_id` /
    :func:`adapt_request_for_transport` strip the prefix the wire name is the bare
    ``MiniMax-M3``. Proxy provider/credential resolution must recognize **both** so a stripped
    name still routes to MiniMax instead of defaulting to OpenAI (transcript-review-2026-06-22).

    Args:
        model_id (str): Catalog id or bare vendor model name.

    Returns:
        bool: Whether the model should route to MiniMax.

    Examples:
        >>> is_minimax_model("minimax/MiniMax-M3")
        True
        >>> is_minimax_model("MiniMax-M3")
        True
        >>> is_minimax_model("openai/gpt-4o")
        False
    """
    return is_minimax_catalog_model(model_id) or model_id.strip().lower().startswith("minimax-")


def resolve_wire_model_id(model_id: str) -> str:
    """Return the upstream vendor model name for proxy egress.

    Catalog ids keep the ``provider/`` prefix in ``sevn.json``; MiniMax expects
    bare names such as ``MiniMax-M2.7`` on the wire.

    Args:
        model_id (str): Workspace catalog model id.

    Returns:
        str: Vendor model string sent in the request body.

    Examples:
        >>> resolve_wire_model_id("minimax/MiniMax-M2.7")
        'MiniMax-M2.7'
        >>> resolve_wire_model_id("openai/gpt-4o-mini")
        'openai/gpt-4o-mini'
    """
    mid = model_id.strip()
    if is_minimax_catalog_model(mid):
        return mid.split("/", 1)[1]
    return mid


def resolve_minimax_anthropic_base_url(configured: str | None) -> str:
    """Pick MiniMax Anthropic-compatible base URL for proxy upstream calls.

    Legacy workspaces may still store the OpenAI-compat ``…/v1`` URL; those are
    ignored in favour of the Anthropic default (legacy workspace default).

    Args:
        configured (str | None): ``providers.minimax.base_url`` when set.

    Returns:
        str: Anthropic-compatible base URL ending before ``/messages``.

    Examples:
        >>> resolve_minimax_anthropic_base_url(None) == DEFAULT_MINIMAX_ANTHROPIC_BASE_URL
        True
        >>> resolve_minimax_anthropic_base_url("https://api.minimax.io/anthropic/v1")
        'https://api.minimax.io/anthropic/v1'
        >>> resolve_minimax_anthropic_base_url("https://api.minimax.io/v1")
        'https://api.minimax.io/anthropic/v1'
    """
    if configured is None or not configured.strip():
        return str(DEFAULT_MINIMAX_ANTHROPIC_BASE_URL)
    url = configured.strip().rstrip("/")
    if "/anthropic" in url:
        return url
    return str(DEFAULT_MINIMAX_ANTHROPIC_BASE_URL)


def resolve_minimax_openai_base_url(configured: str | None) -> str:
    """Pick MiniMax OpenAI-compatible base URL for chat-completions transport.

    When ``providers.minimax.openai_base_url`` is set explicitly, use it;
    otherwise fall back to :data:`DEFAULT_MINIMAX_OPENAI_BASE_URL`.

    Args:
        configured (str | None): ``providers.minimax.openai_base_url`` when set.

    Returns:
        str: OpenAI-compatible base URL (``https://api.minimax.io/v1`` by default).

    Examples:
        >>> resolve_minimax_openai_base_url(None) == DEFAULT_MINIMAX_OPENAI_BASE_URL
        True
        >>> resolve_minimax_openai_base_url("https://custom.minimax.io/v1")
        'https://custom.minimax.io/v1'
        >>> resolve_minimax_openai_base_url("  ")
        'https://api.minimax.io/v1'
    """
    if configured is None or not configured.strip():
        return str(DEFAULT_MINIMAX_OPENAI_BASE_URL)
    return configured.strip().rstrip("/")


def _iter_model_id_strings(value: object) -> list[str]:
    """Collect model id strings from nested provider config values.

    Args:
        value (object): A model id string or nested mapping such as
            ``{"primary": "openai/gpt-4o", "vision": "openai/gpt-4o"}``.

    Returns:
        list[str]: Non-empty trimmed model id strings extracted from ``value``.

    Examples:
        >>> _iter_model_id_strings("minimax/X")
        ['minimax/X']
        >>> _iter_model_id_strings({"primary": "a", "vision": "b"})
        ['a', 'b']
        >>> _iter_model_id_strings(None)
        []
    """
    out: list[str] = []
    if isinstance(value, str) and value.strip():
        out.append(value.strip())
    elif isinstance(value, dict):
        for key in ("primary", "vision", "model"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                out.append(raw.strip())
    return out


def workspace_has_minimax_catalog_model(cfg: object) -> bool:
    """Return True when any configured model id uses the ``minimax/`` prefix.

    Scans ``providers.tier_default``, ``providers.models`` keys, LCM, memory,
    and ``security.scanner.model`` so non-triager slots still enable MiniMax
    proxy credentials.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        bool: Whether MiniMax Anthropic egress rules apply at proxy boot.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> workspace_has_minimax_catalog_model(
        ...     WorkspaceConfig.minimal(
        ...     providers={"tier_default": {"B": "minimax/MiniMax-M2.7"}},
        ...     )
        ... )
        True
    """
    providers = _providers_dict(cfg)
    tier_default = providers.get("tier_default")
    if isinstance(tier_default, dict):
        for val in tier_default.values():
            for mid in _iter_model_id_strings(val):
                if is_minimax_catalog_model(mid):
                    return True
    models = providers.get("models")
    if isinstance(models, dict):
        for key in models:
            if is_minimax_catalog_model(str(key)):
                return True
    sec = getattr(cfg, "security", None)
    scanner = getattr(sec, "scanner", None) if sec is not None else None
    scan_model = getattr(scanner, "model", None) if scanner is not None else None
    if isinstance(scan_model, str) and is_minimax_catalog_model(scan_model):
        return True
    lcm = getattr(cfg, "lcm", None)
    for attr in ("summary_model", "pre_compaction_flush_model"):
        raw = getattr(lcm, attr, None) if lcm is not None else None
        if isinstance(raw, str) and is_minimax_catalog_model(raw):
            return True
    mem = getattr(cfg, "memory", None)
    for attr in ("dreaming_ranker_model", "user_model_extractor_model"):
        raw = getattr(mem, attr, None) if mem is not None else None
        if isinstance(raw, str) and is_minimax_catalog_model(raw):
            return True
    return False


def codemode_enabled(cfg: object, *, model_id: str | None = None) -> bool:
    """Return whether tier-B CodeMode is enabled (W8.1, W4 MiniMax default).

    Reads ``agent.codemode.enabled``; defaults to :data:`DEFAULT_CODEMODE_ENABLED`
    (``False``) so flag-off behaviour matches today's flat tool path.

    When *model_id* is a ``minimax/*`` catalog model and the operator has not
    explicitly set ``agent.codemode.enabled``, defaults to ``True`` (D5: MiniMax
    benefits from CodeMode's single ``run_code`` surface).

    Args:
        cfg (object): Parsed workspace settings.
        model_id (str | None): Optional resolved tier-B model id. When a MiniMax
            model, flips the implicit default to ``True``.

    Returns:
        bool: Whether CodeMode should be active for this turn.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> codemode_enabled(WorkspaceConfig.minimal())
        False
        >>> codemode_enabled(WorkspaceConfig.minimal(), model_id="minimax/m3")
        True
        >>> codemode_enabled(
        ...     WorkspaceConfig.minimal(
        ...     agent={"codemode": {"enabled": True}},
        ...     ),
        ... )
        True
        >>> codemode_enabled(
        ...     WorkspaceConfig.minimal(
        ...     agent={"codemode": {"enabled": False}},
        ...     ),
        ...     model_id="minimax/m3",
        ... )
        False
    """
    agent = _agent_dict(cfg)
    codemode = agent.get("codemode")
    if not isinstance(codemode, dict):
        if model_id is not None and is_minimax_catalog_model(model_id):
            return True
        return DEFAULT_CODEMODE_ENABLED
    raw = codemode.get("enabled")
    if raw is True:
        return True
    if raw is False:
        return False
    if model_id is not None and is_minimax_catalog_model(model_id):
        return True
    return DEFAULT_CODEMODE_ENABLED


def _positive_number(value: object, fallback: float) -> float:
    """Coerce a config value to a positive number, else *fallback*.

    Args:
        value (object): Raw ``agent.codemode.*`` config value.
        fallback (float): Default when *value* is missing or not a positive number.

    Returns:
        float: *value* when a positive int/float (not bool); otherwise *fallback*.

    Examples:
        >>> _positive_number(30, 45.0)
        30.0
        >>> _positive_number(0, 45.0)
        45.0
        >>> _positive_number(None, 45.0)
        45.0
        >>> _positive_number(True, 45.0)
        45.0
    """
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return fallback


def _positive_int(value: object, fallback: int) -> int:
    """Coerce a config value to a positive integer, else *fallback*.

    Args:
        value (object): Raw ``agent.codemode.*`` config value.
        fallback (int): Default when *value* is missing or not a positive int.

    Returns:
        int: *value* when a positive int (not bool); otherwise *fallback*.

    Examples:
        >>> _positive_int(5, 3)
        5
        >>> _positive_int(0, 3)
        3
        >>> _positive_int(None, 3)
        3
        >>> _positive_int(True, 3)
        3
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    if value < 1:
        return fallback
    return value


def codemode_resource_limits(cfg: object) -> dict[str, float | int]:
    """Resolve CodeMode (Monty) sandbox ``ResourceLimits`` from ``agent.codemode``.

    Reads ``agent.codemode.{max_duration_secs,max_memory_bytes,max_allocations}`` and falls
    back to the ``DEFAULT_CODEMODE_*`` constants. Returned as a plain mapping (compatible with
    ``pydantic_monty.ResourceLimits``) so the config layer stays free of the sandbox import.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        dict[str, float | int]: ``{max_duration_secs, max_memory, max_allocations}``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> codemode_resource_limits(WorkspaceConfig.minimal())["max_duration_secs"]
        45.0
        >>> codemode_resource_limits(
        ...     WorkspaceConfig.minimal(agent={"codemode": {"max_duration_secs": 10}}),
        ... )["max_duration_secs"]
        10.0
    """
    agent = _agent_dict(cfg)
    codemode = agent.get("codemode")
    cm = codemode if isinstance(codemode, dict) else {}
    return {
        "max_duration_secs": _positive_number(
            cm.get("max_duration_secs"), DEFAULT_CODEMODE_MAX_DURATION_S
        ),
        "max_memory": int(
            _positive_number(cm.get("max_memory_bytes"), DEFAULT_CODEMODE_MAX_MEMORY_BYTES)
        ),
        "max_allocations": int(
            _positive_number(cm.get("max_allocations"), DEFAULT_CODEMODE_MAX_ALLOCATIONS)
        ),
    }


def codemode_max_retries(cfg: object) -> int:
    """Resolve CodeMode ``run_code`` retry budget from ``agent.codemode.max_retries``.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        int: Positive retry count; defaults to :data:`DEFAULT_CODEMODE_MAX_RETRIES`.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> codemode_max_retries(WorkspaceConfig.minimal())
        3
        >>> codemode_max_retries(
        ...     WorkspaceConfig.minimal(agent={"codemode": {"max_retries": 5}}),
        ... )
        5
    """
    agent = _agent_dict(cfg)
    codemode = agent.get("codemode")
    cm = codemode if isinstance(codemode, dict) else {}
    return _positive_int(cm.get("max_retries"), DEFAULT_CODEMODE_MAX_RETRIES)


def diagnostics_agent_enabled(cfg: object) -> bool:
    """Return whether ``sevn doctor --with-agent`` may invoke the diagnostic agent (W4).

    Reads ``agent.diagnostics.enabled``; defaults to :data:`DEFAULT_DIAGNOSTICS_AGENT_ENABLED`.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        bool: ``False`` only when ``agent.diagnostics.enabled`` is explicitly false.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> diagnostics_agent_enabled(WorkspaceConfig.minimal())
        True
        >>> diagnostics_agent_enabled(
        ...     WorkspaceConfig.minimal(agent={"diagnostics": {"enabled": False}}),
        ... )
        False
    """
    agent = _agent_dict(cfg)
    diagnostics = agent.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return DEFAULT_DIAGNOSTICS_AGENT_ENABLED
    raw = diagnostics.get("enabled")
    if raw is True:
        return True
    if raw is False:
        return False
    return DEFAULT_DIAGNOSTICS_AGENT_ENABLED


def resolve_diagnostics_model(cfg: object, *, override: str | None = None) -> str:
    """Resolve the model id for ``agent.diagnostics`` / ``sevn doctor --with-agent``.

    Precedence: explicit ``override`` (CLI ``--model``) → ``agent.diagnostics.model`` →
    :func:`resolve_model_slot` for :attr:`ModelSlot.tier_b`.

    Args:
        cfg (object): Parsed workspace settings.
        override (str | None): CLI ``--model`` override when set.

    Returns:
        str: Resolved catalog model id.

    Raises:
        TriagerUnavailable: When no model can be resolved.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_diagnostics_model(
        ...     WorkspaceConfig.minimal(
        ...         providers={
        ...             "tier_default": {"triager": "openai/gpt-4o-mini"},
        ...         },
        ...     ),
        ... )
        'openai/gpt-4o-mini'
        >>> resolve_diagnostics_model(
        ...     WorkspaceConfig.minimal(
        ...         agent={"diagnostics": {"model": "anthropic/claude-sonnet"}},
        ...         providers={"tier_default": {"triager": "openai/gpt-4o-mini"}},
        ...     ),
        ... )
        'anthropic/claude-sonnet'
        >>> resolve_diagnostics_model(
        ...     WorkspaceConfig.minimal(),
        ...     override="openai/gpt-4o",
        ... )
        'openai/gpt-4o'
    """
    if isinstance(override, str) and override.strip():
        return override.strip()
    agent = _agent_dict(cfg)
    diagnostics = agent.get("diagnostics")
    if isinstance(diagnostics, dict):
        model = diagnostics.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return resolve_model_slot(cfg, ModelSlot.tier_b)


def native_model_enabled(cfg: object, slot: ModelSlot) -> bool:
    """Return whether the slot uses the native pydantic-ai model factory (W3.4).

    Reads ``providers.native_model.<slot>``; defaults to :data:`DEFAULT_NATIVE_MODEL_ENABLED`
    (``False``) so flag-off behaviour matches today's ``FunctionModel`` path.

    Args:
        cfg (object): Parsed workspace settings.
        slot (ModelSlot): Target slot (only ``triager`` and ``tier_b`` are wired).

    Returns:
        bool: ``True`` only when the per-slot flag is explicitly enabled.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> native_model_enabled(WorkspaceConfig.minimal(), ModelSlot.tier_b)
        False
        >>> native_model_enabled(
        ...     WorkspaceConfig.minimal(
        ...     providers={"native_model": {"tier_b": True}},
        ...     ),
        ...     ModelSlot.tier_b,
        ... )
        True
    """
    flag_key = _NATIVE_MODEL_FLAG_KEYS.get(slot)
    if flag_key is None:
        return False
    providers = _providers_dict(cfg)
    native = providers.get("native_model")
    if not isinstance(native, dict):
        return DEFAULT_NATIVE_MODEL_ENABLED
    raw = native.get(flag_key)
    if raw is True:
        return True
    if raw is False:
        return False
    return DEFAULT_NATIVE_MODEL_ENABLED


def user_model_extraction_enabled(cfg: object) -> bool:
    """Return whether post-turn user-model extraction is enabled (`specs/32-memory-honcho.md` §3.2).

    Absent ``memory.user_model`` is treated as disabled (spec default ``false``), even when
    :data:`DEFAULT_USER_MODEL_ENABLED` drifts in ``defaults.py``.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        bool: ``True`` only when ``memory.user_model.enabled`` is explicitly true.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> user_model_extraction_enabled(WorkspaceConfig.minimal())
        False
        >>> from sevn.config.sections.memory import MemoryWorkspaceSectionConfig, UserModelWorkspaceConfig
        >>> user_model_extraction_enabled(
        ...     WorkspaceConfig.minimal(
        ...         memory=MemoryWorkspaceSectionConfig(
        ...             user_model=UserModelWorkspaceConfig(enabled=True),
        ...         ),
        ...     ),
        ... )
        True
    """
    memory = getattr(cfg, "memory", None)
    if memory is None:
        return False
    user_model = getattr(memory, "user_model", None)
    if user_model is None:
        return False
    return bool(user_model.enabled)


def resolve_slot_fallback_model_ids(
    cfg: object,
    slot: ModelSlot,
    *,
    primary: str,
) -> tuple[str, ...]:
    """Return ordered fallback catalog ids for ``FallbackModel`` after *primary* (W3.2).

    Reads ``providers.fallback_chain[<slot_key>]`` and drops duplicates of *primary*.

    Args:
        cfg (object): Parsed workspace settings.
        slot (ModelSlot): Target slot (``triager`` or ``tier_b``).
        primary (str): Resolved primary catalog id for the slot.

    Returns:
        tuple[str, ...]: Non-empty fallback ids, or ``()`` when unset.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_slot_fallback_model_ids(
        ...     WorkspaceConfig.minimal(
        ...     providers={
        ...             "fallback_chain": {
        ...                 "B": ["anthropic/claude-haiku-4-5", "openai/gpt-5-mini"],
        ...             },
        ...         },
        ...     ),
        ...     ModelSlot.tier_b,
        ...     primary="anthropic/claude-haiku-4-5",
        ... )
        ('openai/gpt-5-mini',)
    """
    chain_key = _FALLBACK_CHAIN_KEYS.get(slot)
    if chain_key is None:
        return ()
    providers = _providers_dict(cfg)
    chains = providers.get("fallback_chain")
    if not isinstance(chains, dict):
        return ()
    raw_chain = chains.get(chain_key)
    if not isinstance(raw_chain, list):
        return ()
    primary_norm = primary.strip()
    seen: set[str] = {primary_norm} if primary_norm else set()
    out: list[str] = []
    for item in raw_chain:
        if not isinstance(item, str):
            continue
        mid = item.strip()
        if not mid or mid in seen:
            continue
        out.append(mid)
        seen.add(mid)
    return tuple(out)


def resolve_transport_for_model_id(providers_obj: dict[str, Any], model_id: str) -> str:
    """Infer transport label from merged ``providers.models[model_id]`` or default.

    Resolution order for ``minimax/*`` catalog ids:

    1. Per-model override in ``providers.models[model_id].transport``.
    2. Provider-level ``providers.minimax.transport``.
    3. Hardcoded default (``DEFAULT_MINIMAX_TRANSPORT`` = ``chat_completions``).

    Args:
        providers_obj (dict[str, Any]): Merged ``providers`` block from workspace.
        model_id (str): Model id to look up in ``providers_obj['models']``.

    Returns:
        str: Lowercased transport name; ``minimax/`` catalog ids default to
        ``chat_completions`` (MiniMax OpenAI-compatible API) so a new install needs no
        manual ``providers.minimax.transport`` entry. Set it explicitly to ``anthropic``
        to use the MiniMax Anthropic-compatible wire instead.

    Examples:
        >>> resolve_transport_for_model_id({}, "x")
        'chat_completions'
        >>> resolve_transport_for_model_id({}, "minimax/MiniMax-M2.7")
        'chat_completions'
        >>> resolve_transport_for_model_id(
        ...     {"minimax": {"transport": "anthropic"}}, "minimax/MiniMax-M3"
        ... )
        'anthropic'
        >>> resolve_transport_for_model_id(
        ...     {"models": {"x": {"transport": "Responses"}}}, "x"
        ... )
        'responses'
        >>> resolve_transport_for_model_id(
        ...     {"minimax": {"transport": "chat_completions"}}, "minimax/MiniMax-M3"
        ... )
        'chat_completions'
    """
    models = providers_obj.get("models")
    if isinstance(models, dict):
        raw = models.get(model_id)
        if isinstance(raw, dict):
            t = raw.get("transport")
            if isinstance(t, str) and t.strip():
                return t.strip().lower()
    if is_minimax_catalog_model(model_id):
        minimax_section = providers_obj.get("minimax")
        if isinstance(minimax_section, dict):
            t = minimax_section.get("transport")
            if isinstance(t, str) and t.strip():
                return t.strip().lower()
        return str(DEFAULT_MINIMAX_TRANSPORT)
    return "chat_completions"


def _main_model_from_doc(doc: dict[str, Any]) -> str | None:
    """Read triager model id from a raw ``sevn.json`` document.

    Args:
        doc (dict[str, Any]): Workspace document.

    Returns:
        str | None: Triager model id when present.

    Examples:
        >>> _main_model_from_doc({"providers": {"tier_default": {"triager": "m"}}})
        'm'
    """
    providers = doc.get("providers")
    if not isinstance(providers, dict):
        return None
    return _tier_default_string(providers, "triager")


def _slot_value_from_doc(doc: dict[str, Any], slot: ModelSlot) -> str | None:
    """Read a per-slot model id from a raw ``sevn.json`` document.

    Args:
        doc (dict[str, Any]): Workspace document.
        slot (ModelSlot): Target slot.

    Returns:
        str | None: Model id when configured.

    Examples:
        >>> _slot_value_from_doc(
        ...     {"providers": {"tier_default": {"B": "tier-b"}}},
        ...     ModelSlot.tier_b,
        ... )
        'tier-b'
    """
    providers = doc.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    if slot in _TIER_DEFAULT_KEYS:
        return _tier_default_string(providers, _TIER_DEFAULT_KEYS[slot])
    if slot == ModelSlot.lcm_summary:
        lcm = doc.get("lcm")
        if isinstance(lcm, dict):
            raw = lcm.get("summary_model")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None
    if slot == ModelSlot.pre_compaction_flush:
        memory = doc.get("memory")
        if isinstance(memory, dict):
            flush = memory.get("pre_compaction_flush")
            if isinstance(flush, dict):
                raw = flush.get("model")
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
        return None
    if slot == ModelSlot.dreaming_ranker:
        memory = doc.get("memory")
        if isinstance(memory, dict):
            dreaming = memory.get("dreaming")
            if isinstance(dreaming, dict):
                scoring = dreaming.get("scoring")
                if isinstance(scoring, dict):
                    ranker = scoring.get("llm_ranker")
                    if isinstance(ranker, dict):
                        raw = ranker.get("model")
                        if isinstance(raw, str) and raw.strip():
                            return raw.strip()
        return None
    if slot == ModelSlot.user_model_extractor:
        memory = doc.get("memory")
        if isinstance(memory, dict):
            user_model = memory.get("user_model")
            if isinstance(user_model, dict):
                raw = user_model.get("extractor_model")
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
        return None
    if slot == ModelSlot.scanner:
        security = doc.get("security")
        if isinstance(security, dict):
            scanner = security.get("scanner")
            if isinstance(scanner, dict):
                raw = scanner.get("model")
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
        return None
    return None


def _set_slot_in_doc(doc: dict[str, Any], slot: ModelSlot, model_id: str) -> None:
    """Write a per-slot model id into a raw ``sevn.json`` document (in place).

    Args:
        doc (dict[str, Any]): Workspace document.
        slot (ModelSlot): Target slot.
        model_id (str): Model id to store.

    Returns:
        None: ``doc`` is updated in place.

    Examples:
        >>> d: dict[str, Any] = {"providers": {"tier_default": {}}}
        >>> _set_slot_in_doc(d, ModelSlot.tier_b, "tier-b")
        >>> d["providers"]["tier_default"]["B"]
        'tier-b'
    """
    if slot in _TIER_DEFAULT_KEYS:
        providers = doc.setdefault("providers", {})
        if not isinstance(providers, dict):
            return
        tier = providers.setdefault("tier_default", {})
        if not isinstance(tier, dict):
            tier = {}
            providers["tier_default"] = tier
        tier[_TIER_DEFAULT_KEYS[slot]] = model_id
        return
    if slot == ModelSlot.lcm_summary:
        lcm = doc.setdefault("lcm", {})
        if isinstance(lcm, dict):
            lcm["summary_model"] = model_id
        return
    if slot == ModelSlot.pre_compaction_flush:
        memory = doc.setdefault("memory", {})
        if not isinstance(memory, dict):
            return
        flush = memory.setdefault("pre_compaction_flush", {})
        if isinstance(flush, dict):
            flush["model"] = model_id
        return
    if slot == ModelSlot.dreaming_ranker:
        memory = doc.setdefault("memory", {})
        if not isinstance(memory, dict):
            return
        dreaming = memory.setdefault("dreaming", {})
        if not isinstance(dreaming, dict):
            return
        scoring = dreaming.setdefault("scoring", {})
        if isinstance(scoring, dict):
            ranker = scoring.setdefault("llm_ranker", {})
            if isinstance(ranker, dict):
                ranker["model"] = model_id
        return
    if slot == ModelSlot.user_model_extractor:
        memory = doc.setdefault("memory", {})
        if not isinstance(memory, dict):
            return
        user_model = memory.setdefault("user_model", {})
        if isinstance(user_model, dict):
            user_model["extractor_model"] = model_id
        return
    if slot == ModelSlot.scanner:
        security = doc.setdefault("security", {})
        if not isinstance(security, dict):
            return
        scanner = security.setdefault("scanner", {})
        if isinstance(scanner, dict):
            scanner["model"] = model_id


_MODEL_PICKER_SLOT_MAP: dict[str, tuple[ModelSlot, ...]] = {
    "triager": (ModelSlot.triager,),
    "tier_b": (ModelSlot.tier_b,),
    "tier_cd": (ModelSlot.tier_c, ModelSlot.tier_d),
}


def model_picker_slot_keys() -> tuple[str, ...]:
    """Return Telegram model-picker callback slot keys.

    Returns:
        tuple[str, ...]: Keys used in ``cfg:models:*`` callbacks.

    Examples:
        >>> "triager" in model_picker_slot_keys()
        True
    """
    return tuple(_MODEL_PICKER_SLOT_MAP.keys())


def model_picker_slots_for_key(slot_key: str) -> tuple[ModelSlot, ...] | None:
    """Map a picker callback key to one or more :class:`ModelSlot` values.

    Args:
        slot_key (str): Picker key (``triager``, ``tier_b``, ``tier_cd``).

    Returns:
        tuple[ModelSlot, ...] | None: Target slots, or ``None`` when unknown.

    Examples:
        >>> model_picker_slots_for_key("tier_cd") == (ModelSlot.tier_c, ModelSlot.tier_d)
        True
        >>> model_picker_slots_for_key("unknown") is None
        True
    """
    slots = _MODEL_PICKER_SLOT_MAP.get(slot_key.strip())
    return slots if slots else None


def list_catalog_model_ids(cfg: object) -> list[str]:
    """Return sorted unique model ids from workspace provider config.

    Collects ``providers.models`` keys, ``providers.tier_default`` entries, and
    currently resolved slot ids so pickers always include active values.

    Args:
        cfg (object): Parsed workspace settings.

    Returns:
        list[str]: Sorted unique non-empty catalog model ids.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ids = list_catalog_model_ids(
        ...     WorkspaceConfig.minimal(
        ...     providers={
        ...             "models": {"openai/gpt-4o-mini": {}},
        ...             "tier_default": {"triager": "openai/gpt-4o-mini"},
        ...         },
        ...     )
        ... )
        >>> ids == ["openai/gpt-4o-mini"]
        True
    """
    ids: set[str] = set()
    providers = _providers_dict(cfg)
    models = providers.get("models")
    if isinstance(models, dict):
        for key in models:
            if isinstance(key, str) and key.strip():
                ids.add(key.strip())
    tier_default = providers.get("tier_default")
    if isinstance(tier_default, dict):
        for val in tier_default.values():
            ids.update(_iter_model_id_strings(val))
    for slot in (ModelSlot.triager, ModelSlot.tier_b, ModelSlot.tier_c, ModelSlot.tier_d):
        try:
            ids.add(resolve_model_slot(cfg, slot))
        except TriagerUnavailable:
            continue
    return sorted(ids)


def apply_model_to_picker_slot(doc: dict[str, Any], slot_key: str, model_id: str) -> None:
    """Write *model_id* into the picker slot(s) for *slot_key*.

    Args:
        doc (dict[str, Any]): Workspace document (mutated in place).
        slot_key (str): Picker key (``triager``, ``tier_b``, ``tier_cd``).
        model_id (str): Catalog model id to persist.

    Returns:
        None: ``doc`` is updated in place.

    Examples:
        >>> d: dict[str, Any] = {"providers": {"tier_default": {}}}
        >>> apply_model_to_picker_slot(d, "tier_b", "openai/gpt-4o-mini")
        >>> d["providers"]["tier_default"]["B"]
        'openai/gpt-4o-mini'
    """
    mid = model_id.strip()
    if not mid:
        return
    slots = model_picker_slots_for_key(slot_key)
    if slots is None:
        return
    for slot in slots:
        _set_slot_in_doc(doc, slot, mid)


def fill_missing_model_slots_from_triager(doc: dict[str, Any]) -> None:
    """Seed unset per-slot model ids from triager when unified mode is off.

    Does not overwrite slots that already have a value so a single-slot edit
    leaves other slots unchanged.

    Args:
        doc (dict[str, Any]): Workspace document (mutated in place).

    Returns:
        None: Missing slots are filled from ``providers.tier_default.triager``.

    Examples:
        >>> d: dict[str, Any] = {
        ...     "providers": {
        ...         "use_main_model_for_all": False,
        ...         "tier_default": {"triager": "main-m", "B": "custom-b"},
        ...     },
        ... }
        >>> fill_missing_model_slots_from_triager(d)
        >>> d["providers"]["tier_default"]["C"]
        'main-m'
        >>> d["providers"]["tier_default"]["B"]
        'custom-b'
    """
    providers = doc.get("providers")
    if not isinstance(providers, dict) or providers.get("use_main_model_for_all") is not False:
        return
    main = _main_model_from_doc(doc)
    if not main:
        return
    for slot in ModelSlot:
        if slot == ModelSlot.triager:
            continue
        if _slot_value_from_doc(doc, slot) is not None:
            continue
        _set_slot_in_doc(doc, slot, main)


_CONFIG_SET_MODEL_SLOT_PATHS: dict[str, ModelSlot] = {
    f"providers.tier_default.{tier_key}": slot for slot, tier_key in _TIER_DEFAULT_KEYS.items()
}
_CONFIG_SET_MODEL_SLOT_PATHS.update(
    {
        "lcm.summary_model": ModelSlot.lcm_summary,
        "memory.pre_compaction_flush.model": ModelSlot.pre_compaction_flush,
        "memory.dreaming.scoring.llm_ranker.model": ModelSlot.dreaming_ranker,
        "memory.user_model.extractor_model": ModelSlot.user_model_extractor,
        "security.scanner.model": ModelSlot.scanner,
    },
)


def model_slot_for_config_dot_path(dotted: str) -> ModelSlot | None:
    """Map a ``sevn config set`` dot path to a :class:`ModelSlot` when applicable.

    Args:
        dotted (str): Dot-separated ``sevn.json`` path (e.g. ``providers.tier_default.B``).

    Returns:
        ModelSlot | None: Target slot, or ``None`` when ``dotted`` is not a model slot path.

    Examples:
        >>> model_slot_for_config_dot_path("providers.tier_default.B") == ModelSlot.tier_b
        True
        >>> model_slot_for_config_dot_path("gateway.port") is None
        True
    """
    return _CONFIG_SET_MODEL_SLOT_PATHS.get(dotted.strip())


def maybe_split_unified_model_on_config_set(
    doc: dict[str, Any],
    dotted: str,
    new_value: Any,
) -> None:
    """Disable unified mode and seed other slots from triager on a diverging per-slot edit.

    When ``providers.use_main_model_for_all`` is true (default), assigning one slot
    to a model id different from ``providers.tier_default.triager`` turns unified mode
    off and copies the triager model into every other unset slot (Mission Control /
    onboarding parity).

    Args:
        doc (dict[str, Any]): Workspace document after ``_set_nested`` (mutated in place).
        dotted (str): Dot path written by ``sevn config set``.
        new_value (Any): Parsed value assigned at ``dotted``.

    Returns:
        None: ``doc`` may set ``use_main_model_for_all`` false and fill missing slots.

    Examples:
        >>> d: dict[str, Any] = {
        ...     "providers": {
        ...         "use_main_model_for_all": True,
        ...         "tier_default": {"triager": "minimax/M3", "B": "openai/gpt-5.5"},
        ...     },
        ... }
        >>> maybe_split_unified_model_on_config_set(
        ...     d,
        ...     "providers.tier_default.B",
        ...     "openai/gpt-5.5",
        ... )
        >>> d["providers"]["use_main_model_for_all"]
        False
        >>> d["providers"]["tier_default"]["C"]
        'minimax/M3'
    """
    slot = model_slot_for_config_dot_path(dotted)
    if slot is None or slot == ModelSlot.triager:
        return
    model_id = str(new_value).strip() if new_value is not None else ""
    if not model_id:
        return
    providers = doc.get("providers")
    if not isinstance(providers, dict) or providers.get("use_main_model_for_all") is False:
        return
    main = _main_model_from_doc(doc)
    if not main or model_id == main:
        return
    providers["use_main_model_for_all"] = False
    fill_missing_model_slots_from_triager(doc)
