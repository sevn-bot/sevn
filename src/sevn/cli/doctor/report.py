"""Human doctor report rendering via W1 ``render/sections`` (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.report
Depends: sevn.cli.doctor.checks, sevn.cli.doctor.solutions, sevn.cli.render

Exports:
    render_doctor_report — sectioned Rich/plain doctor output + summary line.
    render_fix_lines — print ``[fixed]`` / ``[manual]`` rows after ``--fix``.
"""

from __future__ import annotations

from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.fix import FixReport
from sevn.cli.doctor.solutions import (
    NO_CANNED_SOLUTION,
    SolutionsCatalog,
    load_solutions_catalog,
    lookup_solution,
)
from sevn.cli.render import check_fail, check_info, check_ok, check_warn, plain_echo, section


def _render_solution_block(check: DoctorCheck, catalog: SolutionsCatalog) -> None:
    """Print catalog explanation + numbered remediation beneath a check row.

    Args:
        check (DoctorCheck): Probe row that failed or warned.
        catalog (SolutionsCatalog): Bundled solutions catalog.

    Returns:
        None

    Examples:
        >>> _render_solution_block(
        ...     DoctorCheck("x", "Workspace", "x", False, severity="error"),
        ...     load_solutions_catalog(),
        ... )  # doctest: +SKIP
    """
    if check.ok and check.severity != "warn":
        return
    solution = lookup_solution(check.id, catalog)
    if solution is None:
        plain_echo(f"    {NO_CANNED_SOLUTION}")
        return
    plain_echo(f"    {solution.explanation}")
    for idx, step in enumerate(solution.remediation, start=1):
        plain_echo(f"    {idx}. {step}")
    if solution.fix_command:
        plain_echo(f"    fix: {solution.fix_command}")


def _render_check_row(check: DoctorCheck, catalog: SolutionsCatalog) -> None:
    """Emit one severity row for a doctor check.

    Args:
        check (DoctorCheck): Probe row to render.
        catalog (SolutionsCatalog): Bundled solutions catalog.

    Returns:
        None

    Examples:
        >>> _render_check_row(
        ...     DoctorCheck("sevn_json", "Workspace", "sevn.json", True),
        ...     load_solutions_catalog(),
        ... )  # doctest: +SKIP
    """
    detail = check.detail
    if check.hint:
        detail = f"{detail} — {check.hint}" if detail else check.hint
    if check.ok and check.severity != "warn":
        check_ok(check.title, detail)
    elif check.severity == "warn":
        check_warn(check.title, detail)
    elif not check.ok and check.severity == "error":
        check_fail(check.title, detail)
    elif not check.ok:
        check_warn(check.title, detail)
    else:
        check_ok(check.title, detail)
    if check.hint and check.ok and check.severity != "warn":
        check_info(check.hint)
    _render_solution_block(check, catalog)


def render_fix_lines(fix_report: FixReport) -> None:
    """Print ``[fixed]`` / ``[manual]`` lines after a ``--fix`` pass.

    Args:
        fix_report (FixReport): Aggregated fix outcomes.

    Returns:
        None

    Examples:
        >>> from sevn.cli.doctor.fix import FixReport
        >>> render_fix_lines(FixReport())
    """
    for row in fix_report.fixed:
        plain_echo(f"[fixed] {row['check_id']}: {row['detail']}")
    for row in fix_report.manual:
        plain_echo(f"[manual] {row['check_id']}: {row['detail']}")


def render_doctor_report(
    result: CheckResult,
    *,
    success: bool,
    catalog: SolutionsCatalog | None = None,
) -> None:
    """Print a sectioned doctor report and summary line.

    Args:
        result (CheckResult): Collected probe rows.
        success (bool): When True, emit the legacy success footer; else warn/error lines.
        catalog (SolutionsCatalog | None): Optional pre-loaded catalog.

    Returns:
        None

    Examples:
        >>> r = CheckResult()
        >>> r.add(DoctorCheck("sevn_json", "Workspace", "sevn.json", True, detail="ok"))
        >>> render_doctor_report(r, success=True)
        <BLANKLINE>
        ◆ Workspace
          ✓ sevn.json ok
        <BLANKLINE>
        1 ok · 0 warn · 0 fail
        doctor: all required checks passed
    """
    doc = catalog or load_solutions_catalog()
    for section_name, rows in result.by_section():
        section(section_name)
        for check in rows:
            _render_check_row(check, doc)
    ok_count, warn_count, fail_count = result.counts()
    plain_echo("")
    plain_echo(f"{ok_count} ok · {warn_count} warn · {fail_count} fail")
    if success:
        plain_echo("doctor: all required checks passed")
    else:
        for warning in result.warnings:
            plain_echo(f"warning: {warning}", err=True)
        for error in result.errors:
            plain_echo(f"error: {error}", err=True)


__all__ = ["render_doctor_report", "render_fix_lines"]
