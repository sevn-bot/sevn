"""``sevn secret set|list|rm`` (green after W6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.canary import canary
from support.chat import arm_home

pytestmark = pytest.mark.xfail(reason="green after W6", strict=False)


def _runner() -> object:
    from typer.testing import CliRunner

    return CliRunner()


def _app() -> object:
    from sevn.cli import app

    return app


def test_secret_set_reads_without_echo_and_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.config import Settings
    from sevn.log import logger
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    arm_home(monkeypatch, tmp_path)
    with canary() as probe:

        def _getpass(*_args: object, **_kwargs: object) -> str:
            return probe.value

        monkeypatch.setattr("getpass.getpass", _getpass)
        import sevn.cli as cli

        if hasattr(cli, "getpass"):
            monkeypatch.setattr(cli, "getpass", _getpass)
        sink: list[str] = []
        sink_id = logger.add(lambda message: sink.append(str(message)))
        try:
            result = _runner().invoke(  # type: ignore[attr-defined]
                _app(),
                ["secret", "set", "provider/anthropic"],
            )
        finally:
            logger.remove(sink_id)
        assert result.exit_code == 0, result.output
        output = f"{result.stdout}\n{result.stderr or ''}\n{result.output}"
        assert probe.value not in output
        assert probe.value not in "\n".join(sink)
        stored = open_backend(Settings.load(), Paths.from_env()).get("provider/anthropic")
        assert stored == probe.value
        probe.assert_absent(probe.value)


def test_secret_list_shows_names_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    arm_home(monkeypatch, tmp_path)
    with canary() as probe:
        open_backend(Settings.load(), Paths.from_env()).set("provider/openai", probe.value)
        result = _runner().invoke(_app(), ["secret", "list"])  # type: ignore[attr-defined]
        assert result.exit_code == 0, result.output
        assert "provider/openai" in result.output
        assert probe.value not in result.output
        probe.assert_absent(probe.value)


def test_secret_rm_removes_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend
    from sevn.secrets.errors import SecretNotFound

    arm_home(monkeypatch, tmp_path)
    with canary() as probe:
        backend = open_backend(Settings.load(), Paths.from_env())
        backend.set("provider/google", probe.value)
        result = _runner().invoke(  # type: ignore[attr-defined]
            _app(),
            ["secret", "rm", "provider/google"],
        )
        assert result.exit_code == 0, result.output
        assert probe.value not in result.output
        with pytest.raises(SecretNotFound, match=r"^secret not found: provider/google$"):
            backend.get("provider/google")
