"""Tests for proton_cli foundation (session, env, aead, errors)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from proton_cli.account import session as session_store
from proton_cli.crypto import aead
from proton_cli.env import env_for_profile, profile_env_segment
from proton_cli.errors import Ambiguous, NotFound, classify_exit_code
from proton_cli.proton.errors import ErrUnauthorized

if TYPE_CHECKING:
    import pytest


def test_profile_env_segment() -> None:
    assert profile_env_segment("my-work") == "MY_WORK"
    assert profile_env_segment("work") == "WORK"


def test_env_for_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROTON_WORK_USER", raising=False)
    monkeypatch.delenv("PROTON_USER", raising=False)
    monkeypatch.setenv("PROTON_USER", "global@proton.me")
    assert env_for_profile("work", "USER") == "global@proton.me"
    monkeypatch.setenv("PROTON_WORK_USER", "work@proton.me")
    assert env_for_profile("work", "USER") == "work@proton.me"


def test_session_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    sess = session_store.from_parts("uid", "acc", "ref", app_version="Other")
    session_store.save("personal", sess)
    loaded = session_store.load("personal")
    assert loaded is not None
    assert loaded.uid == "uid"
    assert loaded.access_token == "acc"


def test_aead_roundtrip() -> None:
    key = aead.new_key()
    ct = aead.encrypt(key, b"secret", aead.TAG_VAULT_CONTENT)
    assert aead.decrypt(key, ct, aead.TAG_VAULT_CONTENT) == b"secret"


def test_exit_codes() -> None:
    assert classify_exit_code(None) == 0
    assert classify_exit_code(NotFound("vault", "x")) == 3
    assert classify_exit_code(Ambiguous("item", "x", [])) == 4
    assert classify_exit_code(ErrUnauthorized()) == 2


def test_vault_proto_decode() -> None:
    from proton_cli.proto.vault import decode_vault_name_description

    # field 1 = "Personal", field 2 = "Home vault" (10 chars)
    data = b"\x0a\x08Personal\x12\x0aHome vault"
    name, desc = decode_vault_name_description(data)
    assert name == "Personal"
    assert desc == "Home vault"
