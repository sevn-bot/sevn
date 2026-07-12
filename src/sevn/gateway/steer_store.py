"""Session-scoped ``/steer`` buffer for gateway agent glue (`specs/17-gateway.md` Wave 7).

Module: sevn.gateway.steer_store
Depends: sevn.config.workspace_config
Exports:
    SteerEnqueueResult — enqueue outcome for dispatcher ack copy.
    SessionBoundSteerInject — session-scoped ``SteerInject`` façade.
    SessionSteerStore — per-session steer queue + inject factory.
    owner_user_ids_from_workspace — Telegram allowlist → owner frozenset.
    parse_steer_command_text — extract payload from ``/steer`` bypass text.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock

from sevn.config.workspace_config import WorkspaceConfig

DEFAULT_STEER_MAX_PENDING = 8


@dataclass(frozen=True)
class SteerEnqueueResult:
    """Outcome of enqueueing one owner ``/steer`` line."""

    accepted: bool
    buffer_full: bool = False


class SessionBoundSteerInject:
    """Session-scoped steer buffer matching ``SteerInject.pop_pending`` (§4.5)."""

    pending_text: str | None = None

    def __init__(self, store: SessionSteerStore, session_id: str) -> None:
        """Bind one session id to a shared store.
        Args:
            store (SessionSteerStore): Owning gateway buffer.
            session_id (str): Durable session key.
        Examples:
            >>> store = SessionSteerStore(max_pending=2)
            >>> SessionBoundSteerInject(store, "s1") is not None
            True
        """
        self._store = store
        self._session_id = session_id

    def pop_pending(self) -> str | None:
        """Remove and return the next queued steer chunk for this session.
        Returns:
            str | None: Buffered steer text, or ``None`` when the queue is empty.
        Examples:
            >>> store = SessionSteerStore(max_pending=2)
            >>> store.enqueue("s1", "nudge")
            SteerEnqueueResult(accepted=True, buffer_full=False)
            >>> inj = SessionBoundSteerInject(store, "s1")
            >>> inj.pop_pending()
            'nudge'
            >>> inj.pop_pending() is None
            True
        """
        return self._store._pop_pending(self._session_id)

    def inject_pending(self, text: str) -> None:
        """Enqueue one programmatic steer line for the next LLM-boundary pop.
        Args:
            text (str): Steer payload (ignored when blank after strip).
        Examples:
            >>> store = SessionSteerStore(max_pending=2)
            >>> inj = SessionBoundSteerInject(store, "s1")
            >>> inj.inject_pending("call `serp` now")
            >>> inj.pop_pending()
            'call `serp` now'
        """
        chunk = text.strip()
        if chunk:
            self._store.enqueue(self._session_id, chunk)


class SessionSteerStore:
    """In-memory bounded ``/steer`` queue keyed by gateway ``session_id``."""

    def __init__(self, *, max_pending: int = DEFAULT_STEER_MAX_PENDING) -> None:
        """Create an empty store.
        Args:
            max_pending (int): Maximum queued steer lines per session.
        Examples:
            >>> SessionSteerStore(max_pending=4).max_pending
            4
        """
        self.max_pending = max(1, int(max_pending))
        self._lock = Lock()
        self._queues: dict[str, deque[str]] = {}
        self._injections: dict[str, SessionBoundSteerInject] = {}

    @classmethod
    def from_workspace(cls, workspace: WorkspaceConfig) -> SessionSteerStore:
        """Build a store using ``gateway.steer.max_pending`` when configured.
        Args:
            workspace (WorkspaceConfig): Parsed ``sevn.json``.
        Returns:
            SessionSteerStore: Store sized from workspace or template default.
        Examples:
            >>> SessionSteerStore.from_workspace(WorkspaceConfig.minimal()).max_pending
            8
        """
        max_p = DEFAULT_STEER_MAX_PENDING
        gw = workspace.gateway
        if gw is not None and gw.steer is not None and gw.steer.max_pending is not None:
            max_p = int(gw.steer.max_pending)
        return cls(max_pending=max_p)

    def enqueue(self, session_id: str, text: str) -> SteerEnqueueResult:
        """Append one owner steer line for ``session_id``.
        Args:
            session_id (str): Durable gateway session id.
            text (str): Steer payload (non-empty after strip).
        Returns:
            SteerEnqueueResult: Whether the line was accepted.
        Examples:
            >>> s = SessionSteerStore(max_pending=1)
            >>> s.enqueue("s1", "  go left  ")
            SteerEnqueueResult(accepted=True, buffer_full=False)
            >>> s.enqueue("s1", "again")
            SteerEnqueueResult(accepted=False, buffer_full=True)
        """
        chunk = text.strip()
        if not chunk:
            return SteerEnqueueResult(accepted=False)
        with self._lock:
            queue = self._queues.setdefault(session_id, deque())
            if len(queue) >= self.max_pending:
                return SteerEnqueueResult(accepted=False, buffer_full=True)
            queue.append(chunk)
            return SteerEnqueueResult(accepted=True)

    def steer_inject_for(self, session_id: str) -> SessionBoundSteerInject:
        """Return the session-bound ``SteerInject`` façade for executor glue.
        Args:
            session_id (str): Durable gateway session id.
        Returns:
            SessionBoundSteerInject: Shared inject object for one dispatch turn.
        Examples:
            >>> s = SessionSteerStore()
            >>> s.steer_inject_for("s1") is s.steer_inject_for("s1")
            True
        """
        with self._lock:
            existing = self._injections.get(session_id)
            if existing is not None:
                return existing
            inject = SessionBoundSteerInject(self, session_id)
            self._injections[session_id] = inject
            return inject

    def pending_count(self, session_id: str) -> int:
        """Return queued steer line count for diagnostics and tests.
        Args:
            session_id (str): Durable gateway session id.
        Returns:
            int: Number of lines waiting for LLM-boundary injection.
        Examples:
            >>> s = SessionSteerStore()
            >>> s.enqueue("s1", "a")
            SteerEnqueueResult(accepted=True, buffer_full=False)
            >>> s.pending_count("s1")
            1
        """
        with self._lock:
            queue = self._queues.get(session_id)
            return len(queue) if queue is not None else 0

    def _pop_pending(self, session_id: str) -> str | None:
        """Pop the next queued steer line (internal; used by ``SessionBoundSteerInject``).
        Args:
            session_id (str): Durable gateway session id.
        Returns:
            str | None: Next steer chunk, or ``None`` when the queue is empty.
        Examples:
            >>> s = SessionSteerStore()
            >>> s.enqueue("s1", "nudge")
            SteerEnqueueResult(accepted=True, buffer_full=False)
            >>> s._pop_pending("s1")
            'nudge'
        """
        with self._lock:
            queue = self._queues.get(session_id)
            if queue is None or not queue:
                return None
            return queue.popleft()


def parse_steer_command_text(raw: str) -> str | None:
    """Extract steer payload from a ``/steer`` bypass command string.
    Args:
        raw (str): Inbound message text.
    Returns:
        str | None: Payload after ``/steer``, or ``None`` when missing/empty.
    Examples:
        >>> parse_steer_command_text("/steer skip migration")
        'skip migration'
        >>> parse_steer_command_text("/steer") is None
        True
    """
    text = raw.strip()
    if text == "/steer":
        return None
    if text.startswith("/steer "):
        body = text[len("/steer ") :].strip()
        return body or None
    return None


def owner_user_ids_from_workspace(workspace: WorkspaceConfig) -> frozenset[str]:
    """Map Telegram ``allowed_users`` to gateway owner ids for ``/steer``.
    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
    Returns:
        frozenset[str]: Stringified Telegram user ids, or empty when unset.
    Examples:
        >>> owner_user_ids_from_workspace(WorkspaceConfig.minimal())
        frozenset()
    """
    ch = workspace.channels
    if ch is None or ch.telegram is None or not ch.telegram.allowed_users:
        return frozenset()
    return frozenset(str(int(x)) for x in ch.telegram.allowed_users)
