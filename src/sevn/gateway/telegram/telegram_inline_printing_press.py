"""Inline source (c): printing-press CLI cards (I2; D9).

Module: sevn.gateway.telegram.telegram_inline_printing_press
Depends: functools, html, importlib.util, json, pathlib, typing,
    sevn.gateway.telegram.telegram_inline_base, sevn.gateway.telegram.telegram_inline_types

Splits the printing-press source builder out of ``telegram_inline_sources``
(finding-4): keyword routing, the bundled ``_pp_cli`` loader, and payload
formatting now live beside :func:`build_printing_press_inline_results`.

Exports:
    build_printing_press_inline_results — source (c) printing-press cards.

Examples:
    >>> "movie_goat" in _printing_press_slugs("best movie tonight")
    True
"""

from __future__ import annotations

import html
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from sevn.gateway.telegram.telegram_inline_base import (
    DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
    InlineBuildContext,
    InlineResultDict,
    InlineSourceResult,
    PrintingPressRunnerFn,
    _inline_cfg_from_dispatch,
    _result_id,
    _truncate,
    inline_article_result,
)
from sevn.gateway.telegram.telegram_inline_types import InlineSourceKind, inline_source_cache_time

INLINE_PP_CLI_TIMEOUT_S = 30.0

_PRINTING_PRESS_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("recipe", "cook", "ingredient", "nutrition", "meal", "pantry"), "recipe_goat"),
    (("movie", "film", "watch", "stream", "imdb", "tmdb"), "movie_goat"),
    (
        ("nfl", "nba", "mlb", "nhl", "score", "standings", "espn", "game", "team"),
        "espn",
    ),
    (("flight", "airline", "airport", "fly", "fare", "kayak"), "flight_goat"),
)


@lru_cache(maxsize=1)
def _default_printing_press_runner() -> PrintingPressRunnerFn:
    """Load and cache the bundled printing-press ``run_pp_cli`` helper.

    Returns:
        PrintingPressRunnerFn: Callable ``(slug, argv, timeout) -> envelope dict``.

    Examples:
        >>> _default_printing_press_runner() is _default_printing_press_runner()
        True
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "data/bundled_skills/core/printing-press-library/scripts/_pp_cli.py"
    )
    spec = importlib.util.spec_from_file_location("sevn_inline_pp_cli", path)
    if spec is None or spec.loader is None:
        msg = f"printing-press CLI loader unavailable: {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_pp_cli = module.run_pp_cli

    def _runner(slug: str, argv: list[str], timeout: float) -> dict[str, Any]:
        return cast("dict[str, Any]", run_pp_cli(slug, argv, timeout=timeout))

    return _runner


def _printing_press_slugs(query: str) -> list[str]:
    """Return printing-press CLI slugs matching keyword hints in ``query``.

    Args:
        query (str): Inline query text.

    Returns:
        list[str]: Ordered slugs such as ``recipe_goat`` or ``espn``.

    Examples:
        >>> "movie_goat" in _printing_press_slugs("best movie tonight")
        True
    """
    q = query.lower().strip()
    if not q:
        return []
    matched: list[str] = []
    for keywords, slug in _PRINTING_PRESS_KEYWORDS:
        if any(word in q for word in keywords):
            matched.append(slug)
    return matched


def _format_printing_press_payload(slug: str, data: Any) -> tuple[str, str, str]:
    """Map printing-press JSON payload to inline card title, description, and body.

    Args:
        slug (str): Printing-press function slug.
        data (Any): Parsed CLI JSON payload.

    Returns:
        tuple[str, str, str]: ``(title, description, message_body)``.

    Examples:
        >>> title, desc, _body = _format_printing_press_payload(
        ...     "espn", {"title": "Scores", "summary": "Live"}
        ... )
        >>> (title, desc)
        ('Scores', 'Live')
    """
    if isinstance(data, dict):
        title = str(
            data.get("title")
            or data.get("name")
            or data.get("headline")
            or slug.replace("_", " ").title(),
        )
        description = str(
            data.get("summary") or data.get("description") or data.get("subtitle") or "",
        )
        if not description and isinstance(data.get("items"), list):
            description = f"{len(data['items'])} result(s)"
        body_obj = data.get("text") or data.get("body") or data
        if isinstance(body_obj, str):
            body = body_obj
        else:
            body = json.dumps(body_obj, indent=2, ensure_ascii=False)
    elif isinstance(data, list):
        title = slug.replace("_", " ").title()
        description = f"{len(data)} result(s)"
        body = json.dumps(data, indent=2, ensure_ascii=False)
    else:
        title = slug.replace("_", " ").title()
        description = ""
        body = str(data)
    return title, description, body


def build_printing_press_inline_results(
    ctx: InlineBuildContext,
    *,
    run_cli: PrintingPressRunnerFn | None = None,
    max_results: int = DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
    cli_timeout_s: float = INLINE_PP_CLI_TIMEOUT_S,
) -> InlineSourceResult:
    """Build source (c) printing-press inline results (D9).

    Args:
        ctx (InlineBuildContext): Inline query text and dispatch toggles.
        run_cli (PrintingPressRunnerFn | None): CLI runner override for tests.
        max_results (int): Maximum combined rows across matched CLIs.
        cli_timeout_s (float): Subprocess timeout per CLI invocation.

    Returns:
        InlineSourceResult: Recipe/movie/sports/flight cards with long ``cache_time``.

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
        ...     query="movie dune",
        ...     user_id="1",
        ...     inline_query_id="iq",
        ...     content_root=__import__("pathlib").Path("."),
        ...     dispatch=dispatch,
        ... )
        >>> out = build_printing_press_inline_results(ctx, run_cli=lambda *_a, **_k: {"ok": False})
        >>> out.source
        'printing_press'
    """
    source: InlineSourceKind = "printing_press"
    cache_time = inline_source_cache_time(source, _inline_cfg_from_dispatch(ctx.dispatch))
    if not ctx.dispatch.sources_enabled.get(source, False):
        return InlineSourceResult(source=source, cache_time=cache_time, results=())
    query = ctx.query.strip()
    if not query:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())

    slugs = _printing_press_slugs(query)
    if not slugs:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())

    runner = run_cli or _default_printing_press_runner()
    rows: list[InlineResultDict] = []
    errors: list[str] = []

    for slug in slugs:
        if len(rows) >= max_results:
            break
        try:
            envelope = runner(slug, [query], cli_timeout_s)
        except Exception as exc:
            errors.append(f"{slug}: {exc}")
            continue
        if not envelope.get("ok"):
            errors.append(str(envelope.get("error") or slug))
            continue
        title, description, body = _format_printing_press_payload(slug, envelope.get("data"))
        rows.append(
            inline_article_result(
                result_id=_result_id(source, len(rows), ctx.inline_query_id),
                title=title,
                description=_truncate(description, 256),
                message_text=f"<pre>{html.escape(_truncate(body, 3800))}</pre>",
            ),
        )

    error = "; ".join(errors) if errors and not rows else None
    return InlineSourceResult(
        source=source,
        cache_time=cache_time,
        results=tuple(rows[:max_results]),
        error=error,
    )


__all__ = ["build_printing_press_inline_results"]
