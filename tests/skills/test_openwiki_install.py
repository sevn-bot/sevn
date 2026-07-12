"""Tests for ``sevn.skills.openwiki_install``."""

from __future__ import annotations

from unittest.mock import patch

from sevn.skills.openwiki_install import (
    check_node_for_openwiki,
    openwiki_cli_installed,
    run_openwiki_install,
)


def test_openwiki_cli_installed_is_bool() -> None:
    assert isinstance(openwiki_cli_installed(), bool)


def test_check_node_for_openwiki_when_node_missing() -> None:
    with patch("sevn.skills.openwiki_install.shutil.which", return_value=None):
        ok, detail = check_node_for_openwiki()
    assert ok is False
    assert "node not found" in detail


def test_run_openwiki_install_skips_when_already_installed() -> None:
    with patch("sevn.skills.openwiki_install.openwiki_cli_installed", return_value=True):
        code, detail = run_openwiki_install(skip_if_installed=True)
    assert code == 0
    assert "already on PATH" in detail


def test_run_openwiki_install_fails_without_node() -> None:
    with (
        patch("sevn.skills.openwiki_install.openwiki_cli_installed", return_value=False),
        patch(
            "sevn.skills.openwiki_install.check_node_for_openwiki", return_value=(False, "no node")
        ),
    ):
        code, detail = run_openwiki_install(skip_if_installed=True)
    assert code == 1
    assert detail == "no node"
