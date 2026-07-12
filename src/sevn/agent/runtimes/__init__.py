"""Agent runtime implementations (``specs/08-sandbox.md`` RLM host).

Module: sevn.agent.runtimes
Depends: sevn.agent.runtimes.sandbox

Exports:
    PyodideDenoInterpreter — Pyodide-in-Deno REPL for DSPy C/D paths.
    SevnDockerInterpreter — Docker-backed REPL stub.
    build_rlm_interpreter — DSPy-compatible interpreter picker.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> from sevn.agent.runtimes import build_rlm_interpreter
    >>> isinstance(build_rlm_interpreter(WorkspaceConfig.minimal()), object)
    True
"""

from __future__ import annotations

from sevn.agent.runtimes.sandbox import (
    PyodideDenoInterpreter,
    SevnDockerInterpreter,
    build_rlm_interpreter,
)

__all__ = [
    "PyodideDenoInterpreter",
    "SevnDockerInterpreter",
    "build_rlm_interpreter",
]
