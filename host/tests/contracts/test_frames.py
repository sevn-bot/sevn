"""Frame codec and committed vectors (D5, D21). Green after W3."""

from __future__ import annotations

import json
from typing import Any

import pytest
from support.repo import repo_root

pytestmark = pytest.mark.xfail(strict=False, reason="green after W3")

_CASES: list[tuple[str, dict[str, Any]]] = [
    (
        "hello",
        {
            "t": "hello",
            "proto": [1, 1],
            "client": "web",
            "device": "dev_1",
            "last_seq": 10420,
            "caps": ["files"],
        },
    ),
    (
        "challenge",
        {"t": "challenge", "nonce": "nonce-1", "host": "host_1", "host_sig": "c2ln"},
    ),
    ("auth_token", {"t": "auth", "token": "loopback-token"}),
    ("auth_device", {"t": "auth", "device_sig": "c2ln"}),
    (
        "welcome",
        {"t": "welcome", "proto": 1, "host_seq": 10431, "caps": ["files"]},
    ),
    (
        "req",
        {
            "t": "req",
            "id": "c7",
            "m": "messages.send",
            "p": {"op_id": "op_1", "bot": "bot_1", "text": "hi"},
        },
    ),
    (
        "res_ok",
        {"t": "res", "id": "c7", "r": {"job": "job_1", "seq": 10432}},
    ),
    (
        "res_error",
        {"t": "res", "id": "c7", "e": {"code": "invalid_params", "message": "bad"}},
    ),
    (
        "evt",
        {"t": "evt", "s": 10432, "k": "job.queued", "d": {"job": "job_1"}},
    ),
    (
        "tick",
        {"t": "tick", "k": "turn.delta", "d": {"turn": "turn_1", "text": "hi"}},
    ),
]


def _canon(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _iter_frames(document: object) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    if isinstance(document, list):
        values = document
    elif isinstance(document, dict):
        values = list(document.values())
    else:
        raise AssertionError("vectors file must be a list or object of frames")
    for value in values:
        if isinstance(value, list):
            frames.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict) and "t" in value:
            frames.append(value)
        else:
            raise AssertionError("vector entry is not a frame")
    return frames


@pytest.mark.parametrize(("kind", "obj"), _CASES, ids=[kind for kind, _obj in _CASES])
def test_frame_roundtrip(kind: str, obj: dict[str, Any]) -> None:
    from sevn.contracts.frames import dump, parse

    text = _canon(obj)
    frame = parse(text)
    assert dump(frame) == text, kind
    data = frame.model_dump(mode="json", exclude_none=True)
    assert data == obj
    assert data["t"] == obj["t"]


def test_unknown_frame_kind() -> None:
    from sevn.contracts.frames import FrameError, parse

    with pytest.raises(FrameError) as exc:
        parse('{"t":"nope"}')
    assert exc.value.code == "protocol_error"


def test_frames_match_vectors() -> None:
    from sevn.contracts.frames import dump, parse

    path = repo_root() / "contracts" / "vectors" / "frames.json"
    frames = _iter_frames(json.loads(path.read_text(encoding="utf-8")))
    kinds = {frame["t"] for frame in frames}
    assert "challenge" in kinds
    auth = [frame for frame in frames if frame["t"] == "auth"]
    assert any("token" in frame for frame in auth)
    assert any("device_sig" in frame for frame in auth)
    for frame in frames:
        text = _canon(frame)
        assert dump(parse(text)) == text
