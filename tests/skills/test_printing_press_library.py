"""Tests for the ``printing-press-library`` bundled skill scripts.

All subprocess calls are mocked — no Go binaries required.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_PP_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "printing-press-library"
)
_SCRIPTS_DIR = _PP_ROOT / "scripts"


def _load_module(name: str) -> ModuleType:
    """Import a script from the printing-press-library scripts directory.

    Args:
        name (str): Script filename, e.g. ``"_pp_cli.py"``.

    Returns:
        ModuleType: Loaded module.

    Examples:
        >>> _load_module("_pp_cli.py") is not None
        True
    """
    script_path = _SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), script_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Insert scripts dir so relative imports (_pp_cli) resolve.
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# _pp_cli helpers
# ---------------------------------------------------------------------------


class TestResolveBinary:
    """Unit tests for ``_pp_cli.resolve_binary``."""

    def test_known_slug_not_installed(self) -> None:
        """Returns None when shutil.which cannot find the binary."""
        pp = _load_module("_pp_cli.py")
        with patch("shutil.which", return_value=None):
            assert pp.resolve_binary("espn") is None

    def test_known_slug_found(self) -> None:
        """Returns path string when binary is on PATH."""
        pp = _load_module("_pp_cli.py")
        with patch("shutil.which", return_value="/usr/local/bin/espn-pp-cli"):
            result = pp.resolve_binary("espn")
        assert result == "/usr/local/bin/espn-pp-cli"

    def test_unknown_slug_returns_none(self) -> None:
        """Returns None for unrecognised slug."""
        pp = _load_module("_pp_cli.py")
        assert pp.resolve_binary("nonexistent-slug") is None


class TestRunPpCli:
    """Unit tests for ``_pp_cli.run_pp_cli``."""

    def _make_proc(self, stdout: str, returncode: int = 0, stderr: str = "") -> Any:
        proc = MagicMock()
        proc.stdout = stdout
        proc.stderr = stderr
        proc.returncode = returncode
        return proc

    def test_missing_binary_returns_error_envelope(self) -> None:
        """Returns BINARY_MISSING envelope when binary is absent."""
        pp = _load_module("_pp_cli.py")
        with patch("shutil.which", return_value=None):
            result = pp.run_pp_cli("espn", ["today"])
        assert result["ok"] is False
        assert result["code"] == pp.BINARY_MISSING_CODE
        assert "espn-pp-cli" in result["error"]
        assert "make printing-press-starter-pack" in result["error"]

    def test_success_json_stdout(self) -> None:
        """Parses JSON stdout and returns ok=True envelope."""
        pp = _load_module("_pp_cli.py")
        payload = {"meta": {"source": "live"}, "results": [{"team": "Lakers"}]}
        proc = self._make_proc(json.dumps(payload))
        with (
            patch("shutil.which", return_value="/usr/bin/espn-pp-cli"),
            patch("subprocess.run", return_value=proc),
        ):
            result = pp.run_pp_cli("espn", ["scoreboard", "nba"])
        assert result["ok"] is True
        assert result["data"] == payload

    def test_success_non_json_stdout_returned_raw(self) -> None:
        """Non-JSON stdout is returned as raw string in data."""
        pp = _load_module("_pp_cli.py")
        proc = self._make_proc("plain text output")
        with (
            patch("shutil.which", return_value="/usr/bin/espn-pp-cli"),
            patch("subprocess.run", return_value=proc),
        ):
            result = pp.run_pp_cli("espn", ["standings", "nfl"])
        assert result["ok"] is True
        assert result["data"] == "plain text output"

    def test_nonzero_exit_returns_cli_error(self) -> None:
        """Non-zero exit code returns CLI_ERROR envelope with stderr."""
        pp = _load_module("_pp_cli.py")
        proc = self._make_proc("", returncode=2, stderr="usage error")
        with (
            patch("shutil.which", return_value="/usr/bin/espn-pp-cli"),
            patch("subprocess.run", return_value=proc),
        ):
            result = pp.run_pp_cli("espn", ["bad-command"])
        assert result["ok"] is False
        assert result["code"] == "CLI_ERROR"
        assert "usage error" in result["error"]

    def test_agent_flag_appended(self) -> None:
        """``--agent`` is appended to the subprocess command when not present."""
        pp = _load_module("_pp_cli.py")
        proc = self._make_proc("{}")
        with (
            patch("shutil.which", return_value="/usr/bin/espn-pp-cli"),
            patch("subprocess.run", return_value=proc) as mock_run,
        ):
            pp.run_pp_cli("espn", ["today"])
        call_args = mock_run.call_args[0][0]
        assert call_args[-1] == "--agent"

    def test_agent_flag_not_duplicated(self) -> None:
        """``--agent`` is not added twice when already in argv."""
        pp = _load_module("_pp_cli.py")
        proc = self._make_proc("{}")
        with (
            patch("shutil.which", return_value="/usr/bin/espn-pp-cli"),
            patch("subprocess.run", return_value=proc) as mock_run,
        ):
            pp.run_pp_cli("espn", ["today", "--agent"])
        call_args = mock_run.call_args[0][0]
        assert call_args.count("--agent") == 1

    def test_all_four_slugs_have_binaries(self) -> None:
        """BINARIES dict covers all four starter-pack slugs."""
        pp = _load_module("_pp_cli.py")
        for slug in ("espn", "flight_goat", "movie_goat", "recipe_goat"):
            assert slug in pp.BINARIES, f"Missing slug: {slug}"


# ---------------------------------------------------------------------------
# Individual script wrappers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "slug"),
    [
        ("espn.py", "espn"),
        ("flight_goat.py", "flight_goat"),
        ("movie_goat.py", "movie_goat"),
        ("recipe_goat.py", "recipe_goat"),
    ],
)
class TestWrapperScripts:
    """Parametrised tests for all four CLI wrapper scripts."""

    def _make_proc(self, stdout: str, returncode: int = 0) -> Any:
        proc = MagicMock()
        proc.stdout = stdout
        proc.stderr = ""
        proc.returncode = returncode
        return proc

    def test_missing_binary_writes_error_envelope(
        self, script: str, slug: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Script exits 1 and writes BINARY_MISSING envelope when binary absent."""
        mod = _load_module(script)
        with patch("shutil.which", return_value=None):
            rc = mod.main([])
        assert rc == 1
        captured = capsys.readouterr()
        envelope = json.loads(captured.out)
        assert envelope["ok"] is False
        assert envelope["code"] == "BINARY_MISSING"

    def test_success_writes_ok_envelope(
        self, script: str, slug: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Script exits 0 and writes ok=True envelope on successful CLI call."""
        mod = _load_module(script)
        payload = {"results": ["item1"]}
        proc = self._make_proc(json.dumps(payload))
        with (
            patch("shutil.which", return_value=f"/usr/bin/{slug.replace('_', '-')}-pp-cli"),
            patch("subprocess.run", return_value=proc),
        ):
            rc = mod.main(["--", "some-subcommand"])
        assert rc == 0
        captured = capsys.readouterr()
        envelope = json.loads(captured.out)
        assert envelope["ok"] is True
        assert envelope["data"] == payload

    def test_query_shorthand_forwarded(
        self, script: str, slug: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--query`` value is passed as argv to the CLI binary."""
        mod = _load_module(script)
        proc = self._make_proc("{}")
        with (
            patch("shutil.which", return_value=f"/usr/bin/{slug}-pp-cli"),
            patch("subprocess.run", return_value=proc) as mock_run,
        ):
            mod.main(["--query", "test query"])
        call_args = mock_run.call_args[0][0]
        assert "test query" in call_args


# ---------------------------------------------------------------------------
# SKILL.md structure
# ---------------------------------------------------------------------------


def test_skill_md_frontmatter() -> None:
    """SKILL.md frontmatter lists all four scripts and required fields."""
    import yaml

    skill_md = _PP_ROOT / "SKILL.md"
    assert skill_md.is_file(), "SKILL.md missing"
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---"), "SKILL.md missing frontmatter"
    parts = text.split("---", 2)
    blob = yaml.safe_load(parts[1])
    assert blob["name"] == "printing-press-library"
    scripts = {s["path"] for s in blob["scripts"]}
    assert {
        "scripts/espn.py",
        "scripts/flight_goat.py",
        "scripts/movie_goat.py",
        "scripts/recipe_goat.py",
    }.issubset(scripts)
    egress = blob.get("egress", [])
    assert "espn.com" in egress
    assert "themoviedb.org" in egress
