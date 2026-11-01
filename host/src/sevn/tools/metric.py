"""``metric.report``: a bot reports a number the owner tracks."""

from __future__ import annotations

from sevn.domain.errors import DomainError
from sevn.domain.metrics import report
from sevn.tools.registry import TurnDeps, register_toolset


def metric_toolset(deps: TurnDeps) -> dict[str, object]:
    """The metric tool for one turn."""

    async def report_metric(
        key: str,
        value: float | None,
        source: str,
        unit: str = "",
        label: str = "",
        as_of: str | None = None,
        freshness_minutes: int = 1440,
        shareable: bool = True,
    ) -> str:
        """Report the current value of a number the owner tracks.

        ``key`` is a short id such as ``subscribers``. ``source`` says where
        the value came from (an API, a page, a query). Report ``value`` null
        when the read failed; never guess a number. ``as_of`` is when the value
        was true (ISO 8601 with a timezone, default now). After
        ``freshness_minutes`` the dashboard marks it stale. Set ``shareable``
        to false for a number that must not appear on a shared page.
        """
        try:
            await report(
                deps.bot_id,
                key=key,
                value=value,
                source=source,
                unit=unit,
                label=label,
                as_of=as_of,
                freshness_minutes=freshness_minutes,
                shareable=shareable,
            )
        except DomainError as exc:
            if exc.code != "invalid_params":
                raise
            return f"invalid_params: {exc.message}"
        return "ok"

    return {"metric.report": report_metric}


register_toolset("metric", metric_toolset, {"metric.report"})
