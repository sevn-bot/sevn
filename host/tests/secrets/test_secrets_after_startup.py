"""Secret Service failures after startup stay typed (plan 0025 D13, WV F1).

The host starts on the age file; each test then points ``secrets.backend`` at
``secret-service`` backed by a ``FakeKeyring`` and breaks it (locked: ``KeyringLocked``;
unavailable: ``InitError``). Protocol calls must answer ``secrets_locked`` /
``secrets_unavailable`` instead of ``internal``; background secret readers (jev routing,
``noul_score``, the compaction model pick) treat the store as unavailable, log a warning
without any value, and do not raise.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_keyring import FakeKeyring
from support.canary import canary
from support.chat import connected, error_body, load_modules, mint_id, ok, request

_WV_R = pytest.mark.xfail(strict=False, reason="green after WV-R")

_STATES = [
    pytest.param("locked", "secrets_locked", id="locked"),
    pytest.param("unavailable", "secrets_unavailable", id="unavailable"),
]


def _break(ring: FakeKeyring, state: str) -> None:
    if state == "locked":
        ring.locked = True
    else:
        ring.unavailable = True


@pytest.fixture
def ring() -> Iterator[FakeKeyring]:
    from sevn.secrets.backends import use_keyring

    fake = FakeKeyring()
    use_keyring(fake)
    try:
        yield fake
    finally:
        use_keyring(None)


def _use_secret_service(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "secret-service")
    (home / "config.toml").write_text('[secrets]\nbackend = "secret-service"\n', encoding="utf-8")


def _arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from support.chat import arm_home

    arm_home(monkeypatch, tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    _use_secret_service(tmp_path, monkeypatch)
    return tmp_path


class _Logs:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def __call__(self, message: Any) -> None:
        record = message.record
        self.records.append((record["level"].name, str(message)))

    def text(self) -> str:
        return "\n".join(line for _level, line in self.records)

    def warnings(self) -> list[str]:
        return [line for level, line in self.records if level == "WARNING"]


@pytest.fixture
def logs() -> Iterator[_Logs]:
    from sevn.log import logger

    sink = _Logs()
    sink_id = logger.add(sink, level="DEBUG")
    try:
        yield sink
    finally:
        logger.remove(sink_id)


# --- protocol calls ----------------------------------------------------------


@_WV_R
@pytest.mark.parametrize(("state", "code"), _STATES)
async def test_models_list_reports_a_typed_secrets_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ring: FakeKeyring,
    state: str,
    code: str,
) -> None:
    load_modules("sevn.api.models", "sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        _use_secret_service(tmp_path, monkeypatch)
        _break(ring, state)
        listed, _earlier = await request(client, "models.list", {})
        assert error_body(listed)["code"] == code

        ring.locked = False
        ring.unavailable = False
        recovered, _earlier = await request(client, "models.list", {})
        assert isinstance(ok(recovered)["models"], list)


@_WV_R
@pytest.mark.parametrize(("state", "code"), _STATES)
async def test_bots_create_reports_a_typed_secrets_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ring: FakeKeyring,
    state: str,
    code: str,
) -> None:
    load_modules("sevn.api.models", "sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        _use_secret_service(tmp_path, monkeypatch)
        _break(ring, state)
        created, _earlier = await request(
            client,
            "bots.create",
            {"name": "Locked", "runtime": "pydantic_ai", "op_id": mint_id("op_")},
        )
        body = error_body(created)
        assert body["code"] == code
        assert body["code"] != "internal"


# --- model key lookups -------------------------------------------------------


@pytest.mark.parametrize(("state", "code"), _STATES)
def test_resolving_a_keyed_model_fails_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ring: FakeKeyring, state: str, code: str
) -> None:
    from sevn.runtime.models import first_catalog_id, resolve_model, use_model
    from sevn.secrets.errors import SecretsBackendError

    _arm(tmp_path, monkeypatch)
    use_model(None)
    model_id = first_catalog_id("anthropic")
    _break(ring, state)
    with pytest.raises(SecretsBackendError) as caught:
        resolve_model(model_id)
    assert caught.value.code == code


@_WV_R
@pytest.mark.parametrize(("state", "_code"), _STATES)
def test_cheapest_configured_model_treats_the_store_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ring: FakeKeyring,
    logs: _Logs,
    state: str,
    _code: str,
) -> None:
    from sevn.runtime.models import cheapest_configured_model

    _arm(tmp_path, monkeypatch)
    _break(ring, state)
    assert cheapest_configured_model() is None
    assert logs.warnings(), "the fall-through is logged as a warning"


# --- jev routing -------------------------------------------------------------


@pytest.fixture
def jev_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ring: FakeKeyring) -> Iterator[Any]:
    from sevn.decisions import jev

    _arm(tmp_path, monkeypatch)
    jev.use_client(None)
    try:
        yield jev
    finally:
        jev.use_client(None)


def _context() -> Any:
    from sevn.domain.routing import RouterContext

    return RouterContext(
        bot_id="bot_1",
        open_agents=[],
        pending_questions=[],
        recent_user_messages={},
        runtime="pydantic_ai",
    )


@_WV_R
@pytest.mark.parametrize(("state", "code"), _STATES)
async def test_jev_routing_treats_the_store_as_unavailable(
    jev_home: Any, ring: FakeKeyring, logs: _Logs, state: str, code: str
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    with canary() as probe:
        open_backend(Settings.load(), Paths.from_env()).set("provider/typesafe", probe.value)
        _break(ring, state)

        assert await jev_home.noul_score("relevance", "score it", "hello") is None
        assert await jev_home.JevDecider().attempt(_context(), "hello") is None

        warnings = logs.warnings()
        assert warnings, "the unavailable store is logged as a warning"
        assert any(code in line for line in warnings), warnings
        assert probe.value not in logs.text()
        probe.assert_absent(probe.value)


async def test_jev_still_uses_the_key_when_the_store_answers(
    jev_home: Any, ring: FakeKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guards the fall-through above against swallowing a healthy store.
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    seen: list[str] = []

    class _Client:
        def __init__(self, *, api_key: str, model: str | None = None) -> None:
            seen.append(api_key)

    monkeypatch.setattr("sevn.decisions.jev.AsyncTypeSafeClient", _Client)
    key = secrets.token_urlsafe(16)
    open_backend(Settings.load(), Paths.from_env()).set("provider/typesafe", key)
    client = await jev_home._resolve_client()
    assert client is not None
    assert seen == [key]
