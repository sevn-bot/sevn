"""Bundled ``pdf`` skill script subprocess tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from sevn.ui.openui.rasteriser import rasterise_pdf_bytes

_PDF_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "pdf"
)
_SCRIPTS = _PDF_ROOT / "scripts"


def _import_script_main(script_name: str):
    """Load a bundled pdf script module and return its ``main`` callable."""
    script_path = _SCRIPTS / script_name
    module_name = f"sevn_pdf_skill_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main = getattr(module, "main", None)
    assert callable(main)
    return main


def _fixture_pdf_bytes(*, text: str = "Hello PDF fixture") -> bytes:
    """Build minimal PDF bytes for subprocess tests.

    Args:
        text (str, optional): Visible text embedded in the PDF. Defaults to ``Hello PDF fixture``.

    Returns:
        bytes: PDF document bytes.

    Raises:
        pytest.SkipException: When WeasyPrint is unavailable in the test environment.
    """
    blob = rasterise_pdf_bytes(f"<p>{text}</p>")
    if not blob:
        pytest.skip("weasyprint unavailable")
    return blob


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str],
) -> tuple[int, dict[str, object]]:
    """Run one bundled pdf script and parse its JSON stdout envelope.

    Args:
        script_name (str): Script filename under ``scripts/``.
        workspace (Path): Workspace root for ``SEVN_WORKSPACE``.
        cli_args (list[str]): Arguments after the script path.

    Returns:
        tuple[int, dict[str, object]]: Exit code and parsed JSON envelope.
    """
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(script), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = cast("dict[str, object]", json.loads(proc.stdout.strip() or "{}"))
    return proc.returncode, payload


def test_pdf_render_markdown_writes_file(tmp_path: Path) -> None:
    """``pdf.py`` renders markdown to a workspace-relative PDF."""
    if not rasterise_pdf_bytes("<p>probe</p>"):
        pytest.skip("weasyprint unavailable")
    code, payload = _run_script(
        "pdf.py",
        tmp_path,
        ["--out", "out/report.pdf", "--markdown", "# Title\n\nBody text"],
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("output_path") == "out/report.pdf"
    out_file = tmp_path / "out" / "report.pdf"
    assert out_file.is_file()
    assert out_file.stat().st_size > 0


def test_pdf_render_unicode_markdown_via_fpdf2_fallback(tmp_path: Path) -> None:
    """``pdf.py`` renders em-dash / CJK markdown via fpdf2 fallback without crashing."""
    code, payload = _run_script(
        "pdf.py",
        tmp_path,
        [
            "--out",
            "out/unicode.pdf",
            "--markdown",
            "# Report\n\nIntro \u2014 body\n\n\u4e2d\u6587",
        ],
    )
    assert code == 0
    assert payload.get("ok") is True
    out_file = tmp_path / "out" / "unicode.pdf"
    assert out_file.is_file()
    assert out_file.stat().st_size > 0


def test_pdf_render_stdout_is_clean_json_without_weasyprint_natives(tmp_path: Path) -> None:
    """``pdf.py`` stdout stays a single JSON envelope even when WeasyPrint natives are absent.

    WeasyPrint prints a "could not import some external libraries" banner to **stdout**
    on a failed native-lib import; unmuted, it corrupted the skill's JSON-on-stdout
    contract so a successful fpdf2 fallback was still misreported to the agent (P3,
    ``plan/live-session-pdf-render-grounding-failures-plan.md``). ASCII markdown renders
    via the pure-Python fpdf2 fallback on any host, so this runs without WeasyPrint.
    """
    script = _SCRIPTS / "pdf.py"
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(script), "--out", "out/report.pdf", "--markdown", "# Title\n\nBody"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    out = proc.stdout.strip()
    # No banner leakage: stdout is exactly one JSON object, parseable as-is.
    assert out.startswith("{"), f"stdout not clean JSON: {out!r}"
    assert out.endswith("}"), f"stdout not clean JSON: {out!r}"
    assert "WeasyPrint could not import" not in proc.stdout
    payload = cast("dict[str, object]", json.loads(out))
    assert payload.get("ok") is True
    assert (tmp_path / "out" / "report.pdf").stat().st_size > 0


def test_pdf_read_extracts_text(tmp_path: Path) -> None:
    """``pdf_read.py`` returns text from a fixture PDF when pdfplumber is installed."""
    from sevn.pdf.read import pdfplumber_available

    if not pdfplumber_available():
        pytest.skip("pdfplumber not installed")

    fixture = tmp_path / "sample.pdf"
    fixture.write_bytes(_fixture_pdf_bytes(text="AlphaBetaGamma"))
    code, payload = _run_script("pdf_read.py", tmp_path, ["--path", "sample.pdf"])
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert "AlphaBetaGamma" in str(data.get("text", ""))


def test_pdf_read_missing_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``pdf_read.py`` returns dependency envelope when pdfplumber is absent."""
    monkeypatch.setattr("sevn.pdf.read.pdfplumber_available", lambda: False)
    monkeypatch.setenv("SEVN_WORKSPACE", str(tmp_path))
    fixture = tmp_path / "sample.pdf"
    fixture.write_bytes(b"%PDF-1.4\n")
    main = _import_script_main("pdf_read.py")
    code = main(["--path", "sample.pdf"])
    captured = capsys.readouterr()
    payload = cast("dict[str, object]", json.loads(captured.out.strip()))
    assert code != 0
    assert payload.get("ok") is False
    assert payload.get("code") == "DEPENDENCY_MISSING"
    assert "pdfplumber" in str(payload.get("error", ""))


