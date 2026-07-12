"""Spawn, kill, and complete tracked sub-agent runs against the registry (D4/D5/D9/D11).

Module: sevn.agent.subagents.supervisor
Depends: asyncio, contextlib, dataclasses, loguru, sevn.agent.subagents.models,
    sevn.agent.subagents.registry, sevn.config.sections.subagents

Also exports two type aliases: ``SubAgentBody`` (a zero-arg async callable
producing a sub-agent's result) and ``AnnounceBackHook`` (the completion
callback injected by the gateway (D9), kept decoupled — this module never
imports ``sevn.gateway``).

Exports:
    SubAgentSpec — one spawn request.
    SubAgentHandle — live handle to a spawned run's asyncio task.
    SubAgentSupervisor — spawn / kill / kill_all against a ``SubAgentRegistry``.

Examples:
    >>> import asyncio
    >>> from sevn.agent.subagents.registry import SubAgentRegistry
    >>> async def _demo() -> str:
    ...     registry = SubAgentRegistry()
    ...     supervisor = SubAgentSupervisor(registry)
    ...     async def _work() -> int:
    ...         return 42
    ...     handle = await supervisor.spawn(SubAgentSpec(
    ...         level=1, role="tier_b", body=_work,
    ...         session_id="s1", channel="telegram", task_summary="hi",
    ...     ))
    ...     await handle.task
    ...     run = (await registry.snapshot())[0]
    ...     return run.status.value
    >>> asyncio.run(_demo())
    'done'
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from loguru import logger

from sevn.agent.subagents.models import ACTIVE_STATUSES, SubAgentLimitExceeded, SubAgentRun
from sevn.config.sections.subagents import resolve_limits

if TYPE_CHECKING:
    from sevn.agent.subagents.registry import RegistrySnapshot, SubAgentRegistry
    from sevn.config.sections.subagents import Role, SubAgentsWorkspaceConfig

__all__ = [
    "AnnounceBackHook",
    "SubAgentBody",
    "SubAgentHandle",
    "SubAgentSpec",
    "SubAgentSupervisor",
]

SubAgentBody = Callable[[], Awaitable[object]]
"""Zero-arg async callable that performs the sub-agent's work and returns a result."""

AnnounceBackHook = Callable[[SubAgentRun, "object | None", "BaseException | None"], Awaitable[None]]
"""Completion callback: ``(run, result_or_none, error_or_none) -> None``.

D9's fire-and-forget announce-back is implemented by the *caller* (the
gateway, in W3) injecting this as a constructor parameter — this module must
never import ``sevn.gateway`` so the supervisor stays usable in isolation
(CLI, tests, future non-gateway hosts).
"""


@dataclass(frozen=True, slots=True)
class SubAgentSpec:
    """One spawn request handed to :meth:`SubAgentSupervisor.spawn`.

    Args:
        level (Literal[1, 2]): ``1`` for a tracked tier-role run, ``2`` for a
            worker spawned by a level-1 run.
        role (Role): Owning level-1 role (D3 — level-2 runs inherit their
            parent's role).
        body (SubAgentBody): Zero-arg async callable performing the work.
        session_id (str): Gateway session id.
        channel (str): Channel name.
        task_summary (str): Short human-readable task description.
        specialist (str | None): ``subagents.specialists.<name>`` id for a
            specialist level-2 run.
        parent_id (str | None): Required for level-2 specs — the spawning
            level-1 run's id.
        timeout_s (float | None): Per-run override; falls back to the
            supervisor's ``default_timeout_s`` when ``None`` (D11).
    """

    level: Literal[1, 2]
    role: Role
    body: SubAgentBody
    session_id: str
    channel: str
    task_summary: str
    specialist: str | None = None
    parent_id: str | None = None
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class SubAgentHandle:
    """Live handle to a spawned run's backing :class:`asyncio.Task`."""

    id: str
    task: asyncio.Task[object]


