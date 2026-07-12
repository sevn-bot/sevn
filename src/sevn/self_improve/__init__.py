"""Closed-loop self-improve subsystem (`specs/33-self-improvement.md`).

Module: sevn.self_improve
Depends: sevn.self_improve.*

Exports:
    enqueue_improve_job — async façade insert for dashboard/gateway callers.
    abort_improve_job — async operator kill switch.
    effective_self_improve_enabled — env + config merge helper.
    allocate_shortlist — deterministic sampler allocator.
    recall_lessons — deterministic lesson recall façade.
    reject_patch_diff — static diff rejection hook.
    ImproveJobId — persistent job identifier type.
    OwnerPrincipal — owner subject typing for privileged calls.
"""

from __future__ import annotations

from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.facade import abort_improve_job, enqueue_improve_job, run_improve_job_eval
from sevn.self_improve.lessons import Lesson, recall_lessons
from sevn.self_improve.proposer import reject_patch_diff
from sevn.self_improve.sampler import ShortlistCandidate, allocate_shortlist
from sevn.self_improve.types import ImproveJobId, OwnerPrincipal

__all__ = [
    "ImproveJobId",
    "Lesson",
    "OwnerPrincipal",
    "ShortlistCandidate",
    "abort_improve_job",
    "allocate_shortlist",
    "effective_self_improve_enabled",
    "enqueue_improve_job",
    "recall_lessons",
    "reject_patch_diff",
    "run_improve_job_eval",
]