def test_pdf_load_missing_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``pdf_load.py`` returns dependency envelope when openparse is absent."""
    monkeypatch.setattr("sevn.pdf.load.openparse_available", lambda: False)
    monkeypatch.setenv("SEVN_WORKSPACE", str(tmp_path))
    fixture = tmp_path / "sample.pdf"
    fixture.write_bytes(b"%PDF-1.4\n")
    main = _import_script_main("pdf_load.py")
    code = main(["--path", "sample.pdf"])
    captured = capsys.readouterr()
    payload = cast("dict[str, object]", json.loads(captured.out.strip()))
    assert code != 0
    assert payload.get("ok") is False
    assert payload.get("code") == "DEPENDENCY_MISSING"
    assert "openparse" in str(payload.get("error", ""))


def test_pdf_load_parses_fixture(tmp_path: Path) -> None:
    """``pdf_load.py`` returns structured nodes when openparse is installed."""
    from sevn.pdf.load import openparse_available

    if not openparse_available():
        pytest.skip("openparse not installed")

    fixture = tmp_path / "sample.pdf"
    fixture.write_bytes(_fixture_pdf_bytes(text="ChunkMe"))
    code, payload = _run_script("pdf_load.py", tmp_path, ["--path", "sample.pdf"])
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    nodes = data.get("nodes")
    assert isinstance(nodes, list)
    assert len(nodes) >= 1


def test_resolve_path_under_shadow_symlink_farm(tmp_path: Path) -> None:
    """Relative paths must resolve under a symlink-farm shadow workspace.

    Regression for the live-session failure: skill scripts run in a shadow
    workspace whose top-level entries are symlinks back into the real
    workspace. ``Path.resolve`` would follow ``out`` out of the shadow root and
    raise a spurious "escapes workspace root" for every legitimate path, making
    the pdf skill's documented recipe impossible.
    """
    from sevn.pdf.paths import resolve_path_under_workspace

    real = tmp_path / "real"
    (real / "out").mkdir(parents=True)
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "out").symlink_to(real / "out")

    resolved = resolve_path_under_workspace(shadow, "out/page.pdf")
    assert resolved == shadow.resolve() / "out" / "page.pdf"
    # The returned path stays relative to the shadow workspace (callers rely on
    # ``relative_to(workspace)``), and writes through the symlink to the real ws.
    assert resolved.relative_to(shadow.resolve()) == Path("out/page.pdf")
    resolved.write_bytes(b"%PDF-1.4\n")
    assert (real / "out" / "page.pdf").read_bytes() == b"%PDF-1.4\n"


def test_resolve_path_rejects_parent_traversal(tmp_path: Path) -> None:
    """Lexical ``..`` traversal above the workspace root is still rejected."""
    from sevn.pdf.paths import resolve_path_under_workspace

    with pytest.raises(ValueError, match="escapes workspace root"):
        resolve_path_under_workspace(tmp_path, "../../etc/passwd")
