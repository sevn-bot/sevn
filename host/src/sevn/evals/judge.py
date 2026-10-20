"""Score a routing replay with judge-jev when that binary is installed.

A missing binary is skipped. The wrapper does not invent a passing verdict.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sevn.decisions.base import object_dict, redact_text
from sevn.log import logger

_PROMPT = (
    "Judge this routing replay. Say whether each predicted intent and target "
    "match the labeled route."
)
_VERDICTS = frozenset({"pass", "fail", "review", "escalate", "skip"})
_CODE_VERDICT = {0: "pass", 1: "fail", 2: "review", 3: "escalate", 4: "skip"}


@dataclass(frozen=True, slots=True)
class RouteScore:
    """One labeled case and the route the decider chain returned."""

    text: str
    intent: str
    predicted_intent: str
    target: str
    predicted_target: str


async def score_routes(rows: list[RouteScore]) -> dict[str, str]:
    """Call judge-jev on the replay. Skip when the tool is not installed."""
    binary = _binary()
    if binary is None:
        logger.info("judge-jev is not installed; routing judge skipped")
        return {"status": "skipped", "reason": "judge-jev is not installed"}
    context: dict[str, str] = {}
    payload: dict[str, object] = {
        "prompt": _PROMPT,
        "reply": _reply(rows),
        "context": context,
    }
    with tempfile.TemporaryDirectory(prefix="sevn-eval-") as folder:
        path = Path(folder) / "routing.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            code, stdout = await _invoke(binary, path)
        except OSError:
            logger.warning("judge-jev failed")
            return {"status": "error", "reason": "judge-jev could not be started"}
    verdict = _verdict(code, stdout)
    if verdict is None:
        logger.warning("judge-jev failed")
        return {"status": "error", "reason": "judge-jev did not return a verdict"}
    return {"status": "scored", "verdict": verdict}


def _binary() -> Path | None:
    found = shutil.which("judge-jev")
    if found is None:
        return None
    path = Path(found)
    if not path.is_absolute():
        return None
    return path


def _reply(rows: list[RouteScore]) -> str:
    lines = ["Routing replay. Each line is the label, the prediction, and the message."]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. label {row.intent}/{row.target} "
            f"predicted {row.predicted_intent}/{row.predicted_target} "
            f":: {redact_text(row.text)}"
        )
    return "\n".join(lines)


async def _invoke(binary: Path, payload: Path) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        str(binary),
        "run",
        "--rubric",
        "assistant-reply",
        "--input",
        str(payload),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _stderr = await process.communicate()
    code = process.returncode if process.returncode is not None else 10
    text = stdout.decode("utf-8", errors="replace") if stdout else ""
    return code, text


def _verdict(code: int, stdout: str) -> str | None:
    parsed = _object(stdout)
    if parsed is not None:
        verdict = parsed.get("verdict")
        if isinstance(verdict, str) and verdict in _VERDICTS:
            return verdict
    return _CODE_VERDICT.get(code)


def _object(stdout: str) -> dict[str, object] | None:
    try:
        loaded: object = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return object_dict(loaded)
