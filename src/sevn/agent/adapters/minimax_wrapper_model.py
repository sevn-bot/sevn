"""MiniMax native-model wrappers: Anthropic XML recovery + OpenAI settings hygiene.

Module: sevn.agent.adapters.minimax_wrapper_model
Depends: pydantic_ai, sevn.agent.adapters.tier_b_model, sevn.config.llm_params

Exports:
    MiniMaxHygieneContext — correlation fields for MiniMax request hygiene.
    MiniMaxWrapperModel — ``WrapperModel`` applying XML recovery on batch + stream paths
        (Anthropic wire).
    MiniMaxOpenAIWrapperModel — ``WrapperModel`` over ``OpenAIChatModel`` with object-form
        ``tool_choice``, thinking enablement, metadata, and sampling hygiene (W3).
    wrap_minimax_native_model — attach Anthropic wrapper when ``is_minimax_catalog_model`` holds.
    wrap_minimax_openai_native_model — attach OpenAI wrapper when ``is_minimax_catalog_model`` holds.

Examples:
    >>> from pydantic_ai.models.function import FunctionModel
    >>> from pydantic_ai.messages import ModelResponse, TextPart
    >>> async def _noop(messages, info):
    ...     return ModelResponse(parts=[TextPart(content="ok")])
    >>> inner = FunctionModel(_noop, model_name="MiniMax-M2")
    >>> wrapped = wrap_minimax_native_model(
    ...     inner,
    ...     catalog_model_id="minimax/MiniMax-M2",
    ...     hygiene=MiniMaxHygieneContext(agent="tier_b"),
    ... )
    >>> wrapped.model_name
    'MiniMax-M2'
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai._deprecated_callable import deprecated_callable_property
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ModelResponseStreamEvent,
    PartStartEvent,
    TextPart,
)
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings, merge_model_settings

from sevn.agent.adapters.tier_b_model import (
    TriagerBoundToolChoiceContext,
    _apply_xml_tool_recovery,
    build_llm_request_metadata,
    repair_openai_tool_pairing,
)
from sevn.config.llm_params import MINIMAX_THINKING_AGENTS, resolve_minimax_thinking_request
from sevn.config.model_resolution import is_minimax_catalog_model

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from pydantic_ai._run_context import RunContext
    from pydantic_ai.models import Model


@dataclass(frozen=True)
class MiniMaxHygieneContext:
    """Inputs for MiniMax anthropic-wire request hygiene on native models (W4.4)."""

    agent: str
    content_root: Path | None = None
    session_id: str | None = None
    turn_id: str | None = None
    user_id: str | None = None
    channel: str | None = None
    workspace_id: str | None = None
    executor_tier: str | None = None
    triager_bound_tool_choice: TriagerBoundToolChoiceContext | None = None


def _with_xml_tool_recovery(response: ModelResponse) -> ModelResponse:
    """Apply MiniMax XML tool recovery to a resolved ``ModelResponse``.

    Args:
        response (ModelResponse): Inner native model response.

    Returns:
        ModelResponse: Same response with recovered ``ToolCallPart``s when applicable.

    Examples:
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> r = _with_xml_tool_recovery(ModelResponse(parts=[TextPart(content="plain")]))
        >>> r.parts[0].content
        'plain'
    """
    recovered = _apply_xml_tool_recovery(list(response.parts))
    if recovered == response.parts:
        return response
    return replace(response, parts=recovered)


class _RecoveredStreamedResponse(StreamedResponse):
    """Proxy ``StreamedResponse`` that applies XML recovery on ``get()`` (W4.2)."""

    def __init__(self, inner: StreamedResponse) -> None:
        """Wrap one inner stream without altering live delta forwarding.

        Args:
            inner (StreamedResponse): Provider stream to proxy.

        Examples:
            >>> import inspect
            >>> "inner" in inspect.signature(_RecoveredStreamedResponse.__init__).parameters
            True
        """
        super().__init__(model_request_parameters=inner.model_request_parameters)
        self._inner = inner

    def __aiter__(self) -> AsyncIterator[ModelResponseStreamEvent]:
        """Delegate live event iteration to the inner stream (preserves progressive text).

        Returns:
            AsyncIterator[ModelResponseStreamEvent]: Inner stream events unchanged.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(_RecoveredStreamedResponse.__aiter__)
            True
        """
        return self._inner.__aiter__()

    def get(self) -> ModelResponse:
        """Return the inner response with MiniMax XML tool recovery applied.

        Returns:
            ModelResponse: Recovered final response from the proxied stream.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(_RecoveredStreamedResponse.get)
            True
        """
        return _with_xml_tool_recovery(self._inner.get())

    async def close_stream(self) -> None:
        """Close the proxied provider stream.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_RecoveredStreamedResponse.close_stream)
            True
        """
        await self._inner.close_stream()

    @deprecated_callable_property(
        "`StreamedResponse.usage` is no longer a method; access it as a property (drop the parentheses).",
    )
    def usage(self) -> Any:  # type: ignore[override]
        """Return token usage accumulated on the inner stream.

        Returns:
            Any: Inner :attr:`StreamedResponse.usage` value.

        Examples:
            >>> import inspect
            >>> isinstance(type(_RecoveredStreamedResponse).usage, property)
            False
        """
        return self._inner.usage

    @property
    def model_name(self) -> str:
        """Model name reported by the inner stream.

        Returns:
            str: Inner stream model name.

        Examples:
            >>> import inspect
            >>> isinstance(_RecoveredStreamedResponse.model_name, property)
            True
        """
        return self._inner.model_name

    @property
    def provider_name(self) -> str | None:
        """Provider name reported by the inner stream.

        Returns:
            str | None: Inner stream provider label.

        Examples:
            >>> isinstance(_RecoveredStreamedResponse.provider_name, property)
            True
        """
        return self._inner.provider_name

    @property
    def provider_url(self) -> str | None:
        """Provider URL reported by the inner stream.

        Returns:
            str | None: Inner stream provider base URL.

        Examples:
            >>> isinstance(_RecoveredStreamedResponse.provider_url, property)
            True
        """
        return self._inner.provider_url

    @property
    def timestamp(self) -> Any:
        """Response timestamp reported by the inner stream.

        Returns:
            Any: Inner stream timestamp (``datetime``).

        Examples:
            >>> isinstance(_RecoveredStreamedResponse.timestamp, property)
            True
        """
        return self._inner.timestamp

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        """Satisfy the abstract base; iteration uses ``__aiter__`` on the inner stream.

        Returns:
            AsyncIterator[ModelResponseStreamEvent]: Never consumed — delegate via ``__aiter__``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(_RecoveredStreamedResponse._get_event_iterator)
            True
        """
        if False:  # pragma: no cover — satisfy abstract base without double-iterating
            yield PartStartEvent(index=0, part=TextPart(content=""))


class MiniMaxWrapperModel(WrapperModel):
    """Native MiniMax ``AnthropicModel`` wrapper with XML recovery + stream parity (W4).

    Batch ``request`` and streaming ``request_stream`` both run
    :func:`sevn.agent.adapters.tier_b_model._apply_xml_tool_recovery` on the final
    ``ModelResponse`` so XML-in-text tool calls become real ``ToolCallPart``s while
    progressive text deltas still flow through the inner stream unchanged.
    """

    def __init__(
        self,
        wrapped: Model | str,
        *,
        catalog_model_id: str,
        hygiene: MiniMaxHygieneContext,
    ) -> None:
        """Wrap one native Anthropic model with MiniMax-specific hygiene + recovery.

        Args:
            wrapped (Model | str): Inner native model (typically ``AnthropicModel``).
            catalog_model_id (str): Workspace catalog model id.
            hygiene (MiniMaxHygieneContext): Request hygiene correlation fields.

        Examples:
            >>> import inspect
            >>> "hygiene" in inspect.signature(MiniMaxWrapperModel.__init__).parameters
            True
        """
        super().__init__(cast("Model", wrapped))
        self.catalog_model_id = catalog_model_id
        self.hygiene = hygiene

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Call inner model, then recover XML tool calls from text parts (W4.1).

        Args:
            messages (list[ModelMessage]): Conversation history.
            model_settings (ModelSettings | None): Per-request settings override.
            model_request_parameters (ModelRequestParameters): Tool/output parameters.

        Returns:
            ModelResponse: Inner response with XML tool calls recovered.

        Examples:
            >>> import inspect
            >>> "messages" in inspect.signature(MiniMaxWrapperModel.request).parameters
            True
        """
        prepared_settings, prepared_params = self.prepare_request(
            model_settings,
            model_request_parameters,
        )
        response = await self.wrapped.request(messages, prepared_settings, prepared_params)
        return _with_xml_tool_recovery(response)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        """Stream from inner model; XML recovery runs on the final ``get()`` (W4.2).

        Args:
            messages (list[ModelMessage]): Conversation history.
            model_settings (ModelSettings | None): Per-request settings override.
            model_request_parameters (ModelRequestParameters): Tool/output parameters.
            run_context (RunContext[Any] | None): Optional pydantic-ai run context.

        Returns:
            AsyncIterator[StreamedResponse]: Proxy stream forwarding live deltas; ``get()`` applies recovery.

        Examples:
            >>> import inspect
            >>> "run_context" in inspect.signature(MiniMaxWrapperModel.request_stream).parameters
            True
        """
        prepared_settings, prepared_params = self.prepare_request(
            model_settings,
            model_request_parameters,
        )
        async with self.wrapped.request_stream(
            messages,
            prepared_settings,
            prepared_params,
            run_context,
        ) as inner_stream:
            yield _RecoveredStreamedResponse(inner_stream)

    def prepare_request(
        self,
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> tuple[ModelSettings | None, ModelRequestParameters]:
        """Merge MiniMax anthropic-wire hygiene into native settings (W4.4).

        Drops ignored ``top_k``, sets object-form ``tool_choice`` when tools are
        present, attaches config-gated ``anthropic_thinking``, and adds redaction-safe
        ``metadata`` via ``extra_body``. Body normalization remains proxy-side.

        Empty ``end_turn`` nudge stays on the FunctionModel / hook path until W14.

        Args:
            model_settings (ModelSettings | None): Caller settings override.
            model_request_parameters (ModelRequestParameters): Resolved tool parameters.

        Returns:
            tuple[ModelSettings | None, ModelRequestParameters]: Hygiene-adjusted inputs.

        Examples:
            >>> import inspect
            >>> "model_request_parameters" in inspect.signature(
            ...     MiniMaxWrapperModel.prepare_request
            ... ).parameters
            True
        """
        merged_settings, params = self.wrapped.prepare_request(
            model_settings,
            model_request_parameters,
        )
        merged_settings = merge_model_settings(self.settings, merged_settings)
        payload: dict[str, Any] = dict(merged_settings or {})
        payload.pop("top_k", None)

        has_tools = bool(params.function_tools or params.output_tools)
        if has_tools:
            ctx = self.hygiene.triager_bound_tool_choice
            if ctx is not None:
                payload["tool_choice"] = {"type": ctx.anthropic_tool_choice_type()}
            else:
                payload["tool_choice"] = {"type": "auto"}

        thinking = resolve_minimax_thinking_request(
            self.hygiene.agent,
            self.catalog_model_id,
            content_root=self.hygiene.content_root,
        )
        if thinking is not None:
            payload["anthropic_thinking"] = thinking

        if self.hygiene.agent in MINIMAX_THINKING_AGENTS:
            metadata = build_llm_request_metadata(
                session_id=self.hygiene.session_id,
                turn_id=self.hygiene.turn_id,
                user_id=self.hygiene.user_id,
                channel=self.hygiene.channel,
                workspace_id=self.hygiene.workspace_id,
                agent=self.hygiene.agent,
                executor_tier=self.hygiene.executor_tier,
            )
            if metadata:
                extra_body = payload.get("extra_body")
                extra: dict[str, Any] = dict(extra_body) if isinstance(extra_body, dict) else {}
                extra["metadata"] = metadata
                payload["extra_body"] = extra

        if not payload:
            return None, params
        return cast("ModelSettings", payload), params


def wrap_minimax_native_model(
    model: Model,
    *,
    catalog_model_id: str,
    hygiene: MiniMaxHygieneContext,
) -> Model:
    """Return ``MiniMaxWrapperModel`` for MiniMax catalog ids; passthrough otherwise (W4.3).

    Args:
        model (Model): Native model built by :mod:`sevn.agent.adapters.native_model`.
        catalog_model_id (str): Workspace catalog model id.
        hygiene (MiniMaxHygieneContext): MiniMax request hygiene correlation fields.

    Returns:
        Model: Wrapped model for ``minimax/*``, unchanged for other catalog ids.

    Examples:
        >>> from pydantic_ai.models.function import FunctionModel
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> async def _noop(messages, info):
        ...     return ModelResponse(parts=[TextPart(content="ok")])
        >>> inner = FunctionModel(_noop, model_name="x")
        >>> same = wrap_minimax_native_model(
        ...     inner,
        ...     catalog_model_id="anthropic/claude-haiku",
        ...     hygiene=MiniMaxHygieneContext(agent="tier_b"),
        ... )
        >>> same is inner
        True
    """
    if not is_minimax_catalog_model(catalog_model_id):
        return model
    return MiniMaxWrapperModel(
        model,
        catalog_model_id=catalog_model_id,
        hygiene=hygiene,
    )


class MiniMaxOpenAIWrapperModel(WrapperModel):
    """MiniMax ``OpenAIChatModel`` wrapper: object-form ``tool_choice``, thinking, metadata (W3).

    Thin settings-hygiene layer mirroring :class:`MiniMaxWrapperModel` for the
    ``chat_completions`` transport. No XML recovery — the OpenAI wire returns
    structured ``tool_calls`` natively.
    """

    def __init__(
        self,
        wrapped: Model | str,
        *,
        catalog_model_id: str,
        hygiene: MiniMaxHygieneContext,
    ) -> None:
        """Wrap one native ``OpenAIChatModel`` with MiniMax settings hygiene.

        Args:
            wrapped (Model | str): Inner ``OpenAIChatModel``.
            catalog_model_id (str): Workspace catalog model id.
            hygiene (MiniMaxHygieneContext): Request hygiene correlation fields.

        Examples:
            >>> import inspect
            >>> "hygiene" in inspect.signature(MiniMaxOpenAIWrapperModel.__init__).parameters
            True
        """
        super().__init__(cast("Model", wrapped))
        self.catalog_model_id = catalog_model_id
        self.hygiene = hygiene

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Repair tool pairing, then delegate to the inner ``OpenAIChatModel``.

        Drops orphan tool returns from the history first so the chat_completions wire never
        400s with ``2013`` (tool id not found); the OpenAI wire returns structured
        ``tool_calls`` natively, so no XML recovery is applied to the response.

        Args:
            messages (list[ModelMessage]): Conversation history.
            model_settings (ModelSettings | None): Per-request settings override.
            model_request_parameters (ModelRequestParameters): Tool/output parameters.

        Returns:
            ModelResponse: Inner native response.

        Examples:
            >>> import inspect
            >>> "messages" in inspect.signature(MiniMaxOpenAIWrapperModel.request).parameters
            True
        """
        prepared_settings, prepared_params = self.prepare_request(
            model_settings,
            model_request_parameters,
        )
        return await self.wrapped.request(
            repair_openai_tool_pairing(messages),
            prepared_settings,
            prepared_params,
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        """Repair tool pairing, then stream from the inner ``OpenAIChatModel``.

        Args:
            messages (list[ModelMessage]): Conversation history.
            model_settings (ModelSettings | None): Per-request settings override.
            model_request_parameters (ModelRequestParameters): Tool/output parameters.
            run_context (RunContext[Any] | None): Optional pydantic-ai run context.

        Returns:
            AsyncIterator[StreamedResponse]: Inner proxy stream (no XML recovery on the wire).

        Examples:
            >>> import inspect
            >>> "run_context" in inspect.signature(
            ...     MiniMaxOpenAIWrapperModel.request_stream
            ... ).parameters
            True
        """
        prepared_settings, prepared_params = self.prepare_request(
            model_settings,
            model_request_parameters,
        )
        async with self.wrapped.request_stream(
            repair_openai_tool_pairing(messages),
            prepared_settings,
            prepared_params,
            run_context,
        ) as inner_stream:
            yield inner_stream

    def prepare_request(
        self,
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> tuple[ModelSettings | None, ModelRequestParameters]:
        """Merge MiniMax OpenAI-wire hygiene into native settings (W3.1).

        Drops ignored ``top_k``, sets OpenAI-shaped ``tool_choice`` (``"required"``
        or ``"auto"`` via :meth:`TriagerBoundToolChoiceContext.openai_tool_choice`),
        attaches config-gated ``openai_thinking`` for ``reasoning_content`` mapping,
        and adds redaction-safe ``metadata`` via ``extra_body``.

        Args:
            model_settings (ModelSettings | None): Caller settings override.
            model_request_parameters (ModelRequestParameters): Resolved tool parameters.

        Returns:
            tuple[ModelSettings | None, ModelRequestParameters]: Hygiene-adjusted inputs.

        Examples:
            >>> import inspect
            >>> "model_request_parameters" in inspect.signature(
            ...     MiniMaxOpenAIWrapperModel.prepare_request
            ... ).parameters
            True
        """
        merged_settings, params = self.wrapped.prepare_request(
            model_settings,
            model_request_parameters,
        )
        merged_settings = merge_model_settings(self.settings, merged_settings)
        payload: dict[str, Any] = dict(merged_settings or {})
        payload.pop("top_k", None)

        has_tools = bool(params.function_tools or params.output_tools)
        if has_tools:
            ctx = self.hygiene.triager_bound_tool_choice
            if ctx is not None:
                payload["tool_choice"] = ctx.openai_tool_choice()
            else:
                payload["tool_choice"] = "auto"

        thinking = resolve_minimax_thinking_request(
            self.hygiene.agent,
            self.catalog_model_id,
            content_root=self.hygiene.content_root,
        )
        if thinking is not None:
            payload["openai_thinking"] = thinking

        if self.hygiene.agent in MINIMAX_THINKING_AGENTS:
            metadata = build_llm_request_metadata(
                session_id=self.hygiene.session_id,
                turn_id=self.hygiene.turn_id,
                user_id=self.hygiene.user_id,
                channel=self.hygiene.channel,
                workspace_id=self.hygiene.workspace_id,
                agent=self.hygiene.agent,
                executor_tier=self.hygiene.executor_tier,
            )
            if metadata:
                extra_body = payload.get("extra_body")
                extra: dict[str, Any] = dict(extra_body) if isinstance(extra_body, dict) else {}
                extra["metadata"] = metadata
                payload["extra_body"] = extra

        if not payload:
            return None, params
        return cast("ModelSettings", payload), params


def wrap_minimax_openai_native_model(
    model: Model,
    *,
    catalog_model_id: str,
    hygiene: MiniMaxHygieneContext,
) -> Model:
    """Return ``MiniMaxOpenAIWrapperModel`` for MiniMax catalog ids; passthrough otherwise.

    Args:
        model (Model): Native ``OpenAIChatModel`` built by :mod:`sevn.agent.adapters.native_model`.
        catalog_model_id (str): Workspace catalog model id.
        hygiene (MiniMaxHygieneContext): MiniMax request hygiene correlation fields.

    Returns:
        Model: Wrapped model for ``minimax/*``, unchanged for other catalog ids.

    Examples:
        >>> from pydantic_ai.models.function import FunctionModel
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> async def _noop(messages, info):
        ...     return ModelResponse(parts=[TextPart(content="ok")])
        >>> inner = FunctionModel(_noop, model_name="x")
        >>> same = wrap_minimax_openai_native_model(
        ...     inner,
        ...     catalog_model_id="anthropic/claude-haiku",
        ...     hygiene=MiniMaxHygieneContext(agent="tier_b"),
        ... )
        >>> same is inner
        True
    """
    if not is_minimax_catalog_model(catalog_model_id):
        return model
    return MiniMaxOpenAIWrapperModel(
        model,
        catalog_model_id=catalog_model_id,
        hygiene=hygiene,
    )


__all__ = [
    "MiniMaxHygieneContext",
    "MiniMaxOpenAIWrapperModel",
    "MiniMaxWrapperModel",
    "wrap_minimax_native_model",
    "wrap_minimax_openai_native_model",
]
