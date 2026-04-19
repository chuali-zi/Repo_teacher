from __future__ import annotations

from collections.abc import AsyncIterator

from backend.contracts.dto import ChatSseEvent, AnalysisSseEvent
from backend.contracts.enums import ConversationSubStatus, RuntimeEventType, SessionStatus
from backend.m5_session import session_service
from backend.m5_session.event_mapper import runtime_event_to_sse


async def iter_analysis_events(session_id: str) -> AsyncIterator[AnalysisSseEvent]:
    session = session_service.assert_session_matches(session_id)

    for event in session_service.analysis_reconnect_events(session_id):
        yield runtime_event_to_sse(event)
        if event.event_type in {RuntimeEventType.MESSAGE_COMPLETED, RuntimeEventType.ERROR}:
            return

    if session.status in {SessionStatus.ACCESSING, SessionStatus.ANALYZING}:
        async for event in session_service.run_initial_analysis(session_id):
            yield runtime_event_to_sse(event)
            if event.event_type in {RuntimeEventType.MESSAGE_COMPLETED, RuntimeEventType.ERROR}:
                return


async def iter_chat_events(session_id: str) -> AsyncIterator[ChatSseEvent]:
    session = session_service.assert_session_matches(session_id)

    for event in session_service.chat_reconnect_events(session_id):
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
