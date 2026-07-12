"""Compaction scheduler — leaf summaries + optional condensation (`specs/15-memory-lcm.md` §2.5, §4).

Module: sevn.lcm.compaction
Depends: sevn.agent.providers.transport

Exports:
    Classes:
        CompactionResult — compaction telemetry.
        CompactionScheduler — incremental DAG writes.
    Functions:
        completion_text — Extract assistant text from a proxy completion payload.

Examples:
    >>> from sevn.lcm.compaction import CompactionScheduler
    >>> CompactionScheduler.__name__
    'CompactionScheduler'
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TC003 — doctests call ``sqlite3.connect``
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sevn.agent.providers.wire import adapt_request_for_transport
from sevn.config.llm_params import resolve_effective_max_output_tokens, resolve_llm_request_params

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.agent.providers.transport import Transport


def completion_text(response: dict[str, Any]) -> str:
    """Extract assistant text from proxy-shaped completion payloads.

        Args:
    response (dict[str, Any]): Parsed JSON from ``Transport.complete``.

        Returns:
            str: Extracted body or empty string.

        Examples:
            >>> completion_text({"choices":[{"message":{"content":"hi"}}]})
            'hi'
    """
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
    content = response.get("content")
    if isinstance(content, str):
        return content
    blocks = response.get("content")
    if isinstance(blocks, list):
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return ""


@dataclass(frozen=True)
class CompactionResult:
    """One compaction scheduler pass outcome (`specs/15-memory-lcm.md` §2)."""

    summaries_created: int
    depth_created_max: int
    model_id: str
    tokens_in: int
    tokens_out: int


class CompactionScheduler:
    """Leaf compaction from messages; condensation across summaries when configured."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind workspace DB connection.

                Args:
        conn (sqlite3.Connection): ``sevn.db`` connection.

                Examples:
                    >>> True
                    True
        """
        self._conn = conn

    async def run_incremental(
        self,
        *,
        conversation_id: int,
        fresh_tail_count: int,
        incremental_max_depth: int,
        transport: Transport,
        model_id: str,
        leaf_min_fanout: int,
        leaf_chunk_tokens: int,
        condensed_min_fanout: int,
        leaf_target_chars: int,
        condensed_target_chars: int,
        dedup_overlap_threshold: float,
        smart_collapse_enabled: bool,
        summary_language: str,
        content_root: Path | None = None,
    ) -> CompactionResult:
        """Run at most one leaf batch plus optional condensation batch (`specs/15-memory-lcm.md` §2.5).

        Args:
            conversation_id (int): ``lcm_conversations.id`` to compact.
            fresh_tail_count (int): Trailing visible messages reserved verbatim.
            incremental_max_depth (int): Hard ceiling on parent-summary depth; ``0`` disables.
            transport (Transport): Proxy-backed LLM transport used for both batches.
            model_id (str): Provider-rooted model identifier to record in telemetry.
            leaf_min_fanout (int): Minimum messages before a leaf summary is created.
            leaf_chunk_tokens (int): Approximate token cap per leaf batch.
            condensed_min_fanout (int): Minimum sibling summaries before condensation fires.
            leaf_target_chars (int): Soft character budget for the leaf summary body.
            condensed_target_chars (int): Soft character budget for the condensed summary.
            dedup_overlap_threshold (float): Jaccard similarity to mark predecessors subsumed.
            smart_collapse_enabled (bool): Reserved smart-collapse flag (deferred).
            summary_language (str): ``auto``, ``off``, or explicit language directive.
            content_root (Path | None): Workspace content root for ``LLM_params_config.json``.

        Returns:
            CompactionResult: Counts plus tokens consumed for this pass.

        Raises:
            NotImplementedError: When ``transport`` cannot reach the proxy (immediate failure).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CompactionScheduler.run_incremental)
            True
        """
        _ = fresh_tail_count  # reserved for future tail-aware batching
        total_in = 0
        total_out = 0
        created = 0
        depth_max = 0

        leaf_batch = self._select_leaf_source_rows(
            conversation_id, leaf_min_fanout, leaf_chunk_tokens
        )
        if leaf_batch:
            text, tin, tout = await self._llm_summarize_messages(
                transport,
                model_id,
                leaf_batch,
                target_chars=leaf_target_chars,
                summary_language=summary_language,
                content_root=content_root,
            )
            total_in += tin
            total_out += tout
            sid = self._persist_leaf_summary(
                conversation_id,
                leaf_batch,
                text,
                token_count=max(1, len(text) // 4),
                dedup_overlap_threshold=dedup_overlap_threshold,
                smart_collapse_enabled=smart_collapse_enabled,
            )
            created += 1
            depth_max = max(depth_max, 0)
            _ = sid

        cond_batch = self._select_condensation_sources(conversation_id, condensed_min_fanout)
        if cond_batch:
            depths = [int(r[2]) for r in cond_batch]
            next_depth = max(depths) + 1
            if incremental_max_depth > 0 and next_depth >= incremental_max_depth:
                return CompactionResult(
                    summaries_created=created,
                    depth_created_max=depth_max,
                    model_id=model_id,
                    tokens_in=total_in,
                    tokens_out=total_out,
                )
            bodies = [str(r[1]) for r in cond_batch]
            text2, tin2, tout2 = await self._llm_summarize_summaries(
                transport,
                model_id,
                bodies,
                target_chars=condensed_target_chars,
                summary_language=summary_language,
                content_root=content_root,
            )
            total_in += tin2
            total_out += tout2
            self._persist_condensed_summary(
                conversation_id,
                [str(r[0]) for r in cond_batch],
                text2,
                depth=next_depth,
                token_count=max(1, len(text2) // 4),
            )
            created += 1
            depth_max = max(depth_max, next_depth)

        return CompactionResult(
            summaries_created=created,
            depth_created_max=depth_max,
            model_id=model_id,
            tokens_in=total_in,
            tokens_out=total_out,
        )

    def _select_leaf_source_rows(
        self,
        conversation_id: int,
        leaf_min_fanout: int,
        leaf_chunk_tokens: int,
    ) -> list[tuple[int, str, str, int]]:
        """Return contiguous-eligible message rows for one leaf summary.

        Args:
            conversation_id (int): Conversation whose unsummarised messages to scan.
            leaf_min_fanout (int): Minimum batch size before a summary is worth creating.
            leaf_chunk_tokens (int): Approximate token cap that closes the batch early.

        Returns:
            list[tuple[int, str, str, int]]: ``id, role, content, token_count`` per row;
                empty when fanout cannot be met.

        Examples:
            >>> import sqlite3
            >>> CompactionScheduler(sqlite3.connect(":memory:"))._select_leaf_source_rows.__name__
            '_select_leaf_source_rows'
        """
        rows = self._conn.execute(
            """
            SELECT m.id, m.role, m.content, m.token_count
            FROM lcm_messages m
            WHERE m.conversation_id = ?
              AND m.kind = 'message'
              AND m.visible_to_llm = 1
              AND m.status = 'sent'
              AND m.id NOT IN (
                  SELECT message_id FROM lcm_summary_messages
              )
            ORDER BY m.seq ASC
            """,
            (conversation_id,),
        ).fetchall()
        if len(rows) < leaf_min_fanout:
            return []
        batch: list[tuple[int, str, str, int]] = []
        tok_sum = 0
        for mid, role, content, tc in rows:
            cost = int(tc) if tc else max(1, len(content) // 4)
            batch.append((int(mid), str(role), str(content), cost))
            tok_sum += cost
            at_fanout = len(batch) >= leaf_min_fanout
            if at_fanout and tok_sum >= leaf_chunk_tokens:
                break
            if at_fanout:
                break
        if len(batch) < leaf_min_fanout:
            return []
        return batch

    async def _llm_summarize_messages(
        self,
        transport: Transport,
        model_id: str,
        batch: list[tuple[int, str, str, int]],
        *,
        target_chars: int,
        summary_language: str,
        content_root: Path | None = None,
    ) -> tuple[str, int, int]:
        """Call ``Transport.complete`` with a chat-completions-shaped request.

        Args:
            transport (Transport): Proxy-backed LLM transport.
            model_id (str): Model identifier passed through to the request.
            batch (list[tuple[int, str, str, int]]): Source messages to summarise.
            target_chars (int): Soft character budget hint for the summary body.
            summary_language (str): ``auto``, ``off``, or explicit language name.
            content_root (Path | None): Workspace content root for ``LLM_params_config.json``.

        Returns:
            tuple[str, int, int]: ``(summary_text, tokens_in, tokens_out)``.

        Raises:
            RuntimeError: When the model returns empty text (`specs/15-memory-lcm.md` §6).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CompactionScheduler._llm_summarize_messages)
            True
        """
        lines = [f"{role}: {content}" for _, role, content, _ in batch]
        transcript = "\n".join(lines)
        lang_hint = ""
        if summary_language not in ("auto", "off"):
            lang_hint = f"Write the summary in {summary_language}.\n"
        user_prompt = (
            f"{lang_hint}Summarize the following transcript for long-term memory. "
            f"Stay under ~{target_chars} characters. Preserve factual anchors.\n\n{transcript}"
        )
        request: dict[str, object] = {
            "model": model_id,
            "max_tokens": resolve_effective_max_output_tokens(
                "lcm", model_id, None, content_root=content_root
            ),
            "messages": [
                {
                    "role": "system",
                    "content": "You compress conversation logs into dense summaries.",
                },
                {"role": "user", "content": user_prompt},
            ],
            # W7.4: lcm sampling from LLM_params_config.json (built-in default 0.2;
            # MiniMax ids resolve to 1.0/0.95/40 via the resolver).
            **resolve_llm_request_params(
                "lcm", model_id, transport.name, content_root=content_root
            ),
        }
        raw = await transport.complete(adapt_request_for_transport(transport, request))
        tin, tout = transport.tokens_used(raw)
        text = completion_text(raw).strip()
        if not text:
            msg = (
                "LCM compaction received empty model output (specs/15-memory-lcm.md §6 — "
                "check transport/proxy wiring)."
            )
            raise RuntimeError(msg)
        return text, tin, tout

    async def _llm_summarize_summaries(
        self,
        transport: Transport,
        model_id: str,
        bodies: list[str],
        *,
        target_chars: int,
        summary_language: str,
        content_root: Path | None = None,
    ) -> tuple[str, int, int]:
        """Condense multiple summary nodes into one parent summary.

        Args:
            transport (Transport): Proxy-backed LLM transport.
            model_id (str): Model identifier passed through to the request.
            bodies (list[str]): Child summary bodies to merge.
            target_chars (int): Soft character budget for the parent summary.
            summary_language (str): ``auto``, ``off``, or explicit language name.
            content_root (Path | None): Workspace content root for ``LLM_params_config.json``.

        Returns:
            tuple[str, int, int]: ``(parent_text, tokens_in, tokens_out)``.

        Raises:
            RuntimeError: When the model returns empty text.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CompactionScheduler._llm_summarize_summaries)
            True
        """
        wrapped = "\n\n".join(f"<child_summary>{b}</child_summary>" for b in bodies)
        lang_hint = ""
        if summary_language not in ("auto", "off"):
            lang_hint = f"Write in {summary_language}.\n"
        user_prompt = (
            f"{lang_hint}Merge these child summaries into one tighter summary under "
            f"~{target_chars} characters.\n\n{wrapped}"
        )
        request: dict[str, object] = {
            "model": model_id,
            "max_tokens": resolve_effective_max_output_tokens(
                "lcm", model_id, None, content_root=content_root
            ),
            "messages": [
                {
                    "role": "system",
                    "content": "You merge memory summaries without inventing facts.",
                },
                {"role": "user", "content": user_prompt},
            ],
            # W7.4: lcm sampling from LLM_params_config.json (built-in default 0.2).
            **resolve_llm_request_params(
                "lcm", model_id, transport.name, content_root=content_root
            ),
        }
        raw = await transport.complete(adapt_request_for_transport(transport, request))
        tin, tout = transport.tokens_used(raw)
        text = completion_text(raw).strip()
        if not text:
            msg = "LCM condensation received empty model output."
            raise RuntimeError(msg)
        return text, tin, tout

    def _persist_leaf_summary(
        self,
        conversation_id: int,
        batch: list[tuple[int, str, str, int]],
        text: str,
        *,
        token_count: int,
        dedup_overlap_threshold: float,
        smart_collapse_enabled: bool,
    ) -> str:
        """Insert compaction summary + edges; optional dedup promotion.

        Args:
            conversation_id (int): Conversation owning the new summary.
            batch (list[tuple[int, str, str, int]]): Source rows covered by this summary.
            text (str): LLM-produced summary body.
            token_count (int): Token estimate persisted alongside the row.
            dedup_overlap_threshold (float): Jaccard threshold for marking older same-depth
                summaries as subsumed.
            smart_collapse_enabled (bool): Reserved smart-collapse flag (deferred).

        Returns:
            str: Newly inserted ``summary_id`` (UUID hex form).

        Examples:
            >>> CompactionScheduler._persist_leaf_summary.__name__
            '_persist_leaf_summary'
        """
        _ = smart_collapse_enabled  # smart-collapse deferred — lossless rows remain (`specs/15-memory-lcm.md` §11).
        sid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO lcm_summaries (
                summary_id, conversation_id, content, depth, token_count,
                summary_kind, subsumed_by, merged_from, created_at
            ) VALUES (?, ?, ?, 0, ?, 'compaction', NULL, NULL, ?)
            """,
            (sid, conversation_id, text, token_count, now),
        )
        for mid, _, _, _ in batch:
            self._conn.execute(
                "INSERT INTO lcm_summary_messages(summary_id, message_id) VALUES (?, ?)",
                (sid, mid),
            )
        ord_row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) FROM lcm_context_items WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        next_ord = int(ord_row[0]) + 1 if ord_row else 0
        self._conn.execute(
            """
            INSERT INTO lcm_context_items (
                conversation_id, ordinal, item_type, message_id, summary_id
            ) VALUES (?, ?, 'summary', NULL, ?)
            """,
            (conversation_id, next_ord, sid),
        )

        if dedup_overlap_threshold < 1.0:
            self._maybe_mark_subsumed(conversation_id, sid, text, dedup_overlap_threshold)
        return sid

    def _maybe_mark_subsumed(
        self,
        conversation_id: int,
        new_id: str,
        new_text: str,
        threshold: float,
    ) -> None:
        """Mark older same-depth summary subsumed when token-set Jaccard exceeds threshold.

        Args:
            conversation_id (int): Conversation owning candidate predecessors.
            new_id (str): Newly inserted summary id (kept ``subsumed_by IS NULL``).
            new_text (str): Body used to compare against the prior summary.
            threshold (float): Jaccard similarity ceiling in ``[0, 1]``.

        Examples:
            >>> CompactionScheduler._maybe_mark_subsumed.__name__
            '_maybe_mark_subsumed'
        """
        row = self._conn.execute(
            """
            SELECT summary_id, content FROM lcm_summaries
            WHERE conversation_id = ?
              AND summary_kind = 'compaction'
              AND depth = 0
              AND summary_id != ?
              AND subsumed_by IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (conversation_id, new_id),
        ).fetchone()
        if not row:
            return
        old_id, old_body = str(row[0]), str(row[1])
        jac = _token_jaccard(old_body, new_text)
        if jac >= threshold:
            self._conn.execute(
                "UPDATE lcm_summaries SET subsumed_by = ? WHERE summary_id = ?",
                (new_id, old_id),
            )

    def _select_condensation_sources(
        self,
        conversation_id: int,
        condensed_min_fanout: int,
    ) -> list[tuple[str, str, int]]:
        """Pick oldest compaction summaries not yet merged upward.

        Args:
            conversation_id (int): Conversation to scan.
            condensed_min_fanout (int): Minimum sibling count before condensation is eligible.

        Returns:
            list[tuple[str, str, int]]: ``summary_id, content, depth`` rows; empty when
                fanout cannot be met.

        Examples:
            >>> CompactionScheduler._select_condensation_sources.__name__
            '_select_condensation_sources'
        """
        rows = self._conn.execute(
            """
            SELECT s.summary_id, s.content, s.depth
            FROM lcm_summaries s
            WHERE s.conversation_id = ?
              AND s.summary_kind = 'compaction'
              AND s.subsumed_by IS NULL
              AND s.summary_id NOT IN (SELECT child_id FROM lcm_summary_parents)
            ORDER BY s.created_at ASC
            LIMIT ?
            """,
            (conversation_id, condensed_min_fanout),
        ).fetchall()
        if len(rows) < condensed_min_fanout:
            return []
        return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]

    def _persist_condensed_summary(
        self,
        conversation_id: int,
        child_ids: list[str],
        text: str,
        *,
        depth: int,
        token_count: int,
    ) -> str:
        """Insert parent summary + ``lcm_summary_parents`` edges.

        Args:
            conversation_id (int): Conversation owning the new summary.
            child_ids (list[str]): Summary ids merged into this parent.
            text (str): LLM-produced condensed body.
            depth (int): Parent depth (``max(child_depths) + 1``).
            token_count (int): Token estimate persisted alongside the row.

        Returns:
            str: Newly inserted parent ``summary_id``.

        Examples:
            >>> CompactionScheduler._persist_condensed_summary.__name__
            '_persist_condensed_summary'
        """
        sid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO lcm_summaries (
                summary_id, conversation_id, content, depth, token_count,
                summary_kind, subsumed_by, merged_from, created_at
            ) VALUES (?, ?, ?, ?, ?, 'compaction', NULL, ?, ?)
            """,
            (sid, conversation_id, text, depth, token_count, json.dumps(child_ids), now),
        )
        for cid in child_ids:
            self._conn.execute(
                "INSERT INTO lcm_summary_parents(child_id, parent_id) VALUES (?, ?)",
                (cid, sid),
            )
        ord_row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) FROM lcm_context_items WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        next_ord = int(ord_row[0]) + 1 if ord_row else 0
        self._conn.execute(
            """
            INSERT INTO lcm_context_items (
                conversation_id, ordinal, item_type, message_id, summary_id
            ) VALUES (?, ?, 'summary', NULL, ?)
            """,
            (conversation_id, next_ord, sid),
        )
        return sid


def _token_jaccard(a: str, b: str) -> float:
    """Naïve token-set Jaccard similarity in ``[0, 1]``.

    Args:
        a (str): First text.
        b (str): Second text.

    Returns:
        float: Jaccard similarity ``len(A & B) / len(A | B)`` (``1.0`` if both
            empty, ``0.0`` if exactly one empty).

    Examples:
        >>> _token_jaccard("a b c", "b c d") > 0.3
        True
    """
    sa = {w.lower() for w in a.split() if w.strip()}
    sb = {w.lower() for w in b.split() if w.strip()}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0
