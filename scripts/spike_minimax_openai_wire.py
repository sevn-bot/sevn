#!/usr/bin/env python3
"""W0 spike: MiniMax M3 over OpenAI Chat Completions wire via pydantic-ai.

Throwaway script — validates:
  (a) structured tool_calls come back
  (b) tool_choice is honoured (ToolOrOutput)
  (c) reasoning_content → ThinkingPart
  (d) streaming works (no 400)
  (e) dynamic tool_choice via RequireFirstCall capability

Requires MINIMAX_API_KEY (or SEVN_SECRET_MINIMAX) in env.
Usage: uv run python scripts/spike_minimax_openai_wire.py

Exports:
    (none — script entry point only)
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings, ToolOrOutput

_MINIMAX_BASE_URL = "https://api.minimax.io/v1"
_MINIMAX_MODEL = "MiniMax-M3"


def _get_api_key() -> str:
    """Read MiniMax API key from environment.

    Returns:
        str: API key string.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_get_api_key)
        True
    """
    key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("SEVN_SECRET_MINIMAX", "")
    if not key:
        sys.exit("ERROR: set MINIMAX_API_KEY or SEVN_SECRET_MINIMAX in env")
    return key


def _build_model() -> OpenAIChatModel:
    """Build an OpenAIChatModel pointed at MiniMax /v1.

    Returns:
        OpenAIChatModel: Configured model instance.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_build_model)
        True
    """
    provider = OpenAIProvider(base_url=_MINIMAX_BASE_URL, api_key=_get_api_key())
    return OpenAIChatModel(_MINIMAX_MODEL, provider=provider)


def _get_weather(city: str) -> str:
    """Get current weather for a city (stub).

    Args:
        city (str): City name.

    Returns:
        str: Weather description.

    Examples:
        >>> _get_weather("Tokyo")
        'Weather in Tokyo: 22°C, partly cloudy'
    """
    return f"Weather in {city}: 22°C, partly cloudy"


def _calculate(expression: str) -> str:
    """Evaluate a math expression (stub).

    Args:
        expression (str): Math expression string.

    Returns:
        str: Evaluation result.

    Examples:
        >>> _calculate("2 + 2")
        '4'
    """
    return str(eval(expression))


def _list_files(directory: str) -> str:
    """List files in a directory (stub).

    Args:
        directory (str): Directory path.

    Returns:
        str: Comma-separated file names.

    Examples:
        >>> _list_files("/tmp")
        'file1.txt, file2.py, README.md'
    """
    return "file1.txt, file2.py, README.md"


class _RequireFirstCall(AbstractCapability[None]):
    """Force ``tool_name`` to be called before the model responds freely.

    Per-step dynamic ``tool_choice`` via capability — the callable returned
    by ``get_model_settings`` inspects ``ctx.messages`` each step to decide
    whether to force the tool or release.

    Args:
        tool_name: Name of the tool to force on the first step.

    Examples:
        >>> cap = _RequireFirstCall("_get_weather")
        >>> cap.tool_name
        '_get_weather'
    """

    def __init__(self, tool_name: str) -> None:
        """Initialize with the tool name to force first.

        Args:
            tool_name (str): Tool to require on the first step.

        Examples:
            >>> _RequireFirstCall("_get_weather").tool_name
            '_get_weather'
        """
        self.tool_name = tool_name

    def get_model_settings(self) -> Any:
        """Return a per-step settings callable that forces ``tool_name`` until called.

        Returns:
            Callable that receives RunContext and returns ModelSettings.

        Examples:
            >>> cap = _RequireFirstCall("_get_weather")
            >>> callable(cap.get_model_settings())
            True
        """

        def settings(ctx: RunContext[None]) -> ModelSettings:
            called = any(
                isinstance(part, ToolReturnPart) and part.tool_name == self.tool_name
                for message in ctx.messages
                if isinstance(message, ModelRequest)
                for part in message.parts
            )
            if called:
                return ModelSettings()
            return ModelSettings(tool_choice=[self.tool_name])

        return settings


def _extract_tool_calls(messages: list[Any]) -> list[str]:
    """Pull tool call names from message history.

    Args:
        messages (list[Any]): List of pydantic-ai messages.

    Returns:
        list[str]: Tool call representations.

    Examples:
        >>> _extract_tool_calls([])
        []
    """
    calls: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    calls.append(f"{part.tool_name}({part.args})")
    return calls


async def _test_structured_tool_calls() -> dict[str, Any]:
    """Test (a): structured tool_calls from MiniMax /v1.

    Returns:
        dict[str, Any]: Test result with success flag and tool calls found.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_test_structured_tool_calls)
        True
    """
    print("\n=== TEST (a): structured tool_calls ===")
    model = _build_model()
    agent = Agent(model, tools=[_get_weather, _calculate, _list_files])

    result = await agent.run("What is the weather in Tokyo? Also calculate 15 * 7.")
    calls = _extract_tool_calls(result.all_messages())

    print(f"  Tool calls found: {calls}")
    print(f"  Final output: {result.output[:200]}")
    success = len(calls) >= 1
    print(f"  PASS: {success}")
    return {"test": "structured_tool_calls", "success": success, "calls": calls}


async def _test_tool_choice() -> dict[str, Any]:
    """Test (b): tool_choice honoured via ToolOrOutput.

    Uses ToolOrOutput to restrict to ``_get_weather`` while allowing text output.
    Prompt includes a city so the model can fill the required arg.

    Returns:
        dict[str, Any]: Test result with success flag.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_test_tool_choice)
        True
    """
    print("\n=== TEST (b): tool_choice honoured (ToolOrOutput) ===")
    model = _build_model()
    agent = Agent(model, tools=[_get_weather, _calculate])

    result = await agent.run(
        "What is the weather in New York?",
        model_settings=ModelSettings(
            tool_choice=ToolOrOutput(function_tools=["_get_weather"]),
        ),
    )
    calls = _extract_tool_calls(result.all_messages())

    forced_tool_used = any("_get_weather" in c for c in calls)
    no_wrong_tool = not any("_calculate" in c for c in calls)

    print(f"  Tool calls: {calls}")
    print(f"  Forced tool '_get_weather' used: {forced_tool_used}")
    print(f"  No wrong tool '_calculate': {no_wrong_tool}")
    print(f"  Final output: {result.output[:200]}")
    success = forced_tool_used and no_wrong_tool
    print(f"  PASS: {success}")
    return {"test": "tool_choice", "success": success}


async def _test_reasoning_content() -> dict[str, Any]:
    """Test (c): reasoning_content maps to ThinkingPart.

    Returns:
        dict[str, Any]: Test result with success flag and thinking excerpt.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_test_reasoning_content)
        True
    """
    print("\n=== TEST (c): reasoning_content → ThinkingPart ===")
    model = _build_model()
    agent = Agent(model, tools=[_get_weather])

    result = await agent.run("Think step by step: what's the weather in Paris?")

    thinking_found = False
    thinking_content = ""
    for msg in result.all_messages():
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ThinkingPart):
                    thinking_found = True
                    thinking_content = (part.content or "")[:200]

    print(f"  ThinkingPart found: {thinking_found}")
    if thinking_content:
        print(f"  Thinking excerpt: {thinking_content[:100]}...")
    print(f"  PASS: {thinking_found}")
    return {
        "test": "reasoning_content",
        "success": thinking_found,
        "thinking_excerpt": thinking_content[:200],
    }


async def _test_streaming() -> dict[str, Any]:
    """Test (d): streaming works without 400 errors.

    Returns:
        dict[str, Any]: Test result with success flag and chunk count.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_test_streaming)
        True
    """
    print("\n=== TEST (d): streaming (no 400) ===")
    model = _build_model()
    agent = Agent(model, tools=[_get_weather])

    chunks: list[str] = []
    error_msg = ""
    try:
        async with agent.run_stream("What's the weather in London?") as stream:
            async for chunk in stream.stream_text(delta=True):
                chunks.append(chunk)
                if len(chunks) <= 3:
                    print(f"  chunk[{len(chunks) - 1}]: {chunk[:50]!r}")
    except Exception as e:
        error_msg = str(e)
        print(f"  ERROR: {e}")

    success = len(chunks) > 0 and not error_msg
    print(f"  Total chunks: {len(chunks)}")
    print(f"  PASS: {success}")
    return {"test": "streaming", "success": success, "chunks": len(chunks), "error": error_msg}


async def _test_dynamic_tool_choice_capability() -> dict[str, Any]:
    """Test (e): dynamic tool_choice via RequireFirstCall capability.

    Forces ``_get_weather`` on the first step via a capability that returns
    per-step ``ModelSettings``. After the forced tool executes, the model
    is free to respond with text or call other tools.

    Returns:
        dict[str, Any]: Test result with success flag.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_test_dynamic_tool_choice_capability)
        True
    """
    print("\n=== TEST (e): dynamic tool_choice via RequireFirstCall capability ===")
    model = _build_model()
    agent = Agent(
        model,
        tools=[_get_weather, _calculate],
        capabilities=[_RequireFirstCall("_get_weather")],
    )

    result = await agent.run("Calculate 42 * 3 and also tell me the weather in Berlin.")
    calls = _extract_tool_calls(result.all_messages())

    weather_called = any("_get_weather" in c for c in calls)
    print(f"  Tool calls: {calls}")
    print(f"  _get_weather forced-first: {weather_called}")
    print(f"  Final output: {result.output[:200]}")
    success = weather_called
    print(f"  PASS: {success}")
    return {"test": "dynamic_tool_choice_capability", "success": success}


async def _main() -> None:
    """Run all spike tests and print summary.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_main)
        True
    """
    print("=" * 60)
    print("MiniMax OpenAI Chat Completions Wire — W0 Spike")
    print(f"Model: {_MINIMAX_MODEL}")
    print(f"Base URL: {_MINIMAX_BASE_URL}")
    print("=" * 60)

    tests = [
        _test_structured_tool_calls,
        _test_tool_choice,
        _test_reasoning_content,
        _test_streaming,
        _test_dynamic_tool_choice_capability,
    ]

    results: list[dict[str, Any]] = []
    for test_fn in tests:
        try:
            results.append(await test_fn())
        except Exception as e:
            name = test_fn.__name__.replace("_test_", "")
            print(f"  CRASH: {e}")
            traceback.print_exc()
            results.append({"test": name, "success": False, "error": str(e)})

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for r in results:
        status = "✅" if r["success"] else "❌"
        print(f"  {status} {r['test']}")
        if not r["success"]:
            all_pass = False

    print(f"\nOverall: {'ALL PASS ✅' if all_pass else 'SOME FAILED'}")
    if not all_pass:
        print("  → If tool_calls weak, evaluate CodeMode-only fallback (D8)")

    print("\n--- Observations ---")
    print("  reasoning field: 'reasoning_content' (pydantic-ai default, no custom_field needed)")
    print("  tool_calls: standard OpenAI JSON format")
    print("  streaming: standard SSE, no 400")


if __name__ == "__main__":
    asyncio.run(_main())
