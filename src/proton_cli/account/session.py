"""Per-profile Proton auth session persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Session:
    uid: str
    access_token: str
    refresh_token: str
    enc_key_blob: str = ""
    salted_key_pass: str = ""
    app_version: str = ""
    base_url: str = ""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "proton-cli"
    return Path.home() / ".config" / "proton-cli"


def session_path(profile: str) -> Path:
    if not profile:
        profile = "default"
    d = config_dir()
    new_path = d / "sessions" / f"{profile}.json"
    if profile == "default":
        if new_path.is_file():
            return new_path
        legacy = d / "session.json"
        if legacy.is_file():
            return legacy
    return new_path


def from_parts(
    uid: str,
    access_token: str,
    refresh_token: str,
    enc_key_blob: str = "",
    salted_key_pass: str = "",
    app_version: str = "",
    base_url: str = "",
) -> Session:
    blob = enc_key_blob
    legacy = ""
    if blob:
        pass
    elif salted_key_pass:
        legacy = salted_key_pass
    return Session(
        uid=uid,
        access_token=access_token,
        refresh_token=refresh_token,
        enc_key_blob=blob,
        salted_key_pass=legacy,
        app_version=app_version,
        base_url=base_url,
    )


def load(profile: str) -> Session | None:
    path = session_path(profile)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    uid = str(data.get("uid", ""))
    acc = str(data.get("access_token", ""))
    ref = str(data.get("refresh_token", ""))
    if not uid or not acc or not ref:
        return None
    return Session(
        uid=uid,
        access_token=acc,
        refresh_token=ref,
        enc_key_blob=str(data.get("enc_key_blob", "")),
        salted_key_pass=str(data.get("salted_key_pass", "")),
        app_version=str(data.get("app_version", "")),
        base_url=str(data.get("base_url", "")),
    )


def save(profile: str, session: Session) -> None:
    if not profile:
        profile = "default"
    path = config_dir() / "sessions" / f"{profile}.json"
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    payload = {k: v for k, v in asdict(session).items() if v}
    data = json.dumps(payload, indent=2).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def clear(profile: str) -> None:
    path = session_path(profile)
    if path.is_file():
        path.unlink()
