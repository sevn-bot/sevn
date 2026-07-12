"""Sectioned doctor check framework (`specs/23-cli.md` §3).

Module: sevn.cli.doctor
Depends: sevn.cli.doctor.checks, sevn.cli.doctor.probes, sevn.cli.doctor.report,
    sevn.cli.doctor.sections, sevn.cli.doctor.solutions, sevn.cli.doctor.fix

Exports:
    CheckResult — ordered doctor probe collector.
    DoctorCheck — one probe row with section metadata.
    DoctorRunOptions — optional probe flags.
    run_doctor_probes — execute registered probes.
    render_doctor_report — human sectioned output.
    render_fix_lines — ``--fix`` outcome lines.
    load_solutions_catalog — bundled solutions catalog loader.
    apply_safe_fixes — whitelisted ``--fix`` handlers.
    SECTION_ORDER — canonical section banner order.
"""

from __future__ import annotations

from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.fix import FixContext, FixReport, apply_safe_fixes
from sevn.cli.doctor.probes import DoctorRunOptions, run_doctor_probes
from sevn.cli.doctor.report import render_doctor_report, render_fix_lines
from sevn.cli.doctor.sections import SECTION_ORDER
from sevn.cli.doctor.solutions import SolutionsCatalog, load_solutions_catalog

__all__ = [
    "SECTION_ORDER",
    "CheckResult",
    "DoctorCheck",
    "DoctorRunOptions",
    "FixContext",
    "FixReport",
    "SolutionsCatalog",
    "apply_safe_fixes",
    "load_solutions_catalog",
    "render_doctor_report",
    "render_fix_lines",
    "run_doctor_probes",
]
