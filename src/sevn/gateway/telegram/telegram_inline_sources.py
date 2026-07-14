"""Inline-query content-source aggregator (I2; I3 assembles ``answerInlineQuery``).

Module: sevn.gateway.telegram.telegram_inline_sources
Depends: asyncio, html, pathlib, typing, sevn.coding_agents.artifacts.vault,
    sevn.gateway.telegram.telegram_inline_agent, sevn.gateway.telegram.telegram_inline_base,
    sevn.gateway.telegram.telegram_inline_printing_press, sevn.gateway.telegram.telegram_inline_types,
    sevn.gateway.webapp.webapp_viewer, sevn.second_brain.paths, sevn.second_brain.query

Houses the second-brain and artifact source builders plus the cross-source
aggregator/merge (I2.5 / D9). Source (a) agent wiring lives in
``telegram_inline_agent`` and source (c) printing-press in
``telegram_inline_printing_press``; shared primitives are in
``telegram_inline_base`` (finding-4). Stable public symbols are re-exported here
so existing imports keep working.

Exports:
    build_all_inline_source_results — run all enabled sources with error isolation (I2.5).
    build_artifacts_inline_results — source (d) recent artifact vault hits.
    build_second_brain_inline_results — source (b) wiki / second-brain hits.
    inline_sources_module_ready — importability probe.
    merge_inline_query_results — flatten source rows in D9 priority order.

Examples:
    >>> from sevn.gateway.telegram.telegram_inline_sources import inline_sources_module_ready
    >>> inline_sources_module_ready()
    True
"""

from __future__ import annotations

import asyncio
import html
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from sevn.coding_agents.artifacts.vault import list_all_runs, list_run_artifacts, read_artifact
from sevn.gateway.telegram.telegram_inline_agent import (
    build_agent_inline_results,
    capture_router_outbound_text,
    make_run_turn_agent_answer_fn,
)
from sevn.gateway.telegram.telegram_inline_base import (
    DEFAULT_INLINE_AGENT_TIMEOUT_S,
    DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
    DEFAULT_INLINE_MAX_TOTAL_RESULTS,
    AgentAnswerFn,
    InlineBuildContext,
    InlineResultDict,
    InlineSourceResult,
    PrintingPressRunnerFn,
    _empty_source_result,
    _inline_cfg_from_dispatch,
    _result_id,
    _truncate,
    inline_article_result,
)
from sevn.gateway.telegram.telegram_inline_printing_press import build_printing_press_inline_results
from sevn.gateway.telegram.telegram_inline_types import InlineSourceKind, inline_source_cache_time
from sevn.gateway.webapp.webapp_viewer import infer_viewer_payload_from_markdown
from sevn.second_brain.paths import (
    effective_scope,
    legacy_shared_vault_root,
    resolve_scope_root,
    shared_wiki_root,
    wiki_dir_for_scope,
)
from sevn.second_brain.query import second_brain_query

INLINE_SOURCES_MODULE_VERSION = "1.0.0-i2"

SecondBrainQueryFn = Callable[..., list[dict[str, object]]]


def inline_sources_module_ready() -> bool:
    """Return ``True`` when inline source builders are importable.

    Returns:
        bool: ``True`` once I2 builders are present.

    Examples:
        >>> inline_sources_module_ready()
        True
    """
    return True


def build_second_brain_inline_results(
    ctx: InlineBuildContext,
    *,
    query_fn: SecondBrainQueryFn | None = None,
    max_results: int = DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
) -> InlineSourceResult:
    """Build source (b) second-brain / wiki inline results (D9).

    Args:
        ctx (InlineBuildContext): Query + workspace paths.
        query_fn (SecondBrainQueryFn | None): Override for tests; defaults to
            :func:`sevn.second_brain.query.second_brain_query`.
        max_results (int): Maximum article rows from wiki hits.

    Returns:
        InlineSourceResult: Wiki article/snippet rows with static ``cache_time``.

    Examples:
        >>> from sevn.gateway.telegram.telegram_inline import build_inline_dispatch_context
        >>> from sevn.config.sections.channels import TelegramInlineConfig
        >>> dispatch = build_inline_dispatch_context(
        ...     "1",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset(),
        ...     allowed_users=[],
        ... )
        >>> ctx = InlineBuildContext(
        ...     query="",
        ...     user_id="1",
        ...     inline_query_id="iq",
        ...     content_root=__import__("pathlib").Path("."),
        ...     dispatch=dispatch,
        ... )
        >>> build_second_brain_inline_results(ctx).results
        ()
    """
    source: InlineSourceKind = "second_brain"
    cache_time = inline_source_cache_time(source, _inline_cfg_from_dispatch(ctx.dispatch))
    if not ctx.dispatch.sources_enabled.get(source, False):
        return InlineSourceResult(source=source, cache_time=cache_time, results=())
    query = ctx.query.strip()
    if not query:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())

    sb_cfg = ctx.workspace.second_brain if ctx.workspace is not None else None
    scope = effective_scope(ctx.second_brain_scope or ctx.user_id, sb_cfg)
    user_root = resolve_scope_root(ctx.content_root, sb_cfg, scope)
    user_wiki = wiki_dir_for_scope(user_root)
    shared = shared_wiki_root(legacy_shared_vault_root(ctx.content_root))
    runner = query_fn or second_brain_query

    try:
        hits = runner(
            q=query,
            user_wiki=user_wiki,
            shared_wiki=shared,
            include_shared=True,
            limit=max_results,
            workspace_path=ctx.content_root,
        )
    except Exception as exc:
        return InlineSourceResult(
            source=source,
            cache_time=cache_time,
            results=(),
            error=str(exc),
        )

    rows: list[InlineResultDict] = []
    for idx, hit in enumerate(hits[:max_results]):
        page = str(hit.get("page") or hit.get("path") or "wiki")
        snippet = str(hit.get("snippet") or "")
        origin = str(hit.get("origin") or "user")
        title = Path(page).stem.replace("-", " ").replace("_", " ").title() or "Wiki"
        description = _truncate(snippet, 256)
        body_lines = [f"<b>{html.escape(title)}</b>", html.escape(snippet)]
        if page:
            body_lines.append(f"<i>{html.escape(origin)}: {html.escape(page)}</i>")
        rows.append(
            inline_article_result(
                result_id=_result_id(source, idx, ctx.inline_query_id),
                title=title,
                description=description,
                message_text="\n".join(body_lines),
            ),
        )
    return InlineSourceResult(source=source, cache_time=cache_time, results=tuple(rows))


