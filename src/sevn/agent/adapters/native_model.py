"""Native pydantic-ai model factory behind per-slot flags (W3).

Module: sevn.agent.adapters.native_model
Depends: pydantic_ai, sevn.agent.adapters.egress_bridge, sevn.config.llm_params,
    sevn.config.model_resolution

Exports:
    NativeModelContext — inputs for one native model build (proxy bridge + sampling).
    build_native_model_settings — map tier-B sampling knobs to typed provider settings.
    default_native_model_context — convenience ``NativeModelContext`` builder.
    resolve_pydantic_model — catalog id → native ``Model`` via the W2 egress bridge.
    resolve_pydantic_model_for_slot — slot-aware factory with optional ``FallbackModel``.

Examples:
    >>> from sevn.config.model_resolution import ModelSlot
    >>> from sevn.agent.adapters.native_model import NativeModelContext
    >>> isinstance(ModelSlot.tier_b.value, str)
    True
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.providers.openai import OpenAIProvider

from sevn.agent.adapters.egress_bridge import (
    build_sevn_anthropic_client,
    build_sevn_openai_client,
    resolve_proxy_shared_secret,
)
from sevn.agent.adapters.minimax_wrapper_model import (
    MiniMaxHygieneContext,
    wrap_minimax_native_model,
    wrap_minimax_openai_native_model,
)
from sevn.config.llm_params import resolve_llm_request_params
from sevn.config.model_resolution import (
    ModelSlot,
    is_minimax_catalog_model,
    resolve_slot_fallback_model_ids,
    resolve_transport_for_model_id,
    resolve_wire_model_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.models import Model

    from sevn.agent.adapters.tier_b_model import TriagerBoundToolChoiceContext
    from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
    from sevn.agent.tracing.sink import TraceSink

NativeModelSettings = AnthropicModelSettings | OpenAIChatModelSettings | BedrockModelSettings

_DEFAULT_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class NativeModelContext:
    """Correlation + bridge inputs for one native model construction."""

    slot: ModelSlot
    model_id: str
    proxy_base: str
    shared_secret: str | None
    trace: TraceSink | None
    redactor: TraceRedactionPolicy | None
    session_id: str
    turn_id: str
    tier: str | None = None
    parent_span_id: str | None = None
    agent: str = "tier_b"
    content_root: Path | None = None
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS
    seed: int | None = None
    providers_obj: dict[str, Any] | None = None
    fallback_model_ids: tuple[str, ...] = ()
    user_id: str | None = None
    channel: str | None = None
    workspace_id: str | None = None
    executor_tier: str | None = None
    triager_bound_tool_choice: TriagerBoundToolChoiceContext | None = None


def _transport_name_for_model(
    model_id: str,
    providers_obj: dict[str, Any] | None,
) -> str:
    """Resolve the transport label for a catalog model id.

    Args:
        model_id (str): Workspace catalog model id.
        providers_obj (dict[str, Any] | None): Merged ``providers`` block.

    Returns:
        str: Lowercased transport name (``anthropic``, ``chat_completions``, ``bedrock``).

    Examples:
        >>> _transport_name_for_model("minimax/MiniMax-M2", None)
        'chat_completions'
        >>> _transport_name_for_model("minimax/MiniMax-M2", {"minimax": {"transport": "anthropic"}})
        'anthropic'
        >>> _transport_name_for_model("openai/gpt-4o", {"models": {"openai/gpt-4o": {"transport": "chat_completions"}}})
        'chat_completions'
    """
    return resolve_transport_for_model_id(providers_obj or {}, model_id)


def _catalog_provider_family(
    model_id: str,
    providers_obj: dict[str, Any] | None,
) -> str:
    """Infer native provider family from catalog id prefix (W3.1).

    Catalog prefixes win over the generic ``chat_completions`` transport default so
    ``anthropic/claude-*`` and ``bedrock/*`` map to the correct native constructors.
    For ``minimax/*``, the resolved transport determines the family: ``openai``
    (default, ``chat_completions`` wire) or ``anthropic`` (when ``providers.minimax.transport``
    is explicitly ``anthropic``).

    Args:
        model_id (str): Workspace catalog model id.
        providers_obj (dict[str, Any] | None): Merged ``providers`` block.

    Returns:
        str: One of ``anthropic``, ``openai``, ``bedrock``.

    Examples:
        >>> _catalog_provider_family("anthropic/claude-sonnet-4-20250514", None)
        'anthropic'
        >>> _catalog_provider_family("bedrock/anthropic.claude-3-haiku", None)
        'bedrock'
        >>> _catalog_provider_family("minimax/MiniMax-M3", {"minimax": {"transport": "chat_completions"}})
        'openai'
        >>> _catalog_provider_family("minimax/MiniMax-M2", None)
        'openai'
        >>> _catalog_provider_family("minimax/MiniMax-M2", {"minimax": {"transport": "anthropic"}})
        'anthropic'
    """
    mid = model_id.strip().lower()
    if is_minimax_catalog_model(model_id):
        transport = _transport_name_for_model(model_id, providers_obj)
        if transport == "chat_completions":
            return "openai"
        return "anthropic"
    if mid.startswith("anthropic/"):
        return "anthropic"
    if mid.startswith("openai/"):
        return "openai"
    if mid.startswith("bedrock/"):
        return "bedrock"
    transport = _transport_name_for_model(model_id, providers_obj)
    if transport == "anthropic":
        return "anthropic"
    if transport == "bedrock":
        return "bedrock"
    return "openai"


def _sampling_float(sampling: dict[str, float | int], key: str) -> float | None:
    """Return one float sampling knob when present.

    Args:
        sampling (dict[str, float | int]): Transport-filtered sampling kwargs.
        key (str): Sampling key name.

    Returns:
        float | None: Parsed float or ``None`` when absent.

    Examples:
        >>> _sampling_float({"temperature": 0.5}, "temperature")
        0.5
        >>> _sampling_float({}, "temperature") is None
        True
    """
    if key not in sampling:
        return None
    return float(sampling[key])


def _sampling_int(sampling: dict[str, float | int], key: str) -> int | None:
    """Return one int sampling knob when present.

    Args:
        sampling (dict[str, float | int]): Transport-filtered sampling kwargs.
        key (str): Sampling key name.

    Returns:
        int | None: Parsed int or ``None`` when absent.

    Examples:
        >>> _sampling_int({"seed": 7}, "seed")
        7
        >>> _sampling_int({}, "seed") is None
        True
    """
    if key not in sampling:
        return None
    return int(sampling[key])


def _wire_model_name(model_id: str) -> str:
    """Return the upstream model string for a native pydantic-ai constructor.

    Args:
        model_id (str): Workspace catalog model id.

    Returns:
        str: Vendor model name (``minimax/`` prefix stripped).

    Examples:
        >>> _wire_model_name("minimax/MiniMax-M2.7")
        'MiniMax-M2.7'
        >>> _wire_model_name("openai/gpt-4o-mini")
        'openai/gpt-4o-mini'
    """
    return resolve_wire_model_id(model_id)


def build_native_model_settings(
    *,
    model_id: str,
    transport_name: str,
    agent: str,
    content_root: Path | None,
    max_output_tokens: int,
    seed: int | None,
) -> NativeModelSettings:
    """Map tier-B / triager sampling knobs to typed pydantic-ai model settings (W3.3).

    Reuses :func:`sevn.config.llm_params.resolve_llm_request_params` for transport-filtered
    sampling, then projects into provider-specific settings classes. Anthropic paths enable
    instruction + tool-definition caching only (not full message cache — W4/MiniMax gate).

    Args:
        model_id (str): Workspace catalog model id.
        transport_name (str): Resolved transport label.
        agent (str): Agent key for ``LLM_params_config.json`` lookup.
        content_root (Path | None): Workspace content root.
        max_output_tokens (int): Provider ``max_tokens`` floor.
        seed (int | None): Deterministic seed fallback when the workspace file omits ``seed``.

    Returns:
        NativeModelSettings: Provider-specific settings for the native model constructor.

    Examples:
        >>> s = build_native_model_settings(
        ...     model_id="minimax/MiniMax-M2",
        ...     transport_name="anthropic",
        ...     agent="tier_b",
        ...     content_root=None,
        ...     max_output_tokens=4096,
        ...     seed=None,
        ... )
        >>> s["max_tokens"]
        4096
    """
    sampling = resolve_llm_request_params(
        agent,
        model_id,
        transport_name,
        content_root=content_root,
        seed=seed,
    )

    if transport_name == "anthropic":
        payload: dict[str, Any] = {
            "max_tokens": max_output_tokens,
            "anthropic_cache_instructions": True,
            "anthropic_cache_tool_definitions": True,
        }
        for key, parser in (
            ("temperature", _sampling_float),
            ("top_p", _sampling_float),
            ("top_k", _sampling_int),
            ("seed", _sampling_int),
        ):
            value = parser(sampling, key)
            if value is not None:
                payload[key] = value
        return cast("AnthropicModelSettings", payload)

    if transport_name == "bedrock":
        payload = {"max_tokens": max_output_tokens}
        for key, parser in (
            ("temperature", _sampling_float),
            ("top_p", _sampling_float),
            ("top_k", _sampling_int),
        ):
            value = parser(sampling, key)
            if value is not None:
                payload[key] = value
        return cast("BedrockModelSettings", payload)

    payload = {"max_tokens": max_output_tokens}
    for key, parser in (
        ("temperature", _sampling_float),
        ("top_p", _sampling_float),
        ("seed", _sampling_int),
    ):
        value = parser(sampling, key)
        if value is not None:
            payload[key] = value
    return cast("OpenAIChatModelSettings", payload)


def _build_anthropic_native_model(
    *,
    model_id: str,
    ctx: NativeModelContext,
    settings: NativeModelSettings,
) -> AnthropicModel:
    """Build one ``AnthropicModel`` routed through the W2 egress bridge.

    Args:
        model_id (str): Catalog model id (determines wire model name).
        ctx (NativeModelContext): Bridge + trace correlation fields.
        settings (NativeModelSettings): Typed Anthropic settings.

    Returns:
        AnthropicModel: Native model using ``AnthropicProvider(base_url=proxy, http_client=…)``.

    Examples:
        >>> import inspect
        >>> "model_id" in inspect.signature(_build_anthropic_native_model).parameters
        True
    """
    transport = _transport_name_for_model(model_id, ctx.providers_obj)
    http_client = build_sevn_anthropic_client(
        proxy_base=ctx.proxy_base,
        shared_secret=ctx.shared_secret,
        trace=ctx.trace,
        redactor=ctx.redactor,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        tier=ctx.tier,
        parent_span_id=ctx.parent_span_id,
        model_id=model_id,
        regime="PER_TOKEN",
        transport=transport,
    )
    provider = AnthropicProvider(
        base_url=ctx.proxy_base.rstrip("/"),
        http_client=http_client,
        api_key="proxy-injected",
    )
    return AnthropicModel(
        _wire_model_name(model_id),
        provider=provider,
        settings=settings,
    )


def _minimax_hygiene_context(ctx: NativeModelContext) -> MiniMaxHygieneContext:
    """Build MiniMax wrapper hygiene inputs from native model context.

    Args:
        ctx (NativeModelContext): Native build context.

    Returns:
        MiniMaxHygieneContext: Correlation fields for request hygiene.

    Examples:
        >>> c = NativeModelContext(
        ...     slot=ModelSlot.tier_b,
        ...     model_id="minimax/MiniMax-M2",
        ...     proxy_base="http://p",
        ...     shared_secret="s",
        ...     trace=None,
        ...     redactor=None,
        ...     session_id="sess",
        ...     turn_id="turn",
        ...     agent="tier_b",
        ... )
        >>> _minimax_hygiene_context(c).session_id
        'sess'
    """
    return MiniMaxHygieneContext(
        agent=ctx.agent,
        content_root=ctx.content_root,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        user_id=ctx.user_id,
        channel=ctx.channel,
        workspace_id=ctx.workspace_id,
        executor_tier=ctx.executor_tier or ctx.tier,
        triager_bound_tool_choice=ctx.triager_bound_tool_choice,
    )


def _build_openai_native_model(
    *,
    model_id: str,
    ctx: NativeModelContext,
    settings: NativeModelSettings,
) -> OpenAIChatModel:
    """Build one ``OpenAIChatModel`` routed through the W2 egress bridge.

    Args:
        model_id (str): Catalog model id.
        ctx (NativeModelContext): Bridge + trace correlation fields.
        settings (NativeModelSettings): Typed OpenAI chat settings.

    Returns:
        OpenAIChatModel: Native model using ``OpenAIProvider(base_url=proxy, http_client=…)``.

    Examples:
        >>> import inspect
        >>> "ctx" in inspect.signature(_build_openai_native_model).parameters
        True
    """
    transport = _transport_name_for_model(model_id, ctx.providers_obj)
    http_client = build_sevn_openai_client(
        proxy_base=ctx.proxy_base,
        shared_secret=ctx.shared_secret,
        trace=ctx.trace,
        redactor=ctx.redactor,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        tier=ctx.tier,
        parent_span_id=ctx.parent_span_id,
        model_id=model_id,
        regime="PER_TOKEN",
        transport=transport,
    )
    provider = OpenAIProvider(
        base_url=ctx.proxy_base.rstrip("/"),
        http_client=http_client,
        api_key="proxy-injected",
    )
    return OpenAIChatModel(
        _wire_model_name(model_id),
        provider=provider,
        settings=settings,
    )


def _build_bedrock_native_model(
    *,
    model_id: str,
    ctx: NativeModelContext,
    settings: NativeModelSettings,
) -> BedrockConverseModel:
    """Build one ``BedrockConverseModel`` targeting the proxy Bedrock forwarder.

    Bedrock uses boto3 rather than the httpx egress bridge; ``base_url`` points at the
    proxy ``/llm/bedrock`` origin so upstream SigV4 stays server-side (W3.1 bedrock row).

    Args:
        model_id (str): Catalog model id.
        ctx (NativeModelContext): Proxy base + correlation fields.
        settings (NativeModelSettings): Typed Bedrock settings.

    Returns:
        BedrockConverseModel: Native Bedrock model via proxy ``base_url``.

    Examples:
        >>> import inspect
        >>> "model_id" in inspect.signature(_build_bedrock_native_model).parameters
        True
    """
    bedrock_base = f"{ctx.proxy_base.rstrip('/')}/llm/bedrock"
    provider = BedrockProvider(base_url=bedrock_base)
    return BedrockConverseModel(
        _wire_model_name(model_id),
        provider=provider,
        settings=settings,
    )


def _build_single_native_model(*, ctx: NativeModelContext) -> Model:
    """Build one native model for ``ctx.model_id`` (no fallback wrapper).

    Args:
        ctx (NativeModelContext): Full build context including ``model_id``.

    Returns:
        Model: Provider-appropriate native model instance.

    Raises:
        NotImplementedError: When the resolved transport is unsupported for native models.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_build_single_native_model)
        True
    """
    transport_name = _transport_name_for_model(ctx.model_id, ctx.providers_obj)
    provider_family = _catalog_provider_family(ctx.model_id, ctx.providers_obj)
    settings_transport = (
        "anthropic"
        if provider_family == "anthropic"
        else "bedrock"
        if provider_family == "bedrock"
        else transport_name
    )
    settings = build_native_model_settings(
        model_id=ctx.model_id,
        transport_name=settings_transport,
        agent=ctx.agent,
        content_root=ctx.content_root,
        max_output_tokens=ctx.max_output_tokens,
        seed=ctx.seed,
    )
    if provider_family == "anthropic":
        model = _build_anthropic_native_model(
            model_id=ctx.model_id,
            ctx=ctx,
            settings=settings,
        )
        return wrap_minimax_native_model(
            model,
            catalog_model_id=ctx.model_id,
            hygiene=_minimax_hygiene_context(ctx),
        )
    if provider_family == "bedrock":
        return _build_bedrock_native_model(
            model_id=ctx.model_id,
            ctx=ctx,
            settings=settings,
        )
    if provider_family == "openai":
        openai_model = _build_openai_native_model(
            model_id=ctx.model_id,
            ctx=ctx,
            settings=settings,
        )
        return wrap_minimax_openai_native_model(
            openai_model,
            catalog_model_id=ctx.model_id,
            hygiene=_minimax_hygiene_context(ctx),
        )
    msg = (
        f"native model factory does not support provider_family={provider_family!r} "
        f"for model_id={ctx.model_id!r}"
    )
    raise NotImplementedError(msg)


def resolve_pydantic_model(*, ctx: NativeModelContext) -> Model:
    """Return a native pydantic-ai ``Model`` for one catalog id (W3.1).

    MiniMax catalog ids map to ``AnthropicModel`` wrapped in :class:`MiniMaxWrapperModel`
    for XML tool recovery + streaming parity (W4). When ``ctx.fallback_model_ids`` is
    every member is built through the same factory (W3.2).

    Args:
        ctx (NativeModelContext): Slot, catalog id, proxy bridge, and sampling context.

    Returns:
        Model: ``AnthropicModel``, ``OpenAIChatModel``, ``BedrockConverseModel``, or
            ``FallbackModel`` thereof.

    Examples:
        >>> import inspect
        >>> "ctx" in inspect.signature(resolve_pydantic_model).parameters
        True
    """
    primary = _build_single_native_model(ctx=ctx)
    if not ctx.fallback_model_ids:
        return primary
    fallback_models = [
        _build_single_native_model(ctx=replace(ctx, model_id=fallback_id))
        for fallback_id in ctx.fallback_model_ids
    ]
    return FallbackModel(primary, *fallback_models)


def resolve_pydantic_model_for_slot(
    *,
    workspace: object,
    ctx: NativeModelContext,
) -> Model:
    """Build a native model for ``ctx.slot`` including configured fallbacks (W3.2).

    Reads ``providers.fallback_chain`` for ``triager`` / ``B`` keys and excludes the
    primary ``ctx.model_id`` from the fallback list.

    Args:
        workspace (object): Parsed workspace settings.
        ctx (NativeModelContext): Base context; ``model_id`` is the slot primary.

    Returns:
        Model: Native model (optionally wrapped in ``FallbackModel``).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(resolve_pydantic_model_for_slot)
        True
    """
    fallbacks = resolve_slot_fallback_model_ids(
        workspace,
        ctx.slot,
        primary=ctx.model_id,
    )
    return resolve_pydantic_model(ctx=replace(ctx, fallback_model_ids=fallbacks))


def default_native_model_context(
    *,
    slot: ModelSlot,
    model_id: str,
    proxy_base: str,
    session_id: str,
    turn_id: str,
    agent: str,
    trace: TraceSink | None = None,
    redactor: TraceRedactionPolicy | None = None,
    tier: str | None = None,
    parent_span_id: str | None = None,
    content_root: Path | None = None,
    max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    seed: int | None = None,
    providers_obj: dict[str, Any] | None = None,
    shared_secret: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    workspace_id: str | None = None,
    executor_tier: str | None = None,
    triager_bound_tool_choice: TriagerBoundToolChoiceContext | None = None,
) -> NativeModelContext:
    """Convenience builder for :class:`NativeModelContext` with proxy secret resolution.

    Args:
        slot (ModelSlot): Logical model slot (``triager`` or ``tier_b``).
        model_id (str): Resolved catalog model id for the slot.
        proxy_base (str): Egress proxy origin URL.
        session_id (str): Session correlation id.
        turn_id (str): Turn correlation id.
        agent (str): Agent key for sampling lookup.
        trace (TraceSink | None): Optional trace sink.
        redactor (TraceRedactionPolicy | None): Workspace redaction policy.
        tier (str | None): Executor tier label.
        parent_span_id (str | None): Parent span for trace linkage.
        content_root (Path | None): Workspace content root.
        max_output_tokens (int): Provider max output tokens.
        seed (int | None): Deterministic seed fallback when the workspace file omits ``seed``.
        providers_obj (dict[str, Any] | None): Merged providers block.
        shared_secret (str | None): Proxy token; resolved from env when ``None``.
        user_id (str | None): Channel user id for MiniMax ``metadata``.
        channel (str | None): Active channel for MiniMax ``metadata``.
        workspace_id (str | None): Workspace id for MiniMax ``metadata``.
        executor_tier (str | None): Executor tier label for MiniMax ``metadata``.
        triager_bound_tool_choice (TriagerBoundToolChoiceContext | None): Per-turn
            triager-bound ``tool_choice`` escalation for native MiniMax models.

    Returns:
        NativeModelContext: Context ready for :func:`resolve_pydantic_model_for_slot`.

    Examples:
        >>> ctx = default_native_model_context(
        ...     slot=ModelSlot.tier_b,
        ...     model_id="minimax/MiniMax-M2",
        ...     proxy_base="http://127.0.0.1:8787",
        ...     session_id="s",
        ...     turn_id="t",
        ...     agent="tier_b",
        ...     shared_secret="sec",
        ... )
        >>> ctx.model_id
        'minimax/MiniMax-M2'
    """
    secret = shared_secret if shared_secret is not None else resolve_proxy_shared_secret()
    return NativeModelContext(
        slot=slot,
        model_id=model_id,
        proxy_base=proxy_base,
        shared_secret=secret,
        trace=trace,
        redactor=redactor,
        session_id=session_id,
        turn_id=turn_id,
        tier=tier,
        parent_span_id=parent_span_id,
        agent=agent,
        content_root=content_root,
        max_output_tokens=max_output_tokens,
        seed=seed,
        providers_obj=providers_obj,
        user_id=user_id,
        channel=channel,
        workspace_id=workspace_id,
        executor_tier=executor_tier,
        triager_bound_tool_choice=triager_bound_tool_choice,
    )


__all__ = [
    "NativeModelContext",
    "build_native_model_settings",
    "default_native_model_context",
    "resolve_pydantic_model",
    "resolve_pydantic_model_for_slot",
]
