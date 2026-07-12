"""Doctor PDF / WeasyPrint readiness probes (Wave W6)."""

from __future__ import annotations

from sevn.pdf.doctor_check import (
    probe_pdf_optional_extra,
    probe_weasyprint_render,
    weasyprint_native_fix_commands,
)


def test_weasyprint_fix_commands_platform_specific() -> None:
    cmd = weasyprint_native_fix_commands()
    assert "brew install pango" in cmd or "apt-get install" in cmd


def test_probe_weasyprint_render_returns_row() -> None:
    row = probe_weasyprint_render()
    assert row.check_id == "pdf_weasyprint"
    assert isinstance(row.ok, bool)
    assert row.detail
    if not row.ok:
        assert row.hint
        assert "install native libs:" in row.detail
        assert row.hint in row.detail


def test_probe_pdf_optional_extra_returns_row() -> None:
    row = probe_pdf_optional_extra()
    assert row.check_id == "pdf_extra"
    assert isinstance(row.ok, bool)
