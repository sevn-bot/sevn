"""Deterministic scoring + optional LLM re-rank (`specs/31-memory-dreaming.md` §2.4, §6).

Module: sevn.memory.dreaming.scorer
Depends: sevn.config.workspace_config

Exports:
    build_candidates — filter, score, threshold-split candidates.
    maybe_llm_rerank — optional single-shot transport re-ordering.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections import Counter
from typing import TYPE_CHECKING

from sevn.agent.providers.wire import adapt_request_for_transport
from sevn.config.llm_params import resolve_effective_max_output_tokens, resolve_llm_request_params
from sevn.config.workspace_config import DreamingWorkspaceConfig
from sevn.memory.dreaming.filters import (
    content_has_llmignore_provenance,
    lcm_channel_allows_dreaming,
    session_allows_dreaming,
)
from sevn.memory.dreaming.models import DreamingCandidate
from sevn.memory.dreaming.sources import RawMemorySignal

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.agent.providers.transport import Transport


def _parse_metadata_channel(metadata: str | None) -> str | None:
    """Return ``channel`` string from JSON metadata when present.

    Args:
        metadata (str | None): Optional JSON blob (e.g. LCM join metadata).

    Returns:
        str | None: Channel label or ``None``.

    Examples:
        >>> _parse_metadata_channel('{"channel": "private"}')
        'private'
    """
    if not metadata:
        return None
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        return None
    if not isinstance(meta, dict):
        return None
    ch = meta.get("channel")
    return str(ch) if ch is not None else None


def _raw_to_candidate(
    raw: RawMemorySignal,
    *,
    weights: tuple[float, float, float],
    topic_counts: Counter[str],
    now_s: float,
    recall_weights: dict[str, float] | None = None,
) -> DreamingCandidate | None:
    """Map a raw signal to a scored candidate or None when filtered.

    Args:
        raw (RawMemorySignal): Source row prior to dedupe.
        weights (tuple[float, float, float]): ``(recall, diversity, recency)`` weights.
        topic_counts (Counter[str]): Running per-topic counts for diversity.
        now_s (float): ``time.time()`` for recency decay.
        recall_weights (dict[str, float] | None): Optional ``memory_recall_signals`` boosts.

    Returns:
        DreamingCandidate | None: Candidate when the row survives gates.

    Examples:
        >>> from collections import Counter
        >>> from sevn.memory.dreaming.sources import RawMemorySignal
        >>> raw = RawMemorySignal(
        ...     source_kind="memory",
        ...     source_key="k",
        ...     session_label="dm:u",
        ...     topic="t",
        ...     content="hello world",
        ...     created_at="2099-01-01",
        ...     metadata=None,
        ... )
        >>> c = _raw_to_candidate(raw, weights=(0.5, 0.3, 0.2), topic_counts=Counter(), now_s=1e9)
        >>> c is not None and 0.0 <= c.score <= 1.0
        True
    """
    if raw.source_kind == "memory":
        if not session_allows_dreaming(raw.session_label, raw.metadata):
            return None
        if content_has_llmignore_provenance(raw.content, raw.metadata):
            return None
    elif raw.source_kind == "lcm":
        ch = _parse_metadata_channel(raw.metadata)
        if not lcm_channel_allows_dreaming(ch):
            return None
        if content_has_llmignore_provenance(raw.content, raw.metadata):
            return None
    else:
        if content_has_llmignore_provenance(raw.content, raw.metadata):
            return None

    recall_w, diversity_w, recency_w = weights
    length_norm = min(1.0, len(raw.content) / 400.0)
    recall = length_norm
    if recall_weights and raw.source_kind == "memory":
        for mk, w in recall_weights.items():
            if mk in raw.source_key or raw.source_key.endswith(f":{mk}"):
                recall = max(recall, min(1.0, float(w)))
                break
    diversity = 1.0 / (1.0 + math.log1p(topic_counts[raw.topic]))
    topic_counts[raw.topic] += 1

    try:
        if len(raw.created_at) >= 10 and raw.created_at[4] == "-":
            from datetime import UTC, datetime

            dt = datetime.strptime(raw.created_at[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            age_days = max(0.0, (now_s - dt.timestamp()) / 86400.0)
        else:
            age_days = 30.0
    except ValueError:
        age_days = 30.0
    recency = math.exp(-age_days / 45.0)

    score = recall_w * recall + diversity_w * diversity + recency_w * recency
    score = max(0.0, min(1.0, score))
    return DreamingCandidate(
        candidate_id=str(uuid.uuid4()),
        topic=raw.topic[:512],
        value=raw.content[:4000],
        score=score,
        source_keys=[raw.source_key],
        reasons={
            "recall": round(recall, 4),
            "diversity": round(diversity, 4),
            "recency": round(recency, 4),
        },
    )


def build_candidates(
    raws: list[RawMemorySignal],
    dreaming: DreamingWorkspaceConfig,
    *,
    recall_weights: dict[str, float] | None = None,
) -> tuple[list[DreamingCandidate], list[DreamingCandidate], list[tuple[DreamingCandidate, str]]]:
    """Score and filter raw inputs.

    Args:
        raws (list[RawMemorySignal]): Concatenated sources (memory, LCM, logs).
        dreaming (DreamingWorkspaceConfig): Workspace Dreaming section.
        recall_weights (dict[str, float] | None): Optional ``memory_recall_signals`` boosts.

    Returns:
        tuple: ``(kept_pre_threshold, eligible, skipped)`` where ``kept_pre_threshold`` is
        post-dedupe scored rows before threshold/cap gating, ``eligible`` meets threshold,
        and ``skipped`` records below-threshold removals and dedupe drops.

    Examples:
        >>> from sevn.memory.dreaming.sources import RawMemorySignal
        >>> raw = RawMemorySignal(
        ...     source_kind="memory",
        ...     source_key="k",
        ...     session_label="dm:u",
        ...     topic="t",
        ...     content="hello",
        ...     created_at="2099-01-01",
        ...     metadata=None,
        ... )
        >>> k, e, s = build_candidates([raw], DreamingWorkspaceConfig(enabled=True, threshold=0.0))
        >>> len(k) >= 1 and len(e) >= 1
        True
    """
    scoring = dreaming.scoring
    recall_w = scoring.recall_weight if scoring else 0.5
    diversity_w = scoring.diversity_weight if scoring else 0.3
    recency_w = scoring.recency_weight if scoring else 0.2
    weights = (recall_w, diversity_w, recency_w)
    now_s = time.time()
    topic_counts: Counter[str] = Counter()
    kept: list[DreamingCandidate] = []
    skipped: list[tuple[DreamingCandidate, str]] = []
    seen_value_prefix: set[str] = set()

    for raw in raws:
        if raw.source_kind == "memory" and not session_allows_dreaming(
            raw.session_label, raw.metadata
        ):
            continue
        if raw.source_kind == "lcm" and not lcm_channel_allows_dreaming(
            _parse_metadata_channel(raw.metadata),
        ):
            continue
        cand = _raw_to_candidate(
            raw,
            weights=weights,
            topic_counts=topic_counts,
            now_s=now_s,
            recall_weights=recall_weights,
        )
        if cand is None:
            continue
        dedupe = cand.value[:96]
        if dedupe in seen_value_prefix:
            skipped.append((cand, "dedupe"))
            continue
        seen_value_prefix.add(dedupe)
        kept.append(cand)

    if scoring and scoring.adaptive and kept:
        scores = sorted(c.score for c in kept)
        mid = scores[len(scores) // 2]
        thr = max(dreaming.threshold, mid)
    else:
        thr = dreaming.threshold

    eligible: list[DreamingCandidate] = []
    below_threshold: list[tuple[DreamingCandidate, str]] = []
    for c in kept:
        if c.score >= thr:
            eligible.append(c)
        else:
            below_threshold.append((c, "below_threshold"))

    eligible.sort(key=lambda x: x.score, reverse=True)
    return kept, eligible, skipped + below_threshold


async def maybe_llm_rerank(
    candidates: list[DreamingCandidate],
    *,
    dreaming: DreamingWorkspaceConfig,
    transport: Transport | None,
    lcm_summary_model: str | None,
    content_root: Path | None = None,
) -> tuple[list[DreamingCandidate], bool]:
    """Optionally re-rank top-K via a single bounded ``Transport`` call.

    Args:
        candidates (list[DreamingCandidate]): Ordered candidate list.
        dreaming (DreamingWorkspaceConfig): Dreaming workspace section (ranker gate).
        transport (Transport | None): Optional LLM transport.
        lcm_summary_model (str | None): Fallback model id when ranker model unset.
        content_root (Path | None): Workspace content root for ``LLM_params_config.json``.

    Returns:
        tuple[list[DreamingCandidate], bool]: Possibly re-ordered list + error flag.

    Examples:
        >>> import asyncio
        >>> from sevn.memory.dreaming.models import DreamingCandidate
        >>> c = DreamingCandidate(candidate_id="a", topic="t", value="v", score=0.5)
        >>> asyncio.run(maybe_llm_rerank([c], dreaming=DreamingWorkspaceConfig(enabled=True), transport=None, lcm_summary_model=None))
        ([DreamingCandidate(candidate_id='a', topic='t', value='v', score=0.5, source_keys=[], reasons={})], False)
    """
    scoring = dreaming.scoring
    lr = scoring.llm_ranker if scoring else None
    if lr is None or not lr.enabled:
        return candidates, False
    if transport is None:
        return candidates, True
    model = (lr.model.strip() if isinstance(lr.model, str) and lr.model.strip() else None) or (
        lcm_summary_model.strip()
        if isinstance(lcm_summary_model, str) and lcm_summary_model.strip()
        else None
    )
    if not model:
        return candidates, True
    k = min(16, len(candidates))
    if k <= 1:
        return candidates, False
    top = candidates[:k]
    rest = candidates[k:]
    candidate_ids = [c.candidate_id for c in top]
    payload: dict[str, object] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return JSON array of candidate_id strings in best-to-worst order "
                    "for long-term MEMORY.md promotion."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"candidate_ids": candidate_ids}, ensure_ascii=False),
            },
        ],
        "max_tokens": resolve_effective_max_output_tokens(
            "dreaming", model, None, content_root=content_root
        ),
        # W7.4: dreaming sampling from LLM_params_config.json (built-in default 0.0).
        **resolve_llm_request_params("dreaming", model, transport.name, content_root=content_root),
    }
    try:
        resp = await transport.complete(adapt_request_for_transport(transport, payload))
    except Exception:
        return candidates, True
    text = ""
    try:
        choices = resp.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                text = str(msg["content"])
        if not text:
            content = resp.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        body_text = block.get("text")
                        if isinstance(body_text, str):
                            text = body_text
                            break
    except Exception:
        return candidates, True
    try:
        order = json.loads(text)
    except json.JSONDecodeError:
        return candidates, True
    if not isinstance(order, list):
        return candidates, True
    by_id = {c.candidate_id: c for c in top}
    ranked: list[DreamingCandidate] = []
    for cid in order:
        if isinstance(cid, str) and cid in by_id:
            ranked.append(by_id[cid])
    for c in top:
        if c not in ranked:
            ranked.append(c)
    return ranked + rest, False
