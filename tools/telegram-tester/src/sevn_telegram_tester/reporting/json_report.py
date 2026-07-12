"""JSON report envelope for ``sevn telegram-test run --json``.

Module: sevn_telegram_tester.reporting.json_report
Depends: pydantic

Exports:
    JsonReport — stub report model (TE-8 fills per-test rows).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TestStatus = Literal["passed", "failed", "skipped"]


class JsonTestResult(BaseModel):
    """Single test outcome (populated by TE-8 session suite)."""

    name: str
    status: TestStatus = "skipped"
    message: str | None = None
    artifacts: list[str] = Field(default_factory=list)


class JsonReport(BaseModel):
    """Top-level machine-readable report written to stdout."""

    suite: str = ""
    target: str = "local"
    deployment_id_observed: str | None = None
    tests: list[JsonTestResult] = Field(default_factory=list)
    artifacts_dir: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the report for CLI ``--json`` output."""
        return self.model_dump_json(indent=2)
