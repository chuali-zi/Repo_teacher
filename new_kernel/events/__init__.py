"""Events package: SSE contract construction and per-session fan-out."""

from __future__ import annotations

from typing import Protocol

from ..contracts import RepoTutorSseEvent
from .agent_status_tracker import AgentStatusTracker
from .event_bus import EventBus, EventSubscription
from .event_factory import (
    EventFactory,
    agent_status_event,
    answer_stream_delta_event,
    answer_stream_end_event,
    answer_stream_start_event,
    deep_research_progress_event,
    error_event,
    make_event_id,
    message_completed_event,
    now_utc,
    repo_connected_event,
    repo_parse_log_event,
    run_cancelled_event,
    teaching_code_event,
)


class EventSink(Protocol):
    async def emit(self, event: RepoTutorSseEvent) -> None:
        ...


__all__ = [
    "AgentStatusTracker",
    "EventBus",
    "EventFactory",
    "EventSink",
    "EventSubscription",
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
