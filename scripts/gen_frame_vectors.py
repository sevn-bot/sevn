"""Write contracts/vectors/frames.json from the frame models (D21)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sevn.contracts.frames import dump, parse

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "contracts" / "vectors" / "frames.json"

_EXAMPLES: dict[str, dict[str, object]] = {
    "hello": {
        "t": "hello",
        "proto": [1, 1],
        "client": "web",
        "device": "dev_1",
        "last_seq": 10420,
        "caps": ["files"],
    },
    "challenge": {
        "t": "challenge",
        "nonce": "nonce-1",
        "host": "host_1",
        "host_sig": "c2ln",
    },
    "auth_token": {"t": "auth", "token": "loopback-token"},
    "auth_device": {"t": "auth", "device_sig": "c2ln"},
    "welcome": {"t": "welcome", "proto": 1, "host_seq": 10431, "caps": ["files"]},
    "req": {
        "t": "req",
        "id": "c7",
        "m": "messages.send",
        "p": {"op_id": "op_1", "bot": "bot_1", "text": "hi"},
    },
    "res_ok": {"t": "res", "id": "c7", "r": {"job": "job_1", "seq": 10432}},
    "res_error": {
        "t": "res",
        "id": "c7",
        "e": {"code": "invalid_params", "message": "bad"},
    },
    "evt": {"t": "evt", "s": 10432, "k": "job.queued", "d": {"job": "job_1"}},
    "tick": {"t": "tick", "k": "turn.delta", "d": {"turn": "turn_1", "text": "hi"}},
}


def render_vectors() -> str:
    """Canonical ``frames.json`` body, including the trailing newline."""
    rendered: dict[str, object] = {}
    for key in sorted(_EXAMPLES):
        raw = json.dumps(
            _EXAMPLES[key],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        rendered[key] = json.loads(dump(parse(raw)))
    return json.dumps(rendered, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write frame test vectors")
    parser.add_argument("--out", type=Path, default=_OUT)
    args = parser.parse_args()
    out = args.out if isinstance(args.out, Path) else Path(str(args.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_vectors(), encoding="utf-8")


if __name__ == "__main__":
    main()
