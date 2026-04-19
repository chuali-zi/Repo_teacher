from __future__ import annotations

import asyncio

from backend.contracts.domain import (
    AgentActivity,
    DegradationFlag,
    FileTreeSnapshot,
    RuntimeEvent,
    SessionContext,
    UserFacingError,
)
from backend.contracts.enums import (
    AgentActivityPhase,
    ConversationSubStatus,
    DegradationType,
    ErrorCode,
    ProgressStepKey,
    ProgressStepState,
    RuntimeEventType,
    SessionStatus,
)
from backend.m5_session.common import new_id, utc_now
from backend.m5_session.state_machine import assert_sub_status_allowed, assert_transition_allowed


class RuntimeEventService:
    def __init__(self, *, llm_error_builder) -> None:
        self._llm_error_builder = llm_error_builder

    def build_status_snapshot_event(self, session: SessionContext) -> RuntimeEvent:
        return RuntimeEvent(
            event_id=new_id("evt"),
            session_id=session.session_id,
            event_type=RuntimeEventType.STATUS_CHANGED,
            occurred_at=session.updated_at,
            status_snapshot=session.status,
            sub_status_snapshot=session.conversation.sub_status,
        )

    def transition_status(
        self,
        session: SessionContext,
        status: SessionStatus,
        sub_status: ConversationSubStatus | None = None,
    ) -> None:
        assert_transition_allowed(session.status, status)
        session.status = status
        session.conversation.sub_status = sub_status
        assert_sub_status_allowed(session.status, session.conversation.sub_status)
        session.updated_at = utc_now()
        self.append_runtime_event(session, RuntimeEventType.STATUS_CHANGED)

    def set_progress_step(
        self,
        session: SessionContext,
        step_key: ProgressStepKey,
        step_state: ProgressStepState,
        user_notice: str,
        *,
        payload: dict | None = None,
    ) -> RuntimeEvent:
        for item in session.progress_steps:
            if item.step_key == step_key:
                item.step_state = step_state
                break
        session.updated_at = utc_now()
        merged_payload = {
            "progress_steps": [item.model_dump(mode="python") for item in session.progress_steps]
        }
        if payload:
            merged_payload.update(payload)
        return self.append_runtime_event(
            session,
            RuntimeEventType.ANALYSIS_PROGRESS,
            step_key=step_key,
            step_state=step_state,
            user_notice=user_notice,
            payload=merged_payload,
        )

    def append_runtime_event(
        self,
        session: SessionContext,
        event_type: RuntimeEventType,
        *,
        step_key: ProgressStepKey | None = None,
        step_state: ProgressStepState | None = None,
        message_id: str | None = None,
        message_chunk: str | None = None,
        structured_delta: dict | None = None,
        user_notice: str | None = None,
        error: UserFacingError | None = None,
        degradation: DegradationFlag | None = None,
        activity: AgentActivity | None = None,
        payload: dict | None = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            event_id=new_id("evt"),
            session_id=session.session_id,
            event_type=event_type,
            occurred_at=utc_now(),
            status_snapshot=session.status,
            sub_status_snapshot=session.conversation.sub_status,
            step_key=step_key,
            step_state=step_state,
            message_id=message_id,
            message_chunk=message_chunk,
            structured_delta=structured_delta,
            user_notice=user_notice,
            error=error,
            degradation=degradation,
            activity=activity,
            payload=payload,
        )
        session.runtime_events.append(event)
        session.updated_at = event.occurred_at
        return event

    def record_agent_activity(
        self,
        session: SessionContext,
        *,
        phase: str,
        summary: str,
        tool_name: str | None = None,
        tool_arguments: dict | None = None,
        round_index: int | None = None,
        elapsed_ms: int | None = None,
        soft_timed_out: bool = False,
        failed: bool = False,
        retryable: bool = False,
    ) -> RuntimeEvent:
        activity = AgentActivity(
            activity_id=new_id("act"),
            phase=AgentActivityPhase(phase),
            summary=summary,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
            round_index=round_index,
            elapsed_ms=elapsed_ms,
            soft_timed_out=soft_timed_out,
            failed=failed,
            retryable=retryable,
        )
        session.active_agent_activity = activity
        return self.append_runtime_event(
            session,
            RuntimeEventType.AGENT_ACTIVITY,
            activity=activity,
        )

    def fail_chat_turn(self, session: SessionContext, exc: Exception) -> list[RuntimeEvent]:
        start_index = len(session.runtime_events)
        error = self._llm_error_builder(exc)
        session.last_error = error
        session.active_agent_activity = None
        self.transition_status(
            session,
            SessionStatus.CHATTING,
            ConversationSubStatus.WAITING_USER,
        )
        self.append_runtime_event(
            session,
            RuntimeEventType.ERROR,
            error=error,
        )
        return session.runtime_events[start_index:]

    def cancel_chat_turn(
        self,
        session: SessionContext,
        exc: asyncio.CancelledError,
    ) -> list[RuntimeEvent]:
        start_index = len(session.runtime_events)
        error = UserFacingError(
            error_code=ErrorCode.LLM_API_FAILED,
            message="本轮输出连接已中断，请重试。",
            retryable=True,
            stage=SessionStatus.CHATTING,
            input_preserved=True,
            internal_detail=str(exc) or "chat stream cancelled",
        )
        session.last_error = error
        session.active_agent_activity = None
        self.transition_status(
            session,
            SessionStatus.CHATTING,
            ConversationSubStatus.WAITING_USER,
        )
        self.append_runtime_event(
            session,
            RuntimeEventType.ERROR,
            error=error,
        )
        return session.runtime_events[start_index:]

    def maybe_create_degradation(self, file_tree: FileTreeSnapshot) -> DegradationFlag | None:
        if file_tree.repo_size_level == "large":
            return DegradationFlag(
                degradation_id=new_id("deg"),
                type=DegradationType.LARGE_REPO,
                reason="source_code_file_count > 3000",
                user_notice="仓库较大，优先输出结构总览和阅读起点。",
                started_at=utc_now(),
            )
        if file_tree.primary_language != "Python":
            return DegradationFlag(
                degradation_id=new_id("deg"),
                type=DegradationType.NON_PYTHON_REPO,
                reason="primary_language != Python",
                user_notice="当前仓库不是 Python 主仓库，仅提供保守结构说明。",
                started_at=utc_now(),
            )
        return None
