"""Redacting loguru setup (D17, spec §12)."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def captured_log(tmp_path: Path) -> Iterator[tuple[list[object], Path]]:
    from sevn.log import logger, setup

    logger.remove()
    log_path = tmp_path / "sevnd.log"
    setup(level="DEBUG", json_file=log_path)
    found: list[object] = []
    sink_id = logger.add(lambda message: found.append(message))
    try:
        yield found, log_path
    finally:
        logger.remove(sink_id)
        logger.complete()


def _secret(kind: str) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def chunk(size: int, symbols: str = alphabet) -> str:
        return "".join(secrets.choice(symbols) for _ in range(size))

    if kind == "openai":
        return "sk-" + chunk(20)
    if kind == "anthropic":
        return "sk-ant-" + chunk(20)
    if kind == "github":
        return "ghp_" + chunk(20)
    if kind == "slack":
        return "xoxb-" + chunk(12)
    if kind == "bearer":
        return "Bearer " + chunk(12)
    if kind == "aws":
        return "AKIA" + chunk(16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    raise AssertionError(kind)


def _assert_marker(
    found: list[object],
    log_path: Path,
    value: str,
    marker: str,
) -> None:
    messages: list[str] = []
    extras: list[str] = []
    formatted: list[str] = []
    for item in found:
        record = item.record  # type: ignore[attr-defined]
        messages.append(str(record["message"]))
        extras.append(str(record["extra"]))
        formatted.append(str(item))
    file_text = log_path.read_text(encoding="utf-8")
    blob = "\n".join([*messages, *extras, *formatted, file_text])
    assert value not in blob
    assert any(marker in part for part in messages)
    assert any(marker in part for part in extras)
    assert marker in file_text


@pytest.mark.parametrize("kind", ["openai", "anthropic", "github", "slack", "bearer", "aws"])
def test_redacts_patterns(
    kind: str,
    captured_log: tuple[list[object], Path],
) -> None:
    from sevn.log import logger

    found, log_path = captured_log
    value = _secret(kind)
    logger.bind(leak=value).warning("seen " + value)
    logger.complete()
    _assert_marker(found, log_path, value, "«redacted»")


def test_redacts_registered_secret(
    captured_log: tuple[list[object], Path],
) -> None:
    from sevn.log import logger
    from sevn.secrets.registry import register

    found, log_path = captured_log
    value = secrets.token_urlsafe(24)
    register("opencode/api_key", value)
    logger.bind(leak=value).warning("seen " + value)
    logger.complete()
    _assert_marker(found, log_path, value, "«redacted:opencode/api_key»")


def test_stdlib_logging_is_intercepted(captured_log: tuple[list[object], Path]) -> None:
    found, _log_path = captured_log
    logging.getLogger("uvicorn.error").warning("hi")
    matched = [
        item
        for item in found
        if item.record["name"] == "uvicorn.error" and "hi" in str(item)  # type: ignore[attr-defined]
    ]
    assert matched


def test_contextualize_binds_ids(captured_log: tuple[list[object], Path]) -> None:
    from sevn.log import logger

    found, _log_path = captured_log
    with logger.contextualize(bot_id="bot_1", agent_id="agent_2"):
        logger.info("bound")
    extra = found[-1].record["extra"]  # type: ignore[attr-defined]
    assert extra["bot_id"] == "bot_1"
    assert extra["agent_id"] == "agent_2"


def test_exception_text_is_redacted(captured_log: tuple[list[object], Path]) -> None:
    from sevn.log import logger
    from sevn.secrets.registry import register

    _found, log_path = captured_log
    value = secrets.token_urlsafe(24)
    register("opencode/api_key", value)
    try:
        raise RuntimeError(value)
    except RuntimeError:
        logger.exception("boom {secret}", secret=value)
    logger.complete()
    text = log_path.read_text(encoding="utf-8")
    assert value not in text
    assert "«redacted:opencode/api_key»" in text
    payload = json.loads(text.splitlines()[-1])
    assert "exception" in payload
    assert value not in payload["exception"]


def test_nested_extra_is_redacted(captured_log: tuple[list[object], Path]) -> None:
    from sevn.log import logger
    from sevn.secrets.registry import register

    found, log_path = captured_log
    value = secrets.token_urlsafe(24)
    register("opencode/api_key", value)
    logger.bind(nested={"token": value}).warning("nested")
    logger.complete()
    text = log_path.read_text(encoding="utf-8")
    extra = str(found[-1].record["extra"])  # type: ignore[attr-defined]
    assert value not in text
    assert value not in extra
    assert "«redacted:opencode/api_key»" in text
    assert "«redacted:opencode/api_key»" in extra


def test_json_file_lines(captured_log: tuple[list[object], Path]) -> None:
    from sevn.log import logger

    _found, log_path = captured_log
    logger.info("line-one")
    logger.complete()
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    for line in lines:
        payload = json.loads(line)
        assert {"time", "level", "message", "extra"} <= set(payload)