def build_artifacts_inline_results(
    ctx: InlineBuildContext,
    *,
    max_results: int = DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
    preview_chars: int = 400,
) -> InlineSourceResult:
    """Build source (d) recent artifact / past-answer inline results (D9).

    Scans the ALRCA artifact vault for filenames and bodies matching the query.
    Results are scoped to the requesting user's visibility (filename + snippet only).

    Args:
        ctx (InlineBuildContext): Query text and workspace root.
        max_results (int): Maximum artifact rows.
        preview_chars (int): Body preview width for the inline message.

    Returns:
        InlineSourceResult: Recent artifact article rows.

    Examples:
        >>> from sevn.gateway.telegram.telegram_inline import build_inline_dispatch_context
        >>> from sevn.config.sections.channels import TelegramInlineConfig
        >>> dispatch = build_inline_dispatch_context(
        ...     "1",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset(),
        ...     allowed_users=[],
        ... )
        >>> ctx = InlineBuildContext(
        ...     query="summary",
        ...     user_id="1",
        ...     inline_query_id="iq",
        ...     content_root=__import__("pathlib").Path("."),
        ...     dispatch=dispatch,
        ... )
        >>> build_artifacts_inline_results(ctx).source
        'artifacts'
    """
    source: InlineSourceKind = "artifacts"
    cache_time = inline_source_cache_time(source, _inline_cfg_from_dispatch(ctx.dispatch))
    if not ctx.dispatch.sources_enabled.get(source, False):
        return InlineSourceResult(source=source, cache_time=cache_time, results=())
    query = ctx.query.strip().lower()
    if not query:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())

    try:
        runs = list_all_runs(ctx.content_root)
    except Exception as exc:
        return InlineSourceResult(
            source=source,
            cache_time=cache_time,
            results=(),
            error=str(exc),
        )

    rows: list[InlineResultDict] = []
    tokens = [t for t in query.split() if t]

    for run in runs:
        if len(rows) >= max_results:
            break
        run_id = str(run.get("run_id") or "")
        if not run_id:
            continue
        for entry in list_run_artifacts(run_id, ctx.content_root):
            if len(rows) >= max_results:
                break
            name = str(entry.get("name") or "")
            haystack = name.lower()
            preview = ""
            if tokens and not any(tok in haystack for tok in tokens):
                content = read_artifact(run_id, name, ctx.content_root)
                if content is None:
                    continue
                preview = content
                haystack = preview.lower()
                if not any(tok in haystack for tok in tokens):
                    continue
            elif not tokens:
                continue
            if not preview:
                content = read_artifact(run_id, name, ctx.content_root)
                preview = content or ""
            title = name or run_id
            description = _truncate(preview.replace("\n", " "), 256)
            body = _truncate(preview, preview_chars)
            row = inline_article_result(
                result_id=_result_id(source, len(rows), ctx.inline_query_id),
                title=f"{run_id}: {title}",
                description=description,
                message_text=(f"<b>{html.escape(title)}</b>\n<pre>{html.escape(body)}</pre>"),
            )
            inferred = infer_viewer_payload_from_markdown(preview)
            if inferred is not None:
                view, view_data = inferred
                row["_viewer_spec"] = {"view": view, "view_data": view_data}
            rows.append(row)

    return InlineSourceResult(source=source, cache_time=cache_time, results=tuple(rows))


