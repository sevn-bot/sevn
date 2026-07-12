"""Doctor check model and result collector (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.checks
Depends: dataclasses, typing, sevn.cli.doctor.sections, sevn.onboarding.live_validate

Exports:
    DoctorCheck — one doctor probe row with section + severity metadata.
    CheckResult — ordered collector with JSON export and section grouping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sevn.cli.doctor.sections import SECTION_ORDER, section_for, title_for
from sevn.onboarding.live_validate import ValidationCheck

Severity = Literal["warn", "error"] | None


@dataclass
class DoctorCheck:
    """One doctor probe row for human + machine output.

    Args:
        id (str): Stable check identifier (preserved for ``--json`` back-compat).
        section (str): Section banner grouping.
        title (str): Short human row label.
        ok (bool): Whether the probe passed.
        severity (Severity): Optional ``warn`` or ``error`` grade.
        detail (str): Primary detail string (``--json`` ``detail`` field).
        hint (str | None): Optional remediation hint.
    """

    id: str
    section: str
    title: str
    ok: bool
    severity: Severity = None
    detail: str = ""
    hint: str | None = None

    @classmethod
    def from_validation(
        cls,
        vc: ValidationCheck,
        *,
        section: str | None = None,
        title: str | None = None,
    ) -> DoctorCheck:
        """Build a ``DoctorCheck`` from an onboarding ``ValidationCheck``.

        Args:
            vc (ValidationCheck): Live-validation probe row.
            section (str | None): Override section; default from ``vc.check_id``.
            title (str | None): Override title; default from ``vc.check_id``.

        Returns:
            DoctorCheck: Mapped doctor row.

        Examples:
            >>> DoctorCheck.from_validation(
            ...     ValidationCheck("secrets_backend", True, "info", "ok"),
            ... ).id
            'secrets_backend'
        """
        sev: Severity = None
        if vc.severity in ("warn", "error"):
            sev = vc.severity
        return cls(
            id=vc.check_id,
            section=section or section_for(vc.check_id),
            title=title or title_for(vc.check_id),
            ok=vc.ok,
            severity=sev,
            detail=vc.detail,
            hint=vc.hint,
        )

    def to_json_row(self) -> dict[str, Any]:
        """Serialize to the legacy ``--json`` check dict shape.

        Returns:
            dict[str, Any]: ``{id, ok, detail}`` plus optional ``severity``/``hint``.

        Examples:
            >>> DoctorCheck("sqlite", "Storage", "SQLite", True, detail="ok").to_json_row()["id"]
            'sqlite'
        """
        row: dict[str, Any] = {"id": self.id, "ok": self.ok, "detail": self.detail}
        if self.severity in ("warn", "error"):
            row["severity"] = self.severity
        if self.hint:
            row["hint"] = self.hint
        return row


@dataclass
class CheckResult:
    """Ordered doctor probe results with warn/error side channels.

    Args:
        checks (list[DoctorCheck]): Probe rows in registration order.
        warnings (list[str]): Legacy warning strings for ``--json`` ``warnings``.
        errors (list[str]): Error strings that drive exit code 4.
    """

    checks: list[DoctorCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, check: DoctorCheck) -> None:
        """Append one check row (no automatic warn/error side effects).

        Args:
            check (DoctorCheck): Probe row to record.

        Returns:
            None

        Examples:
            >>> r = CheckResult()
            >>> r.add(DoctorCheck("sevn_json", "Workspace", "sevn.json", True, detail="ok"))
            >>> len(r.checks)
            1
        """
        self.checks.append(check)

    def add_validation(self, vc: ValidationCheck) -> None:
        """Map and append an onboarding ``ValidationCheck``.

        Args:
            vc (ValidationCheck): Secrets/webapp/LLM probe row.

        Returns:
            None

        Examples:
            >>> r = CheckResult()
            >>> r.add_validation(ValidationCheck("secrets_backend", True, "info", "ok"))
            >>> r.checks[-1].id
            'secrets_backend'
        """
        check = DoctorCheck.from_validation(vc)
        self.checks.append(check)
        if not vc.ok:
            msg = f"{vc.check_id}: {vc.detail}"
            if vc.severity == "error":
                self.errors.append(msg)
            elif vc.severity == "warn":
                self.warnings.append(msg)
        elif vc.severity == "warn":
            self.warnings.append(vc.hint or vc.detail)

    def add_custom_error(self, message: str) -> None:
        """Append a free-form error string (no check row).

        Args:
            message (str): Error text appended to ``errors``.

        Returns:
            None

        Examples:
            >>> r = CheckResult()
            >>> r.add_custom_error("telegram probe requested but not implemented")
            >>> r.errors[-1]
            'telegram probe requested but not implemented'
        """
        self.errors.append(message)

    def to_json_checks(
        self,
        *,
        include_solutions: bool = False,
        catalog: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Return legacy ``checks`` list for ``--json`` envelopes.

        Args:
            include_solutions (bool): When True, attach ``solution`` on warn/fail rows.
            catalog (Any | None): Optional pre-loaded ``SolutionsCatalog``.

        Returns:
            list[dict[str, Any]]: Serialized check rows in registration order.

        Examples:
            >>> CheckResult(
            ...     checks=[DoctorCheck("sevn_json", "Workspace", "sevn.json", True, detail="p")]
            ... ).to_json_checks()[0]["id"]
            'sevn_json'
        """
        if not include_solutions:
            return [check.to_json_row() for check in self.checks]
        from sevn.cli.doctor.solutions import solution_for_json

        rows: list[dict[str, Any]] = []
        for check in self.checks:
            row = check.to_json_row()
            if not check.ok or check.severity == "warn":
                row["solution"] = solution_for_json(check.id, catalog)
            rows.append(row)
        return rows

    def by_section(self) -> list[tuple[str, list[DoctorCheck]]]:
        """Group checks by section in canonical banner order.

        Returns:
            list[tuple[str, list[DoctorCheck]]]: Non-empty sections only.

        Examples:
            >>> r = CheckResult()
            >>> r.add(DoctorCheck("sevn_json", "Workspace", "sevn.json", True))
            >>> r.by_section()[0][0]
            'Workspace'
        """
        buckets: dict[str, list[DoctorCheck]] = {name: [] for name in SECTION_ORDER}
        for check in self.checks:
            if check.section not in buckets:
                buckets[check.section] = []
            buckets[check.section].append(check)
        out: list[tuple[str, list[DoctorCheck]]] = []
        seen: set[str] = set()
        for name in SECTION_ORDER:
            rows = buckets.get(name, [])
            if rows:
                out.append((name, rows))
                seen.add(name)
        for name, rows in buckets.items():
            if name not in seen and rows:
                out.append((name, rows))
        return out

    def counts(self) -> tuple[int, int, int]:
        """Count ok, warn, and fail rows for the summary line.

        Returns:
            tuple[int, int, int]: ``(ok_count, warn_count, fail_count)``.

        Examples:
            >>> r = CheckResult()
            >>> r.add(DoctorCheck("a", "Workspace", "a", True))
            >>> r.counts()
            (1, 0, 0)
        """
        ok_count = warn_count = fail_count = 0
        for check in self.checks:
            if check.ok and check.severity != "warn":
                ok_count += 1
            elif not check.ok and check.severity == "error":
                fail_count += 1
            elif check.severity == "warn" or not check.ok:
                warn_count += 1
            else:
                ok_count += 1
        return ok_count, warn_count, fail_count


__all__ = ["CheckResult", "DoctorCheck", "Severity"]
