"""WeasyPrint native library install helpers (P8 onboarding)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sevn.onboarding.live_validate import probe_pdf_weasyprint
from sevn.pdf.doctor_check import PdfDoctorRow
from sevn.pdf.native_libs import (
    install_weasyprint_native_libs,
    maybe_install_pdf_native_libs_after_promote,
)


def test_probe_pdf_weasyprint_returns_validation_check() -> None:
    chk = probe_pdf_weasyprint()
    assert chk.check_id == "pdf_weasyprint"
    assert isinstance(chk.ok, bool)
    assert chk.detail
    if not chk.ok:
        assert chk.severity == "warn"
        assert chk.hint


def test_install_skips_when_weasyprint_already_ok() -> None:
    ok_row = PdfDoctorRow(
        check_id="pdf_weasyprint",
        ok=True,
        detail="WeasyPrint native libs OK",
    )
    with patch("sevn.pdf.native_libs.probe_weasyprint_render", return_value=ok_row):
        ok, detail = install_weasyprint_native_libs()
    assert ok is True
    assert "already OK" in detail


def test_install_runs_brew_on_darwin_when_missing(monkeypatch) -> None:
    fail_row = PdfDoctorRow(
        check_id="pdf_weasyprint",
        ok=False,
        detail="WeasyPrint unavailable",
        hint="brew install pango",
    )
    ok_row = PdfDoctorRow(
        check_id="pdf_weasyprint",
        ok=True,
        detail="WeasyPrint native libs OK",
    )
    calls = {"n": 0}

    def _probe() -> PdfDoctorRow:
        calls["n"] += 1
        return ok_row if calls["n"] > 1 else fail_row

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""
    mock_proc.stdout = ""

    monkeypatch.setattr("sevn.pdf.native_libs.platform.system", lambda: "Darwin")
    monkeypatch.setattr("sevn.pdf.native_libs.shutil.which", lambda cmd: "/opt/homebrew/bin/brew")
    monkeypatch.setattr("sevn.pdf.native_libs.probe_weasyprint_render", _probe)
    monkeypatch.setattr("sevn.pdf.native_libs.subprocess.run", lambda *a, **k: mock_proc)

    ok, detail = install_weasyprint_native_libs()
    assert ok is True
    assert "brew install pango" in detail


def test_maybe_install_skips_non_darwin(monkeypatch) -> None:
    monkeypatch.setattr("sevn.pdf.native_libs.platform.system", lambda: "Linux")
    assert maybe_install_pdf_native_libs_after_promote() is None


def test_maybe_install_skips_when_probe_ok(monkeypatch) -> None:
    ok_row = PdfDoctorRow(
        check_id="pdf_weasyprint",
        ok=True,
        detail="WeasyPrint native libs OK",
    )
    monkeypatch.setattr("sevn.pdf.native_libs.platform.system", lambda: "Darwin")
    monkeypatch.setattr("sevn.pdf.native_libs.probe_weasyprint_render", lambda: ok_row)
    assert maybe_install_pdf_native_libs_after_promote() is None


def test_maybe_install_attempts_brew_on_darwin_when_degraded(
    monkeypatch,
) -> None:
    fail_row = PdfDoctorRow(
        check_id="pdf_weasyprint",
        ok=False,
        detail="WeasyPrint unavailable",
        hint="brew install pango",
    )
    monkeypatch.setattr("sevn.pdf.native_libs.platform.system", lambda: "Darwin")
    monkeypatch.setattr("sevn.pdf.native_libs.probe_weasyprint_render", lambda: fail_row)
    monkeypatch.setattr(
        "sevn.pdf.native_libs.install_weasyprint_native_libs",
        lambda **_: (True, "installed WeasyPrint native libs via brew install pango"),
    )
    line = maybe_install_pdf_native_libs_after_promote()
    assert line == "installed WeasyPrint native libs via brew install pango"
