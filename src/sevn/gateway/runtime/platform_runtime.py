"""Per-channel runtime status, pause/resume, and circuit breaker.

Module: sevn.gateway.runtime.platform_runtime
Depends: dataclasses, time, typing

Exports:
    PlatformRuntimeState — one adapter runtime row.
    PlatformRuntimeRegistry — in-process pause/resume + circuit breaker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

PlatformConnectionState = Literal["connected", "paused", "circuit_open", "stopped"]


@dataclass
class PlatformRuntimeState:
    """Runtime health for one registered channel adapter."""

    name: str
    adapter_type: str = ""
    connected: bool = False
    paused: bool = False
    circuit_open: bool = False
    consecutive_failures: int = 0
    last_failure_at: float | None = None
    last_error: str | None = None

    @property
    def connection_state(self) -> PlatformConnectionState:
        """Return Mission Control compatible connection state label.

        Returns:
            PlatformConnectionState: Derived runtime label.

        Examples:
            >>> PlatformRuntimeState("telegram", circuit_open=True).connection_state
            'circuit_open'
        """
        if self.circuit_open:
            return "circuit_open"
        if self.paused:
            return "paused"
        if self.connected:
            return "connected"
        return "stopped"


@dataclass
class PlatformRuntimeRegistry:
    """Track adapter runtime status and operator pause/resume controls."""

    failure_threshold: int = 5
    circuit_reset_seconds: float = 300.0
    _platforms: dict[str, PlatformRuntimeState] = field(default_factory=dict)

    def register(self, name: str, *, adapter_type: str = "") -> PlatformRuntimeState:
        """Ensure runtime row exists for ``name``.

        Args:
            name (str): Adapter name.
            adapter_type (str): Adapter implementation label.

        Returns:
            PlatformRuntimeState: Mutable runtime row.

        Examples:
            >>> reg = PlatformRuntimeRegistry()
            >>> reg.register("telegram", adapter_type="telegram").name
            'telegram'
        """
        row = self._platforms.get(name)
        if row is None:
            row = PlatformRuntimeState(name=name, adapter_type=adapter_type or name)
            self._platforms[name] = row
        elif adapter_type:
            row.adapter_type = adapter_type
        return row

    def mark_connected(self, name: str, *, connected: bool = True) -> None:
        """Update connection flag for one adapter.

        Args:
            name (str): Adapter name.
            connected (bool): Connection verdict.

        Examples:
            >>> reg = PlatformRuntimeRegistry()
            >>> reg.register("telegram").name
            'telegram'
            >>> reg.mark_connected("telegram")
            >>> reg.get("telegram").connected
            True
        """
        self.register(name).connected = connected

    def pause(self, name: str) -> bool:
        """Pause inbound processing for one adapter.

        Args:
            name (str): Adapter name.

        Returns:
            bool: ``False`` when unknown.

        Examples:
            >>> reg = PlatformRuntimeRegistry()
            >>> reg.register("telegram").name
            'telegram'
            >>> reg.pause("telegram")
            True
        """
        row = self._platforms.get(name)
        if row is None:
            return False
        row.paused = True
        return True

    def resume(self, name: str) -> bool:
        """Resume one paused adapter and clear an open circuit.

        Args:
            name (str): Adapter name.

        Returns:
            bool: ``False`` when unknown.

        Examples:
            >>> reg = PlatformRuntimeRegistry()
            >>> reg.register("telegram").name
            'telegram'
            >>> reg.pause("telegram")
            True
            >>> reg.resume("telegram")
            True
        """
        row = self._platforms.get(name)
        if row is None:
            return False
        row.paused = False
        row.circuit_open = False
        row.consecutive_failures = 0
        row.last_failure_at = None
        row.last_error = None
        return True

    def accepts_inbound(self, name: str) -> bool:
        """Return whether inbound messages may be processed.

        Args:
            name (str): Adapter name.

        Returns:
            bool: ``True`` when not paused and circuit is closed/half-open.

        Examples:
            >>> reg = PlatformRuntimeRegistry()
            >>> reg.register("telegram").name
            'telegram'
            >>> reg.accepts_inbound("telegram")
            True
        """
        row = self._platforms.get(name)
        if row is None:
            return True
        if row.paused:
            return False
        if row.circuit_open:
            opened_at = row.last_failure_at
            if opened_at is None:
                return False
            if (time.monotonic() - opened_at) >= self.circuit_reset_seconds:
                row.circuit_open = False
                row.consecutive_failures = 0
                return True
            return False
        return True

    def record_outbound_success(self, name: str) -> None:
        """Reset failure counters after a successful outbound send.

        Args:
            name (str): Adapter name.

        Examples:
            >>> reg = PlatformRuntimeRegistry()
            >>> reg.register("telegram").name
            'telegram'
            >>> reg.record_outbound_failure("telegram", "boom")
            >>> reg.record_outbound_success("telegram")
            >>> reg.get("telegram").consecutive_failures
            0
        """
        row = self._platforms.get(name)
        if row is None:
            return
        row.consecutive_failures = 0
        row.circuit_open = False
        row.last_failure_at = None
        row.last_error = None

    def record_outbound_failure(self, name: str, error: str) -> None:
        """Increment failure counter and open circuit when threshold exceeded.

        Args:
            name (str): Adapter name.
            error (str): Failure summary.

        Examples:
            >>> reg = PlatformRuntimeRegistry(failure_threshold=1)
            >>> reg.register("telegram").name
            'telegram'
            >>> reg.record_outbound_failure("telegram", "timeout")
            >>> reg.get("telegram").circuit_open
            True
        """
        row = self.register(name)
        row.consecutive_failures += 1
        row.last_failure_at = time.monotonic()
        row.last_error = error[:500]
        if row.consecutive_failures >= self.failure_threshold:
            row.circuit_open = True

    def list_platforms(self) -> tuple[PlatformRuntimeState, ...]:
        """Return sorted runtime rows.

        Returns:
            tuple[PlatformRuntimeState, ...]: Snapshot of registered adapters.

        Examples:
            >>> PlatformRuntimeRegistry().list_platforms()
            ()
        """
        return tuple(sorted(self._platforms.values(), key=lambda row: row.name))

    def get(self, name: str) -> PlatformRuntimeState | None:
        """Return one runtime row.

        Args:
            name (str): Adapter name.

        Returns:
            PlatformRuntimeState | None: Row or ``None``.

        Examples:
            >>> PlatformRuntimeRegistry().get("missing") is None
            True
        """
        return self._platforms.get(name)


__all__ = ["PlatformConnectionState", "PlatformRuntimeRegistry", "PlatformRuntimeState"]
