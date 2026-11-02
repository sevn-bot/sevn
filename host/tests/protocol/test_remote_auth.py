"""Non-loopback sessions: challenge, device auth, scopes and revocation (plan 0055 D2, D3).

Pinned for W3 (see ``.ignorelocal/test-plans/0055-direct-multi-host.md``):
- ``Session(connection, hub, *, token, queue_limit, cookie=None, loopback, allowed_hosts)``;
  a ``loopback=False`` session never takes the token or cookie path.
- After ``hello`` a non-loopback session gets ``challenge{nonce, host, host_sig}``; the device
  answers ``auth{device_sig}``; ``hello.device`` names the device, ``hello.origin`` the origin.
- Every refusal closes 4001 ``unauthorized``; a revoke closes live sessions 4003 ``revoked``.
- The session draws nonces from ``sevn.identity.handshake.new_nonce`` (module attribute).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from support.memory import (
    MemoryHost,
    collect_until_close,
    handshake,
    hello_frame,
    memory_host,
    recv_frame,
    send_frame,
)
from support.pairing import (
    ORIGIN,
    Device,
    authenticate,
    call,
    hello,
    new_device,
    op_id,
    owner_client,
    pair_device,
    register_methods,
    sign_auth,
    unb64u,
    verify_host_sig,
)


@asynccontextmanager
async def _host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[MemoryHost]:
    async with memory_host(tmp_path, monkeypatch) as host:
        register_methods()
        yield host


async def _answer(client: Any, host: MemoryHost, device: Device, *, signed_origin: str) -> None:
    """Read the challenge (if the host sends one before closing) and sign it."""
    from sevn.transports.base import ConnectionClosed

    try:
        challenge = await recv_frame(client)
    except ConnectionClosed:
        return
    if challenge.get("t") != "challenge":
        return
    nonce = unb64u(challenge["nonce"])
    sig = sign_auth(device.key, nonce, signed_origin, host.hub.identity.host_pubkey_fp)
    await send_frame(client, {"t": "auth", "device_sig": sig})


async def _refused(client: Any) -> None:
    frames, closed = await collect_until_close(client)
    assert (closed.code, closed.reason) == (4001, "unauthorized")
    assert all(frame.get("t") != "welcome" for frame in frames), frames


async def test_non_loopback_session_gets_challenge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner)
        nonces: list[bytes] = []
        for _ in range(2):
            client, session = host.open_remote()
            await send_frame(client, hello(device.id))
            challenge = await recv_frame(client)
            assert challenge["t"] == "challenge"
            assert challenge["host"] == host.hub.identity.host_id
            nonce = unb64u(challenge["nonce"])
            assert len(nonce) == 32
            verify_host_sig(host.hub.identity.public_key, nonce, ORIGIN, challenge["host_sig"])
            assert session.scope != "owner"
            nonces.append(nonce)
        assert nonces[0] != nonces[1]


async def test_loopback_token_is_refused_on_a_non_loopback_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: a proxied or remote session never takes the loopback token path."""
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner)
        client, session = host.open_remote()
        await send_frame(client, hello(device.id))
        assert (await recv_frame(client))["t"] == "challenge"
        await send_frame(client, {"t": "auth", "token": host.token})
        await _refused(client)
        assert session.scope != "owner"


async def test_loopback_cookie_does_not_open_a_non_loopback_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        client, session = host.open_remote(cookie=host.token)
        await send_frame(client, hello("dev_cookie"))
        first = await recv_frame(client)
        assert first["t"] == "challenge", first
        assert session.scope != "owner"


@pytest.mark.parametrize("scope", ["owner", "member", "read_only"])
async def test_valid_device_auth_sets_device_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner, scope=scope)
        client, session = host.open_remote()
        welcome = await authenticate(host, client, device)
        assert welcome["t"] == "welcome", welcome
        assert session.scope == scope
        me = await call(client, "devices.self", {})
        assert me["r"]["id"] == device.id
        assert me["r"]["scope"] == scope
        owner_only = await call(client, "devices.list", {})
        if scope == "owner":
            assert "r" in owner_only, owner_only
        else:
            assert owner_only["e"]["code"] == "forbidden"
        listed = await call(owner, "devices.list", {})
        row = next(item for item in listed["r"]["devices"] if item["id"] == device.id)
        assert row["last_seen"] is not None


async def _bad_sig(host: MemoryHost, owner: Any) -> Device:
    device = await pair_device(host, owner)
    return Device(key=Ed25519PrivateKey.generate(), id=device.id, scope=device.scope)


async def _unknown(_host: MemoryHost, _owner: Any) -> Device:
    stranger = new_device()
    stranger.id = "dev_01J00000000000000000000000"
    return stranger


async def _revoked(host: MemoryHost, owner: Any) -> Device:
    device = await pair_device(host, owner)
    res = await call(owner, "devices.revoke", {"id": device.id, "op_id": op_id()})
    assert res["r"]["revoked_at"] is not None
    return device


