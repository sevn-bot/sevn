"""First-round bound-toolset enforcement filter (provider-agnostic).

Covers `bound_tools_only_first_round`: on the first tier-B round the model may only
see the triager-bound toolset; from the second round the full toolset is exposed.
The filter lives at the pydantic-ai toolset layer, so it applies to every model and
provider (Anthropic, OpenAI, MiniMax, …), not just one wire format.
"""

from __future__ import annotations

from types import SimpleNamespace

from sevn.agent.adapters.tier_b_toolset import bound_tools_only_first_round

_ALLOWED = frozenset({"serp", "request_escalation"})


def _ctx(run_step: int) -> SimpleNamespace:
    return SimpleNamespace(run_step=run_step)


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_first_round_allows_bound_tool() -> None:
    f = bound_tools_only_first_round(_ALLOWED)
    assert f(_ctx(1), _tool("serp")) is True


def test_first_round_allows_request_escalation() -> None:
    f = bound_tools_only_first_round(_ALLOWED)
    assert f(_ctx(1), _tool("request_escalation")) is True


def test_first_round_hides_meta_tools() -> None:
    f = bound_tools_only_first_round(_ALLOWED)
    for meta in ("run_skill_script", "run_code", "list_registry", "load_tool"):
        assert f(_ctx(1), _tool(meta)) is False, meta


def test_second_round_exposes_everything() -> None:
    f = bound_tools_only_first_round(_ALLOWED)
    assert f(_ctx(2), _tool("run_skill_script")) is True
    assert f(_ctx(2), _tool("load_tool")) is True


def test_later_rounds_stay_open() -> None:
    f = bound_tools_only_first_round(_ALLOWED)
    assert f(_ctx(9), _tool("anything")) is True


def test_codemode_run_code_allowed_first_round_when_bound() -> None:
    # When CodeMode is on the harness adds run_code to the allowed set.
    f = bound_tools_only_first_round(_ALLOWED | frozenset({"run_code"}))
    assert f(_ctx(1), _tool("run_code")) is True


def test_filter_applies_via_function_toolset_filtered() -> None:
    """`.filtered()` accepts the predicate and yields a wrapping toolset."""
    from pydantic_ai.toolsets import FunctionToolset

    ts = FunctionToolset()
    wrapped = ts.filtered(bound_tools_only_first_round(_ALLOWED))
    assert hasattr(wrapped, "call_tool")  # dispatch delegates to the inner toolset
