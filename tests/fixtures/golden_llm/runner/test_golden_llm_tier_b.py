"""Golden LLM tier-B corpus runner (`pytest -m golden_llm`, W11).

Replay tests run tokenlessly in default ``make test``. Live record tests require
``SEVN_GOLDEN_LLM=1`` and carry the ``golden_llm`` marker.
"""

from __future__ import annotations

import pytest

from tests.fixtures.golden_llm.harness import (
    assert_golden_outcome,
    cases_to_dataset,
    discover_cases,
    golden_llm_live_enabled,
    load_recording,
    prepare_workspace,
    run_golden_case_replay,
)


def test_all_case_files_validate() -> None:
    """Every ``cases/*/*.json`` file loads through the golden schema."""
    cases = discover_cases()
    assert len(cases) >= 20
    categories = {c.category for c in cases}
    assert categories >= {"tools", "skills", "input", "codemode"}


def test_cases_to_dataset_bridge() -> None:
    """Cases convert into a pydantic-evals Dataset (W12 prep)."""
    dataset = cases_to_dataset(discover_cases(category="tools")[:3])
    assert len(dataset.cases) == 3
    assert dataset.cases[0].inputs


@pytest.mark.parametrize("case_id", [c.id for c in discover_cases()])
@pytest.mark.asyncio
async def test_golden_llm_replays_recorded_case_tokenless(
    case_id: str,
    tmp_path,
) -> None:
    """Each recorded case replays without ``SEVN_GOLDEN_LLM`` or live keys."""
    cases = {c.id: c for c in discover_cases()}
    case = cases[case_id]
    recording = load_recording(case)
    assert recording is not None, f"missing recording for {case_id}"
    root = prepare_workspace(tmp_path, case)
    outcome = await run_golden_case_replay(case, root, recording, turn_id=f"replay-{case_id}")
    if case.assertions.tool_success:
        assert outcome.status == "completed"
    else:
        assert outcome.status == "failed"
    assert_golden_outcome(case, outcome, recording=recording)


@pytest.mark.asyncio
async def test_golden_llm_inline_files_no_deployed_workspace(tmp_path) -> None:
    """Inline workspace files run without a pre-deployed operator workspace."""
    cases = {c.id: c for c in discover_cases(category="tools")}
    case = cases["read_01"]
    assert case.workspace.inline_files
    recording = load_recording(case)
    assert recording is not None
    root = prepare_workspace(tmp_path, case)
    assert (root / "hello.txt").read_text() == "hello world\n"
    outcome = await run_golden_case_replay(case, root, recording)
    assert outcome.status == "completed"
    assert_golden_outcome(case, outcome, recording=recording)


@pytest.mark.golden_llm
@pytest.mark.skipif(not golden_llm_live_enabled(), reason="SEVN_GOLDEN_LLM=1 required")
@pytest.mark.asyncio
async def test_golden_llm_live_record_when_enabled(tmp_path) -> None:
    """Opt-in live record path (skipped in default CI)."""
    pytest.skip("live transport wiring lands in W12; replay is the W11 CI gate")


def test_golden_llm_marker_registered() -> None:
    """``golden_llm`` marker is registered for ``pytest -m golden_llm`` selection."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads((Path("pyproject.toml")).read_text(encoding="utf-8"))
    markers = {
        m.split(":")[0].strip().strip('"') for m in data["tool"]["pytest"]["ini_options"]["markers"]
    }
    assert "golden_llm" in markers
