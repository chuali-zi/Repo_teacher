from __future__ import annotations

from collections.abc import Callable

from backend.contracts.domain import RuntimeEvent, SessionContext, SessionStore, TempResourceSet
from backend.contracts.enums import ErrorCode, MessageType, RuntimeEventType, SessionStatus
from backend.contracts.domain import UserFacingError, UserFacingErrorException


class SessionRepository:
    def __init__(
        self,
        *,
        store: SessionStore,
        cleanup_temp_resources: Callable[[TempResourceSet], None],
    ) -> None:
        self.store = store
        self._cleanup_temp_resources = cleanup_temp_resources

    def require(
        self,
        session_id: str | None,
        *,
        allow_missing: bool = False,
    ) -> SessionContext:
        session = self.store.active_session
        if session is None:
            raise UserFacingErrorException(
                UserFacingError(
                    error_code=ErrorCode.INVALID_STATE,
                    message="当前没有活跃会话。",
                    retryable=True,
                    stage=SessionStatus.IDLE,
                    input_preserved=True,
                )
            )
        if session_id is None and allow_missing:
            return session
        if session_id != session.session_id:
            raise UserFacingErrorException(
                UserFacingError(
                    error_code=ErrorCode.INVALID_STATE,
                    message="会话已失效，请刷新后重试。",
                    retryable=True,
                    stage=session.status,
                    input_preserved=True,
                )
            )
        return session

    def set_active(self, session: SessionContext) -> None:
        self.store.active_session = session

    def clear_active(self) -> None:
        active = self.store.active_session
        if active and active.temp_resources and active.temp_resources.cleanup_required:
            self._cleanup_temp_resources(active.temp_resources)
        self.store.active_session = None

    def latest_runtime_event(
        self,
        session_id: str,
        event_type: RuntimeEventType,
    ) -> RuntimeEvent | None:
        session = self.require(session_id)
        for event in reversed(session.runtime_events):
            if event.event_type == event_type:
                return event
        return None

    def latest_initial_report_completed_event(self, session_id: str) -> RuntimeEvent | None:
        session = self.require(session_id)
        for event in reversed(session.runtime_events):
            if event.event_type != RuntimeEventType.MESSAGE_COMPLETED or not event.payload:
                continue
            payload = event.payload.get("message")
            if payload and payload.get("message_type") == MessageType.INITIAL_REPORT:
                return event
        return None

    def latest_chat_terminal_event(self, session_id: str) -> RuntimeEvent | None:
        session = self.require(session_id)
        for event in reversed(session.runtime_events):
            if event.event_type == RuntimeEventType.ERROR:
                return event
            if event.event_type != RuntimeEventType.MESSAGE_COMPLETED or not event.payload:
                continue
            payload = event.payload.get("message")
            if payload and payload.get("message_type") in {
                MessageType.AGENT_ANSWER,
                MessageType.GOAL_SWITCH_CONFIRMATION,
                MessageType.STAGE_SUMMARY,
                MessageType.ERROR,
            }:
                return event
        return None
