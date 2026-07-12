"""``DREAMS.md`` section rendering (`specs/31-memory-dreaming.md` §4 `review.py`).

Module: sevn.memory.dreaming.review
Depends: sevn.memory.dreaming.models

Exports:
    format_run_summary — markdown diary chunk for one run.
"""

from __future__ import annotations

from sevn.memory.dreaming.models import DreamingCandidate


def format_run_summary(
    *,
    run_id: str,
    promoted: list[DreamingCandidate],
    skipped_count: int,
    llm_ranker_error: bool,
) -> str:
    """Build markdown fragment for the diary.

    Args:
        run_id (str): Dreaming run UUID text.
        promoted (list[DreamingCandidate]): Rows surfaced to the operator summary.
        skipped_count (int): Count of skipped candidates this run.
        llm_ranker_error (bool): Whether ranker fell back.

    Returns:
        str: Markdown body (trailing newline).

    Examples:
        >>> from sevn.memory.dreaming.models import DreamingCandidate
        >>> "run_id" in format_run_summary(
        ...     run_id="r1",
        ...     promoted=[DreamingCandidate(candidate_id="c", topic="t", value="v", score=0.5)],
        ...     skipped_count=1,
        ...     llm_ranker_error=False,
        ... )
        True
    """
    lines = [
        f"- run_id: `{run_id}`",
        f"- promoted: {len(promoted)}",
        f"- skipped: {skipped_count}",
    ]
    if llm_ranker_error:
        lines.append("- llm_ranker: error (fell back to deterministic order)")
    for c in promoted[:12]:
        lines.append(f"  - `{c.candidate_id[:8]}…` **{c.topic}** score={c.score:.3f}")
    if len(promoted) > 12:
        lines.append(f"  - … plus {len(promoted) - 12} more")
    return "\n".join(lines) + "\n"
