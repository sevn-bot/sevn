"""Workspace-file store for ``job-ops`` (JSONL jobs + resume text).

Module: job-ops/scripts/lib/store.py

No database: discovered jobs live in ``<content_root>/job-ops/jobs.jsonl`` (one
:class:`JobPosting` per line) and the operator resume in
``<content_root>/job-ops/resume.md``. De-duplication is keyed on
:meth:`JobPosting.dedupe_key`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import JobPosting, Resume
from .settings import data_dir

JOBS_FILE = "jobs.jsonl"
RESUME_FILE = "resume.md"


def _now_iso() -> str:
    """Return the current UTC time as a second-precision ISO 8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobStore:
    """Read/write access to the workspace JSONL job store."""

    def __init__(self, root: Path | None = None) -> None:
        """Initialise the store under ``<content_root>/job-ops``.

        Args:
            root (Path | None): Content root override; defaults to env resolution.
        """
        self._dir = data_dir(root)
        self._jobs_path = self._dir / JOBS_FILE
        self._resume_path = self._dir / RESUME_FILE

    @property
    def jobs_path(self) -> Path:
        """Return the path to the JSONL jobs file."""
        return self._jobs_path

    def load(self) -> list[JobPosting]:
        """Load all stored postings (skips malformed lines).

        Returns:
            list[JobPosting]: Postings in file order.
        """
        if not self._jobs_path.is_file():
            return []
        out: list[JobPosting] = []
        for line in self._jobs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(JobPosting.model_validate_json(line))
            except ValueError:
                continue
        return out

    def _write_all(self, jobs: list[JobPosting]) -> None:
        """Persist ``jobs`` to disk, replacing the file contents.

        Args:
            jobs (list[JobPosting]): Full desired file contents.
        """
        payload = "\n".join(j.model_dump_json(exclude_none=True) for j in jobs)
        self._jobs_path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")

    def upsert_many(self, incoming: list[JobPosting]) -> tuple[int, int]:
        """Merge ``incoming`` postings into the store, de-duplicating by key.

        New keys are appended; for existing keys the prior record is merged forward
        and any populated fields from the fresh scrape win. Fields the new scrape
        omits — listing data (e.g. ``job_description``), AI enrichments, and operator
        tracking — are preserved from the prior record.

        Args:
            incoming (list[JobPosting]): Freshly discovered postings.

        Returns:
            tuple[int, int]: ``(added, updated)`` counts.
        """
        existing = self.load()
        by_key: dict[str, JobPosting] = {j.dedupe_key(): j for j in existing}
        added = 0
        updated = 0
        for job in incoming:
            key = job.dedupe_key()
            prior = by_key.get(key)
            if prior is None:
                if job.first_seen is None:
                    job.first_seen = _now_iso()
                by_key[key] = job
                added += 1
                continue
            merged = {
                **prior.model_dump(exclude_none=True),
                **job.model_dump(exclude_none=True),
            }
            by_key[key] = JobPosting.model_validate(merged)
            updated += 1
        self._write_all(list(by_key.values()))
        return added, updated

    def get(self, key: str) -> JobPosting | None:
        """Return the stored posting matching ``key`` (dedupe key), or ``None``."""
        for job in self.load():
            if job.dedupe_key() == key:
                return job
        return None

    def mark_seen(self, keys: Iterable[str], *, seen: bool = True) -> int:
        """Set the ``seen`` flag for the given dedupe keys in one write.

        Args:
            keys (Iterable[str]): Dedupe keys to mark.
            seen (bool): Value to store (``True`` marks seen; ``False`` clears it).

        Returns:
            int: Number of stored postings updated.
        """
        wanted = set(keys)
        if not wanted:
            return 0
        jobs = self.load()
        changed = 0
        for job in jobs:
            if job.dedupe_key() in wanted:
                job.seen = seen
                changed += 1
        if changed:
            self._write_all(jobs)
        return changed

    def update(self, job: JobPosting) -> None:
        """Replace a single stored posting matched by dedupe key.

        Args:
            job (JobPosting): Posting whose stored copy should be overwritten.
        """
        jobs = self.load()
        key = job.dedupe_key()
        for i, existing in enumerate(jobs):
            if existing.dedupe_key() == key:
                jobs[i] = job
                self._write_all(jobs)
                return
        jobs.append(job)
        self._write_all(jobs)

    def read_resume(self) -> Resume:
        """Return the stored operator resume (empty when unset)."""
        if not self._resume_path.is_file():
            return Resume(text="")
        return Resume(text=self._resume_path.read_text(encoding="utf-8"))

    def write_resume(self, text: str) -> Path:
        """Persist the operator resume text.

        Args:
            text (str): Resume/profile markdown or plain text.

        Returns:
            Path: The resume file path.
        """
        self._resume_path.write_text(text, encoding="utf-8")
        return self._resume_path