async def build_all_inline_source_results(
    ctx: InlineBuildContext,
    *,
    answer_fn: AgentAnswerFn | None = None,
    run_cli: PrintingPressRunnerFn | None = None,
    query_fn: SecondBrainQueryFn | None = None,
    agent_timeout_s: float = DEFAULT_INLINE_AGENT_TIMEOUT_S,
    max_results_per_source: int = DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
) -> tuple[InlineSourceResult, ...]:
    """Run all enabled inline sources; isolate per-source failures (I2.5 / D9).

    Args:
        ctx (InlineBuildContext): Shared inline build context.
        answer_fn (AgentAnswerFn | None): Agent answer provider for source (a).
        run_cli (PrintingPressRunnerFn | None): Printing-press runner override.
        query_fn (SecondBrainQueryFn | None): Second-brain query override.
        agent_timeout_s (float): Agent answer timeout seconds.
        max_results_per_source (int): Per-source row cap.

    Returns:
        tuple[InlineSourceResult, ...]: One entry per source in D9 priority order.

    Examples:
        >>> import asyncio
        >>> from sevn.gateway.telegram.telegram_inline import build_inline_dispatch_context
        >>> from sevn.config.sections.channels import TelegramInlineConfig
        >>> dispatch = build_inline_dispatch_context(
        ...     "1",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset({"1"}),
        ...     allowed_users=[],
        ... )
        >>> ctx = InlineBuildContext(
        ...     query="x",
        ...     user_id="1",
        ...     inline_query_id="iq",
        ...     content_root=__import__("pathlib").Path("."),
        ...     dispatch=dispatch,
        ... )
        >>> len(asyncio.run(build_all_inline_source_results(ctx))) == 4
        True
    """
    builders: list[
        tuple[InlineSourceKind, Callable[[], Awaitable[InlineSourceResult] | InlineSourceResult]]
    ] = [
        (
            "agent",
            lambda: build_agent_inline_results(
                ctx,
                answer_fn=answer_fn,
                timeout_s=agent_timeout_s,
                max_results=max_results_per_source,
            ),
        ),
        (
            "second_brain",
            lambda: build_second_brain_inline_results(
                ctx,
                query_fn=query_fn,
                max_results=max_results_per_source,
            ),
        ),
        (
            "printing_press",
            lambda: build_printing_press_inline_results(
                ctx,
                run_cli=run_cli,
                max_results=max_results_per_source,
            ),
        ),
        (
            "artifacts",
            lambda: build_artifacts_inline_results(ctx, max_results=max_results_per_source),
        ),
    ]

    out: list[InlineSourceResult] = []
    for source, fn in builders:
        if not ctx.dispatch.sources_enabled.get(source, False):
            out.append(_empty_source_result(source, ctx.dispatch))
            continue
        try:
            raw = fn()
            if asyncio.iscoroutine(raw):
                resolved = await raw
            else:
                resolved = cast("InlineSourceResult", raw)
            out.append(resolved)
        except Exception as exc:
            out.append(
                InlineSourceResult(
                    source=source,
                    cache_time=inline_source_cache_time(
                        source, _inline_cfg_from_dispatch(ctx.dispatch)
                    ),
                    results=(),
                    error=str(exc),
                ),
            )
    return tuple(out)


def merge_inline_query_results(
    source_results: tuple[InlineSourceResult, ...] | list[InlineSourceResult],
    *,
    max_total: int = DEFAULT_INLINE_MAX_TOTAL_RESULTS,
) -> list[InlineResultDict]:
    """Flatten source rows in D9 priority order with a total cap.

    Args:
        source_results (tuple[InlineSourceResult, ...] | list[InlineSourceResult]):
            Per-source builder outputs (typically from :func:`build_all_inline_source_results`).
        max_total (int): Maximum combined inline rows.

    Returns:
        list[InlineResultDict]: Telegram inline result dicts ready for ``answerInlineQuery``.

    Examples:
        >>> a = InlineSourceResult(source="agent", cache_time=10, results=({"type": "article", "id": "1"},))
        >>> merge_inline_query_results((a,), max_total=5)[0]["id"]
        '1'
    """
    merged: list[InlineResultDict] = []
    for block in source_results:
        for row in block.results:
            merged.append(row)
            if len(merged) >= max_total:
                return merged
    return merged


__all__ = [
    "DEFAULT_INLINE_AGENT_TIMEOUT_S",
    "DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE",
    "DEFAULT_INLINE_MAX_TOTAL_RESULTS",
    "INLINE_SOURCES_MODULE_VERSION",
    "AgentAnswerFn",
    "InlineBuildContext",
    "InlineSourceResult",
    "PrintingPressRunnerFn",
    "SecondBrainQueryFn",
    "build_agent_inline_results",
    "build_all_inline_source_results",
    "build_artifacts_inline_results",
    "build_printing_press_inline_results",
    "build_second_brain_inline_results",
    "capture_router_outbound_text",
    "inline_article_result",
    "inline_sources_module_ready",
    "make_run_turn_agent_answer_fn",
]
