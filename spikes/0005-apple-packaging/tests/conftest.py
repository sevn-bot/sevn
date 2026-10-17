"""Spike packaging tests. Live checks stay out of the default run."""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests marked live",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: operator session or paid Apple credentials; excluded unless SEVN_LIVE=1 or --live",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live") or os.environ.get("SEVN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test excluded unless SEVN_LIVE=1 or --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