class SubAgentSupervisor:
    """Owns spawn, completion, and kill semantics against one registry (D4).

    Args:
        registry (SubAgentRegistry): Backing registry — the only source of
            truth for run state.
        config (SubAgentsWorkspaceConfig | None): Effective ``subagents``
            subtree; ``None`` falls back to built-in defaults everywhere
            (mirrors :func:`sevn.config.sections.subagents.resolve_limits`).
        default_timeout_s (float | None): Fallback per-run wall-clock timeout
            when a spec does not set its own (D11); defaults to
            ``config.timeout_s`` when omitted.
        announce_back (AnnounceBackHook | None): Completion callback (D9);
            ``None`` disables announce-back (e.g. in unit tests).

    Examples:
        >>> from sevn.agent.subagents.registry import SubAgentRegistry
        >>> supervisor = SubAgentSupervisor(SubAgentRegistry())
        >>> isinstance(supervisor, SubAgentSupervisor)
        True
    """

    def __init__(
        self,
        registry: SubAgentRegistry,
        *,
        config: SubAgentsWorkspaceConfig | None = None,
        default_timeout_s: float | None = None,
        announce_back: AnnounceBackHook | None = None,
    ) -> None:
        """Bind a supervisor to one registry, config, and optional hooks (D4).

        Args:
            registry (SubAgentRegistry): Backing registry — the only source of
                truth for run state.
            config (SubAgentsWorkspaceConfig | None): Effective ``subagents``
                subtree; ``None`` falls back to built-in defaults everywhere.
            default_timeout_s (float | None): Fallback per-run wall-clock timeout
                when a spec omits its own (D11); defaults to ``config.timeout_s``.
            announce_back (AnnounceBackHook | None): Completion callback (D9);
                ``None`` disables announce-back (e.g. in unit tests).

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> isinstance(SubAgentSupervisor(SubAgentRegistry()), SubAgentSupervisor)
            True
        """
        self._registry = registry
        self._config = config
        self._default_timeout_s = (
            default_timeout_s
            if default_timeout_s is not None
            else (config.timeout_s if config is not None else None)
        )
        self._announce_back = announce_back
        self._tasks: dict[str, asyncio.Task[object]] = {}

    @property
    def registry(self) -> SubAgentRegistry:
        """The backing :class:`SubAgentRegistry` (W3.1 — L1 lifecycle tracking).

        Exposed so callers that already hold a supervisor (gateway boot,
        ``agent_turn``, tool contexts) can register/finalize lightweight
        level-1 tracking rows directly against the same registry the
        supervisor spawns level-2 runs against, without threading a second
        object through the whole call chain.

        Returns:
            SubAgentRegistry: The backing registry this supervisor mutates.

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> sup = SubAgentSupervisor(SubAgentRegistry())
            >>> isinstance(sup.registry, SubAgentRegistry)
            True
        """
        return self._registry

    @property
    def config(self) -> SubAgentsWorkspaceConfig | None:
        """The effective ``subagents`` subtree this supervisor was built with (W3.3).

        Exposed so callers resolving specialist gating (``resolve_specialist`` /
        ``specialist_spawn_allowed`` — D8) can reach the same config the
        supervisor itself uses for limit resolution, without a second
        constructor parameter threaded through the gateway/tool layers.

        Returns:
            SubAgentsWorkspaceConfig | None: The effective config, or ``None``.

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> SubAgentSupervisor(SubAgentRegistry()).config is None
            True
        """
        return self._config

    def _specialist_max_concurrent(self, specialist: str | None) -> int | None:
        """Resolve a specialist's ``max_concurrent`` cap, or ``None`` when unbounded.

        Args:
            specialist (str | None): Specialist id, or ``None`` for a generic run.

        Returns:
            int | None: The configured ``max_concurrent`` cap, or ``None`` when
            there is no config, no such specialist, or no specialist named.

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> SubAgentSupervisor(SubAgentRegistry())._specialist_max_concurrent(None) is None
            True
        """
        if specialist is None or self._config is None:
            return None
        entry = self._config.specialists.get(specialist)
        return entry.max_concurrent if entry is not None else None

    async def spawn(self, spec: SubAgentSpec) -> SubAgentHandle | SubAgentLimitExceeded:
        """Enforce limits (D2/D5/D8) then register and launch the run's task.

        Args:
            spec (SubAgentSpec): Spawn request.

        Returns:
            SubAgentHandle | SubAgentLimitExceeded: A live handle, or a typed
            rejection when the effective cap has already been reached —
            never raises for a capacity rejection (D5).

        Raises:
            ValueError: ``spec.level == 2`` with no ``parent_id`` (programming
                error, not a capacity condition).

        Examples:
            >>> import asyncio
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> from sevn.config.sections.subagents import SubAgentsWorkspaceConfig
            >>> async def _demo() -> bool:
            ...     cfg = SubAgentsWorkspaceConfig(max_level1_default=1)
            ...     registry = SubAgentRegistry()
            ...     supervisor = SubAgentSupervisor(registry, config=cfg)
            ...     async def _work() -> None:
            ...         await asyncio.sleep(10)
            ...     spec = SubAgentSpec(
            ...         level=1, role="tier_b", body=_work,
            ...         session_id="s", channel="c", task_summary="t",
            ...     )
            ...     first = await supervisor.spawn(spec)
            ...     second = await supervisor.spawn(spec)
            ...     ok = isinstance(second, SubAgentLimitExceeded)
            ...     await supervisor.kill(first.id)
            ...     return ok
            >>> asyncio.run(_demo())
            True
        """
        max_l1, max_l2 = resolve_limits(self._config, spec.role)
        specialist_cap = self._specialist_max_concurrent(spec.specialist)
        rejection: dict[str, SubAgentLimitExceeded] = {}

        def _predicate(snap: RegistrySnapshot) -> bool:
            if spec.level == 1:
                current = snap.counts().get((1, spec.role), 0)
                if current >= max_l1:
                    rejection["result"] = SubAgentLimitExceeded(
                        level=1,
                        role=spec.role,
                        reason="level1_limit",
                        limit=max_l1,
                        current=current,
                    )
                    return False
                return True
            if spec.parent_id is None:
                msg = "level-2 spawn requires parent_id"
                raise ValueError(msg)
            if spec.specialist is not None and specialist_cap is not None:
                specialist_current = snap.active_specialist(spec.specialist)
                if specialist_current >= specialist_cap:
                    rejection["result"] = SubAgentLimitExceeded(
                        level=2,
                        role=spec.role,
                        reason="specialist_limit",
                        limit=specialist_cap,
                        current=specialist_current,
                        specialist=spec.specialist,
                    )
                    return False
            children_current = snap.active_children(spec.parent_id)
            if children_current >= max_l2:
                rejection["result"] = SubAgentLimitExceeded(
                    level=2,
                    role=spec.role,
                    reason="level2_limit",
                    limit=max_l2,
                    current=children_current,
                )
                return False
            return True

        run = await self._registry.register_if(
            _predicate,
            level=spec.level,
            role=spec.role,
            specialist=spec.specialist,
            parent_id=spec.parent_id,
            session_id=spec.session_id,
            channel=spec.channel,
            task_summary=spec.task_summary,
        )
        if run is None:
            return rejection["result"]
        timeout_s = spec.timeout_s if spec.timeout_s is not None else self._default_timeout_s
        task = asyncio.ensure_future(self._run(run.id, spec, timeout_s))
        self._tasks[run.id] = task
        return SubAgentHandle(id=run.id, task=task)

    async def _announce(
        self,
        run: SubAgentRun,
        result: object | None,
        error: BaseException | None,
    ) -> None:
        """Invoke the announce-back hook (D9), isolating and logging any failure.

        Args:
            run (SubAgentRun): The finished run to announce.
            result (object | None): Body return value on success.
            error (BaseException | None): Body exception, or timeout/cancel marker.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> sup = SubAgentSupervisor(SubAgentRegistry())
            >>> asyncio.run(sup._announce(None, None, None)) is None  # hook unset → no-op
            True
        """
        if self._announce_back is None:
            return
        try:
            await self._announce_back(run, result, error)
        except Exception:
            logger.bind(subagent_id=run.id).exception("subagent announce-back hook failed")

    async def _run(
        self,
        subagent_id: str,
        spec: SubAgentSpec,
        timeout_s: float | None,
    ) -> None:
        """Run one sub-agent body, updating the registry and announcing on exit.

        Args:
            subagent_id (str): Registered run id to drive to a terminal state.
            spec (SubAgentSpec): The spawn request whose ``body`` is executed.
            timeout_s (float | None): Per-run wall-clock cap; ``None`` disables it (D11).

        Examples:
            >>> import asyncio
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     sup = SubAgentSupervisor(registry)
            ...     async def _body() -> str:
            ...         return "ok"
            ...     spec = SubAgentSpec(
            ...         level=1, role="tier_b", body=_body,
            ...         session_id="s", channel="c", task_summary="t",
            ...     )
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c", task_summary="t",
            ...     )
            ...     await sup._run(run.id, spec, None)
            ...     finished = await registry.get(run.id)
            ...     return finished.status.value
            >>> asyncio.run(_demo())
            'done'
        """
        try:
            try:
                # ``mark_running`` lives inside this try (not just the body await)
                # so a cancel that lands while still acquiring the registry lock —
                # before the body has even started — still routes through the
                # ``CancelledError`` branch below instead of leaking past both
                # ``except`` clauses and skipping the ``mark_killed`` transition.
                await self._registry.mark_running(subagent_id)
                if timeout_s is not None:
                    result = await asyncio.wait_for(spec.body(), timeout=timeout_s)
                else:
                    result = await spec.body()
            except TimeoutError:
                run = await self._registry.mark_failed(subagent_id)
                await self._announce(
                    run,
                    None,
                    TimeoutError(f"sub-agent {subagent_id} timed out after {timeout_s}s"),
                )
                return
            except asyncio.CancelledError:
                run = await self._registry.mark_killed(subagent_id)
                await self._announce(run, None, None)
                raise
            except Exception as exc:  # isolate one sub-agent's failure from the supervisor
                run = await self._registry.mark_failed(subagent_id)
                await self._announce(run, None, exc)
                return
            else:
                run = await self._registry.mark_done(subagent_id)
                await self._announce(run, result, None)
        finally:
            self._tasks.pop(subagent_id, None)

    async def kill(self, subagent_id: str, *, cascade: bool = True) -> bool:
        """Cooperatively cancel a run's task; cascades to active level-2 children (D4).

        Args:
            subagent_id (str): Target run id.
            cascade (bool): When ``True`` (default), kill active children first.

        Returns:
            bool: ``True`` if a live task was cancelled; ``False`` when the id
            is unknown to this supervisor or already terminal.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> async def _demo() -> bool:
            ...     registry = SubAgentRegistry()
            ...     supervisor = SubAgentSupervisor(registry)
            ...     async def _work() -> None:
            ...         await asyncio.sleep(10)
            ...     handle = await supervisor.spawn(SubAgentSpec(
            ...         level=1, role="tier_b", body=_work,
            ...         session_id="s", channel="c", task_summary="t",
            ...     ))
            ...     killed = await supervisor.kill(handle.id)
            ...     run = (await registry.snapshot())[0]
            ...     return killed and run.status.value == "killed"
            >>> asyncio.run(_demo())
            True
        """
        task = self._tasks.get(subagent_id)
        if task is None:
            return False
        if cascade:
            children = await self._registry.children_of(subagent_id)
            for child in children:
                if child.status in ACTIVE_STATUSES:
                    await self.kill(child.id, cascade=True)
        if task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # Fallback transition (asyncio edge case): a task cancelled before its
        # coroutine ever gets its first scheduler turn never executes any of
        # ``_run``'s body — not even ``mark_running`` — so the run would
        # otherwise stay stuck at ``pending`` forever. ``_run``'s own
        # ``except CancelledError`` branch already handles the common case
        # (cancelled mid-flight), so this only fires the row was never
        # touched; it is a no-op once ``_run`` already reached a terminal
        # status.
        run = await self._registry.get(subagent_id)
        if run is not None and run.status in ACTIVE_STATUSES:
            run = await self._registry.mark_killed(subagent_id)
            await self._announce(run, None, None)
        return True

    async def kill_all(self, *, role: Role | None = None) -> int:
        """Kill every active level-1 run, optionally scoped to one role (D13).

        Args:
            role (Role | None): Restrict to this role when given.

        Returns:
            int: Number of runs actually cancelled.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> async def _demo() -> int:
            ...     registry = SubAgentRegistry()
            ...     supervisor = SubAgentSupervisor(registry)
            ...     async def _work() -> None:
            ...         await asyncio.sleep(10)
            ...     await supervisor.spawn(SubAgentSpec(
            ...         level=1, role="tier_b", body=_work,
            ...         session_id="s", channel="c", task_summary="t",
            ...     ))
            ...     return await supervisor.kill_all(role="tier_b")
            >>> asyncio.run(_demo())
            1
        """
        active_l1 = await self._registry.running(level=1, role=role)
        count = 0
        for run in active_l1:
            if await self.kill(run.id, cascade=True):
                count += 1
        return count
