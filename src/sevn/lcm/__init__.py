"""Lossless context management (`specs/15-memory-lcm.md`).

Module: sevn.lcm
Depends: sevn.lcm.engine, sevn.lcm.assembler, sevn.lcm.compaction, sevn.lcm.flush

Exports:
    LcmEngine — ingest / assemble / compaction façade.
    SessionView — gateway session scope.
    InboundLcmMessage — inbound persist shape.
    SummarySearchScope — summary search selector literal alias.
    SessionSummaryHit — search hit row.
    AssembledContext — assembled transcript + telemetry.
    CompactionResult — compaction telemetry.
    MemoryWrite — flush structured row.
    MemoryWrites — flush batch envelope.

Examples:
    >>> from sevn.lcm import LcmEngine
    >>> LcmEngine.__name__
    'LcmEngine'
"""

from __future__ import annotations

from sevn.lcm.assembler import AssembledContext, LcmAssembler
from sevn.lcm.compaction import CompactionResult, CompactionScheduler, completion_text
from sevn.lcm.engine import (
    InboundLcmMessage,
    LcmEngine,
    SessionSummaryHit,
    SessionView,
    SummarySearchScope,
)
from sevn.lcm.flush import (
    FlushDecodeOutcome,
    MemoryWrite,
    MemoryWrites,
    is_allowlisted_relative_path,
    run_flush_decode_with_retry_once,
    validate_memory_writes,
)
from sevn.lcm.large_files import LargeFileSpill, maybe_spill_large_payload
from sevn.lcm.query import (
    conversations_meta,
    describe_item,
    expand_query,
    expand_summary,
    fetch_message,
    fetch_recent_messages,
    grep_messages,
    list_conversations,
    search_summaries_scoped,
)
from sevn.lcm.search import search_session_summaries

__all__ = [
    "AssembledContext",
    "CompactionResult",
    "CompactionScheduler",
    "FlushDecodeOutcome",
    "InboundLcmMessage",
    "LargeFileSpill",
    "LcmAssembler",
    "LcmEngine",
    "MemoryWrite",
    "MemoryWrites",
    "SessionSummaryHit",
    "SessionView",
    "SummarySearchScope",
    "completion_text",
    "conversations_meta",
    "describe_item",
    "expand_query",
    "expand_summary",
    "fetch_message",
    "fetch_recent_messages",
    "grep_messages",
    "is_allowlisted_relative_path",
    "list_conversations",
    "maybe_spill_large_payload",
    "run_flush_decode_with_retry_once",
    "search_session_summaries",
    "search_summaries_scoped",
    "validate_memory_writes",
]
