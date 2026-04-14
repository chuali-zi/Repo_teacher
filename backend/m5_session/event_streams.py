from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

from backend.contracts.dto import ChatSseEvent, AnalysisSseEvent
from backend.contracts.enums import ConversationSubStatus, RuntimeEventType, SessionStatus
from backend.m5_session import session_service
from backend.m5_session.event_mapper import runtime_event_to_sse


async def iter_analysis_events(session_id: str) -> AsyncIterator[AnalysisSseEvent]:
    session = session_service.assert_session_matches(session_id)

    for event in _analysis_reconnect_events(session_id):
        yield runtime_event_to_sse(event)
        if event.event_type in {RuntimeEventType.MESSAGE_COMPLETED, RuntimeEventType.ERROR}:
            return

    if session.status in {SessionStatus.ACCESSING, SessionStatus.ANALYZING}:
        for event in await session_service.run_initial_analysis(session_id):
            yield runtime_event_to_sse(event)
            if event.event_type in {RuntimeEventType.MESSAGE_COMPLETED, RuntimeEventType.ERROR}:
                return


async def iter_chat_events(session_id: str) -> AsyncIterator[ChatSseEvent]:
    session = session_service.assert_session_matches(session_id)

    for event in _chat_reconnect_events(session_id):
        yield runtime_event_to_sse(event)
        if event.event_type in {RuntimeEventType.MESSAGE_COMPLETED, RuntimeEventType.ERROR}:
            return

    if (
        session.status == SessionStatus.CHATTING
        and session.conversation.sub_status == ConversationSubStatus.AGENT_THINKING
    ):
        async for event in session_service.run_chat_turn(session_id):
            yield runtime_event_to_sse(event)
            if event.event_type in {RuntimeEventType.MESSAGE_COMPLETED, RuntimeEventType.ERROR}:
                return


def _analysis_reconnect_events(session_id: str) -> list:
    session = session_service.assert_session_matches(session_id)
    events = [session_service.build_status_snapshot_event(session)]

    latest_progress = session_service.latest_runtime_event(
        session_id,
        RuntimeEventType.ANALYSIS_PROGRESS,
    )
    if latest_progress is not None:
        events.append(latest_progress)

    if session.status == SessionStatus.CHATTING:
        final_event = session_service.latest_initial_report_completed_event(session_id)
        if final_event is not None:
            events.append(final_event)
    elif session.status in {SessionStatus.ACCESS_ERROR, SessionStatus.ANALYSIS_ERROR}:
        error_event = session_service.latest_runtime_event(session_id, RuntimeEventType.ERROR)
        if error_event is not None:
            events.append(error_event)

    return _dedupe_by_event_id(events)


def _chat_reconnect_events(session_id: str) -> list:
    session = session_service.assert_session_matches(session_id)
    events = [session_service.build_status_snapshot_event(session)]
    if (
        session.status == SessionStatus.CHATTING
        and session.conversation.sub_status != ConversationSubStatus.WAITING_USER
    ):
        return _dedupe_by_event_id(events)

    final_event = session_service.latest_chat_terminal_event(session_id)
    if final_event is not None:
        events.append(final_event)
    return _dedupe_by_event_id(events)


def _dedupe_by_event_id(events: Iterable) -> list:
    deduped = []
    seen: set[str] = set()
    for event in events:
        if event is None or event.event_id in seen:
            continue
        seen.add(event.event_id)
        deduped.append(event)
    return deduped
