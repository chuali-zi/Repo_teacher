"""Construct public SSE event contracts for one session."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ..contracts import (
    AgentStatus,
    AgentStatusEvent,
    AnswerStreamDeltaEvent,
    AnswerStreamEndEvent,
    AnswerStreamStartEvent,
    ApiError,
    ChatMessage,
    ChatMode,
    DeepResearchProgressEvent,
    ErrorEvent,
    MessageCompletedEvent,
    ParseLogLine,
    RepoConnectedEvent,
    RepoParseLogEvent,
    RepositorySummary,
    RunCancelledEvent,
    SseEventType,
    TeachingCodeEvent,
    TeachingCodeSnippet,
)


def make_event_id() -> str:
    return f"evt_{uuid4().hex[:12]}"


def now_utc() -> datetime:
    return datetime.now(UTC)


def agent_status_event(*, session_id: str, status: AgentStatus) -> AgentStatusEvent:
    return AgentStatusEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.AGENT_STATUS),
        status=status,
    )


def repo_parse_log_event(*, session_id: str, log: ParseLogLine) -> RepoParseLogEvent:
    return RepoParseLogEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.REPO_PARSE_LOG),
        log=log,
    )


def repo_connected_event(
    *,
    session_id: str,
    repository: RepositorySummary,
    initial_message: str,
    current_code: TeachingCodeSnippet | None = None,
) -> RepoConnectedEvent:
    return RepoConnectedEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.REPO_CONNECTED),
        repository=repository,
        initial_message=initial_message,
        current_code=current_code,
    )


def teaching_code_event(
    *,
    session_id: str,
    snippet: TeachingCodeSnippet,
) -> TeachingCodeEvent:
    return TeachingCodeEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.TEACHING_CODE),
        snippet=snippet,
    )


def answer_stream_start_event(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    mode: ChatMode,
) -> AnswerStreamStartEvent:
    return AnswerStreamStartEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.ANSWER_STREAM_START),
        turn_id=turn_id,
        message_id=message_id,
        mode=mode,
    )


def answer_stream_delta_event(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    delta_text: str,
) -> AnswerStreamDeltaEvent:
    return AnswerStreamDeltaEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.ANSWER_STREAM_DELTA),
        turn_id=turn_id,
        message_id=message_id,
        delta_text=delta_text,
    )


def answer_stream_end_event(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
) -> AnswerStreamEndEvent:
    return AnswerStreamEndEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.ANSWER_STREAM_END),
        turn_id=turn_id,
        message_id=message_id,
    )


def message_completed_event(
    *,
    session_id: str,
    message: ChatMessage,
    agent_status: AgentStatus | None = None,
    current_code: TeachingCodeSnippet | None = None,
) -> MessageCompletedEvent:
    return MessageCompletedEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.MESSAGE_COMPLETED),
        message=message,
        agent_status=agent_status,
        current_code=current_code,
    )


def deep_research_progress_event(
    *,
    session_id: str,
    turn_id: str,
    phase: str,
    summary: str,
    completed_units: int = 0,
    total_units: int = 0,
    current_target: str | None = None,
) -> DeepResearchProgressEvent:
    return DeepResearchProgressEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.DEEP_RESEARCH_PROGRESS),
        turn_id=turn_id,
        phase=phase,
        summary=summary,
        completed_units=completed_units,
        total_units=total_units,
        current_target=current_target,
    )


def run_cancelled_event(
    *,
    session_id: str,
    agent_status: AgentStatus,
    turn_id: str | None = None,
) -> RunCancelledEvent:
    return RunCancelledEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.RUN_CANCELLED),
        turn_id=turn_id,
        agent_status=agent_status,
    )


def error_event(
    *,
    session_id: str,
    error: ApiError,
    agent_status: AgentStatus | None = None,
) -> ErrorEvent:
    return ErrorEvent(
        **_event_base(session_id=session_id, event_type=SseEventType.ERROR),
        error=error,
        agent_status=agent_status,
    )


class EventFactory:
    """Stateless wrapper for dependency injection sites that expect an object."""

    __slots__ = ()

    make_event_id = staticmethod(make_event_id)
    now_utc = staticmethod(now_utc)
    agent_status_event = staticmethod(agent_status_event)
    repo_parse_log_event = staticmethod(repo_parse_log_event)
    repo_connected_event = staticmethod(repo_connected_event)
    teaching_code_event = staticmethod(teaching_code_event)
    answer_stream_start_event = staticmethod(answer_stream_start_event)
    answer_stream_delta_event = staticmethod(answer_stream_delta_event)
    answer_stream_end_event = staticmethod(answer_stream_end_event)
    message_completed_event = staticmethod(message_completed_event)
    deep_research_progress_event = staticmethod(deep_research_progress_event)
    run_cancelled_event = staticmethod(run_cancelled_event)
    error_event = staticmethod(error_event)


def _event_base(*, session_id: str, event_type: SseEventType) -> dict[str, object]:
    return {
        "event_id": make_event_id(),
        "event_type": event_type,
        "session_id": session_id,
        "occurred_at": now_utc(),
    }


__all__ = [
    "EventFactory",
    "agent_status_event",
    "answer_stream_delta_event",
    "answer_stream_end_event",
    "answer_stream_start_event",
    "deep_research_progress_event",
    "error_event",
    "make_event_id",
    "message_completed_event",
    "now_utc",
    "repo_connected_event",
    "repo_parse_log_event",
    "run_cancelled_event",
    "teaching_code_event",
]
