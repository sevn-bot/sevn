"""ALRCA goal contract — schema, storage, and CLI helpers (CA3.1).

Module: sevn.coding_agents.alrca.goal
Depends: json, pathlib, uuid

Exports:
    GoalContract — typed goal envelope (success criteria, budget, constraints).
    GoalStatus — terminal/running status enum.
    list_goals — list all persisted goals from workspace vault.
    load_goal — read an existing run goal from workspace vault.
    new_goal — construct a fresh goal contract with a generated run_id.
    save_goal — persist a goal contract to the workspace vault.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import StrEnum
from pathlib import Path  # noqa: TC003 — runtime vault paths
from typing import Any

JsonDict = dict[str, Any]

_GOALS_DIR = "coding_agents/goals"


class GoalStatus(StrEnum):
    """Lifecycle state for an ALRCA goal run."""

    pending = "pending"
    running = "running"
    complete = "complete"
    exhausted = "exhausted"
    failed = "failed"


class GoalContract:
    """Structured goal handed to the ALRCA loop worker.

    Args:
        run_id (str): Unique run identifier (UUID4).
        agent_id (str): Registry agent id that owns this run.
        description (str): Natural-language goal statement.
        success_criteria (list[str]): Verifiable acceptance conditions.
        constraints (list[str]): Hard constraints (budget, scope).
        max_turns (int): Hard cap on executor invocations per goal.
        status (GoalStatus): Current lifecycle state.
        created_at (float): Unix timestamp at construction.
        updated_at (float): Unix timestamp of last status change.
        extra (JsonDict): Extension attributes.

    Examples:
        >>> g = GoalContract(run_id="r1", agent_id="a1", description="fix tests")
        >>> g.status == GoalStatus.pending
        True
        >>> g.max_turns
        10
    """

    def __init__(
        self,
        *,
        run_id: str,
        agent_id: str,
        description: str,
        success_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        max_turns: int = 10,
        status: GoalStatus = GoalStatus.pending,
        created_at: float | None = None,
        updated_at: float | None = None,
        extra: JsonDict | None = None,
    ) -> None:
        """Construct a GoalContract.

        Args:
            run_id (str): Unique run identifier.
            agent_id (str): Registry agent id.
            description (str): Natural-language goal statement.
            success_criteria (list[str] | None): Verifiable acceptance conditions.
            constraints (list[str] | None): Hard constraints.
            max_turns (int): Executor invocation cap.
            status (GoalStatus): Initial lifecycle state.
            created_at (float | None): Unix timestamp; defaults to now.
            updated_at (float | None): Unix timestamp; defaults to now.
            extra (JsonDict | None): Extension attributes.

        Examples:
            >>> g = GoalContract(run_id="r1", agent_id="a1", description="fix lint")
            >>> g.max_turns
            10
        """
        now = time.time()
        self.run_id = run_id
        self.agent_id = agent_id
        self.description = description
        self.success_criteria: list[str] = success_criteria or []
        self.constraints: list[str] = constraints or []
        self.max_turns = max_turns
        self.status = GoalStatus(status)
        self.created_at: float = created_at if created_at is not None else now
        self.updated_at: float = updated_at if updated_at is not None else now
        self.extra: JsonDict = extra or {}

    def to_dict(self) -> JsonDict:
        """Serialise goal to a JSON-safe dict.

        Returns:
            JsonDict: Full goal document ready for file persistence.

        Examples:
            >>> g = GoalContract(run_id="r1", agent_id="a1", description="d")
            >>> g.to_dict()["run_id"]
            'r1'
        """
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "constraints": self.constraints,
            "max_turns": self.max_turns,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> GoalContract:
        """Deserialise from a JSON dict.

        Args:
            data (JsonDict): Stored goal document.

        Returns:
            GoalContract: Hydrated goal.

        Examples:
            >>> g = GoalContract.from_dict({"run_id": "r", "agent_id": "a", "description": "d"})
            >>> g.run_id
            'r'
        """
        known = {
            "run_id",
            "agent_id",
            "description",
            "success_criteria",
            "constraints",
            "max_turns",
            "status",
            "created_at",
            "updated_at",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            run_id=str(data["run_id"]),
            agent_id=str(data.get("agent_id", "")),
            description=str(data.get("description", "")),
            success_criteria=list(data.get("success_criteria") or []),
            constraints=list(data.get("constraints") or []),
            max_turns=int(data.get("max_turns", 10)),
            status=GoalStatus(data.get("status", GoalStatus.pending)),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            extra=extra,
        )


def _goals_dir(workspace_path: Path) -> Path:
    """Return the goals vault directory, creating it when absent.

    Args:
        workspace_path (Path): Operator workspace root.

    Returns:
        Path: ``<workspace>/coding_agents/goals/`` directory.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     d = _goals_dir(pathlib.Path(t))
        ...     d.is_dir()
        True
    """
    d = workspace_path / _GOALS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_goal(
    *,
    agent_id: str,
    description: str,
    success_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
    max_turns: int = 10,
) -> GoalContract:
    """Construct a fresh goal contract with a generated run_id.

    Args:
        agent_id (str): Registry agent id.
        description (str): Natural-language goal statement.
        success_criteria (list[str] | None): Verifiable conditions.
        constraints (list[str] | None): Hard constraints.
        max_turns (int): Executor invocation cap.

    Returns:
        GoalContract: New pending goal.

    Examples:
        >>> g = new_goal(agent_id="a1", description="fix lint")
        >>> len(g.run_id) > 8
        True
    """
    return GoalContract(
        run_id=str(uuid.uuid4()),
        agent_id=agent_id,
        description=description,
        success_criteria=success_criteria,
        constraints=constraints,
        max_turns=max_turns,
    )


def save_goal(goal: GoalContract, workspace_path: Path) -> Path:
    """Persist ``goal`` to ``<workspace>/coding_agents/goals/<run_id>.json``.

    Args:
        goal (GoalContract): Goal to persist.
        workspace_path (Path): Operator workspace root.

    Returns:
        Path: Written file path.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     g = new_goal(agent_id="a", description="d")
        ...     p = save_goal(g, pathlib.Path(t))
        ...     p.exists()
        True
    """
    target = _goals_dir(workspace_path) / f"{goal.run_id}.json"
    target.write_text(json.dumps(goal.to_dict(), indent=2), encoding="utf-8")
    return target


def load_goal(run_id: str, workspace_path: Path) -> GoalContract | None:
    """Load a goal from the vault by run_id.

    Args:
        run_id (str): Run identifier to look up.
        workspace_path (Path): Operator workspace root.

    Returns:
        GoalContract | None: Hydrated goal or ``None`` when not found.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     g = new_goal(agent_id="a", description="d")
        ...     _ = save_goal(g, pathlib.Path(t))
        ...     loaded = load_goal(g.run_id, pathlib.Path(t))
        ...     loaded is not None and loaded.description == "d"
        True
    """
    target = _goals_dir(workspace_path) / f"{run_id}.json"
    if not target.is_file():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    return GoalContract.from_dict(data)


def list_goals(workspace_path: Path) -> list[GoalContract]:
    """List all persisted goals ordered newest-first by created_at.

    Args:
        workspace_path (Path): Operator workspace root.

    Returns:
        list[GoalContract]: All stored goal contracts.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     g = new_goal(agent_id="a", description="d")
        ...     _ = save_goal(g, pathlib.Path(t))
        ...     goals = list_goals(pathlib.Path(t))
        ...     len(goals) == 1
        True
    """
    goals_dir = _goals_dir(workspace_path)
    contracts: list[GoalContract] = []
    for f in sorted(goals_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            contracts.append(GoalContract.from_dict(data))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return contracts


__all__ = [
    "GoalContract",
    "GoalStatus",
    "list_goals",
    "load_goal",
    "new_goal",
    "save_goal",
]
