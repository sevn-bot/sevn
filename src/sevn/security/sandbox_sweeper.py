"""Orphan Docker sandbox cleanup vs gateway run registry (``specs/08-sandbox.md`` §4.5).

Module: sevn.security.sandbox_sweeper
Depends: typing

Exports:
    SandboxRunRegistry — gateway run row contract (mock until gateway ships).
    SandboxLabeledContainer — minimal container view for sweeper input.
    orphan_container_should_kill — TTL rule ``2 * sandbox_max_lifetime``.
    sweep_orphan_labels — dry-runnable batch helper for unit tests.

Examples:
    >>> from sevn.security.sandbox_sweeper import orphan_container_should_kill
    >>> class _R:
    ...     missing_since = 1_000_000.0
    ...     live = False
    ...     def is_live(self, run_id: str) -> bool:
    ...         return self.live
    ...     def missing_since_unix_s(self, run_id: str) -> float | None:
    ...         return None if self.live else self.missing_since
    >>> orphan_container_should_kill(
    ...     run_id="r1",
    ...     now_unix_s=1_000_500.0,
    ...     sandbox_max_lifetime_s=1000,
    ...     registry=_R(),
    ... )
    False
"""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


@runtime_checkable
class SandboxRunRegistry(Protocol):
    """Logical live-run index (``specs/17-gateway.md`` when implemented)."""

    def is_live(self, run_id: str) -> bool:
        """Return whether gateway still leases ``run_id``.

        Args:
            run_id (str): ``sevn.run_id`` correlation label string.

        Returns:
            bool: ``True`` while run registry rows remain active.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    def missing_since_unix_s(self, run_id: str) -> float | None:
        """Return seconds-since-epoch marking disappearance window start.

        Args:
            run_id (str): ``sevn.run_id`` correlation label string.

        Returns:
            float | None: Timestamp when absent from live lease table or ``None``.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...


class SandboxLabeledContainer(TypedDict):
    """Docker-like row with opaque id plus ``sevn.run_id`` label."""

    container_id: str
    labels: dict[str, str]


def orphan_container_should_kill(
    *,
    run_id: str,
    now_unix_s: float,
    sandbox_max_lifetime_s: float,
    registry: SandboxRunRegistry,
) -> bool:
    """Return ``True`` when orphaned long enough to kill (§4.5).

    Args:
        run_id (str): Value of ``sevn.run_id`` Docker label.
        now_unix_s (float): Current UNIX wall time in seconds.
        sandbox_max_lifetime_s (float): Configured ``sandbox.max_lifetime`` cap.
        registry (SandboxRunRegistry): Gateway registry (mockable in tests).

    Returns:
        bool: Whether the sweeper should terminate the container.

    Examples:
        >>> class _Reg:
        ...     live = False
        ...     missing_since = 100.0
        ...     def is_live(self, run_id: str) -> bool:
        ...         return self.live
        ...     def missing_since_unix_s(self, run_id: str) -> float | None:
        ...         return None if self.live else self.missing_since
        >>> orphan_container_should_kill(
        ...     run_id="x",
        ...     now_unix_s=500.0,
        ...     sandbox_max_lifetime_s=100,
        ...     registry=_Reg(),
        ... )
        True
    """
    if sandbox_max_lifetime_s <= 0:
        return False
    if registry.is_live(run_id):
        return False
    since = registry.missing_since_unix_s(run_id)
    if since is None:
        return False
    threshold = 2.0 * sandbox_max_lifetime_s
    return (now_unix_s - since) > threshold


def sweep_orphan_labels(
    *,
    containers: list[SandboxLabeledContainer],
    now_unix_s: float,
    sandbox_max_lifetime_s: float,
    registry: SandboxRunRegistry,
) -> list[str]:
    """Enumerate container ids that qualify for orphan termination.

    Args:
        containers (list[SandboxLabeledContainer]): Candidate containers.
        now_unix_s (float): Current UNIX time.
        sandbox_max_lifetime_s (float): Configured lifetime cap.
        registry (SandboxRunRegistry): Live/missing metadata.

    Returns:
        list[str]: ``container_id`` values to kill.

    Examples:
        >>> c = SandboxLabeledContainer(
        ...     container_id="c1",
        ...     labels={"sevn.run_id": "dead"},
        ... )
        >>> class _G:
        ...     live = False
        ...     missing_since = 0.0
        ...     def is_live(self, run_id: str) -> bool:
        ...         return self.live
        ...     def missing_since_unix_s(self, run_id: str) -> float | None:
        ...         return self.missing_since
        >>> out = sweep_orphan_labels(
        ...     containers=[c],
        ...     now_unix_s=9_999_999.0,
        ...     sandbox_max_lifetime_s=1.0,
        ...     registry=_G(),
        ... )
        >>> out == ["c1"]
        True
    """
    doomed: list[str] = []
    for row in containers:
        run_id_val = row["labels"].get("sevn.run_id")
        if not run_id_val:
            continue
        if orphan_container_should_kill(
            run_id=run_id_val,
            now_unix_s=now_unix_s,
            sandbox_max_lifetime_s=sandbox_max_lifetime_s,
            registry=registry,
        ):
            doomed.append(row["container_id"])
    return doomed
