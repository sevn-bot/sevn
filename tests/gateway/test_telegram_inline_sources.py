"""Telegram inline content-source builder tests (I2.1-I2.5)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sevn.coding_agents.artifacts.vault import write_artifact
from sevn.config.sections.channels import TelegramInlineConfig, TelegramInlineSourcesConfig
from sevn.gateway.telegram.telegram_inline import build_inline_dispatch_context
from sevn.gateway.telegram.telegram_inline_sources import (
    InlineBuildContext,
    InlineSourceResult,
    build_agent_inline_results,
    build_all_inline_source_results,
    build_artifacts_inline_results,
    build_printing_press_inline_results,
    build_second_brain_inline_results,
    capture_router_outbound_text,
    inline_article_result,
    make_run_turn_agent_answer_fn,
    merge_inline_query_results,
)


def _ctx(
    tmp_path: Path,
    *,
    query: str = "weather today",
    user_id: str = "42",
    owner: bool = False,
    sources: TelegramInlineSourcesConfig | None = None,
) -> InlineBuildContext:
    inline_cfg = TelegramInlineConfig(
        enabled=True,
        sources=sources or TelegramInlineSourcesConfig(),
    )
    owner_ids = frozenset({user_id}) if owner else frozenset({"99"})
    dispatch = build_inline_dispatch_context(
        user_id,
        inline_cfg=inline_cfg,
        owner_ids=owner_ids,
        allowed_users=[],
    )
    return InlineBuildContext(
        query=query,
        user_id=user_id,
        inline_query_id="iq-test-1",
        content_root=tmp_path,
        dispatch=dispatch,
    )


@pytest.mark.asyncio
async def test_agent_source_blocked_for_non_owner(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, owner=False)

    async def _answer(_q: str) -> str:
        return "should not run"

    out = await build_agent_inline_results(ctx, answer_fn=_answer)
    assert out.results == ()
    assert out.source == "agent"


@pytest.mark.asyncio
async def test_agent_source_returns_answer_for_owner(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, owner=True, query="capital of france")

    async def _answer(q: str) -> str:
        assert q == "capital of france"
        return "Paris is the capital of France."

    out = await build_agent_inline_results(ctx, answer_fn=_answer)
    assert len(out.results) == 1
    row = out.results[0]
    assert row["type"] == "article"
    assert "Paris" in row["title"]
    assert out.cache_time == ctx.dispatch.cache_time_agent


@pytest.mark.asyncio
async def test_agent_source_timeout_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, owner=True)

    async def _slow(_q: str) -> str:
        await asyncio.sleep(0.05)
        return "late"

    out = await build_agent_inline_results(ctx, answer_fn=_slow, timeout_s=0.001)
    assert out.results == ()
    assert out.error is not None
    assert "timed out" in out.error


def test_second_brain_maps_hits(tmp_path: Path) -> None:
    wiki = tmp_path / "second_brain" / "users" / "42" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "notes.md").write_text("# Notes\nweather forecast details\n", encoding="utf-8")

    ctx = _ctx(tmp_path, query="weather", user_id="42")

    def _fake_query(**kwargs: Any) -> list[dict[str, object]]:
        return [
            {
                "page": "notes.md",
                "snippet": "weather forecast details",
                "origin": "user",
            },
        ]

    out = build_second_brain_inline_results(ctx, query_fn=_fake_query)
    assert len(out.results) == 1
    assert out.results[0]["title"] == "Notes"
    assert "forecast" in out.results[0]["description"]


def test_second_brain_error_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, query="x")

    def _boom(**_kwargs: Any) -> list[dict[str, object]]:
        msg = "wiki offline"
        raise RuntimeError(msg)

    out = build_second_brain_inline_results(ctx, query_fn=_boom)
    assert out.results == ()
    assert out.error == "wiki offline"


def test_printing_press_routes_movie_intent(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, query="movie dune streaming")

    def _runner(slug: str, argv: list[str], _timeout: float) -> dict[str, Any]:
        assert slug == "movie_goat"
        assert argv == ["movie dune streaming"]
        return {"ok": True, "data": {"title": "Dune", "summary": "Sci-fi epic"}}

    out = build_printing_press_inline_results(ctx, run_cli=_runner)
    assert len(out.results) == 1
    assert out.results[0]["title"] == "Dune"
    assert out.cache_time == ctx.dispatch.cache_time_static


def test_printing_press_binary_missing_yields_no_rows(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, query="recipe pasta")

    def _missing(_slug: str, _argv: list[str], _timeout: float) -> dict[str, Any]:
        return {"ok": False, "code": "BINARY_MISSING", "error": "not on PATH"}

    out = build_printing_press_inline_results(ctx, run_cli=_missing)
    assert out.results == ()
    assert out.error is not None


def test_artifacts_search_matches_filename_and_body(tmp_path: Path) -> None:
    write_artifact("run-a", "summary.md", "# Summary\nweather report\n", tmp_path)
    write_artifact("run-b", "other.txt", "unrelated\n", tmp_path)
    ctx = _ctx(tmp_path, query="weather")

    out = build_artifacts_inline_results(ctx)
    assert len(out.results) == 1
    assert "summary.md" in out.results[0]["title"]
    assert "weather" in out.results[0]["description"].lower()


def test_artifacts_vault_read_error_isolated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, query="x")

    def _boom(_path: Path) -> list[dict[str, Any]]:
        msg = "vault unavailable"
        raise OSError(msg)

    import sevn.gateway.telegram.telegram_inline_sources as mod

    original = mod.list_all_runs
    mod.list_all_runs = _boom  # type: ignore[assignment]
    try:
        out = build_artifacts_inline_results(ctx)
    finally:
        mod.list_all_runs = original

    assert out.results == ()
    assert out.error == "vault unavailable"


@pytest.mark.asyncio
async def test_build_all_isolates_one_failing_source(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, owner=True, query="recipe chicken")

    async def _answer(q: str) -> str:
        return f"agent: {q}"

    def _wiki(**_kwargs: Any) -> list[dict[str, object]]:
        msg = "second brain down"
        raise RuntimeError(msg)

    def _pp(slug: str, argv: list[str], _timeout: float) -> dict[str, Any]:
        return {"ok": True, "data": {"title": slug, "text": " ".join(argv)}}

    write_artifact("run-1", "notes.md", "recipe chicken soup", tmp_path)

    blocks = await build_all_inline_source_results(
        ctx,
        answer_fn=_answer,
        query_fn=_wiki,
        run_cli=_pp,
    )
    assert len(blocks) == 4
    by_source = {b.source: b for b in blocks}
    assert len(by_source["agent"].results) == 1
    assert by_source["second_brain"].results == ()
    assert by_source["second_brain"].error == "second brain down"
    assert len(by_source["printing_press"].results) == 1
    assert len(by_source["artifacts"].results) >= 1


def test_merge_caps_total_results() -> None:
    rows = tuple(
        inline_article_result(
            result_id=f"id-{i}",
            title=f"t{i}",
            description="d",
            message_text=f"body {i}",
        )
        for i in range(5)
    )
    blocks = (
        InlineSourceResult(source="agent", cache_time=10, results=rows[:2]),
        InlineSourceResult(source="second_brain", cache_time=300, results=rows[2:]),
    )
    merged = merge_inline_query_results(blocks, max_total=3)
    assert len(merged) == 3
    assert [r["id"] for r in merged] == ["id-0", "id-1", "id-2"]


def test_disabled_source_returns_empty_block(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        sources=TelegramInlineSourcesConfig(agent=False, second_brain=False),
    )
    out = build_second_brain_inline_results(ctx)
    assert out.results == ()


@pytest.mark.asyncio
async def test_build_all_respects_disabled_sources(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        owner=True,
        sources=TelegramInlineSourcesConfig(
            agent=True,
            second_brain=False,
            printing_press=False,
            artifacts=False,
        ),
    )

    async def _answer(_q: str) -> str:
        return "ok"

    blocks = await build_all_inline_source_results(ctx, answer_fn=_answer)
    assert len(blocks) == 4
    assert len(blocks[0].results) == 1
    assert all(len(b.results) == 0 for b in blocks[1:])


@dataclass
class _CaptureMsg:
    text: str


class _CaptureRouter:
    """Minimal router stand-in for ``capture_router_outbound_text`` tests."""

    def __init__(self) -> None:
        self.route_outgoing_calls: list[str] = []

    async def route_outgoing(self, msg: object) -> None:
        text = getattr(msg, "text", None)
        if isinstance(text, str):
            self.route_outgoing_calls.append(text)


@pytest.mark.asyncio
async def test_concurrent_capture_router_outbound_text_isolated() -> None:
    """W7: parallel captures must not cross-contaminate outbound text (finding-7)."""
    router = _CaptureRouter()
    gate = asyncio.Event()

    async def _emit(label: str, delay: float) -> None:
        await gate.wait()
        await asyncio.sleep(delay)
        await router.route_outgoing(_CaptureMsg(label))

    async def _run(label: str, delay: float) -> str | None:
        return await capture_router_outbound_text(router, _emit(label, delay))

    tasks = [
        asyncio.create_task(_run("capture-alpha", 0.03)),
        asyncio.create_task(_run("capture-beta", 0.01)),
    ]
    gate.set()
    alpha, beta = await asyncio.gather(*tasks)
    assert {alpha, beta} == {"capture-alpha", "capture-beta"}


@pytest.mark.asyncio
async def test_build_agent_inline_results_honors_max_results_zero(tmp_path: Path) -> None:
    """W7: ``max_results=0`` must suppress agent rows (finding-14)."""
    ctx = _ctx(tmp_path, owner=True, query="hello")

    async def _answer(_q: str) -> str:
        return "Agent answer body"

    out = await build_agent_inline_results(ctx, answer_fn=_answer, max_results=0)
    assert out.results == ()


@pytest.mark.asyncio
async def test_build_agent_inline_results_honors_max_results_cap(tmp_path: Path) -> None:
    """W7: ``max_results`` caps agent article rows (finding-14)."""
    ctx = _ctx(tmp_path, owner=True, query="hello")

    async def _answer(_q: str) -> str:
        return "Agent answer body"

    out = await build_agent_inline_results(ctx, answer_fn=_answer, max_results=1)
    assert len(out.results) == 1


def test_smoke_make_run_turn_agent_answer_fn_importable() -> None:
    """W7: agent answer factory remains importable from inline sources surface."""
    assert callable(make_run_turn_agent_answer_fn)
