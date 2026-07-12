"""PDF / WeasyPrint readiness probes for ``sevn doctor`` (Wave W6 / D4).

Module: sevn.pdf.doctor_check
Depends: platform, sevn.pdf.fallback_render, sevn.pdf.read, sevn.pdf.load

Exports:
    PdfDoctorRow — one doctor probe outcome for PDF readiness.
    weasyprint_native_fix_commands — OS-specific install commands for native libs.
    probe_weasyprint_render — check WeasyPrint can rasterise a trivial PDF.
    probe_pdf_optional_extra — check ``[pdf]`` extra packages for read/load scripts.

Examples:
    >>> isinstance(weasyprint_native_fix_commands(), str)
    True
"""

from __future__ import annotations

import contextlib
import io
import platform
from dataclasses import dataclass

from sevn.pdf.fallback_render import fpdf2_available
from sevn.pdf.load import openparse_available
from sevn.pdf.read import pdfplumber_available


@dataclass(frozen=True)
class PdfDoctorRow:
    """One doctor probe outcome for PDF readiness."""

    check_id: str
    ok: bool
    detail: str
    hint: str | None = None
    severity: str = "warn"


def weasyprint_native_fix_commands() -> str:
    """Return platform-specific commands to install WeasyPrint native libraries.

    Returns:
        str: Shell command(s) for the current OS family.

    Examples:
        >>> cmd = weasyprint_native_fix_commands()
        >>> "brew" in cmd or "apt-get" in cmd
        True
    """
    system = platform.system().lower()
    if system == "darwin":
        return "brew install pango"
    return (
        "apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b "
        "libcairo2 libffi8 fontconfig"
    )


def probe_weasyprint_render() -> PdfDoctorRow:
    """Probe whether WeasyPrint can render a trivial PDF (native libs present).

    Returns:
        PdfDoctorRow: ``pdf_weasyprint`` check row.

    Examples:
        >>> row = probe_weasyprint_render()
        >>> row.check_id
        'pdf_weasyprint'
    """
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from weasyprint import HTML
    except (ImportError, OSError) as exc:
        hint = weasyprint_native_fix_commands()
        fallback = (
            "fpdf2 fallback is available" if fpdf2_available() else "install fpdf2 for fallback"
        )
        return PdfDoctorRow(
            check_id="pdf_weasyprint",
            ok=False,
            detail=(f"WeasyPrint unavailable — install native libs: {hint} ({exc}); {fallback}"),
            hint=hint,
            severity="warn",
        )
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            blob = HTML(string="<p>sevn doctor probe</p>").write_pdf()
    except Exception as exc:
        hint = weasyprint_native_fix_commands()
        return PdfDoctorRow(
            check_id="pdf_weasyprint",
            ok=False,
            detail=f"WeasyPrint render failed — install native libs: {hint} ({exc})",
            hint=hint,
            severity="warn",
        )
    if not blob:
        hint = weasyprint_native_fix_commands()
        return PdfDoctorRow(
            check_id="pdf_weasyprint",
            ok=False,
            detail=f"WeasyPrint returned empty PDF — install native libs: {hint}",
            hint=hint,
            severity="warn",
        )
    return PdfDoctorRow(
        check_id="pdf_weasyprint",
        ok=True,
        detail="WeasyPrint native libs OK",
    )


def probe_pdf_optional_extra() -> PdfDoctorRow:
    """Probe optional ``[pdf]`` extra packages used by pdf_read / pdf_load scripts.

    Returns:
        PdfDoctorRow: ``pdf_extra`` check row.

    Examples:
        >>> row = probe_pdf_optional_extra()
        >>> row.check_id
        'pdf_extra'
    """
    missing: list[str] = []
    if not pdfplumber_available():
        missing.append("pdfplumber")
    if not openparse_available():
        missing.append("openparse")
    if missing:
        return PdfDoctorRow(
            check_id="pdf_extra",
            ok=False,
            detail=f"optional [pdf] packages missing: {', '.join(missing)}",
            hint="uv sync --extra pdf",
            severity="warn",
        )
    return PdfDoctorRow(
        check_id="pdf_extra",
        ok=True,
        detail="pdf_read/pdf_load optional extra installed",
    )


__all__ = [
    "PdfDoctorRow",
    "probe_pdf_optional_extra",
    "probe_weasyprint_render",
    "weasyprint_native_fix_commands",
]
