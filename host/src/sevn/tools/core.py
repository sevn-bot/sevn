"""Core toolset. Feature modules register their own toolsets; this file does not import them."""

from __future__ import annotations

from sevn.tools.registry import TurnDeps, register_toolset


def shell(command: str) -> str:
    """Accept a shell command. Execution waits for the sandbox."""
    _ = command
    return "ok"


def write_file(path: str, content: str) -> str:
    """Accept a file write. Execution waits for the sandbox."""
    _ = content
    return path


def _core_tools(_deps: TurnDeps) -> dict[str, object]:
    return {"shell": shell, "write": write_file}


register_toolset("core", _core_tools, {"shell", "write"})
