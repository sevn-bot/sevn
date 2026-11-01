"""One usage shape for every runtime (plan fleet-dashboards, phase 2).

``cost_source`` says where ``cost_usd`` came from:

- ``price_table``: priced per model response from ``genai-prices``.
- ``local``: a local model (Ollama). No API spend, so ``cost_usd`` is 0.
- ``subscription``: a Claude turn on the user's own login. Quota, not dollars,
  so ``cost_usd`` is null. ``estimated_usd`` keeps the SDK's list-price figure.
- ``unknown``: at least one response could not be priced. ``cost_usd`` is
  null rather than a partial sum that would read as the whole cost.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

type CostSource = Literal["price_table", "local", "subscription", "unknown"]

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
_COUNT_KEYS = ("requests", "tool_calls", *TOKEN_KEYS)
_LOCAL_PROVIDERS = frozenset({"ollama"})


def usage_record(
    counts: Mapping[str, object],
    *,
    cost_usd: float | None,
    cost_source: CostSource,
    estimated_usd: float | None = None,
) -> dict[str, object]:
    """The stored usage dict. Missing counts are 0."""
    record: dict[str, object] = {key: _int(counts.get(key)) for key in _COUNT_KEYS}
    record["cost_usd"] = cost_usd
    record["cost_source"] = cost_source
    record["estimated_usd"] = estimated_usd
    return record


def price_responses(responses: Iterable[object]) -> tuple[float | None, CostSource]:
    """Sum the cost of each pydantic-ai ``ModelResponse``.

    Tiered prices depend on one request's size, so each response is priced on
    its own usage, never the turn's total.
    """
    total = 0.0
    priced = False
    for response in responses:
        provider = getattr(response, "provider_name", None)
        if isinstance(provider, str) and provider in _LOCAL_PROVIDERS:
            continue
        model = getattr(response, "model_name", None)
        cost = getattr(response, "cost", None)
        if not isinstance(model, str) or model == "" or not callable(cost):
            return None, "unknown"
        try:
            calculation = cost()
        except (LookupError, ValueError):
            # ``cost()`` lets pricing errors through: an unknown model is a
            # LookupError, usage it cannot split (cache reads above the input)
            # is a ValueError. Pricing must never fail the turn.
            return None, "unknown"
        total += float(getattr(calculation, "total_price", 0))
        priced = True
    if not priced:
        return 0.0, "local"
    return round(total, 6), "price_table"


def combine(old: Mapping[str, object], new: Mapping[str, object]) -> dict[str, object]:
    """Add the usage of a later run of the same turn (resume or auto approval)."""
    if not old:
        return dict(new)
    if not new:
        return dict(old)
    counts = {key: _int(old.get(key)) + _int(new.get(key)) for key in _COUNT_KEYS}
    old_source = _source(old)
    new_source = _source(new)
    estimate = _add_optional(_float(old.get("estimated_usd")), _float(new.get("estimated_usd")))
    sources = {old_source, new_source}
    if "unknown" in sources:
        return usage_record(counts, cost_usd=None, cost_source="unknown", estimated_usd=estimate)
    if "subscription" in sources:
        return usage_record(
            counts, cost_usd=None, cost_source="subscription", estimated_usd=estimate
        )
    cost = (_float(old.get("cost_usd")) or 0.0) + (_float(new.get("cost_usd")) or 0.0)
    source: CostSource = "local" if sources == {"local"} else "price_table"
    return usage_record(counts, cost_usd=round(cost, 6), cost_source=source, estimated_usd=estimate)


def cost_source_of(usage: Mapping[str, object]) -> CostSource:
    """The stored source. Usage written before phase 2 has none: ``unknown``."""
    return _source(usage)


def tokens_of(usage: Mapping[str, object]) -> int:
    """Input plus output tokens.

    In this shape ``input_tokens`` already includes cache reads and writes.
    Each runtime normalizes to that; Anthropic's raw count leaves them out.
    """
    return _int(usage.get("input_tokens")) + _int(usage.get("output_tokens"))


def cost_of(usage: Mapping[str, object]) -> float | None:
    return _float(usage.get("cost_usd"))


def _source(usage: Mapping[str, object]) -> CostSource:
    raw = usage.get("cost_source")
    if raw in ("price_table", "local", "subscription", "unknown"):
        return raw
    return "unknown"


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _add_optional(first: float | None, second: float | None) -> float | None:
    if first is None and second is None:
        return None
    return round((first or 0.0) + (second or 0.0), 6)
