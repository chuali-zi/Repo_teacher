from __future__ import annotations

from backend.contracts.domain import MessageRecord, RuntimeEvent
from backend.contracts.dto import (
    AgentActivityDto,
    AgentActivityEvent,
    AnalysisProgressEvent,
    AnswerStreamDeltaEvent,
    AnswerStreamEndEvent,
    AnswerStreamStartEvent,
    DegradationFlagDto,
    DegradationNoticeEvent,
    ErrorEvent,
    MessageCompletedEvent,
    MessageDto,
    MessageErrorStateDto,
    StatusChangedEvent,
    StructuredMessageContentDto,
    SuggestionDto,
    SseEventDto,
    UserFacingErrorDto,
)
from backend.contracts.enums import RuntimeEventType
from backend.m5_session.state_machine import view_for_status


def runtime_event_to_sse(event: RuntimeEvent) -> SseEventDto:
    if event.event_type == RuntimeEventType.STATUS_CHANGED:
        return StatusChangedEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            status=event.status_snapshot,
            sub_status=event.sub_status_snapshot,
            view=view_for_status(event.status_snapshot, event.sub_status_snapshot),
        )

    if event.event_type == RuntimeEventType.ANALYSIS_PROGRESS:
        return AnalysisProgressEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            step_key=event.step_key,
            step_state=event.step_state,
            user_notice=event.user_notice or "",
            progress_steps=list(event.payload.get("progress_steps", [])) if event.payload else [],
        )

    if event.event_type == RuntimeEventType.DEGRADATION_NOTICE:
        degradation = event.degradation
        return DegradationNoticeEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            degradation=DegradationFlagDto(
                degradation_id=degradation.degradation_id,
                type=degradation.type,
                reason=degradation.reason,
                user_notice=degradation.user_notice,
                related_paths=degradation.related_paths,
            ),
        )

    if event.event_type == RuntimeEventType.AGENT_ACTIVITY:
        activity = event.activity
        return AgentActivityEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            activity=AgentActivityDto.model_validate(activity.model_dump(mode="python")),
        )

    if event.event_type == RuntimeEventType.ANSWER_STREAM_START:
        return AnswerStreamStartEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            message_id=event.message_id,
            message_type=event.payload["message_type"],
        )

    if event.event_type == RuntimeEventType.ANSWER_STREAM_DELTA:
        return AnswerStreamDeltaEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            message_id=event.message_id,
            delta_text=event.message_chunk or "",
            structured_delta=event.structured_delta,
        )

    if event.event_type == RuntimeEventType.ANSWER_STREAM_END:
        return AnswerStreamEndEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            message_id=event.message_id,
        )

    if event.event_type == RuntimeEventType.MESSAGE_COMPLETED:
        message = MessageRecord.model_validate(event.payload["message"])
        return MessageCompletedEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            message=_message_dto(message),
            status=event.status_snapshot,
            sub_status=event.sub_status_snapshot,
            view=view_for_status(event.status_snapshot, event.sub_status_snapshot),
        )

    if event.event_type == RuntimeEventType.ERROR:
        return ErrorEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            error=UserFacingErrorDto.from_domain(event.error),
            status=event.status_snapshot,
            sub_status=event.sub_status_snapshot,
            view=view_for_status(event.status_snapshot, event.sub_status_snapshot),
        )

    raise ValueError(f"Unsupported runtime event type: {event.event_type}")


def _message_dto(message: MessageRecord) -> MessageDto:
    return MessageDto(
        message_id=message.message_id,
        role=message.role,
        message_type=message.message_type,
        created_at=message.created_at,
        raw_text=message.raw_text,
        structured_content=(
            StructuredMessageContentDto.model_validate(
                message.structured_content.model_dump(mode="python")
            )
            if message.structured_content
            else None
        ),
        initial_report_content=(
            message.initial_report_content.model_dump(mode="python")
            if message.initial_report_content
            else None
        ),
        related_goal=message.related_goal,
        suggestions=[
            SuggestionDto.model_validate(item.model_dump(mode="python"))
            for item in message.suggestions
        ],
        streaming_complete=message.streaming_complete,
        error_state=(
            MessageErrorStateDto(
                error=UserFacingErrorDto.from_domain(message.error_state.error),
                failed_during_stream=message.error_state.failed_during_stream,
                partial_text_available=message.error_state.partial_text_available,
            )
            if message.error_state
            else None
        ),
    )
