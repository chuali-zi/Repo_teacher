# SessionStore：内存 dict[session_id -> SessionState]，create_session / get / drop；进程退出即丢失，第一版无持久化。
from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING
from uuid import uuid4

from ..contracts import AgentStatus, ChatMode
from .session_state import SessionState, default_scratchpad_factory

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from ..memory.scratchpad import Scratchpad


EventBusFactory = Callable[[], "EventBus"]
IdleStatusFactory = Callable[[str], AgentStatus]
ScratchpadFactory = Callable[[], "Scratchpad"]
SessionIdFactory = Callable[[], str]


class SessionStore:
    """
    Process-local in-memory registry for SessionState objects.

    This store deliberately contains no business workflow. It creates the state container,
    returns existing containers, and drops containers. Repository parsing, turn lifecycle,
    status transitions, and event publication stay in their owning modules.
    """

    def __init__(
        self,
        *,
        event_bus_factory: EventBusFactory,
        idle_status_factory: IdleStatusFactory,
        scratchpad_factory: ScratchpadFactory | None = None,
        session_id_factory: SessionIdFactory | None = None,
    ) -> None:
        self._event_bus_factory = event_bus_factory
        self._idle_status_factory = idle_status_factory
        self._scratchpad_factory = scratchpad_factory or default_scratchpad_factory
        self._session_id_factory = session_id_factory or _new_session_id
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        session_id: str | None = None,
        mode: ChatMode = ChatMode.CHAT,
    ) -> SessionState:
        with self._lock:
            normalized_id = self._reserve_session_id(session_id)
            state = SessionState(
                session_id=normalized_id,
                event_bus=self._event_bus_factory(),
                agent_status=self._idle_status_factory(normalized_id),
                mode=mode,
                scratchpad=self._scratchpad_factory(),
            )
            self._sessions[normalized_id] = state
            return state

    def create_session(
        self,
        *,
        session_id: str | None = None,
        mode: ChatMode = ChatMode.CHAT,
    ) -> SessionState:
        return self.create(session_id=session_id, mode=mode)

    def get(self, session_id: str) -> SessionState:
        normalized_id = _normalize_session_id(session_id)
        with self._lock:
            try:
                return self._sessions[normalized_id]
            except KeyError:
                raise KeyError(normalized_id) from None

    def drop(self, session_id: str) -> None:
        normalized_id = _normalize_session_id(session_id)
        with self._lock:
            self._sessions.pop(normalized_id, None)

    def __contains__(self, session_id: object) -> bool:
        if not isinstance(session_id, str):
            return False
        try:
            normalized_id = _normalize_session_id(session_id)
        except ValueError:
            return False
        with self._lock:
            return normalized_id in self._sessions

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _reserve_session_id(self, session_id: str | None) -> str:
        if session_id is not None:
            normalized_id = _normalize_session_id(session_id)
            if normalized_id in self._sessions:
                raise ValueError(f"session already exists: {normalized_id}")
            return normalized_id

        for _ in range(100):
            normalized_id = _normalize_session_id(self._session_id_factory())
            if normalized_id not in self._sessions:
                return normalized_id
        raise RuntimeError("could not allocate a unique session_id")


def _new_session_id() -> str:
    return f"sess_{uuid4().hex[:12]}"


def _normalize_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("session_id must be a non-empty string")
    return normalized


__all__ = [
    "EventBusFactory",
    "IdleStatusFactory",
    "ScratchpadFactory",
    "SessionIdFactory",
    "SessionStore",
]