@pytest.mark.parametrize(
    "make_device", [_bad_sig, _unknown, _revoked], ids=["bad-sig", "unknown-device", "revoked"]
)
async def test_bad_sig_unknown_revoked_device_close_4001(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_device: Any
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await make_device(host, owner)
        client, session = host.open_remote()
        await send_frame(client, hello(device.id))
        await _answer(client, host, device, signed_origin=ORIGIN)
        await _refused(client)
        assert session.scope != "owner"


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("wss://evil.example", ("mac.tailnet.ts.net",)),
        (None, ("mac.tailnet.ts.net",)),
        ("wss://mac.tailnet.ts.net.evil.example", ("mac.tailnet.ts.net",)),
        ("ws://100.101.102.103:9999", ("100.101.102.103:8787",)),
    ],
    ids=["foreign-host", "no-origin", "suffix-trick", "wrong-port"],
)
async def test_origin_not_in_allowed_hosts_closes_4001(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    origin: str | None,
    allowed: tuple[str, ...],
) -> None:
    """The device signs correctly for the origin it sent; only the origin rule refuses it."""
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner)
        client, _session = host.open_remote(allowed_hosts=allowed)
        await send_frame(client, hello(device.id, origin))
        await _answer(client, host, device, signed_origin=origin if origin is not None else "")
        await _refused(client)


async def test_allowed_host_with_port_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner)
        client, _session = host.open_remote(allowed_hosts=("100.101.102.103:8787",))
        welcome = await authenticate(host, client, device, origin="ws://100.101.102.103:8787")
        assert welcome["t"] == "welcome"


async def test_nonce_reuse_closes_4001(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sevn.identity.handshake as handshake_module

    fixed = b"sevn-test-fixed-nonce-0000000001"
    monkeypatch.setattr(handshake_module, "new_nonce", lambda: fixed)
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner)
        first, _ = host.open_remote()
        await send_frame(first, hello(device.id))
        challenge = await recv_frame(first)
        assert unb64u(challenge["nonce"]) == fixed, "the session must draw handshake.new_nonce()"
        sig = sign_auth(device.key, fixed, ORIGIN, host.hub.identity.host_pubkey_fp)
        await send_frame(first, {"t": "auth", "device_sig": sig})
        assert (await recv_frame(first))["t"] == "welcome"
        # The same nonce again within 10 minutes: refused although the signature is valid.
        second, session = host.open_remote()
        await send_frame(second, hello(device.id))
        await _answer(second, host, device, signed_origin=ORIGIN)
        await _refused(second)
        assert session.scope != "owner"


async def test_revoke_closes_live_sessions_within_1s_with_4003(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        phone = await pair_device(host, owner, name="Phone")
        laptop = await pair_device(host, owner, name="Laptop")
        phone_a, _ = host.open_remote()
        phone_b, _ = host.open_remote()
        other, _ = host.open_remote()
        for client, device in ((phone_a, phone), (phone_b, phone), (other, laptop)):
            assert (await authenticate(host, client, device))["t"] == "welcome"
        res = await call(owner, "devices.revoke", {"id": phone.id, "op_id": op_id()})
        assert res["r"]["revoked_at"] is not None
        for client in (phone_a, phone_b):
            closed = await asyncio.wait_for(client.wait_closed(), 1.0)
            assert closed == (4003, "revoked")
        still = await call(other, "devices.self", {})
        assert still["r"]["id"] == laptop.id
        again, _ = host.open_remote()
        await send_frame(again, hello(phone.id))
        await _answer(again, host, phone, signed_origin=ORIGIN)
        await _refused(again)


async def test_token_and_cookie_paths_unchanged_for_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loopback sessions keep the token and cookie paths byte for byte, with no challenge."""
    from sevn.protocol.session import Session
    from sevn.transports.memory import pair

    async with _host(tmp_path, monkeypatch) as host:

        def open_loopback(cookie: str | None) -> tuple[Any, Any]:
            client, server = pair()
            session = Session(
                server,
                host.hub,
                token=host.token,
                queue_limit=host.queue_limit,
                cookie=cookie,
                loopback=True,
            )
            host.tasks.append(asyncio.create_task(session.run()))
            host.clients.append(client)
            return client, session

        token_client, token_session = open_loopback(None)
        welcome = await handshake(token_client, host.token)
        assert welcome["t"] == "welcome"
        assert token_session.scope == "owner"

        cookie_client, cookie_session = open_loopback(host.token)
        await send_frame(cookie_client, hello_frame())
        assert (await recv_frame(cookie_client))["t"] == "welcome"
        assert cookie_session.scope == "owner"

        bad_cookie, _ = open_loopback("not-the-token")
        await send_frame(bad_cookie, hello_frame())
        await _refused(bad_cookie)


@pytest.mark.parametrize(
    "origin",
    ["wss://evil.example", "wss://mac.tailnet.ts.net.evil.example", None],
    ids=["foreign-host", "suffix-trick", "no-origin"],
)
async def test_unallowed_origin_challenge_is_not_a_signing_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str | None
) -> None:
    """A challenge sent for an unallowed origin (a decoy) carries no valid host signature.

    Otherwise anyone could make the host sign challenges for an origin of their choosing.
    """
    from cryptography.exceptions import InvalidSignature
    from sevn.transports.base import ConnectionClosed

    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        device = await pair_device(host, owner)
        client, session = host.open_remote()
        await send_frame(client, hello(device.id, origin))
        try:
            challenge = await recv_frame(client)
        except ConnectionClosed:
            return  # closing at once is also allowed
        if challenge.get("t") == "challenge":
            nonce = unb64u(challenge["nonce"])
            identity = host.hub.identity
            for presented in {origin or "", ORIGIN}:
                with pytest.raises((InvalidSignature, ValueError)):
                    verify_host_sig(identity.public_key, nonce, presented, challenge["host_sig"])
            sig = sign_auth(device.key, nonce, origin or "", identity.host_pubkey_fp)
            await send_frame(client, {"t": "auth", "device_sig": sig})
        await _refused(client)
        assert session.scope != "owner"
