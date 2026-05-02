"""Track and broadcast the current AgentStatus for one session."""

from __future__ import annotations

from typing import Literal, Protocol

from ..contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    RepoTutorSseEvent,
)
from .event_factory import agent_status_event, now_utc


PetMood = Literal["idle", "think", "act", "scan", "teach", "research", "error"]


class _EventSink(Protocol):
    async def emit(self, event: RepoTutorSseEvent) -> None:
        ...


class AgentStatusTracker:
    """Owns a session-local AgentStatus value and emits status events on change."""

    def __init__(
        self,
        *,
        session_id: str,
        sink: _EventSink,
        initial_status: AgentStatus | None = None,
    ) -> None:
        self._session_id = _normalize_session_id(session_id)
        self._sink = sink
        self._current = initial_status or _idle_status(self._session_id)
        if self._current.session_id != self._session_id:
            raise ValueError("initial_status.session_id must match session_id")

    @property
    def current(self) -> AgentStatus:
        return self._current

    async def update_phase(
        self,
        *,
        state: AgentPetState,
        phase: AgentPhase,
        label: str,
        pet_mood: PetMood,
        pet_message: str,
        current_action: str | None = None,
        current_target: str | None = None,
        emit: bool = True,
    ) -> AgentStatus:
        status = AgentStatus(
            session_id=self._session_id,
            state=state,
            phase=phase,
            label=label,
            pet_mood=pet_mood,
            pet_message=pet_message,
            current_action=current_action,
            current_target=current_target,
            metrics=self._current.metrics,
            updated_at=now_utc(),
        )
        self._current = status
        if emit:
            await self._sink.emit(agent_status_event(session_id=self._session_id, status=status))
        return status

    async def add_metrics(
        self,
        *,
        llm_call: int = 0,
        tool_call: int = 0,
        tokens: int = 0,
        elapsed_ms: int = 0,
        emit: bool = False,
    ) -> AgentStatus:
        metrics = AgentMetrics(
            llm_call_count=self._current.metrics.llm_call_count + llm_call,
            tool_call_count=self._current.metrics.tool_call_count + tool_call,
            token_count=self._current.metrics.token_count + tokens,
            elapsed_ms=self._current.metrics.elapsed_ms + elapsed_ms,
        )
        status = self._current.model_copy(update={"metrics": metrics, "updated_at": now_utc()})
        self._current = status
        if emit:
            await self._sink.emit(agent_status_event(session_id=self._session_id, status=status))
        return status

    async def update_metrics(
        self,
        *,
        llm_call: int = 0,
        tool_call: int = 0,
        tokens: int = 0,
        elapsed_ms: int = 0,
        emit: bool = False,
    ) -> AgentStatus:
        return await self.add_metrics(
            llm_call=llm_call,
            tool_call=tool_call,
            tokens=tokens,
            elapsed_ms=elapsed_ms,
            emit=emit,
        )


def _idle_status(session_id: str) -> AgentStatus:
    return AgentStatus(
        session_id=session_id,
        state=AgentPetState.IDLE,
        phase=AgentPhase.IDLE,
        label="待机中",
        pet_mood="idle",
        pet_message="等待你的问题",
        current_action=None,
        current_target=None,
        metrics=AgentMetrics(),
        updated_at=now_utc(),
    )


def _normalize_session_id(session_id: str) -> str:
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("session_id must be a non-empty string")
    return normalized


__all__ = ["AgentStatusTracker", "PetMood"]
