"""The command runner behind ``sevn service`` and the service doctor probes (plan 0025 D1).

Every ``systemctl``, ``journalctl``, ``loginctl`` and ``launchctl`` call goes through
:func:`execute`. Tests install a fake with :func:`use_runner`, so the default suite never
touches a real service manager.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

#: Exit code reported when the program does not exist (as a shell would).
MISSING = 127
#: Exit code reported when the program cannot be started for another reason.
NOT_EXECUTABLE = 126
#: Exit code reported when the timeout expired and the child was killed.
TIMED_OUT = 124


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of one command. ``stdout``/``stderr`` are empty when not captured."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runner(Protocol):
    """Runs ``argv`` and returns a :class:`CommandResult`."""

    def __call__(self, argv: Sequence[str], /, **kwargs: object) -> object: ...


_override: Runner | None = None


def use_runner(runner: Runner | None) -> None:
    """Route every service command through ``runner``; ``None`` restores :func:`run`."""
    global _override
    _override = runner


def run(
    argv: Sequence[str], *, timeout: float | None = None, capture: bool = True
) -> CommandResult:
    """Run ``argv`` without a shell. Never raises for a missing binary or a timeout.

    A missing program reports 127 and an expired ``timeout`` reports 124 after the child is
    killed. With ``capture=False`` the child writes straight to this process's stdout and
    stderr (used to follow logs).
    """
    args = [str(item) for item in argv]
    try:
        completed = subprocess.run(  # noqa: S603 — fixed service-manager argv, no shell
            args,
            capture_output=capture,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(returncode=MISSING, stderr=f"{args[0]}: {exc.strerror or exc}")
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=TIMED_OUT, stderr=f"{args[0]}: timed out after {timeout}s")
    except OSError as exc:
        return CommandResult(returncode=NOT_EXECUTABLE, stderr=f"{args[0]}: {exc.strerror or exc}")
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def execute(
    argv: Sequence[str], *, timeout: float | None = None, capture: bool = True
) -> CommandResult:
    """Run ``argv`` through the installed runner, or :func:`run` when none is installed."""
    runner = _override
    if runner is None:
        return run(argv, timeout=timeout, capture=capture)
    result = runner(list(argv), timeout=timeout, capture=capture)
    if not isinstance(result, CommandResult):
        raise TypeError(f"service runner returned {type(result).__name__}, not CommandResult")
    return result
