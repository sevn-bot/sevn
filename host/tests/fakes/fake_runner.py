"""Scripted command runner for ``sevn.service.runner`` (plan 0025 D1).

The fake never starts a process. Each call is recorded with a snapshot of the
watched file (the unit or plist) taken at call time, so a test can tell whether a
command ran before or after the file was written or removed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Call:
    argv: list[str]
    watched: bytes | None
    kwargs: dict[str, object] = field(default_factory=dict[str, object])


@dataclass
class _Rule:
    prefix: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class FakeRunner:
    """Answers commands by argv prefix. The most recently added matching rule wins."""

    def __init__(self, watch: Path | None = None) -> None:
        self.watch = watch
        self.calls: list[Call] = []
        self._rules: list[_Rule] = []

    def on(self, *prefix: str, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self._rules.append(_Rule(tuple(prefix), returncode, stdout, stderr))

    def __call__(self, argv: Sequence[str], **kwargs: object) -> object:
        from sevn.service.runner import CommandResult

        args = [str(item) for item in argv]
        snapshot: bytes | None = None
        if self.watch is not None and self.watch.is_file():
            snapshot = self.watch.read_bytes()
        self.calls.append(Call(args, snapshot, dict(kwargs)))
        for rule in reversed(self._rules):
            if tuple(args[: len(rule.prefix)]) == rule.prefix:
                return CommandResult(
                    returncode=rule.returncode, stdout=rule.stdout, stderr=rule.stderr
                )
        return CommandResult(returncode=0, stdout="", stderr="")

    def argvs(self) -> list[list[str]]:
        return [call.argv for call in self.calls]

    def find(self, *prefix: str) -> list[Call]:
        return [call for call in self.calls if tuple(call.argv[: len(prefix)]) == prefix]

    def index(self, *prefix: str) -> int:
        """Position of the first call with ``prefix``; -1 when it never ran."""
        for position, call in enumerate(self.calls):
            if tuple(call.argv[: len(prefix)]) == prefix:
                return position
        return -1
